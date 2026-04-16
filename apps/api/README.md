# CaseOps API

This service hosts the CaseOps backend APIs. The initial skeleton includes:

- application settings bootstrap
- health and metadata routes
- a root router for future module expansion
- test coverage for startup and health behavior

## Run Locally

```powershell
uv sync
uv run uvicorn caseops_api.main:app --reload --app-dir src
```
