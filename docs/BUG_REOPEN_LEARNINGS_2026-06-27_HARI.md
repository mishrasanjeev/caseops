# Bug Reopen Learnings - Hari 2026-06-27

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari27Jun2026.xlsx`.

## Reported Items

- `bug-001` - Medium - Research / Context Research - natural-language cheque dishonour queries show irrelevant or low-quality OCR authorities for Section 138 / Section 142 issues.
- `bug-002` - Medium - Research - Search remains disabled or unresponsive after applying filters in Context or Keyword Research.
- `case-reopening audit` - Explicit user concern outside the sheet: determine why cases are reopening and do not treat status fixes shallowly.

## Validity

- `bug-001`: Valid, and it reopens the June 26 Research fix. The prior local fix ranked readable authorities ahead of bad OCR and hid raw mojibake snippets, but it still allowed a low-quality OCR authority card to occupy result slots when readable results were available.
- `bug-002`: Valid. The Research page tied the React Query key directly to draft filter state and disabled Search while the existing query refetched. Changing filters could therefore auto-fire a stale search and leave the explicit Search button disabled during the workflow the tester was trying to perform.
- `case-reopening audit`: Not present as a workbook row, but valid as a product-risk audit. Backend status normalization already maps legacy `closed` input to `disposed`; the missing proof was a browser reload/read-back regression showing a disposed matter does not come back as active/intake. The UI also used both `Disposed` and `Dispose`, which made status interpretation weaker than it needed to be.

## Brutal Root Cause

1. I previously fixed the Research OCR symptom instead of the Research OCR invariant. The invariant is not "do not print mojibake"; it is "do not surface low-quality OCR authorities when readable authorities satisfy the query."
2. The June 26 regression still expected the bad OCR card to be visible. That test preserved the shallow behavior and would have blocked the correct fix. Regressions must encode the intended product truth, not the implementation compromise from the previous patch.
3. Research filter state was treated as committed search state. Draft controls should not change the active query until the user submits; otherwise every filter edit becomes a hidden search action and the visible Search button becomes a race with background fetching.
4. The case-status concern was under-tested at the durable workflow boundary. Updating a select is not enough; a real reopening bug would show up after server persistence and reload/read-back.
5. Status terminology drift (`Disposed` vs `Dispose`) made it easier for testers and developers to misread what the lifecycle action is doing.
6. Production language must remain strict: local Playwright proof is not production proof. Do not label a bug `Properly fixed` until the deployed commit is verified against production.

## Permanent Rules

- For Research quality bugs, audit ranking, suppression, pagination, and rendering. A UI placeholder is not a fix when the bad authority still appears.
- Do not keep low-quality OCR rows in the first-page candidate set once readable authorities exist for the same query. Keep damaged OCR only as a last resort when no readable match exists.
- Search forms must distinguish draft criteria from committed criteria. Filters should be staged until explicit submit unless the UI intentionally declares live search.
- Reopened-bug regressions must be updated when they encode the old broken behavior.
- Lifecycle/status bugs require reload/read-back Playwright coverage, not just immediate UI mutation assertions.
- Use the strict verdict vocabulary from the bug-fixing skill: `Properly fixed`, `Partially fixed`, `Not fixed`, or `Inconclusive`. Local-only proof cannot be promoted to production `Properly fixed`.

## Regression Anchors Added

- `apps/api/src/caseops_api/services/authorities.py` suppresses low-quality OCR results when readable authority results exist, while preserving damaged OCR as a last-resort fallback.
- `apps/api/tests/test_authorities.py` now verifies the garbled cheque dishonour authority is absent when a readable Section 138 / Section 142 authority exists, and still returned when no readable match exists.
- `apps/web/app/app/research/page.tsx` separates draft filters from committed `SearchCriteria`, so filter edits no longer auto-refetch or disable the Search button before submit.
- `apps/web/app/app/research/page.test.tsx` verifies filter edits remain staged until Search is clicked and garbled OCR result cards are suppressed when readable results exist.
- `tests/e2e/hari-2026-06-27-bugs.spec.ts` verifies the exact workbook cheque query, keyword and contextual filter-submit behavior, and disposed matter persistence after reload.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` was strengthened so the earlier OCR regression now requires suppression of the bad card instead of preserving it.
- `apps/web/app/app/matters/page.tsx` and `apps/web/app/app/matters/page.test.tsx` align the portfolio status label with `Dispose`.

## Current Verdict

Fixed locally after targeted pytest, Vitest, TypeScript, production build, and Playwright runs passed. Formal production verdict remains `Inconclusive` until this commit is deployed and the committed Playwright probe passes against `caseops.ai` with the QA tenant.

Local proof captured on 2026-06-27:

- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_authorities.py::test_contextual_search_prioritizes_readable_authority_over_garbled_ocr apps/api/tests/test_authorities.py::test_contextual_search_uses_garbled_ocr_only_when_no_readable_match_exists` - PASS, 2 tests.
- `npm --prefix apps/web test -- app/app/research/page.test.tsx app/app/matters/page.test.tsx` - PASS, 11 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-27-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 4 tests.
- `npx playwright test --config .tmp/hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-26-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 2 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_gba_law_office_prd.py::test_matter_status_closed_input_normalizes_to_disposed` - PASS, 1 test.
