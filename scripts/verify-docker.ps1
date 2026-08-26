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
$ComposeProject = "caseops-acceptance"
$ComposeFile = Join-Path $RepoRoot "docker-compose.yml"
$ApiPort = "18000"
$WebPort = "13100"
$PostgresPort = "25432"
$ValkeyPort = "26379"
$ReleaseSha = ((& git -C $RepoRoot rev-parse HEAD | Out-String).Trim())

if ($LASTEXITCODE -ne 0 -or $ReleaseSha -notmatch "^[0-9a-f]{40}$") {
    throw "Could not resolve the exact candidate SHA."
}

$DirtyContext = ((& git -C $RepoRoot status --porcelain --untracked-files=all -- apps/api apps/web docker-compose.yml package.json package-lock.json .dockerignore .gcloudignore playwright.docker.config.ts scripts/verify-docker.ps1 | Out-String).Trim())
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
    CASEOPS_DOCKER_PUBLIC_API_URL = "http://127.0.0.1:$ApiPort"
    CASEOPS_DOCKER_PUBLIC_APP_URL = "http://127.0.0.1:$WebPort"
    CASEOPS_DOCKER_CORS_ORIGINS = "[`"http://127.0.0.1:$WebPort`",`"http://localhost:$WebPort`"]"
    CASEOPS_AUTH_RATE_LIMIT_ENABLED = "false"
    CASEOPS_CASE_TRACKING_ENABLED = "true"
    CASEOPS_IP_WORKSPACE_ENABLED = "true"
    CASEOPS_IP_RULE_GOVERNANCE_ENABLED = "true"
    CASEOPS_CASE_TRACKING_PROVIDER = "ecourtsindia"
    CASEOPS_ECOURTSINDIA_API_BASE_URL = "https://provider.example"
    CASEOPS_ECOURTSINDIA_API_TOKEN = "docker-acceptance-provider-token"
    CASEOPS_E2E_API_PORT = $ApiPort
    CASEOPS_E2E_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:$PostgresPort/caseops"
    CASEOPS_E2E_DOCKER_PROJECT = $ComposeProject
    CASEOPS_E2E_DOCKER_COMPOSE_FILE = $ComposeFile
    CASEOPS_WEB_BASE_URL = "http://127.0.0.1:$WebPort"
}

foreach ($Name in $AcceptanceEnvironment.Keys) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, "Process")
    [Environment]::SetEnvironmentVariable($Name, $AcceptanceEnvironment[$Name], "Process")
}

$Succeeded = $false
try {
    Write-Host "[docker-acceptance] exact candidate $ReleaseSha"
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

    foreach ($Service in @("api", "web")) {
        $ImageId = ((& docker compose --project-name $ComposeProject --file $ComposeFile images --quiet $Service | Out-String).Trim())
        $ImageMetadata = (& docker image inspect $ImageId | ConvertFrom-Json)
        $ImageRevision = $ImageMetadata[0].Config.Labels.'org.opencontainers.image.revision'
        if ($ImageRevision -ne $ReleaseSha) {
            throw "$Service image revision $ImageRevision does not match $ReleaseSha."
        }
    }

    $ApiHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    $ApiIdentity = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/build"
    $WebIdentity = Invoke-RestMethod "http://127.0.0.1:$WebPort/api/release-identity"
    if ($ApiHealth.status -ne "ok") { throw "API health probe did not return ok." }
    if ($ApiIdentity.release_sha -ne $ReleaseSha) { throw "API runtime identity does not match the candidate." }
    if ($WebIdentity.release_sha -ne $ReleaseSha) { throw "Web runtime identity does not match the candidate." }

    Write-Host "[docker-acceptance] running Playwright against Docker + PostgreSQL"
    & npx playwright test --config playwright.docker.config.ts --reporter=list @PlaywrightArgs
    if ($LASTEXITCODE -ne 0) { throw "Docker Playwright acceptance failed." }

    $PostTestHealth = Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/health"
    if ($PostTestHealth.status -ne "ok") { throw "API became unhealthy after Playwright." }
    $Succeeded = $true
    Write-Host "[docker-acceptance] PASS $ReleaseSha"
}
finally {
    if (-not $Succeeded) {
        Write-Host "[docker-acceptance] failure diagnostics"
        & docker compose --project-name $ComposeProject --file $ComposeFile ps --all
        & docker compose --project-name $ComposeProject --file $ComposeFile logs --tail 200 api web migrate worker
    }
    if ($Succeeded -and -not $KeepRunning) {
        & docker compose --project-name $ComposeProject --file $ComposeFile down --volumes --remove-orphans
    }
    foreach ($Name in $AcceptanceEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], "Process")
    }
}

if (-not $Succeeded) { exit 1 }
