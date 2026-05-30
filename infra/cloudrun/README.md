# Cloud Run Deployment Assets

These manifests keep the current founder-stage `CaseOps` API and document worker aligned with the target GCP runtime:

- `api-service.yaml`: HTTP API on Cloud Run with `Cloud SQL` and `GCS`
- `document-worker-job.yaml`: non-HTTP document processor job for OCR, retries, and reindexing
- `legal-update-sync-job.yaml`: nightly legal update/watchlist sync job
- `case-tracking-poll-job.yaml`: nightly bookmarked case polling job
- `deploy.ps1`: idempotent deployment helper for the API, worker jobs, and scheduler triggers

## Assumptions

- The API image is built from `apps/api/Dockerfile`
- A dedicated runtime service account exists
- `Cloud SQL for PostgreSQL` is the primary database
- `GCS` is the document storage backend in cloud
- `Secret Manager` contains `caseops-ecourtsindia-api-token` before case tracking is enabled in cloud
- `Cloud Scheduler` triggers run the document worker frequently and legal/case polling nightly

## Required Replacements

Before deploying, replace these placeholders:

- `__PROJECT_ID__`
- `__PROJECT_NUMBER__`
- `__REGION__`
- `__CLOUD_SQL_INSTANCE__`
- `__SERVICE_ACCOUNT__`
- `__API_IMAGE__`
- `__DATABASE_URL__`
- `__GCS_BUCKET__`
- `__PUBLIC_APP_URL__`
- `__AUTH_SECRET_VERSION__`

## Suggested Deployment Flow

1. Build and publish the API image.
2. Run `deploy.ps1` with your project, image, database, bucket, and identity values.
3. Validate the API service, worker jobs, and scheduler triggers in the GCP console.

## Example

```powershell
.\infra\cloudrun\deploy.ps1 `
  -ProjectId "caseops-prod" `
  -ProjectNumber "123456789012" `
  -Region "asia-south1" `
  -CloudSqlInstance "caseops-sql" `
  -ServiceAccount "caseops-runtime@caseops-prod.iam.gserviceaccount.com" `
  -SchedulerServiceAccount "caseops-scheduler@caseops-prod.iam.gserviceaccount.com" `
  -ApiImage "asia-south1-docker.pkg.dev/caseops-prod/platform/caseops-api:latest" `
  -DatabaseUrl "postgresql+psycopg://caseops:REPLACE_ME@/caseops?host=/cloudsql/caseops-prod:asia-south1:caseops-sql" `
  -GcsBucket "caseops-prod-documents" `
  -PublicAppUrl "https://app.caseops.ai"
```

## IAM Notes

- the runtime service account should have access to `Cloud SQL`, `GCS`, and any secrets the API needs
- the scheduler service account must be able to execute all Cloud Run jobs
  - Google’s current Cloud Run IAM docs list `roles/run.invoker` and `roles/run.jobsExecutor` as roles that grant `run.jobs.run`
- the principal deploying these assets needs permission to update Cloud Run services, Cloud Run jobs, and Cloud Scheduler jobs

## Notes

- The worker job runs `caseops-document-worker --once`, which lets Cloud Run Jobs act as the queue drainer without needing a permanently running non-HTTP process.
- The legal update sync job runs `caseops-sync-legal-updates` at midnight IST by default.
- The case tracking poll job runs `caseops-poll-tracked-cases` at midnight IST by default.
- OCR support expects `tesseract` to be present in the API image. The current Dockerfile installs it directly.
- Document cache is ephemeral in Cloud Run and intentionally stored under `/tmp`.
