# Release Signoff - 2026-05-20

## Verdict

GO with caveat.

Production deployment completed for `8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`.
The caveat is that the CI staging deploy job was guarded and skipped its staging deploy
steps; all required test/security checks and production deployment proof passed.

## Release Target

- Deployed SHA: `8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`
- Origin main SHA at release gate: `8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`
- Release signoff generated: `2026-05-20T01:01:47.3470211Z`

## Included Merged Work

- PR #62: `idna` upgraded to `3.15` to remediate `CVE-2026-45409`.
- PR #61: WTD-11.4 AI Safety Eval Harness Foundation.

## CI Gate

Latest `origin/main` checks for `8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`:

- API ruff: success
- API pytest coverage shards 1/4, 2/4, 3/4, 4/4: success
- API combined coverage: success
- Web typecheck, vitest, and build: success
- Postgres + pgvector validation: success
- OpenAPI generated client clean diff: success
- Secret scan / gitleaks: success
- pip-audit high+critical: success
- npm audit high+critical: success
- License allow-list: success
- CodeQL and CodeQL Advanced actions/python/javascript-typescript: success
- Playwright app suite: success
- Cloud Run manifest secret-ref check: success
- Prod verification Playwright workflow: success
- Staging deploy caveat: CI staging deploy job completed, but deploy steps were skipped by guardrail.

## Local Release Sanity

- `git status --short`: clean before deploy
- `git diff --check`: passed before deploy
- `uv --directory apps/api lock --check`: passed
- `uv --directory apps/api run caseops-eval-ai-safety`: passed, 6/6 cases
- `uv --directory apps/api run pytest tests/test_eval_ai_safety.py`: passed, 9/9 tests

Note: the targeted pytest command exited successfully but PowerShell displayed a
post-success pytest temp symlink cleanup warning.

## Deploy Command

Canonical deploy command:

```sh
scripts/deploy-prod.sh 8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2
```

Actual Windows shell invocation used Git Bash because the WSL `bash` launcher was
not available in this environment:

```powershell
C:\Progra~1\Git\bin\bash.exe scripts/deploy-prod.sh 8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2
```

## Build Proof

- API build ID: `21cbafec-78ab-45bd-b5b8-02fc1cb1238f`
- API build status: `SUCCESS`
- API image tag: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api:8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`
- Web build ID: `c5de3115-c05e-4628-9c98-b5b778b82a07`
- Web build status: `SUCCESS`
- Web image tag: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-web:8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`

## Migration Proof

- Migration job: `caseops-migrate-job`
- Migration execution: `caseops-migrate-job-5bzkf`
- Migration status: completed successfully
- Completion time: `2026-05-20T00:58:35.443857Z`

## Cloud Run Proof

- API revision: `caseops-api-00145-cnf`
- API traffic: 100% to latest revision
- API image: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api:8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`
- Web revision: `caseops-web-00132-9h8`
- Web traffic: 100% to latest revision
- Web image: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-web:8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`

## Health And Staleness Proof

- API health endpoint: `https://api.caseops.ai/api/health`
- API health response: `{"status":"ok"}`
- Deploy script staleness check: API and Web both reported
  `8c11af4afef2d6489d3666a2c57d3d3a4bd03ab2`, matching the deployed SHA.
- ClamAV sidecar check: `EG-003 clamav sidecar present.`

## Playwright Proof

- CI Playwright app suite for latest `origin/main`: success
- Prod verification Playwright workflow for latest `origin/main`: success
- Post-deploy prod Playwright: not separately triggered by `deploy-prod.sh`

## Final Notes

- No production model evaluations were run.
- No Temporal config, notifications, corpus cleanup, ingest/backfill/embedding jobs,
  staging workflow changes, or product/runtime code changes were made during release.
- No secrets or API keys are recorded in this signoff.
