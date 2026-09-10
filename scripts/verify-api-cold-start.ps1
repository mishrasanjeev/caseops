#Requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ApiImage,
    [Parameter(Mandatory=$true)][string]$EvidenceDirectory,
    [ValidatePattern('^[0-9.]+/[0-9]{1,2}$')][string]$NetworkSubnet,
    [ValidateRange(1,10)][int]$Runs = 3,
    [switch]$CollectFunctionalDiagnostics
)
$ErrorActionPreference = 'Stop'
$ScannerImage = 'clamav/clamav@sha256:71fbb76b397cd84a90043caf1178a7f81bd0c131a031e7b0619afd721fbfad41'
$RunId = 'caseops-cold-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$Network = $null
$Api = $null
$Scanner = $null
$Postgres = $null
$Migration = $null
$Seed = $null
$StateVolume = $null
$Result = [ordered]@{status='incomplete'; cold_budget_seconds=30; warm_budget_seconds=5}
$ProbePath = Join-Path $PSScriptRoot 'cold-upload-http.py'
if (-not (Test-Path -LiteralPath $ProbePath)) { throw 'HTTP acceptance helper is missing.' }
$EvidenceDirectory = [IO.Path]::GetFullPath($EvidenceDirectory)
if (Test-Path -LiteralPath $EvidenceDirectory) { throw 'Use a fresh evidence directory.' }
New-Item -ItemType Directory -Path $EvidenceDirectory | Out-Null

if ($Runs -gt 1) {
    $ApiImage = (& docker image inspect $ApiImage --format '{{.Id}}' | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot pin the image for repeated runs.' }
    $Results = @()
    $ExecutionFailures = @()
    for ($Index = 1; $Index -le $Runs; $Index++) {
        $RunDirectory = Join-Path $EvidenceDirectory ('run-{0:d2}' -f $Index)
        $Arguments = @{ApiImage=$ApiImage; EvidenceDirectory=$RunDirectory; Runs=1}
        if ($NetworkSubnet) { $Arguments.NetworkSubnet = $NetworkSubnet }
        if ($CollectFunctionalDiagnostics) { $Arguments.CollectFunctionalDiagnostics = $true }
        try { & $PSCommandPath @Arguments } catch {
            $ExecutionFailures += $Index
            Write-Warning "Cold run $Index failed; its evidence is retained."
        }
        $ReportPath = Join-Path $RunDirectory 'result.json'
        if (-not (Test-Path -LiteralPath $ReportPath)) { throw "Run $Index has no completion report." }
        $Results += Get-Content -LiteralPath $ReportPath -Raw | ConvertFrom-Json
    }
    $Worst = ($Results | Measure-Object -Property cold_http_seconds -Maximum).Maximum
    $Passed = $ExecutionFailures.Count -eq 0 -and @($Results | Where-Object { $_.status -ne 'passed' }).Count -eq 0
    $Stable = $Passed -and $Runs -ge 3 -and $Worst -le 27
    [ordered]@{
        status=$(if ($Stable) { 'passed' } else { 'failed_stability' })
        runs=$Results; fresh_runs=$Runs; cold_budget_seconds=30
        minimum_stability_margin_seconds=3; worst_cold_seconds=$Worst
        stable_margin_proven=$Stable
        execution_failures=$ExecutionFailures
        scope='Local exact-image HTTP with synthetic PostgreSQL portfolio; production and browser proof remain separate'
    } | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'result.json')
    if (-not $Stable) { throw 'Repeated cold starts did not establish the required stable margin.' }
    return
}

function Invoke-Docker {
    param([string[]]$Arguments)
    $Output = (& docker @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Docker command failed: $($Arguments[0])" }
    return $Output
}

try {
    $ApiIdentity = Invoke-Docker @('image', 'inspect', $ApiImage, '--format', '{{.Id}}')
    $ScannerIdentity = Invoke-Docker @('image', 'inspect', $ScannerImage, '--format', '{{.Id}}')
    $PostgresIdentity = Invoke-Docker @('image', 'inspect', 'pgvector/pgvector@sha256:cf134a767f474095eeba57e0117be8e568e011a63f33fbf252f14c9b760f8e6f', '--format', '{{.Id}}')
    $Result.api_image = $ApiIdentity
    $Result.scanner_image = $ScannerIdentity
    $Result.postgres_image = $PostgresIdentity
    $Result.network = 'internal_no_internet'
    $NetworkArguments = @('network', 'create', '--internal', '--label', "caseops.cold-test=$RunId")
    if ($NetworkSubnet) { $NetworkArguments += @('--subnet', $NetworkSubnet) }
    $Network = Invoke-Docker ($NetworkArguments + @($RunId))
    $DatabaseUrl = 'postgresql+psycopg://caseops:cold-local-only@postgres:5432/caseops'
    $Postgres = Invoke-Docker @('run', '-d', '--name', "$RunId-postgres", '--network', $RunId,
        '--network-alias', 'postgres', '--cpus', '1', '--memory', '1g',
        '--label', "caseops.cold-test=$RunId", '-e', 'POSTGRES_USER=caseops',
        '-e', 'POSTGRES_PASSWORD=cold-local-only', '-e', 'POSTGRES_DB=caseops', $PostgresIdentity)
    $DatabaseClock = [Diagnostics.Stopwatch]::StartNew()
    do {
        & docker exec $Postgres pg_isready -U caseops -d caseops *> $null
        if ($LASTEXITCODE -eq 0) { break }
        if ($DatabaseClock.Elapsed.TotalSeconds -gt 30) { throw 'Isolated PostgreSQL did not become ready.' }
        Start-Sleep -Milliseconds 200
    } while ($true)
    $Migration = Invoke-Docker @('create', '--name', "$RunId-migrate", '--network', $RunId,
        '--cpus', '2', '--memory', '2g', '--label', "caseops.cold-test=$RunId",
        '-e', "CASEOPS_DATABASE_URL=$DatabaseUrl", '-e', 'CASEOPS_ENV=local',
        $ApiIdentity, 'alembic', 'upgrade', 'head')
    Invoke-Docker @('start', '--attach', $Migration) 2>&1 | Out-Null
    $MigrationState = (Invoke-Docker @('inspect', $Migration) | ConvertFrom-Json)[0]
    if ($MigrationState.State.ExitCode -ne 0) { throw 'Isolated database migration failed.' }
    $StateVolume = Invoke-Docker @('volume', 'create', '--label', "caseops.cold-test=$RunId", "$RunId-state")
    $Seed = Invoke-Docker @('create', '--name', "$RunId-seed", '--network', $RunId,
        '--cpus', '2', '--memory', '4g', '--label', "caseops.cold-test=$RunId",
        '--mount', "type=volume,source=$StateVolume,target=/proof-state",
        '-e', "CASEOPS_DATABASE_URL=$DatabaseUrl", '-e', 'CASEOPS_ENV=local',
        '-e', 'CASEOPS_AUTO_MIGRATE=false', '-e', 'CASEOPS_COLD_STATE=/proof-state/state.json',
        $ApiIdentity, 'python', '/tmp/cold-upload-http.py', 'seed')
    Invoke-Docker @('cp', $ProbePath, "${Seed}:/tmp/cold-upload-http.py") | Out-Null
    Invoke-Docker @('start', '--attach', $Seed) 2>&1 | Out-Null
    if (((Invoke-Docker @('inspect', $Seed) | ConvertFrom-Json)[0]).State.ExitCode -ne 0) {
        throw 'Canonical portfolio fixture preparation failed.'
    }
    $Scanner = Invoke-Docker @('create', '--name', "$RunId-scanner", '--network', $RunId,
        '--network-alias', 'scanner', '--cpus', '1', '--memory', '1500m',
        '--label', "caseops.cold-test=$RunId", '-e', 'CLAMAV_NO_FRESHCLAMD=true', $ScannerImage)
    $Api = Invoke-Docker @('create', '--name', "$RunId-api", '--network', $RunId,
        '--cpus', '2', '--memory', '4g',
        '--mount', "type=volume,source=$StateVolume,target=/proof-state",
        '--label', "caseops.cold-test=$RunId", '-e', 'PORT=8000',
        '-e', "CASEOPS_DATABASE_URL=$DatabaseUrl",
        '-e', 'CASEOPS_ENV=local', '-e', 'CASEOPS_AUTO_MIGRATE=false',
        '-e', 'CASEOPS_COLD_STATE=/proof-state/state.json',
        '-e', 'CASEOPS_CLAMAV_HOST=scanner', '-e', 'CASEOPS_CLAMAV_REQUIRED=true',
        '-e', 'CASEOPS_CLAMAV_TIMEOUT_S=2', '-e', 'CASEOPS_RERANK_ENABLED=true',
        '-e', 'CASEOPS_RERANK_BACKEND=fastembed', $ApiIdentity)
    Invoke-Docker @('cp', $ProbePath, "${Api}:/tmp/cold-upload-http.py") | Out-Null
    $Clock = [Diagnostics.Stopwatch]::StartNew()
    $StartedEpoch = ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000).ToString([Globalization.CultureInfo]::InvariantCulture)
    Invoke-Docker @('start', $Scanner, $Api) | Out-Null
    # Internal networks deliberately have no published host route. Probe real
    # loopback HTTP inside the container, without adding an Internet-capable NIC.
    $HealthProbe = 'import json,urllib.request; response=urllib.request.urlopen("http://127.0.0.1:8000/api/health",timeout=1); body=json.load(response); assert body["status"]=="ok"; print(json.dumps(body))'
    $ProbeOutput = Invoke-Docker @('exec', $Api, 'python', '/tmp/cold-upload-http.py', 'wait-portfolio', $StartedEpoch)
    $ColdResult = $ProbeOutput | ConvertFrom-Json
    $ProbeOutput | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'cold-portfolio-http.json')
    $ColdSeconds = $ColdResult.cold_http_seconds
    $ColdGatePassed = $ColdResult.cold_gate_passed
    $Ready = $ColdGatePassed
    $Result.cold_http_seconds = $ColdSeconds
    $Result.cold_gate_passed = $ColdGatePassed
    $Result.status = if ($ColdGatePassed) { 'incomplete' } else { 'failed_cold_budget' }
    if (-not $Ready) {
        $ProbeOutput | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'last-probe-error.txt')
        if (-not $CollectFunctionalDiagnostics) { throw 'Cold HTTP readiness exceeded the 30-second budget.' }
        # This diagnostic continuation never changes the failed cold gate or exit code.
        while ($Clock.Elapsed.TotalSeconds -lt 120) {
            $ProbeOutput = (& docker exec $Api python -c $HealthProbe 2>&1 | Out-String).Trim()
            if ($LASTEXITCODE -eq 0) { $Ready = $true; break }
            Start-Sleep -Milliseconds 200
        }
        if (-not $Ready) { throw 'Cold gate failed and HTTP functional diagnostics could not start.' }
    }
    $ObservedReadySeconds = $Clock.Elapsed.TotalSeconds
    $WarmPortfolio = Invoke-Docker @('exec', $Api, 'python', '/tmp/cold-upload-http.py', 'portfolio')
    $WarmPortfolio | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'warm-portfolio-http.json')
    if (($WarmPortfolio | ConvertFrom-Json).seconds -gt 5) { throw 'Warm portfolio exceeded the five-second budget.' }
    $ApiLogs = (& docker logs $Api 2>&1 | Out-String)
    if ($ApiLogs -notmatch 'Startup native ready duration_seconds=[0-9.]+ provider=fastembed') {
        throw 'The serving process did not prove real native reranker readiness.'
    }

    $ScanResult = Invoke-Docker @('exec', $Api, 'python', '/tmp/cold-upload-http.py', 'healthy')
    $ScanResult | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'healthy-http.json')
    Invoke-Docker @('stop', '--time', '2', $Scanner) | Out-Null
    $OutageResult = Invoke-Docker @('exec', $Api, 'python', '/tmp/cold-upload-http.py', 'unavailable')
    $OutageResult | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'outage-http.json')
    $WarmClock = [Diagnostics.Stopwatch]::StartNew()
    $Healthy = Invoke-Docker @('exec', $Api, 'python', '-c', $HealthProbe)
    if (($Healthy | ConvertFrom-Json).status -ne 'ok') { throw 'Unrelated health failed after scanner outage.' }
    $WarmSeconds = $WarmClock.Elapsed.TotalSeconds
    if ($WarmSeconds -gt 5) { throw 'Unrelated health exceeded the five-second budget after scanner outage.' }
    Invoke-Docker @('start', $Scanner) | Out-Null
    $ScannerClock = [Diagnostics.Stopwatch]::StartNew()
    do {
        & docker exec $Api python -c 'import clamd; assert clamd.ClamdNetworkSocket(host="scanner",port=3310,timeout=1).ping()=="PONG"' *> $null
        if ($LASTEXITCODE -eq 0) { break }
        if ($ScannerClock.Elapsed.TotalSeconds -gt 30) { throw 'Scanner did not recover within 30 seconds.' }
        Start-Sleep -Milliseconds 200
    } while ($true)
    $RecoveryResult = Invoke-Docker @('exec', $Api, 'python', '/tmp/cold-upload-http.py', 'recovered')
    $RecoveryResult | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'recovery-http.json')
    $Result = [ordered]@{
        api_image=$ApiIdentity; scanner_image=$ScannerIdentity; network='internal_no_internet'
        cold_http_seconds=$ColdSeconds; cold_budget_seconds=30
        cold_gate_passed=$ColdGatePassed; observed_ready_seconds=$ObservedReadySeconds
        cold_portfolio=$ColdResult.portfolio; warm_portfolio=($WarmPortfolio | ConvertFrom-Json)
        api_cpu=2; api_memory_bytes=4294967296; scanner_cpu=1; scanner_memory_bytes=1572864000
        native_reranker='fastembed'; startup_readiness_budget_seconds=60
        after_outage_health_seconds=$WarmSeconds; after_outage_health_budget_seconds=5
        postgres_image=$PostgresIdentity; helper_sha256=(Get-FileHash -LiteralPath $ProbePath -Algorithm SHA256).Hash.ToLowerInvariant()
        clean_and_eicar=($ScanResult | ConvertFrom-Json)
        scanner_outage=($OutageResult | ConvertFrom-Json)
        recovery=($RecoveryResult | ConvertFrom-Json)
        functional_http_status='passed'
        status=$(if ($ColdGatePassed) { 'passed' } else { 'failed_cold_budget' })
        scope='Local cold authenticated portfolio and real-scanner upload/download; not Playwright or production portfolio certification'
    }
    if (-not $ColdGatePassed) { throw 'HTTP functional diagnostics passed; cold readiness still failed the 30-second gate.' }
} catch {
    $Result.error = $_.Exception.Message
    throw
} finally {
    $Result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory 'result.json')
    foreach ($Container in @($Api, $Scanner, $Seed, $Migration, $Postgres)) {
        if (-not $Container) { continue }
        $State = (Invoke-Docker @('inspect', $Container) | ConvertFrom-Json)[0]
        if ($State.Config.Labels.'caseops.cold-test' -ne $RunId) { throw 'Container cleanup ownership mismatch.' }
        $Name = if ($Container -eq $Api) { 'api' } elseif ($Container -eq $Scanner) { 'scanner' } elseif ($Container -eq $Postgres) { 'postgres' } elseif ($Container -eq $Seed) { 'seed' } else { 'migration' }
        & docker logs --timestamps $Container *> (Join-Path $EvidenceDirectory "$Name.log")
        $State | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $EvidenceDirectory "$Name-state.json")
        Invoke-Docker @('rm', '--force', '--volumes', $Container) | Out-Null
    }
    if ($StateVolume) {
        $Volume = (Invoke-Docker @('volume', 'inspect', $StateVolume) | ConvertFrom-Json)[0]
        if ($Volume.Labels.'caseops.cold-test' -ne $RunId) { throw 'Volume cleanup ownership mismatch.' }
        Invoke-Docker @('volume', 'rm', $StateVolume) | Out-Null
    }
    if ($Network) { Invoke-Docker @('network', 'rm', $Network) | Out-Null }
}
