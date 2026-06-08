# Google Workspace GCP UAT Setup - 2026-06-08

Scope: short-lived CaseOps UAT setup for Gmail, Google Calendar, and Google
Drive readiness in a Google Cloud project. Do not write real client secrets,
OAuth tokens, webhook tokens, or user mailbox payloads into this repo.

## What Can Be Automated

`scripts/google-workspace-uat-setup.ps1` can:

- Enable Gmail, Google Calendar, Google Drive, Pub/Sub, and Secret Manager APIs.
- Create a Gmail Pub/Sub topic and push subscription.
- Grant `gmail-api-push@system.gserviceaccount.com` publisher access to the
  Gmail topic.
- Generate and store a Gmail webhook verification token in Secret Manager.
- Optionally bind OAuth client ID/secret and Gmail topic settings into the
  `caseops-api` Cloud Run service.
- Write a cleanup manifest with a seven-day default retention.
- Optionally register a local Windows cleanup task.

`scripts/google-workspace-uat-cleanup.ps1` can:

- Remove the generated Pub/Sub subscription and topic.
- Remove the temporary Secret Manager secrets when `-DeleteSecrets` is passed.
- Remove CaseOps Google env vars from Cloud Run when `-DisableCloudRunConfig` is
  passed.

The cleanup script intentionally does not disable project APIs because the
active project can be shared with production or other workloads.

## Manual Google Auth Platform Step

The standard Google OAuth web client is created in Google Auth Platform. Use a
web application client and add these redirect URIs:

```text
https://api.caseops.ai/api/calendar/connections/google-calendar/callback
https://api.caseops.ai/api/mailbox/gmail/callback
https://api.caseops.ai/api/drive/google/callback
```

Use one OAuth web client for Gmail, Google Calendar, and Google Drive UAT.
Durable Drive sync/commit remains a separate product slice.

Required OAuth scopes for UAT:

```text
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/gmail.metadata
https://www.googleapis.com/auth/drive.readonly
```

## Setup Command

Run from repo root after creating the OAuth client in Google Auth Platform:

```powershell
.\scripts\google-workspace-uat-setup.ps1 `
  -ProjectId perfect-period-305406 `
  -Region asia-south1 `
  -CloudRunService caseops-api `
  -ApiBaseUrl https://api.caseops.ai `
  -RetentionDays 7 `
  -OAuthClientId "<client-id-from-google-auth-platform>" `
  -OAuthClientSecret "<client-secret-from-google-auth-platform>" `
  -ConfigureCloudRun `
  -RegisterLocalCleanupTask
```

Do not paste the OAuth secret into chat or docs. Paste it only into the local
PowerShell prompt.

## Cleanup Command

The setup script prints the manifest path. Manual cleanup is:

```powershell
.\scripts\google-workspace-uat-cleanup.ps1 `
  -ManifestPath "C:\tmp\<manifest>.json" `
  -DeleteSecrets `
  -DisableCloudRunConfig
```

## Product Admin UX

Tenant admins use:

```text
/app/admin/integrations
/app/calendar
/app/admin/provider-operations
```

`/app/admin/integrations` shows a compact Google Workspace setup panel with
Calendar, Gmail, and Drive status. Calendar and Gmail route to `/app/calendar`
for connection/import/watch actions. Drive connects and lists recent file
metadata in the same panel. Durable Drive sync/import is still not enabled.

Tenant users with document upload access use:

```text
/app/calendar
/app/matters/{matter_id}/documents
```

`/app/calendar` lets each user connect Google Calendar and Gmail where the
workspace has OAuth configured. The matter Documents page lets each document
uploader connect their own Google Drive account, list recent file metadata, and
revoke the connection. Drive file bytes are not imported and no matter
attachments are created from Drive in this slice.

Tenant users must never see OAuth secrets, webhook tokens, raw provider
payloads, provider costs, gross profit, gross margin, or platform-only notes.
