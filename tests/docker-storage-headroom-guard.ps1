#Requires -Version 5.1
[CmdletBinding()]
param([string]$ScriptPath, [string]$EvidenceDirectory)
$ErrorActionPreference = 'Stop'
if (-not $ScriptPath) { $ScriptPath = Join-Path $PSScriptRoot '../scripts/verify-docker.ps1' }
$Tokens = $null
$Errors = $null
$Ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path -LiteralPath $ScriptPath).Path, [ref]$Tokens, [ref]$Errors)
if ($Errors.Count) { throw 'Docker verifier has parse errors.' }
$Definition = @($Ast.FindAll({ param($Node)
    $Node -is [Management.Automation.Language.FunctionDefinitionAst] -and $Node.Name -eq 'Assert-DockerStorageHeadroom'
}, $true))
if ($Definition.Count -ne 1) { throw 'Expected the actual storage admission function.' }
. ([scriptblock]::Create($Definition[0].Extent.Text))
$Work = Join-Path ([IO.Path]::GetTempPath()) ('caseops-storage-guard-' + [Guid]::NewGuid().ToString('N'))
$Retain = [bool]$EvidenceDirectory
if (-not $Retain) { $EvidenceDirectory = $Work }
[void][IO.Directory]::CreateDirectory($EvidenceDirectory)
$ResultsDirectory = Join-Path $EvidenceDirectory 'stage-receipts'
[void][IO.Directory]::CreateDirectory($ResultsDirectory)
$ComposeProject = 'caseops-acceptance-111111111111-aaaaaaaaaaaa'
$ReleaseSha = '1' * 40
$ComposeFile = 'C:/owned directory/compose file.yml'
$ApiPython = 'Invoke-OfflineStorageProbe'
function docker { throw 'Real Docker is forbidden in this offline guard.' }
function Invoke-OfflineStorageProbe {
    $Code = $input | Out-String
    if ($args.Count -ne 8 -or ($args[0..3] -join ',') -cne '-I,-S,-B,-' -or
        $args[4] -cne $ComposeProject -or $args[5] -cne $ReleaseSha -or $args[7] -cne $ComposeFile -or
        -not $Code.Contains('os.statvfs') -or -not $Code.Contains("'--network=none'")) {
        throw 'Probe escaped its exact isolated native arguments/stdin.'
    }
    $script:Calls++
    if ($Case -eq 'native-exception') { throw 'Offline process-start exception' }
    $global:LASTEXITCODE = if ($Case -eq 'native-failure') { 19 } else { 0 }
    if ($Case -eq 'malformed-json') { return 'not JSON' }
    $Rows = @(@{ path='/'; available_bytes=[long]68719476736; free_inodes=100000 })
    if ($Stage -in @('pre-postgres', 'pre-browser')) {
        $Rows += @{ path='/var/lib/postgresql/data'; available_bytes=[long]68719476736; free_inodes=100000 }
    }
    switch ($Case) {
        'low-bytes' { $Rows[0].available_bytes-- }
        'low-inodes' { $Rows[0].free_inodes-- }
        'string-bytes' { $Rows[0].available_bytes='68719476736' }
        'float-inodes' { $Rows[0].free_inodes=100000.5 }
        'negative-inodes' { $Rows[0].free_inodes=-1 }
        'wrong-path' { $Rows[0].path='C:/' }
        'missing-pg-volume' { $Rows=@($Rows[0]) }
        'low-pg-volume' { $Rows[1].available_bytes=0 }
    }
    $Value = @{ version=1; project=$ComposeProject; release_sha=$ReleaseSha; stage=$Stage;
        minimum_bytes=[long]68719476736; minimum_inodes=100000; status='passed';
        cleanup_complete=$true; filesystems=$Rows }
    if ($Case -eq 'wrong-release') { $Value.release_sha='2' * 40 }
    if ($Case -eq 'cleanup-failed') { $Value.cleanup_complete=$false }
    if ($Case -eq 'missing-result') { $Value.Remove('filesystems') }
    $Value | ConvertTo-Json -Depth 7 -Compress
}
$Cases = @('exact-threshold', 'post-build', 'owned-pg-volume', 'browser-volume',
    'low-bytes', 'low-inodes', 'native-failure', 'native-exception', 'malformed-json', 'string-bytes',
    'float-inodes', 'negative-inodes', 'wrong-path', 'missing-pg-volume', 'low-pg-volume',
    'wrong-release', 'cleanup-failed', 'missing-result')
try {
    foreach ($Name in @('guard-inventory.json', 'guard-results.jsonl', 'guard-completion.json')) {
        if (Test-Path -LiteralPath (Join-Path $EvidenceDirectory $Name)) { throw 'Refusing to replace guard evidence.' }
    }
    ConvertTo-Json -InputObject $Cases | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'guard-inventory.json') -Encoding UTF8
    foreach ($Case in $Cases) {
        $Stage = switch ($Case) {
            'post-build' { 'post-build' }
            'owned-pg-volume' { 'pre-postgres' }
            { $_ -in @('browser-volume', 'missing-pg-volume', 'low-pg-volume') } { 'pre-browser' }
            default { 'pre-build' }
        }
        $script:Calls = $script:Expensive = 0
        $ErrorText = $null
        try { Assert-DockerStorageHeadroom -Stage $Stage; $script:Expensive++ }
        catch { $ErrorText=$_.Exception.Message }
        $ExpectedPass = $Case -in @('exact-threshold', 'post-build', 'owned-pg-volume', 'browser-volume')
        $Passed = $script:Calls -eq 1 -and (($ExpectedPass -and -not $ErrorText -and $script:Expensive -eq 1) -or
            (-not $ExpectedPass -and $ErrorText -like '*headroom admission refused*' -and $script:Expensive -eq 0))
        @{ nodeid=$Case; outcome=if ($Passed) {'passed'} else {'failed'}; error=$ErrorText; expensive_calls=$script:Expensive } |
            ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $EvidenceDirectory 'guard-results.jsonl') -Encoding UTF8
        if (-not $Passed) { throw "Storage guard control failed: $Case" }
    }
    @{ event='execution_finished'; tests=$Cases.Count; failures=0; exit_code=0 } | ConvertTo-Json |
        Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'guard-completion.json') -Encoding UTF8
    $global:LASTEXITCODE=0
    Write-Host "[docker-acceptance] storage headroom guard: $($Cases.Count) regression cases passed"
} finally {
    if (-not $Retain -and (Test-Path -LiteralPath $Work)) {
        $FullWork = [IO.Path]::GetFullPath($Work)
        $TempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd([char[]]'\/') + [IO.Path]::DirectorySeparatorChar
        if (-not $FullWork.StartsWith($TempRoot, [StringComparison]::OrdinalIgnoreCase) -or
            [IO.Path]::GetFileName($FullWork) -notlike 'caseops-storage-guard-*') { throw 'Unsafe offline guard cleanup path.' }
        Remove-Item -LiteralPath $FullWork -Recurse -Force
    }
}
