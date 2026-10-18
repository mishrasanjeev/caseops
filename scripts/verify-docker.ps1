#Requires -Version 5.1

[CmdletBinding(PositionalBinding=$false)]
param(
    [switch]$KeepRunning,
    [switch]$SkipBuild,
    [switch]$PreCommit,
    [ValidatePattern('^[0-9.]+/[0-9]{1,2}$')]
    [string]$NetworkSubnet,
    [ValidatePattern('^[0-9.]+/[0-9]{1,2}$')]
    [string]$WorkerNetworkSubnet,
    [string]$ResultsDirectory,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PlaywrightArgs = @()
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
$ApiDir = Join-Path $RepoRoot "apps\api"
$ApiPython = Join-Path $ApiDir ".venv\Scripts\python.exe"
$TestApiProxyScript = Join-Path $RepoRoot "scripts\docker-acceptance-api-proxy.mjs"
# Browser acceptance must use the candidate's own config, specs and installed
# Playwright. A relative --config or npx lookup follows the caller's working
# directory, which on 2026-09-28 silently ran another checkout's browser suite.
$PlaywrightConfig = Join-Path $RepoRoot "playwright.docker.config.ts"
$PlaywrightCli = Join-Path $RepoRoot "node_modules\@playwright\test\cli.js"
$TestApiProxyProcess = $null
$TestApiProxyStdout = $null
$TestApiProxyStderr = $null
$FailureEvidenceAttempted = $false
if (-not $ResultsDirectory) {
    $ResultsDirectory = Join-Path $RepoRoot (".tmp\docker-acceptance\" + [Guid]::NewGuid().ToString("N"))
}
$ResultsDirectory = [IO.Path]::GetFullPath($ResultsDirectory)
New-Item -ItemType Directory -Path $ResultsDirectory -Force | Out-Null
Write-Host "[docker-acceptance] retained reports: $ResultsDirectory"

function Get-WorkingTreeFingerprint {
    $Entries = @{}
    foreach ($Line in @(& git -C $RepoRoot ls-files --stage)) {
        if ($Line -notmatch "^[0-9]+ ([0-9a-f]{40}) 0`t(.+)$") { continue }
        $Entries[$Matches[2]] = $Matches[1]
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not read the candidate Git index." }
    $ChangedPaths = @(
        & git -C $RepoRoot ls-files --modified --others --exclude-standard
    )
    if ($LASTEXITCODE -ne 0) { throw "Could not enumerate changed candidate files." }
    foreach ($RelativePath in ($ChangedPaths | Sort-Object -Unique)) {
        $AbsolutePath = Join-Path $RepoRoot $RelativePath
        if (-not (Test-Path -LiteralPath $AbsolutePath -PathType Leaf)) { continue }
        $BlobHash = ((& git -C $RepoRoot hash-object -- $RelativePath | Out-String).Trim())
        if ($LASTEXITCODE -ne 0 -or $BlobHash -notmatch "^[0-9a-f]{40}$") {
            throw "Could not fingerprint $RelativePath."
        }
        $Entries[$RelativePath] = $BlobHash
    }
    foreach ($RelativePath in @(& git -C $RepoRoot ls-files --deleted)) {
        $Entries[$RelativePath] = "DELETED"
    }
    $Records = foreach ($RelativePath in ($Entries.Keys | Sort-Object)) {
        "$RelativePath`0$($Entries[$RelativePath])"
    }
    $Bytes = [Text.Encoding]::UTF8.GetBytes(($Records -join "`n"))
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try {
        return -join ($Hasher.ComputeHash($Bytes) | ForEach-Object { $_.ToString("x2") })
    }
    finally {
        $Hasher.Dispose()
    }
}

function Test-TcpPortBlockAvailable {
    param(
        [Parameter(Mandatory=$true)]
        [int]$BasePort
    )

    $Listeners = @()
    try {
        foreach ($Offset in 0..4) {
            $Listener = [Net.Sockets.TcpListener]::new(
                [Net.IPAddress]::Loopback,
                $BasePort + $Offset
            )
            $Listener.ExclusiveAddressUse = $true
            $Listener.Start()
            $Listeners += $Listener
        }
        return $true
    }
    catch [Net.Sockets.SocketException] {
        # Windows excluded ranges and an existing listener both surface here.
        return $false
    }
    finally {
        foreach ($Listener in $Listeners) {
            $Listener.Stop()
        }
    }
}

function Get-AvailablePortBase {
    param(
        [Parameter(Mandatory=$true)]
        [int]$InitialBlock
    )

    foreach ($ProbeOffset in 0..5999) {
        $CandidateBlock = ($InitialBlock + $ProbeOffset) % 6000
        $CandidateBase = 20000 + ($CandidateBlock * 5)
        if (Test-TcpPortBlockAvailable -BasePort $CandidateBase) {
            return $CandidateBase
        }
    }
    throw "No available five-port Docker acceptance block exists between 20000 and 49999."
}

$SourceFingerprint = Get-WorkingTreeFingerprint
$ReleaseSha = if ($PreCommit) {
    # Runtime release endpoints deliberately accept only exact Git-shaped revisions.
    $SourceFingerprint.Substring(0, 40)
} else {
    ((& git -C $RepoRoot rev-parse HEAD | Out-String).Trim())
}
if (
    $LASTEXITCODE -ne 0 `
    -or $ReleaseSha -notmatch "^[0-9a-f]{40}$" `
    -or ($PreCommit -and $SourceFingerprint -notmatch "^[0-9a-f]{64}$")
) {
    throw "Could not resolve the exact candidate source identity."
}

# A release identity is shared across agents; the Compose project owns mutable
# containers and volumes, so each invocation needs its own namespace.
$RunNonce = [Guid]::NewGuid().ToString("N").Substring(0, 12)
$ComposeProject = "caseops-acceptance-$($ReleaseSha.Substring(0, 12))-$RunNonce"
$PortBlock = [Convert]::ToInt32($RunNonce.Substring(0, 6), 16) % 6000
$PreferredPortBase = 20000 + ($PortBlock * 5)
$PortBase = Get-AvailablePortBase -InitialBlock $PortBlock
$ApiPort = ($PortBase + 0).ToString()
$TestApiPort = ($PortBase + 1).ToString()
$WebPort = ($PortBase + 2).ToString()
$PostgresPort = ($PortBase + 3).ToString()
$ValkeyPort = ($PortBase + 4).ToString()

$DirtyContext = ((& git -C $RepoRoot status --porcelain --untracked-files=all -- apps/api apps/web docker-compose.yml package.json package-lock.json .nvmrc .dockerignore .gcloudignore playwright.app.config.ts playwright.docker.config.ts tests/e2e/support/oauth scripts/docker-acceptance-api-proxy.mjs scripts/verify-docker.ps1 | Out-String).Trim())
if ($DirtyContext -and -not $PreCommit) {
    throw "Docker acceptance requires a committed, clean build context. Commit the candidate first.`n$DirtyContext"
}

function Assert-CandidateSourceUnchanged {
    param([Parameter(Mandatory=$true)][string]$Stage)

    if ((Get-WorkingTreeFingerprint) -ne $SourceFingerprint) {
        throw "Candidate source changed $Stage. Rebuild and rerun acceptance for the new source; this run cannot certify it."
    }
    if (-not $PreCommit) {
        $CurrentHead = ((& git -C $RepoRoot rev-parse HEAD | Out-String).Trim())
        if ($LASTEXITCODE -ne 0 -or $CurrentHead -ne $ReleaseSha) {
            throw "Candidate commit changed $Stage. Rebuild the current canonical candidate."
        }
    }
}

function Assert-CandidateDataClassProjection {
    $ProjectionArguments = @(
        (Join-Path $RepoRoot "scripts\ip_data_class_projection.py")
        "validate"
    )
    & $ApiPython @ProjectionArguments
    $ProjectionExitCode = $LASTEXITCODE
    if ($ProjectionExitCode -ne 0) {
        throw "Candidate data-class projection validation failed (exit $ProjectionExitCode). Regenerate and commit the reviewed projection before Docker acceptance."
    }
}

function Test-PathWithinRoot {
    param(
        [Parameter(Mandatory=$true)][AllowEmptyString()][string]$Path,
        [Parameter(Mandatory=$true)][string]$Root
    )

    if (-not $Path -or -not [IO.Path]::IsPathRooted($Path)) { return $false }
    $Separators = [char[]]@([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    $FullRoot = [IO.Path]::GetFullPath($Root).TrimEnd($Separators) + [IO.Path]::DirectorySeparatorChar
    $FullPath = [IO.Path]::GetFullPath($Path)
    $Comparison = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
        [StringComparison]::OrdinalIgnoreCase
    } else {
        [StringComparison]::Ordinal
    }
    return $FullPath.StartsWith($FullRoot, $Comparison)
}

function Assert-CandidatePlaywrightSuite {
    param([string[]]$Arguments = @())

    if (@($Arguments | Where-Object { $_ -match "^--reporter(?:=|$)" }).Count) {
        throw "Docker acceptance owns its structured Playwright reporters."
    }
    if (-not (Test-Path -LiteralPath $PlaywrightConfig -PathType Leaf)) {
        throw "Candidate Playwright config is missing: $PlaywrightConfig"
    }
    if (-not (Test-Path -LiteralPath $PlaywrightCli -PathType Leaf)) {
        throw "Candidate Playwright is not installed at $PlaywrightCli; refusing to resolve it elsewhere."
    }
    $HelperPython = [Environment]::GetEnvironmentVariable("CASEOPS_E2E_PYTHON", "Process")
    if (
        -not (Test-PathWithinRoot -Path $HelperPython -Root $RepoRoot) -or
        -not (Test-Path -LiteralPath $HelperPython -PathType Leaf)
    ) {
        throw "Browser support helpers would run Python outside the candidate: '$HelperPython'."
    }

    $InventoryPath = Join-Path $ResultsDirectory "playwright-inventory.json"
    if (Test-Path -LiteralPath $InventoryPath) {
        throw "Playwright inventory already exists; refusing to overwrite retained evidence: $InventoryPath."
    }
    $SavedListingEnvironment = @{}
    foreach ($Name in @("PLAYWRIGHT_JSON_OUTPUT_FILE", "PLAYWRIGHT_JSON_OUTPUT_DIR", "PLAYWRIGHT_JSON_OUTPUT_NAME")) {
        $SavedListingEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    $ListingLocationPushed = $false
    try {
        # Native JSON bytes must not pass through Windows PowerShell's OEM stdout decoder.
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_FILE", $InventoryPath, "Process")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_DIR", $null, "Process")
        [Environment]::SetEnvironmentVariable("PLAYWRIGHT_JSON_OUTPUT_NAME", $null, "Process")
        Push-Location -LiteralPath $RepoRoot
        $ListingLocationPushed = $true
        & $NodePath $PlaywrightCli test --config $PlaywrightConfig --list --reporter=json @Arguments
        $ListExitCode = $LASTEXITCODE
    }
    finally {
        foreach ($Name in $SavedListingEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $SavedListingEnvironment[$Name], "Process")
        }
        if ($ListingLocationPushed) { Pop-Location }
    }
    if ($ListExitCode -ne 0 -or -not (Test-Path -LiteralPath $InventoryPath -PathType Leaf)) {
        throw "Could not list the candidate Playwright suite (exit $ListExitCode); see $InventoryPath."
    }
    try {
        $InventoryBytes = [IO.File]::ReadAllBytes($InventoryPath)
        if ($InventoryBytes.Length -eq 0) { throw "Empty inventory file." }
        $StrictUtf8 = New-Object Text.UTF8Encoding($false, $true)
        $ListingText = $StrictUtf8.GetString($InventoryBytes).TrimStart([char]0xFEFF)
        $Report = $ListingText | ConvertFrom-Json -ErrorAction Stop
        if ($null -eq $Report -or $null -eq $Report.config -or $null -eq $Report.suites) {
            throw "Missing inventory structure."
        }
    }
    catch { throw "The candidate Playwright inventory is invalid UTF-8 JSON; see $InventoryPath." }
    if (@($Report.errors).Count -gt 0) {
        throw "The candidate Playwright suite has load errors; see $InventoryPath."
    }
    if ([int]$Report.stats.expected -ne 0 -or [int]$Report.stats.unexpected -ne 0 -or
        [int]$Report.stats.flaky -ne 0) {
        throw "Playwright discovery contains executed results; see $InventoryPath."
    }
    $ConfigFile = [string]$Report.config.configFile
    if (
        -not (Test-PathWithinRoot -Path $ConfigFile -Root $RepoRoot) -or
        [IO.Path]::GetFullPath($ConfigFile) -ne [IO.Path]::GetFullPath($PlaywrightConfig)
    ) {
        throw "Playwright resolved config '$ConfigFile' instead of $PlaywrightConfig."
    }
    $RootDir = [string]$Report.config.rootDir
    $TestDirs = @($RootDir) + @($Report.config.projects | ForEach-Object { [string]$_.testDir })
    foreach ($TestDir in $TestDirs) {
        if (-not (Test-PathWithinRoot -Path $TestDir -Root $RepoRoot)) {
            throw "Playwright resolved test directory '$TestDir' outside the candidate $RepoRoot."
        }
    }
    $Pending = New-Object 'System.Collections.Generic.Queue[object]'
    foreach ($Suite in @($Report.suites)) { if ($null -ne $Suite) { $Pending.Enqueue($Suite) } }
    $SpecCount = 0
    $TestCount = 0
    while ($Pending.Count -gt 0) {
        $Suite = $Pending.Dequeue()
        if ($Suite.file) {
            $SpecFile = [IO.Path]::Combine($RootDir, [string]$Suite.file)
            if (-not (Test-PathWithinRoot -Path $SpecFile -Root $RepoRoot)) {
                throw "Playwright listed spec '$SpecFile' outside the candidate $RepoRoot."
            }
        }
        foreach ($Spec in @($Suite.specs | Where-Object { $null -ne $_ })) {
            $SpecCount++
            foreach ($Test in @($Spec.tests | Where-Object { $null -ne $_ })) {
                if (@($Test.results | Where-Object { $null -ne $_ }).Count -gt 0) {
                    throw "Playwright discovery contains executed results; see $InventoryPath."
                }
                $TestCount++
            }
        }
        foreach ($Child in @($Suite.suites)) { if ($null -ne $Child) { $Pending.Enqueue($Child) } }
    }
    if ($SpecCount -eq 0 -or $TestCount -eq 0) {
        throw "The candidate Playwright selection is empty; an empty browser run cannot certify."
    }
    # Native --list reports unexecuted tests as skipped, with empty result arrays.
    if ([int]$Report.stats.skipped -ne $TestCount) {
        throw "Playwright discovery test totals disagree; see $InventoryPath."
    }
    Write-Host "[docker-acceptance] candidate Playwright inventory: $SpecCount specs from $RootDir"
}

function Invoke-CandidatePlaywright {
    param([string[]]$Arguments = @())

    if (@($Arguments | Where-Object { $_ -match "^--reporter(?:=|$)" }).Count) {
        throw "Docker acceptance owns its structured Playwright reporters."
    }
    $ReportStem = Join-Path $ResultsDirectory ("playwright-" + [Guid]::NewGuid().ToString("N"))
    # Playwright clears project output directories at the next invocation. Keep
    # all bytes, including unattached originals, before another shard can start.
    $RetainArtifacts = {
        param($Report)

        $Staging = "$ReportStem.artifacts"
        try {
            [void](New-Item -ItemType Directory -Path $Staging -ErrorAction Stop)
            $SelectedProjects = @()
            $Pending = New-Object 'System.Collections.Generic.Queue[object]'
            foreach ($Suite in @($Report.suites)) { if ($null -ne $Suite) { $Pending.Enqueue($Suite) } }
            while ($Pending.Count) {
                $Suite = $Pending.Dequeue()
                foreach ($Spec in @($Suite.specs)) {
                    $SelectedProjects += @($Spec.tests | Where-Object { $_.projectName } |
                        ForEach-Object { $_.projectName })
                }
                foreach ($Child in @($Suite.suites)) { if ($null -ne $Child) { $Pending.Enqueue($Child) } }
            }
            if (-not $SelectedProjects.Count) {
                for ($Index = 0; $Index -lt $Arguments.Count; $Index++) {
                    if ($Arguments[$Index] -match '^--project=(.+)$') { $SelectedProjects += $Matches[1] }
                    elseif ($Arguments[$Index] -eq '--project' -and $Index + 1 -lt $Arguments.Count) {
                        $SelectedProjects += $Arguments[++$Index]
                    }
                }
            }
            $OutputDirs = @($Report.config.projects |
                Where-Object { -not $SelectedProjects.Count -or $_.name -in $SelectedProjects } |
                ForEach-Object { $_.outputDir } |
                Where-Object { $_ } | Sort-Object -Unique -CaseSensitive)
            if (-not $OutputDirs.Count) {
                $InventoryPath = Join-Path $ResultsDirectory "playwright-inventory.json"
                if (Test-Path -LiteralPath $InventoryPath -PathType Leaf) {
                    $Inventory = Get-Content -LiteralPath $InventoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
                    $OutputDirs = @($Inventory.config.projects |
                        Where-Object { -not $SelectedProjects.Count -or $_.name -in $SelectedProjects } |
                        ForEach-Object { $_.outputDir } |
                        Where-Object { $_ } | Sort-Object -Unique -CaseSensitive)
                }
            }
            $ResolvedOutputs = $OutputDirs.Count -gt 0
            if (-not $ResolvedOutputs) { $OutputDirs = @(Join-Path $RepoRoot "test-results") }
            $SnapshotTree = {
                param([string]$Root)

                $Items = New-Object 'System.Collections.Generic.List[object]'
                $Queue = New-Object 'System.Collections.Generic.Queue[string]'
                $Queue.Enqueue($Root)
                while ($Queue.Count) {
                    $Directory = [IO.DirectoryInfo]::new((& $IoPath $Queue.Dequeue()))
                    if ([int]$Directory.Attributes -eq -1) {
                        throw "Artifact directory metadata is unavailable."
                    }
                    if ($Directory.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        throw "Artifact retention refuses reparse points."
                    }
                    $Items.Add([pscustomobject]@{
                        FullName = (& $NormalPath $Directory.FullName); PSIsContainer = $true
                    })
                    foreach ($Item in $Directory.GetFileSystemInfos()) {
                        if ([int]$Item.Attributes -eq -1) {
                            throw "Artifact entry metadata is unavailable."
                        }
                        if ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                            throw "Artifact retention refuses reparse points."
                        }
                        if ($Item.Attributes -band [IO.FileAttributes]::Directory) {
                            $Queue.Enqueue((& $NormalPath $Item.FullName))
                        }
                        else { $Items.Add([pscustomobject]@{
                            FullName = (& $NormalPath $Item.FullName); PSIsContainer = $false; Length = $Item.Length
                        }) }
                    }
                }
                return $Items.ToArray()
            }
            $Comparison = if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
                [StringComparer]::OrdinalIgnoreCase
            } else { [StringComparer]::Ordinal }
            $Files = New-Object 'System.Collections.Generic.Dictionary[string,object]' ($Comparison)
            $Directories = New-Object 'System.Collections.Generic.List[string]'
            # .NET Framework directory operations otherwise reject long evidence paths.
            $IoPath = {
                param([string]$Path)
                if ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT) {
                    $NativePath = $Path.Replace('/', '\')
                    if ($NativePath.StartsWith('\\?\')) { return $NativePath }
                    if ($NativePath.StartsWith('\\')) { return '\\?\UNC\' + $NativePath.Substring(2) }
                    return '\\?\' + $NativePath
                }
                return $Path
            }
            $NormalPath = {
                param([string]$Path)
                if ($Path.StartsWith('\\?\UNC\')) { return '\\' + $Path.Substring(8) }
                if ($Path.StartsWith('\\?\')) { return $Path.Substring(4) }
                return $Path
            }
            $HashFile = {
                param([string]$Path)
                $Stream = [IO.File]::OpenRead((& $IoPath $Path))
                $Hasher = [Security.Cryptography.SHA256]::Create()
                try { return -join ($Hasher.ComputeHash($Stream) | ForEach-Object { $_.ToString("x2") }) }
                finally { $Hasher.Dispose(); $Stream.Dispose() }
            }
            $RootPrefix = [IO.Path]::GetFullPath($RepoRoot).TrimEnd([char[]]"\/") + [IO.Path]::DirectorySeparatorChar
            foreach ($OutputDir in $OutputDirs) {
                if (-not (Test-PathWithinRoot -Path $OutputDir -Root $RepoRoot) -or
                    (Test-PathWithinRoot -Path $ResultsDirectory -Root $OutputDir) -or
                    (Test-PathWithinRoot -Path $OutputDir -Root $ResultsDirectory) -or
                    [IO.Path]::GetFullPath($OutputDir) -eq [IO.Path]::GetFullPath($ResultsDirectory)) {
                    throw "Artifact output directory is outside the candidate or overlaps retained reports."
                }
                # Check ancestors too: a lexically contained output may cross a junction.
                $Ancestor = Get-Item -LiteralPath (Split-Path -Parent $OutputDir) -Force -ErrorAction Stop
                while (Test-PathWithinRoot -Path $Ancestor.FullName -Root $RepoRoot) {
                    if ($Ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                        throw "Artifact retention refuses reparse points."
                    }
                    $Ancestor = $Ancestor.Parent
                }
                if (-not (Test-Path -LiteralPath $OutputDir -PathType Container)) {
                    if ($ResolvedOutputs) { throw "Artifact output directory is missing." }
                    continue
                }
                $Before = @(& $SnapshotTree $OutputDir | Sort-Object FullName)
                foreach ($Item in $Before) {
                    $Relative = $Item.FullName.Substring($RootPrefix.Length).Replace('\', '/')
                    $Retained = "payload/$Relative"
                    $Target = Join-Path $Staging $Retained
                    if ($Item.PSIsContainer) {
                        [void][IO.Directory]::CreateDirectory((& $IoPath $Target))
                        if (-not $Directories.Contains($Retained)) { $Directories.Add($Retained) }
                        continue
                    }
                    if ($Files.ContainsKey($Item.FullName)) { continue }
                    $Hash = & $HashFile $Item.FullName
                    [IO.File]::Copy((& $IoPath $Item.FullName), (& $IoPath $Target), $false)
                    if ([IO.FileInfo]::new((& $IoPath $Target)).Length -ne $Item.Length -or
                        (& $HashFile $Target) -cne $Hash) {
                        throw "Artifact copy verification failed."
                    }
                    $Files[$Item.FullName] = [ordered]@{
                        original_path = $Item.FullName; relative_path = $Relative
                        retained_path = $Retained; size = $Item.Length; sha256 = $Hash
                    }
                }
                $After = @(& $SnapshotTree $OutputDir | Sort-Object FullName)
                if ($Before.Count -ne $After.Count -or
                    [string]::Join("`n", @($Before.FullName)) -cne [string]::Join("`n", @($After.FullName))) {
                    throw "Artifact source inventory changed during retention."
                }
                foreach ($Item in $After | Where-Object { -not $_.PSIsContainer }) {
                    if ($Item.Length -ne $Files[$Item.FullName].size -or
                        (& $HashFile $Item.FullName) -cne $Files[$Item.FullName].sha256) {
                        throw "Artifact source bytes changed during retention."
                    }
                }
            }
            $Attachments = New-Object 'System.Collections.Generic.List[object]'
            $Pending = New-Object 'System.Collections.Generic.Queue[object]'
            foreach ($Suite in @($Report.suites)) { if ($null -ne $Suite) { $Pending.Enqueue($Suite) } }
            while ($Pending.Count) {
                $Suite = $Pending.Dequeue()
                foreach ($Spec in @($Suite.specs)) {
                    foreach ($Test in @($Spec.tests | Where-Object { $null -ne $_ })) {
                        foreach ($Result in @($Test.results)) {
                            foreach ($Attachment in @($Result.attachments | Where-Object { $_.path })) {
                                $Original = [string]$Attachment.path
                                $Absolute = if ([IO.Path]::IsPathRooted($Original)) {
                                    & $NormalPath ([IO.Path]::GetFullPath((& $IoPath $Original)))
                                } else { & $NormalPath ([IO.Path]::GetFullPath((& $IoPath (Join-Path $RepoRoot $Original)))) }
                                if (-not $Files.ContainsKey($Absolute)) {
                                    throw "Reported attachment is missing from retained output: $Original"
                                }
                                $Attachments.Add([ordered]@{
                                    test_id = $Test.id; project_name = $Test.projectName
                                    name = $Attachment.name; original_path = $Original
                                    retained_path = $Files[$Absolute].retained_path
                                    size = $Files[$Absolute].size; sha256 = $Files[$Absolute].sha256
                                })
                            }
                        }
                    }
                }
                foreach ($Child in @($Suite.suites)) { if ($null -ne $Child) { $Pending.Enqueue($Child) } }
            }
            $Manifest = [ordered]@{
                event = "artifacts_retained"; release_sha = $ReleaseSha
                json = "$ReportStem.json"; junit = "$ReportStem.xml"
                output_directories = @($OutputDirs); directories = @($Directories.ToArray())
                files = @($Files.Values | Sort-Object relative_path); attachments = @($Attachments.ToArray())
            } | ConvertTo-Json -Depth 12
            [IO.File]::WriteAllText((& $IoPath (Join-Path $Staging "manifest.pending.json")), $Manifest,
                (New-Object Text.UTF8Encoding($false)))
            # An atomic same-directory manifest rename commits the complete payload;
            # a partial copy never has a manifest or an execution completion receipt.
            [IO.File]::Move((& $IoPath (Join-Path $Staging "manifest.pending.json")),
                (& $IoPath (Join-Path $Staging "manifest.json")))
            return (Join-Path $Staging "manifest.json")
        }
        catch {
            [ordered]@{
                event = "artifact_retention_failed"; release_sha = $ReleaseSha
                partial = $Staging; json = "$ReportStem.json"; junit = "$ReportStem.xml"
                detail = $_.Exception.Message
            } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$ReportStem.retention-failed.json" -Encoding UTF8
            throw
        }
    }
    $ReportEnvironment = @{
        PLAYWRIGHT_JSON_OUTPUT_FILE = "$ReportStem.json"
        PLAYWRIGHT_JUNIT_OUTPUT_FILE = "$ReportStem.xml"
    }
    $SavedReportEnvironment = @{}
    foreach ($Name in $ReportEnvironment.Keys) {
        $SavedReportEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
        [Environment]::SetEnvironmentVariable($Name, $ReportEnvironment[$Name], "Process")
    }
    $PlaywrightExitCode = 1
    $StartedAt = [DateTime]::UtcNow.ToString("o")
    $LocationPushed = $false
    try {
        Push-Location -LiteralPath $RepoRoot
        $LocationPushed = $true
        & $NodePath $PlaywrightCli test --config $PlaywrightConfig --reporter=list,json,junit @Arguments
        $PlaywrightExitCode = $LASTEXITCODE
        $ArtifactReport = $null
        try { $ArtifactReport = Get-Content -LiteralPath "$ReportStem.json" -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { } # Keep failed-run output even when the final reporter is incomplete.
        $ArtifactsManifest = & $RetainArtifacts $ArtifactReport
        foreach ($ReportPath in $ReportEnvironment.Values) {
            if (-not (Test-Path -LiteralPath $ReportPath -PathType Leaf)) {
                throw "Playwright execution is incomplete: missing report $ReportPath."
            }
        }
        try {
            $Report = Get-Content -LiteralPath "$ReportStem.json" -Raw | ConvertFrom-Json
        }
        catch { throw "Playwright execution is incomplete: invalid JSON report $ReportStem.json." }
        try { [xml]$JUnit = Get-Content -LiteralPath "$ReportStem.xml" -Raw }
        catch { throw "Playwright execution is incomplete: invalid XML report $ReportStem.xml." }
        $Pending = New-Object 'System.Collections.Generic.Queue[object]'
        foreach ($Suite in @($Report.suites)) {
            if ($null -ne $Suite) { $Pending.Enqueue($Suite) }
        }
        $BrowserTests = 0
        while ($Pending.Count -gt 0) {
            $Suite = $Pending.Dequeue()
            foreach ($Spec in @($Suite.specs)) {
                foreach ($Test in @($Spec.tests)) {
                    if ($null -eq $Test) { continue }
                    if (@($Test.results | Where-Object { $null -ne $_ }).Count -eq 0) {
                        throw "Playwright execution is incomplete: a selected test has no result."
                    }
                    if (@($Test.results | Where-Object {
                        $_.status -notin @("passed", "failed", "timedOut", "skipped")
                    }).Count) {
                        throw "Playwright execution is incomplete: invalid or interrupted test result."
                    }
                    $BrowserTests++
                }
            }
            foreach ($Child in @($Suite.suites)) {
                if ($null -ne $Child) { $Pending.Enqueue($Child) }
            }
        }
        $XmlTests = $JUnit.SelectNodes("/testsuites/testsuite/testcase").Count
        $StatsTests = [int]$Report.stats.expected + [int]$Report.stats.unexpected +
            [int]$Report.stats.skipped + [int]$Report.stats.flaky
        if ($BrowserTests -eq 0 -or $XmlTests -ne $BrowserTests -or $StatsTests -ne $BrowserTests) {
            throw "Playwright execution is incomplete: empty or disagreeing JSON/XML test totals."
        }
        if ($PlaywrightExitCode -eq 0 -and (
            [int]$Report.stats.unexpected -ne 0 -or [int]$Report.stats.flaky -ne 0 -or
            @($Report.errors | Where-Object { $null -ne $_ }).Count -ne 0
        )) {
            throw "Playwright exit zero disagrees with its failed structured results."
        }
        # Write completion only after both final reports reconcile; a nonzero
        # process exit still fails the caller's gate. Preserve every invocation.
        [ordered]@{
            event = "execution_finished"
            release_sha = $ReleaseSha
            arguments = @($Arguments)
            started_at = $StartedAt
            completed_at = [DateTime]::UtcNow.ToString("o")
            exit_code = $PlaywrightExitCode
            tests = $BrowserTests
            stats = $Report.stats
            json = "$ReportStem.json"
            junit = "$ReportStem.xml"
            artifacts_manifest = $ArtifactsManifest
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath "$ReportStem.completion.json" -Encoding UTF8
        Write-Host "[docker-acceptance] browser execution reports: $ReportStem ($BrowserTests tests)"
    }
    finally {
        foreach ($Name in $ReportEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $SavedReportEnvironment[$Name], "Process")
        }
        if ($LocationPushed) { Pop-Location }
        $global:LASTEXITCODE = $PlaywrightExitCode
    }
}

function Get-ComposeServiceState {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Project,
        [Parameter(Mandatory=$true)]
        [string]$File,
        [Parameter(Mandatory=$true)]
        [string]$Service
    )

    $ContainerIds = @(
        & docker compose --project-name $Project --file $File ps --all --quiet $Service |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ -match "^[0-9a-f]+$" }
    )
    if ($LASTEXITCODE -ne 0 -or $ContainerIds.Count -eq 0) {
        throw "Could not resolve the $Service container in $Project."
    }
    $States = @(& docker inspect --format "{{.State.Status}}" $ContainerIds)
    if ($LASTEXITCODE -ne 0 -or $States.Count -eq 0 -or ($States | Where-Object { -not $_ }).Count -gt 0) {
        throw "Could not inspect the $Service container in $Project."
    }
    if ($States -contains "running") {
        return "running"
    }
    return [string]$States[0]
}

function Save-DockerAcceptanceFailureEvidence {
    $SavedExitCode = $LASTEXITCODE
    $script:FailureEvidenceAttempted = $true
    $Stem = Join-Path $ResultsDirectory ("failure-" + [Guid]::NewGuid().ToString("N"))
    $CaptureErrors = New-Object 'System.Collections.Generic.List[object]'
    try {
        try {
            & docker compose --project-name $ComposeProject --file $ComposeFile logs `
                --tail 1000 --timestamps --no-color api web migrate worker postgres valkey acceptance-case-provider `
                2>&1 | Set-Content -LiteralPath "$Stem.compose.log" -Encoding UTF8
            if ($LASTEXITCODE -ne 0) { throw "Compose log capture exited $LASTEXITCODE." }
        }
        catch {
            $CaptureErrors.Add(@{ stage = "compose_logs"; exit_code = $LASTEXITCODE; exception_type = $_.Exception.GetType().FullName })
        }
        try {
            $ContainerIds = @(& docker compose --project-name $ComposeProject --file $ComposeFile ps --all --quiet)
            if ($LASTEXITCODE -ne 0 -or $ContainerIds.Count -eq 0 -or $ContainerIds.Count -gt 16 -or
                @($ContainerIds | Where-Object { $_ -notmatch '^[0-9a-f]{12,64}$' }).Count) {
                throw "Owned container inventory capture failed."
            }
            # Select safe fields at the Docker boundary; never inspect Config.Env,
            # command arguments, healthcheck output or the full container object.
            $StateFormat = "{{.Id}}`t{{.Name}}`t{{.Image}}`t{{.State.Status}}`t{{.State.Running}}`t{{.State.Paused}}`t{{.State.Restarting}}`t{{.State.OOMKilled}}`t{{.State.Dead}}`t{{.State.ExitCode}}`t{{.State.StartedAt}}`t{{.State.FinishedAt}}"
            "id`tname`timage_id`tstatus`trunning`tpaused`trestarting`toom_killed`tdead`texit_code`tstarted_at`tfinished_at" |
                Set-Content -LiteralPath "$Stem.container-state.tsv" -Encoding UTF8
            & docker inspect --format $StateFormat @ContainerIds `
                2>&1 | Add-Content -LiteralPath "$Stem.container-state.tsv" -Encoding UTF8
            if ($LASTEXITCODE -ne 0) { throw "Owned container state capture exited $LASTEXITCODE." }
        }
        catch {
            $CaptureErrors.Add(@{ stage = "container_state"; exit_code = $LASTEXITCODE; exception_type = $_.Exception.GetType().FullName })
        }
        try {
            [ordered]@{
                event = if ($CaptureErrors.Count) { "failure_capture_failed" } else { "failure_capture_finished" }
                release_sha = $ReleaseSha
                compose_project = $ComposeProject
                captured_at = [DateTime]::UtcNow.ToString("o")
                logs = "$Stem.compose.log"
                container_state = "$Stem.container-state.tsv"
                errors = @($CaptureErrors.ToArray())
            } | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath "$Stem.capture.json" -Encoding UTF8
        }
        catch {
            $CaptureErrors.Add(@{ stage = "capture_manifest"; exception_type = $_.Exception.GetType().FullName })
        }
        if ($CaptureErrors.Count) {
            Write-Warning "Docker failure evidence capture failed separately from the gate: $Stem ($($CaptureErrors.stage -join ', '))."
        } else {
            Write-Host "[docker-acceptance] retained pre-cleanup failure evidence: $Stem"
        }
    }
    finally { $global:LASTEXITCODE = $SavedExitCode }
}

function Invoke-IsolatedNativePostgresGate {
    param([Parameter(Mandatory=$true)][scriptblock]$Validation)

    # Only this invocation's Compose namespace may own a disposable database.
    if ($ReleaseSha -cnotmatch '^[0-9a-f]{40}$' -or
        $ComposeProject -cnotmatch '^caseops-acceptance-([0-9a-f]{12})-([0-9a-f]{12})$') {
        throw "Invalid owned release/project identity for native PostgreSQL validation."
    }
    $ProjectRevision = $Matches[1]
    $ProjectNonce = $Matches[2]
    if ($ProjectRevision -cne $ReleaseSha.Substring(0, 12)) {
        throw "Native PostgreSQL project does not belong to the candidate release."
    }
    $NativeDatabaseName = "caseops_native_${ProjectRevision}_${ProjectNonce}"
    if ($PostgresPort -notmatch '^[0-9]{1,5}$' -or
        [int]$PostgresPort -lt 1 -or [int]$PostgresPort -gt 65535 -or
        $ApiImageId -notmatch '^sha256:[0-9a-f]{64}$' -or
        $AcceptanceNetworkId -notmatch '^[0-9a-f]{12,64}$') {
        throw "Invalid owned PostgreSQL port, inspected image or acceptance network."
    }
    $BrowserDatabaseUrl = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    $NativeDatabaseUrl = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/$NativeDatabaseName"
    if ($env:CASEOPS_E2E_DATABASE_URL -cne $BrowserDatabaseUrl -or
        $NativeDatabaseUrl -ceq $BrowserDatabaseUrl) {
        throw "Browser acceptance must retain its separate application database."
    }
    $SavedNativeEnvironment = @{}
    foreach ($Name in @("CASEOPS_TEST_POSTGRES_URL", "CASEOPS_DATABASE_URL")) {
        $SavedNativeEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    }
    $NativeImageArguments = @(
        "run", "--rm", "--memory", "512m", "--memory-swap", "512m",
        "--network", $AcceptanceNetworkId,
        "--env", "CASEOPS_ENV=e2e", "--env", "CASEOPS_AUTO_MIGRATE=false",
        "--env", "CASEOPS_DATABASE_URL=postgresql+psycopg://caseops:caseops@postgres:5432/$NativeDatabaseName",
        "--env", "CASEOPS_DB_STATEMENT_TIMEOUT_MS=60000",
        "--env", "CASEOPS_DB_LOCK_TIMEOUT_MS=5000",
        "--env", "CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS=60000",
        "--env", "CASEOPS_AUTH_SECRET=change-me-change-me-change-me-2026",
        "--env", "HF_HUB_OFFLINE=1", "--env", "TRANSFORMERS_OFFLINE=1",
        $ApiImageId
    )
    $PostgresArguments = @(
        "compose", "--project-name", $ComposeProject, "--file", $ComposeFile,
        "exec", "--no-TTY", "postgres"
    )
    $CreatedNativeDatabase = $false
    $NativeGateFailed = $false
    $NativeExitCode = 1
    try {
        Write-Host "[docker-acceptance] creating independently migrated native database $NativeDatabaseName"
        # createdb refuses an existing database; never reuse or clone application data.
        $CreateArguments = $PostgresArguments + @(
            "createdb", "--username", "caseops", "--maintenance-db", "postgres",
            "--template", "template0", "--", $NativeDatabaseName
        )
        & docker @CreateArguments
        if ($LASTEXITCODE -ne 0) { throw "Fresh native PostgreSQL database creation failed (exit $LASTEXITCODE); refusing reuse." }
        $CreatedNativeDatabase = $true
        foreach ($Name in $SavedNativeEnvironment.Keys) {
            [Environment]::SetEnvironmentVariable($Name, $NativeDatabaseUrl, "Process")
        }
        $ExtensionArguments = $PostgresArguments + @(
            "psql", "--username", "caseops", "--dbname", $NativeDatabaseName,
            "--no-psqlrc", "--set", "ON_ERROR_STOP=1", "--command", "CREATE EXTENSION vector"
        )
        & docker @ExtensionArguments
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL vector extension creation failed (exit $LASTEXITCODE)." }
        & docker @NativeImageArguments alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Independent native PostgreSQL migration failed (exit $LASTEXITCODE)." }
        & docker @NativeImageArguments python -m caseops_api.scripts.seed_statutes
        if ($LASTEXITCODE -ne 0) { throw "Exact-image native statute catalog seed failed (exit $LASTEXITCODE)." }
        & docker @NativeImageArguments caseops-db-index-health
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL pre-validation index health gate failed (exit $LASTEXITCODE)." }
        & $Validation
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL validation failed (exit $LASTEXITCODE)." }
        & docker @NativeImageArguments caseops-db-index-health
        if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL post-rehearsal index health gate failed (exit $LASTEXITCODE)." }
        $NativeExitCode = 0
    }
    catch {
        $NativeGateFailed = $true
        $NativeExitCode = if ($LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 1 }
        try { Save-DockerAcceptanceFailureEvidence }
        catch { Write-Warning "Docker failure evidence capture raised separately from the native gate: $($_.Exception.GetType().FullName)." }
        throw
    }
    finally {
        try {
            if ($CreatedNativeDatabase) {
                # No SQL/shell interpolation: native tools receive a bounded identifier.
                $DropArguments = $PostgresArguments + @(
                    "dropdb", "--username", "caseops", "--maintenance-db", "postgres",
                    "--force", "--", $NativeDatabaseName
                )
                & docker @DropArguments
                if ($LASTEXITCODE -ne 0) { throw "Native PostgreSQL cleanup failed (exit $LASTEXITCODE): $NativeDatabaseName." }
            }
        }
        catch {
            if (-not $NativeGateFailed) {
                $NativeExitCode = if ($LASTEXITCODE -ne 0) { $LASTEXITCODE } else { 1 }
                throw
            }
            Write-Warning "Native database cleanup also failed; retaining the original gate failure: $($_.Exception.Message)"
        }
        finally {
            foreach ($Name in $SavedNativeEnvironment.Keys) {
                if ($null -eq $SavedNativeEnvironment[$Name]) {
                    Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
                } else {
                    [Environment]::SetEnvironmentVariable($Name, $SavedNativeEnvironment[$Name], "Process")
                }
            }
            $global:LASTEXITCODE = $NativeExitCode
        }
    }
}

$PinnedNodeVersion = ((Get-Content -LiteralPath (Join-Path $RepoRoot ".nvmrc") -Raw).Trim() -replace "^v", "")
& (Join-Path $RepoRoot "tests\docker-candidate-source-guard.ps1")
& (Join-Path $RepoRoot "tests\docker-acceptance-repo-root-guard.ps1")
& (Join-Path $RepoRoot "tests\docker-native-postgres-isolation-guard.ps1")
& (Join-Path $RepoRoot "tests\docker-failure-evidence-guard.ps1")
& (Join-Path $RepoRoot "tests\docker-release-image-identity-guard.ps1") `
    -EvidenceDirectory (Join-Path $ResultsDirectory "image-identity-guard")
$NodePath = (Get-Command node -ErrorAction Stop).Source
Write-Host "[docker-acceptance] validating local proxy cancellation and transport semantics"
& $NodePath --test (Join-Path $RepoRoot "scripts\docker-acceptance-api-proxy.test.mjs")
if ($LASTEXITCODE -ne 0) { throw "Docker acceptance proxy regression tests failed." }
$ActualNodeVersion = (((& $NodePath --version) | Out-String).Trim() -replace "^v", "")
if ($ActualNodeVersion -ne $PinnedNodeVersion) {
    throw (
        "Docker acceptance requires Node v$PinnedNodeVersion from .nvmrc; " +
        "found v$ActualNodeVersion at $NodePath. Activate the pinned runtime before retrying."
    )
}
$NpmPath = (Get-Command npm -ErrorAction Stop).Source

$PreviousEnvironment = @{}
$AcceptanceEnvironment = @{
    COMPOSE_PROFILES = "acceptance"
    CASEOPS_RELEASE_SHA = $ReleaseSha
    CASEOPS_DOCKER_ENV = "e2e"
    CASEOPS_DOCKER_API_APP = "oauth_emulator_api:app"
    CASEOPS_DOCKER_API_APP_DIR = "/oauth-harness"
    CASEOPS_E2E_OAUTH_EMULATOR = "calendar-20261008"
    CASEOPS_DOCKER_INTERNAL_WORKER_NETWORK = "true"
    CASEOPS_DOCKER_API_PORT = $ApiPort
    CASEOPS_DOCKER_WEB_PORT = $WebPort
    CASEOPS_DOCKER_POSTGRES_PORT = $PostgresPort
    CASEOPS_DOCKER_VALKEY_PORT = $ValkeyPort
    CASEOPS_DOCKER_PUBLIC_API_URL = "http://127.0.0.1:$TestApiPort"
    CASEOPS_DOCKER_PUBLIC_APP_URL = "http://127.0.0.1:$WebPort"
    CASEOPS_DOCKER_CORS_ORIGINS = "[`"http://127.0.0.1:$WebPort`",`"http://localhost:$WebPort`"]"
    CASEOPS_AUTH_RATE_LIMIT_ENABLED = "false"
    CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL = "platform-admin-e2e@example.com"
    CASEOPS_CASE_TRACKING_ENABLED = "true"
    CASEOPS_IP_WORKSPACE_ENABLED = "true"
    CASEOPS_IP_RULE_GOVERNANCE_ENABLED = "true"
    CASEOPS_CASE_TRACKING_PROVIDER = "ecourtsindia"
    CASEOPS_ECOURTSINDIA_API_BASE_URL = "http://acceptance-case-provider:8080"
    CASEOPS_ECOURTSINDIA_API_TOKEN = "docker-acceptance-provider-token"
    CASEOPS_LLM_PROVIDER = "mock"
    CASEOPS_LLM_MODEL = "caseops-mock-1"
    CASEOPS_SUMMARY_ACCEPTANCE = "1"
    CASEOPS_E2E_HEARING_PROVIDER = "sep10-offline"
    # Playwright's Node control-plane and browser calls go through a loopback
    # proxy with a bounded keep-alive pool for the long multi-shard run.
    CASEOPS_E2E_API_PORT = $TestApiPort
    CASEOPS_E2E_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    CASEOPS_E2E_AUTH_SECRET = "change-me-change-me-change-me-2026"
    CASEOPS_E2E_DOCKER_PROJECT = $ComposeProject
    CASEOPS_E2E_DOCKER_COMPOSE_FILE = $ComposeFile
    CASEOPS_TEST_POSTGRES_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    CASEOPS_TEST_RESULT_JOURNAL = (Join-Path $ResultsDirectory "postgres-results.jsonl")
    CASEOPS_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    CASEOPS_ENV = "ci"
    CASEOPS_AUTH_SECRET = "docker-postgres-validation-secret-at-least-32-bytes"
    CASEOPS_WEB_BASE_URL = "http://127.0.0.1:$WebPort"
    # Browser support helpers honour this before any path of their own.
    CASEOPS_E2E_PYTHON = $ApiPython
    # Worktrees under OneDrive cannot always accept uv cache hardlinks on Windows.
    UV_LINK_MODE = "copy"
}

foreach ($Name in $AcceptanceEnvironment.Keys) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, $AcceptanceEnvironment[$Name], "Process")
}

$Succeeded = $false
# npm, npx, uv, Python and Compose resolve inputs from the working directory.
Push-Location -LiteralPath $RepoRoot
try {
    $IdentityKind = if ($PreCommit) { "pre-commit source fingerprint" } else { "commit" }
    $CandidateIdentity = if ($PreCommit) { $SourceFingerprint } else { $ReleaseSha }
    Write-Host "[docker-acceptance] exact $IdentityKind $CandidateIdentity"
    if ($PreCommit) {
        Write-Host "[docker-acceptance] derived runtime revision $ReleaseSha"
    }
    if ($PortBase -ne $PreferredPortBase) {
        Write-Host (
            "[docker-acceptance] preferred port block $PreferredPortBase-$($PreferredPortBase + 4) " +
            "is reserved or occupied; using $PortBase-$($PortBase + 4)"
        )
    }
    Write-Host "[docker-acceptance] preparing frozen host test dependencies"
    & $NpmPath ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Host Node dependency sync failed." }
    Write-Host "[docker-acceptance] type-checking browser tests and configurations"
    & $NpmPath run typecheck:e2e
    if ($LASTEXITCODE -ne 0) { throw "Browser test or configuration typecheck failed." }
    & uv sync --project $ApiDir --frozen
    if ($LASTEXITCODE -ne 0) { throw "Host API dependency sync failed." }
    $ApiPackage = ((& $ApiPython -c "import caseops_api, psycopg, sqlalchemy; print(caseops_api.__file__)" | Out-String).Trim())
    if ($LASTEXITCODE -ne 0) { throw "Host API fixture dependencies or project package are unavailable." }
    if (-not (Test-PathWithinRoot -Path $ApiPackage -Root $ApiDir)) {
        throw "Host API fixtures import caseops_api from '$ApiPackage', outside the candidate $ApiDir."
    }
    Assert-CandidateDataClassProjection
    Assert-CandidatePlaywrightSuite -Arguments $PlaywrightArgs

    Write-Host "[docker-acceptance] resetting isolated project $ComposeProject"
    & docker compose --profile acceptance --project-name $ComposeProject --file $ComposeFile down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "Could not reset the isolated Compose project." }

    # Retained acceptance projects can exhaust Docker's default address pools.
    # An explicit free subnet avoids pruning another task's networks or data.
    if ($NetworkSubnet) {
        & docker network create --subnet $NetworkSubnet `
            --label "com.docker.compose.project=$ComposeProject" `
            --label "com.docker.compose.network=default" `
            "${ComposeProject}_default"
        if ($LASTEXITCODE -ne 0) { throw "Could not create the isolated acceptance subnet." }
    }
    if ($WorkerNetworkSubnet) {
        & docker network create --internal --subnet $WorkerNetworkSubnet `
            --label "com.docker.compose.project=$ComposeProject" `
            --label "com.docker.compose.network=worker-offline" `
            "${ComposeProject}_worker-offline"
        if ($LASTEXITCODE -ne 0) { throw "Could not create the offline worker subnet." }
    }

    if (-not $SkipBuild) {
        Write-Host "[docker-acceptance] building API and web production images"
        & docker compose --project-name $ComposeProject --file $ComposeFile build --pull api web
        if ($LASTEXITCODE -ne 0) { throw "Docker image build failed." }
    }

    Assert-CandidateSourceUnchanged -Stage "after image build"
    Write-Host "[docker-acceptance] starting migration-first stack"
    & docker compose --project-name $ComposeProject --file $ComposeFile up --detach --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw "Docker stack did not become healthy." }

    $MigrationId = ((& docker compose --project-name $ComposeProject --file $ComposeFile ps --all --quiet migrate | Out-String).Trim())
    $MigrationExitCode = ((& docker inspect --format "{{.State.ExitCode}}" $MigrationId | Out-String).Trim())
    if ($MigrationExitCode -ne "0") {
        throw "Migration container exited with code $MigrationExitCode."
    }

    $ApiImageId = $null
    foreach ($Service in @("api", "web")) {
        $ImageId = ((& docker compose --project-name $ComposeProject --file $ComposeFile images --quiet $Service | Out-String).Trim())
        if ($LASTEXITCODE -ne 0 -or $ImageId -cnotmatch '^(?:sha256:)?[0-9a-f]{12,64}$') {
            throw "$Service image handle resolution failed."
        }
        $ImageMetadata = (& docker image inspect $ImageId | ConvertFrom-Json)
        if ($LASTEXITCODE -ne 0 -or $ImageMetadata.Count -ne 1 -or
            $ImageMetadata[0].Id -cnotmatch '^sha256:[0-9a-f]{64}$') {
            throw "$Service canonical image inspection failed."
        }
        $ImageRevision = $ImageMetadata[0].Config.Labels.'org.opencontainers.image.revision'
        if ($ImageRevision -ne $ReleaseSha) {
            throw "$Service image revision $ImageRevision does not match $ReleaseSha."
        }
        if ($Service -eq "api") { $ApiImageId = $ImageMetadata[0].Id }
    }

    Write-Host "[docker-acceptance] verifying real cloud worker environment startup offline"
    $WorkerStartupReceipts = @()
    foreach ($Worker in @(
        @{ Command = "caseops-document-worker"; Prefix = "DOCUMENT"; Args = @("--documents-only", "--once", "--skip-migrations") },
        @{ Command = "caseops-court-sync-worker"; Prefix = "COURT_SYNC"; Args = @("--once", "--skip-migrations") }
    )) {
        $WorkerArguments = @(
            "run", "--rm", "--pull=never", "--network=none", "--read-only", "--entrypoint=timeout",
            "--env=CASEOPS_ENV=cloud", "--env=CASEOPS_AUTO_MIGRATE=false",
            "--env=CASEOPS_AUTH_SECRET=$([Guid]::NewGuid().ToString('N'))",
            "--env=CASEOPS_DATABASE_URL=postgresql+psycopg://offline:offline@127.0.0.1:9/no_database",
            "--env=CASEOPS_$($Worker.Prefix)_WORKER_ADMISSION_PROTOCOL_VERSION=1",
            "--env=CASEOPS_$($Worker.Prefix)_WORKER_ADMISSION_ENABLED=false",
            $ApiImageId, "--kill-after=5s", "30s", $Worker.Command
        ) + $Worker.Args
        $WorkerOutput = ((& docker @WorkerArguments 2>&1) | Out-String).Trim()
        $WorkerExit = $LASTEXITCODE
        $WorkerStartupReceipts += [ordered]@{
            command = $Worker.Command; image_id = $ApiImageId; network = "none"
            protocol_environment = "1"; admission_environment = "false"
            startup_timeout_seconds = 30; kill_after_seconds = 5
            exit = $WorkerExit; output = $WorkerOutput
        }
        $WorkerStartupReceipts | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (
            Join-Path $ResultsDirectory "worker-env-startup.json"
        ) -Encoding utf8
        if ($WorkerExit -ne 0 -or $WorkerOutput -notmatch 'admission_protocol=1 admission=disabled' -or
            $WorkerOutput -notmatch 'attempted=0 completed=0 failed=0 unfinalized=0') {
            throw "$($Worker.Command) rejected cloud protocol environment or performed work while disabled: $WorkerOutput"
        }
    }

    $ApiHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    $ApiIdentity = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/build"
    $WebIdentity = Invoke-RestMethod "http://127.0.0.1:$WebPort/api/release-identity"
    if ($ApiHealth.status -ne "ok") { throw "API health probe did not return ok." }
    if ($ApiIdentity.release_sha -ne $ReleaseSha) { throw "API runtime identity does not match the candidate." }
    if ($WebIdentity.release_sha -ne $ReleaseSha) { throw "Web runtime identity does not match the candidate." }

    Write-Host "[docker-acceptance] verifying the web server's internal API origin"
    $ServerOriginProbe = "(async()=>{const base=process.env.CASEOPS_API_BASE_URL;if(base!=='http://api:8000')throw new Error('Invalid internal API origin');const health=await fetch(base+'/api/health',{signal:AbortSignal.timeout(5000)});const build=await fetch(base+'/api/build',{signal:AbortSignal.timeout(5000)});if(!health.ok||!build.ok)throw new Error('Internal API unavailable');if((await health.json()).status!=='ok'||(await build.json()).release_sha!==process.env.CASEOPS_RELEASE_SHA)throw new Error('Internal API identity mismatch');process.stdout.write('internal-api-origin-and-identity-ok');})().catch(()=>process.exit(1))"
    & docker compose --project-name $ComposeProject --file $ComposeFile exec --no-TTY web node -e $ServerOriginProbe
    if ($LASTEXITCODE -ne 0) { throw "Web server-to-server API origin/identity preflight failed." }

    Write-Host "[docker-acceptance] verifying complete PostgreSQL index coverage"
    & docker compose --project-name $ComposeProject --file $ComposeFile exec --no-TTY api caseops-db-index-health
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL index health gate failed." }

    Write-Host "[docker-acceptance] verifying index health within the production job memory ceiling"
    $AcceptanceNetworkId = ((& docker network ls `
        --filter "label=com.docker.compose.project=$ComposeProject" `
        --filter "label=com.docker.compose.network=default" `
        --format "{{.ID}}" | Out-String).Trim())
    if (-not $ApiImageId -or -not $AcceptanceNetworkId -or $AcceptanceNetworkId -match "\s") {
        throw "Could not resolve the exact API image and isolated Compose network."
    }
    & docker run --rm `
        --memory 512m `
        --memory-swap 512m `
        --network $AcceptanceNetworkId `
        --env CASEOPS_ENV=e2e `
        --env CASEOPS_AUTO_MIGRATE=false `
        --env CASEOPS_DATABASE_URL=postgresql+psycopg://caseops:caseops@postgres:5432/caseops `
        --env CASEOPS_DB_STATEMENT_TIMEOUT_MS=60000 `
        --env CASEOPS_DB_LOCK_TIMEOUT_MS=5000 `
        --env CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS=60000 `
        --env CASEOPS_AUTH_SECRET=change-me-change-me-change-me-2026 `
        $ApiImageId `
        caseops-db-index-health
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL index health exceeded its 512 MiB production job ceiling or failed."
    }

    Write-Host "[docker-acceptance] pausing the document worker for migration-state validation"
    & docker compose --project-name $ComposeProject --file $ComposeFile stop --timeout 30 worker
    if ($LASTEXITCODE -ne 0) { throw "Could not stop the document worker before PostgreSQL validation." }
    $WorkerStateBeforePostgres = Get-ComposeServiceState `
        -Project $ComposeProject `
        -File $ComposeFile `
        -Service "worker"
    if ($WorkerStateBeforePostgres -ne "exited") {
        throw "Document worker remained $WorkerStateBeforePostgres during migration-state validation."
    }

    Write-Host "[docker-acceptance] running the complete PostgreSQL + pgvector validation suite"
    Assert-CandidateSourceUnchanged -Stage "before isolated PostgreSQL acceptance"
    Invoke-IsolatedNativePostgresGate -Validation {
        Push-Location $ApiDir
        $PostgresExitCode = 1
        try {
            $NativeArguments = @(
                (Join-Path $RepoRoot "scripts\run_postgres_acceptance.py"),
                "--api-dir", $ApiDir, "--results-directory", $ResultsDirectory
            )
            & $ApiPython @NativeArguments
            $PostgresExitCode = $LASTEXITCODE
            if (-not (Test-Path -LiteralPath $AcceptanceEnvironment.CASEOPS_TEST_RESULT_JOURNAL)) {
                throw "PostgreSQL validation did not retain its incremental result journal."
            }
            if ($PostgresExitCode -ne 0) { throw "PostgreSQL + pgvector validation failed (exit $PostgresExitCode)." }
            $DriverCompletion = Join-Path $ResultsDirectory "postgres-driver-completion.json"
            if (-not (Test-Path -LiteralPath $DriverCompletion -PathType Leaf)) {
                throw "PostgreSQL validation did not retain complete whole-file driver evidence."
            }
            $NativeCompletion = Get-Content -LiteralPath $DriverCompletion -Raw | ConvertFrom-Json
            if ($NativeCompletion.exit_code -ne 0 -or $NativeCompletion.shards -ne 8 -or
                -not $NativeCompletion.source_unchanged -or $NativeCompletion.collected -lt 1) {
                throw "PostgreSQL whole-file driver did not reconcile the full successful inventory."
            }
        }
        finally {
            Pop-Location
            $global:LASTEXITCODE = $PostgresExitCode
        }
    }
    Assert-CandidateSourceUnchanged -Stage "after isolated PostgreSQL acceptance"

    Write-Host "[docker-acceptance] rechecking schema and index health after rollback rehearsals"
    & docker compose --project-name $ComposeProject --file $ComposeFile exec --no-TTY api caseops-db-index-health
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL post-rehearsal index health gate failed." }
    # Browser data never receives native fixtures or rollback rehearsals. Keep
    # the production release seed before browsers, using the inspected API image.
    Write-Host "[docker-acceptance] seeding the release statute catalog"
    & docker compose --project-name $ComposeProject --file $ComposeFile exec --no-TTY api python -m caseops_api.scripts.seed_statutes
    if ($LASTEXITCODE -ne 0) { throw "Release statute catalog seed failed." }
    Write-Host "[docker-acceptance] restarting the document worker at the restored schema head"
    & docker compose --project-name $ComposeProject --file $ComposeFile start worker
    if ($LASTEXITCODE -ne 0) { throw "Could not restart the document worker after PostgreSQL validation." }
    Start-Sleep -Seconds 2
    $WorkerStateAfterRestart = Get-ComposeServiceState `
        -Project $ComposeProject `
        -File $ComposeFile `
        -Service "worker"
    if ($WorkerStateAfterRestart -ne "running") {
        throw "Document worker was $WorkerStateAfterRestart after PostgreSQL validation."
    }

    Assert-CandidateSourceUnchanged -Stage "before browser acceptance"
    Write-Host "[docker-acceptance] running Playwright against Docker + PostgreSQL"
    $TestApiProxyStdout = Join-Path $ResultsDirectory "api-proxy.stdout.log"
    $TestApiProxyStderr = Join-Path $ResultsDirectory "api-proxy.stderr.log"
    $TestApiProxyProcess = Start-Process `
        -FilePath $NodePath `
        -ArgumentList @("`"$TestApiProxyScript`"", $TestApiPort, $ApiPort) `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $TestApiProxyStdout `
        -RedirectStandardError $TestApiProxyStderr
    $ProxyReady = $false
    foreach ($Attempt in 1..30) {
        if ($TestApiProxyProcess.HasExited) { break }
        try {
            $ProxyHealth = Invoke-RestMethod "http://127.0.0.1:$TestApiPort/api/health" -TimeoutSec 5
            if ($ProxyHealth.status -eq "ok") {
                $ProxyReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ProxyReady) {
        $ProxyError = if (Test-Path -LiteralPath $TestApiProxyStderr) {
            Get-Content -LiteralPath $TestApiProxyStderr -Raw
        } else { "" }
        throw "Docker acceptance API proxy did not become ready. $ProxyError"
    }
    if ($PlaywrightArgs.Count -eq 0) {
        # Bound each Windows worker's lifetime without retries: every desktop
        # test still runs exactly once, and the mobile project remains whole.
        Invoke-CandidatePlaywright -Arguments @("--project=app-chromium", "--shard=1/2")
        if ($LASTEXITCODE -ne 0) { throw "Docker Playwright desktop shard 1/2 failed." }
        Invoke-CandidatePlaywright -Arguments @("--project=app-chromium", "--shard=2/2")
        if ($LASTEXITCODE -ne 0) { throw "Docker Playwright desktop shard 2/2 failed." }
        Invoke-CandidatePlaywright -Arguments @("--project=app-mobile")
        if ($LASTEXITCODE -ne 0) { throw "Docker Playwright mobile project failed." }
    }
    else {
        Invoke-CandidatePlaywright -Arguments $PlaywrightArgs
        if ($LASTEXITCODE -ne 0) { throw "Docker Playwright focused acceptance failed." }
    }

    $WorkerStateAfterPlaywright = Get-ComposeServiceState `
        -Project $ComposeProject `
        -File $ComposeFile `
        -Service "worker"
    if ($WorkerStateAfterPlaywright -ne "running") {
        throw "Document worker was $WorkerStateAfterPlaywright after Playwright."
    }
    $PostTestHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    if ($PostTestHealth.status -ne "ok") { throw "API became unhealthy after Playwright." }
    Assert-CandidateSourceUnchanged -Stage "before acceptance certification"
    $Succeeded = $true
    Write-Host "[docker-acceptance] PASS $ReleaseSha"
}
finally {
    if ($null -ne $TestApiProxyProcess -and -not $TestApiProxyProcess.HasExited) {
        Stop-Process -Id $TestApiProxyProcess.Id -Force
        Wait-Process -Id $TestApiProxyProcess.Id -ErrorAction SilentlyContinue
    }
    if (-not $Succeeded) {
        Write-Host "[docker-acceptance] failure diagnostics"
        if (-not $FailureEvidenceAttempted) {
            try { Save-DockerAcceptanceFailureEvidence }
            catch { Write-Warning "Docker failure evidence capture raised separately from the gate: $($_.Exception.GetType().FullName)." }
        }
    }
    if (-not $KeepRunning) {
        & docker compose --profile acceptance --project-name $ComposeProject --file $ComposeFile down --volumes --remove-orphans
    }
    foreach ($Name in $AcceptanceEnvironment.Keys) {
        if ($null -eq $PreviousEnvironment[$Name]) {
            Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], "Process")
        }
    }
    if ($null -ne $TestApiProxyProcess) {
        $TestApiProxyProcess.WaitForExit()
        $TestApiProxyProcess.Dispose()
    }
    Pop-Location
}

if (-not $Succeeded) { exit 1 }
