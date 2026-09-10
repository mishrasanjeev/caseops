param([Parameter(Mandatory=$true)][string]$Label, [Parameter(Mandatory=$true)][string[]]$Tests)
$ErrorActionPreference = 'Stop'
if ($Label -notmatch '^[a-z0-9-]+$') { throw 'Use a new simple run label.' }
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$output = Join-Path $root 'docs/ip-implementation/evidence/other-ip-domain-workflows-2026-09-10-v2'
[IO.Directory]::CreateDirectory($output) | Out-Null
$journal = Join-Path $output "$Label-launch.jsonl"
$writer = [IO.StreamWriter]::new([IO.File]::Open($journal, [IO.FileMode]::CreateNew), [Text.UTF8Encoding]::new($false))
$writer.AutoFlush = $true
$pgName = "caseops-other-ip-next-pg-$Label"
$testName = "caseops-other-ip-next-tests-$Label"
$pgImage = 'sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f'
$testImage = 'sha256:09d833f4e368065b410628495562e0bb96d83e8610393a127eee5e235069fc20'
$createdPg = $false
function Invoke-Docker([string[]]$Arguments) {
    $writer.WriteLine((@{event='docker_started'; arguments=$Arguments} | ConvertTo-Json -Compress))
    & docker @Arguments 2>&1 | Tee-Object -FilePath (Join-Path $output "$Label-launch.log") -Append
    $exitCode = $LASTEXITCODE
    $writer.WriteLine((@{event='docker_finished'; exit_code=$exitCode} | ConvertTo-Json -Compress))
    if ($exitCode -ne 0) { throw "Docker command failed with exit $exitCode." }
}
try {
    $internal = & docker network inspect caseops-sep10-provider --format '{{.Internal}}'
    if ($LASTEXITCODE -ne 0 -or $internal -ne 'true') { throw 'Approved internal-only network is unavailable.' }
    foreach ($test in $Tests) {
        if (-not (Test-Path -LiteralPath (Join-Path $root "apps/api/$(($test -split '::')[0])"))) { throw "Missing selection: $test" }
    }
    Invoke-Docker @('run', '-d', '--name', $pgName, '--label', 'caseops.track=other-ip-next', '--network', 'caseops-sep10-provider',
        '--cpus=0.25', '--memory=512m', '--memory-swap=512m', '-e', 'POSTGRES_PASSWORD=other-ip-isolated-test-only',
        '-e', 'POSTGRES_DB=other_ip_next', $pgImage, '-c', 'shared_buffers=64MB', '-c', 'max_connections=40')
    $createdPg = $true
    $ready = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        & docker exec $pgName pg_isready -h 127.0.0.1 -U postgres -d other_ip_next *> $null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw 'Owned fresh PostgreSQL did not become ready.' }
    Invoke-Docker @('exec', $pgName, 'psql', '-U', 'postgres', '-d', 'other_ip_next', '-Atc',
        "SELECT current_database(), count(*) FROM information_schema.tables WHERE table_schema='public';")
    $arguments = @('run', '--name', $testName, '--label', 'caseops.track=other-ip-next', '--network', 'caseops-sep10-provider',
        '--cpus=0.75', '--memory=1536m', '--memory-swap=1536m', '--entrypoint', 'bash',
        '--mount', "type=bind,source=$root,target=/workspace,readonly", '--mount', "type=bind,source=$output,target=/output",
        '-e', "RUN_LABEL=$Label", '-e', "CASEOPS_TEST_POSTGRES_URL=postgresql+psycopg://postgres:other-ip-isolated-test-only@${pgName}:5432/other_ip_next",
        '-e', 'CASEOPS_ENV=local', '-e', 'CASEOPS_LLM_PROVIDER=mock', '-e', 'CASEOPS_EMBEDDING_PROVIDER=mock',
        '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', 'HF_HUB_OFFLINE=1', '-e', 'OMP_NUM_THREADS=1',
        '-e', 'CASEOPS_TEST_TEMPORAL_SERVER_PATH=/opt/caseops-test-tools/temporal-test-server',
        '-e', 'CASEOPS_TEST_TEMPORAL_SERVER_SHA256=daa58458d32f6254a901085c27ad1c19a64a4e171679ed08b5b92c298baba6ce',
        $testImage, '/workspace/scripts/tests/run-other-ip-next-container.sh') + $Tests
    Invoke-Docker $arguments
    $events = @(Get-Content -LiteralPath (Join-Path $output "$Label.jsonl") | ConvertFrom-Json)
    $ids = @($events | Where-Object event -eq collection | ForEach-Object nodeids)
    $expectedFiles = @($Tests | ForEach-Object { ($_ -split '::')[0] } | Sort-Object -Unique)
    $actualFiles = @($ids | ForEach-Object { ($_ -split '::')[0] } | Sort-Object -Unique)
    if (-not $ids.Count -or @(Compare-Object $expectedFiles $actualFiles).Count) { throw 'Collected test-file inventory does not match selection.' }
    foreach ($selection in $Tests) {
        if (-not @($ids | Where-Object { $_ -eq $selection -or $_.StartsWith($selection + '::') -or $_.StartsWith($selection + '[') }).Count) { throw "Missing selected identity: $selection" }
    }
    foreach ($id in $ids) {
        foreach ($phase in @('setup', 'call', 'teardown')) {
            $reports = @($events | Where-Object { $_.event -eq 'test_report' -and $_.nodeid -eq $id -and $_.when -eq $phase })
            if ($reports.Count -ne 1 -or $reports[0].outcome -ne 'passed') { throw "Unverified phase: $id / $phase" }
        }
    }
    $finished = @($events | Where-Object event -eq session_finished)
    if ($finished.Count -ne 1 -or $finished[0].exitstatus -ne 0) { throw 'Pytest completion is not proven.' }
    $writer.WriteLine((@{event='reconciled'; test_count=$ids.Count; nodeids=$ids; exit_code=0} | ConvertTo-Json -Compress))
} finally {
    if ($createdPg) {
        & docker stop $pgName 2>&1 | Tee-Object -FilePath (Join-Path $output "$Label-launch.log") -Append
        $writer.WriteLine((@{event='owned_postgres_stopped'; name=$pgName; exit_code=$LASTEXITCODE} | ConvertTo-Json -Compress))
    }
    $writer.Dispose()
}
