# Strict Repository Quality Audit - 2026-07-10

Verdict: **NO-GO** for a release-grade sign-off.

The audited code now contains targeted fixes for the highest-confidence
security and workflow defects found in this pass. The verdict remains NO-GO
because those fixes are not deployed, the canonical monolithic backend run
exited unexpectedly before completion, provider and disaster-recovery proof
was not rerun, and several infrastructure gaps remain open.

## Scope

- Repository: CaseOps at commit 1aef504 before this audit's local changes.
- Surfaces: apps/api, apps/web, tests/e2e, scripts, infra, Docker, and GitHub
  Actions workflows.
- Product mapping: J01-J15 and M01-M15, with direct fixes concentrated in
  J01/M01, J02/M02, J08/M08, J11/M10, J14/M14, and J15/M15.
- Test mapping: QG-AUTH, QG-API, QG-UI, QG-SEC, QG-OPS, FT-042, FT-070,
  FT-071, FT-072, FT-075, SEC-001, SEC-003, SEC-007, SEC-017, and SEC-018.
- User-owned untracked artifacts were recorded and preserved:
  .vvaharness-remediate-off,
  docs/E2E_FULL_FUNCTIONAL_NONFUNCTIONAL_SECURITY_TEST_REPORT_2026-07-09.md,
  and outputs/.

## Current Inventory

| Surface | Current evidence |
| --- | --- |
| OpenAPI | 423 paths and 491 operations |
| Backend source | 302 Python files and 37 route modules |
| Backend tests | 174 pytest modules after this audit's additions; 1,993 tests were collected by the interrupted canonical run |
| Frontend routes | 87 page.tsx routes |
| Direct page tests | 77 of 87 pages have sibling page.test.tsx coverage |
| Frontend tests | 112 Vitest files and 507 tests after this audit's additions |
| Browser tests | 54 Playwright specs, about 166 statically counted tests, 26 skip sites |
| CI | 6 workflow files |
| Largest backend hotspots | db/models.py 11,427 lines; services/matters.py 4,054; services/calendar_sync.py 3,501; routes/matters.py 3,297 |
| Largest web hotspots | generated openapi-types.ts 38,708 lines; manual endpoints.ts 7,329; schemas.ts 3,689; documents page 2,449; hearings page 2,039 |

## Verification Snapshot

| Command or check | Result |
| --- | --- |
| scripts/verify-backend.ps1 | Ruff passed; pytest collected 1,993 tests, then the Python process exited -1 near 5 percent without a traceback |
| Targeted authority-treatment isolation | 11 passed; the boundary file was not the cause of the process exit |
| Frontend read-only baseline | 109 files and 469 tests passed; TypeScript passed |
| Portal security regressions | 27 targeted tests passed |
| Release/build hardening regressions | 17 tests passed; Ruff, config discovery, and bash syntax passed |
| Legal-date regression under America/Los_Angeles | Failed 6 tests before the first fix; 89 timezone-sensitive tests passed across the expanded audit set |
| Cause-list CSRF regression | Failed before the fix; passed after the fix |
| Page-waiver regression | Exposed 20 stale waivers before cleanup; passed after cleanup |
| Current full frontend coverage gate | 112 files and 507 tests passed; statements 48.65%, branches 41.15%, functions 38.60%, lines 51.00% |
| Current TypeScript and production build | Passed; Next.js generated all 62 static pages |
| Git diff check | Passed, with line-ending advisory warnings only |

The interrupted monolithic backend run is not counted as a suite pass.
Deterministic no-coverage shards are being used as the next strongest local
proof and their final results must be retained with the change.

## Findings and Fix Status

### QG-20260710-001 - Portal magic-link token exposed in the cloud profile

- Severity: Critical.
- Bug verdict: Inconclusive pending deployed managed-environment proof.
- Hardening status: Partially implemented.
- Root cause: the portal treated every environment except production/prod as
  non-production, while Cloud Run uses CASEOPS_ENV=cloud. The request-link and
  admin-invite responses therefore returned plaintext debug tokens, and the
  mailer did not send the ownership challenge.
- Local remediation: all debug-token and delivery decisions now use the shared
  strict local/non-local classifier. Cloud, staging, and unknown managed names
  hide the token and take the mail-delivery path.
- Evidence: portal.py, portal_mailer.py, and test_portal_auth.py.

### QG-20260710-002 - Portal invite scope and single-use guarantees drifted

- Severity: High.
- Bug verdict: Inconclusive pending deployed end-user proof.
- Hardening status: Partially implemented.
- Root causes: invitations accepted arbitrary matter IDs without validating
  tenant ownership; re-invites did not replace grant permissions; magic-link
  consumption used a read/check/write race.
- Local remediation: validate and deduplicate the complete matter set before
  mutation, replace scope on re-invite, and claim a magic link with a
  conditional update requiring exactly one affected row.
- Evidence: portal_auth.py and test_portal_auth.py.

### QG-20260710-003 - RFC 7807 errors were parsed as opaque text

- Severity: High.
- Bug verdict: Inconclusive pending browser proof on a deployed build.
- Hardening status: Partially implemented.
- Root cause: the web client recognized application/json but not
  application/problem+json, losing detail/type and bypassing refresh logic.
- Local remediation: parse application/json and any structured +json media
  type. Added transport tests for 422 and expired-session 401 responses.
- Evidence: lib/api/client.ts and lib/api/client.test.ts.

### QG-20260710-004 - Sign-out cleared UI state but left the server cookie live

- Severity: High.
- Bug verdict: Inconclusive pending deployed browser proof.
- Hardening status: Partially implemented.
- Root cause: logout used raw fetch without the required double-submit CSRF
  header and cleared local state regardless of the 403.
- Local remediation: logout uses the shared cookie/CSRF-aware client, always
  clears local state in finally, propagates server failure, and avoids a false
  success toast.
- Evidence: use-session.ts, Topbar.tsx, and their tests.

### QG-20260710-005 - Post-login redirect and portal auth boundaries were unsafe

- Severity: High.
- Bug verdict: Inconclusive pending deployed password and MFA browser proof.
- Hardening status: Partially implemented.
- Root causes: next was passed directly to router.replace; portal 401s could
  invoke employee refresh and redirect to employee sign-in.
- Local remediation: accept only canonical /app paths; reject absolute,
  protocol-relative, backslash, control-character, traversal, and encoded
  separator variants. Portal requests never use employee refresh and redirect
  only to /portal/sign-in.
- Evidence: safe-next-path.ts, SignInForm.tsx, client.ts, and tests.

### QG-20260710-006 - Cause-list PDF POST omitted CSRF

- Severity: High.
- Bug verdict: Inconclusive pending deployed browser-download proof.
- Hardening status: Partially implemented.
- Root cause: blob generation used raw fetch with cookies but no CSRF header.
- Local remediation: expose the shared CSRF header helper and use it for the
  protected cause-list PDF POST.
- Evidence: endpoints.ts and endpoints.test.ts.

### QG-20260710-007 - Legal dates shifted by timezone

- Severity: High for court and filing workflows.
- Bug verdict: Inconclusive pending deployed UTC-negative browser proof.
- Hardening status: Partially implemented.
- Root cause: several portal and portfolio surfaces parsed YYYY-MM-DD at UTC
  midnight; date-input defaults used UTC conversion.
- Local remediation: use the legal-date parser for all audited calendar-date
  rendering/range paths and local calendar components for date-input defaults.
- Evidence: dates.ts, portal pages, dashboard, portfolio, hearings, matter
  overview, notices, Today, documents, predictive intelligence, litigation
  review, and 89 tests across the timezone-sensitive sets.

### QG-20260710-008 - Build source could leak secrets or misrepresent a commit

- Severity: Critical.
- Bug verdict: Inconclusive pending the next controlled production deploy.
- Hardening status: Partially implemented.
- Root causes: apps/api lacked context-local secret ignores; deploy-prod could
  upload current dirty bytes under a caller-provided SHA.
- Local remediation: context-local Cloud Build and Docker ignores exclude
  .env variants, virtual environments, caches, and runtime data while retaining
  .env.example. Deploy requires the requested ref to equal HEAD and rejects a
  dirty API/web build context before gcloud.
- Evidence: apps/api/.gcloudignore, apps/api/.dockerignore,
  scripts/deploy-prod.sh, and fake-command regression tests.

### QG-20260710-009 - Cloud Run literal-secret CI gate could never match

- Severity: High.
- Bug verdict: Inconclusive until the GitHub Security workflow passes.
- Hardening status: Partially implemented.
- Root cause: grep examined a value line and then searched that same line for
  the env name located on the preceding YAML line.
- Local remediation: a PyYAML scanner associates env names with value/valueFrom,
  requires secretKeyRef for secret-like names, and reports file and line.
- Evidence: check_cloudrun_manifest_secrets.py, security.yml, and scanner tests.

### QG-20260710-010 - Deploy health certification failed open

- Severity: High.
- Bug verdict: Inconclusive pending the next controlled deploy.
- Hardening status: Partially implemented.
- Root cause: curl failure was converted to a JSON string and never validated.
- Local remediation: network failure, malformed JSON, and any status other than
  ok stop the deploy before the DONE message.
- Evidence: deploy-prod.sh and fake curl regression tests.

### QG-20260710-011 - Pine Labs exceptions leaked provider internals

- Severity: High.
- Bug verdict: Inconclusive pending deployed provider-failure proof.
- Hardening status: Partially implemented.
- Root cause: raw exception strings were interpolated into client-visible 502
  details for create and sync.
- Local remediation: retain only sanitized server diagnostics (tenant/object
  identifiers and provider error type) and return stable actionable messages;
  planted provider secrets appear in neither client responses nor logs.
- Evidence: payments.py and payment regressions.

### QG-20260710-012 - Page coverage waivers masked deleted tests

- Severity: Medium.
- Bug verdict: Inconclusive until CI runs the updated matrix.
- Hardening status: Partially implemented.
- Root cause: 20 pages had both a test and a waiver; deleting their tests would
  still pass.
- Local remediation: remove stale waivers and fail when any waiver points to a
  missing page or to a page that now has a sibling test.
- Evidence: app/__page-coverage-matrix.test.ts.

### QG-20260710-013 - Required MFA enrollment stranded users

- Severity: Medium-high.
- Bug verdict: Inconclusive pending end-to-end enrollment proof.
- Hardening status: Partially implemented.
- Root cause: sign-in preserved next on the enrollment URL, but the security
  page ignored it and offered no post-recovery-code navigation.
- Local remediation: recovery codes remain visible and a safe Continue to
  workspace action uses the same post-login path sanitizer.
- Evidence: account/security page and page test.

### QG-20260710-014 - Production browser failures retained authenticated media

- Severity: High.
- Bug verdict: Inconclusive until the production CI failure path is inspected.
- Hardening status: Partially implemented.
- Root cause: both production Playwright configs retained traces, screenshots,
  and videos on failure while using an authenticated QA storage state. Those
  artifacts can contain legal data and session-bearing requests.
- Local remediation: live-tenant configs now retain text diagnostics only and
  explicitly disable trace, screenshot, and video capture. A structural test
  prevents re-enabling authenticated browser media accidentally.
- Evidence: playwright.prod-ram.config.ts, playwright.notice-prod.config.ts,
  and test_deploy_prod_hardening.py.

### QG-20260710-015 - Pine Labs callbacks targeted nonexistent or wrong hosts

- Severity: High.
- Bug verdict: Inconclusive pending Pine Labs UAT/deployed redirect proof.
- Hardening status: Partially implemented.
- Root cause: the customer return URL targeted `/billing/invoices/{id}`, which
  has no frontend route, while the provider webhook reused the frontend app
  origin instead of the API request origin. Pydantic's normalized trailing
  slash also produced a double slash in both URLs.
- Local remediation: customer completion returns to the existing matter billing
  page with a normalized app origin; webhook registration uses FastAPI's named
  API route URL derived from the incoming API origin.
- Evidence: routes/payments.py, services/payments.py, and the Pine Labs happy-path
  regression in test_company_profile_and_matters.py.

## Remaining Confirmed Gaps

| ID | Status | Gap |
| --- | --- | --- |
| REM-20260710-001 | Partially implemented | The checked-in document worker manifest still depends on deployment-time database substitution and lacks a declarative auth-secret reference; the PowerShell deploy path can render plaintext credentials into a temporary YAML. |
| REM-20260710-002 | Partially implemented | Live-tenant media capture is now disabled, but release-mode local/provider artifacts and uploaded text reports still need a documented redaction/content audit. |
| REM-20260710-003 | Partially implemented | Document and court-sync workers select queued jobs before claiming them atomically; overlapping schedules can duplicate external side effects. |
| REM-20260710-004 | Partially implemented | API and web container builds do not install exclusively from committed lockfiles and some runtime commands can trigger dependency resolution. |
| REM-20260710-005 | Missing | The marketing demo-request route can acknowledge a lead without durable persistence when SMTP is absent or fails. |
| REM-20260710-006 | Missing | PDF viewer Search advances one page and reports a match without inspecting document text. |
| REM-20260710-007 | Partially implemented | Pine Labs return/webhook URLs are corrected locally; provider UAT must prove the deployed redirect and signed webhook reach the intended app/API hosts. |
| REM-20260710-008 | Partially implemented | Release verification does not bind provider tests and production smoke to a proven deployed full SHA/image digest. |
| REM-20260710-009 | Partially implemented | Full backend verification is resource-fragile on this Windows workspace; the monolithic process exited -1 and sharded completion evidence is required. |
| REM-20260710-010 | Partially implemented | Numeric frontend coverage still excludes page.tsx even though page tests now exist for most routes; axe coverage remains five routes out of 87. |

## Stable Regression Test List

| ID | Required test |
| --- | --- |
| JUL10-AUTH-001 | Cloud, staging, and unknown managed environments never return a portal debug token. |
| JUL10-AUTH-002 | Managed environments attempt portal mail delivery; explicit local/test environments do not. |
| JUL10-AUTH-003 | Mixed-tenant invite matter IDs reject before creating a portal user or grant. |
| JUL10-AUTH-004 | Re-invite deduplicates IDs and can tighten true permissions to false. |
| JUL10-AUTH-005 | A magic-link conditional claim succeeds once and replay fails. |
| JUL10-AUTH-006 | Problem+JSON preserves detail/type and triggers one employee refresh/retry. |
| JUL10-AUTH-007 | Portal 401 performs no employee refresh and lands at portal sign-in. |
| JUL10-AUTH-008 | Logout sends cookies and CSRF, clears local state, and reports server rejection honestly. |
| JUL10-AUTH-009 | Password and MFA success reject every external/traversal next value. |
| JUL10-AUTH-010 | Required MFA enrollment shows recovery codes before safe continuation. |
| JUL10-API-001 | Cause-list PDF POST includes the current double-submit CSRF value. |
| JUL10-API-002 | Pine create and sync 502 details never include a planted secret. |
| JUL10-API-003 | Pine return URL resolves to matter billing and webhook URL resolves to the named API route without double slashes. |
| JUL10-DATE-001 | Portal list/detail/hearing dates retain their SQL calendar day under America/Los_Angeles. |
| JUL10-DATE-002 | Date-input defaults use local components around local midnight. |
| JUL10-OPS-001 | API Cloud Build and Docker ignore secret/cache canaries but retain .env.example. |
| JUL10-OPS-002 | Literal secret env values fail the YAML scanner; valid secretKeyRef passes. |
| JUL10-OPS-003 | Mismatched ref and dirty build context stop before any gcloud invocation. |
| JUL10-OPS-004 | Network failure, degraded health, and malformed health stop deploy certification. |
| JUL10-OPS-005 | Production Playwright configs keep trace, screenshot, and video capture disabled. |
| JUL10-QA-001 | A page-test waiver is invalid once the sibling test exists. |
| JUL10-QA-002 | All deterministic backend test shards complete without failure. |
| JUL10-QA-003 | Full Vitest, TypeScript, and production Next build pass. |

## Recommended Fix Order

1. Merge and deploy the critical portal/build/auth fixes, then run production
   portal, logout, redirect, cause-list, legal-date, and MFA Playwright probes
   against the exact deployed SHA.
2. Make document-worker secrets fully declarative and remove plaintext YAML
   rendering.
3. Add atomic worker leases/claims with PostgreSQL concurrency tests.
4. Bind release verification to image digest/full SHA and audit the remaining
   text/local-provider artifacts plus QA-session lifetime.
5. Persist demo requests before acknowledging them and implement real PDF text
   search.
6. Make container dependency graphs lockfile-only and network-independent at
   runtime.
7. Expand route/page/accessibility/provider matrices and remove remaining
   baseline waivers.
8. Decompose the largest backend and frontend hotspots in behavior-preserving
   slices after the release/security fixes are stable.

## Required Verification Before Closure

- Run all four deterministic backend shards and Ruff.
- Run full Vitest, TypeScript, Next production build, and updated page matrix.
- Run PostgreSQL validation and migration upgrade proof.
- Run local Playwright for affected end-user workflows.
- Deploy through scripts/deploy-prod.sh from a clean exact HEAD.
- Prove deployed full SHA/image digest and run production Playwright.
- Run provider-gated Pine Labs and SendGrid verification without skips.
- Re-run backup creation, restore, and application cutover evidence.

## Do Not Close Until

- No critical item depends only on local tests.
- The deployed revision identity is proven.
- Portal tokens are absent from every managed-environment response.
- Logout invalidates the HttpOnly cookie in a real browser.
- No required provider test skips in release mode.
- All backend shards, web gates, PostgreSQL validation, and affected browser
  workflows pass.
- Remaining infrastructure and verification gaps are owner-assigned with dated
  evidence rather than represented as complete.
