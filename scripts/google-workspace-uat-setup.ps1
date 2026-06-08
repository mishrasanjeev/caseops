param(
    [string]$ProjectId,
    [string]$Region = "asia-south1",
    [string]$CloudRunService = "caseops-api",
    [string]$ApiBaseUrl = "https://api.caseops.ai",
    [string]$ResourcePrefix = "caseops-google-uat",
    [int]$RetentionDays = 7,
    [string]$OAuthClientId,
    [string]$OAuthClientSecret,
    [switch]$ConfigureCloudRun,
    [switch]$RegisterLocalCleanupTask
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

function Gcloud-Value {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $value = & gcloud @Args
    if ($LASTEXITCODE -ne 0) {
        throw "gcloud failed: $($Args -join ' ')"
    }
    return (($value | Out-String).Trim())
}

function New-Token {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return (($bytes | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Ensure-SecretVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Project
    )
    & gcloud secrets describe $Name --project $Project *> $null
    if ($LASTEXITCODE -ne 0) {
        Run-Gcloud @(
            "secrets", "create", $Name,
            "--project", $Project,
            "--replication-policy", "automatic",
            "--labels", "caseops=google-workspace-uat"
        )
    }
    $tmp = New-TemporaryFile
    try {
        Set-Content -LiteralPath $tmp -Value $Value -NoNewline
        Run-Gcloud @(
            "secrets", "versions", "add", $Name,
            "--project", $Project,
            "--data-file", $tmp
        )
    } finally {
        Remove-Item -LiteralPath $tmp -Force
    }
}

if (-not $ProjectId) {
    $ProjectId = Gcloud-Value @("config", "get-value", "project")
}
if (-not $ProjectId) {
    throw "ProjectId is required."
}
if ($RetentionDays -lt 1 -or $RetentionDays -gt 30) {
    throw "RetentionDays must be between 1 and 30."
}

$suffix = (Get-Date -Format "yyyyMMddHHmm")
$prefix = "$ResourcePrefix-$suffix"
$topicId = "$prefix-gmail-topic"
$subscriptionId = "$prefix-gmail-push"
$webhookToken = New-Token
$cleanupAt = (Get-Date).AddDays($RetentionDays)
$manifestPath = Join-Path "C:\tmp" "$prefix-manifest.json"

$calendarRedirectUri = "$ApiBaseUrl/api/calendar/connections/google-calendar/callback"
$gmailRedirectUri = "$ApiBaseUrl/api/mailbox/gmail/callback"
$driveRedirectUri = "$ApiBaseUrl/api/drive/google/callback"
$pubsubTopicName = "projects/$ProjectId/topics/$topicId"
$pushEndpoint = "$ApiBaseUrl/api/mailbox/gmail/webhook?token=$webhookToken"

Write-Host "Preparing CaseOps Google Workspace UAT resources"
Write-Host "Project: $ProjectId"
Write-Host "Topic: $topicId"
Write-Host "Cleanup after: $($cleanupAt.ToString("u"))"

Run-Gcloud @(
    "services", "enable",
    "gmail.googleapis.com",
    "calendar-json.googleapis.com",
    "drive.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "--project", $ProjectId
)

& gcloud pubsub topics describe $topicId --project $ProjectId *> $null
if ($LASTEXITCODE -ne 0) {
    Run-Gcloud @(
        "pubsub", "topics", "create", $topicId,
        "--project", $ProjectId,
        "--labels", "caseops=google-workspace-uat,ttl_days=$RetentionDays"
    )
}

Run-Gcloud @(
    "pubsub", "topics", "add-iam-policy-binding", $topicId,
    "--project", $ProjectId,
    "--member", "serviceAccount:gmail-api-push@system.gserviceaccount.com",
    "--role", "roles/pubsub.publisher"
)

& gcloud pubsub subscriptions describe $subscriptionId --project $ProjectId *> $null
if ($LASTEXITCODE -ne 0) {
    Run-Gcloud @(
        "pubsub", "subscriptions", "create", $subscriptionId,
        "--project", $ProjectId,
        "--topic", $topicId,
        "--push-endpoint", $pushEndpoint,
        "--ack-deadline", "20",
        "--message-retention-duration", "7d",
        "--labels", "caseops=google-workspace-uat,ttl_days=$RetentionDays"
    )
}

$secretNames = @("$prefix-gmail-webhook-token")
Ensure-SecretVersion -Name "$prefix-gmail-webhook-token" -Value $webhookToken -Project $ProjectId

if ($OAuthClientSecret) {
    Ensure-SecretVersion -Name "$prefix-google-oauth-client-secret" -Value $OAuthClientSecret -Project $ProjectId
    $secretNames += "$prefix-google-oauth-client-secret"
}

if ($ConfigureCloudRun) {
    if (-not $OAuthClientId -or -not $OAuthClientSecret) {
        throw "ConfigureCloudRun requires OAuthClientId and OAuthClientSecret."
    }
    Run-Gcloud @(
        "run", "services", "update", $CloudRunService,
        "--project", $ProjectId,
        "--region", $Region,
        "--update-env-vars",
        "CASEOPS_GOOGLE_CALENDAR_CLIENT_ID=$OAuthClientId,CASEOPS_GOOGLE_CALENDAR_REDIRECT_URI=$calendarRedirectUri,CASEOPS_GMAIL_CLIENT_ID=$OAuthClientId,CASEOPS_GMAIL_REDIRECT_URI=$gmailRedirectUri,CASEOPS_GMAIL_PUBSUB_TOPIC=$pubsubTopicName,CASEOPS_GOOGLE_DRIVE_CLIENT_ID=$OAuthClientId,CASEOPS_GOOGLE_DRIVE_REDIRECT_URI=$driveRedirectUri",
        "--update-secrets",
        "CASEOPS_GOOGLE_CALENDAR_CLIENT_SECRET=$prefix-google-oauth-client-secret:latest,CASEOPS_GMAIL_CLIENT_SECRET=$prefix-google-oauth-client-secret:latest,CASEOPS_GMAIL_WEBHOOK_VERIFICATION_TOKEN=$prefix-gmail-webhook-token:latest,CASEOPS_GOOGLE_DRIVE_CLIENT_SECRET=$prefix-google-oauth-client-secret:latest",
        "--quiet"
    )
}

$manifest = [ordered]@{
    project_id = $ProjectId
    region = $Region
    cloud_run_service = $CloudRunService
    api_base_url = $ApiBaseUrl
    created_at = (Get-Date).ToUniversalTime().ToString("o")
    cleanup_after = $cleanupAt.ToUniversalTime().ToString("o")
    topic_id = $topicId
    topic_name = $pubsubTopicName
    subscription_id = $subscriptionId
    calendar_redirect_uri = $calendarRedirectUri
    gmail_redirect_uri = $gmailRedirectUri
    drive_redirect_uri = $driveRedirectUri
    secrets = $secretNames
}

$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath

if ($RegisterLocalCleanupTask) {
    $cleanupScript = Join-Path (Split-Path -Parent $PSCommandPath) "google-workspace-uat-cleanup.ps1"
    $taskName = "CaseOpsGoogleWorkspaceUatCleanup-$suffix"
    $runAt = $cleanupAt.ToString("HH:mm")
    $runDate = $cleanupAt.ToString("MM/dd/yyyy")
    $taskCommand = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$cleanupScript`" -ManifestPath `"$manifestPath`" -DeleteSecrets -DisableCloudRunConfig"
    & schtasks.exe /Create /TN $taskName /TR $taskCommand /SC ONCE /ST $runAt /SD $runDate /F
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to register local cleanup task."
    }
}

Write-Host "Manifest written: $manifestPath"
Write-Host "OAuth redirect URIs to add in Google Auth Platform:"
Write-Host "  $calendarRedirectUri"
Write-Host "  $gmailRedirectUri"
Write-Host "  $driveRedirectUri"
Write-Host "Cleanup command:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File scripts/google-workspace-uat-cleanup.ps1 -ManifestPath `"$manifestPath`" -DeleteSecrets -DisableCloudRunConfig"
