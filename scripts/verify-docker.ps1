#Requires -Version 5.1

[CmdletBinding(PositionalBinding=$false)]
param(
    [switch]$KeepRunning,
    [switch]$SkipBuild,
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PlaywrightArgs = @()
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..").Path
$ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
$ApiDir = Join-Path $RepoRoot "apps\api"
$ApiPython = Join-Path $ApiDir ".venv\Scripts\python.exe"
$ReleaseSha = ((& git -C $RepoRoot rev-parse HEAD | Out-String).Trim())
$TestApiProxyScript = Join-Path $RepoRoot "scripts\docker-acceptance-api-proxy.mjs"
$TestApiProxyProcess = $null
$TestApiProxyStdout = $null
$TestApiProxyStderr = $null

if ($LASTEXITCODE -ne 0 -or $ReleaseSha -notmatch "^[0-9a-f]{40}$") {
    throw "Could not resolve the exact candidate SHA."
}

$ComposeProject = "caseops-acceptance-$($ReleaseSha.Substring(0, 12))"
$PortBlock = [Convert]::ToInt32($ReleaseSha.Substring(0, 6), 16) % 6000
$PortBase = 20000 + ($PortBlock * 5)
$ApiPort = ($PortBase + 0).ToString()
$TestApiPort = ($PortBase + 1).ToString()
$WebPort = ($PortBase + 2).ToString()
$PostgresPort = ($PortBase + 3).ToString()
$ValkeyPort = ($PortBase + 4).ToString()

$DirtyContext = ((& git -C $RepoRoot status --porcelain --untracked-files=all -- apps/api apps/web docker-compose.yml package.json package-lock.json .dockerignore .gcloudignore playwright.docker.config.ts scripts/docker-acceptance-api-proxy.mjs scripts/verify-docker.ps1 | Out-String).Trim())
if ($DirtyContext) {
    throw "Docker acceptance requires a committed, clean build context. Commit the candidate first.`n$DirtyContext"
}

$PreviousEnvironment = @{}
$AcceptanceEnvironment = @{
    CASEOPS_RELEASE_SHA = $ReleaseSha
    CASEOPS_DOCKER_ENV = "e2e"
    CASEOPS_DOCKER_API_PORT = $ApiPort
    CASEOPS_DOCKER_WEB_PORT = $WebPort
    CASEOPS_DOCKER_POSTGRES_PORT = $PostgresPort
    CASEOPS_DOCKER_VALKEY_PORT = $ValkeyPort
    CASEOPS_DOCKER_PUBLIC_API_URL = "http://127.0.0.1:$TestApiPort"
    CASEOPS_DOCKER_PUBLIC_APP_URL = "http://127.0.0.1:$WebPort"
    CASEOPS_DOCKER_CORS_ORIGINS = "[`"http://127.0.0.1:$WebPort`",`"http://localhost:$WebPort`"]"
    CASEOPS_AUTH_RATE_LIMIT_ENABLED = "false"
    CASEOPS_CASE_TRACKING_ENABLED = "true"
    CASEOPS_IP_WORKSPACE_ENABLED = "true"
    CASEOPS_IP_RULE_GOVERNANCE_ENABLED = "true"
    CASEOPS_CASE_TRACKING_PROVIDER = "ecourtsindia"
    CASEOPS_ECOURTSINDIA_API_BASE_URL = "https://provider.example"
    CASEOPS_ECOURTSINDIA_API_TOKEN = "docker-acceptance-provider-token"
    # Playwright's Node control-plane and browser calls go through a loopback
    # proxy that opens one fresh Windows-to-Docker connection per request.
    CASEOPS_E2E_API_PORT = $TestApiPort
    CASEOPS_E2E_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    CASEOPS_E2E_DOCKER_PROJECT = $ComposeProject
    CASEOPS_E2E_DOCKER_COMPOSE_FILE = $ComposeFile
    CASEOPS_WEB_BASE_URL = "http://127.0.0.1:$WebPort"
    # Worktrees under OneDrive cannot always accept uv cache hardlinks on Windows.
    UV_LINK_MODE = "copy"
}

foreach ($Name in $AcceptanceEnvironment.Keys) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, $AcceptanceEnvironment[$Name], "Process")
}

$Succeeded = $false
try {
    Write-Host "[docker-acceptance] exact candidate $ReleaseSha"
    Write-Host "[docker-acceptance] preparing frozen host test dependencies"
    & npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw "Host Node dependency sync failed." }
    & uv sync --project $ApiDir --frozen
    if ($LASTEXITCODE -ne 0) { throw "Host API dependency sync failed." }
    & $ApiPython -c "import caseops_api, psycopg, sqlalchemy"
    if ($LASTEXITCODE -ne 0) { throw "Host API fixture dependencies or project package are unavailable." }

    Write-Host "[docker-acceptance] resetting isolated project $ComposeProject"
    & docker compose --project-name $ComposeProject --file $ComposeFile down --volumes --remove-orphans
    if ($LASTEXITCODE -ne 0) { throw "Could not reset the isolated Compose project." }

    if (-not $SkipBuild) {
        Write-Host "[docker-acceptance] building API and web production images"
        & docker compose --project-name $ComposeProject --file $ComposeFile build --pull api web
        if ($LASTEXITCODE -ne 0) { throw "Docker image build failed." }
    }

    Write-Host "[docker-acceptance] starting migration-first stack"
    & docker compose --project-name $ComposeProject --file $ComposeFile up --detach --wait --wait-timeout 300
    if ($LASTEXITCODE -ne 0) { throw "Docker stack did not become healthy." }

    $MigrationId = ((& docker compose --project-name $ComposeProject --file $ComposeFile ps --all --quiet migrate | Out-String).Trim())
    $MigrationExitCode = ((& docker inspect --format "{{.State.ExitCode}}" $MigrationId | Out-String).Trim())
    if ($MigrationExitCode -ne "0") {
        throw "Migration container exited with code $MigrationExitCode."
    }

    $ApiImageId = $null
    foreach ($Service in @("api", "web")) {
        $ImageId = ((& docker compose --project-name $ComposeProject --file $ComposeFile images --quiet $Service | Out-String).Trim())
        $ImageMetadata = (& docker image inspect $ImageId | ConvertFrom-Json)
        $ImageRevision = $ImageMetadata[0].Config.Labels.'org.opencontainers.image.revision'
        if ($ImageRevision -ne $ReleaseSha) {
            throw "$Service image revision $ImageRevision does not match $ReleaseSha."
        }
        if ($Service -eq "api") { $ApiImageId = $ImageId }
    }

    $ApiHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    $ApiIdentity = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/build"
    $WebIdentity = Invoke-RestMethod "http://127.0.0.1:$WebPort/api/release-identity"
    if ($ApiHealth.status -ne "ok") { throw "API health probe did not return ok." }
    if ($ApiIdentity.release_sha -ne $ReleaseSha) { throw "API runtime identity does not match the candidate." }
    if ($WebIdentity.release_sha -ne $ReleaseSha) { throw "Web runtime identity does not match the candidate." }

    Write-Host "[docker-acceptance] verifying complete PostgreSQL index coverage"
    & docker compose --project-name $ComposeProject --file $ComposeFile exec --no-TTY api caseops-db-index-health
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL index health gate failed." }

    Write-Host "[docker-acceptance] verifying index health within the production job memory ceiling"
    $AcceptanceNetworkId = ((& docker network ls `
        --filter "label=com.docker.compose.project=$ComposeProject" `
        --filter "label=com.docker.compose.network=default" `
        --format "{{.ID}}" | Out-String).Trim())
    if (-not $ApiImageId -or -not $AcceptanceNetworkId -or $AcceptanceNetworkId -match "\s") {
        throw "Could not resolve the exact API image and isolated Compose network."
    }
    & docker run --rm `
        --memory 512m `
        --memory-swap 512m `
        --network $AcceptanceNetworkId `
        --env CASEOPS_ENV=e2e `
        --env CASEOPS_AUTO_MIGRATE=false `
        --env CASEOPS_DATABASE_URL=postgresql+psycopg://caseops:caseops@postgres:5432/caseops `
        --env CASEOPS_DB_STATEMENT_TIMEOUT_MS=60000 `
        --env CASEOPS_DB_LOCK_TIMEOUT_MS=5000 `
        --env CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS=60000 `
        --env CASEOPS_AUTH_SECRET=change-me-change-me-change-me-2026 `
        $ApiImageId `
        caseops-db-index-health
    if ($LASTEXITCODE -ne 0) {
        throw "PostgreSQL index health exceeded its 512 MiB production job ceiling or failed."
    }

    Write-Host "[docker-acceptance] running Playwright against Docker + PostgreSQL"
    $NodePath = (Get-Command node -ErrorAction Stop).Source
    $TestApiProxyStdout = [IO.Path]::GetTempFileName()
    $TestApiProxyStderr = [IO.Path]::GetTempFileName()
    $TestApiProxyProcess = Start-Process `
        -FilePath $NodePath `
        -ArgumentList @("`"$TestApiProxyScript`"", $TestApiPort, $ApiPort) `
        -PassThru `
        -WindowStyle Hidden `
        -RedirectStandardOutput $TestApiProxyStdout `
        -RedirectStandardError $TestApiProxyStderr
    $ProxyReady = $false
    foreach ($Attempt in 1..30) {
        if ($TestApiProxyProcess.HasExited) { break }
        try {
            $ProxyHealth = Invoke-RestMethod "http://127.0.0.1:$TestApiPort/api/health" -TimeoutSec 5
            if ($ProxyHealth.status -eq "ok") {
                $ProxyReady = $true
                break
            }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $ProxyReady) {
        $ProxyError = if (Test-Path -LiteralPath $TestApiProxyStderr) {
            Get-Content -LiteralPath $TestApiProxyStderr -Raw
        } else { "" }
        throw "Docker acceptance API proxy did not become ready. $ProxyError"
    }
    & npx playwright test --config playwright.docker.config.ts --reporter=list @PlaywrightArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Playwright acceptance failed." }

    $PostTestHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    if ($PostTestHealth.status -ne "ok") { throw "API became unhealthy after Playwright." }
    $Succeeded = $true
    Write-Host "[docker-acceptance] PASS $ReleaseSha"
}
finally {
    if ($null -ne $TestApiProxyProcess -and -not $TestApiProxyProcess.HasExited) {
        Stop-Process -Id $TestApiProxyProcess.Id -Force
        Wait-Process -Id $TestApiProxyProcess.Id -ErrorAction SilentlyContinue
    }
    if (-not $Succeeded) {
        Write-Host "[docker-acceptance] failure diagnostics"
        & docker compose --project-name $ComposeProject --file $ComposeFile ps --all
        & docker compose --project-name $ComposeProject --file $ComposeFile logs --tail 200 api web migrate worker
        if ($TestApiProxyStderr -and (Test-Path -LiteralPath $TestApiProxyStderr)) {
            Get-Content -LiteralPath $TestApiProxyStderr
        }
    }
    if ($Succeeded -and -not $KeepRunning) {
        & docker compose --project-name $ComposeProject --file $ComposeFile down --volumes --remove-orphans
    }
    foreach ($Name in $AcceptanceEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], "Process")
    }
    foreach ($LogPath in @($TestApiProxyStdout, $TestApiProxyStderr)) {
        if ($LogPath -and (Test-Path -LiteralPath $LogPath)) {
            Remove-Item -LiteralPath $LogPath -Force
        }
    }
}

if (-not $Succeeded) { exit 1 }
