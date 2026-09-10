param(
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string[]]$Tests
)
$ErrorActionPreference = 'Stop'
if ($Label -notmatch '^[a-z0-9-]+$') { throw 'Use a simple unique run label.' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output = Join-Path $root 'docs/ip-implementation/evidence/other-ip-resume-2026-09-10'
$scratch = "C:/tmp/oip-resume-0910-$Label"
if ((Test-Path -LiteralPath $scratch) -or (Test-Path -LiteralPath "$output/$Label.jsonl")) {
    throw 'Run labels cannot reuse or erase prior evidence.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (Join-Path $root '.other-ip-test/deps')
$env:CASEOPS_TEST_RESULT_JOURNAL = "$output/$Label.jsonl"
$env:CASEOPS_ENV = 'local'
$env:CASEOPS_LLM_PROVIDER = 'mock'
$env:CASEOPS_EMBEDDING_PROVIDER = 'mock'
$env:CASEOPS_TEST_POSTGRES_URL = ''
$env:OMP_NUM_THREADS = '1'
$env:HF_HUB_OFFLINE = '1'
Push-Location (Join-Path $root 'apps/api')
try {
    foreach ($selection in $Tests) {
        if (-not (Test-Path -LiteralPath ($selection -split '::')[0])) { throw "Missing test: $selection" }
    }
    & $Python -B -m pytest -q -p no:cacheprovider --tb=short "--basetemp=$scratch" "--junitxml=$output/$Label.xml" @Tests 2>&1 |
        Tee-Object -FilePath "$output/$Label.log"
    $code = $LASTEXITCODE
    if (-not (Test-Path -LiteralPath "$output/$Label.jsonl")) { throw "Pytest did not initialize its journal; inspect $Label.log (exit $code)." }
    $events = @(Get-Content -LiteralPath "$output/$Label.jsonl" | ConvertFrom-Json)
    $nodes = @($events | Where-Object event -eq 'collection' | ForEach-Object nodeids)
    foreach ($selection in $Tests) {
        $prefix = $selection.Replace('\', '/')
        if (-not @($nodes | Where-Object { $_ -eq $prefix -or $_.StartsWith($prefix + '::') -or $_.StartsWith($prefix + '[') }).Count) {
            throw "Selection was not collected: $selection"
        }
    }
    if (-not @($events | Where-Object event -eq 'session_finished').Count) { throw 'Incomplete pytest session.' }
    foreach ($node in $nodes) {
        $phases = @($events | Where-Object { $_.event -eq 'test_report' -and $_.nodeid -eq $node })
        if (-not ($phases.when -contains 'setup') -or -not ($phases.when -contains 'teardown')) { throw "Incomplete phases: $node" }
        if (($phases | Where-Object { $_.when -eq 'setup' -and $_.outcome -eq 'passed' }) -and -not ($phases.when -contains 'call')) { throw "Missing call phase: $node" }
    }
    Write-Output "Reconciled $($nodes.Count) collected identities and their phases. Exit $code."
    exit $code
} finally { Pop-Location }
