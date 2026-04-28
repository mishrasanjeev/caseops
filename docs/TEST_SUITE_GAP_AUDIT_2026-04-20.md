# Test Suite Gap Audit

Date: 2026-04-20
Workspace: `C:\Users\mishr\caseops`
Scope: current working tree, including uncommitted frontend marketing changes already present in the repo during this audit.

## Verdict

The test suite is not complete.

The repository has meaningful automated coverage across all three layers, but it is missing four things required for a credible "complete" claim:

1. Coverage measurement and thresholds.
2. Reliable execution of the Playwright app suite in the current Windows environment.
3. Adequate frontend route/component coverage relative to the size of the UI surface.
4. Better isolation in the backend suite so the full run is stable, not order-dependent.

## Evidence Snapshot

| Layer | Current state | Evidence from this audit |
| --- | --- | --- |
| Backend | Broad but not fully stable | Full pytest run: `382 passed`, `5 failed`, `4 skipped`. The failing module `apps/api/tests/test_session_4_parallel_features.py` then passed in isolation (`15 passed`), which strongly suggests suite-order leakage or environment contamination. |
| Frontend unit/integration | Healthy but thin | Vitest run passed: `13 files`, `46 tests`. |
| Playwright e2e | Defined, but not reliably executable locally | `31` tests in `8` spec files. Full `npm run test:e2e:app` did not start browser execution because `tests/e2e/global-setup.ts` failed while running `uv run ...` against the API venv on Windows. |
| Coverage enforcement | Missing | No `pytest-cov`, no Vitest coverage config, no LCOV/HTML coverage publishing, no minimum thresholds in CI. |

## Inventory Numbers

| Surface | Count |
| --- | --- |
| Backend source Python files under `apps/api/src/caseops_api` | `108` |
| Backend test modules under `apps/api/tests` | `55` |
| Approx backend test cases | `322+` named `def test_...` cases; actual full run observed `391` outcomes including skips/failures |
| Web source TS/TSX files under `apps/web` | `113` |
| Web test files | `13` |
| Web test cases | `46` |
| Next page routes (`apps/web/app/**/page.tsx`) | `30` |
| Page-level tests (`page.test.tsx`) | `1` |
| Component TSX files under `apps/web/components` | `50` |
| Component test files | `8` |
| Playwright spec files | `8` |
| Playwright tests | `31` |

## Gap List

### P0: No coverage metrics or thresholds anywhere

This is the largest structural gap.

- The repo proves "tests can pass", but it does not prove "important code is covered".
- There is no backend line/branch coverage gate.
- There is no frontend statement/branch coverage gate.
- There is no e2e route/workflow coverage matrix.
- CI in `.github/workflows/ci.yml` runs pytest, Vitest, build, and Playwright, but does not collect or enforce coverage percentages.

Why this matters:

- A green build can still leave newly added routes, components, or edge paths untested.
- The current suite size looks respectable, but there is no automated floor stopping silent erosion.

### P0: Playwright is not currently reliable as a release signal on this workstation

The configured app suite exists, but the full run is fragile.

- `npm run test:e2e:app` failed before browser tests began.
- `tests/e2e/global-setup.ts` prepares the DB by calling `uv --directory apps/api run python -c "..."`.
- In this environment that command failed because Windows could not remove a locked API venv executable.
- This means the e2e suite is coupled to local venv mutability, not just app behavior.

Why this matters:

- When the suite cannot start deterministically, it stops being a trustworthy gate.
- A broken setup path hides real browser regressions behind environment noise.

Recommended fix direction:

- Replace the `uv run` setup step in Playwright global setup with a no-sync path that uses the existing virtualenv directly.
- Keep the DB preparation path independent from package syncing.

### P0: Backend full-suite stability is not good enough

The backend suite is broad, but the full run is not isolated enough.

Observed behavior:

- Full run: `382 passed`, `5 failed`, `4 skipped`.
- The failures were reported from `apps/api/tests/test_session_4_parallel_features.py`.
- Re-running that module alone produced `15 passed`.

What that means:

- This is not just a feature bug.
- It is a suite-quality bug: order dependence, cached settings leakage, engine/session leakage, or cross-test environment contamination.

Why this matters:

- A test suite that passes file-by-file but fails in aggregate will produce flaky CI and false confidence.
- The specific failure output included a fallback to the default Postgres DSN (`postgresql+psycopg://caseops:***@127.0.0.1:5432/caseops`) and a `password authentication failed` error, which is consistent with leaked DB configuration or cache state.

Recommended fix direction:

- Audit `get_settings.cache_clear()` and `clear_engine_cache()` usage in tests that mutate env or DB state.
- Identify which earlier test or fixture leaves the session layer pointed at Postgres instead of per-test SQLite.
- Add one CI job that runs the full backend suite with randomized order to expose more leak points early.

### P1: Frontend unit coverage is far too thin for the size of the UI

This is the biggest functional coverage gap.

Facts:

- `30` page routes exist.
- Only `1` page-level test exists: `apps/web/app/app/matters/[id]/documents/page.test.tsx`.
- `50` component files exist.
- Only `8` component test files exist.

This means most frontend behavior is currently protected only by indirect smoke coverage or not protected at all.

#### High-risk untested page routes

These are large or behavior-heavy pages with no direct `page.test.tsx` coverage.

| Route file | Size | Gap |
| --- | --- | --- |
| `apps/web/app/law-firms/page.tsx` | `844` lines | Large marketing route, no direct test, no Playwright route-specific coverage. |
| `apps/web/app/guide/page.tsx` | `777` lines | Large documentation page, no direct test, no navigation/contents assertions. |
| `apps/web/app/app/contracts/[id]/page.tsx` | `736` lines | Contract workspace detail page with uploads, extraction, playbook compare, and redline viewer; no direct unit test and no dedicated e2e workflow. |
| `apps/web/app/app/intake/page.tsx` | `640` lines | Intake queue create/update/promote logic; no direct unit test and no Playwright workflow. |
| `apps/web/app/solo-lawyers/page.tsx` | `410` lines | New marketing persona route, no direct test. |
| `apps/web/app/general-counsels/page.tsx` | `381` lines | New marketing persona route, no direct test. |
| `apps/web/app/app/admin/teams/page.tsx` | `363` lines | Team creation, deletion, and scoping logic; no direct unit test and no e2e. |
| `apps/web/app/app/matters/[id]/hearings/page.tsx` | `249` lines | Court sync trigger, hearing packs, imported orders/cause list; no direct unit test and no dedicated e2e. |

#### App-shell/auth primitives with no direct tests

These are especially important because the browser session layer has already been a real failure point in prior e2e work.

- `apps/web/lib/session.ts`
- `apps/web/lib/use-session.ts`
- `apps/web/components/app/RequireAuth.tsx`
- `apps/web/components/app/Sidebar.tsx`
- `apps/web/components/app/Topbar.tsx`

Why this matters:

- Session storage, redirect handling, sign-out, `next=` preservation, and refresh cadence are foundational behavior.
- Today those paths are mostly validated only indirectly through full-browser flows.

#### Large untested reusable components

| Component file | Size | Gap |
| --- | --- | --- |
| `apps/web/components/marketing/ProductGallery.tsx` | `408` lines | No direct component test. |
| `apps/web/components/marketing/pitch/primitives.tsx` | `274` lines | Shared building blocks for new pitch pages, no direct tests. |
| `apps/web/components/app/HearingPackDialog.tsx` | `255` lines | Critical workflow UI, no direct test. |
| `apps/web/components/marketing/CTA.tsx` | `172` lines | Main landing CTA component, no direct test. |
| `apps/web/components/app/Sidebar.tsx` | `171` lines | Role/capability-driven nav, no direct test. |
| `apps/web/components/marketing/Hero.tsx` | `160` lines | Main marketing hero, no direct test. |
| `apps/web/components/app/CounselRecommendationsCard.tsx` | `119` lines | Business logic UI, no direct test. |
| `apps/web/components/app/Topbar.tsx` | `103` lines | Search + sign-out + session display, no direct test. |

### P1: Playwright covers the spine, not the full product

The e2e suite is a focused smoke/regression suite, not a full workflow suite.

What is covered reasonably well:

- Marketing landing page basics.
- Sign-in input validation.
- Core sign-in to dashboard happy path.
- Matter creation and one document-upload flow.
- Drafting happy path.
- Query error/retry behavior for matters/contracts.
- A small a11y sweep.
- One role-gate check.

What is still missing in Playwright:

- Intake workflow:
  - create request
  - edit triage notes
  - change status/priority
  - promote request into a matter
- Team admin workflow:
  - create team
  - delete team
  - toggle team scoping
  - verify scoped visibility with two users
- Contract detail workflow:
  - upload attachment
  - extract clauses
  - extract obligations
  - install default playbook
  - run playbook comparison
  - open redline viewer on DOCX
- Matter hearings workflow:
  - run court sync
  - assert sync job summary
  - open/generate hearing pack
  - verify imported cause list / order display
- Research workflow:
  - search with filters
  - save authority annotation
  - query-string deep link through topbar search
- Portfolio workflow:
  - verify KPI buckets and idle-matter logic
- Outside counsel workflow:
  - create counsel
  - validate spend/profile rendering after mutation
- Billing/payment workflow:
  - create invoice
  - send invoice
  - generate Pine Labs payment link
  - sync/webhook-driven paid state
- Admin governance workflow:
  - audit export creation/download
  - role/member management changes
- Session lifecycle workflow:
  - refresh token while tab stays open
  - anonymous redirect back to `next=...`
  - sign-out while on deep route

### P1: Playwright environment matrix is too narrow

Current limitations:

- Only one browser project: `app-chromium`.
- No Firefox coverage.
- No WebKit/Safari coverage.
- No mobile viewport project.
- No visual snapshot regression checks.

Why this matters:

- The app has responsive marketing routes and a large UI surface.
- Single-browser smoke coverage is useful, but it is not enough to claim e2e completeness.

### P1: Several backend paths are only partially exercised or skipped locally

This is not a blanket backend problem, but it is a real gap.

Observed gaps:

- `4` backend tests were skipped during the full run.
- `apps/api/tests/test_eval_hnsw_recall.py` explicitly skips three seed-based recall tests on Windows because of SQLite file-lock behavior.
- `apps/api/tests/test_reranker.py` contains a native fastembed integration test that only runs when `CASEOPS_RERANK_RUN_NATIVE=1`.

Why this matters:

- The local audit does not fully exercise recall-benchmark and native reranker paths.
- These are exactly the kinds of retrieval-quality surfaces that tend to drift silently if not exercised in at least one dependable environment.

### P1: Some sizable backend service modules still lack focused tests

Important nuance:

- Many backend features are covered indirectly through route/integration tests.
- That said, some large service modules do not have dedicated, like-named test modules and therefore are harder to reason about in isolation.

Highest-risk examples:

| Service file | Size | Notes |
| --- | --- | --- |
| `apps/api/src/caseops_api/services/corpus_structured.py` | `501` lines | No direct test references found in this audit. This is a large extraction/LLM shaping service and should have focused tests of prompt shaping, coercion, quality validation, and persistence behavior. |
| `apps/api/src/caseops_api/services/document_jobs.py` | `468` lines | Only lightly referenced directly; deserves focused lifecycle/idempotency tests. |
| `apps/api/src/caseops_api/services/matter_access.py` | `442` lines | Access-control logic is high risk and should be defended by direct service-level tests, not only route behavior. |
| `apps/api/src/caseops_api/services/matter_review.py` | `232` lines | Route-level coverage exists, but no dedicated service-level tests were found; ranking/fact extraction/chronology heuristics deserve direct assertions. |
| `apps/api/src/caseops_api/services/contract_review.py` | `140` lines | Behavior-heavy heuristic service; should have focused tests independent of route plumbing. |
| `apps/api/src/caseops_api/services/contract_redline.py` | `138` lines | XML parsing logic is brittle by nature and should have dedicated parser fixtures/tests. |

### P2: New marketing expansion is almost entirely unguarded

The repo now contains a much wider public web surface than the tests reflect.

New/expanded public routes:

- `/law-firms`
- `/general-counsels`
- `/solo-lawyers`
- `/guide`

Current gap:

- `marketing.spec.ts` validates the landing page, FAQ, SEO endpoints, CTA links, and demo form.
- It does not validate these new public routes at all.
- None of those routes have direct unit/page tests either.

Why this matters:

- Marketing pages tend to change frequently.
- They carry SEO metadata, dense layout, sticky navigation, deep anchor linking, and route-specific copy that can regress without touching the current landing-page assertions.

### P2: Several Next special routes and utility surfaces are untested

Examples:

- `apps/web/app/app/error.tsx`
- `apps/web/app/app/loading.tsx`
- `apps/web/app/not-found.tsx`
- `apps/web/app/llms.txt/route.ts`
- `apps/web/app/llms-full.txt/route.ts`
- `apps/web/app/icon.tsx`

These are lower priority than auth/workflow gaps, but they are still part of the shipped surface.

## What Is Covered Well Enough Today

This audit is a gap list, not a claim that nothing exists. Important strengths already present:

- Backend domain coverage is broad across auth, matters, contracts, outside counsel, teams, audits, drafting, recommendations, tenant isolation, security, and webhook protection.
- Vitest coverage is concentrated in the most mutation-heavy dialogs/forms that existed earlier in the project.
- Playwright does cover the app spine, document upload, drafting happy path, query-error recovery, a11y smoke, and a few role-based checks.

## Recommended Next Test Additions

If the goal is "complete enough to trust", the next additions should be done in this order:

1. **DONE (2026-04-20, `38879ea`):** Add coverage tooling and thresholds for pytest and Vitest. *pytest-cov 7.0.0 + `[tool.coverage.*]` config; `@vitest/coverage-v8` + v8 reporter. Baselines: backend 78% lines, web 29% statements. Thresholds intentionally deferred until two weeks of baseline data.*
2. **DONE (2026-04-20, `8d8528c`):** Make Playwright global setup deterministic on Windows by removing the `uv run` dependency from DB setup. *`apiVenvPython()` helper in `tests/e2e/global-setup.ts` resolves `.venv/Scripts/python.exe` directly with `uv run --no-sync` only as fallback.*
3. **DONE (2026-04-20, `8d8528c`):** Fix the backend order-dependent leak so full-suite pytest is stable. *Autouse fixture in `apps/api/tests/conftest.py` clears `get_settings` + engine caches at teardown. Verified full suite `408 passed, 4 skipped` in 6m49s (was 382/5).*
4. **PARTIAL (2026-04-20, `8f3a2d0`):** Add focused tests for:
   - `session.ts` — **DONE** (7 tests)
   - `use-session.ts` — **DONE** (7 tests, refresh-interval lifecycle included)
   - `RequireAuth.tsx` — pending
   - `Sidebar.tsx` — pending
   - `Topbar.tsx` — pending
5. Add page-level tests for:
   - `app/intake/page.tsx`
   - `app/contracts/[id]/page.tsx`
   - `app/admin/teams/page.tsx`
   - `app/matters/[id]/hearings/page.tsx`
   - `app/research/page.tsx`
   - `app/portfolio/page.tsx`
6. Add Playwright specs for:
   - intake
   - teams admin
   - contract detail tabs
   - hearings/court sync
   - research
   - billing/payment
7. **DONE (2026-04-20, `8f3a2d0`):** Add simple route smoke tests for:
   - `/law-firms` — 200 + h1 + canonical + JSON-LD + no console errors
   - `/general-counsels` — 200 + h1 + canonical + JSON-LD + no console errors
   - `/solo-lawyers` — 200 + h1 + canonical + JSON-LD + no console errors
   - `/guide` — 200 + h1 + canonical + JSON-LD + no console errors

---

## Execution Log — 2026-04-20 (evening)

Sequence agreed with user: A1 deploy first, then Q4 OCR quality gate
+ R1/R2 stepwise-drafting templates in parallel. Keep this log updated
as items complete. Legacy checklist above (items 1-7) tracks the Codex
audit; the items below track follow-on work driven by the audit.

### Thread A — Production hygiene (unblock today's value)

- [ ] **A1 — Deploy API + Web to Cloud Run.** 8 commits on `main` not in prod: `8d8528c` (backend leak + Playwright fix), `38879ea` (coverage tooling), `8f3a2d0` (auth-hook tests + segment smoke), `662de6a` (Sprint P3 bench matcher), `8a88bbd` (SC judge DoB/appointment enrichment), `8aa67e2` (BUG-004 + BUG-010), `3d7502c` (Haiku fallback batch), `8d767dc` (Sprint Q5 matter summary). Redeploy both services to Cloud Run `asia-south1`.
- [ ] **A2 — Identify + fix remaining Hari bugs.** 4 of 10 unaddressed (BUG-003, BUG-005, BUG-007 were in the "won't fix / duplicate" bucket per earlier pass). Re-check the xlsx to confirm and close.
- [ ] **A3 — Verify CI green after the three pushes.** GitHub Actions on commits `662de6a`, `8a88bbd`.

### Thread B — Sprint Q4 (OCR quality gate — prevents corpus poisoning)

- [ ] **Q4a** — per-page OCR confidence + length-normalised quality score emitted during extraction.
- [ ] **Q4b** — reject pages with confidence < 0.4 from chunking so OCR garbage never reaches embeddings (lever #4 in `memory/feedback_vector_embedding_pipeline.md`).
- [ ] **Q4c** — unit tests: synthetic high-conf page passes, synthetic low-conf page is rejected, mixed doc keeps only clean pages.

### Thread C — Sprint R1/R2 (stepwise drafting + per-type prompts)

- [ ] **R1** — `apps/api/src/caseops_api/schemas/drafting_templates/` — one Pydantic schema per `DraftType` (Bail, Anticipatory Bail, Divorce, Cheque Bounce, Affidavit, Criminal Complaint, Civil Suit, Property Dispute Notice). Fields: required facts, applicable statutes, procedural posture.
- [ ] **R2** — `apps/api/src/caseops_api/services/drafting_prompts.py` — one specialised system prompt per `DraftType`. Bail enforces BNSS s.483 (not BNS), triple-test, custody-duration; Cheque Bounce enforces s.138 NI Act boilerplate; etc.
- [ ] **R3** — `GET /api/drafting/templates/{draft_type}` returns the form schema. Web builds a React Hook Form + Zod stepper at `app/matters/{id}/drafts/new?type=bail`.
- [ ] **R7** — per-type fixture under `apps/api/tests/fixtures/drafting/{type}.json` — 3 canonical matter seeds per type + golden draft for regression.

## Bottom Line

CaseOps does have a real test suite across backend, frontend, and Playwright.

But it is not complete in the sense you asked for. The most important missing pieces are coverage enforcement, frontend route/component depth, reliable Playwright execution, and backend suite isolation.
