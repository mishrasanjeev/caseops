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
