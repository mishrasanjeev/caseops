# Strict Repo Quality Audit - 2026-04-24

Verdict: `NO-GO` for release-grade strictness.

This audit is intentionally stricter than the current CI bar. It is written as
an execution brief for Claude Code: fix the P0/P1 items, add the missing tests,
and do not close an item without evidence from code, tests, and where relevant
runtime or deploy state.

## Scope

- Repository root: `C:\Users\mishr\caseops`.
- Surfaces reviewed: `apps/api`, `apps/web`, `tests/e2e`, `.github/workflows`,
  `infra`, `docs`, `.claude/skills`.
- Product references: `docs/PRD_CLAUDE_CODE_2026-04-23.md`,
  `docs/WORK_TO_BE_DONE.md`, `docs/STRICT_ENTERPRISE_GAP_TASKLIST.md`.
- Skills applied: `.claude/skills/enterprise-hardening/SKILL.md` and
  `.claude/skills/caseops-prd-execution/SKILL.md`.

## Evidence Snapshot

Inventory gathered on 2026-04-24:

- Backend OpenAPI exposes `135` paths and `157` operations.
- Frontend has `43` `page.tsx` routes.
- Frontend direct page tests exist for `10` of `43` page routes.
- Frontend unit/component test suite has `26` files and `116` tests.
- Backend pytest suite has `75` test modules and roughly `565` collected test
  cases by static count.
- Playwright suite has `18` specs and roughly `58` tests; at least one provider
  path is skipped when Pine Labs credentials are not present.

Verification attempted:

| Check | Result | Notes |
| --- | --- | --- |
| `scripts\verify-backend.ps1` | `FAIL` | PowerShell parser error around the inline here-string passed to `python -c`; canonical Windows backend verification is broken. |
| `scripts\verify-web.ps1 -Quick` | `FAIL` | Vitest startup hit Vite/Rolldown `spawn EPERM` under the sandbox. |
| `apps/api/.venv/Scripts/ruff.exe check src tests` | `PASS` | Backend lint passed. |
| Targeted backend pytest: auth cookies, portal auth, webhook security, OpenAPI quality | `FAIL` | `28 passed, 1 failed`; `GET /api/calendar/events.ics` OpenAPI declares unexpected `text/plain`. |
| `npm run typecheck --workspace @caseops/web` | `PASS` | Next typegen and `tsc --noEmit` passed. |
| `npm run test --workspace @caseops/web` | `PASS` | `26` files, `116` tests passed when run outside the sandbox restriction. |

Do not treat this as a clean sign-off. The strongest canonical backend and web
verification scripts did not complete cleanly, and one targeted backend quality
test failed.

## Critical Findings

### P0-001 Admin Audit Export Is Broken After HttpOnly Cookie Migration

Status: `Missing` regression fix.

Evidence:

- `apps/web/lib/session.ts:30-36` documents that `getStoredToken()` always
  returns `null` in the HttpOnly-cookie era.
- `apps/web/app/app/admin/page.tsx:51-69` still calls `getStoredToken()` and
  sends `Authorization: Bearer ${token}` for `/api/admin/audit/export`.

Impact:

- A valid cookie-authenticated admin cannot export the audit trail from the UI.
- The page reports "Your session expired" even when the session is valid.
- This is a governance and compliance feature, so this is stop-ship.

Required fix:

- Replace bearer-token export with cookie-aware `fetch` using
  `credentials: "include"` or a blob-capable shared API helper.
- Preserve CSV/JSONL blob download behavior and server error detail handling.
- Add a regression test proving a valid cookie session can export audit logs
  without calling `getStoredToken()`.
- Add an E2E or integration test for the admin export happy path and a 403 path.

Acceptance:

- No app UI code calls `getStoredToken()` except explicit compatibility tests.
- Audit export succeeds with a cookie session and fails gracefully on 401/403.

### P0-002 Canonical Backend Verification Script Is Broken On Windows

Status: `Missing` verification fix.

Evidence:

- `scripts/verify-backend.ps1:28` invokes `& $VenvPy -c @'`.
- Running `scripts\verify-backend.ps1` failed before lint or tests with a
  PowerShell parser error.

Impact:

- The documented backend verification recipe in `CLAUDE.md` is not repeatable
  for the current Windows workspace.
- Outside agents can falsely assume backend verification passed because the
  documented command exists.

Required fix:

- Rewrite the import sanity check so PowerShell parses it reliably.
- Set workspace-local temp/cache paths for pytest where needed.
- Keep the script compatible with arbitrary pytest args and `-k` expressions.
- Add a CI or local smoke check that executes the script itself.

Acceptance:

- `scripts\verify-backend.ps1` runs lint and targeted pytest cleanly on Windows.
- Script failure messages identify whether the problem is bootstrap, import,
  lint, or pytest.

### P0-003 OpenAPI Quality Test Fails For Calendar ICS Media Type

Status: `Partially implemented`.

Evidence:

- `apps/api/src/caseops_api/api/routes/calendar.py:96-137` sets
  `response_class=PlainTextResponse` but returns `media_type="text/calendar;
  charset=utf-8"`.
- Targeted `tests/test_openapi_quality.py::test_every_api_route_returns_json_or_file`
  failed because OpenAPI declared `text/plain` for `GET /api/calendar/events.ics`.

Impact:

- Generated clients and OpenAPI consumers see the wrong media type.
- The quality gate is currently red.

Required fix:

- Make OpenAPI declare `text/calendar` for the ICS route.
- Assert the actual response header and OpenAPI schema agree.
- Keep acceptable non-JSON media types explicit and narrow.

Acceptance:

- `tests/test_openapi_quality.py` passes.
- Generated TypeScript API types are regenerated if schema output changes.

### P0-004 SendGrid Webhook Signature Verification Fails Open

Status: `Partially implemented`.

Evidence:

- `apps/api/src/caseops_api/api/routes/notifications.py:101-105` returns `True`
  when `CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY` is missing.
- `apps/api/src/caseops_api/api/routes/notifications.py:111-116` returns `True`
  if `cryptography` is unavailable.

Impact:

- In a production-like environment, an unsigned or unverifiable SendGrid event
  webhook can be accepted if configuration or dependency packaging is wrong.
- Webhooks are CSRF-exempt by design, so provider signature checks must be
  fail-closed outside local development.

Required fix:

- Permit unsigned SendGrid webhooks only in explicit local/test modes.
- Fail closed with 401/503 in staging/production when public key is absent,
  invalid, or crypto support is unavailable.
- Add `cryptography` as an explicit backend dependency or remove the optional
  import failure path.
- Add tests for missing key in local, missing key in production, invalid
  signature, valid signature, stale timestamp if supported, malformed payload,
  and dependency/configuration failure.

Acceptance:

- Production/staging webhook verification cannot silently downgrade to no-op.
- All webhook tests pass under both local/test and production-mode settings.

### P0-005 Billing E2E Skip Hides The Invoice UI Path

Status: `Partially implemented`.

Evidence:

- `tests/e2e/billing-payment.spec.ts:43-46` skips the test when
  `CASEOPS_PINE_LABS_API_KEY` is absent, with the note "invoice-only path still
  exercised by unit tests."

Impact:

- The default E2E run can skip the provider path and the invoice UI path in the
  same body.
- Release sign-off does not prove the billing UI works end to end.

Required fix:

- Split invoice-only E2E from Pine Labs payment-link/provider E2E.
- Keep provider E2E optional locally but mandatory in UAT/release sign-off with
  sandbox credentials.
- Add explicit skip reporting to release evidence.

Acceptance:

- Invoice creation UI is always covered by default E2E.
- Pine Labs sandbox path is covered by a separate provider-gated job.

### P1-001 No Enforced Coverage Thresholds

Status: `Missing`.

Evidence:

- Backend has coverage configuration but no enforced fail-under threshold.
- Frontend has `test:coverage` but no strict CI coverage gate.

Impact:

- Large new surfaces can land with low or no direct tests.
- Current route/page coverage cannot be trusted as exhaustive.

Required fix:

- Add backend coverage thresholds for route, service, security, and DB layers.
- Add frontend coverage thresholds for page components, shared API helpers,
  forms, state/error handling, and critical workflows.
- Use targeted per-area gates before attempting a blunt global threshold.

Acceptance:

- CI fails when a critical route/page/service loses required coverage.

### P1-002 API Route Coverage Is Broad But Not Exhaustive

Status: `Partially implemented`.

Evidence:

- OpenAPI exposes `157` operations.
- Existing tests cover many security and feature paths, but there is no
  generated route-to-test matrix proving every route has positive, negative,
  auth, authz, tenant, audit, validation, pagination, and rate-limit coverage
  where applicable.

Required fix:

- Generate an API coverage ledger from OpenAPI.
- For each route, track positive path, validation failure, 401, 403,
  cross-tenant/resource denial, audit event, pagination, rate limit, and
  idempotency where applicable.

Acceptance:

- A test fails if a new backend route is added without an explicit coverage
  classification and owner.

### P1-003 Frontend Page Coverage Is Not Exhaustive

Status: `Partially implemented`.

Evidence:

- `43` Next `page.tsx` routes exist.
- Direct page tests exist for only `10` routes.
- Large untested pages include:
  - `apps/web/app/law-firms/page.tsx`
  - `apps/web/app/guide/page.tsx`
  - `apps/web/app/app/clients/[id]/page.tsx`
  - `apps/web/app/app/matters/[id]/communications/page.tsx`
  - `apps/web/app/app/matters/[id]/recommendations/page.tsx`
  - `apps/web/app/app/matters/[id]/outside-counsel/page.tsx`
  - `apps/web/app/app/matters/[id]/billing/page.tsx`
  - `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx`
  - `apps/web/app/app/admin/email-templates/page.tsx`
  - `apps/web/app/app/admin/notifications/page.tsx`

Required fix:

- Add a generated page coverage ledger.
- Every shipped route needs unit/component coverage plus at least one E2E route
  smoke or workflow test.
- Large pages must cover loading, empty, success, validation, permission denial,
  provider failure, mobile, and accessibility states.

Acceptance:

- A test fails when a new `page.tsx` is added without declared unit/E2E/a11y
  coverage or an explicit documented exemption.

### P1-004 UI/UX And Accessibility Gates Are Too Narrow

Status: `Partially implemented`.

Evidence:

- `tests/e2e/a11y.spec.ts` and `tests/e2e/mobile-responsive.spec.ts` exist.
- Coverage is not route-wide and does not prove every modal, drawer, toast,
  keyboard path, empty state, and error state.

Required fix:

- Add route-wide axe checks for all app and marketing pages.
- Add keyboard-only tests for forms, menus, modal close behavior, focus traps,
  destructive confirmations, and upload/dropzone controls.
- Add mobile, tablet, and desktop assertions for all core workflows.
- Add assertions that shipped app surfaces do not expose dead CTAs, placeholder
  copy, or misleading "coming soon" states unless explicitly labelled as
  roadmap.

Acceptance:

- UI routes cannot pass with inaccessible controls, broken responsive layouts,
  dead primary CTAs, or unhandled loading/error states.

### P1-005 Security Tooling Is Not Strict Enough

Status: `Missing`.

Required fix:

- Add CI jobs for JavaScript dependency advisories, Python dependency
  advisories, OSV or equivalent transitive vulnerability scan, secret scanning,
  license allow-list, container/image scanning if images are built in CI, and
  static security rules for auth, CSRF, SSRF, path traversal, unsafe redirects,
  crypto, and injection.

Acceptance:

- CI blocks high/critical vulnerabilities unless there is a reviewed, dated,
  owner-assigned exception.

### P1-006 Database Validation And Migration Proof Is Incomplete

Status: `Partially implemented`.

Required fix:

- Add PostgreSQL-backed tests for unique constraints, foreign keys, nullable and
  not-null constraints, check constraints, tenant scoping on tenant-owned
  tables, soft-deletes, cascade/restrict delete behavior, portal grant expiry
  and revocation, team scoping, Alembic upgrade from empty DB, and Alembic
  upgrade from previous release snapshot.

Acceptance:

- SQLite-only behavior cannot be used as proof for production DB correctness.

### P1-007 AI, Retrieval, And Provider Governance Need Route-Wide Gates

Status: `Partially implemented`.

Required fix:

- For every LLM, retrieval, drafting, recommendation, OCR, corpus, and provider
  call, add tests for tenant isolation, capability/role enforcement, rate limit,
  quota enforcement, timeout, provider 4xx/5xx, prompt-injection refusal,
  cross-tenant data leakage, model-run audit persistence, cost/token accounting,
  and log redaction.

Acceptance:

- A new expensive/provider route cannot land without rate-limit, audit, and
  failure-mode tests.

### P1-008 Upload, OCR, And Document Security Need More Abuse Tests

Status: `Partially implemented`.

Required fix:

- Add tests for oversized files, MIME mismatch, magic-byte mismatch, polyglot
  files, password-protected PDFs, corrupt PDFs, excessive page count, archive
  rejection where applicable, malware scan unavailable local/test vs production,
  malware positive, OCR timeout, OCR empty/garbage output, and GCS signed URL
  tenant isolation and expiry.

Acceptance:

- Production upload handling fails closed when scanner/provider protections are
  unavailable.

### P1-009 Observability, Audit, Backup, And Restore Are Not Release-Proven

Status: `Partially implemented`.

Required fix:

- Add proof for JSON log shape, trace/span correlation, audit event creation for
  all governance mutations, audit export integrity and permissions, alerting for
  webhook/provider failure, backup creation, restore drill from backup into a
  clean environment, and tenant export where required.

Acceptance:

- Release sign-off includes current evidence for logs, audit, backup, and
  restore, not only runbook text.

### P1-010 OpenAPI And Generated Client Drift Is Not Strictly Enforced

Status: `Partially implemented`.

Evidence:

- `apps/web/lib/api/openapi-types.ts` exists.
- There is no verified clean-diff gate proving generated frontend types match
  the current backend OpenAPI schema on every PR.

Required fix:

- Add CI step to generate OpenAPI/types and fail if the working tree changes.
- Add tests that prevent route media-type drift and undocumented auth behavior.

Acceptance:

- Backend schema changes cannot merge without updated generated clients and
  route contract tests.

## Exhaustive Test Case List

Use this as the mandatory test backlog. IDs are stable and should be referenced
from PRs, commits, and future gap ledgers.

### Release And Verification

| ID | Test | Required Evidence |
| --- | --- | --- |
| QG-REL-001 | `scripts/verify-backend.ps1` runs on Windows from repo root. | Passing command output in PR. |
| QG-REL-002 | `scripts/verify-backend.sh` runs on Linux. | CI or local Linux proof. |
| QG-REL-003 | `scripts/verify-web.ps1 -Quick` runs on Windows. | Passing command output. |
| QG-REL-004 | `npm run build:web` passes. | CI pass. |
| QG-REL-005 | `npm run test:e2e:app` passes with provider-independent tests. | CI pass. |
| QG-REL-006 | Provider-gated E2E runs with Pine Labs sandbox credentials in UAT/release. | Release evidence with skip status. |
| QG-REL-007 | Production smoke proves deployed commit SHA and build time. | Build fingerprint endpoint or page. |
| QG-REL-008 | No canonical verification command depends on global temp/cache locations. | Script and CI proof. |

### Auth, Session, CSRF, RBAC

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-AUTH-001 | Cookie login issues HttpOnly access and refresh cookies. | Backend integration. |
| QG-AUTH-002 | JS cannot read access token and app still works. | Frontend unit/E2E. |
| QG-AUTH-003 | All UI API calls use cookie-aware helpers after migration. | Static test or lint rule. |
| QG-AUTH-004 | No app UI route depends on `getStoredToken()`. | Static test. |
| QG-AUTH-005 | Refresh rotates cookies and rejects stale/invalid refresh. | Backend integration. |
| QG-AUTH-006 | Logout clears cookies and blocks subsequent API access. | Backend plus E2E. |
| QG-AUTH-007 | Cookie-auth mutating request without CSRF header returns 403. | Backend integration. |
| QG-AUTH-008 | Cookie-auth mutating request with mismatched CSRF returns 403. | Backend integration. |
| QG-AUTH-009 | Bearer-auth SDK request remains CSRF-exempt. | Backend integration. |
| QG-AUTH-010 | Portal routes do not gain write endpoints while broadly CSRF-exempt. | Static route policy test. |
| QG-AUTH-011 | Every route declares auth required or explicit public/webhook exemption. | Generated OpenAPI policy test. |
| QG-AUTH-012 | Every protected route has 401 and 403 tests. | Generated route matrix. |
| QG-AUTH-013 | Every capability-protected route has role-denial tests. | Generated route matrix. |
| QG-AUTH-014 | Admin-only pages hide controls for non-admins and backend still denies. | Unit, E2E, backend. |
| QG-AUTH-015 | Tenant switch or stale context cannot leak previous tenant data. | E2E and backend. |

### API Route Contract

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-API-001 | Generate route coverage ledger from all `157` OpenAPI operations. | CI artifact. |
| QG-API-002 | New route without coverage classification fails CI. | Generated test. |
| QG-API-003 | Every route has expected response media type. | OpenAPI quality test. |
| QG-API-004 | Every JSON route has a response model or documented exemption. | OpenAPI quality test. |
| QG-API-005 | Every mutation validates malformed JSON and schema errors. | Route tests. |
| QG-API-006 | Every list route covers pagination max, negative, over-limit, and default. | Route tests. |
| QG-API-007 | Every list route covers search/filter/sort invalid values. | Route tests. |
| QG-API-008 | Every route returns problem-detail style errors consistently. | API contract test. |
| QG-API-009 | Every route forbids cross-tenant resource IDs. | Tenant isolation tests. |
| QG-API-010 | Every destructive mutation is audited. | Audit tests. |
| QG-API-011 | Idempotent/provider callbacks handle duplicate delivery. | Webhook/provider tests. |
| QG-API-012 | Generated TypeScript client is current with OpenAPI. | Clean-diff CI test. |

### Database And Migrations

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-DB-001 | Alembic upgrade from empty Postgres DB. | CI service DB. |
| QG-DB-002 | Alembic upgrade from previous release snapshot. | Migration CI. |
| QG-DB-003 | Unique constraints reject duplicates. | DB tests. |
| QG-DB-004 | FK constraints reject orphan rows. | DB tests. |
| QG-DB-005 | Not-null constraints reject missing required fields. | DB tests. |
| QG-DB-006 | Check constraints reject invalid enums, dates, and amounts. | DB tests. |
| QG-DB-007 | Soft-deleted records stay hidden from normal queries. | Service tests. |
| QG-DB-008 | Cascade/restrict delete behavior is intentional per table. | DB tests. |
| QG-DB-009 | Tenant-owned rows always include tenant/company key. | Static and DB tests. |
| QG-DB-010 | Portal grant expiry, revocation, and scope are enforced. | DB plus API tests. |
| QG-DB-011 | Team membership changes update matter access correctly. | Service plus API tests. |
| QG-DB-012 | Migration rollback policy is documented and tested or explicitly forbidden. | Docs plus CI. |

### Backend Feature Modules

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-MAT-001 | Matter create, read, update, delete/archive happy paths. | API tests. |
| QG-MAT-002 | Matter validation for dates, status, court, client, owner, and duplicate refs. | API/DB tests. |
| QG-MAT-003 | Matter access denies cross-team and cross-tenant users. | API tests. |
| QG-MAT-004 | Matter documents, hearings, tasks, recommendations, billing, communications tabs load independently. | API plus E2E. |
| QG-CLI-001 | Client create/update/KYC validates required fields and duplicates. | API/DB tests. |
| QG-CLI-002 | Client detail cannot expose other tenant matters or contacts. | API/E2E. |
| QG-CON-001 | Contract create/analyze/clause extraction covers success/failure/provider timeout. | API tests. |
| QG-CON-002 | Contract detail UI matches API states. | Unit/E2E. |
| QG-CAL-001 | Calendar JSON feed validates range and max window. | API tests. |
| QG-CAL-002 | Calendar ICS feed has correct `text/calendar` OpenAPI and response header. | API contract test. |
| QG-CAL-003 | Calendar export cannot leak cross-tenant hearings/tasks/deadlines. | API tests. |
| QG-TEAM-001 | Team create/update/member assign/remove covers role and tenant boundaries. | API/E2E. |
| QG-ADMIN-001 | Audit export works with cookie auth and permission denial. | API/unit/E2E. |
| QG-ADMIN-002 | Email templates preview/save/send-test cover invalid template and provider failure. | API/unit/E2E. |
| QG-PORTAL-001 | Portal request-link, verify-link, me, and logout cover invalid, expired, reused token. | API/E2E. |
| QG-PORTAL-002 | Portal future write routes require portal CSRF or narrowed exemption. | Static policy test. |

### AI, Retrieval, Corpus, Drafting

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-AI-001 | Every AI/provider route has tenant-aware rate limiting. | Generated policy test. |
| QG-AI-002 | Every AI/provider route writes model-run/audit metadata. | API/service test. |
| QG-AI-003 | Provider timeout returns stable error and no raw exception leak. | Service/API test. |
| QG-AI-004 | Provider 4xx/5xx returns stable error and is logged safely. | Service/API test. |
| QG-AI-005 | Prompt injection cannot override tenant/document boundaries. | Safety tests. |
| QG-AI-006 | Retrieval never returns cross-tenant citations/snippets. | Integration tests. |
| QG-AI-007 | Drafting generation covers no facts, invalid template, provider unavailable, and success. | API/E2E. |
| QG-AI-008 | Recommendations cover stale data, empty result, low confidence, and accepted/dismissed actions. | API/E2E. |
| QG-AI-009 | Hearing packs cover missing hearing, missing docs, corpus failure, and successful pack. | API/E2E. |
| QG-AI-010 | Corpus ingest covers duplicate document, bad OCR, bad metadata, embedding failure, and rerank fallback. | Service tests. |
| QG-AI-011 | AI logs redact prompts, secrets, PII where required. | Logging tests. |
| QG-AI-012 | Cost/token accounting cannot be negative or missing for completed calls. | DB/service tests. |

### Uploads, Documents, OCR

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-UPL-001 | Valid PDF upload success. | API/E2E. |
| QG-UPL-002 | Oversized upload rejected. | API test. |
| QG-UPL-003 | MIME mismatch rejected. | API test. |
| QG-UPL-004 | Magic-byte mismatch rejected. | API test. |
| QG-UPL-005 | Malware positive rejected. | API/service test. |
| QG-UPL-006 | Scanner unavailable fails closed in production. | API/service test. |
| QG-UPL-007 | Scanner unavailable local/test behavior is explicit. | API/service test. |
| QG-UPL-008 | Corrupt PDF returns stable error. | API/service test. |
| QG-UPL-009 | Password-protected PDF returns stable error. | API/service test. |
| QG-UPL-010 | OCR timeout is handled and retriable where expected. | Service test. |
| QG-UPL-011 | Signed URL access is tenant-scoped and expires. | API/integration test. |
| QG-UPL-012 | Document deletion/archive removes access without orphaning audit. | API/DB test. |

### Payments, Webhooks, Notifications

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-PAY-001 | Invoice-only billing E2E runs without Pine Labs credentials. | E2E. |
| QG-PAY-002 | Pine Labs payment-link success runs with sandbox credentials. | Provider E2E/UAT. |
| QG-PAY-003 | Pine Labs invalid signature rejected. | API test. |
| QG-PAY-004 | Pine Labs duplicate webhook is idempotent. | API/DB test. |
| QG-PAY-005 | Pine Labs provider timeout/failure is user-visible and audited. | API/E2E. |
| QG-NOTIF-001 | SendGrid valid signature accepted. | API test. |
| QG-NOTIF-002 | SendGrid invalid signature rejected. | API test. |
| QG-NOTIF-003 | SendGrid missing key fails closed in production. | API test. |
| QG-NOTIF-004 | SendGrid missing `cryptography` fails closed in production. | API test. |
| QG-NOTIF-005 | Notification retry/backoff and dead-letter behavior is verified. | Service/integration. |
| QG-NOTIF-006 | Email template rendering escapes user-controlled content. | Unit/security test. |
| QG-NOTIF-007 | Calendar/email reminders do not duplicate on retry. | Service test. |

### Frontend Pages And UX

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-UI-001 | Generate page coverage ledger from every `page.tsx`. | CI artifact. |
| QG-UI-002 | New page without unit/E2E/a11y classification fails CI. | Generated test. |
| QG-UI-003 | Every app page covers loading state. | Unit tests. |
| QG-UI-004 | Every app page covers empty state. | Unit tests. |
| QG-UI-005 | Every app page covers API error state. | Unit tests. |
| QG-UI-006 | Every app page covers permission denial. | Unit/E2E. |
| QG-UI-007 | Every form covers required, invalid, boundary, server validation, and success. | Unit/E2E. |
| QG-UI-008 | Every destructive action requires confirmation and handles failure. | Unit/E2E. |
| QG-UI-009 | Every modal/drawer traps focus and closes predictably. | A11y/E2E. |
| QG-UI-010 | Every toast/error message is actionable and not misleading. | Unit/E2E. |
| QG-UI-011 | Every shipped primary CTA performs a real action or is clearly disabled with reason. | E2E/static. |
| QG-UI-012 | Marketing pages have mobile, tablet, desktop layout checks. | E2E. |
| QG-UI-013 | App pages have mobile, tablet, desktop layout checks. | E2E. |
| QG-UI-014 | Keyboard-only navigation covers sidebar, top nav, forms, modals, tables. | E2E. |
| QG-UI-015 | Route-wide axe scan covers app, portal, auth, and marketing pages. | E2E. |

Priority frontend routes to add direct tests first:

- `/app/admin`
- `/app/admin/email-templates`
- `/app/admin/notifications`
- `/app/clients`
- `/app/clients/[id]`
- `/app/matters/[id]/billing`
- `/app/matters/[id]/communications`
- `/app/matters/[id]/drafts/[draftId]`
- `/app/matters/[id]/outside-counsel`
- `/app/matters/[id]/recommendations`
- `/guide`
- `/law-firms`
- `/solo-lawyers`
- `/general-counsels`

### Security And Compliance

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-SEC-001 | Secret scan blocks committed credentials. | CI. |
| QG-SEC-002 | JS dependency vulnerability scan blocks high/critical issues. | CI. |
| QG-SEC-003 | Python dependency vulnerability scan blocks high/critical issues. | CI. |
| QG-SEC-004 | License allow-list blocks disallowed licenses. | CI. |
| QG-SEC-005 | Static security rules cover auth bypass, CSRF, SSRF, path traversal, injection, unsafe redirect. | CI. |
| QG-SEC-006 | CORS only permits approved origins in production. | API/config test. |
| QG-SEC-007 | Security headers present on web and API responses where applicable. | E2E/API test. |
| QG-SEC-008 | Cookies have Secure, HttpOnly where needed, SameSite, path, max-age. | API test. |
| QG-SEC-009 | Rate limits apply to auth, AI, upload, webhook, provider-triggered expensive flows. | API test. |
| QG-SEC-010 | Raw exceptions and stack traces never leak to clients in production mode. | API test. |

### Observability, Docs, Deploy

| ID | Test | Required Coverage |
| --- | --- | --- |
| QG-OPS-001 | JSON log fields are stable and redact sensitive data. | Unit/API test. |
| QG-OPS-002 | Trace IDs propagate from request to logs and provider calls. | Integration test. |
| QG-OPS-003 | Audit events exist for admin, auth, billing, team, document, AI policy mutations. | API/DB tests. |
| QG-OPS-004 | Backup runbook has a current automated backup proof. | Release evidence. |
| QG-OPS-005 | Restore drill succeeds into clean environment. | Release evidence. |
| QG-OPS-006 | Deployment manifests use secret references, not literals. | Static/CI test. |
| QG-OPS-007 | Cloud Run/API auth exposure is intentional and tested. | Deploy smoke. |
| QG-DOC-001 | PRD, gap ledger, OpenAPI, runbooks updated for changed behavior. | PR review checklist. |
| QG-DOC-002 | Docs do not claim complete coverage where tests are skipped or partial. | Docs review. |
| QG-DOC-003 | Every P0/P1 closure links code, tests, and verification output. | Gap ledger. |

## Claude Code Fix Order

Do not parallelize fixes that touch the same files. Suggested order:

1. Fix `scripts/verify-backend.ps1`, then rerun targeted backend verification.
2. Fix admin audit export cookie-auth regression and add tests.
3. Fix calendar ICS OpenAPI media type and regenerate client types if needed.
4. Make SendGrid webhook verification fail closed outside local/test.
5. Split billing invoice E2E from provider-gated Pine Labs E2E.
6. Add generated API route coverage matrix.
7. Add generated frontend page coverage matrix.
8. Add coverage thresholds for critical backend/frontend surfaces.
9. Add dependency, secret, license, and static security CI gates.
10. Expand UI UX, accessibility, mobile, and documentation tests from the matrix.

## Required Verification After Fixes

Run the strongest practical set and paste results into the PR or follow-up
ledger:

```powershell
scripts\verify-backend.ps1
scripts\verify-web.ps1 -Quick
npm run build:web
npm run test:e2e:app
npm run test:e2e:marketing
```

For provider release sign-off, also run:

```powershell
npm run test:e2e:app -- tests/e2e/billing-payment.spec.ts
```

Only count the provider run as release evidence when Pine Labs sandbox
credentials are present and the test is not skipped.

## Do Not Close Until

- All P0 findings above are fixed with tests.
- Canonical verification scripts pass or have a documented environment-specific
  blocker with a stronger alternate proof.
- API route and frontend page coverage ledgers are generated and enforced.
- Security scans are wired into CI.
- Docs and gap ledgers are updated in the same PR as code changes.
- Any skipped provider, deploy, backup, or restore check is explicit, dated,
  owner-assigned, and not presented as a clean `GO`.
