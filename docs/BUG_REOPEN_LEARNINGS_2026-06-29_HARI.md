# Bug Reopen Learnings - Hari 2026-06-29

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari29Jun2026.xlsx`.

## Reported Items

- `bug-001` - Medium - Research / Context Research - corrupted OCR text still appears in result previews for the cheque dishonour / 35-day notice query.
- `bug-002` - Medium - Research - `Court name contains` filter returns `No authorities matched` for partial court names such as `Madras` even when relevant unfiltered results exist.
- `case-reopening audit` - Explicit repeated user concern outside the sheet: explain why cases/bugs reopen and prevent shallow fixes.

## Validity

- `bug-001`: Valid as a product symptom, but already fixed in current `main` by the June 27 suppression invariant. The required action in this batch is revalidation, not another UI-only masking patch.
- `bug-002`: Valid. The UI promised `Court name contains`, but backend authority search used exact equality in the lexical fallback, exact-name prefilter, pgvector probe, pgvector filtered CTE, and score boost. A user-entered `Madras` could therefore miss `Madras High Court`.
- `case-reopening audit`: Valid as a process and regression-quality issue. This batch reopened because the previous filter fix proved "Search remains enabled and submits filters" but did not verify the deeper backend semantics of the filter label.

## Brutal Root Cause

1. I treated `bug-002` on June 27 as a UI state-machine bug only. That was incomplete. The visible complaint changed from disabled Search to no results because the backend filter contract was still wrong.
2. The test I added proved payload submission, not that the submitted payload behaved correctly against seeded authority data.
3. I did not compare the UI words (`contains`) against the backend predicate (`==`). That is a contract mismatch, and it is exactly the kind of shallow fix that reopens bugs.
4. The product-wide audit must look for semantic equivalents, not just the same component. Here that meant all authority search retrieval branches: exact-name prefilter, pgvector prefilter, fallback scan, and ranking boost.
5. For case/status reopening, June 27 added reload/read-back proof. No new status defect is in this workbook. The recurring reopen pattern here is broader: tests were proving one symptom instead of the full user promise.

## Permanent Rules

- When a UI label says `contains`, backend predicates must be substring/case-insensitive unless the UI explicitly says exact.
- Research filter fixes must cover all retrieval branches: lexical fallback, pgvector/HNSW prefilter, exact-name boost, rerank input, pagination counts, and user-visible cards.
- A Playwright test that only checks request payload is not sufficient when the bug is "valid filter returns no results." Add a backend/API regression with seeded data for the same filter semantics.
- For reopened bugs, preserve prior regressions only if they encode the true product invariant. Do not let a test prove a partial workaround.
- Do not call a batch `Properly fixed` from local evidence alone. Production verdict stays `Inconclusive` until the deployed commit passes production verification.

## Regression Anchors Added

- `apps/api/src/caseops_api/services/authorities.py` now applies case-insensitive substring court filtering in the SQLAlchemy fallback path, exact-name prefilter, pgvector probe, pgvector filtered CTE, and ranking boost.
- `apps/api/tests/test_authorities.py` seeds a `Madras High Court` authority and verifies `court_name: "madras"` returns it for the workbook bail query.
- `apps/web/app/app/research/page.test.tsx` verifies the partial `Madras` court filter is submitted and the returned `Madras High Court` result renders.
- `tests/e2e/hari-2026-06-29-bugs.spec.ts` drives the Research UI with `Madras`, verifies Search remains enabled, submits the partial court filter, and renders a matching `Madras High Court` authority.
- `playwright.app.config.ts` registers the June 29 Playwright regression in the normal app suite.

## Product-Wide Sweep

- The only user-facing Research label found as `Court name contains` was `apps/web/app/app/research/page.tsx`; it is now backed by contains semantics.
- Judgment alert court filters already use `AuthorityDocument.court_name.ilike("%...%")`.
- Matter/cause-list search filters already use substring `ilike` matching.
- Remaining exact `court_name == ...` usages are canonical joins/analytics contexts, not free-text contains filters.

## Current Verdict

`bug-001` is already fixed in current `main` and was revalidated locally. `bug-002` is locally fixed and covered across API, web unit, and Playwright regression tests. Formal production verdict remains `Inconclusive` until this commit is merged, deployed, and production Playwright passes on the shipped build.

## Local Verification - 2026-06-29

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_authority_search_court_name_filter_is_case_insensitive_contains apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 3 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx` - PASS, 6 tests.
- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/authorities.py apps/api/tests/test_authorities.py` - PASS.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-29-bugs.spec.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 5 tests.
