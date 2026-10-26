param([Parameter(Mandatory=$true)][string]$RepoRoot)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Read-SourceAst {
    param([string]$RelativePath)
    $Tokens = $null
    $ParseErrors = $null
    $FullPath = Join-Path $RepoRoot $RelativePath
    $Ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $FullPath, [ref]$Tokens, [ref]$ParseErrors
    )
    if ($ParseErrors.Count -ne 0) { throw "Source parse failed: $RelativePath" }
    return $Ast
}

function Read-ScalarAssignment {
    param($Ast, [string]$Name)
    $Matches = @($Ast.FindAll({
        param($Node)
        $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        $Node.Left.Extent.Text -eq $Name
    }, $true))
    if ($Matches.Count -ne 1) { throw "Expected one scalar assignment: $Name" }
    $Right = $Matches[0].Right
    # Evaluate only the selected scalar, never the operational harness body.
    return & ([ScriptBlock]::Create($Right.Extent.Text))
}

$DockerAst = Read-SourceAst 'scripts/verify-docker.ps1'
$ColdAst = Read-SourceAst 'scripts/verify-api-cold-start.ps1'
$AutomatedTestHeaders = @{}
$HeaderAssignments = @($DockerAst.FindAll({
    param($Node)
    $Node -is [System.Management.Automation.Language.AssignmentStatementAst] -and
    $Node.Left.Extent.Text -eq '$AutomatedTestHeaders'
}, $true))
if ($HeaderAssignments.Count -gt 1) { throw 'Ambiguous metadata header assignment' }
if ($HeaderAssignments.Count -eq 1) {
    $AutomatedTestHeaders = & ([ScriptBlock]::Create($HeaderAssignments[0].Right.Extent.Text))
}

$script:RestCalls = [System.Collections.Generic.List[object]]::new()
function Invoke-RestMethod {
    param([string]$Uri, [hashtable]$Headers = @{}, [int]$TimeoutSec = 0)
    $script:RestCalls.Add(@{uri=$Uri;headers=$Headers;timeout=$TimeoutSec})
    return @{status='ok';release_sha=('a' * 40)}
}
if ((Get-Command Invoke-RestMethod).CommandType -ne 'Function') {
    throw 'Offline REST interceptor is unavailable'
}
$ApiPort = 18001
$WebPort = 18002
$TestApiPort = 18003
$Commands = @($DockerAst.FindAll({
    param($Node)
    $Node -is [System.Management.Automation.Language.CommandAst] -and
    $Node.GetCommandName() -eq 'Invoke-RestMethod'
}, $true))
foreach ($Command in $Commands) {
    $null = & ([ScriptBlock]::Create($Command.Extent.Text))
}
@{
    repo_root=$RepoRoot
    rest_calls=@($script:RestCalls.ToArray())
    server_origin_code=(Read-ScalarAssignment $DockerAst '$ServerOriginProbe')
    cold_health_code=(Read-ScalarAssignment $ColdAst '$HealthProbe')
    operational_harness_executed=$false
} | ConvertTo-Json -Depth 8 -Compress
