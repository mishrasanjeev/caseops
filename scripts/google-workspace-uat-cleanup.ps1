param(
    [string]$ProjectId,
    [string]$Region = "asia-south1",
    [string]$CloudRunService = "caseops-api",
    [string]$ManifestPath,
    [switch]$DeleteSecrets,
    [switch]$DisableCloudRunConfig
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Run-Gcloud {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    & gcloud @Args
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: $($Args -join ' ')"
    }
}

if (-not $ManifestPath) {
    throw "Pass -ManifestPath from the setup script output."
}
if (-not (Test-Path -LiteralPath $ManifestPath)) {
    throw "Manifest not found: $ManifestPath"
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if (-not $ProjectId) {
    $ProjectId = [string]$manifest.project_id
}
if (-not $ProjectId) {
    throw "ProjectId is required."
}
if ($manifest.region) {
    $Region = [string]$manifest.region
}
if ($manifest.cloud_run_service) {
    $CloudRunService = [string]$manifest.cloud_run_service
}

Write-Host "Cleaning CaseOps Google Workspace UAT resources in project $ProjectId"

if ($DisableCloudRunConfig) {
    $envVars = @(
        "CASEOPS_GOOGLE_CALENDAR_CLIENT_ID",
        "CASEOPS_GOOGLE_CALENDAR_CLIENT_SECRET",
        "CASEOPS_GOOGLE_CALENDAR_REDIRECT_URI",
        "CASEOPS_GMAIL_CLIENT_ID",
        "CASEOPS_GMAIL_CLIENT_SECRET",
        "CASEOPS_GMAIL_REDIRECT_URI",
        "CASEOPS_GMAIL_PUBSUB_TOPIC",
        "CASEOPS_GMAIL_WEBHOOK_VERIFICATION_TOKEN",
        "CASEOPS_GOOGLE_DRIVE_CLIENT_ID",
        "CASEOPS_GOOGLE_DRIVE_CLIENT_SECRET",
        "CASEOPS_GOOGLE_DRIVE_REDIRECT_URI"
    ) -join ","
    Run-Gcloud @(
        "run", "services", "update", $CloudRunService,
        "--project", $ProjectId,
        "--region", $Region,
        "--remove-env-vars", $envVars,
        "--quiet"
    )
}

if ($manifest.subscription_id) {
    & gcloud pubsub subscriptions describe $manifest.subscription_id --project $ProjectId *> $null
    if ($LASTEXITCODE -eq 0) {
        Run-Gcloud @(
            "pubsub", "subscriptions", "delete", [string]$manifest.subscription_id,
            "--project", $ProjectId,
            "--quiet"
        )
    }
}

if ($manifest.topic_id) {
    & gcloud pubsub topics describe $manifest.topic_id --project $ProjectId *> $null
    if ($LASTEXITCODE -eq 0) {
        Run-Gcloud @(
            "pubsub", "topics", "delete", [string]$manifest.topic_id,
            "--project", $ProjectId,
            "--quiet"
        )
    }
}

if ($DeleteSecrets -and $manifest.secrets) {
    foreach ($secret in $manifest.secrets) {
        & gcloud secrets describe $secret --project $ProjectId *> $null
        if ($LASTEXITCODE -eq 0) {
            Run-Gcloud @(
                "secrets", "delete", [string]$secret,
                "--project", $ProjectId,
                "--quiet"
            )
        }
    }
}

Write-Host "Cleanup complete. APIs were not disabled because they can be shared by other workloads."
