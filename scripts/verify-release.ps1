#Requires -Version 5.1
# Canonical release sign-off verification (PowerShell).
# Runs the repo's backend/web verification recipes, checks the deployed
# surface, and writes a Markdown evidence file with a strict verdict.
#
# Usage:
#   ./scripts/verify-release.ps1
#   ./scripts/verify-release.ps1 -ExpectedCommit a44ea31
#   ./scripts/verify-release.ps1 -SkipBackend -SkipWeb
#   ./scripts/verify-release.ps1 -BuildInfoUrl https://api.caseops.ai/api/build

[CmdletBinding(PositionalBinding=$false)]
param(
    [string]$ExpectedCommit = "",
    [string]$ApiHealthUrl = "https://api.caseops.ai/api/health",
    [string]$WebUrl = "https://caseops.ai/",
    [string]$CodeAvailableUrl = "https://api.caseops.ai/api/matters/code-available?code=RELEASE-SIGNOFF-TEST",
    [string]$RemindersUrl = "https://api.caseops.ai/api/matters/00000000-0000-0000-0000-000000000000/reminders",
    [string]$BuildInfoUrl = "",
    [string]$EvidencePath = "",
    [string[]]$BackendArgs = @(),
    [string[]]$WebArgs = @(),
    [switch]$SkipBackend,
    [switch]$SkipWeb,
    [switch]$SkipProd
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = `
    [Net.ServicePointManager]::SecurityProtocol -bor `
    [Net.SecurityProtocolType]::Tls12

$RepoRoot = Resolve-Path "$PSScriptRoot\.."
Set-Location $RepoRoot

if (-not $ExpectedCommit) {
    $ExpectedCommit = (& git rev-parse --short HEAD).Trim()
}
$GitHead = (& git rev-parse HEAD).Trim()
$GeneratedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

if (-not $EvidencePath) {
    $stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
    $EvidencePath = Join-Path $RepoRoot "docs\runbooks\release-signoff-$stamp.md"
} elseif (-not [System.IO.Path]::IsPathRooted($EvidencePath)) {
    $EvidencePath = Join-Path $RepoRoot $EvidencePath
}

$EvidenceDir = Split-Path -Parent $EvidencePath
if (-not (Test-Path $EvidenceDir)) {
    New-Item -ItemType Directory -Path $EvidenceDir | Out-Null
}

$Checks = New-Object System.Collections.Generic.List[object]
$Caveats = New-Object System.Collections.Generic.List[string]

function New-CheckResult {
    param(
        [string]$Name,
        [string]$Command,
        [string]$Result,
        [string]$Note
    )

    [pscustomobject]@{
        Name = $Name
        Command = $Command
        Result = $Result
        Note = $Note
    }
}

function Add-Caveat {
    param([string]$Message)

    if ($Message) {
        $script:Caveats.Add($Message)
    }
}

function Invoke-CommandCheck {
    param(
        [string]$Name,
        [string]$Command,
        [scriptblock]$Runner
    )

    Write-Host "[verify-release] $Name"
    & $Runner
    $exitCode = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
    $result = if ($exitCode -eq 0) { "pass" } else { "fail" }
    $note = "exit code $exitCode"
    return (New-CheckResult -Name $Name -Command $Command -Result $result -Note $note)
}

function Invoke-UrlCheck {
    param(
        [string]$Name,
        [string]$Url,
        [int]$ExpectedStatus
    )

    $status = $null
    $body = ""
    $errorText = ""

    $scratchDir = Join-Path $RepoRoot ".tmp-release"
    if (-not (Test-Path $scratchDir)) {
        New-Item -ItemType Directory -Path $scratchDir | Out-Null
    }

    $bodyFile = Join-Path $scratchDir ([Guid]::NewGuid().ToString() + ".body.txt")
    $stdoutFile = Join-Path $scratchDir ([Guid]::NewGuid().ToString() + ".stdout.txt")
    $stderrFile = Join-Path $scratchDir ([Guid]::NewGuid().ToString() + ".stderr.txt")

    try {
        $curlExe = (Get-Command curl.exe -ErrorAction Stop).Source
        $process = Start-Process -FilePath $curlExe `
            -ArgumentList @("-sS", "-L", "-o", $bodyFile, "-w", "%{http_code}", $Url) `
            -NoNewWindow `
            -PassThru `
            -Wait `
            -RedirectStandardOutput $stdoutFile `
            -RedirectStandardError $stderrFile
        $statusText = ""
        if (Test-Path $stdoutFile) {
            $statusText = [System.IO.File]::ReadAllText($stdoutFile).Trim()
        }
        if (Test-Path $bodyFile) {
            $body = [System.IO.File]::ReadAllText($bodyFile)
        }
        if (Test-Path $stderrFile) {
            $errorText = [System.IO.File]::ReadAllText($stderrFile).Trim()
        }
        if ($statusText -match "^\d{3}$") {
            $status = [int]$statusText
        } elseif ($process.ExitCode -ne 0) {
            $status = 0
        }
    } finally {
        if (Test-Path $bodyFile) {
            Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $stdoutFile) {
            Remove-Item -LiteralPath $stdoutFile -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path $stderrFile) {
            Remove-Item -LiteralPath $stderrFile -Force -ErrorAction SilentlyContinue
        }
    }

    $note = if ($body) { $body } else { $errorText }
    $note = $note.Replace("`r", " ").Replace("`n", " ").Trim()
    if ($note.Length -gt 180) {
        $note = $note.Substring(0, 180)
    }

    $result = if ($status -eq $ExpectedStatus) { "pass" } else { "fail" }
    return [pscustomobject]@{
        Name = $Name
        Command = $Url
        Result = $result
        Note = "expected $ExpectedStatus, actual $status; $note".Trim()
        Status = $status
        Body = $body
    }
}

if ($SkipBackend) {
    $Checks.Add((New-CheckResult -Name "Backend verification" -Command "scripts/verify-backend.ps1" -Result "skipped" -Note "Skipped by caller"))
    Add-Caveat "Backend verification was skipped."
} else {
    $backendCommand = "scripts/verify-backend.ps1" + ($(if ($BackendArgs.Count) { " " + ($BackendArgs -join " ") } else { "" }))
    $Checks.Add((Invoke-CommandCheck -Name "Backend verification" -Command $backendCommand -Runner {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$RepoRoot\scripts\verify-backend.ps1" @BackendArgs
    }))
}

if ($SkipWeb) {
    $Checks.Add((New-CheckResult -Name "Web verification" -Command "scripts/verify-web.ps1" -Result "skipped" -Note "Skipped by caller"))
    Add-Caveat "Web verification was skipped."
} else {
    $webCommand = "scripts/verify-web.ps1" + ($(if ($WebArgs.Count) { " " + ($WebArgs -join " ") } else { "" }))
    $Checks.Add((Invoke-CommandCheck -Name "Web verification" -Command $webCommand -Runner {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$RepoRoot\scripts\verify-web.ps1" @WebArgs
    }))
}

if ($SkipProd) {
    $Checks.Add((New-CheckResult -Name "Production smoke checks" -Command "prod urls" -Result "skipped" -Note "Skipped by caller"))
    Add-Caveat "Production smoke checks were skipped."
} else {
    $Checks.Add((Invoke-UrlCheck -Name "API health" -Url $ApiHealthUrl -ExpectedStatus 200))
    $Checks.Add((Invoke-UrlCheck -Name "Web root" -Url $WebUrl -ExpectedStatus 200))
    $Checks.Add((Invoke-UrlCheck -Name "Code available endpoint (unauthenticated)" -Url $CodeAvailableUrl -ExpectedStatus 401))
    $Checks.Add((Invoke-UrlCheck -Name "Reminders endpoint (unauthenticated)" -Url $RemindersUrl -ExpectedStatus 401))
}

if ($BuildInfoUrl) {
    $buildCheck = Invoke-UrlCheck -Name "Build fingerprint" -Url $BuildInfoUrl -ExpectedStatus 200
    if ($buildCheck.Result -eq "pass" -and $buildCheck.Body -and $buildCheck.Body -match [regex]::Escape($ExpectedCommit)) {
        $buildCheck = New-CheckResult -Name "Build fingerprint" -Command $BuildInfoUrl -Result "pass" -Note "Response contains expected commit $ExpectedCommit"
    } elseif ($buildCheck.Result -eq "pass") {
        $buildCheck = New-CheckResult -Name "Build fingerprint" -Command $BuildInfoUrl -Result "caveat" -Note "Endpoint responded 200 but did not prove expected commit $ExpectedCommit"
        Add-Caveat "Build fingerprint endpoint did not prove the expected commit."
    } else {
        $buildCheck = New-CheckResult -Name "Build fingerprint" -Command $BuildInfoUrl -Result "caveat" -Note $buildCheck.Note
        Add-Caveat "Build fingerprint endpoint could not be verified."
    }
    $Checks.Add($buildCheck)
} else {
    $Checks.Add((New-CheckResult -Name "Build fingerprint" -Command "(not supplied)" -Result "caveat" -Note "No build info URL supplied; deployed commit not proven from live surface"))
    Add-Caveat "No build fingerprint URL supplied; deployed commit not proven from the live surface."
}

$hasFail = $false
$hasCaveat = $false
foreach ($check in $Checks) {
    if ($check.Result -eq "fail") {
        $hasFail = $true
    }
    if ($check.Result -in @("skipped", "caveat")) {
        $hasCaveat = $true
    }
}

$Verdict = if ($hasFail) {
    "NO-GO"
} elseif ($hasCaveat -or $Caveats.Count -gt 0) {
    "GO with caveat"
} else {
    "GO"
}

function Escape-MarkdownCell {
    param([string]$Text)

    if (-not $Text) {
        return ""
    }
    return $Text.Replace("|", "\|").Replace("`r", " ").Replace("`n", " ")
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Release Sign-Off Evidence")
$lines.Add("")
$tick = [char]96
$lines.Add("- Generated at: " + $tick + $GeneratedAt + $tick)
$lines.Add("- Target commit: " + $tick + $ExpectedCommit + $tick)
$lines.Add("- Local git HEAD: " + $tick + $GitHead + $tick)
$lines.Add("- Verdict: " + $tick + $Verdict + $tick)
$lines.Add("")
$lines.Add("## Checks")
$lines.Add("")
$lines.Add("| Check | Command / URL | Result | Notes |")
$lines.Add("| --- | --- | --- | --- |")
foreach ($check in $Checks) {
    $lines.Add("| $(Escape-MarkdownCell $check.Name) | $(Escape-MarkdownCell $check.Command) | $(Escape-MarkdownCell $check.Result) | $(Escape-MarkdownCell $check.Note) |")
}
$lines.Add("")
$lines.Add("## Caveats")
$lines.Add("")
if ($Caveats.Count -eq 0) {
    $lines.Add("- None")
} else {
    foreach ($caveat in $Caveats) {
        $lines.Add("- $caveat")
    }
}
$lines.Add("")
$lines.Add("## Reviewer Notes")
$lines.Add("")
$lines.Add("- Add any manual observations, screenshots, or deployment metadata here.")

[System.IO.File]::WriteAllLines($EvidencePath, $lines)

Write-Host "[verify-release] evidence written to $EvidencePath"
Write-Host "[verify-release] verdict: $Verdict"

if ($Verdict -eq "NO-GO") {
    exit 1
}
exit 0
