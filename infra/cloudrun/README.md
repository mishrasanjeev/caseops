# Cloud Run Deployment Assets

Production (`perfect-period-305406`, `asia-south1`) has exactly two checked-in
writers:

- `scripts/deploy-prod.sh` releases the `caseops-api` and `caseops-web`
  services and the release-owned seed and backfill jobs. It is the only writer
  of `caseops-api` and the only definition of `caseops-migrate-job`: step 2
  creates or updates that job with its complete contract (command, arguments,
  environment, secrets, identity, Cloud SQL, resources, retries and task
  timeout) and reads every field back before alembic runs. Run it as described
  in `docs/GCP_DEPLOY.md`.
- `scheduler-inventory.json` is the only definition of the recurring Cloud Run
  jobs and their Cloud Scheduler triggers. `scripts/scheduler_inventory.py`
  converges it on every release (called by `deploy-prod.sh`), grants each job's
  invoker binding before its trigger, and compares every job's `bootstrap`
  contract (command, arguments, environment, secrets, identity and resources)
  with the live job.

No checked-in Cloud Run service or job manifest exists. Never recreate or
replace a service or job from one (`gcloud run services replace`,
`gcloud run jobs replace`); `apps/api/tests/test_cloudrun_service_ownership.py`
fails on a service or job manifest and on a replace invocation.

## The caseops-api service

`deploy-prod.sh` deploys `caseops-api` with `gcloud run deploy`, which keeps
every value the release does not set. Every release sets this contract, and
`apps/api/tests/test_deploy_prod_hardening.py` pins the executed command:

- Two containers. `api` runs the API image with no command override, so the
  image `CMD` (`uvicorn caseops_api.main:app --no-proxy-headers --host 0.0.0.0 --port ${PORT}
  --app-dir src`) serves on port 8080 with 2 CPU and 4 GiB. `clamav` runs the
  ClamAV image already deployed to the service.
- TCP startup probes on 8080 and 3310: initial delay 0, period 2 s, timeout
  1 s, failure threshold 120. The API starts without waiting for the sidecar
  and its lifespan refuses to serve until clamd answers
  (`CASEOPS_CLAMAV_REQUIRED=true`).
- Concurrency 1, a 120-second request timeout, a service-level minimum of 4
  and maximum of 20 instances, a revision maximum of 20 and no revision-level
  minimum.
- Request-based billing (`--cpu-throttling`: CPU only while a request is in
  flight) and startup CPU boost (`--cpu-boost`). Both apply to the revision
  template, so they precede the first `--container`; gcloud parses every
  later argument as a per-container flag and rejects them there.

A new project gets the same contract from section 6 of `docs/GCP_DEPLOY.md`;
`apps/api/tests/test_cloudrun_service_ownership.py` compares that command with
the release and loads its environment through the production settings
validators.

After routing, the release reads back the sidecar, the API startup probe, the
ClamAV probe delay, period, timeout and failure threshold, the scanner
requirement, startup independence, request-based billing, startup CPU boost,
concurrency, the request timeout, the service minimum and maximum, the
revision maximum and the absence of an API command or argument override, and
withholds certification on any drift. A missing `cpu-throttling` annotation
counts as request-based billing, which is Cloud Run's default. The release
refuses to deploy at all when the live service has no ClamAV container to
carry forward. `scripts/eg003-apply-clamav.sh` is the repair path: it re-adds the
sidecar to an export of the live service, and the next release converges the
probes and startup order.

The ClamAV image and resources (1 CPU, 1500 MiB) and every environment value
outside the release's `--update-env-vars` and `--update-secrets` (for example
`CASEOPS_ENV=production`, CORS, the document bucket, the embedding provider,
SendGrid and eCourts bindings) are live service state. They were set outside the release script, at
bootstrap, by the EG-003 repair or by earlier service updates, and each
release carries them forward unchanged. Every sensitive value is a Secret
Manager reference (verified on 2026-09-27).

## Retired on 2026-09-27

`api-service.yaml` and `deploy.ps1` were removed because neither was a live
deploy path:

- All 472 `caseops-api` revisions, configuration generations 1 to 472 from
  19 April to 27 September 2026 with none deleted, lack the manifest's
  `uv run` command, `cpu-throttling: "false"` (instance-based billing),
  `gen2` execution environment, secrets annotation and manifest-only
  environment values. The manifest also set `CASEOPS_ENV=cloud` with no
  scanner host, so a revision replaced from it could not have passed the
  required-scanner fence, and the next release would have stopped on the
  missing ClamAV container.
- `deploy.ps1` stopped applying the manifest on 31 May 2026 (PR #94). Its
  job and scheduler path never ran against production: 400 days of admin
  audit logs contain no `caseops-document-worker` job or trigger, which that
  script created first. IPLF-001B made the inventory the only scheduler and
  job owner on 1 August 2026.

The six job manifests were removed on the same day (EH-DEPLOY-04 in
`docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`). No tool applied any of them:

- `activity-report-job.yaml`, `case-tracking-poll-job.yaml`,
  `ip-journal-watch-job.yaml` and `legal-update-sync-job.yaml` ran `uv run`
  commands, which the inventory forbids, with an unrendered auth-secret
  version. The live jobs equal their inventory `bootstrap` contracts. Audit
  logs show that only `caseops-legal-update-sync` and
  `caseops-case-tracking-poll` were ever created from these files, by a manual
  `gcloud run jobs replace` on 31 May 2026; the inventory has converged them
  since 1 August 2026.
- `migrate-job.yaml` was never applied: the job was created with
  `gcloud run jobs create` on 23 April 2026. Its environment omitted
  `CASEOPS_AUTO_MIGRATE=false`, so the cloud settings validator would have
  stopped alembic before it started.
- `document-worker-job.yaml` described a worker that was never provisioned and
  could not start in cloud: it set no `CASEOPS_AUTH_SECRET`. The worker runs
  only in the local Compose stack and Docker acceptance. A production worker
  would be a new inventory entry.

## Notes

- `Secret Manager` holds a dedicated 32+ byte
  `caseops-machine-readiness-evidence-secret`, distinct from the auth secret;
  the same value is configured as the GitHub Actions secret
  `CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET`.
- The case tracking poll job runs `caseops-poll-tracked-cases` every five
  minutes from 6:00 PM to 7:55 PM Asia/Kolkata, inside the configured 6:00 PM
  to 8:00 PM refresh window. Production/cloud runs refuse to start new provider
  calls outside that window unless an operator uses `--force`; any unfinished
  backlog remains visible in provider operations and resumes on the next
  scheduled run.
- The hearing reminders job runs `caseops-send-hearing-reminders` on the
  `caseops-reminders-cadence` scheduler, as documented in
  `docs/runbooks/hearing-reminder-channels.md`.
- The QG-OPS-006 gate (`scripts/check_cloudrun_manifest_secrets.py
  infra/cloudrun` in `.github/workflows/security.yml`) reads every inventory
  `bootstrap` contract. A secret-like name in `environment` or a `secrets`
  value other than a Secret Manager `<secret>:<version>` reference fails, and
  a directory with no definitions fails closed.
- OCR uses the `tesseract` installed in the API image.
- The live service does not override `CASEOPS_DOCUMENT_STORAGE_CACHE_PATH`, so
  the settings default (`./storage/document-cache` under the image's `/app`
  working directory) applies on Cloud Run's ephemeral container filesystem.
