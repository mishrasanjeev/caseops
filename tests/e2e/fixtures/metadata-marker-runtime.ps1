$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# Dependency readiness only. The actual product-source commands and HTTP
# arguments remain in metadata-marker-probes.ps1, inside their original tests.
$Tokens = $null
$ParseErrors = $null
$Ast = [System.Management.Automation.Language.Parser]::ParseInput(
    '$CaseOpsMetadataRuntime = "ready"', [ref]$Tokens, [ref]$ParseErrors
)
if ($ParseErrors.Count -ne 0) { throw 'PowerShell parser is unavailable' }
$Assignments = @($Ast.FindAll({
    param($Node)
    $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $Node.Left.Extent.Text -eq '$CaseOpsMetadataRuntime'
}, $true))
if ($Assignments.Count -ne 1) { throw 'PowerShell AST callback is unavailable' }
$Value = & ([ScriptBlock]::Create('6 * 7'))
if ($Value -ne 42) { throw 'PowerShell script evaluation is unavailable' }
@{
    runtime_version=$PSVersionTable.PSVersion.ToString()
    parser_ready=$true
    ast_callback_ready=$true
    literal_evaluation=$Value
} | ConvertTo-Json -Compress
