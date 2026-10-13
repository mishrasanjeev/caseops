#Requires -Version 5.1
[CmdletBinding()]
param([string]$ScriptPath, [string]$EvidenceDirectory)

$ErrorActionPreference = "Stop"
if (-not $ScriptPath) {
    $ScriptPath = [IO.Path]::Combine(
        (Split-Path -Parent $MyInvocation.MyCommand.Path), "..", "scripts", "verify-docker.ps1"
    )
}
$Tokens = $null
$ParseErrors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $ScriptPath).Path, [ref]$Tokens, [ref]$ParseErrors
)
if ($ParseErrors.Count) { throw "Docker acceptance script has PowerShell parse errors." }
$CaptureFunction = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $Node.Name -eq "Save-DockerAcceptanceFailureEvidence"
}, $true))
if ($CaptureFunction.Count -ne 1) { throw "Expected one failure evidence function." }
$MainTry = @($Ast.EndBlock.Statements | Where-Object {
    $_ -is [Management.Automation.Language.TryStatementAst]
})
if ($MainTry.Count -ne 1 -or -not $MainTry[0].Finally) { throw "Expected one standard cleanup block." }
$Cleanup = [scriptblock]::Create(($MainTry[0].Finally.Statements.Extent.Text -join "`n"))
$Work = Join-Path ([IO.Path]::GetTempPath()) ("caseops-evidence-guard-" + [Guid]::NewGuid().ToString("N"))
[void][IO.Directory]::CreateDirectory($Work)
$RetainEvidence = [bool]$EvidenceDirectory
if (-not $EvidenceDirectory) { $EvidenceDirectory = Join-Path $Work "evidence" }
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
[void][IO.Directory]::CreateDirectory($EvidenceDirectory)
$Journal = Join-Path $EvidenceDirectory "guard-results.jsonl"
$InventoryPath = Join-Path $EvidenceDirectory "guard-inventory.json"
$CompletionPath = Join-Path $EvidenceDirectory "guard-completion.json"
foreach ($Path in @($Journal, $InventoryPath, $CompletionPath)) {
    if (Test-Path -LiteralPath $Path) { throw "Refusing to overwrite guard evidence: $Path" }
}
$Cases = @(
    "bounded-safe-capture-before-owned-cleanup",
    "logs-exit-is-separate-and-state-still-captured",
    "logs-exception-is-separate-and-state-still-captured",
    "inventory-exit-is-separate",
    "invalid-container-id-never-inspected",
    "container-inventory-is-bounded",
    "state-exit-is-separate",
    "manifest-io-error-preserves-primary-exception",
    "capture-exception-preserves-primary-exception",
    "repeated-capture-never-overwrites-evidence"
)
[IO.File]::WriteAllText($InventoryPath, (ConvertTo-Json -InputObject $Cases))
$ReleaseSha = "1" * 40
$ComposeProject = "caseops-acceptance-111111111111-aaaaaaaaaaaa"
$ComposeFile = Join-Path $Work "compose with spaces.yml"
$TestApiProxyProcess = $null
$Succeeded = $false
$KeepRunning = $false
$AcceptanceEnvironment = @{}
$PreviousEnvironment = @{}
$InitialLocation = (Get-Location).Path

function Assert-Guard([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}

function Set-Content {
    [CmdletBinding()]
    param([Parameter(ValueFromPipeline=$true)]$Value, [string]$LiteralPath, [string]$Encoding)
    begin { $Values = New-Object 'System.Collections.Generic.List[object]' }
    process { $Values.Add($Value) }
    end {
        if ($Case -eq "manifest-io-error-preserves-primary-exception" -and $LiteralPath.EndsWith(".capture.json")) {
            throw "fake manifest I/O failure"
        }
        Microsoft.PowerShell.Management\Set-Content -LiteralPath $LiteralPath -Value $Values.ToArray() -Encoding $Encoding
    }
}

function docker {
    $Arguments = @($args)
    $Stage = if ($Arguments -contains "logs") { "logs" }
        elseif ($Arguments -contains "ps") { "inventory" }
        elseif ($Arguments[0] -eq "inspect") { "state" }
        elseif ($Arguments -contains "down") { "cleanup" }
        else { throw "Unexpected Docker arguments: $Arguments" }
    $script:Invocations.Add(@{ stage = $Stage; arguments = $Arguments })
    $global:LASTEXITCODE = 0
    if ($Stage -ne "state") {
        Assert-Guard ($Arguments -contains $ComposeProject -and $Arguments -contains $ComposeFile) "Capture escaped the owned project/file."
    }
    if ($Stage -eq "logs") {
        Assert-Guard ($Arguments -contains "1000" -and $Arguments -contains "--tail" -and
            $Arguments -contains "--timestamps" -and $Arguments -contains "--no-color") "Logs are unbounded or lack timestamp/plain output."
        Assert-Guard (($Arguments[-7..-1] -join ',') -eq "api,web,migrate,worker,postgres,valkey,acceptance-case-provider") "Unexpected log service inventory."
        if ($Case -eq "logs-exception-is-separate-and-state-still-captured") { throw "fake logs exception" }
        "api | 2026-10-11T00:00:00Z retained bounded diagnostic"
        if ($Case -eq "logs-exit-is-separate-and-state-still-captured") { $global:LASTEXITCODE = 23 }
    } elseif ($Stage -eq "inventory") {
        Assert-Guard ($Arguments -contains "--all" -and $Arguments -contains "--quiet") "Capture requested a verbose container dump."
        if ($Case -eq "inventory-exit-is-separate") { $global:LASTEXITCODE = 24; return }
        if ($Case -eq "invalid-container-id-never-inspected") { "foreign; injected"; return }
        if ($Case -eq "container-inventory-is-bounded") {
            foreach ($Index in 1..17) { "{0:x12}" -f $Index }
            return
        }
        "a" * 64
    } elseif ($Stage -eq "state") {
        Assert-Guard ($Arguments.Count -eq 4 -and $Arguments[1] -eq "--format" -and $Arguments[3] -ceq ("a" * 64)) "Inspect was not bounded to the owned inventory."
        $Format = $Arguments[2]
        Assert-Guard ($Format -notmatch 'Config|Health|Error|Command|Args' -and
            $Format.Contains("{{.Image}}") -and $Format.Contains("{{.State.OOMKilled}}") -and
            $Format.Contains("{{.State.ExitCode}}")) "Inspect requested unsafe or incomplete fields."
        "$($Arguments[3])`t/owned-api`tsha256:$('b' * 64)`texited`tfalse`tfalse`tfalse`ttrue`tfalse`t137`t2026-10-11T00:00:00Z`t2026-10-11T00:01:00Z"
        if ($Case -eq "state-exit-is-separate") { $global:LASTEXITCODE = 25 }
    } else {
        Assert-Guard ($Arguments -contains "acceptance" -and $Arguments -contains "--volumes" -and
            $Arguments -contains "--remove-orphans") "Cleanup did not retain its owned acceptance profile."
        $script:CleanupCalls++
    }
}

function Invoke-FailedGate {
    $script:FailureEvidenceAttempted = $false
    $global:LASTEXITCODE = 19
    Push-Location -LiteralPath $Work
    $OriginalError = $null
    try {
        try { throw "original gate failure" }
        finally { & $Cleanup }
    }
    catch { $OriginalError = $_.Exception.Message }
    Assert-Guard ($OriginalError -ceq "original gate failure") "Capture replaced the primary gate exception: $OriginalError"
    Assert-Guard ((Get-Location).Path -eq $InitialLocation) "Cleanup did not restore caller location."
    Assert-Guard ($script:Invocations[-1].stage -eq "cleanup") "Owned cleanup did not run after capture."
}

$Passed = 0
$CaseOrdinal = 0
try {
    foreach ($Case in $Cases) {
        . ([scriptblock]::Create($CaptureFunction[0].Extent.Text))
        if ($Case -eq "capture-exception-preserves-primary-exception") {
            function Save-DockerAcceptanceFailureEvidence { throw "fake capture exception" }
        }
        # Keep Windows PowerShell 5.1 paths bounded; full identities stay in journals.
        $ResultsDirectory = Join-Path $EvidenceDirectory ("c{0:D2}" -f $CaseOrdinal)
        $CaseOrdinal++
        [void][IO.Directory]::CreateDirectory($ResultsDirectory)
        $Invocations = New-Object 'System.Collections.Generic.List[object]'
        $CleanupCalls = 0
        $Outcome = "failed"
        try {
            Invoke-FailedGate
            Assert-Guard ($CleanupCalls -eq 1) "Cleanup was omitted or duplicated."
            $Manifests = @(Get-ChildItem -LiteralPath $ResultsDirectory -Filter "*.capture.json")
            if ($Case -notin @("manifest-io-error-preserves-primary-exception", "capture-exception-preserves-primary-exception")) {
                Assert-Guard ($Manifests.Count -eq 1) "Missing capture manifest."
                $Manifest = Get-Content -LiteralPath $Manifests[0].FullName -Raw | ConvertFrom-Json
                $ShouldFail = $Case -notin @("bounded-safe-capture-before-owned-cleanup", "repeated-capture-never-overwrites-evidence")
                $ExpectedEvent = if ($ShouldFail) { "failure_capture_failed" } else { "failure_capture_finished" }
                Assert-Guard ($Manifest.event -eq $ExpectedEvent -and [bool]$Manifest.errors.Count -eq $ShouldFail) "Capture failure was not classified separately."
            } else {
                Assert-Guard ($Manifests.Count -eq 0) "Failed capture was falsely marked complete."
            }
            if ($Case -in @("invalid-container-id-never-inspected", "container-inventory-is-bounded", "inventory-exit-is-separate")) {
                Assert-Guard (@($Invocations | Where-Object { $_.stage -eq "state" }).Count -eq 0) "Invalid container inventory reached inspect."
            }
            if ($Case -eq "repeated-capture-never-overwrites-evidence") {
                $OriginalBytes = [Convert]::ToBase64String([IO.File]::ReadAllBytes($Manifests[0].FullName))
                Invoke-FailedGate
                Assert-Guard (@(Get-ChildItem -LiteralPath $ResultsDirectory -Filter "*.capture.json").Count -eq 2 -and
                    [Convert]::ToBase64String([IO.File]::ReadAllBytes($Manifests[0].FullName)) -ceq $OriginalBytes) "Repeated capture overwrote prior evidence."
            }
            $Passed++
            $Outcome = "passed"
        }
        finally {
            $Row = @{ event = "case_report"; nodeid = $Case; outcome = $Outcome; invocations = @($Invocations.ToArray()) }
            [IO.File]::AppendAllText($Journal, (($Row | ConvertTo-Json -Depth 8 -Compress) + "`n"))
        }
    }
    Assert-Guard ($Passed -eq $Cases.Count) "Incomplete failure evidence guard inventory."
    [IO.File]::WriteAllText($CompletionPath, (@{ event = "execution_finished"; tests = $Passed; exit_code = 0 } | ConvertTo-Json))
    Write-Host "[docker-acceptance] failure evidence guard: $Passed regression cases passed"
}
finally {
    $FullWork = [IO.Path]::GetFullPath($Work)
    $FullTemp = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]"\/") + [IO.Path]::DirectorySeparatorChar
    if (-not $FullWork.StartsWith($FullTemp, [StringComparison]::OrdinalIgnoreCase) -or
        ($RetainEvidence -and ([IO.Path]::GetFullPath($EvidenceDirectory)).StartsWith($FullWork + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) {
        throw "Guard cleanup escaped its temp root or would delete retained evidence."
    }
    Remove-Item -LiteralPath $FullWork -Recurse -Force
}
