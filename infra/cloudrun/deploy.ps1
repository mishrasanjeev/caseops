param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$ProjectNumber,

    [Parameter(Mandatory = $true)]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$CloudSqlInstance,

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccount,

    [Parameter(Mandatory = $true)]
    [string]$SchedulerServiceAccount,

    [Parameter(Mandatory = $true)]
    [string]$ApiImage,

    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrl,

    [Parameter(Mandatory = $true)]
    [string]$GcsBucket,

    [Parameter(Mandatory = $true)]
    [string]$PublicAppUrl,

    [string]$AuthSecretVersion = "latest",
    [string]$SchedulerLocation,
    [string]$SchedulerJobName = "caseops-document-worker-trigger",
    [string]$SchedulerSchedule = "*/2 * * * *",
    [string]$SchedulerTimeZone = "Asia/Kolkata",
    [switch]$SkipScheduler
)

$ErrorActionPreference = "Stop"

if (-not $SchedulerLocation) {
    $SchedulerLocation = $Region
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$renderRoot = Join-Path $env:TEMP ("caseops-cloudrun-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $renderRoot | Out-Null

function Render-Template {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TemplatePath,

        [Parameter(Mandatory = $true)]
        [string]$OutputPath,

        [Parameter(Mandatory = $true)]
        [hashtable]$Replacements
    )

    $content = Get-Content $TemplatePath -Raw
    foreach ($key in $Replacements.Keys) {
        $content = $content.Replace($key, [string]$Replacements[$key])
    }
    Set-Content -Path $OutputPath -Value $content -NoNewline
}

function Ensure-Gcloud {
    $command = Get-Command gcloud -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "gcloud CLI is required to deploy Cloud Run assets."
    }
}

function Ensure-SchedulerJob {
    param(
        [string]$ProjectId,
        [string]$Location,
        [string]$JobName,
        [string]$Region,
        [string]$SchedulerServiceAccount,
        [string]$Schedule,
        [string]$TimeZone
    )

    $uri = "https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/caseops-document-worker:run"
    $scope = "https://www.googleapis.com/auth/cloud-platform"
    $describeArgs = @(
        "scheduler", "jobs", "describe", $JobName,
        "--location", $Location,
        "--project", $ProjectId
    )

    & gcloud @describeArgs 2>$null | Out-Null
    $exists = $LASTEXITCODE -eq 0

    $schedulerAction = "create"
    if ($exists) {
        $schedulerAction = "update"
    }

    $commonArgs = @(
        "scheduler", "jobs",
        $schedulerAction,
        "http", $JobName,
        "--location", $Location,
        "--project", $ProjectId,
        "--schedule", $Schedule,
        "--time-zone", $TimeZone,
        "--uri", $uri,
        "--http-method", "POST",
        "--message-body", "{}",
        "--oauth-service-account-email", $SchedulerServiceAccount,
        "--oauth-token-scope", $scope
    )

    & gcloud @commonArgs
}

Ensure-Gcloud

$replacements = @{
    "__PROJECT_ID__" = $ProjectId
    "__PROJECT_NUMBER__" = $ProjectNumber
    "__REGION__" = $Region
    "__CLOUD_SQL_INSTANCE__" = $CloudSqlInstance
    "__SERVICE_ACCOUNT__" = $ServiceAccount
    "__API_IMAGE__" = $ApiImage
    "__DATABASE_URL__" = $DatabaseUrl
    "__GCS_BUCKET__" = $GcsBucket
    "__PUBLIC_APP_URL__" = $PublicAppUrl
    "__AUTH_SECRET_VERSION__" = $AuthSecretVersion
}

$apiManifest = Join-Path $renderRoot "api-service.yaml"
$workerManifest = Join-Path $renderRoot "document-worker-job.yaml"

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "api-service.yaml") `
    -OutputPath $apiManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "document-worker-job.yaml") `
    -OutputPath $workerManifest `
    -Replacements $replacements

& gcloud run services replace $apiManifest --region $Region --project $ProjectId
& gcloud run jobs replace $workerManifest --region $Region --project $ProjectId

if (-not $SkipScheduler) {
    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $SchedulerJobName `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $SchedulerSchedule `
        -TimeZone $SchedulerTimeZone
}

Write-Host "Cloud Run API deployed, document worker job deployed, and scheduler configured."
Write-Host "Rendered manifests: $renderRoot"
