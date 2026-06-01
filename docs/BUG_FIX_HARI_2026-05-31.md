# Hari 2026-05-31 Bug Batch — Diagnosis, Fixes, Verdicts, Runbook

Source sheet: `caseOps bugsHari31May2026.xlsx` (BUG-042, BUG-043, BUG-049).
Branch / worktree: `worktree-hari-2026-05-31-bugs` (isolated; Codex CLI untouched).

## TL;DR — why these reopened

The May 30 pass (commit `9c947f2`) **wrote the code and the YAML but never
verified the deployed, credentialed, end-to-end path.** Concretely:

1. `infra/cloudrun/api-service.yaml` + `case-tracking-poll-job.yaml` reference
   Secret Manager secret **`caseops-ecourtsindia-api-token`, which does not
   exist** in project `perfect-period-305406`. A Cloud Run deploy that mounts a
   missing secret fails at secret-resolution — so the eCourts integration could
   not have gone live even if deploy was attempted.
2. `case-tracking-poll-job.yaml` and `legal-update-sync-job.yaml` were committed
   but **never applied** — there is no `caseops-case-tracking-poll` /
   `caseops-legal-update-sync` Cloud Run job and no midnight scheduler in prod.
3. The case-search and watchlist UIs **failed silently** — a configured search
   that returned zero rows rendered nothing, and a watchlist create/run that
   errored showed no message. To the user that is indistinguishable from "search
   returns nothing / inputs unreliable."

The code (provider adapter, bookmark model, poll → notification, watchlist
matching → in-app alert) is largely complete and unit-tested. The defects were
at the **integration / deploy / credential / UX-legibility seams**, which is
exactly the recurring reopen pattern.

## Per-bug verdicts (paired with proof artifacts)

| Bug | Type | Verdict | Proof |
|-----|------|---------|-------|
| BUG-042 | Reopened bug | **Partially fixed** (UI legibility fixed + contract locked; live data blocked on credential) | `apps/web/app/app/case-tracking/page.tsx`; vitest `app/app/case-tracking/page.test.tsx` (2 new cases); Playwright `tests/e2e/hari-2026-05-31-bugs.spec.ts:72,112` PASSED; adapter contract `apps/api/tests/test_case_tracking.py` 21 PASSED. **Live eCourts search = Inconclusive (no API token).** |
| BUG-043 | Enhancement (mostly built) | **Partially fixed** (backend poll→in-app-notification complete + tested; automation not deployed) | `apps/api/tests/test_case_tracking.py::test_case_tracking_refresh_detects_order_and_enqueues_in_app_idempotently` PASSED; Playwright 05-30 bookmark→update flow PASSED. **Nightly poll job not deployed; live = Inconclusive (token).** |
| BUG-049 | Bug + enhancement | **Partially fixed** (silent-failure fixed + matching tested; nightly sync not deployed) | `apps/web/app/app/statutes/page.tsx`; vitest `app/app/statutes/page.test.tsx` (1 new case); Playwright `tests/e2e/hari-2026-05-31-bugs.spec.ts:153,223` PASSED; backend `test_statutes_routes.py` 21 PASSED incl. watchlist match + enqueue. **Nightly sync job not deployed = Inconclusive for automation.** |

No item is marked "Properly fixed": each has a deploy- or credential-blocked leg
that has not been verified on the production surface. Per the bug-fixing skill,
those legs are **Inconclusive** until the runbook below is executed.

## What changed in this branch (surgical)

- `apps/web/app/app/case-tracking/page.tsx` — render the backend error `detail`
  verbatim via `apiErrorMessage()` (was hard-coded "check configuration"); add an
  explicit empty-results state (`case-tracking-search-empty`) so a 0-row search no
  longer renders nothing; surface bookmark errors.
- `apps/web/app/app/statutes/page.tsx` — inline verbatim error for watchlist
  create / run / source-sync mutations (were silent).
- `apps/web/app/app/{case-tracking,statutes}/page.test.tsx` — 3 new vitest cases.
- `tests/e2e/hari-2026-05-31-bugs.spec.ts` — 4 new Playwright specs, wired into
  `playwright.app.config.ts` testMatch.
- `tests/e2e/support/env.ts` + `playwright.app.config.ts` — `CASEOPS_E2E_API_PORT`
  override (default 8000) so the suite runs in a worktree alongside a busy 8000.

Error copy uses `apiErrorMessage()` (duck-typed, logs raw error first) rather than
`instanceof ApiError`, per the cross-module class-identity learning.

## RUNBOOK A — Obtain & install the eCourts India API token (unblocks BUG-042/043)

The product calls `https://webapi.ecourtsindia.com/api/partner/*` with a
`Authorization: Bearer eci_live_...` token. **No such token exists yet** (the sheet
only had the placeholder `eci_live_your_token_here`).

1. **Sign up / get the token.** eCourtsIndia is a paid third-party API (₹200 free
   signup credits). Create an account at https://ecourtsindia.com/api and generate
   a **live** partner token (`eci_live_...`). Note: their docs portal currently
   redirects to a successor host (`court-api.kleopatra.io`); confirm the live base
   URL and the exact **search query-parameter names** on the dashboard at signup
   (see Residual risk below — our adapter currently sends `query`/`courtCodes`; the
   documented example uses `advocates`/`courtCodes`/`filingDateFrom`).
2. **Store it in Secret Manager** (never on a command line — use a file):
   ```powershell
   # token in a local file token.txt (no trailing newline), then:
   gcloud secrets create caseops-ecourtsindia-api-token `
     --replication-policy=automatic --data-file=token.txt
   Remove-Item token.txt
   ```
   If the secret should be readable by the API/job service account:
   ```powershell
   gcloud secrets add-iam-policy-binding caseops-ecourtsindia-api-token `
     --member="serviceAccount:<API_SERVICE_ACCOUNT>" `
     --role="roles/secretmanager.secretAccessor"
   ```
3. **Confirm the base URL** in `infra/cloudrun/api-service.yaml`
   (`CASEOPS_ECOURTSINDIA_API_BASE_URL`) matches the live host before deploy.
4. **Deploy** via the canonical script (see Runbook B). After deploy, the
   `/api/case-tracking/status` endpoint must return `configured=true`.
5. **Verify live** (the leg currently Inconclusive): run a real search by CNR
   (fully documented path `/api/partner/case/{cnr}`) and confirm a result row
   renders, then bookmark and refresh.

## RUNBOOK B — Deploy the automation (unblocks BUG-043 polling + BUG-049 sync)

Prereq for the case-tracking poll job: Runbook A complete (the poll job mounts the
eCourts secret and will fail to deploy without it). The **legal-update sync job
needs no token** (PRS source is public) and can be deployed independently.

```powershell
# Canonical deploy (creates/updates the two jobs + midnight Asia/Kolkata schedulers):
infra/cloudrun/deploy.ps1   # see params: LegalUpdateSchedulerJobName, CaseTrackingSchedulerJobName
```

The deploy script already renders `legal-update-sync-job.yaml` +
`case-tracking-poll-job.yaml` and calls `Ensure-SchedulerJob` for both at
`0 0 * * *` Asia/Kolkata. Also set `CASEOPS_LEGAL_UPDATE_SYNC_ENABLED=true`
(the job manifest already does) so the nightly run is not a no-op.

Post-deploy verification (do NOT mark Properly fixed without this):
```powershell
gcloud run jobs list --region=asia-south1 | Select-String "case-tracking-poll|legal-update-sync"
gcloud scheduler jobs list --location=asia-south1 | Select-String "case-tracking-poll-midnight|legal-update-sync-midnight"
gcloud run jobs execute caseops-legal-update-sync --region=asia-south1 --wait   # PRS sync smoke
```

## Residual risk — unverified search parameter contract (BUG-042)

`EcourtsIndiaApiProvider.search_cases` sends the free-text term as `query=` and
`litigants=`. The only **documented** eCourts search example uses
`advocates`, `courtCodes`, `filingDateFrom`. I could not reach the live docs
(403 / auth-gated) and have no token, so I did **not** change the param names
blindly — that is the exact guess-the-contract mistake from May 30. CNR lookup
(`/api/partner/case/{cnr}`) is fully documented and works. **Action for the token
holder:** run one live free-text search; if it returns nothing while CNR works,
correct the param name in `search_cases` (one line) — the contract test in
`test_case_tracking.py` documents the current assumption.

## Local toolchain note (Node)

The repo is already standardized on **Node 22.14.0** (`.nvmrc`, every CI workflow
`node-version: "22"`, Docker base `node:22.14.0-alpine`). The only gap was a local
shell defaulting to Node 16, which breaks vitest/rolldown (`styleText` needs Node
≥20.12). To make local match durably: use a version manager that honors `.nvmrc`
(fnm/nvm auto-switch on `cd`), and optionally add an `engines.node: ">=22.14 <23"`
field to `package.json` so the wrong runtime fails fast.
