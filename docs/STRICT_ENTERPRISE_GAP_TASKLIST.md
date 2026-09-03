# Strict Enterprise Gap Tasklist

This is the fail-closed enterprise hardening ledger for CaseOps.
`docs/WORK_TO_BE_DONE.md` is planning input only. Codex must cross-check
backlog claims against code, tests, and deploy manifests before changing any
status here.

Status legend:

- `Implemented`
- `Partially implemented`
- `Missing`
- `Stale-doc`

## Current Provider And Billing Ledger - 2026-06-02

- Billing/pricing/platform-admin code is `Implemented` and deployed. Manual
  production billing signoff is still pending; use
  `docs/runbooks/production-billing-signoff-2026-06-02.md`.
- Pine Labs production payments are `Missing/UAT blocked` for live enablement.
  Production must remain `CASEOPS_PINE_LABS_ENV=disabled` until UAT credentials,
  webhook registration, product enablement, endpoint schemas, MDR/settlement
  details, test scenarios, and founder go/no-go are complete.
- ADP-20 is `Partially implemented`: readiness-gated CaseOps-to-Outlook hearing
  sync only. Broad two-way Outlook/mailbox/provider webhook automation is not
  included.
- ADP-21 is `Partially implemented`: Google Drive readiness status exists under
  provider operations; durable Drive sync is pending.
- ADP-22 is `Partially implemented`: mailbox connector readiness status exists
  under provider operations; durable mailbox ingestion is pending.
- ADP-23 is `Partially implemented`: in-app digest previews and readiness status
  exist; external digest delivery remains provider-gated and disabled.
- ADP-24 is `Implemented foundation`: tenant admins can list failed/blocked
  provider jobs, see redacted errors, and request audited replay/ignore/resolve
  actions through `/app/admin/provider-operations`.

Current overall verdict (2026-04-25): **`GO`**. Every stop-ship
control gap (EG-001 through EG-007) is closed and live in prod with
evidence. EG-001 (HttpOnly cookies + double-submit CSRF), EG-002
(auto-migrate off + canonical deploy-prod.sh with migrate-job gate),
EG-003 (clamav sidecar wired + fail-closed default + EICAR rejection
prod smoke), EG-004 (per-route AI rate limits), EG-005 (matter
summary cache + ModelRun audit + cross-provider cutover), EG-006
(draft preview tenant policy gate + redacted 502 + ModelRun audit on
both success + failure), EG-007 (every sensitive env in Secret
Manager + 90-day rotation runbook + drill executed in
`caseops-api-00052-5w2`), P1-009 (backup/restore drill). Structural
hardening gaps EG-008 (hotspot decomposition) + EG-009 (exception
discipline) remain `Partially implemented` but are not stop-ship.

## 2026-07-10 Whole-Repository Audit Addendum

Current audit: docs/STRICT_REPO_QUALITY_AUDIT_2026-07-10.md.

Release-evidence verdict for the affected July controls: **NO-GO until their
listed production proof is complete; GO for continued repository
implementation.** The critical code defects below have local regression fixes,
but the affected build has not been deployed and the canonical monolithic
backend verification process exited -1 before completion. Do not treat local
green tests as production enforcement.

- JUL10-EG-001 **Partially implemented** Portal authentication boundary.
  Local code now hides debug tokens and sends magic links for cloud, staging,
  and unknown managed environment names; invitation matter IDs are
  tenant-validated, re-invite scopes are replaced, and magic-link consumption
  uses a conditional single-use claim. Remaining: deploy and run authenticated
  production portal Playwright against the exact revision.
- JUL10-EG-002 **Partially implemented** Browser session/error boundary.
  Local code parses RFC 7807 media types, sends CSRF on logout and cause-list
  generation, sanitizes post-login redirects, and keeps portal 401 handling
  separate from employee refresh. Remaining: deployed cookie invalidation,
  password/MFA redirect, and portal-expiry browser proof.
- JUL10-EG-003 **Partially implemented** Build provenance and source secrecy.
  API build contexts now ignore local secret/cache files and deploy-prod
  rejects mismatched refs and dirty API/web source before gcloud. Remaining:
  a controlled production deploy proving the exact full SHA/image digest.
- JUL10-EG-004 **Partially implemented** Cloud Run manifest secret gate.
  The ineffective grep check is replaced by a YAML-aware scanner with local
  tests. Remaining: GitHub Security workflow proof and conversion of the
  document-worker deployment path away from plaintext database substitution.
- JUL10-EG-005 **Partially implemented** Deployment health certification.
  Local fake-command tests prove network/degraded health fails closed.
  Remaining: add a true readiness endpoint covering database and critical
  dependencies, then prove Cloud Run probes and post-deploy readiness.
- JUL10-EG-006 **Partially implemented** Legal calendar-date consistency.
  Audited portal, dashboard, portfolio, hearing, matter, notice, Today,
  document, predictive-intelligence, and litigation-review paths now use local
  calendar semantics and pass UTC-negative tests. Remaining: deployed
  multi-timezone browser proof and a schema-driven guard for future date fields.
- JUL10-EG-007 **Partially implemented** Test-gate reliability. Twenty stale
  page-test waivers were removed and future stale waivers fail. Remaining:
  complete deterministic backend shard evidence, page.tsx numeric coverage,
  route-wide axe, and provider-gated release proof.
- JUL10-EG-008 **Missing** Atomic worker claiming/leases. Document and court
  sync workers can select queued work before claiming it, while schedules may
  overlap the allowed execution window. Add PostgreSQL concurrency tests and
  lease ownership/heartbeat semantics.
- JUL10-EG-009 **Partially implemented** Production test artifact secrecy.
  Live-tenant Playwright configs now disable traces, screenshots, and videos,
  with a regression guard. Remaining: audit uploaded text reports and local
  release/provider artifacts, and use short-lived least-privilege QA sessions.
- JUL10-EG-010 **Partially implemented** Reproducible containers. API and web
  image builds still do not install exclusively from committed lockfiles, and
  some runtime commands can resolve dependencies. Move builds to frozen
  lockfiles and prove network-disabled startup.
- JUL10-EG-011 **Partially implemented** Pine Labs callback routing. Local code
  now returns customers to the existing matter-billing page and derives the
  webhook from the named API route rather than the frontend origin. Remaining:
  Pine UAT and deployed signed-webhook/return-navigation proof.

## Strict Repo Quality Audit (2026-04-24)  - P0 status

All five P0 findings from `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`
closed in commit `161c384`:

- `P0-001` `Implemented` Admin audit export uses cookie auth.
  Anchor: `apps/web/app/app/admin/page.tsx:50-103`,
  `apps/web/app/app/admin/page.test.tsx`. 4 vitest cases including a
  static QG-AUTH-004 guard against re-importing `getStoredToken`.
- `P0-002` `Implemented` `scripts/verify-backend.ps1` runs cleanly on
  Windows. Sanity check extracted to `scripts/_backend_sanity_check.py`
  shared between `.ps1` and `.sh`. Each stage logs `STAGE=` line.
- `P0-003` `Implemented` Calendar ICS declares `text/calendar` in
  OpenAPI; new QG-CAL-002 schema-vs-runtime test added.
  Anchor: `apps/api/src/caseops_api/api/routes/calendar.py:18-31`,
  `apps/api/tests/test_calendar.py::test_ics_openapi_media_type_matches_runtime_header`.
- `P0-004` `Implemented` SendGrid webhook fail-closed outside local.
  `WebhookConfigError` + 503 in non-local env when key missing OR
  `cryptography` unavailable. `cryptography>=42.0.0` is now an
  explicit dep. 9 new tests in
  `apps/api/tests/test_sendgrid_webhook_security.py`.
- `P0-005` `Implemented` Billing E2E split. Invoice-only path runs
  on every E2E pass; Pine Labs payment-link path is provider-gated
  for UAT/release sign-off only.

P1 status after commit `8466911`:

- `P1-001` `Implemented` Per-area coverage gate is wired into CI through
  `scripts/coverage_gate.py`.
- `P1-002` `Partially implemented` API route coverage matrix is enforced for
  new routes, with 16 dated baseline waivers in
  `apps/api/tests/test_route_coverage_matrix.py`.
- `P1-003` `Partially implemented` Frontend page coverage matrix is enforced
  for new pages, with 20 dated baseline waivers in
  `apps/web/app/__page-coverage-matrix.test.ts`.
- `P1-004` `Implemented` Mobile and axe sweeps cover the smoke surfaces.
- `P1-005` `Implemented` Security CI gates cover dependency advisories,
  gitleaks, license allow-list, and Cloud Run secret-reference checks.
- `P1-006` `Implemented` Postgres-backed DB validation tests are live through
  `AQ-005`: CI has a `pgvector/pgvector:pg17` service container and runs the
  Postgres validation marker suite. The broader all-DB-sensitive-test expansion
  remains a separate `AQ-005` follow-on gap.
- `P1-007` `Implemented` AI route governance gate enforces rate limits for
  `/api/ai/*` and `/api/recommendations/*` mutations.
- `P1-008` `Implemented` Upload size cap and abuse tests landed.
- `P1-009` `Implemented` Backup/restore drill executed end-to-end against a
  throwaway clone in `asia-south1` on 2026-04-24. RTO 7 min for the 200 GB
  corpus; row counts, alembic version, pgvector + HNSW indexes all parity with
  prod. Evidence: `docs/RESTORE_DRILL_2026-04-24.md`. Follow-on gaps tracked:
  cross-region backup export and application-level cutover drill.
- `P1-010` `Implemented` OpenAPI client drift gate is wired into CI.

The original `QG-*` entries below are retained as audit history; this section
is the current closure status.

## Phase C-2 (2026-04-24, MOD-TS-015)  - client portal matter surface

`Implemented` in commit `b0965e9`:

- Six new endpoints under `/api/portal/*` gated by a live
  `MatterPortalGrant` (role='client') scope check + cookie-based
  `get_current_portal_user` dependency.
- Web pages `/portal` (matter list) + `/portal/matters/[id]`
  (Overview / Comms / Hearings / KYC tabs).
- 14 backend tests in `apps/api/tests/test_portal_matters.py` cover
  tenant isolation, no-grant 404, cross-tenant 404, can_reply gate
  (403), audit row written on reply + KYC submit, hearings list,
  outside-counsel role denied, unauthenticated 401.
- 5 web vitest cases on the matter detail + 4 updated on the
  landing page.
- Role-guards sweep + route coverage matrix updated to whitelist
  the new portal-cookie-auth pattern.
- AutoMail magic-link send (Phase C-1) already routes invitations
  to real email; portal users sign in, see their matters, click
  in, reply, submit KYC end-to-end.

Phase C-3 (outside-counsel portal  - work-product upload, invoice
submission, time entries) intentionally next; not landed today.

## Automated QA And Coverage Audit (2026-04-25)

Current verdict: `NO-GO` for eliminating manual testers today.

Evidence: `docs/AUTOMATED_QA_COVERAGE_AUDIT_2026-04-25.md`.

- `AQ-001` `Partially implemented` Backend coverage runs reliably, uploads an
  artifact, and enforces regression floors (revisited 2026-08-16). Direct
  per-file floors remain selective even though bucket and total floors cover the
  broader surface.
  Two corrections vs the original audit:
  1. The "41.54% line / 9.99% branch" figure was a stale per-area
     `coverage.json` artifact, not the full coverage run. Actual
     full-suite **TOTAL coverage is 81%** (line) per a fresh local
     run on 2026-04-25  - `779 passed, 11 skipped, 1643.85s` on
     Windows; CI Linux baseline is `665.26s` (11m 5s) per the green
     run on 6af7560.
  2. The "904 s timeout" was an audit-script wrapper budget, not a
     real hang. Nothing in the suite is wedged. Codex's wrapper
     just needs a more generous timeout (1500 s for Linux CI parity,
     1800-2400 s for Windows local).
  Slowest 20 cases are all SETUP time (5-11 s each), driven by
  conftest fixture cost re-running per test. Per-session or
  per-class fixture scope would shave ~120-200 s  - flagged for
  follow-on but not stop-ship.
  Current gate scope is exact: `scripts/coverage_gate.py` enforces 9 direct
  per-file floors; line floors across every file grouped into the 5
  `api`/`core`/`db`/`schemas`/`services` buckets; branch floors for
  `api`/`core`/`db`/`services` (not `schemas`); and overall line/branch floors.
  A file outside the 9-file list is indirectly covered by its bucket and the
  totals but has no individual floor, so aggregate headroom can absorb some
  file-level regression. Close the remaining sub-item by adding direct floors
  for other high-risk modules when aggregate gates are too coarse.

- `AQ-002` `Implemented` Frontend coverage gate is reliable + wired
  end-to-end into CI (closed 2026-04-25).
  Reliability fix: form/dialog tests that type ~30+ characters with
  `userEvent` finished under 2 s on a bare run but crossed the
  5000 ms default under v8 coverage on Linux. `apps/web/vitest.config.ts`
  `testTimeout: 15_000` leaves headroom without hiding real flakes.
  Reporters: added `json-summary` so CI can upload a stable shape
  alongside `text`, `html`, `lcov`.
  Thresholds: `lines: 31`, `statements: 30`, `branches: 22`  -
  rounded down from today's baseline (31.83 / 30.31 / 22.89 / 25.28).
  Updated only when real tests lift coverage; never ratcheted down
  to make CI green.
  CI: `.github/workflows/ci.yml` `web` job now runs
  `npm run test:coverage` instead of `npm run test:web` and uploads
  `apps/web/coverage/{coverage-summary.json,lcov.info}` as a
  `web-coverage` artifact (retention 14 days).
  Verified: full `npm run test:coverage --workspace @caseops/web`
  passes 142/142, summary file produced, thresholds clear.

- `AQ-003` `Partially implemented` Page-level UI coverage is not exhaustive.
  Evidence: 46 frontend pages, 16 sibling `page.test.tsx` files, 30 pages
  without direct page tests. `apps/web/app/__page-coverage-matrix.test.ts`
  blocks new unclassified pages but leaves baseline waivers.
  Close when: app pages have sibling page tests and marketing pages have SEO,
  CTA, mobile, keyboard, and no-404 automation.

- `AQ-004` `Partially implemented` API route matrix is too shallow.
  Evidence: route/OpenAPI gates pass, but 16 `ALLOWED_UNTESTED` backend route
  waivers remain and the current matrix proves route references, not every
  required happy/negative/auth/authz/tenant/audit/rate-limit category.
  Close when: operation-level coverage ledger is enforced and all baseline
  waivers are burned down or expiring with owner approval.

- `AQ-005` `Implemented` Postgres-backed validation suite live + wired
  into CI (closed 2026-04-25).
  CI: new job `postgres-validation` in `.github/workflows/ci.yml`
  spins up a `pgvector/pgvector:pg17` service container (same backend
  version as prod Cloud SQL), enables the `vector` extension, runs
  `pytest -q -m postgres tests/test_postgres_validation.py` against
  it. Total job time ~3-5 min.
  Marker: `pytest.mark.postgres` registered in `pyproject.toml`;
  `tests/conftest.py::pytest_collection_modifyitems` auto-skips
  postgres tests when `CASEOPS_TEST_POSTGRES_URL` is not set, so
  developer laptops + the existing api job are unaffected.
  Test surface (12 cases, anchor coverage for the gaps SQLite cannot
  prove):
  - alembic upgrade head runs cleanly on PG (catches batch-mode
    migrations that secretly assume SQLite)
  - every declared foreign-key inventory column has a leading index
  - conflict-check trigram indexes exist with the expected PostgreSQL shape
  - authority exact-name prefilter matches party tokens on PostgreSQL
  - pgvector extension + HNSW index + cosine `<=>` operator end-to-end
    (the only place the corpus-retrieval shape is proven on prod
    semantics)
  - portal_user FK `ON DELETE SET NULL` actually nulls the FK on
    parent delete (SQLite previously ignored ON DELETE because its connection
    setup did not enable foreign keys; every current SQLite connection now
    enables `PRAGMA foreign_keys=ON`)
  - JSONB column roundtrip preserves nested dict (vs SQLite's
    text-encoded JSON path)
  - UniqueConstraint on `matter_invoice_line_items.time_entry_id`
    raises IntegrityError on duplicate insert
  - unique tenant keys block cross-tenant identity collisions
  - C-3c `oc_cross_visibility_enabled` `server_default=false()`
    actually inserts False on bare INSERT (proves migration server
    default applied)
  - standalone Notice composite tenant constraints and Matter delete policy
    reject cross-tenant links and destructive parent deletion
  - Notice direction/reply-state database checks reject invalid combinations
  Verified locally on 2026-07-16 against a fresh isolated PostgreSQL 17 +
  pgvector database: 13/13 passed after `alembic upgrade head`, including the
  prior-revision lifecycle migration repair and durable provider-calendar
  deletion test. The normal
  SQLite suite continues to auto-skip this marked module without a PG URL.
  Per-area test-matrix expansion + Postgres CI for ALL DB-sensitive
  tests (not just the validation file) remains a separate gap  -
  this commit lays the foundation.

- `AQ-006` `Partially implemented` Provider-skip-on-release loophole
  closed (2026-04-25); the broader "every PRD journey has full
  matrix coverage" sub-item remains.
  Provider-skip fix: new helper
  `tests/e2e/support/provider-gating.ts` exports
  `requireProviderCredentialOrSkip(test, { provider, envVar,
  alsoRequire? })`. Default mode (laptop, normal PR CI) keeps the
  existing `test.skip` behavior. Under `CASEOPS_RELEASE_MODE=true`
  the same helper throws at describe-load with a loud
  `[CASEOPS_RELEASE_MODE=true] <Provider> credential(s) missing: ...`
  message  - the spec fails instead of silently skipping. Applied to
  Pine Labs in `billing-payment.spec.ts`. Verified both branches
  locally on 2026-04-25 (default = 1 passed + 1 skipped; release-no-key
  = throws with the documented message).
  Browser diversity + every-PRD-journey full matrix coverage are
  separate sub-items that keep this `Partially implemented`. Wire
  `CASEOPS_RELEASE_MODE=true` in a release-only CI job (or release
  runbook step) to actually exercise the gate; the gate exists but
  no automation sets the flag yet.

## Stop-Ship Control Gaps

- `EG-001` `Implemented` Browser bearer-token hardening (closed
  2026-04-24, deployed in revision `caseops-api-00042-zlj` on commit
  `fbb6a29`).
  Evidence: `apps/web/lib/session.ts:35-37`  - `getStoredToken()`
  always returns `null`; HttpOnly `caseops_session` + JS-readable
  `caseops_csrf` cookies issued by `apps/api/src/caseops_api/core/cookies.py`
  with `Domain=.caseops.ai` (BUG-011 fix) and matching CSRF
  middleware in `apps/api/src/caseops_api/core/csrf.py`. Phase C-2
  (commit `65e8873`) extended the same double-submit pattern to
  the portal surface (`PORTAL_CSRF_COOKIE` + `X-Portal-CSRF-Token`).
  Live prod smoke 2026-04-24: `POST /api/portal/matters/.../communications`
  without `X-Portal-CSRF-Token` returned 403 "Missing CSRF token.";
  `POST /api/portal/auth/request-link` returned 200 (auth path
  exempt as designed).

- `EG-002` `Implemented` Deploy-time migration safety
  (closed 2026-04-24).
  Evidence: live `caseops-api` service has `CASEOPS_AUTO_MIGRATE=false`
  (verified via `gcloud run services describe`); manifest
  `infra/cloudrun/api-service.yaml:48-55` declares the policy with the
  EG-002 anchor comment; separate `caseops-migrate-job` Cloud Run Job
  runs `python -m alembic upgrade head` on the same image as the API;
  `scripts/deploy-prod.sh` (added 2026-04-24) is the canonical deploy
  path and enforces order: build -> migrate-job -> api -> web ->
  staleness sweep. Migrate-job re-bumped to `caseops-api:fbb6a29` and
  executed cleanly (`caseops-migrate-job-nxbkc`, no-op since alembic
  already at `20260424_0001`).

  **2026-07-28 release-lineage regression discovered:** the same gate
  correctly stopped candidate `7495bc6` because production's
  `alembic_version` referenced `20260723_0001`, which was absent from the
  candidate API image. The web-only navigation fix was deployed safely; the
  API image was not promoted. Keep this follow-up open until a migration
  inventory/CI check proves every production-referenced revision is present in
  the candidate image before the next API rollout.

- `EG-003` `Implemented` Malware scanning enforcement (closed
  2026-04-25, deployed in revision `caseops-api-00049-m6c`).
  Evidence: `scripts/eg003-apply-clamav.sh` wires
  `clamav/clamav:1.4` as a Cloud Run multi-container sidecar
  (1 CPU / 1.5 GiB), adds `CASEOPS_CLAMAV_HOST=127.0.0.1` +
  `CASEOPS_CLAMAV_PORT=3310` env vars to the API container, removes
  the prior `CASEOPS_CLAMAV_REQUIRED=false` override (env-aware
  default = `true` in cloud env now wins), and adds the
  `run.googleapis.com/container-dependencies={"api":["clamav"]}`
  annotation so the API waits for clamd startup probe to pass.
  `scripts/deploy-prod.sh` now fails the deploy if the sidecar is
  missing post-deploy (regression guard).
  Live prod smoke 2026-04-25: an EICAR test-file upload to
  `POST /api/matters/{matter_id}/attachments` returned HTTP 400 with
  `"Upload 'eicar.txt' matched virus signature 'Eicar-Test-Signature'.
  Refusing to store the file."`  - proves real clamd in the sidecar +
  signature DB + `reject_if_infected` wired end to end.
  Cost: idle stays $0 (`minScale=0`); per-request adds ~$0.00007/sec
  while clamav shares the request lifecycle. First upload after a
  cold start incurs ~30-60s while clamd loads signatures; if that
  becomes a UX complaint, flip `minScale=1` (~$30-50/mo).

- `EG-004` `Implemented` Authenticated abuse controls for expensive AI routes
  (closed 2026-04-24 via P1-007).
  Evidence: `ai_route_rate_limit` + `tenant_aware_key` from
  `apps/api/src/caseops_api/core/rate_limit.py` are wired on every
  AI-mutating endpoint:
  `apps/api/src/caseops_api/api/routes/matters.py:329,860,1015`,
  `apps/api/src/caseops_api/api/routes/drafting.py:180`,
  `apps/api/src/caseops_api/api/routes/ai.py:69,90,111,132,156,179,202,221`,
  `apps/api/src/caseops_api/api/routes/recommendations.py:13`.
  Closure was tracked separately as P1-007 in this same ledger.
  Tenant-budget caps (cost-aware, not just request-rate) remain
  open as a follow-on under EG-005 / EG-006 model-run governance.

- `EG-005` `Implemented` Matter summary governance (closed
  2026-04-25 via stale-doc re-look  - code shipped earlier; ledger had
  not been re-graded).
  Evidence:
  - **Cache:** `Matter.executive_summary_json` column added in
    migration `20260423_0001`; `services/matter_summary.py:306-309`
    short-circuits and returns the cached payload unless the caller
    passes `force_refresh=True`. The POST `.../regenerate` route is the
    only caller that invalidates; GET / DOCX / PDF use the cache.
  - **ModelRun audit:** `_on_model_run` callback at
    `services/matter_summary.py:329-344` writes a `ModelRun` row per
    successful LLM call (provider, model, prompt+completion tokens,
    latency, tenant, matter, actor membership, status='ok'). Wired
    via `generate_structured(..., on_model_run=_on_model_run)`.
  - **Provider-failure handling:** broadened to catch
    `LLMQuotaExhaustedError` (Anthropic 402 -> straight to OpenAI),
    `LLMResponseFormatError` (malformed JSON -> Haiku retry -> OpenAI),
    and the parent `LLMProviderError` (503/overload/timeouts -> OpenAI
    cutover)  - `services/matter_summary.py:360-398`.
  - **Test coverage:** `test_matter_summary_export.py
    ::test_summary_caches_after_first_call_and_skips_llm_on_second`
    proves the second GET hits the cache and never invokes the LLM
    stub; companion tests verify POST regenerate forces a fresh call
    and writes a ModelRun audit row each time.

- `EG-006` `Implemented` Draft preview governance (closed
  2026-04-25 via stale-doc re-look  - code shipped earlier; ledger had
  not been re-graded).
  Evidence:
  - **Tenant AI policy gate:** `services/drafting_preview.py:151-166`
    calls `is_model_allowed(policy, purpose='drafting_preview',
    model=llm.model)` and raises HTTP 403 with an actionable message
    when the tenant's `tenant_ai_policy` blocks the model.
  - **ModelRun audit:** `_write_model_run` is invoked on BOTH the
    success path (`services/drafting_preview.py:187-198`, status='ok')
    AND the failure path (`drafting_preview.py:173-184`, status='error',
    error='preview_provider_failed')  - preview failures are now
    visible in the audit dashboard.
  - **Provider-failure handling:** `_invoke_with_cutover`
    (`drafting_preview.py:210-251`) is the same Haiku -> OpenAI
    cutover ladder used by the structured AI services
    (recommendations / matter_summary). `LLMQuotaExhaustedError` cuts
    straight to OpenAI; `LLMProviderError` tries Haiku first.
  - **Redacted 502:** `_preview_via_openai` (`drafting_preview.py:254-274`)
    logs the raw exception at WARN with full repr but returns an
    actionable, redacted user-visible detail ("Drafting preview is
    temporarily unavailable. Please retry in a minute, or contact
    support if this persists.")  - no provider name, no exception
    class, no internal trace markers leak.
  - **Test coverage:** `test_drafting_preview.py
    ::test_preview_redacts_provider_error_in_502` asserts the user-
    visible detail does NOT contain `LLMProviderError`, provider internals,
    or a planted `SECRET_INTERNAL_TRACE_xyz` substring;
    `test_preview_persists_error_model_run_when_provider_fails`
    asserts the failure-path ModelRun row is persisted.

- `EG-007` `Implemented` Secret-management and runtime control wiring
  (closed 2026-04-25 with the rotation drill in revision
  `caseops-api-00052-5w2`).
  Every sensitive env on the API service flows through Secret Manager:
  `caseops-auth-secret`,
  `caseops-voyage-api-key`, `caseops-sendgrid-api-key`,
  `caseops-database-url`, `caseops-openai-api-key`,
  `caseops-pine-labs-api-key`, `caseops-pine-labs-api-secret`. Web
  service: `caseops-smtp-password` is the only sensitive env and is
  also Secret-Managed.
  Rotation procedure documented end-to-end in
  `docs/runbooks/secret-rotation.md` (10 secrets in scope, provider-
  specific verification recipe per secret, emergency-rotation path,
  90-day cadence, ownership). Drill executed 2026-04-25 against
  `caseops-pine-labs-api-key`: added v2, redeployed, `/api/health`
  green throughout. 4 orphaned `caseops-pinelabs-*` (no-dash)
  secrets deleted in the same task  - `gcloud secrets list` is now
  the single source of truth.
  Cross-region replication remains `automatic` (Google-managed); a
  multi-region replication policy is a follow-on when the
  multi-region prod story lands.
  Pine Labs key rotation with the provider (the 04-19 raw value was
  visible in `gcloud run describe` output before today's swap): not
  yet executed; tracked as a low-priority follow-on since UAT
  credentials. Production credentials when issued will rotate
  through this runbook.

## Structural Code Risks

- `EG-008` `Partially implemented` Backend and web hotspot decomposition.
  Evidence: `apps/api/src/caseops_api/db/models.py` (3205 lines),
  `apps/api/src/caseops_api/services/matters.py` (1622 lines),
  `apps/api/src/caseops_api/api/routes/matters.py` (1263 lines),
  `apps/api/src/caseops_api/services/court_sync_sources.py` (1276 lines),
  `apps/web/lib/api/endpoints.ts` (1728 lines).
  Gap: critical change surfaces are still concentrated in a few oversized files,
  raising regression risk and review difficulty.
  Close when: the biggest hotspots are split into coherent modules with narrower
  responsibilities and the manual API client is retired route by route.

- `EG-009` `Partially implemented` Exception-handling discipline.
  Evidence: raw or broad exception paths exist in
  `apps/api/src/caseops_api/services/drafting_preview.py:97-118`,
  `apps/api/src/caseops_api/services/contracts.py:835-868`,
  `apps/api/src/caseops_api/services/matters.py:1309-1339`.
  Gap: critical surfaces still swallow or flatten too many failures, making
  support and incident triage weaker than an enterprise system should allow.
  Close when: critical-path exceptions are narrowed, user-visible errors remain
  actionable without leaking internals, and logging captures the real failure.

## Extracted Remaining Gaps From docs/WORK_TO_BE_DONE.md

- `WTD-4.2` `Partially implemented` Proper RAG.
  Remaining scope: full corpus ingestion, reranker, live Postgres integration
  tests, matter-attachment embeddings, and scoring calibration.
  Evidence: `docs/WORK_TO_BE_DONE.md:327-342`.

- `WTD-4.5` `Partially implemented` Hearing-pack automation and export.
  Remaining scope: scheduled auto-trigger, authority matching, DOCX/PDF export.
  Evidence: `docs/WORK_TO_BE_DONE.md:389-392`.

- `WTD-5.1` `Partially implemented` Durable workflow foundation.
  `WTD-5.1a` adds disabled-by-default notification workflow config health,
  a safe worker check entrypoint, and a deterministic no-op notification-intent
  probe with redacted audit metadata. It adds no notification delivery,
  reminder scheduling, external provider calls, staging/prod deploy changes, or
  autonomous scans.
  `WTD-5.1b` adds the real Temporal SDK dependency, redacted Temporal client
  and worker config construction, a guarded worker runtime entrypoint, and a
  deterministic no-op notification-intent workflow/activity with explicit retry
  policy, timeouts, task queue, and version metadata. It still adds no
  notification delivery, reminder scheduling, external provider calls,
  staging/prod deploy changes, corpus jobs, or autonomous scans.
  Evidence: `apps/api/src/caseops_api/services/durable_workflows.py`,
  `apps/api/src/caseops_api/workers/notification_workflows.py`,
  `apps/api/src/caseops_api/workflows/notification_intents.py`,
  `apps/api/tests/test_durable_workflows.py`.
  `WTD-5.1c` operator runtime proof is complete against the operator-owned
  Mumbai Temporal backend. The proof preserved redacted config/status output
  and did not run notification delivery, reminder scheduling, external provider
  calls, or feature workflows.
  Remaining: porting/retiring non-notification polling workers where applicable.

- `WTD-5.2` `Missing` Agent identity, scoped grants, approval gates, and
  budgets.
  Evidence: `docs/WORK_TO_BE_DONE.md:417-426`.

- `WTD-5.3` `Partially implemented` Notification service with durable delivery
  and retry. The foundation persists tenant-scoped delivery intents, processes
  in-app notifications idempotently, records bounded retry/dead-letter state,
  and blocks email/SMS/WhatsApp without provider calls. Remaining scope:
  provider-specific policy, credential, and runbook approval before external
  delivery or ADP-20 automation.
  Evidence: `apps/api/src/caseops_api/services/notification_delivery.py`,
  `apps/api/src/caseops_api/services/notification_rules.py`,
  `apps/api/tests/test_durable_workflows.py`.

- `WTD-6.5` `Partially implemented` OpenAPI maturity and generated web client
  rollout.
  Evidence: `docs/WORK_TO_BE_DONE.md:512-517`,
  `apps/web/package.json:13`,
  `apps/web/lib/api/openapi-types.ts:1`.

- `WTD-7.2` `Partially implemented` Generic task and deadline model beyond
  contract-only obligations (updated 2026-05-16). Tasks/Deadlines Cockpit
  foundation is implemented for matter-scoped create/list/update/complete/
  reopen using existing task/deadline records; generated proceeding
  intelligence lineage is preserved.
  Evidence: `apps/api/src/caseops_api/db/models.py` (`MatterTask` and
  `MatterDeadline`),
  `apps/api/src/caseops_api/api/routes/matters.py` (matter task/deadline
  cockpit endpoints), `apps/web/app/app/matters/[id]/tasks/page.tsx`
  (matter cockpit task/deadline page), and
  `apps/api/src/caseops_api/services/calendar_service.py` (unified feed
  across hearings, tasks, deadlines).
  Remaining: admin task templates per practice-area remain missing.

- `WTD-7.3` `Partially implemented` Model-evaluation admin gate and cost rollup.
  Evidence: `docs/WORK_TO_BE_DONE.md:541-545`,
  `apps/api/src/caseops_api/db/models.py:2704`,
  `apps/api/src/caseops_api/services/evaluation.py:12-137`.

- `WTD-7.4` `Implemented` Statute, Section, Issue, and Relief model
  (closed 2026-04-25 via MOD-TS-017 Slices S1+S2+S3+S4).
  Evidence: `apps/api/alembic/versions/20260425_0004_statute_model.py`
  (4 tables: statutes / statute_sections / matter_statute_references
  / authority_statute_references), `apps/api/src/caseops_api/scripts/
  seed_data/statutes.json` (7 central acts, 91 sections, indiacode.
  nic.in source URLs), `services/statute_resolver.py` (tolerant
  parser handling BNSS-vs-BNS substring trap, 'Section ', 'S.', 'Article'
  variants), 23 backend tests + 5 vitest cases. Drafting prompt
  receives bare section text for verbatim quoting on appeal-
  memorandum drafts. Live in prod; 7 acts / 91 sections seeded
  via `caseops-seed-statutes` Cloud Run Job. Remaining (out of
  v1 scope): bare-text enrichment for the long-tail sections,
  amendment history, cross-act mapping (CrPC -> BNSS), state acts.

- `WTD-8.3` `Partially implemented` Backup + restore drill closed
  2026-04-24 (see P1-009 above and `docs/RESTORE_DRILL_2026-04-24.md`).
  Remaining sub-items: cross-region backup export, per-tenant export
  drill (right-to-erasure / portability), application-level cutover
  drill (Cloud Run flip onto a restored instance).
  Evidence: `docs/WORK_TO_BE_DONE.md:576-582`.

- `WTD-8.4` `Partially implemented` Full CI/CD.
  Remaining scope: image build and push, staged deploy, branch protection.
  Evidence: `docs/WORK_TO_BE_DONE.md:584-588`.

- `WTD-8.5` `Partially implemented` Secret-management completion.
  Evidence: `docs/WORK_TO_BE_DONE.md:590-595`,
  `infra/cloudrun/api-service.yaml:14-66`.

- `WTD-9.1` `Partially implemented` Broader parsing stack.
  Evidence: `docs/WORK_TO_BE_DONE.md:601-609`.

- `WTD-9.2` `Partially implemented` Structural extraction replacing heuristics.
  Evidence: `docs/WORK_TO_BE_DONE.md:611-615`.

- `WTD-9.3` `Partially implemented` Enterprise virus-scanning step.
  Evidence: `docs/WORK_TO_BE_DONE.md:617-620`,
  `apps/api/src/caseops_api/services/virus_scan.py:80-82`,
  `apps/api/src/caseops_api/services/virus_scan.py:153-169`.

- `WTD-10.1` `Missing` Company and tenant management console.
  Evidence: `docs/WORK_TO_BE_DONE.md:626-629`.

- `WTD-10.2` `Missing` OIDC and SAML SSO.
  Evidence: `docs/WORK_TO_BE_DONE.md:631-634`.

- `WTD-10.3` `Partially implemented` AI policy controls.
  Evidence: `docs/WORK_TO_BE_DONE.md:636-642`,
  `apps/api/src/caseops_api/services/tenant_ai_policy.py:9-11`,
  `apps/api/src/caseops_api/services/llm.py:636-663`.

- `WTD-10.5` `Implemented foundation` Plan entitlements and enforcement.
  Evidence: pricing/billing/platform-admin rollout, tenant billing APIs,
  plan catalog, entitlement gating, usage/spend reports, and platform-admin
  profit/provider-event surfaces. Manual production signoff remains pending.

- `WTD-11.2` `Missing` Authorization matrix tests.
  Evidence: `docs/WORK_TO_BE_DONE.md:664-666`.

- `WTD-11.4` `Implemented` AI safety benchmark automation.
  Evidence: `apps/api/src/caseops_api/scripts/eval_ai_safety.py` supplies the
  deterministic release gate; `apps/api/tests/fixtures/ai_safety_eval/` covers
  all eight required AI surfaces plus explicit detector failures;
  `apps/api/tests/test_eval_ai_safety.py` proves all eleven required safety
  rules, incomplete-suite rejection, redacted output, CLI behavior, and
  canonical `EvaluationRun`/`EvaluationCase` persistence; and
  `.github/workflows/ci.yml` runs the release gate. Runbook:
  `docs/runbooks/ai-safety-eval-harness.md`. Live-provider benchmarking and
  independent legal/UAT approval remain separate release controls.

- `WTD-11.5` `Partially implemented` Payment verification depth.
  Evidence: `docs/WORK_TO_BE_DONE.md:678-680`,
  `tests/e2e/billing-payment.spec.ts:39-46`.

- `WTD-11.6` `Partially implemented` PRD-complete E2E coverage.
  Evidence: `docs/WORK_TO_BE_DONE.md:682-685`.

- `WTD-11.7` `Missing` Route-wide accessibility automation.
  Evidence: `docs/WORK_TO_BE_DONE.md:687-689`.

- `WTD-12.1` `Missing` Broader jurisdiction adapters and per-tenant connector
  credentials.
  Evidence: `docs/WORK_TO_BE_DONE.md:695-701`.

- `WTD-12.2` `Missing` Connector health UI.
  Evidence: `docs/WORK_TO_BE_DONE.md:703-705`.

- `WTD-12.3a` `Implemented` Calendar sync.
  Evidence: bounded manual Outlook bulk sync is tracked as `EH-PROV-02` below;
  durable always-on automation remains gated on `WTD-5.1` Temporal.

- `WTD-12.3b` `Partially implemented` Inbound email ingest foundation for
  matter communications.
  Evidence: manual explicit matter selection endpoint
  `POST /api/matters/{matter_id}/communications/import-email`, provider/message
  idempotency on `(company_id, matter_id, external_message_id)`, tenant +
  restricted matter + ethical wall + team scoping via the existing matter access
  gate, full body/attachments routed through matter attachment storage, and
  redacted `inbound_email.imported` audit metadata.
  Remaining: provider/webhook or admin-triggered mailbox connector, thread
  grouping, intake routing, and runtime proof. Autonomous mailbox sweep remains
  out of scope unless explicitly approved.

## Stale-Doc Items To Correct In docs/WORK_TO_BE_DONE.md

- `DRIFT-001` `Stale-doc` Teams are no longer absent.
  Evidence: `docs/WORK_TO_BE_DONE.md:473-476`,
  `apps/api/src/caseops_api/db/models.py:3147-3204`,
  `apps/api/src/caseops_api/api/routes/teams.py:1-154`,
  `apps/web/app/app/admin/teams/page.tsx:67-188`,
  `apps/api/src/caseops_api/services/matter_access.py:190-192`.

- `DRIFT-002` `Stale-doc` `EvaluationRun` is no longer a pending table.
  Evidence: `docs/WORK_TO_BE_DONE.md:545`,
  `apps/api/src/caseops_api/db/models.py:2704`,
  `apps/api/src/caseops_api/services/evaluation.py:12-137`.

- `DRIFT-003` `Stale-doc` OpenTelemetry and structured JSON logging are no
  longer absent in code.
  Evidence: `docs/WORK_TO_BE_DONE.md:562-574`,
  `apps/api/src/caseops_api/core/observability.py:1-277`.

- `DRIFT-004` `Stale-doc` Generated OpenAPI TypeScript output already exists,
  even though rollout is still incomplete.
  Evidence: `docs/WORK_TO_BE_DONE.md:512-517`,
  `apps/web/package.json:13`,
  `apps/web/lib/api/openapi-types.ts:1`.

## 2026-04-24 Strict Repo Quality Audit Additions

QG-P0-001 through QG-P0-005 historical entries removed 2026-04-26  -
all five duplicated the `P0-001` ... `P0-005` entries earlier in this
file (closed in commit `161c384`). The active per-area coverage
ledger is `P1-002` / `P1-003` / `AQ-003` / `AQ-004` above.

- `QG-P1-002` `Implemented` Security scanning and dependency/license gates are
  wired into CI.
  Evidence: `.github/workflows/security.yml`,
  `docs/CODEX_REVIEW_PACK_2026-04-24.md`.

## 2026-04-24 Product-Scope Queue Additions

- `MOD-TS-001-A` `Implemented` Appeal Strength Analyzer (closed
  2026-04-25). Per-ground argument-completeness analysis on an
  appeal_memorandum draft. Pure-read; no LLM call; deterministic.
  Frame is **argument completeness, NOT outcome prediction**  - the
  no-favorability rule from the bench-aware drafting skill is enforced
  structurally:
  - `_FORBIDDEN_PATTERN` (word-boundary regex) gates EVERY string the
    analyzer emits in `suggestions`, `weak_evidence_paths`,
    `recommended_edits`. Forbidden tokens: win, lose, loss, winnable,
    winnability, favourable, favorable, favour, favor, tendency,
    tends to, usually grants, usually rules, probability, chance of
    success, likely to succeed, predict, prediction, outcome.
  - In-service `_check_phrase` raises AssertionError on any leak;
    the structural unit test in `tests/test_appeal_strength.py
    ::test_no_favorability_language_anywhere_in_output` scans the
    full surface independently.
  Service: `services/appeal_strength.py`
    - parses numbered grounds from the draft body via regex
    - per-ground citation coverage: supported / partial / uncited
    - resolves inline citations against bench_strategy_context
      authorities first, then a wider DB lookup
    - tags authority strength: binding (SC) / peer (HC) /
      persuasive (lower / tribunal / arbitration / advisory) / unknown
    - rolls up to overall_strength: strong / moderate / weak
    - emits actionable suggestions per ground ("add SC authority",
      "drop the unsupported sub-proposition")
  Route: `GET /api/matters/{matter_id}/appeal-strength?draft_id=...`
  with cross-tenant 404; auth gated by the matters router.
  Web: `AppealStrengthPanel` rendered alongside `BenchContextCard` on
  the appeal-memorandum drafting flow. Per-ground rows with green/
  amber/red tone, weak-evidence-paths section, recommended-edits list.
  Tests: 8 backend unit + route + structural-no-favorability + 2
  vitest cases (no-draft note + per-ground rendering with the same
  no-favorability sweep at the rendered surface).
  PRD: `MOD-TS-001-A` row added with journey/module/US/FT mapping;
  US-018A added; FT-024B + FT-031B added.

- `BAAD-001` `Implemented` Bench-aware appeal drafting wired end to end
  (closed 2026-04-25 across 4 commits + 1 doc closure).
  Slices shipped:
  1. **Template** (`2b72b0c`)  - `DraftTemplateType.APPEAL_MEMORANDUM`,
     `AppealMemorandumFacts`, `_APPEAL_FIELDS`, `_APPEAL_MEMORANDUM`
     prompt + golden fixture.
  2. **Bench strategy context service** (`708587f`)  - pure-read
     `services/bench_strategy_context.py` with structured judges_json
     match + bench_name fallback, citable-authorities preference,
     practice-area pattern derivation suppressed below 3-supporting-
     authority floor, drafting cautions, unsupported gaps, 4-level
     `context_quality` scoring.
  3. **Drafting integration + per-template prompt wiring** (`4a2191d`)
      - `_build_messages` now appends per-template prompt addendum
     for ALL nine templates (turning on the Sprint R2 prompts that
     were registered but never imported); `generate_draft_version`
     calls `build_bench_strategy_context` for `appeal_memorandum`
     and injects a `BENCH HISTORY CONTEXT` block; explicit positive
     evidence-phrasing anchor + enumerated negative instruction
     against favorability phrases; falls back gracefully to plain
     appeal draft if context build raises.
  4. **API endpoint + UI** (this commit)  - new
     `GET /api/matters/{matter_id}/bench-strategy-context` route
     (auth + tenancy gated, 404 on cross-tenant); new
     `BenchContextCard` component in
     `apps/web/components/drafting/BenchContextCard.tsx` rendered
     by `DraftingStepper` only when template is appeal_memorandum;
     pattern detail hidden + amber limitation note shown when
     quality is low/none.
  Bench-aware drafting hard rules verified:
  - No favorability copy in service surface, prompt, or UI (4
    structural tests across both layers).
  - REQUIRED PHRASING anchor present in prompt; enumerated NEVER
    WRITE list of forbidden phrases verified by
    `test_build_messages_has_no_favorability_phrasing`.
  - Weak-evidence path (low/none quality) emits limitation note and
    suppresses pattern claims at both prompt and UI layers.
  - Tenant-isolation: cross-tenant matter returns 404 (route test
    `test_bench_strategy_context_route_404_on_cross_tenant`).
  Test surface: 14 backend tests in
  `apps/api/tests/test_bench_strategy_context.py` (service + route +
  drafting integration); 3 vitest cases in
  `apps/web/components/drafting/BenchContextCard.test.tsx`. Plus
  73-test drafting-suite green after the per-template prompt wiring.

## Codex Discipline

- Codex must read `.codex/skills/enterprise-hardening/SKILL.md` before any
  enterprise-readiness, scale-hardening, or `WORK_TO_BE_DONE.md` audit.
- Codex must update this file in the same task as the audit.
- Codex must not close a hardening item without evidence from code, tests, and
  deploy or runtime state where relevant.
- Codex must call out doc drift explicitly instead of silently trusting or
  rewriting old backlog text.

---

## Provider/runtime drift  - Hari 2026-05-09 sweep findings

The 2026-05-09 multi-PR sweep surfaced two enterprise hardening gaps
that span code, infrastructure manifest, runtime env, and provider-side
config. Both are tracked here so future enterprise audits stop
re-discovering them as new findings.

### EH-PROV-01  - SendGrid Event Webhook end-to-end wiring (PR #22)

- **Status:** Partially implemented (code complete, infrastructure
  manifest landed, **provider-side config + Secret Manager value
  pending operator action**).
- **Code (in `fix/sendgrid-webhook-delivery-visibility`):**
  - `apps/api/src/caseops_api/api/routes/sendgrid_webhook.py`  -
    ECDSA P-256 signed-event verification with explicit fail-closed
    on missing/invalid signature.
  - `apps/api/src/caseops_api/db/models/email_suppression.py` +
    Alembic migration  - tenant-scoped suppression table,
    `(company_id, recipient_email)` unique constraint.
  - `apps/api/src/caseops_api/services/email_suppression.py`  -
    `is_suppressed`, `record_suppression`, idempotent on duplicate
    events. `services/email_send.py` calls `is_suppressed` before
    every business mailer; `services/employee_mailer.py` and
    `services/portal_mailer.py` are intentional bypasses (auth
    flow can never be silently suppressed).
  - Test coverage: 12 backend tests including
    `test_auth_flow_mailers_bypass_suppression` (regression lock).
- **Infrastructure manifest:**
  - `infra/cloud-run/api.yaml` (or equivalent service.yaml)  -
    references `caseops-sendgrid-webhook-public-key` Secret
    Manager value via `valueFrom.secretKeyRef`.
  - Runbook: `docs/runbooks/sendgrid-event-webhook.md`.
- **Pending operator steps (gating Properly Implemented):**
  1. Create the `caseops-sendgrid-webhook-public-key` Secret
     Manager secret with the SendGrid-provided P-256 public key.
  2. In SendGrid dashboard:
     Settings -> Mail Settings -> Event Webhook -> enable Signed
     Event Webhook, set HTTPS POST URL to
     `https://api.caseops.ai/api/webhooks/sendgrid/events`, enable
     `bounce`, `dropped`, `spam_report`, `unsubscribe`,
     `group_unsubscribe` events.
  3. Verify the webhook end-to-end via the runbook's curl probe.
- **Why this is enterprise hardening, not a bug fix:** SendGrid
  send had been working from imperatively-set Cloud Run env vars
  for months while the webhook side had no declarative wiring at
  all. This is the classic "deploy manifest drift" failure mode
  the enterprise-hardening skill flags as `Stale-doc` /
  `Partially implemented`.

### EH-PROV-02  - Outlook bounded bulk sync vs durable automation (PR #23)

- **Status:** Implemented (bounded manual sync); durable automation
  is explicitly deferred to Temporal.
- **Code (in `fix/outlook-sync-all`):**
  - `apps/api/src/caseops_api/api/routes/calendar.py::sync_all_outlook`  -
    bounded endpoint that returns
    `durable_automation: "blocked_pending_provider_approval"` literal so
    callers cannot mistake it for continuous sync.
  - `apps/web/components/matters/MatterCalendarSyncCard.tsx`  - UI
    button with disabled state + connection-required messaging.
- **Why tracked here:** any future "always-on Outlook sync" claim
  is a roadmap item gated on Temporal landing, NOT on this PR.
  The literal `blocked_pending_provider_approval` is the enterprise-readable
  source of truth now that Temporal operator proof and WTD-5.3 foundation are
  complete.

### Closure pre-conditions

`EH-PROV-01` remains open in this ledger until the merged commit is
deployed to `caseops.ai` via `scripts/deploy-prod.sh`, the
`Prod verification (Playwright)` workflow has run against the
deployed SHA, and the operator-side SendGrid dashboard + Secret Manager
steps in `docs/runbooks/sendgrid-event-webhook.md` are complete.

`EH-PROV-02` is closed for bounded manual calendar sync. Durable
always-on calendar automation is not closed by that work and remains
tracked under `WTD-5.1` / `WTD-5.3`.

---

## 2026-07-15 Lifecycle And Regression-Discovery Hardening

### EH-LC-01 - Matter terminal-state concurrency and operational boundary

- **Status:** Locally implemented; production verification pending.
- **Gap found:** matter status and `is_active` were patchable through a broad
  metadata route; the UI replayed full stale snapshots; disposal did not
  consistently govern operational children or background provider writers.
- **Required invariant:** generic PATCH cannot dispose/reopen or edit a disposed
  matter; lifecycle changes use capability + reason + source status + timestamp;
  stale writes return 409; reopen lands in Intake; old conflict clearance is
  retained only as historical/stale evidence and does not block a later Active
  transition; post-disposal tasks/deadlines/hearings/jobs cannot make the matter
  operational again. Legacy terminal rows and already-synced provider calendar
  artifacts are neutralized/tombstoned on migration and again before reopen.
  Every operational portal, integration, AI/provider,
  metadata, bulk, assignment, and linked-record writer uses the shared fresh-
  parent guard; provider paths recheck after I/O or an intermediate commit.
- **Closure evidence required:** backend transition/concurrency/side-effect tests,
  a repository-wide inventory proving every generic Matter PATCH caller sends
  mandatory CAS, forced provider/matching interleavings with no durable output,
  legacy migration/reopen child-neutralization proof, React dirty-payload and
  explicit lifecycle tests, two-session Playwright with final read-back, and the
  same committed production spec passing on the deployed commit.
- **Learning:** a one-session `disposed` reload assertion proves persistence at
  one instant; it does not prove terminality across concurrent writers or jobs.
  A lock acquired before a commit or provider call also proves nothing about
  the final persistence boundary because a commit releases that lock.

### EH-LC-04 - Conflict review/status decoupling (2026-07-22)

- **Status:** `Properly fixed` on exact deployed commit
  `34f19ad2bc0a5b48398144998cf546cc9e7a815a` on 2026-07-22.
- **Policy:** conflict review is optional and auditable. Missing, pending,
  conflicted, cleared, waived, invalid, stale-scope, and pre-reopen results must
  not block creation or an Intake/On-hold to Active transition. A stale result
  must not be presented as current clearance.
- **Adjacent invariants retained:** conflict scanning/resolution, tenant and
  matter access, terminal lifecycle, optimistic concurrency, audit provenance,
  and party-scope/lifecycle versioning remain enforced independently.
- **Local evidence:** canonical backend verification passed Ruff plus 59
  affected conflict/lifecycle/intake/import tests; three focused React files
  passed 19 tests, TypeScript passed, and the 64-route production build passed.
  The combined July 15 and July 22 local Chromium run passed 5/5 in 20.5s with
  the shared exact local tester identity. July 22 passed 2/2: no-check Intake
  activation in 1.3s and controlled Dispose -> Reopen -> Historical-cleared
  -> Active in 2.1s with lifecycle-version/CAS and reload persistence proof.
- **Current-claim audit:** current product records describe scanner scope as
  clients plus matters only; broader contacts remain an explicit follow-on gap.
- **Production evidence:** the earlier authenticated run retained the prior
  build's legacy HTTP 409 as the pre-deploy reproduction. Exact commit
  `34f19ad2bc0a5b48398144998cf546cc9e7a815a` was then deployed to API revision
  `caseops-api-00210-fnv` and web revision `caseops-web-00189-k9f`, with 100%
  traffic and exact registry/runtime digests. The committed July 22 spec passed
  2/2 with the supplied `legal` tester and again on the independent QA tenant
  in GitHub run `29929098217`; the broader RAM and notice suites also passed.
- **Closure evidence:** satisfied. Persistent release proof is in
  `docs/runbooks/release-signoff-2026-07-22-34f19ad.md`.

### EH-DB-02 - Database-test fixture integrity

- **Status:** Implemented for the July 15 batch; retained as a permanent review
  control.
- **Gap found:** permissive SQLite execution allowed positive-path tests to use
  nonexistent notification-rule and custom-role parents, creating impossible
  production states and hiding missing constraint enforcement.
- **Control:** all SQLite connections enable foreign keys; positive fixtures
  seed valid parents or omit truly optional relationships; negative tests assert
  dangling/cross-tenant rejection; PostgreSQL remains mandatory for dialect,
  migration, lock, and constraint proof.

### EH-QA-05 - Automatic discovery of dated bug regressions

- **Status:** Implemented in repository; production suite run pending this batch's
  deployment.
- **Gap found:** local and production Playwright configs manually enumerated dated
  bug specs, so a committed test could silently be absent from routine runs.
- **Control:** canonical `hari|ram-YYYY-MM-DD-bugs.spec.ts` and
  `hari|ram-YYYY-MM-DD-prod.spec.ts` patterns are selected automatically; the
  functional-QA process test locks both patterns.
- **Evidence:** `playwright.app.config.ts`, `playwright.prod-ram.config.ts`, and
  `scripts/functional-qa-process.test.mjs`.

## 2026-08-16 Strategic Gap Review — verified control gaps

Source: `docs/STRATEGIC_GAP_REVIEW_2026-08-16.md`, verified against `ba869fa2`
by direct code inspection (243 findings). An external strategy review triggered
this pass; 35 of its 111 checkable claims were wrong or overstated and were not
carried forward. The dated April/May benchmark analyses retain the named sources
and URLs that support their comparisons.

Two methodology rules established by this pass and binding on future audits:

1. Confirm `git rev-parse --short HEAD` before measuring. A first pass measured a
   tree 391 commits behind `main` and produced figures wrong by 3-6x.
2. `infra/cloudrun/api-service.yaml` is a reference template, not production
   truth: `scripts/deploy-prod.sh:364-389` deploys via
   `gcloud run deploy --update-env-vars` and never applies it, and
   `infra/cloudrun/deploy.ps1:234` warns against replacing it. Cloud Run *job*
   manifests are applied and may be relied on.

**Scope of severity:** "stop-ship" in `EH-SGR-*` blocks activation, a release
claim, or pilot use of the named surface until that control passes. It does not
block unrelated repository implementation, testing, documentation, or parallel
work listed in `docs/EXECUTION_BACKLOG.md`.

### EH-SGR-01 - Intra-state invoices issued with the wrong GST head

- **Status:** Implemented. Landed in PR #240 (merged 2026-08-17).
- **Evidence:** `services/matter_billing.py` gains `_GST_STATE_CODES` (38
  statutory codes), `gst_state_code_for_place` and
  `resolve_place_of_supply_state_code`, which resolves in precedence order:
  explicit place of supply, client GSTIN, profile default, supplier state.
  Regression: `tests/test_20260816_gst_place_of_supply.py`.
- **Was:** Missing. This entry was stale for three days — PR #240 shipped the
  fix and touched no ledger file. Corrected 2026-08-20 after verifying the
  symbols on `origin/main`, not from the PR description.
- **Gap found:** intra-state B2C invoices are issued with IGST instead of
  CGST+SGST, and a malformed client GSTIN silently produces the same wrong head.
  Place of supply is a free-text display field that never reaches the tax engine,
  which infers jurisdiction from GSTIN digits alone.
- **Control required:** make place of supply a structured input to the tax-head
  decision. For ordinary domestic services under IGST Act 2017 §12(2), use the
  registered recipient's location; for an unregistered recipient use the
  recipient's address on record when it exists, and the supplier's location only
  when no such address exists. Validate the applicable rule and fail closed on
  ambiguous or malformed inputs. Regress registered/unregistered x
  address-present/address-absent x intra/inter-state.
- **Severity:** blocks GST invoice activation/pilot use. Filing-level defect on
  invoices issued through the affected path; unrelated implementation proceeds.

### EH-SGR-02 - A matter can be made permanently unopenable

- **Status:** Implemented. Landed in PR #240 (merged 2026-08-17).
- **Evidence:** the OC-portal and refund-webhook writers no longer emit a
  status the read schema rejects, so `GET /api/matters/{id}` cannot be
  permanently 500ed by a write. Regression:
  `tests/test_20260816_invoice_status_enum_drift.py`, with
  `tests/test_20260816_legacy_invoice_data_safety.py` covering rows already
  written in the bad state.
- **Was:** Missing. Stale for three days; corrected 2026-08-20.
- **Gap found:** an outside-counsel portal invoice submission writes
  `needs_review`, and a refund webhook writes an out-of-enum status; both are
  valid DB states the read schema rejects, so `GET /api/matters/{id}` 500s on
  every subsequent load with no in-product remedy.
- **Control required:** one status enum reconciled across DB, write path and read
  schema; the create/update/read-parse audit mandated for enum drift; backfill of
  rows already in the bad state.
- **Severity:** stop-ship. Repeats the failure class recorded in
  `docs/BUG_REOPEN_LEARNINGS_2026-08-14_RAM.md`.

### EH-SGR-03 - Client payments under-credited

- **Status:** Implemented. Landed in PR #240 (merged 2026-08-17).
- **Evidence:** `services/payments.py` gains `_attempt_collected_minor` and
  `recalculate_invoice_collection`, which sums credited attempts instead of
  taking the largest, and returns early when an invoice has no attempts so a
  receipt recorded outside the attempt flow is never zeroed. Regression:
  `tests/test_20260816_invoice_collection_sum.py`.
- **Was:** Missing. Stale for three days; corrected 2026-08-20.
- **Gap found:** an invoice settled across several attempts credits only the
  largest attempt; the webhook cannot read the amount from the provider's
  documented nested payload and yields 0, so partial payments record as zero
  collected; the flat `amount` key is read as paisa or rupees depending on JSON
  type; the matter-invoice webhook path has no out-of-order guard.
- **Control required:** sum attempts; parse the documented envelope with an
  explicit unit contract; port the subscription path's out-of-order guard.
- **Severity:** stop-ship. Clients are chased for money already paid.

### EH-SGR-04 - Invoice numbering not gapless, not concurrency-safe, not immutable

- **Status:** Implemented. Sequence half in PR #240 (2026-08-17), immutability
  half in migration `20260820_0002`.
- **Gap found:** arbitrary invoice numbers may be supplied by an admin or an
  outside-counsel portal user; the sequence is read unlocked so concurrent
  creation raises an uncaught IntegrityError (500, not retry); a tenant without a
  billing profile can auto-number exactly one invoice ever; immutability exists
  only because no edit endpoint was written - no CHECK, trigger or revision table.
- **Closed by:**
  - Gapless and concurrency-safe: `invoice_number_sequence_query` takes the
    profile row with `FOR UPDATE` before the read-modify-write, and
    `next_invoice_number` no longer returns a constant when a tenant has no
    billing profile. Regression:
    `tests/test_20260816_invoice_number_allocation.py`, whose locking assertion
    compiles against the PostgreSQL dialect because SQLite ignores `FOR UPDATE`.
  - Immutable: `20260820_0002` adds a BEFORE UPDATE trigger rejecting any change
    to `invoice_number`, plus a non-blank CHECK declared on the model and applied
    on every dialect. Regression:
    `tests/test_20260820_invoice_number_immutable.py`.
- **Corrected in the gap text above:** the "arbitrary numbers from an admin"
  half was already wrong when written. The firm-issued create path exposes
  `invoice_number` only on `InvoiceNumberPreviewResponse`, a response model; no
  request schema accepts it. The outside-counsel portal does take a number
  (`portal_outside_counsel.py`), but that is the OC firm's own invoice number on
  a `NEEDS_REVIEW` submission, not an allocation from the firm's GST sequence —
  correct data, not a defect.
- **Deliberately not added:** a revision table. The ledger listed it as one of
  three absent mechanisms, but a revision history records permitted changes;
  once the column cannot change there is nothing to record, and adding one would
  imply a mutation path that must not exist.
- **Verification caveat:** the trigger assertions are `@pytest.mark.postgres`
  and SKIP on the default suite (4 skipped locally). They run in the
  `postgres-validation` CI job. Local evidence covers the CHECK, the model
  declaration and the migration replay only.
- **Severity:** was stop-ship for GST invoicing.

### EH-SGR-05 - Rate limiting covers 3.7% of the API and is per-instance

- **Status:** Partially implemented.
- **Gap found:** slowapi with process-local in-memory storage, no `storage_uri`
  and no Redis anywhere, so limits are per container instance;
  `scripts/deploy-prod.sh:58` pins max 20 instances at concurrency 1, making the
  effective limit up to 20x documented. 7 of 40 route modules apply any limit,
  covering 23 of 622 endpoint decorators. `test_ai_route_governance.py:32`
  inspects only `/api/ai/*` and `/api/recommendations/*`.
- **Severity:** stop-ship for abuse and cost control.

### EH-SGR-06 - Two security controls fail open by construction

- **Status:** Partially implemented.
- **Gap found:** `services/inbound_email.py:224-225` bare-returns from
  `_verify_signature` in mock mode before the HMAC comparison;
  `core/csrf.py:72-80` exempts any path ending `/webhook` via
  `_EXEMPT_SUFFIXES`, by design. Separately there is no log redaction, so any
  `extra={...}` carrying client names, emails or payment payloads reaches Cloud
  Logging in the clear.
- **Severity:** stop-ship. Privilege exposure in a legal product.

### EH-SGR-07 - Citation verifier does not check the proposition on production paths

- **Status:** Partially implemented. The code control is in place and tested;
  the missing layer is verification — no measurement of the change against
  production data, so the size of the correction is unknown. Per this skill's
  own rule, mixed evidence stays at `Partially implemented` rather than
  upgrading early. It moves to `Implemented` when the replay below has run.
- **Gap found:** of three `verified=True` paths in `services/citations.py`, the
  bracket-tag short-circuit read neither `source.text` nor `claim.proposition`,
  and both production prompts (`recommendations.py`, `litigation_strategy.py`,
  in the citation-format instruction) hard-require that tag. Any citation the
  model emitted in the required format therefore bypassed verification
  entirely: "citation verified" meant "the model emitted an in-range list
  index". How often production actually emitted the tag is not measured — the
  prompts require it, which is a strong reason to expect near-total coverage,
  but that is an inference, not a count. Drafting passes `proposition=None`.
  `tests/test_citations.py` asserted the bypass as intended behaviour.
- **Fix landed:** three changes, in the order that made each one safe.
  1. Gate hardened - distinct non-stopword token counting, `_STOPWORDS` added
     (the docstring had promised a stopword list that never existed, and the
     overlap set was a list, so one repeated token satisfied the two-token rule).
  2. Callers given real propositions - `litigation_strategy.item_proposition()`
     composes description/rationale/label/stage_label/mitigation/action at all
     four call sites, replacing the literal `"strategy item citation"`.
  3. Bracket tag demoted to a resolver: it now answers "which source is this?"
     and the resolved source clears the same gate as any other match.
  The two tests that pinned the bypass are inverted, not deleted, and carry the
  supersession note. `source_text_unavailable` was added so a retrieval gap is
  not misreported as an ungrounded claim.
- **Deliberately unchanged:** a claim with no proposition is still
  `bare_citation`. That is drafting's contract - "we hold this authority", not
  "it supports this sentence". Forcing a proposition there would feed a whole
  draft body to a bag-of-words check, which passes trivially and proves nothing.
- **Known limit, recorded not implied:** the gate is a *topicality filter*, not
  an entailment check. It is bag-of-words and polarity-blind, so a negated
  proposition shares every content word with the holding it contradicts. Closing
  that needs entailment or quoted-span verification. Do not describe a pass as
  "the source supports the claim".
- **Still open:** the production re-baseline. `scripts/replay_citation_gate.py`
  measures how many currently-"verified" citations the real gate rejects; it
  needs production data and has not been run. Expect recommendation and strategy
  confidence to drop (`_cap_confidence`) and some citations to stop rendering -
  that is the gate working, but the magnitude is unmeasured. Any published
  quality number that predates this change is stale.
- **Severity:** was stop-ship. Reliance on fabricated precedent is judicially
  treated as misconduct.
- **Adjacent, noted not fixed:** refusal ordering in `litigation_strategy`.
  Citation verification runs before the forbidden-phrase check, so a payload
  that both contains disallowed language ("will win") and fails the gate is
  refused as "primary route has no verified authority". Both are 422 and the
  user is protected either way, but the message names the wrong reason, which
  will mislead whoever debugs it. Surfaced because a fixture with an ungrounded
  rationale made the forbidden-phrase test pass for the wrong reason once the
  gate went live. Out of scope for this change; ordering is pre-existing.
- **Evidence:** `tests/test_20260816_bracket_tag_is_a_resolver.py`,
  `tests/test_20260816_proposition_gate_hardening.py`.

### EH-SGR-08 - Customer-facing claims not backed by running code

- **Status:** Missing.
- **Gap found:** `apps/web/components/marketing/Security.tsx:83` sells
  "Prompt-injection tests" while the stripper is unreachable from
  the hosted provider adapters, with `conftest.py:106` pinning the suite to mock. A
  billable "API access - API keys and dashboard" SKU is seeded active while no
  API-key authentication exists.
- **Control required:** a test that asserts each marketing claim against code.
  The honesty framework is currently prose-enforced, not test-enforced.
- **Severity:** stop-ship for commercial and revenue-recognition reasons.

### EH-SGR-09 - Observability and DR are configured but not operative

- **Status:** Partially implemented.
- **Gap found:** OTel is broken at three independent layers - the `observability`
  extra is never installed (`apps/api/Dockerfile:39-40`), no artifact sets the
  flag for the production API, and the exporter default is `localhost:4318` with
  no collector target. Staging sets `CASEOPS_OTEL_ENABLED=true` (`ci.yml:509`)
  against an image without the SDK, so it emits no traces while reading as
  working evidence. `matter_id` is plumbed but never called from any route,
  service or worker. Logs are JSON but not Cloud Logging-shaped (`level`, not
  `severity`; no trace field). There is no alert policy, uptime check, SLO, log
  metric or paging integration anywhere. `/api/health` returns 200 with an
  unreachable database. One restore rehearsal has ever occurred (2026-04-24),
  51 days past the missed quarterly slot; no IaC artifact configures Cloud SQL
  backups, GCS versioning or lifecycle.
- **Severity:** scale-hardening, blocking for any monitored pilot.

### EH-SGR-10 - IP documents endpoint returns every tenant document unpaginated

- **Status:** Missing.
- **Gap found:** surfaced while mapping the 2026-08-16 feedback document
  (`docs/FEEDBACK_MERGE_BACKLOG_2026-08-16.md`, DOC-IP-03). `GET /api/ip/documents`
  returns EVERY document in the tenant with no pagination and an N+1 per-row
  access check (`_assert_document_targets_accessible`). There is no
  taxonomy/type/state filter, so the caller cannot narrow the set either.
- **Control required:** taxonomy_key / query / state filters plus pagination
  applied in SQL *before* the per-row access loop, so restricted documents leak
  no count and the row scan is bounded.
- **Severity:** scale-hardening. Degrades with tenant size and duplicates the
  unbounded-scan class already recorded against `/api/health/ingest` in
  EH-SGR-09.

### EH-SGR-11 - IP identifier uniqueness has two conflicting rules

- **Status:** Partially implemented.
- **Gap found:** `ip_identifiers` has no unique constraint and instead flags
  duplicates via `_duplicate_identifiers` (`services/ip_records.py:80-104`) with
  `reconciliation_status='needs_review'`, while `docket.primary_identifier` is
  hard-unique per company (`uq_ip_docket_company_identifier`,
  `db/models.py:14012-14016`) and returns HTTP 409. The same user-facing concept
  ("application number already exists") therefore behaves two different ways
  depending on which field it lands in.
- **Control required:** one decided rule (per company? per registry+kind? are
  legitimate re-filings allowed?), encoded once. The 2026-08-16 feedback document
  lists this as an open requirement, so the decision is a founder input.
- **Severity:** scale-hardening, blocking for IP identifier UI work.

### EH-SGR-12 - IP duplicate detection silently misses matches (office not normalised)

- **Status:** Missing.
- **Gap found:** `_duplicate_identifiers` (`services/ip_records.py:95-96`) keys on
  the raw `office` value, so "Delhi" and "delhi" occupy different namespaces and
  the duplicate check fails to detect real duplicates. A duplicate-detection
  routine that silently under-detects is worse than none, because downstream
  reconciliation treats its output as authoritative.
- **Control required:** normalise `office` (and `jurisdiction`) before use as a
  duplicate-detection key, and seed the registry-office master so the value comes
  from a controlled list rather than free text.
- **Severity:** stop-ship for IP identifier work. Surfaced by
  `docs/OPEN_ITEM_RESOLUTIONS_2026-08-16.md` D-1.

### EH-SGR-13 - Two disagreeing identifier normalisations

- **Status:** Partially implemented.
- **Gap found:** `normalize_ip_identifier` (`services/ip_identifier_rules.py:14-18`)
  applies NFKC + casefold + alphanumeric-only, while the docket create path
  applies only `.strip().upper()` (`services/ip_operations.py:313`). `TM-1234`
  and `TM 1234` therefore collide in the ledger but not on the docket - the same
  pair of strings is one number in one layer and two in the other.
- **Control required:** one normalisation. Resolved by deriving
  `docket.primary_identifier` from the confirmed current `is_primary` ledger row
  so it inherits the ledger normalisation (see OPEN_ITEM_RESOLUTIONS §3).
- **Severity:** scale-hardening; becomes stop-ship once identifier UI ships.

### EH-SGR-14 - Terminal-status constants disagree between IP modules

- **Status:** Partially implemented.
- **Gap found:** `services/ip_lifecycle.py:40-42` and `services/ip_records.py:708`
  define different terminal sets. The latter mixes application phases
  (`refused`/`withdrawn`/`registered`) into a docket-status test and omits
  `archived`/`transferred`/`retired`. It is not fail-open today only because an
  adjacent `docket_is_active` check at `ip_records.py:721` happens to cover the
  gap - correct by luck, not by construction.
- **Control required:** one shared terminal constant, asserted by a test that
  fails if the two modules diverge again.
- **Severity:** scale-hardening. Same class as the lifecycle rules already
  recorded under EH-LC-01.

### EH-SGR-15 - Ingest fetcher sends a spoofed browser user-agent

- **Status:** Missing.
- **Gap found:** the authority ingest fetcher presents a spoofed Chrome
  user-agent and does not consult `robots.txt` or apply a per-host minimum
  interval. This is the clearest terms-of-use exposure in the ingest path and it
  sits badly against the repository rule that public legal data needs source,
  lineage and access-boundary checks.
- **Control required:** identifying user-agent
  (`CaseOps-AuthorityIngest/1.0 (+https://<domain>/crawler; contact <ops-email>)`),
  `robots.txt` fetched and honoured once per host per run, and a per-host minimum
  request interval.
- **Severity:** stop-ship before any expanded ingest run. Surfaced by
  `docs/OPEN_ITEM_RESOLUTIONS_2026-08-16.md` §9.

### EH-SGR-16 - Dead notification channels are user-selectable

- **Status:** Missing.
- **Gap found:** `SMS` and `WHATSAPP` are selectable notification channels with
  no way to reach a recipient - there is no verified phone number on `User` or
  `CompanyMembership`, and WhatsApp has no adapter. Selecting `sms` on a hearing
  produces reminder rows that can only ever reach `FAILED`, while the UI presents
  the choice as valid.
- **Control required:** remove both from every user-facing selector and mark them
  `roadmap` in the API response until a verified-phone slice and an adapter
  exist. Keep the enum members for forward compatibility.
- **Severity:** stop-ship for the hearing-reminder workflow (F-03): it is the
  product inviting a failure it cannot fulfil.

## 2026-08-20 Parallel-lane deploy control gap

### EH-DEPLOY-01 - A split alembic revision graph reaches the trunk unchecked

- **Status:** Partially implemented — control written and unit-proven in
  `fix/alembic-single-head-gate-20260820` (PR #284), **not yet merged**. It is
  not `Implemented` until it is on `main` and has demonstrably failed a real
  offending pull request.
- **Gap found:** two lanes each added a migration whose `down_revision` was
  `20260820_0002` — `20260821_0001` (calendar reconciliation, PR #282) and
  `20260821_0002` (IP cost items, PR #283). That is two alembic heads, and
  `alembic upgrade head` refuses to run with more than one, so the deploy fails
  at the migration step.
- **Why nothing caught it:** `scripts/migration_preflight.py` checked lock risk
  (UJ-67-EXC-01) and destructive downgrades (UJ-67-EXC-06) but never the shape
  of the revision graph. The `postgres-validation` job does run `alembic upgrade
  head`, yet **neither pull request's branch contains both migrations** — each
  holds only its own file — so neither branch can fail. The collision first
  appears on the trunk, after both have merged.
- **Why this is a fail-open control, not bad luck:** nothing about the two lanes
  was irregular. Any two parallel branches adding a migration from the same
  parent produce this, and the repository runs many concurrent lanes by design.
  The default outcome of ordinary work was a broken trunk.
- **A blind spot in the first version of this control, found in review.**
  Checking `len(heads) > 1` misses a cycle entirely. A graph that is *only* a
  cycle has **zero** heads, and — the harder case — a sound chain beside a
  disconnected cycle has **exactly one**, so neither "more than one head" nor
  "exactly one head" sees it. `MIGRATION-REVISION-CYCLE` therefore walks
  `down_revision` to a base independently of the head count, and a merge
  revision counts as grounded only when *every* parent is: one poisoned branch
  makes the merge unreachable.
- **Control required:** evaluate the revision graph over every migration present
  rather than only the changed one, so the pull-request merge commit — which is
  what CI builds — sees both files and fails before merge. Report the heads and
  their paths, and name the resolution (re-chain, or an explicit merge revision);
  a gate that only refuses gets deleted rather than satisfied.
- **Severity:** stop-ship for any release train carrying two concurrent
  migration lanes. Not stop-ship for a single-lane release.
- **Residual risk after PR #284:** the gate fires on the *second* lane's CI run
  after the first merges. It does not resolve an existing collision — #282 and
  #283 still need a re-chain or merge revision, whichever lands second. It also
  cannot see a migration that exists only in an unmerged sibling branch, which
  is correct: that is not yet a property of the trunk.
- **Verification:** with both lanes' real migration files present,
  `python scripts/migration_preflight.py validate` exits 1 and names both heads;
  with either alone, and on current `main`, it exits 0 reporting the single
  head. Unit coverage in
  `apps/api/tests/test_uj67_migration_preflight.py::TestRevisionGraphShape`
  (linear chain, the exact collision shape, merge-revision resolution, duplicate
  revision ids, and an assertion that the committed graph has one head).
- **Three real occurrences in two days, none caught by anything but a manual
  check.** The gap was recorded from a predicted collision. It has since
  happened three times for real, and the *predicted* failure mode was the least
  dangerous of them:
  1. **2026-08-20, two heads.** `20260821_0001` (calendar) and the IP-cost
     migration both chained from `20260820_0002`. Predicted; resolved by
     re-chaining.
  2. **2026-08-21, duplicate id.** PR #282 carried a *second* migration,
     `20260821_0002`, colliding with the IP-cost migration's id.
  3. **2026-08-21, duplicate id again.** PR #285 claimed `20260821_0003`,
     colliding with the same branch a second time.
  A duplicate id is worse than a split head and was the case nobody predicted.
  Two heads make `alembic upgrade head` refuse to run — loud, and it stops. A
  duplicate id makes alembic emit a warning and then resolve it silently,
  leaving one migration unreachable: no error, no failed deploy, columns that
  never appear.
  Demonstrated against the real files rather than a reconstruction: restoring
  the pre-renumber IP-cost migration beside `20260821_0003_ip_deadline_incident_lifecycle.py`
  makes `validate` exit 1 with `MIGRATION-DUPLICATE-REVISION` naming both files;
  removing it returns exit 0 and `single head 20260821_0003`.
  This raises the severity: the gap is not an occasional hazard of unusual
  scheduling, it is the ordinary outcome whenever two lanes touch migrations in
  the same week, and it recurs every time main moves.

## 2026-08-22 Step-up second-factor audit

### EH-SEC-01 - Step-up is conditional on MFA enrolment, and enrolment defaults to none

- **Status:** Partially implemented. The control exists, is correct once a
  tenant enables it, and five of the highest-consequence call sites are now
  unconditional. The remaining ~45 keep the conditional default.
- **Gap found:** `services/security.py::require_recent_step_up` requires a
  step-up only when the caller **already has MFA enrolled**, or when tenant
  policy mandates MFA:

  ```python
  should_require = require_if_mfa_enrolled and setting is not None and setting.status == "enrolled"
  ```

  `TenantSecurityPolicy.tenant_admin_mfa_required` and `all_users_mfa_required`
  both default to `False`, and a tenant with no policy row has no requirement at
  all. So for a new tenant the resolved rule is **"an actor with no MFA
  enrolment satisfies the second factor by not having one"** — the default
  posture, not an edge case.
- **Why this is not simply a bug:** the conditional shape is a deliberate
  progressive-adoption stance and it is right for most actions. A hard
  requirement everywhere would lock a tenant out of its own product before it
  has adopted MFA. The gap is not that the rule is conditional; it is that the
  conditional rule is applied *uniformly*, including to actions that are
  irreversible or that grant authority, where proceeding with no second factor
  is worse than refusing.
- **Closed here (unconditional via the new `require_step_up_always`):**
  | Purpose | Why it cannot be conditional |
  |---|---|
  | `data_operation_execution` | Authorises an export, purge or offboarding (closed earlier, PR #296) |
  | `retention_policy_activation` × 2 | Approving and activating a schedule authorises **every future purge** under it — upstream of the gate closed in #296, which is why leaving it conditional was an inconsistency |
  | `legal_hold_change` × 2 | Activating and, critically, **releasing** a hold lifts preservation and makes held evidence deletable |
- **Recorded, deliberately NOT changed here:** each of these is outside the
  records-governance lane, and hardening them has real lockout consequences
  that are a product decision rather than a defect fix. Listed by the strength
  of the case for making them unconditional:
  | Purpose | Sites | Consequence if performed without a second factor |
  |---|---|---|
  | `role_capability_change` | 1 | Privilege escalation from a compromised session |
  | `destructive_action` | 2 | Named as destructive |
  | `payment_activation_change` | 3 | Enables live payment capture |
  | `billing_export` | 13 | Bulk financial data egress |
  | `connector_credential_change` / `connector_disconnect` | 8 | Provider credential and integration control |
  | `record_access_change` | 1 | Alters who can see restricted records |
  | `platform_admin_access` | 1 | Cross-tenant administrative reach |
- **Severity:** not stop-ship on its own — a tenant that enables the MFA policy
  is protected on every one of these paths, and the product decision to allow
  progressive adoption is legitimate. It is a fail-open **default** on
  irreversible actions, which the hardening protocol counts as a gap whether or
  not a bug has been reported.
- **Decision needed from the product/security owner:** whether the
  `role_capability_change` and `destructive_action` purposes should join the
  unconditional set, accepting that a tenant with no MFA enrolment could not
  perform them at all.
- **A hollow test found and replaced:**
  `test_both_lifecycle_paths_demand_step_up` asserted
  `'require_recent_step_up' in inspect.getsource(...)`. A source-text grep
  cannot distinguish a conditional gate from an unconditional one, so it passed
  throughout the period the gate was open for un-enrolled actors. It now deletes
  the step-up row and asserts a real 403. Verified by falsification: restoring
  the conditional helper fails the new test and passed the old one.
- **Verification:** `verify-backend.sh` across the data-governance, retention,
  approval, review-contract and hold suites — 81 passed. Every test that had to
  change was green *because* of the hole, which is the clearest evidence that
  the hole was load-bearing.

### EH-SEC-02 - Step-up purposes are audit labels, not enforcement boundaries

- **Status:** Partially implemented. True for the five `require_step_up_always`
  sites, which match the purpose exactly. Not true for the ~45 sites on
  `require_recent_step_up`.
- **Gap found:** `require_recent_step_up` falls back to *any* purpose:

  ```python
  if recent_step_up_expires_at(session, context=context, purpose=purpose):
      return
  if purpose != "step_up" and recent_step_up_expires_at(session, context=context):
      return
  ```

  The second call passes no purpose, so it matches any unexpired step-up row.
  **Verified empirically**, not read off the source: a step-up completed for
  `matter_summary` satisfies a later requirement for `legal_hold_change`
  (`conditional=True`), while `require_step_up_always` refuses it
  (`always=False`).
- **Why it matters:** `STEP_UP_PURPOSES` reads as a set of separately-governed
  controls, and its own comment says purposes are named apart "so the two can be
  governed independently later". At enforcement time they are interchangeable
  for the whole TTL — `mfa_step_up_ttl_minutes`, default **15**. So one MFA
  prompt accepted for the mildest reason currently authorises the strongest one
  within that window, on every conditional site.
- **Not changed here, deliberately.** Removing the fallback re-prompts users on
  every distinct purpose within a working session, which has a real usability
  cost and reaches ~45 call sites outside the records-governance lane. That is a
  product decision. What is not acceptable is for the current behaviour to be
  true *by accident*, so it is now pinned by
  `apps/api/tests/test_step_up_purpose_semantics.py`, whose failure message says
  to update this entry deliberately rather than let code and ledger diverge.
- **Interaction with EH-SEC-01:** the five hardened sites gain a second property
  beyond unconditionality — a cross-purpose step-up cannot authorise them
  either. That was a consequence of matching the purpose exactly rather than a
  separately argued decision, and it is asserted so it cannot regress silently.
- **A related sharp edge, safe but undiagnosable:** `complete_step_up` records
  `purpose if purpose in STEP_UP_PURPOSES else "step_up"`. A typo in a caller's
  purpose string therefore produces a row labelled `step_up`, which
  `require_step_up_always` would never accept — the control would refuse
  *forever* rather than fail open. That is the safe direction, but the 403 says
  nothing about the cause. The test asserts every purpose used with the
  unconditional gate is registered.
- **Severity:** not stop-ship. It narrows, but does not remove, the value of a
  second factor, and the strongest actions are already exempt.
- **Decision needed from the product/security owner:** whether the conditional
  gate should stop accepting cross-purpose step-ups, accepting the extra prompts.

### Owner decisions on EH-SEC-01 and EH-SEC-02 — 2026-08-22

Both open questions were put to the repository owner and both were answered.
Recorded here because a security posture chosen deliberately and a security gap
left by accident look identical in the code six months later.

**EH-SEC-01 — do not extend the unconditional set.** Asked whether
`role_capability_change` and `destructive_action` should require a second factor
unconditionally. Answer: **no — avoid MFA.** The conditional,
progressive-adoption rule stands for those and for the rest of the ~45 sites.

**EH-SEC-02 — keep the cross-purpose fallback.** Asked whether the conditional
gate should stop accepting a step-up completed for a different purpose. Answer:
**no — no frequent prompts.** One step-up continues to satisfy any purpose for
the TTL.

Consequences, stated plainly so nobody has to re-derive them:

- On the ~45 conditional sites, an actor with **no MFA enrolment** has no second
  factor at all, and an actor with one enrolled needs only a single step-up per
  15-minute window to authorise anything. That is now a **chosen posture**, not
  an oversight. Tenants that want more can still set
  `TenantSecurityPolicy.all_users_mfa_required`, which is the intended lever.
- The five `require_step_up_always` sites are **out of scope of both answers**
  and keep their stronger behaviour. The questions asked whether to *extend*
  hardening to more purposes and whether to *remove* the fallback from the
  conditional gate; neither asked to weaken protection already shipped for
  irreversible acts, and reading them that way would silently reverse a merged,
  owner-accepted control (#296). Those five are: authorising an export/purge
  execution, approving and activating a retention schedule, and activating and
  releasing a legal hold.
- The practical cost of that exemption is **one extra MFA prompt per irreversible
  act** — releasing a hold or authorising a purge needs a step-up for that exact
  purpose. If the owner intends "no frequent prompts" to cover these five as
  well, say so and they revert to the conditional gate; this note exists so that
  is a decision rather than a discovery.

Status of both entries stays `Partially implemented`: the control is now
deliberately partial rather than accidentally so, and the tests pin which half
is which.
