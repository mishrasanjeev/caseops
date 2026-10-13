#Requires -Version 5.1
[CmdletBinding()]
param([string]$ScriptPath, [Parameter(Mandatory=$true)][string]$EvidenceDirectory)

$ErrorActionPreference = "Stop"
if (-not $ScriptPath) { $ScriptPath = Join-Path $PSScriptRoot "../scripts/verify-docker.ps1" }
$Tokens = $null
$ParseErrors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path -LiteralPath $ScriptPath).Path, [ref]$Tokens, [ref]$ParseErrors
)
if ($ParseErrors.Count) { throw "Release image caller has parse errors." }
$Blocks = @($Ast.FindAll({
    param($Node)
    $Node -is [Management.Automation.Language.ForEachStatementAst] -and
    $Node.Variable.VariablePath.UserPath -eq "Service" -and
    $Node.Extent.Text.Contains('$ImageMetadata')
}, $true))
if ($Blocks.Count -ne 1) { throw "Expected the actual API/web image-resolution caller." }
$ImageCaller = [scriptblock]::Create($Blocks[0].Extent.Text)
$FullId = "sha256:" + ("a" * 64)
$ReleaseSha = "1" * 40
$ComposeProject = "caseops-acceptance-111111111111-aaaaaaaaaaaa"
$ComposeFile = "owned compose with spaces.yml"
$Cases = @(
    @{ Name = "abbreviated-compose-image-resolves-canonical"; Handle = "a" * 12 },
    @{ Name = "bare-full-compose-image-resolves-canonical"; Handle = "a" * 64 },
    @{ Name = "canonical-compose-image-retains-canonical"; Handle = $FullId },
    @{ Name = "invalid-compose-handle-rejected"; Handle = "foreign image"; Error = "image handle" },
    @{ Name = "compose-exit-rejected"; Handle = "a" * 12; Stage = "compose"; Error = "image handle" },
    @{ Name = "inspect-exit-rejected"; Handle = "a" * 12; Stage = "inspect"; Error = "inspection" },
    @{ Name = "empty-inspection-rejected"; Handle = "a" * 12; Count = 0; Error = "inspection" },
    @{ Name = "ambiguous-inspection-rejected"; Handle = "a" * 12; Count = 2; Error = "inspection" },
    @{ Name = "noncanonical-inspected-id-rejected"; Handle = "a" * 12; Id = "a" * 12; Error = "inspection" },
    @{ Name = "wrong-release-image-rejected"; Handle = "a" * 12; Revision = "2" * 40; Error = "does not match" }
)
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
[void][IO.Directory]::CreateDirectory($EvidenceDirectory)
foreach ($Name in @("guard-inventory.json", "guard-results.jsonl", "guard-completion.json")) {
    if (Test-Path -LiteralPath (Join-Path $EvidenceDirectory $Name)) { throw "Refusing to overwrite image guard evidence." }
}
@($Cases.Name) | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDirectory "guard-inventory.json") -Encoding UTF8
function docker {
    $script:Invocations += ,@($args)
    $global:LASTEXITCODE = 0
    if ($args[0] -eq "compose") {
        if ($script:Case.Stage -eq "compose") { $global:LASTEXITCODE = 19 }
        return $script:Case.Handle
    }
    if ($args[0] -eq "image" -and $args[1] -eq "inspect") {
        if ($script:Case.Stage -eq "inspect") { $global:LASTEXITCODE = 19 }
        $Count = if ($script:Case.ContainsKey("Count")) { $script:Case.Count } else { 1 }
        $Id = if ($script:Case.ContainsKey("Id")) { $script:Case.Id } else { $FullId }
        $Revision = if ($script:Case.ContainsKey("Revision")) { $script:Case.Revision } else { $ReleaseSha }
        $Rows = @()
        for ($Index = 0; $Index -lt $Count; $Index++) {
            $Rows += @{ Id = $Id; Config = @{ Labels = @{ "org.opencontainers.image.revision" = $Revision } } }
        }
        return ConvertTo-Json -InputObject $Rows -Depth 5 -Compress
    }
    throw "Unexpected fake Docker invocation."
}
$Failures = 0
foreach ($Case in $Cases) {
    $script:Case = $Case
    $script:Invocations = @()
    $ApiImageId = $null
    $ErrorText = $null
    try { . $ImageCaller } catch { $ErrorText = $_.Exception.Message }
    $Passed = if ($Case.Error) { $ErrorText -and $ErrorText.Contains($Case.Error) } else {
        -not $ErrorText -and $ApiImageId -ceq $FullId -and $script:Invocations.Count -eq 4
    }
    if (-not $Passed) { $Failures++ }
    [ordered]@{ nodeid = $Case.Name; outcome = if ($Passed) { "passed" } else { "failed" };
        error = $ErrorText; api_image_id = $ApiImageId; invocations = $script:Invocations } |
        ConvertTo-Json -Depth 8 -Compress |
        Add-Content -LiteralPath (Join-Path $EvidenceDirectory "guard-results.jsonl") -Encoding UTF8
}
$ExitCode = if ($Failures) { 1 } else { 0 }
[ordered]@{ event = "execution_finished"; tests = $Cases.Count; failures = $Failures; exit_code = $ExitCode } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $EvidenceDirectory "guard-completion.json") -Encoding UTF8
if ($Failures) { throw "$Failures release image caller controls failed." }
Write-Host "[docker-acceptance] release image identity guard: $($Cases.Count) regression cases passed"
