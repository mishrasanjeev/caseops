# CaseOps API

This service hosts the CaseOps backend APIs. The initial skeleton includes:

- application settings bootstrap
- health and metadata routes
- a root router for future module expansion
- test coverage for startup and health behavior

## Run Locally

```powershell
cd ..\..
docker compose up postgres valkey

cd apps\api
uv sync
uv run uvicorn caseops_api.main:app --reload --app-dir src
```

CaseOps local API runtime is Postgres-first. Use `CASEOPS_DATABASE_URL` to point at a Postgres 17 + `pgvector` instance, not SQLite, for normal local development and seeded data work.

## Bulk Matter Creation

The production matter import workflow is tenant-scoped and capability-gated by
`matters:bulk_import` (Owner/Admin by default; delegable to a custom Matter
Manager role).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/matters/imports/template?format=xlsx|csv` | Download the controlled template |
| `POST` | `/api/matters/imports/preview` | Validate and persist a CSV/XLSX preview |
| `GET` | `/api/matters/imports/history` | Search tenant import history |
| `GET` | `/api/matters/imports/{job_id}` | Read job summary and row results |
| `POST` | `/api/matters/imports/{job_id}/commit` | Revalidate and create every valid row |
| `POST` | `/api/matters/imports/{job_id}/cancel` | Cancel an uncommitted preview |
| `GET` | `/api/matters/imports/{job_id}/errors` | Download formula-safe error CSV |

Limits are 2 MB and 500 non-empty data rows. Preview jobs expire after 24
hours; completed commit is idempotent. Matter creation and its import-row outcome
commit atomically. An `importing` job with no heartbeat for ten minutes can be
resumed safely, and PostgreSQL serializes concurrent same-tenant case-number
creation. See
`docs/PRD_BULK_MATTER_CREATION_2026-07-17.md` for the full field, validation,
security, state-machine, and partial-success specification.

## Document Worker

```powershell
uv sync
uv run caseops-document-worker --once
```

Continuous polling mode:

```powershell
uv run caseops-document-worker
```

## Cloud Runtime Notes

- use `CASEOPS_DOCUMENT_STORAGE_BACKEND=gcs` in Cloud Run
- point `CASEOPS_DOCUMENT_STORAGE_GCS_BUCKET` at the tenant document bucket
- set `CASEOPS_DOCUMENT_STORAGE_CACHE_PATH=/tmp/caseops-document-cache` for ephemeral cache materialization
- keep `CASEOPS_TESSERACT_COMMAND=/usr/bin/tesseract` in the container runtime if OCR is enabled
