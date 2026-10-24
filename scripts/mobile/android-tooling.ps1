[CmdletBinding()]
param([switch]$SelfTest)

function Assert-AndroidChildPath([string]$Path, [string]$Parent) {
    $prefix = [IO.Path]::GetFullPath($Parent).TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
    if (-not [IO.Path]::GetFullPath($Path).StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path escapes its intended directory: $Path"
    }
}

function Invoke-AndroidDownload([string]$Url, [string]$Destination) {
    # Each caller-owned attempt has its own retained part file; curl must not retry into it.
    & curl.exe --silent --show-error --fail --location --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 1200 --speed-time 60 --speed-limit 1024 --retry 0 --output $Destination $Url
    if ($LASTEXITCODE -ne 0) { throw "curl download failed with exit code $LASTEXITCODE" }
}

function Get-VerifiedArchive(
    [string]$Url, [string]$Name, [string]$Sha256, [string]$DownloadsDirectory,
    [scriptblock]$Downloader = { param($uri, $part) Invoke-AndroidDownload $uri $part }
) {
    if ($Name -ne [IO.Path]::GetFileName($Name) -or $Sha256 -notmatch '^[a-fA-F0-9]{64}$') {
        throw 'Expected a cache filename and a pinned SHA256'
    }
    [IO.Directory]::CreateDirectory($DownloadsDirectory) | Out-Null
    $archive = Join-Path $DownloadsDirectory $Name
    Assert-AndroidChildPath $archive $DownloadsDirectory
    if (Test-Path -LiteralPath $archive) {
        if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -eq $Sha256) { return $archive }
        $retained = $archive + '.invalid-' + [Guid]::NewGuid().ToString('N')
        [IO.File]::Move($archive, $retained)
        Write-Verbose "Retained invalid cache at $retained"
    }
    for ($attempt = 1; $attempt -le 3; $attempt++) {
        $part = $archive + '.' + [Guid]::NewGuid().ToString('N') + '.part'
        $reservation = [IO.File]::Open($part, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $reservation.Dispose()
        try { & $Downloader $Url $part | Out-Null }
        catch {
            if ($attempt -eq 3) { throw "Download failed after 3 attempts; retaining parts in ${DownloadsDirectory}: $($_.Exception.Message)" }
            Write-Verbose "Attempt $attempt failed; retaining $part : $($_.Exception.Message)"
            continue
        }
        if ((Get-FileHash -LiteralPath $part -Algorithm SHA256).Hash -ne $Sha256) {
            throw "Checksum mismatch; retaining unexecuted part $part"
        }
        try { [IO.File]::Move($part, $archive) }
        catch {
            # A competing invocation may already have published the same verified archive.
            if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or
                (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $Sha256) {
                throw "Archive publication failed; retaining $part : $($_.Exception.Message)"
            }
        }
        return $archive
    }
}

function Expand-VerifiedArchive([string]$Archive, [string]$Destination) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $Destination) { throw "Refusing to extract over existing directory: $Destination" }
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        foreach ($entry in $zip.Entries) {
            if ([IO.Path]::IsPathRooted($entry.FullName) -or $entry.FullName.Contains(':')) {
                throw 'Archive path escapes its installation directory'
            }
            $target = [IO.Path]::GetFullPath((Join-Path $Destination $entry.FullName))
            Assert-AndroidChildPath $target $Destination
        }
    } finally { $zip.Dispose() }
    [IO.Compression.ZipFile]::ExtractToDirectory($Archive, $Destination)
}

function Test-AndroidJdk([string]$Path) {
    foreach ($relative in @('bin/java.exe', 'bin/javac.exe', 'bin/jar.exe', 'lib/modules', 'release')) {
        $file = Join-Path $Path $relative
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or (Get-Item -LiteralPath $file).Length -eq 0) { return $false }
    }
    return $true
}

function Get-AndroidJdk([string]$Root) {
    $candidates = @()
    if (Test-Path -LiteralPath $Root -PathType Container) {
        if (Test-AndroidJdk $Root) { $candidates += [IO.Path]::GetFullPath($Root) }
        $candidates += @(Get-ChildItem -LiteralPath $Root -Directory | Where-Object { Test-AndroidJdk $_.FullName } | ForEach-Object { $_.FullName })
    }
    if ($candidates.Count -ne 1) { throw "Expected one complete JDK at $Root; found $($candidates.Count). Existing files are preserved." }
    return $candidates[0]
}

function Install-AndroidJdk([string]$Archive, [string]$Destination) {
    $Destination = [IO.Path]::GetFullPath($Destination)
    $parent = [IO.Path]::GetDirectoryName($Destination)
    if (-not $parent) { throw 'A filesystem root is not a JDK installation directory' }
    Assert-AndroidChildPath $Destination $parent
    if (Test-Path -LiteralPath $Destination) { return Get-AndroidJdk $Destination }
    $staging = $Destination + '.staging-' + [Guid]::NewGuid().ToString('N')
    Assert-AndroidChildPath $staging $parent
    Expand-VerifiedArchive $Archive $staging
    Get-AndroidJdk $staging | Out-Null
    # Sibling staging keeps publication on the same volume and never merges installations.
    [IO.Directory]::Move($staging, $Destination)
    return Get-AndroidJdk $Destination
}

function Install-AndroidCommandTools([string]$Archive, [string]$SdkRoot) {
    $parent = Join-Path $SdkRoot 'cmdline-tools'
    $destination = Join-Path $parent '15859902'
    Assert-AndroidChildPath $destination $parent
    if (Test-Path -LiteralPath $destination) {
        if (Test-Path -LiteralPath (Join-Path $destination 'bin/sdkmanager.bat') -PathType Leaf) { return $destination }
        throw "Refusing to replace an incomplete command-tools installation: $destination"
    }
    [IO.Directory]::CreateDirectory($parent) | Out-Null
    $staging = Join-Path $parent ('15859902.staging-' + [Guid]::NewGuid().ToString('N'))
    Expand-VerifiedArchive $Archive $staging
    $source = Join-Path $staging 'cmdline-tools'
    Assert-AndroidChildPath $source $staging
    if (-not (Test-Path -LiteralPath (Join-Path $source 'bin/sdkmanager.bat') -PathType Leaf)) {
        throw "Command-tools archive is incomplete; retaining $staging"
    }
    [IO.Directory]::Move($source, $destination)
    return $destination
}

function Merge-AndroidToolPath([string[]]$Bins, [AllowEmptyString()][string]$Path) {
    $selected = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $entries = [Collections.Generic.List[string]]::new()
    $key = { param($value) $value.Trim().Trim('"').Replace('/', '\').TrimEnd([char[]]'\/') }
    foreach ($bin in $Bins) {
        if ($bin -and $selected.Add((& $key $bin))) { $entries.Add($bin) }
    }
    foreach ($entry in ($Path -split ';')) {
        if ($entry -and -not $selected.Contains((& $key $entry))) { $entries.Add($entry) }
    }
    return $entries -join ';'
}

function Write-AndroidProbe([string]$Path, [string]$Json) {
    try { $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) }
    catch { throw "Refusing to overwrite or unable to create probe evidence at $Path : $($_.Exception.Message)" }
    try {
        $writer = [IO.StreamWriter]::new($stream, [Text.UTF8Encoding]::new($true))
        try { $writer.WriteLine($Json) } finally { $writer.Dispose() }
    } finally { $stream.Dispose() }
}

if (-not $SelfTest) { return }

# Offline fixtures only. Retain the entire unique run, including failed parts and a live journal.
$ErrorActionPreference = 'Stop'
function curl.exe { throw 'Offline self-test forbids network transport' }
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('caseops-android-offline-' + [Guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$journalPath = Join-Path $testRoot 'results.jsonl'
$journalStream = [IO.File]::Open($journalPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
$journal = [IO.StreamWriter]::new($journalStream, [Text.UTF8Encoding]::new($false))
$journal.AutoFlush = $true
Write-Output "Offline evidence: $testRoot"

function Assert-Offline($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Assert-OfflineThrows([scriptblock]$Action, [string]$Pattern) {
    try { & $Action | Out-Null } catch {
        if ($_.Exception.Message -notmatch $Pattern) { throw }
        return
    }
    throw "Expected failure matching: $Pattern"
}
function New-OfflineFile([string]$Path, [string]$Text = 'fixture') {
    [IO.Directory]::CreateDirectory((Split-Path -Parent $Path)) | Out-Null
    [IO.File]::WriteAllText($Path, $Text)
}
function New-OfflineZip([string]$Path, [Collections.IDictionary]$Entries) {
    Add-Type -AssemblyName System.IO.Compression
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew)
    $zip = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create)
    try {
        foreach ($name in $Entries.Keys) {
            $writer = [IO.StreamWriter]::new($zip.CreateEntry($name).Open())
            try { $writer.Write($Entries[$name]) } finally { $writer.Dispose() }
        }
    } finally { $zip.Dispose(); $stream.Dispose() }
}
function New-OfflineJdk([string]$Root, [string]$Missing = '') {
    foreach ($name in @('bin/java.exe', 'bin/javac.exe', 'bin/jar.exe', 'lib/modules', 'release')) {
        if ($name -ne $Missing) { New-OfflineFile (Join-Path $Root $name) }
    }
}
function Get-OfflineDownload([string]$Directory, [scriptblock]$Downloader) {
    Get-VerifiedArchive 'https://offline.invalid/archive.zip' 'archive.zip' $fixtureHash $Directory $Downloader
}

$fixture = Join-Path $testRoot 'download-fixture'
New-OfflineFile $fixture 'verified local bytes'
$fixtureHash = (Get-FileHash -LiteralPath $fixture -Algorithm SHA256).Hash
$copyFixture = { param($uri, $part) [IO.File]::Copy($fixture, $part, $true) }
$jdkEntries = [ordered]@{}
foreach ($name in @('bin/java.exe', 'bin/javac.exe', 'bin/jar.exe', 'lib/modules', 'release')) { $jdkEntries['jdk-21/' + $name] = 'fixture' }
$tests = [ordered]@{
    'character-array trimming and single-separator containment' = {
        Assert-OfflineThrows { 'C:\fixture'.TrimEnd('\\', '/') } 'exactly one character'
        Assert-AndroidChildPath (Join-Path $caseRoot 'child') ($caseRoot + '\/')
    }
    'containment rejects root, sibling prefix and traversal' = {
        foreach ($path in @($caseRoot, ($caseRoot + '-sibling/file'), (Join-Path $caseRoot '../outside'))) {
            Assert-OfflineThrows { Assert-AndroidChildPath $path $caseRoot } 'escapes'
        }
    }
    'clean ZIP extraction loads PS5.1 ZipFile assembly' = {
        $archive = Join-Path $caseRoot 'fixture.zip'
        New-OfflineZip $archive ([ordered]@{ 'directory/file.txt' = 'clean' })
        $destination = Join-Path $caseRoot 'extracted'
        Expand-VerifiedArchive $archive $destination
        Assert-Offline ([IO.File]::ReadAllText((Join-Path $destination 'directory/file.txt')) -eq 'clean') 'Clean extraction failed'
    }
    'ZIP rejects forward and backward traversal before writing' = {
        foreach ($entry in @('../escape.txt', '..\escape.txt', '../extracted-sibling/escape.txt')) {
            $archive = Join-Path $caseRoot ([Guid]::NewGuid().ToString('N') + '.zip')
            New-OfflineZip $archive ([ordered]@{ 'safe.txt' = 'safe'; $entry = 'escape' })
            $destination = Join-Path $caseRoot 'extracted'
            Assert-OfflineThrows { Expand-VerifiedArchive $archive $destination } 'escapes'
            Assert-Offline (-not (Test-Path -LiteralPath $destination)) 'Validation wrote extraction files'
        }
        Assert-Offline (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'escape.txt'))) 'ZIP escaped staging'
    }
    'ZIP rejects rooted paths and alternate streams' = {
        foreach ($entry in @('/root.txt', '\root.txt', 'C:\root.txt', 'file.txt:stream')) {
            $archive = Join-Path $caseRoot ([Guid]::NewGuid().ToString('N') + '.zip')
            New-OfflineZip $archive ([ordered]@{ $entry = 'escape' })
            Assert-OfflineThrows { Expand-VerifiedArchive $archive (Join-Path $caseRoot 'extracted') } 'escapes'
        }
    }
    'extraction refuses existing destinations without changing bytes' = {
        $destination = Join-Path $caseRoot 'existing'
        $marker = Join-Path $destination 'retained.txt'
        New-OfflineFile $marker 'original'
        Assert-OfflineThrows { Expand-VerifiedArchive 'unused.zip' $destination } 'Refusing'
        Assert-Offline ([IO.File]::ReadAllText($marker) -eq 'original') 'Existing extraction changed'
    }
    'failed extraction retains already extracted files' = {
        $archive = Join-Path $caseRoot 'broken.zip'
        New-OfflineZip $archive ([ordered]@{ 'first.txt' = 'retained'; 'collision' = 'file'; 'collision/child.txt' = 'blocked' })
        $destination = Join-Path $caseRoot 'partial'
        Assert-OfflineThrows { Expand-VerifiedArchive $archive $destination } 'directory|file|path'
        Assert-Offline ([IO.File]::ReadAllText((Join-Path $destination 'first.txt')) -eq 'retained') 'Partial extraction was lost'
    }
    'download verifies before final cache publication' = {
        $download = { param($uri, $part)
            Assert-Offline (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'archive.zip'))) 'Final cache exists during download'
            Assert-Offline ($part.EndsWith('.part')) 'Download did not use a part file'
            [IO.File]::Copy($fixture, $part, $true)
        }
        $archive = Get-OfflineDownload $caseRoot $download
        Assert-Offline ((Get-FileHash -LiteralPath $archive).Hash -eq $fixtureHash) 'Published bytes not verified'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part').Count -eq 0) 'Successful part not moved'
    }
    'valid cache reuse never calls downloader' = {
        [IO.File]::Copy($fixture, (Join-Path $caseRoot 'archive.zip'))
        $archive = Get-OfflineDownload $caseRoot { throw 'Unexpected downloader call' }
        Assert-Offline ((Get-FileHash -LiteralPath $archive).Hash -eq $fixtureHash) 'Cache reuse failed'
    }
    'interrupted retry uses unique parts and preserves failed bytes' = {
        $state = [pscustomobject]@{ Parts = [Collections.Generic.List[string]]::new() }
        $download = { param($uri, $part)
            $state.Parts.Add($part)
            if ($state.Parts.Count -eq 1) { [IO.File]::WriteAllText($part, 'interrupted'); throw 'Interrupted fixture' }
            [IO.File]::Copy($fixture, $part, $true)
        }
        Get-OfflineDownload $caseRoot $download | Out-Null
        Assert-Offline ($state.Parts.Count -eq 2 -and $state.Parts[0] -ne $state.Parts[1]) 'Retry reused the part file'
        Assert-Offline ([IO.File]::ReadAllText($state.Parts[0]) -eq 'interrupted') 'Interrupted bytes were lost'
    }
    'legacy poisoned final cache is retained and recovered' = {
        New-OfflineFile (Join-Path $caseRoot 'archive.zip') 'old partial'
        $archive = Get-OfflineDownload $caseRoot $copyFixture
        $retained = @(Get-ChildItem -LiteralPath $caseRoot -Filter '*.invalid-*')
        Assert-Offline ($retained.Count -eq 1 -and [IO.File]::ReadAllText($retained[0].FullName) -eq 'old partial') 'Poisoned cache was not retained'
        Assert-Offline ((Get-FileHash -LiteralPath $archive).Hash -eq $fixtureHash) 'Cache recovery failed'
    }
    'hash mismatch retains part and never publishes' = {
        Assert-OfflineThrows { Get-OfflineDownload $caseRoot { param($uri, $part) [IO.File]::WriteAllText($part, 'wrong') } } 'Checksum mismatch'
        Assert-Offline (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'archive.zip'))) 'Bad hash published'
        $parts = @(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part')
        Assert-Offline ($parts.Count -eq 1 -and [IO.File]::ReadAllText($parts[0].FullName) -eq 'wrong') 'Bad hash evidence missing'
    }
    'download exhaustion is bounded and retains every part' = {
        Assert-OfflineThrows { Get-OfflineDownload $caseRoot { param($uri, $part) [IO.File]::WriteAllText($part, 'partial'); throw 'Offline transport failure' } } 'after 3 attempts.*Offline transport failure'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part').Count -eq 3) 'Expected exactly three retained attempts'
        Assert-Offline (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'archive.zip'))) 'Failed download published'
    }
    'concurrent verified cache publication is reused without clobber' = {
        $download = { param($uri, $part)
            [IO.File]::Copy($fixture, $part, $true)
            [IO.File]::Copy($fixture, (Join-Path $caseRoot 'archive.zip'))
        }
        $archive = Get-OfflineDownload $caseRoot $download
        Assert-Offline ((Get-FileHash -LiteralPath $archive).Hash -eq $fixtureHash) 'Competing cache changed'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part').Count -eq 1) 'Competing part was deleted'
    }
    'concurrent invalid cache publication is not overwritten' = {
        $download = { param($uri, $part)
            [IO.File]::Copy($fixture, $part, $true)
            New-OfflineFile (Join-Path $caseRoot 'archive.zip') 'competitor'
        }
        Assert-OfflineThrows { Get-OfflineDownload $caseRoot $download } 'publication failed'
        Assert-Offline ([IO.File]::ReadAllText((Join-Path $caseRoot 'archive.zip')) -eq 'competitor') 'Competing cache overwritten'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part').Count -eq 1) 'Verified part was lost'
    }
    'cache rejects path escape filenames' = {
        Assert-OfflineThrows { Get-VerifiedArchive 'https://offline.invalid' '../escape.zip' $fixtureHash $caseRoot $copyFixture } 'cache filename'
    }
    'default curl wrapper uses bounded HTTPS-only arguments offline' = {
        $state = [pscustomobject]@{ Arguments = @() }
        function curl.exe {
            $state.Arguments = @($args)
            $outputIndex = [array]::IndexOf($state.Arguments, '--output')
            [IO.File]::Copy($fixture, $state.Arguments[$outputIndex + 1], $true)
            $global:LASTEXITCODE = 0
        }
        Get-VerifiedArchive 'https://offline.invalid/archive.zip' 'archive.zip' $fixtureHash $caseRoot | Out-Null
        foreach ($pair in @(@('--connect-timeout', '20'), @('--max-time', '1200'), @('--speed-time', '60'), @('--speed-limit', '1024'), @('--retry', '0'), @('--proto', '=https'), @('--proto-redir', '=https'))) {
            $index = [array]::IndexOf($state.Arguments, $pair[0])
            Assert-Offline ($index -ge 0 -and [string]$state.Arguments[$index + 1] -eq $pair[1]) "Missing curl bound $($pair -join ' ')"
        }
        Assert-Offline ($state.Arguments -contains '--fail' -and $state.Arguments -contains '--location') 'Missing curl status/redirect flags'
    }
    'default curl nonzero status preserves three attempts offline' = {
        function curl.exe {
            $outputIndex = [array]::IndexOf($args, '--output')
            [IO.File]::WriteAllText($args[$outputIndex + 1], 'curl partial')
            $global:LASTEXITCODE = 28
        }
        Assert-OfflineThrows { Get-VerifiedArchive 'https://offline.invalid/archive.zip' 'archive.zip' $fixtureHash $caseRoot } 'after 3 attempts.*exit code 28'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Filter '*.part').Count -eq 3) 'Curl failures lost attempt evidence'
    }
    'JDK validation requires all five nonempty components' = {
        foreach ($missing in @('bin/java.exe', 'bin/javac.exe', 'bin/jar.exe', 'lib/modules', 'release')) {
            $root = Join-Path $caseRoot ([Guid]::NewGuid().ToString('N'))
            New-OfflineJdk $root $missing
            Assert-Offline (-not (Test-AndroidJdk $root)) "Missing $missing accepted"
            New-OfflineFile (Join-Path $root $missing) ''
            Assert-Offline (-not (Test-AndroidJdk $root)) "Empty $missing accepted"
        }
    }
    'complete staged JDK publishes atomically and resolves wrapper' = {
        $archive = Join-Path $caseRoot 'jdk.zip'
        New-OfflineZip $archive $jdkEntries
        $destination = Join-Path $caseRoot 'jdk21'
        $jdk = Install-AndroidJdk $archive $destination
        Assert-Offline ($jdk -eq (Join-Path $destination 'jdk-21')) 'Wrong published JDK'
        Assert-Offline (Test-AndroidJdk $jdk) 'Published JDK incomplete'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter 'jdk21.staging-*').Count -eq 0) 'JDK staging was not moved'
    }
    'incomplete JDK archive stays staged and unpublished' = {
        $archive = Join-Path $caseRoot 'jdk.zip'
        New-OfflineZip $archive ([ordered]@{ 'jdk-21/bin/java.exe' = 'not enough' })
        $destination = Join-Path $caseRoot 'jdk21'
        Assert-OfflineThrows { Install-AndroidJdk $archive $destination } 'complete JDK'
        Assert-Offline (-not (Test-Path -LiteralPath $destination)) 'Incomplete JDK published'
        $staged = @(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter 'jdk21.staging-*')
        Assert-Offline ($staged.Count -eq 1 -and (Test-Path -LiteralPath (Join-Path $staged[0].FullName 'jdk-21/bin/java.exe'))) 'Incomplete staging lost'
    }
    'existing incomplete JDK is preserved and rejected' = {
        $destination = Join-Path $caseRoot 'jdk21'
        $java = Join-Path $destination 'jdk-21/bin/java.exe'
        New-OfflineFile $java 'original incomplete install'
        Assert-OfflineThrows { Install-AndroidJdk 'must-not-open.zip' $destination } 'complete JDK'
        Assert-Offline ([IO.File]::ReadAllText($java) -eq 'original incomplete install') 'Incomplete install changed'
        Assert-Offline (@(Get-ChildItem -LiteralPath $caseRoot -Directory -Filter '*.staging-*').Count -eq 0) 'Existing JDK was extracted over'
    }
    'existing complete JDK is reused without archive access' = {
        New-OfflineJdk (Join-Path $caseRoot 'jdk-21')
        $jdk = Install-AndroidJdk 'must-not-open.zip' $caseRoot
        Assert-Offline ($jdk -eq (Join-Path $caseRoot 'jdk-21')) 'Complete JDK reuse failed'
    }
    'JDK root destination is rejected before archive or directory access' = {
        Assert-OfflineThrows { Install-AndroidJdk 'must-not-open.zip' ([IO.Path]::GetPathRoot($caseRoot)) } 'filesystem root'
    }
    'ambiguous complete JDKs are rejected rather than first-selected' = {
        New-OfflineJdk (Join-Path $caseRoot 'first')
        New-OfflineJdk (Join-Path $caseRoot 'second')
        Assert-OfflineThrows { Get-AndroidJdk $caseRoot } 'found 2'
    }
    'command tools publish within intended SDK boundary' = {
        $archive = Join-Path $caseRoot 'tools.zip'
        New-OfflineZip $archive ([ordered]@{ 'cmdline-tools/bin/sdkmanager.bat' = 'fixture' })
        $sdk = Join-Path $caseRoot 'sdk'
        $tools = Install-AndroidCommandTools $archive $sdk
        Assert-Offline ($tools -eq (Join-Path $sdk 'cmdline-tools/15859902')) 'Wrong command-tools destination'
        Assert-Offline (Test-Path -LiteralPath (Join-Path $tools 'bin/sdkmanager.bat')) 'Command tools not published'
    }
    'existing partial command tools are preserved' = {
        $marker = Join-Path $caseRoot 'cmdline-tools/15859902/partial.txt'
        New-OfflineFile $marker 'original'
        Assert-OfflineThrows { Install-AndroidCommandTools 'must-not-open.zip' $caseRoot } 'incomplete command-tools'
        Assert-Offline ([IO.File]::ReadAllText($marker) -eq 'original') 'Partial command tools changed'
    }
    'incomplete command-tools archive remains staged' = {
        $archive = Join-Path $caseRoot 'tools.zip'
        New-OfflineZip $archive ([ordered]@{ 'cmdline-tools/partial.txt' = 'retained' })
        Assert-OfflineThrows { Install-AndroidCommandTools $archive $caseRoot } 'archive is incomplete'
        Assert-Offline (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'cmdline-tools/15859902'))) 'Incomplete tools published'
        $staged = @(Get-ChildItem -LiteralPath (Join-Path $caseRoot 'cmdline-tools') -Directory -Filter '*.staging-*')
        Assert-Offline ($staged.Count -eq 1 -and (Test-Path -LiteralPath (Join-Path $staged[0].FullName 'cmdline-tools/partial.txt'))) 'Failed tools staging lost'
    }
    'existing command tools are reused without archive access' = {
        New-OfflineFile (Join-Path $caseRoot 'cmdline-tools/15859902/bin/sdkmanager.bat')
        $tools = Install-AndroidCommandTools 'must-not-open.zip' $caseRoot
        Assert-Offline ($tools -eq (Join-Path $caseRoot 'cmdline-tools/15859902')) 'Existing tools reuse failed'
    }
    'selected PATH bins precede old tools even when already present late' = {
        $bins = @('C:\selected\jdk\bin', 'C:\selected\sdk\platform-tools', 'C:\selected\sdk\emulator', 'C:\selected\sdk\cmdline-tools\15859902\bin')
        $old = 'C:\old\bin;C:\Windows;' + ($bins -join ';')
        $actual = Merge-AndroidToolPath $bins $old
        Assert-Offline ($actual -ceq (($bins + @('C:\old\bin', 'C:\Windows')) -join ';')) 'Old PATH precedence survived'
    }
    'PATH merge is idempotent and removes selected-bin variants' = {
        $bins = @('C:\selected\bin', 'C:\sdk\bin')
        $first = Merge-AndroidToolPath $bins 'C:\old\bin;"c:/SELECTED/bin/";C:\SDK\BIN\;C:\selected\bin;;C:\Windows'
        Assert-Offline ($first -ceq 'C:\selected\bin;C:\sdk\bin;C:\old\bin;C:\Windows') 'Selected variants were retained'
        Assert-Offline ((Merge-AndroidToolPath $bins $first) -ceq $first) 'Repeated PATH merge changed value'
        Assert-Offline ((Merge-AndroidToolPath $bins '') -ceq ($bins -join ';')) 'Empty PATH merge failed'
    }
    'probe output creates valid UTF8 JSON' = {
        $path = Join-Path $caseRoot 'probe.json'
        Write-AndroidProbe $path '{"schemaVersion":1}'
        Assert-Offline (([IO.File]::ReadAllText($path) | ConvertFrom-Json).schemaVersion -eq 1) 'New probe JSON invalid'
    }
    'probe output never overwrites existing evidence' = {
        $path = Join-Path $caseRoot 'probe.json'
        New-OfflineFile $path 'original evidence'
        $before = (Get-FileHash -LiteralPath $path).Hash
        Assert-OfflineThrows { Write-AndroidProbe $path '{"replacement":true}' } 'Refusing to overwrite'
        Assert-Offline ((Get-FileHash -LiteralPath $path).Hash -eq $before) 'Existing probe was overwritten'
    }
    'probe output refuses a concurrently owned file' = {
        $path = Join-Path $caseRoot 'probe.json'
        $owner = [IO.File]::Open($path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
        try {
            $bytes = [Text.Encoding]::UTF8.GetBytes('competing writer')
            $owner.Write($bytes, 0, $bytes.Length)
            $owner.Flush()
            Assert-OfflineThrows { Write-AndroidProbe $path 'replacement' } 'Refusing to overwrite'
        } finally { $owner.Dispose() }
        Assert-Offline ([IO.File]::ReadAllText($path) -eq 'competing writer') 'Competing evidence was truncated'
    }
    'actual probe script defeats stale existence checks with offline mocks' = {
        function Get-CimInstance { [pscustomobject]@{ FreeSpace = 1GB; TotalPhysicalMemory = 2GB; Name = 'offline'; HypervisorPresent = $false; VirtualizationFirmwareEnabled = $false } }
        function Get-Process { }
        function Get-Command { }
        $path = Join-Path $caseRoot 'probe.json'
        function Test-Path {
            param([string]$LiteralPath)
            if ($LiteralPath -eq $path) { return $false }
            Microsoft.PowerShell.Management\Test-Path -LiteralPath $LiteralPath
        }
        & (Join-Path $PSScriptRoot 'probe-native.ps1') -OutputPath $path | Out-Null
        $before = (Get-FileHash -LiteralPath $path).Hash
        Assert-OfflineThrows { & (Join-Path $PSScriptRoot 'probe-native.ps1') -OutputPath $path } 'Refusing to overwrite'
        Assert-Offline ((Get-FileHash -LiteralPath $path).Hash -eq $before) 'Probe entry point clobbered evidence'
    }
    'entry points retain official pins and exclude package execution' = {
        $setup = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'setup-android.ps1'))
        Assert-Offline ($setup.Contains('90ae805d20434428bffcb699c290860f19bb5f66a67e6b330067e3de801fb04a')) 'Command-tools pin changed'
        Assert-Offline ($setup.Contains('f9d6e191ab098c0d416e7d588a24420a8621cd2f4720dab2459b8b7b2d2d8b4e')) 'JDK pin changed'
        Assert-Offline ($setup -notmatch '--licenses|--install|&\s*\(') 'Setup executes package/runtime commands'
        foreach ($file in @('setup-android.ps1', 'use-android-env.ps1', 'probe-native.ps1', 'android-tooling.ps1')) {
            $parseErrors = $null
            [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $file), [ref]$null, [ref]$parseErrors) | Out-Null
            Assert-Offline (@($parseErrors).Count -eq 0) "Parser errors in $file : $parseErrors"
        }
        $useEnv = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'use-android-env.ps1'))
        Assert-Offline ($useEnv.Contains('Merge-AndroidToolPath $bins $userPath')) 'Persisted PATH does not use tested prepend'
        $activation = [Management.Automation.Language.Parser]::ParseInput($useEnv, [ref]$null, [ref]$null)
        $persisted = $activation.Find({ param($node) $node -is [Management.Automation.Language.HashtableAst] }, $true)
        $keys = @($persisted.KeyValuePairs | ForEach-Object { $_.Item1.Value } | Sort-Object)
        Assert-Offline (($keys -join ',') -ceq 'ANDROID_HOME,ANDROID_SDK_ROOT,APPIUM_HOME,JAVA_HOME') 'User environment whitelist changed'
        Assert-Offline ($useEnv.Contains('$env:GRADLE_USER_HOME = Join-Path $HOME')) 'Gradle home is not session scoped'
    }
}

$failed = 0
$completed = 0
try {
    $journal.WriteLine((@{ event = 'inventory'; runtime = $PSVersionTable.PSVersion.ToString(); tests = @($tests.Keys) } | ConvertTo-Json -Compress))
    foreach ($name in $tests.Keys) {
        $caseRoot = Join-Path $testRoot ('case-' + ($completed + 1))
        [IO.Directory]::CreateDirectory($caseRoot) | Out-Null
        $journal.WriteLine((@{ event = 'start'; name = $name } | ConvertTo-Json -Compress))
        try {
            & $tests[$name]
            $journal.WriteLine((@{ event = 'result'; name = $name; outcome = 'passed' } | ConvertTo-Json -Compress))
            Write-Output "PASS $name"
        } catch {
            $failed++
            $detail = $_.Exception.ToString() + "`n" + $_.InvocationInfo.PositionMessage + "`n" + $_.ScriptStackTrace
            $journal.WriteLine((@{ event = 'result'; name = $name; outcome = 'failed'; detail = $detail } | ConvertTo-Json -Compress))
            Write-Output "FAIL $name`n$detail"
        }
        $completed++
    }
    $journal.WriteLine((@{ event = 'complete'; selected = $tests.Count; completed = $completed; passed = $completed - $failed; failed = $failed } | ConvertTo-Json -Compress))
} finally { $journal.Dispose(); $journalStream.Dispose() }
Write-Output "Selected=$($tests.Count) Completed=$completed Passed=$($completed - $failed) Failed=$failed Journal=$journalPath"
if ($failed -gt 0 -or $completed -ne $tests.Count) { throw "Offline Android tooling tests failed: $failed / $($tests.Count)" }
