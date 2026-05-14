# Release Sign-Off Evidence

- Generated at: `2026-05-14 22:26 +05:30`
- Reviewer: `Codex`
- Environment: `prod`
- Target commit: `05b3025d63a10a86eb30a1637f4bc9625bb33a65`
- Deployed build fingerprint URL: `not available as an app URL; Cloud Run service metadata proves image tags`
- Verdict: `GO with caveat`

## Scope

- Release or change set under review: production release unblock for PR #34, increasing API Cloud Run memory headroom after the recommendations smoke hit a raw Google Frontend 503 on the prior production revision.
- Bug sheet or ticket scope: production Cloud Run recommendations OOM release blocker.
- Declared exclusions: no new feature work, no corpus ingest/backfill/embedding jobs, no product/backend/frontend code changes, no staging secret changes.

## Build Identity

- Expected commit: `05b3025d63a10a86eb30a1637f4bc9625bb33a65`
- Observed commit or build id:
  - API image: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api:05b3025d63a10a86eb30a1637f4bc9625bb33a65`
  - Web image: `asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-web:05b3025d63a10a86eb30a1637f4bc9625bb33a65`
- Proof:
  - API revision `caseops-api-00137-57k` serves 100% traffic.
  - Web revision `caseops-web-00126-l97` serves 100% traffic.
  - `scripts/deploy-prod.sh` staleness sweep reported both API and Web tags match `05b3025d63a10a86eb30a1637f4bc9625bb33a65`.
  - `gcloud run services describe caseops-api` showed API runtime `2 CPU`, `4Gi`, concurrency `40`, timeout `300s`, and the `clamav/clamav:1.4` sidecar present.

## Checks

| Check | Command / URL | Result | Notes |
| --- | --- | --- | --- |
| Main CI | `gh run watch 25869435803 --exit-status --interval 30` | pass | API, Web, Postgres + pgvector, Playwright app suite, and staging deploy gate completed; staging deploy was a credential-gated no-op. |
| Security | `gh run list --commit 05b3025d63a10a86eb30a1637f4bc9625bb33a65` | pass | Security workflow run `25869435775` succeeded. |
| CodeQL | `gh run list --commit 05b3025d63a10a86eb30a1637f4bc9625bb33a65` | pass | CodeQL Advanced run `25869435630` succeeded. |
| Production deploy | `scripts/deploy-prod.sh 05b3025d63a10a86eb30a1637f4bc9625bb33a65` | pass | API build `a11231f2-4c14-4af7-bbaf-6093507650dd`; Web build `9166259a-ddf9-4195-a79c-d58741941499`. |
| Migration job | `caseops-migrate-job-jz7vb` | pass | Cloud Run job completed before API/Web deploy. |
| API health | `curl.exe -fsS https://api.caseops.ai/api/health` | pass | Response: `{"status":"ok"}`. |
| API runtime fingerprint | `gcloud run services describe caseops-api --region asia-south1 --project perfect-period-305406` | pass | API revision `caseops-api-00137-57k`, 100% traffic, image tag matches target SHA, `2 CPU`, `4Gi`, concurrency `40`, timeout `300s`. |
| Web runtime fingerprint | `gcloud run services describe caseops-web --region asia-south1 --project perfect-period-305406` | pass | Web revision `caseops-web-00126-l97`, 100% traffic, image tag matches target SHA. |
| ClamAV sidecar guard | `scripts/deploy-prod.sh` post-deploy guard | pass | Deploy script reported `EG-003 clamav sidecar present.` |
| Prod Playwright ram-batch | `gh workflow run prod-verify.yml --ref main`; `gh run watch 25872371950 --exit-status --interval 30` | pass | Manual post-deploy prod verification run `25872371950` passed in `15m10s`. |

## Caveats

- Staging deploy remains a visible no-op until GCP staging Workload Identity and secrets are configured: `GCP_PROJECT_ID`, `GCP_REGION`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SA`, and staging DB/auth secrets.
- Production runtime proof is stronger than staging proof for this release: API/Web deployed images match the target SHA, health is OK, migrations completed, API resource settings match the OOM unblock, and prod Playwright ram-batch passed after deployment.

## Commands Run

```text
git fetch origin main
gh run watch 25869435803 --exit-status --interval 30
gh run list --commit 05b3025d63a10a86eb30a1637f4bc9625bb33a65 --limit 10 --json databaseId,name,status,conclusion,headSha,createdAt,url
git switch --detach 05b3025d63a10a86eb30a1637f4bc9625bb33a65
scripts/deploy-prod.sh 05b3025d63a10a86eb30a1637f4bc9625bb33a65
gcloud run services describe caseops-api --region asia-south1 --project perfect-period-305406 --format="json(...)"
gcloud run services describe caseops-web --region asia-south1 --project perfect-period-305406 --format="json(...)"
curl.exe -fsS https://api.caseops.ai/api/health
gh workflow run prod-verify.yml --ref main
gh run watch 25872371950 --exit-status --interval 30
```

## Reviewer Notes

- Release blocker resolved operationally by PR #34: API Cloud Run deploy now pins `2 CPU`, `4Gi`, concurrency `40`, timeout `300s`; `infra/cloudrun/api-service.yaml` is aligned to the same settings.
- Production deploy used the canonical script path and did not run any corpus ingest, backfill, embedding, scraping, or feature work.
- Final release status is `GO with caveat`.

## Fail-Closed Reminder

- A clean `GO` is not issued because staging runtime proof remains unavailable.
- The release is acceptable as `GO with caveat` because production build identity, health, migration completion, runtime resource settings, ClamAV sidecar presence, and post-deploy prod Playwright evidence are all present.
