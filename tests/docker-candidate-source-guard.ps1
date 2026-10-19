#Requires -Version 5.1
[CmdletBinding()]
param([string]$ScriptPath)

$ErrorActionPreference = "Stop"
# Windows PowerShell leaves $PSScriptRoot empty in param defaults under -File.
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
$Guard = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $Node.Name -eq "Assert-CandidateSourceUnchanged"
}, $true))
if ($Guard.Count -ne 1) { throw "Expected one candidate-source guard." }
. ([scriptblock]::Create($Guard[0].Extent.Text))

$SourceFingerprint = "a" * 64
$ObservedFingerprint = $SourceFingerprint
$ReleaseSha = "1" * 40
$ObservedHead = $ReleaseSha
$RepoRoot = "isolated-guard-test"
function Get-WorkingTreeFingerprint { $script:ObservedFingerprint }
function git {
    $script:LASTEXITCODE = 0
    $script:ObservedHead
}
function Assert-Rejected([string]$ExpectedPrefix) {
    $Rejected = $false
    try { Assert-CandidateSourceUnchanged -Stage "in isolated regression" }
    catch {
        if ($_.Exception.Message -notlike "$ExpectedPrefix*") { throw }
        $Rejected = $true
    }
    if (-not $Rejected) { throw "The changed candidate was incorrectly accepted." }
}

$PreCommit = $true
Assert-CandidateSourceUnchanged -Stage "with stable pre-commit source"
$ObservedFingerprint = "b" * 64
Assert-Rejected "Candidate source changed"
$ObservedFingerprint = $SourceFingerprint
$PreCommit = $false
Assert-CandidateSourceUnchanged -Stage "with stable committed source"
$ObservedHead = "2" * 40
Assert-Rejected "Candidate commit changed"
Write-Host "[docker-acceptance] candidate-source guard: 4 regression cases passed"

$ProjectionGuard = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and
    $Node.Name -eq "Assert-CandidateDataClassProjection"
}, $true))
if ($ProjectionGuard.Count -ne 1) { throw "Expected one candidate data-class projection guard." }
. ([scriptblock]::Create($ProjectionGuard[0].Extent.Text))

$RepoRoot = Join-Path ([IO.Path]::GetTempPath()) "isolated projection candidate with spaces"
$ApiPython = "Invoke-IsolatedProjectionPython"
$ProjectionExitCode = 0
$ProjectionProcessCalls = New-Object 'System.Collections.Generic.List[object]'
function Invoke-IsolatedProjectionPython {
    $script:ProjectionProcessCalls.Add([object[]]$args)
    $script:LASTEXITCODE = $script:ProjectionExitCode
}
function Assert-ProjectionCall {
    if ($ProjectionProcessCalls.Count -ne 1) { throw "Expected exactly one candidate Python call." }
    $Received = @($ProjectionProcessCalls[0])
    $ExpectedScript = Join-Path $RepoRoot "scripts\ip_data_class_projection.py"
    if (
        $Received.Count -ne 2 -or
        $Received[0] -cne $ExpectedScript -or $Received[1] -cne "validate"
    ) {
        throw "Projection guard must pass the absolute candidate script and validate as two exact arguments."
    }
}

# The guard must use this invocation's exit, not a stale native exit code.
$LASTEXITCODE = 91
Assert-CandidateDataClassProjection
Assert-ProjectionCall
foreach ($FailureExit in @(1, 7)) {
    $ProjectionProcessCalls.Clear()
    $ProjectionExitCode = $FailureExit
    $LASTEXITCODE = 0
    $Rejected = $false
    try { Assert-CandidateDataClassProjection }
    catch {
        if ($_.Exception.Message -notlike "Candidate data-class projection validation failed*") { throw }
        $Rejected = $true
    }
    if (-not $Rejected) { throw "Projection validation exit $FailureExit was incorrectly accepted." }
    # No render/repair or second command is permitted after validation fails.
    Assert-ProjectionCall
}

function Test-DriverCommand($Node) {
    $Ancestor = $Node.Parent
    while ($null -ne $Ancestor) {
        if ($Ancestor -is [Management.Automation.Language.FunctionDefinitionAst]) { return $false }
        $Ancestor = $Ancestor.Parent
    }
    return $true
}
$ProjectionInvocation = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.CommandAst] -and
    $Node.GetCommandName() -eq "Assert-CandidateDataClassProjection" -and (Test-DriverCommand $Node)
}, $true))
$DependencySync = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.CommandAst] -and
    $Node.GetCommandName() -eq "uv" -and
    ($Node.CommandElements.Extent.Text -contains "sync") -and (Test-DriverCommand $Node)
}, $true))
$DependencyProbe = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.AssignmentStatementAst] -and
    $Node.Left.Extent.Text -eq '$ApiPackage'
}, $true))
$PackageOwnershipGuard = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.IfStatementAst] -and
    $Node.Extent.Text.Contains('Test-PathWithinRoot -Path $ApiPackage -Root $ApiDir')
}, $true))
$ResourceCommands = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.CommandAst] -and
    $Node.GetCommandName() -eq "docker" -and (Test-DriverCommand $Node) -and
    ($Node.CommandElements.Extent.Text -contains "compose") -and
    (($Node.CommandElements.Extent.Text -contains "down") -or
     ($Node.CommandElements.Extent.Text -contains "build"))
}, $true))
if (
    $ProjectionInvocation.Count -ne 1 -or $DependencySync.Count -ne 1 -or
    $DependencyProbe.Count -ne 1 -or $PackageOwnershipGuard.Count -ne 1 -or
    $ResourceCommands.Count -lt 2
) { throw "Missing or ambiguous driver dependency/projection/resource boundary." }
$FirstResourceCommand = $ResourceCommands | Sort-Object { $_.Extent.StartOffset } | Select-Object -First 1
if (
    $DependencySync[0].Extent.EndOffset -ge $DependencyProbe[0].Extent.StartOffset -or
    $DependencyProbe[0].Extent.EndOffset -ge $PackageOwnershipGuard[0].Extent.StartOffset -or
    $PackageOwnershipGuard[0].Extent.EndOffset -ge $ProjectionInvocation[0].Extent.StartOffset -or
    $ProjectionInvocation[0].Extent.EndOffset -ge $FirstResourceCommand.Extent.StartOffset -or
    -not [object]::ReferenceEquals($ProjectionInvocation[0].Parent.Parent, $DependencyProbe[0].Parent)
) { throw "Projection validation must follow owned API dependency verification before any Compose reset/build." }
$script:LASTEXITCODE = 0
Write-Host "[docker-acceptance] candidate data-class projection guard: 4 regression cases passed (8 total)"
