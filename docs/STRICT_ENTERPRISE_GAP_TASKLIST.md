# Strict Enterprise Gap Tasklist

This is the fail-closed enterprise hardening ledger for CaseOps.
`docs/WORK_TO_BE_DONE.md` is planning input only. Claude must cross-check
backlog claims against code, tests, and deploy manifests before changing any
status here.

Status legend:

- `Implemented`
- `Partially implemented`
- `Missing`
- `Stale-doc`

Current overall verdict (2026-04-23): `NO-GO` for claiming "enterprise-grade,
hardened, ready to scale" without caveat.

## Strict Repo Quality Audit (2026-04-24) — P0 status

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
- `P1-006` `Missing` Postgres-backed DB validation tests remain deferred until
  CI has a Postgres service container.
- `P1-007` `Implemented` AI route governance gate enforces rate limits for
  `/api/ai/*` and `/api/recommendations/*` mutations.
- `P1-008` `Implemented` Upload size cap and abuse tests landed.
- `P1-009` `Partially implemented` Runbook exists, but backup/restore drill
  evidence against a clean environment has not been re-run in this session.
- `P1-010` `Implemented` OpenAPI client drift gate is wired into CI.

The original `QG-*` entries below are retained as audit history; this section
is the current closure status.

## Phase C-2 (2026-04-24, MOD-TS-015) — client portal matter surface

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

Phase C-3 (outside-counsel portal — work-product upload, invoice
submission, time entries) intentionally next; not landed today.

## Stop-Ship Control Gaps

- `EG-001` `Missing` Browser bearer-token hardening.
  Evidence: `apps/web/lib/session.ts:5-48`, `apps/web/next.config.ts:3-8`.
  Gap: access tokens still live in `localStorage`, so any successful XSS sink
  becomes a session-exfiltration event.
  Close when: browser auth moves to HttpOnly/SameSite cookies or an equivalent
  opaque session transport, the CSRF story is explicit, and the localStorage
  token path is removed.

- `EG-002` `Partially implemented` Deploy-time migration safety.
  Evidence: `apps/api/src/caseops_api/main.py:17-22`,
  `infra/cloudrun/api-service.yaml:44-45`,
  `apps/api/src/caseops_api/core/settings.py:54`.
  Gap: the live API service still auto-runs DB migrations on startup.
  Close when: schema migration becomes a separate controlled job or release
  step, and runtime services start with `CASEOPS_AUTO_MIGRATE=false`.

- `EG-003` `Partially implemented` Malware scanning enforcement.
  Evidence: `apps/api/src/caseops_api/services/virus_scan.py:80-82`,
  `apps/api/src/caseops_api/services/virus_scan.py:153-169`,
  `apps/api/src/caseops_api/services/matters.py:1300-1305`,
  `apps/api/src/caseops_api/services/contracts.py:826-831`,
  `infra/cloudrun/api-service.yaml:35-66`.
  Gap: uploads skip scanning when ClamAV is unset and fail open when the
  scanner errors unless `CASEOPS_CLAMAV_REQUIRED=true`; Cloud Run manifests do
  not wire the scanner.
  Close when: the production path has a real scanner wired, enforced, audited,
  and fail-closed.

- `EG-004` `Missing` Authenticated abuse controls for expensive AI routes.
  Evidence: rate limits are present only at
  `apps/api/src/caseops_api/api/routes/auth.py:21-23` and
  `apps/api/src/caseops_api/api/routes/bootstrap.py:14-20`, while expensive
  generation paths remain unthrottled at
  `apps/api/src/caseops_api/api/routes/matters.py:298-400` and
  `apps/api/src/caseops_api/api/routes/drafting.py:165-193`.
  Gap: authenticated users can repeatedly hit AI-heavy routes without route
  class limits, tenant budgets, or cost guardrails.
  Close when: expensive endpoints have route or tenant-aware throttles and the
  strongest practical regression coverage.

- `EG-005` `Partially implemented` Matter summary governance.
  Evidence: `apps/api/src/caseops_api/services/matter_summary.py:231-302`,
  `apps/api/src/caseops_api/api/routes/matters.py:298-400`,
  `apps/api/src/caseops_api/services/llm.py:626-673`.
  Gap: matter summaries are generated on demand for GET and export, there is no
  persisted cache, no `ModelRun` writer is passed, and fallback only handles
  malformed JSON rather than wider provider failures.
  Close when: summary generation is cached or explicitly regenerated, model runs
  are audited, provider-failure handling matches other AI surfaces, and exports
  do not silently trigger redundant LLM work.

- `EG-006` `Partially implemented` Draft preview governance.
  Evidence: `apps/api/src/caseops_api/services/drafting_preview.py:51-121`,
  `apps/api/src/caseops_api/api/routes/drafting.py:165-193`,
  `apps/api/src/caseops_api/services/tenant_ai_policy.py:9-11`,
  `apps/api/src/caseops_api/services/llm.py:636-673`.
  Gap: preview calls `llm.generate(...)` directly, does not persist a
  `ModelRun`, does not reuse the structured-call policy path, and returns raw
  exception detail in a 502.
  Close when: preview uses the same tenant policy and audit discipline as other
  AI paths and redacts provider or internal exception text.

- `EG-007` `Partially implemented` Secret-management and runtime control wiring.
  Evidence: `infra/cloudrun/api-service.yaml:14`,
  `infra/cloudrun/api-service.yaml:48-49`,
  `infra/cloudrun/api-service.yaml:62-66`,
  `docs/WORK_TO_BE_DONE.md:590-595`.
  Gap: auth secret is secret-managed, but DB connectivity and the rest of the
  sensitive runtime surface are not fully wired through a single managed-secret
  policy with rotation evidence.
  Close when: all production secrets use Secret Manager or an equivalent managed
  store, rotation is documented, and runtime manifests stop embedding raw
  secret values.

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

- `WTD-5.1` `Missing` Temporal durable workflows.
  Evidence: `docs/WORK_TO_BE_DONE.md:407-415`.

- `WTD-5.2` `Missing` Agent identity, scoped grants, approval gates, and
  budgets.
  Evidence: `docs/WORK_TO_BE_DONE.md:417-426`.

- `WTD-5.3` `Missing` Notification service with durable delivery and retry.
  Evidence: `docs/WORK_TO_BE_DONE.md:428-435`.

- `WTD-6.5` `Partially implemented` OpenAPI maturity and generated web client
  rollout.
  Evidence: `docs/WORK_TO_BE_DONE.md:512-517`,
  `apps/web/package.json:13`,
  `apps/web/lib/api/openapi-types.ts:1`.

- `WTD-7.2` `Missing` Generic task and deadline model beyond contract-only
  obligations.
  Evidence: `docs/WORK_TO_BE_DONE.md:534-540`.

- `WTD-7.3` `Partially implemented` Model-evaluation admin gate and cost rollup.
  Evidence: `docs/WORK_TO_BE_DONE.md:541-545`,
  `apps/api/src/caseops_api/db/models.py:2704`,
  `apps/api/src/caseops_api/services/evaluation.py:12-137`.

- `WTD-7.4` `Missing` Statute, Section, Issue, and Relief model.
  Evidence: `docs/WORK_TO_BE_DONE.md:547-550`.

- `WTD-8.3` `Missing` Backup, restore, and tenant-export drill evidence.
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

- `WTD-10.5` `Missing` Plan entitlements and enforcement.
  Evidence: `docs/WORK_TO_BE_DONE.md:650-652`.

- `WTD-11.2` `Missing` Authorization matrix tests.
  Evidence: `docs/WORK_TO_BE_DONE.md:664-666`.

- `WTD-11.4` `Missing` AI safety benchmark automation.
  Evidence: `docs/WORK_TO_BE_DONE.md:673-676`.

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

- `WTD-12.3` `Missing` Email ingest and calendar sync.
  Evidence: `docs/WORK_TO_BE_DONE.md:707-709`.

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

- `QG-P0-001` `Missing` Admin audit export is broken after the HttpOnly cookie
  migration because the UI still calls `getStoredToken()` and sends a bearer
  header even though `getStoredToken()` now always returns `null`.
  Evidence: `apps/web/lib/session.ts:30-36`,
  `apps/web/app/app/admin/page.tsx:51-69`,
  `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

- `QG-P0-002` `Missing` Canonical Windows backend verification is not
  repeatable because `scripts/verify-backend.ps1` fails to parse before lint or
  pytest run.
  Evidence: `scripts/verify-backend.ps1:28`,
  `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

- `QG-P0-003` `Partially implemented` Calendar ICS route returns an ICS body but
  OpenAPI quality verification fails because the declared response media type is
  `text/plain`.
  Evidence: `apps/api/src/caseops_api/api/routes/calendar.py:96-137`,
  `tests/test_openapi_quality.py`,
  `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

- `QG-P0-004` `Partially implemented` SendGrid webhook signature verification
  can fail open when the public key is missing or the crypto dependency cannot
  be imported.
  Evidence: `apps/api/src/caseops_api/api/routes/notifications.py:101-116`,
  `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

- `QG-P0-005` `Partially implemented` Billing E2E coverage is not clean because
  the Pine Labs credential skip can also hide the invoice UI path from default
  E2E verification.
  Evidence: `tests/e2e/billing-payment.spec.ts:43-46`,
  `docs/STRICT_REPO_QUALITY_AUDIT_2026-04-24.md`.

- `QG-P1-001` `Partially implemented` Generated API route and frontend page
  coverage ledgers now exist and fail on new unclassified surfaces, but 16 API
  and 20 page baseline waivers remain real test gaps.
  Evidence: `apps/api/tests/test_route_coverage_matrix.py`,
  `apps/web/app/__page-coverage-matrix.test.ts`,
  `docs/CODEX_REVIEW_PACK_2026-04-24.md`.

- `QG-P1-002` `Implemented` Security scanning and dependency/license gates are
  wired into CI.
  Evidence: `.github/workflows/security.yml`,
  `docs/CODEX_REVIEW_PACK_2026-04-24.md`.

## Claude Discipline

- Claude must read `.claude/skills/enterprise-hardening/SKILL.md` before any
  enterprise-readiness, scale-hardening, or `WORK_TO_BE_DONE.md` audit.
- Claude must update this file in the same task as the audit.
- Claude must not close a hardening item without evidence from code, tests, and
  deploy or runtime state where relevant.
- Claude must call out doc drift explicitly instead of silently trusting or
  rewriting old backlog text.
