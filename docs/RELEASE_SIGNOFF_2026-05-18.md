# Release Sign-Off Evidence

- Generated at: `2026-05-18 17:57 +05:30`
- Reviewer: `Codex`
- Environment: `prod`
- Target commit: `70e3871edd87f8434dd52e721ae51c4a9e356c5d`
- Commit summary: `[codex] Add Temporal runtime foundation`
- Deployed build fingerprint URL: `not available as an app URL; Cloud Run service metadata and deploy script staleness check prove image tags`
- Verdict: `GO with caveat`

## Scope

- Release or change set under review: production deployment of commit `70e3871edd87f8434dd52e721ae51c4a9e356c5d`.
- Bug sheet or ticket scope: PR #50 API CI pytest coverage sharding and PR #48 WTD-5.1b Temporal Durable Workflow Runtime Foundation after both PRs merged to `origin/main`.
- Declared exclusions: no product/runtime code changes during signoff, no new product milestones, no staging deploy workflow changes, no corpus ingest/backfill/embedding jobs, and no secret exposure.

## Build Identity

- Expected commit: `70e3871edd87f8434dd52e721ae51c4a9e356c5d`
- Observed commit or build id:
  - API image: `caseops-api:70e3871`
  - Web image: `caseops-web:70e3871`
  - API service revision: `caseops-api-00144-j5g`
  - Web service revision: `caseops-web-00131-f4w`
  - Migration job execution: `caseops-migrate-job-tfw7l`
- Proof:
  - `scripts/deploy-prod.sh 70e3871` completed successfully.
  - API revision `caseops-api-00144-j5g` serves 100% production traffic.
  - Web revision `caseops-web-00131-f4w` serves 100% production traffic.
  - Deploy script staleness check reported `api=70e3871 web=70e3871`.
  - API health response was `{"status":"ok"}`.
  - ClamAV sidecar check passed.
  - Local worktree was clean before signoff doc creation.

## Checks

| Check | Command / Evidence | Result | Notes |
| --- | --- | --- | --- |
| Production deploy | `scripts/deploy-prod.sh 70e3871` | pass | Built API and Web images, ran migration job, deployed both Cloud Run services, and completed post-deploy checks. |
| API build | Cloud Build `5c2f1472-854a-4de5-a0b0-8a271ed95d05` | pass | Published `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api:70e3871`. |
| Web build | Cloud Build `0ef5c17a-fcab-4d51-bb1a-7fdbe52d2bb4` | pass | Published `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-web:70e3871`. |
| Migration job | `caseops-migrate-job-tfw7l` | pass | Completed before API and Web deploy. |
| API runtime fingerprint | `gcloud run services describe caseops-api --region asia-south1 --project perfect-period-305406` | pass | Revision `caseops-api-00144-j5g`, image `caseops-api:70e3871`, latest revision at 100% traffic. |
| Web runtime fingerprint | `gcloud run services describe caseops-web --region asia-south1 --project perfect-period-305406` | pass | Revision `caseops-web-00131-f4w`, image `caseops-web:70e3871`, latest revision at 100% traffic. |
| API health | `curl.exe -fsS https://api.caseops.ai/api/health` | pass | Response: `{"status":"ok"}`. |
| Deploy staleness check | `scripts/deploy-prod.sh` post-deploy guard | pass | Reported `api=70e3871 web=70e3871`. |
| ClamAV sidecar guard | `scripts/deploy-prod.sh` post-deploy guard | pass | Reported `EG-003 clamav sidecar present.` |
| Local worktree | `git status --short` | pass | Clean before doc creation. |

## Caveats

- Staging proof remains unavailable/skipped for this release. No staging deploy workflow was changed or run as part of this signoff.
- No additional prod Playwright verification was run after this deployment during this signoff task. Confidence is based on the successful canonical production deploy path, migration completion, Cloud Run runtime fingerprints, API health, image staleness check, and ClamAV sidecar guard.
- The verdict is `GO with caveat` rather than a clean `GO` because staging runtime proof remains unavailable.

## Commands Run

```text
git status --short
git fetch origin main
git switch --detach origin/main
scripts/deploy-prod.sh 70e3871
gcloud run services describe caseops-api --region asia-south1 --project perfect-period-305406 --format="json(status.traffic)"
gcloud run services describe caseops-web --region asia-south1 --project perfect-period-305406 --format="json(status.traffic)"
curl.exe -fsS https://api.caseops.ai/api/health
git status --short
git diff --check
```

## Reviewer Notes

- The production deploy used the canonical `scripts/deploy-prod.sh` path.
- The deploy did not run corpus ingest, backfill, embedding, scraping, provider delivery, or new product milestone work.
- No secrets are recorded in this signoff.

## Fail-Closed Reminder

- Do not treat this as a clean `GO` until staging runtime proof is available or an explicit release waiver is recorded.
- If production runtime tags drift from `70e3871`, re-run the build identity and health checks before relying on this signoff.
