#Requires -Version 5.1
[CmdletBinding()]
param(
    [string]$ScriptPath = (Join-Path $PSScriptRoot "..\scripts\verify-docker.ps1")
)

$ErrorActionPreference = "Stop"
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
