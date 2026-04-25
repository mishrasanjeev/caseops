# Automated QA And Coverage Audit

Date: 2026-04-25
Verdict: `NO-GO` for eliminating manual testers today
Audience: Claude Code, Codex, engineering, QA

## Scope

This audit verifies the current automated test inventory, route/page coverage
gates, available code coverage evidence, and CI discipline. It is intentionally
stricter than "does CI pass"; the target is whether CaseOps can stop relying on
manual testers for ordinary regression discovery.

Applied skills:

- `.claude/skills/strict-quality-review/SKILL.md`
- `.claude/skills/caseops-prd-execution/SKILL.md`
- `.claude/skills/enterprise-hardening/SKILL.md`

## Executive Verdict

Do not remove manual tester reliance yet.

The repo has meaningful automated coverage:

- Backend has `788` collected pytest cases.
- Backend route/OpenAPI gates pass.
- Critical per-area backend coverage gates pass for 9 security/core modules.
- Frontend has 142 Vitest tests in the coverage run.
- Playwright lists 66 E2E tests across 19 spec files.
- CI now runs backend pytest with coverage, route/page matrices, web typecheck,
  Vitest, build, Playwright app suite, security scans, and OpenAPI drift.

But the automation is not exhaustive enough:

- Fresh full backend coverage did not complete locally within 15 minutes.
- The latest available backend coverage artifact is low overall:
  `41.54%` line coverage and `9.99%` branch coverage.
- Frontend coverage fails: 141/142 tests passed, but
  `NewWorkspaceForm.test.tsx` timed out under coverage.
- 30 of 46 frontend pages still lack sibling `page.test.tsx` files.
- API route coverage still has 16 explicit baseline waivers.
- Coverage gates protect only 9 backend files, not the product surface.
- Postgres-backed DB validation remains a known hardening gap.
- Provider-gated and production-only flows still depend on environment secrets
  or deployed smoke proof.

## Evidence Snapshot

Commands run on 2026-04-25:

| Check | Result | Evidence |
| --- | --- | --- |
| OpenAPI inventory | `146` paths, `172` operations | `create_application().openapi()` |
| Backend route modules | `23` route files | `apps/api/src/caseops_api/api/routes/*.py` |
| Backend pytest modules | `81` modules | `apps/api/tests/test_*.py` |
| Backend pytest collection | `788` tests collected | `python -m pytest --collect-only -q` |
| Route/OpenAPI gates | `5 passed` | `tests/test_route_coverage_matrix.py`, `tests/test_openapi_quality.py` |
| Backend per-area coverage gate | `9/9 passed` | `scripts/coverage_gate.py apps/api/coverage.json` |
| Full backend coverage run | timed out after 904s | no fresh `coverage-audit-2026-04-25.json` produced |
| Existing backend coverage artifact | 130 files, `41.54%` line, `9.99%` branch | `apps/api/coverage.json`, last written 2026-04-24 17:06:43 |
| Frontend pages | `46` `page.tsx` routes | filesystem inventory |
| Frontend sibling page tests | `16` of `46` pages | filesystem inventory with literal-path matching |
| Frontend page coverage matrix | `2 passed` | `npm run test --workspace @caseops/web -- app/__page-coverage-matrix.test.ts` |
| Frontend full coverage | failed | 141 passed, 1 timeout in `NewWorkspaceForm.test.tsx` |
| Playwright list | `66` tests in `19` files | `npx playwright test --list` |
| E2E skip inventory | 1 provider-gated skip | Pine Labs payment-link path skips without `CASEOPS_PINE_LABS_API_KEY` |

Environment caveats:

- `uv --directory apps/api run pytest ...` failed locally because the user UV
  cache under `AppData\Local\uv\cache` was access-denied.
- Sandboxed Vitest failed with Vite/Rolldown `spawn EPERM`; the page matrix
  passed outside the sandbox.
- Pytest needed elevated execution and explicit `--basetemp` because the
  default Windows temp path was access-denied.
- Long-running `caseops-ingest-corpus` Python processes were already active.
  They were not stopped because they are corpus-ingest jobs, not pytest
  leftovers.

## Current Coverage Gaps

### AQ-001 Backend Overall Coverage Is Too Low

Status: `Partially implemented` — area + total ratchet wired
2026-04-25 729b7e1; raising the totals floor remains future work.

Evidence:

- Existing artifact: `apps/api/coverage.json`.
- Totals: `41.54%` line coverage, `9.99%` branch coverage.
- `scripts/coverage_gate.py` now layers three gate kinds on every CI
  run, in addition to the existing per-file gates:
  - `BUCKET_THRESHOLDS` for `api`, `core`, `db`, `schemas`, `services`
    — each with line + (where applicable) branch floors set ~0.5–2 pts
    under the 2026-04-25 baseline.
  - `TOTAL_LINE_MIN = 41.0%` and `TOTAL_BRANCH_MIN = 9.5%`. A
    wholesale coverage collapse fails the gate even if no single file
    crosses its per-file floor.
- CI artifact upload (`api-coverage`) was already wired in
  `.github/workflows/ci.yml`; coverage report is published per PR.

Impact:

- Bucket regressions in `services/` (the largest under-covered area)
  are now detectable in CI. The 25% floor will trip on a meaningful
  drop while the team backfills service-layer tests bucket-by-bucket.
- Total coverage erosion is now caught even when individual security-
  critical files stay green.

Remaining closure work:

- Drive `services/` line coverage past 50% by retiring legacy
  uncovered helpers and adding focused service-layer tests; raise the
  bucket and total floors as that lands.
- Make full backend coverage complete in CI and locally without the
  904-second timeout (test-suite sharding remains an option).

### AQ-002 Frontend Coverage Fails

Status: `Missing` reliable coverage gate

Evidence:

- `npm run test:coverage --workspace @caseops/web` failed.
- Result: 33 test files executed, 141 passed, 1 failed.
- Failing test: `apps/web/app/sign-in/NewWorkspaceForm.test.tsx`, case
  `submits, stores the session, and routes on success`.
- Failure: 5000 ms timeout plus jsdom "navigation to another Document" warning.
- No `apps/web/coverage/coverage-summary.json` was produced.

Impact:

- Web coverage cannot be enforced.
- A single timeout can hide actual coverage regressions.

Required closure:

- Mock navigation deterministically in `NewWorkspaceForm.test.tsx`.
- Raise only the specific test timeout if there is a real async reason.
- Add `npm run test:coverage --workspace @caseops/web` to CI.
- Upload web coverage artifacts.
- Add minimum thresholds for pages, API helpers, forms, state/error handling,
  and critical components.

### AQ-003 Page-Level UI Coverage Is Not Exhaustive

Status: `Partially implemented`

Evidence:

- 46 frontend `page.tsx` routes.
- 16 have sibling `page.test.tsx`.
- 30 lack sibling page tests.
- `apps/web/app/__page-coverage-matrix.test.ts` allows known waivers and only
  blocks new unclassified pages.

Pages still missing sibling page tests:

- `page.tsx`
- `app/page.tsx`
- `app/admin/email-templates/page.tsx`
- `app/admin/notifications/page.tsx`
- `app/clients/page.tsx`
- `app/clients/[id]/page.tsx`
- `app/contracts/page.tsx`
- `app/courts/page.tsx`
- `app/courts/judges/[judge_id]/page.tsx`
- `app/courts/[id]/page.tsx`
- `app/drafting/page.tsx`
- `app/hearings/page.tsx`
- `app/matters/page.tsx`
- `app/matters/[id]/page.tsx`
- `app/matters/[id]/audit/page.tsx`
- `app/matters/[id]/billing/page.tsx`
- `app/matters/[id]/communications/page.tsx`
- `app/matters/[id]/documents/[attachment_id]/view/page.tsx`
- `app/matters/[id]/drafts/page.tsx`
- `app/matters/[id]/drafts/new/page.tsx`
- `app/matters/[id]/drafts/[draftId]/page.tsx`
- `app/matters/[id]/outside-counsel/page.tsx`
- `app/matters/[id]/recommendations/page.tsx`
- `app/outside-counsel/page.tsx`
- `app/recommendations/page.tsx`
- `general-counsels/page.tsx`
- `guide/page.tsx`
- `law-firms/page.tsx`
- `sign-in/page.tsx`
- `solo-lawyers/page.tsx`

Required closure:

- Add page tests for all app pages before removing manual regression passes.
- Marketing pages need at least SEO, CTA, mobile, keyboard, and no-404 checks.
- App pages need loading, empty, success, error, permission-denied, mobile, and
  keyboard checks.
- Page matrix should fail if a waiver points to a page that now has a test, so
  the allow-list shrinks automatically.

### AQ-004 API Route Matrix Is Too Weak

Status: `Partially implemented`

Evidence:

- OpenAPI exposes 172 operations.
- `tests/test_route_coverage_matrix.py` passes, but only proves each route is
  referenced somewhere unless waived.
- 16 backend route waivers remain:

| Route | Required missing test |
| --- | --- |
| `DELETE /api/matters/{matter_id}/access/grants/{grant_id}` | revoke grant plus audit and tenant isolation |
| `DELETE /api/matters/{matter_id}/clients/{client_id}` | unassign client, 404, cross-tenant |
| `DELETE /api/teams/{team_id}/members/{membership_id}` | remove team member, role denial |
| `GET /api/authorities/stats` | corpus stats happy, auth, empty corpus |
| `GET /api/contracts/{contract_id}/attachments/{attachment_id}/redline` | redline fetch, 404, tenant isolation |
| `PATCH /api/outside-counsel/profiles/{counsel_id}` | update profile, authz, validation |
| `POST /api/admin/email-templates/{template_id}/render` | render preview, invalid data, permission |
| `POST /api/ai/contracts/{contract_id}/clauses/extract` | AI clause extract, rate limit, policy, failure |
| `POST /api/ai/contracts/{contract_id}/obligations/extract` | obligations extract, rate limit, failure |
| `POST /api/ai/contracts/{contract_id}/playbook/compare` | playbook compare, policy, failure |
| `POST /api/contracts/{contract_id}/attachments/{attachment_id}/retry` | retry, authz, tenant isolation |
| `POST /api/matters/{matter_id}/clients` | assign client, idempotency, cross-tenant |
| `POST /api/matters/{matter_id}/drafts/{draft_id}/approve` | approve, no verified citations, authz |
| `POST /api/matters/{matter_id}/drafts/{draft_id}/finalize` | finalize, immutable finalized draft |
| `POST /api/matters/{matter_id}/pack` | hearing-pack assemble, no authorities, audit |
| `POST /api/teams/{team_id}/members` | add member, duplicate, role denial |

Required closure:

- Replace route-reference detection with an explicit route-operation ledger.
- For every operation track: happy path, validation, 401, 403, cross-tenant,
  audit, pagination/filter/sort, rate limit, timeout, idempotency.
- CI must fail if any operation lacks required categories and no dated,
  owner-assigned waiver exists.

### AQ-005 Database Validation Is Not Enterprise-Complete

Status: `Missing` for Postgres-backed critical DB validation

Evidence:

- Existing enterprise ledger tracks P1-006 as missing until CI has a Postgres
  service container.
- Current tests lean heavily on SQLite-compatible paths.

Impact:

- Constraint, cascade, index, JSON/JSONB, timestamp, lock, and pgvector behavior
  can differ from production.

Required closure:

- Add Postgres service container to CI.
- Run a dedicated `postgres-validation` pytest marker suite.
- Cover tenant keys, unique constraints, foreign-key cascade/restrict,
  soft-delete filters, migration upgrade/downgrade where supported, pgvector
  indexes, and advisory/row locking if used.

### AQ-006 E2E Coverage Does Not Fully Replace Manual UAT

Status: `Partially implemented`

Evidence:

- `npx playwright test --list` lists 66 tests in 19 files.
- App config has Chromium desktop and Pixel 5 mobile project.
- Pine Labs payment-link path is provider-gated.
- Production smoke exists but is not a substitute for every user journey.

Required closure:

- Every PRD journey must have at least one Playwright happy path and one
  negative/empty/error path.
- UAT/release job must provision provider sandbox secrets and fail when
  provider-gated tests skip.
- Add browser diversity for release: Chromium plus at least WebKit or Firefox
  on the highest-risk customer-facing flows.
- Add visual regression snapshots for complex pages: matter cockpit, drafting,
  contract workspace, portal, billing, court/judge pages.

## Exhaustive Automated Test Case List

Claude must use this list as the minimum automation contract. A route, page, or
feature is not "manual-tester free" until every applicable item is either
automated or explicitly waived with owner, date, expiry, and rationale.

### Backend API Test Cases

- `API-001` Happy path for every operation.
- `API-002` Required-field validation for every create/update/action route.
- `API-003` Type/range/enum validation for every payload and query parameter.
- `API-004` 401 unauthenticated for every protected operation.
- `API-005` 403 wrong role or missing capability for every privileged route.
- `API-006` 404 or equivalent non-leaking response for cross-tenant resources.
- `API-007` Tenant isolation for list, detail, mutation, export, download, and
  async job routes.
- `API-008` Pagination, limit cap, cursor stability, filtering, and sorting for
  every list route.
- `API-009` Audit event written for every governance/security/business mutation.
- `API-010` Rate limit for auth, AI, upload, webhook, export, provider, and
  expensive routes.
- `API-011` Timeout/provider failure response for AI, OCR, email, payment,
  court sync, storage, and virus scan integrations.
- `API-012` Idempotency for webhooks, retries, provider callbacks, invite/send
  flows, and repeated submits.
- `API-013` File upload abuse: size, extension, MIME mismatch, magic bytes,
  malware scanner unavailable, infected payload, empty payload.
- `API-014` Export/download authorization and content type.
- `API-015` OpenAPI response schema and runtime media type match.
- `API-016` Generated TypeScript client has clean diff.

### Database Test Cases

- `DB-001` Alembic upgrade to head on clean Postgres.
- `DB-002` Alembic upgrade on migrated existing Postgres snapshot.
- `DB-003` Critical unique constraints reject duplicates.
- `DB-004` Tenant key is required and enforced on persistent business objects.
- `DB-005` Foreign-key cascade/restrict behavior is proven.
- `DB-006` Soft-deleted rows are excluded from default reads and included only
  when explicitly requested.
- `DB-007` JSON/JSONB fields round-trip real production payload shapes.
- `DB-008` pgvector extension and HNSW indexes exist where required.
- `DB-009` Timestamp/timezone behavior is stable.
- `DB-010` Backup/restore row counts, alembic version, extensions, and indexes
  match.

### Frontend Page Test Cases

- `UI-001` Page renders success state with representative data.
- `UI-002` Loading skeleton/spinner does not expose broken layout.
- `UI-003` Empty state is truthful and has no dead primary CTA.
- `UI-004` API error state is actionable and retry works where applicable.
- `UI-005` 401/403/404 states are visible and non-leaking.
- `UI-006` Create/edit/delete/archive/restore dialogs validate client-side.
- `UI-007` Server validation errors attach to the right field or toast.
- `UI-008` Keyboard navigation works for forms, dialogs, menus, tabs, tables.
- `UI-009` Axe has zero serious/critical violations.
- `UI-010` Mobile 360px, tablet, and desktop layouts have no horizontal scroll.
- `UI-011` Primary CTA performs a real action or is hidden until available.
- `UI-012` Generated API types match actual endpoint payloads.
- `UI-013` Role/capability gating hides or disables unauthorized actions.
- `UI-014` Optimistic UI, if any, rolls back on failure.

### E2E Journey Test Cases

- `E2E-001` Bootstrap workspace and sign in.
- `E2E-002` Create matter, open cockpit, navigate all tabs.
- `E2E-003` Intake request, triage, promote, duplicate-code recovery.
- `E2E-004` Upload document, process/OCR, view, search, annotate.
- `E2E-005` Research query, saved annotation, no-result path.
- `E2E-006` Court directory, court profile, judge profile, bench match.
- `E2E-007` Draft creation, preview, generate, submit, request changes,
  regenerate, approve, finalize, export.
- `E2E-008` Recommendations generate, accept/reject/defer, weak-evidence path.
- `E2E-009` Hearing schedule, reminders, hearing pack, follow-up task.
- `E2E-010` Calendar week/month/day and ICS download.
- `E2E-011` Billing invoice default path and provider payment-link UAT path.
- `E2E-012` Contract upload, clause extraction, obligation extraction,
  playbook compare, redline.
- `E2E-013` Client create/profile/KYC/communication.
- `E2E-014` Teams, matter grants, ethical walls, unauthorized access.
- `E2E-015` Admin audit export, email templates, notifications.
- `E2E-016` Client portal magic link, matter list/detail, comms, hearings, KYC.
- `E2E-017` Outside-counsel portal assignment, work-product upload, invoice,
  time entry.
- `E2E-018` Public marketing/segment pages, SEO, sitemap, robots, demo request.
- `E2E-019` Mobile smoke for dashboard, matter cockpit, dialogs, portal,
  drafting, billing, contracts.

### Security And AI Safety Test Cases

- `SEC-001` Cookie attributes and CSRF double-submit for app and portal.
- `SEC-002` Bearer and cookie auth cannot be confused across app/portal.
- `SEC-003` Suspended membership/session invalidation.
- `SEC-004` Role and capability matrix on every mutating route.
- `SEC-005` Cross-tenant isolation for every resource type.
- `SEC-006` Webhook signature fail-closed outside local/test.
- `SEC-007` Upload scanner fail-closed in production.
- `SEC-008` Secret settings reject placeholders in non-local envs.
- `SEC-009` Dependency advisory, license, and secret scans fail CI.
- `SEC-010` Prompt injection in uploaded docs, authorities, emails, and
  contract text cannot override system rules.
- `SEC-011` AI output refuses weak evidence and cites only supplied sources.
- `SEC-012` AI model policy, model run audit, token/cost accounting.
- `SEC-013` PII/provider payload redaction at rest and in logs.
- `SEC-014` No raw exception leakage to user-visible API errors.

## Claude Fix Order

1. Fix frontend coverage reliability.
   Target: `npm run test:coverage --workspace @caseops/web` passes and uploads
   a coverage artifact in CI.

2. Make full backend coverage finish.
   Target: `pytest --cov=caseops_api` completes under CI timeout, or suite is
   sharded with combined coverage.

3. Expand backend coverage gates.
   Target: add thresholds for routes, high-risk services, AI services, billing,
   contracts, drafting, matters, portal, and upload/worker surfaces.

4. Burn down the 16 API route waivers.
   Target: remove all entries from `ALLOWED_UNTESTED` or convert them into
   expiring waivers with owners.

5. Burn down the 30 frontend page test gaps.
   Target: every app page has a sibling `page.test.tsx`; marketing pages have
   E2E SEO/mobile/CTA coverage at minimum.

6. Add Postgres validation CI.
   Target: service container plus `pytest -m postgres` for constraints,
   migrations, pgvector, and tenant keys.

7. Make provider-gated checks mandatory in release/UAT.
   Target: Pine Labs, SendGrid, storage, OCR, LLM, embedding, and court-sync
   provider tests fail the UAT workflow if skipped.

8. Add PRD journey matrix.
   Target: each `Jxx`, `US-xxx`, and `FT-xxx` has an automated test reference,
   owner, and current status.

9. Add no-manual-tester release gate.
   Target: release cannot be marked `GO` unless backend coverage, web coverage,
   route matrix, page matrix, E2E, security, OpenAPI drift, Postgres validation,
   provider UAT, and prod smoke all pass or have explicit accepted waivers.

## Required Verification Commands

Backend:

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -q tests/test_route_coverage_matrix.py tests/test_openapi_quality.py
.\.venv\Scripts\python.exe -m pytest -q --cov=caseops_api --cov-report=json:coverage.json --cov-report=term
.\.venv\Scripts\python.exe ..\..\scripts\coverage_gate.py coverage.json
```

Frontend:

```powershell
npm run typecheck:web
npm run test:web
npm run test:coverage --workspace @caseops/web
npm run build:web
npm run test --workspace @caseops/web -- app/__page-coverage-matrix.test.ts
```

E2E:

```powershell
npx playwright test --list
npm run test:e2e:app
npm run test:e2e:marketing
```

Security and contract:

```powershell
npm audit --audit-level=high
uv --directory apps/api run ruff check src tests
uv --directory apps/api run python ../../scripts/dump_openapi.py openapi.json
```

## Do Not Close Checklist

Do not tell the founder that manual testers are unnecessary until all are true:

- Full backend coverage completes and passes threshold gates.
- Frontend coverage completes and passes threshold gates.
- API route waiver count is zero or all waivers are expiring and approved.
- Frontend page waiver count is zero or all waivers are expiring and approved.
- Postgres validation suite runs in CI.
- E2E journeys cover all PRD-critical happy, empty, error, authz, and mobile
  states.
- Provider-gated flows run in UAT/release and cannot silently skip.
- Security, OpenAPI drift, and generated-client gates pass.
- Production smoke proves deployed commit identity and critical flows.
- The release artifact records every command, result, skip, and waiver.

