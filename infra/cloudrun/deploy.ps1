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
    [string]$LegalUpdateSchedulerJobName = "caseops-legal-update-sync-midnight",
    [string]$LegalUpdateSchedulerSchedule = "0 0 * * *",
    [string]$CaseTrackingSchedulerJobName = "caseops-case-tracking-poll-1800-ist",
    [string]$CaseTrackingSchedulerSchedule = "0 18 * * *",
    [string]$ActivityReportSchedulerJobName = "caseops-activity-report-0800-ist",
    [string]$ActivityReportSchedulerSchedule = "0 8 * * *",
    [string]$IpJournalWatchSchedulerJobName = "caseops-ip-journal-watch-publication-cadence",
    [string]$IpJournalWatchSchedulerSchedule = "15 */2 * * *",
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

function Resolve-ImmutableImage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectId,

        [Parameter(Mandatory = $true)]
        [string]$ImageReference
    )

    $digest = [string](& gcloud artifacts docker images describe $ImageReference `
        --project $ProjectId `
        --format "value(image_summary.digest)")
    if ($LASTEXITCODE -ne 0 -or $digest -notmatch '^sha256:[a-f0-9]{64}$') {
        throw "Could not resolve an immutable digest for API image '$ImageReference'."
    }

    $imageName = $ImageReference
    $digestSeparator = $imageName.IndexOf("@")
    if ($digestSeparator -ge 0) {
        $imageName = $imageName.Substring(0, $digestSeparator)
    } else {
        $lastSlash = $imageName.LastIndexOf("/")
        $lastColon = $imageName.LastIndexOf(":")
        if ($lastColon -gt $lastSlash) {
            $imageName = $imageName.Substring(0, $lastColon)
        }
    }
    return "$imageName@$digest"
}

function Ensure-SchedulerJob {
    param(
        [string]$ProjectId,
        [string]$Location,
        [string]$JobName,
        [string]$RunJobName,
        [string]$Region,
        [string]$SchedulerServiceAccount,
        [string]$Schedule,
        [string]$TimeZone
    )

    $uri = "https://run.googleapis.com/v2/projects/$ProjectId/locations/$Region/jobs/${RunJobName}:run"
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
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to $schedulerAction Cloud Scheduler job '$JobName'."
    }
}

function Ensure-CloudRunJobInvoker {
    param(
        [string]$ProjectId,
        [string]$Region,
        [string]$JobName,
        [string]$SchedulerServiceAccount
    )

    $member = "serviceAccount:$SchedulerServiceAccount"
    $iamArgs = @(
        "run", "jobs", "add-iam-policy-binding", $JobName,
        "--region", $Region,
        "--project", $ProjectId,
        "--member", $member,
        "--role", "roles/run.invoker",
        "--quiet"
    )

    & gcloud @iamArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to grant '$member' permission to execute Cloud Run job '$JobName'."
    }
}

Ensure-Gcloud
$ApiImage = Resolve-ImmutableImage -ProjectId $ProjectId -ImageReference $ApiImage

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
$legalUpdateManifest = Join-Path $renderRoot "legal-update-sync-job.yaml"
$caseTrackingManifest = Join-Path $renderRoot "case-tracking-poll-job.yaml"
$activityReportManifest = Join-Path $renderRoot "activity-report-job.yaml"
$ipJournalWatchManifest = Join-Path $renderRoot "ip-journal-watch-job.yaml"

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "api-service.yaml") `
    -OutputPath $apiManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "activity-report-job.yaml") `
    -OutputPath $activityReportManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "document-worker-job.yaml") `
    -OutputPath $workerManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "legal-update-sync-job.yaml") `
    -OutputPath $legalUpdateManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "case-tracking-poll-job.yaml") `
    -OutputPath $caseTrackingManifest `
    -Replacements $replacements

Render-Template `
    -TemplatePath (Join-Path $scriptRoot "ip-journal-watch-job.yaml") `
    -OutputPath $ipJournalWatchManifest `
    -Replacements $replacements

# NOTE: the API *service* is deployed by scripts/deploy-prod.sh, which uses
# `gcloud run deploy --image` and preserves the multi-container shape
# (the EG-003 clamav sidecar). Do NOT `gcloud run services replace`
# api-service.yaml here — a full-spec replace drops the clamav sidecar and
# resets tuned scaling. This script only manages the jobs + schedulers.
# ($apiManifest is still rendered above for reference / manual inspection.)
foreach ($manifest in @(
    $workerManifest,
    $legalUpdateManifest,
    $caseTrackingManifest,
    $activityReportManifest,
    $ipJournalWatchManifest
)) {
    & gcloud run jobs replace $manifest --region $Region --project $ProjectId
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to replace Cloud Run job from manifest '$manifest'."
    }
}

if (-not $SkipScheduler) {
    foreach ($runJobName in @(
        "caseops-document-worker",
        "caseops-legal-update-sync",
        "caseops-case-tracking-poll",
        "caseops-activity-report",
        "caseops-ip-journal-watch"
    )) {
        Ensure-CloudRunJobInvoker `
            -ProjectId $ProjectId `
            -Region $Region `
            -JobName $runJobName `
            -SchedulerServiceAccount $SchedulerServiceAccount
    }

    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $SchedulerJobName `
        -RunJobName "caseops-document-worker" `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $SchedulerSchedule `
        -TimeZone $SchedulerTimeZone

    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $LegalUpdateSchedulerJobName `
        -RunJobName "caseops-legal-update-sync" `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $LegalUpdateSchedulerSchedule `
        -TimeZone $SchedulerTimeZone

    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $CaseTrackingSchedulerJobName `
        -RunJobName "caseops-case-tracking-poll" `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $CaseTrackingSchedulerSchedule `
        -TimeZone $SchedulerTimeZone

    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $ActivityReportSchedulerJobName `
        -RunJobName "caseops-activity-report" `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $ActivityReportSchedulerSchedule `
        -TimeZone $SchedulerTimeZone

    Ensure-SchedulerJob `
        -ProjectId $ProjectId `
        -Location $SchedulerLocation `
        -JobName $IpJournalWatchSchedulerJobName `
        -RunJobName "caseops-ip-journal-watch" `
        -Region $Region `
        -SchedulerServiceAccount $SchedulerServiceAccount `
        -Schedule $IpJournalWatchSchedulerSchedule `
        -TimeZone $SchedulerTimeZone
}

Write-Host "Cloud Run jobs deployed with immutable images; schedulers configured."
Write-Host "Rendered manifests: $renderRoot"
