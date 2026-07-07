# Bug Reopen Learnings - Conflict Checks 2026-07-07

Source workbooks:

- `C:\Users\mishr\Downloads\CaseOps_Aishwarya_07Jul2026.xlsx`
- `C:\Users\mishr\Downloads\CaseOps_Ram07Jul2026.xlsx`

## Reported Items

- `Aishwarya BUG-001` - High - Matter Management / Matter Status - changing a matter from Intake to Active is blocked by mandatory conflict-check validation, with no direct option on the current screen to review or waive.
- `Ram BUG-001` - High/P1 - Matters / Conflict Check - running a conflict check fails with "Could not reach the workspace API. Check your connection and try again."

## Validity

- `Aishwarya BUG-001`: Valid UX/product-completion bug. The backend gate is correct, but the matter edit workflow left the user at a 409 toast instead of showing persistent guidance and a direct route to the Conflict check card.
- `Ram BUG-001`: Valid backend bug. Reproduced on production with the supplied `legal` test account. The browser showed a CORS/network-style failure, but a direct authenticated API POST returned `500 Internal Server Error`.

## Brutal Root Cause

1. I let a backend invariant masquerade as a finished workflow. Blocking Active until conflict clearance is correct, but the reported page must explain the next action and provide a direct path to the review controls.
2. I wrote conflict-check tests that seeded old-style `Matter.client_name` data but did not seed a real `Client` row. Production tenants have real `clients` rows, so the stale `Client.primary_name` reference crashed only in the data shape that mattered.
3. I trusted a happy-path QA tenant too much. The `legal` tenant reproduction exposed the client-table path that the prior regression suite never exercised.
4. I treated the browser "workspace API unreachable" message as a frontend symptom until direct API probing proved the server was returning 500. Network-looking UI errors still require server-path proof.
5. I left stale implementation comments in `ConflictCheckCard` saying intake gating was future work even though the API already enforced it. Stale comments are a warning sign that tests and user flows may be out of sync.

## Permanent Rules

- Conflict-check regressions must create at least one real `Client` row, not only matters with free-text client names.
- Mandatory gates must have two tests: one for the enforcement and one for the user recovery path from the page where the block appears.
- Any browser CORS/network-looking failure on a mutating endpoint must be reproduced with a direct authenticated API request before classifying the bug.
- UI comments that describe implemented gates as future work must be corrected during the fix. Stale comments are product-risk debt.
- Workbook bugs touching status transitions must be covered by API tests, React tests, and a Playwright browser test registered in `playwright.app.config.ts`.

## Fixes Added

- `apps/api/src/caseops_api/services/conflict_checks.py` now scans `Client.name`, the actual model column, and stores string candidate IDs.
- `apps/api/src/caseops_api/services/matters.py` now returns actionable activation-block messages that point users to the Conflict check card.
- `apps/web/app/app/matters/[id]/page.tsx` now keeps conflict-gate activation failures visible inline, shows an Active-status pre-save hint, and provides a Review conflict check button that focuses the card.
- `apps/web/components/matters/ConflictCheckCard.tsx` now documents the real gating behavior, is focusable from the edit form, and tells non-resolver users that a partner/admin must clear, mark conflicted, or waive a pending result.

## Regression Anchors Added

- `apps/api/tests/test_conflict_checks.py::test_run_conflict_check_flags_existing_client_record_as_pending` covers the real `Client.name` scan path that failed in production.
- Existing API gate tests now assert that 409 activation messages include "Conflict check card".
- `apps/web/app/app/matters/[id]/page.test.tsx` covers the inline conflict-gate guidance and Review conflict check button.
- `tests/e2e/hari-2026-07-07-bugs.spec.ts` drives the full local browser path: real client creation, matter creation, UI conflict scan, blocked Active save with guidance, clear check, and successful Active save.
- `playwright.app.config.ts` includes the new Playwright regression in the app suite.

## Local Verification - 2026-07-07

- `apps\api\.venv\Scripts\python.exe -m pytest apps\api\tests\test_conflict_checks.py` - PASS, 20 tests.
- `apps\api\.venv\Scripts\ruff.exe check apps\api\src\caseops_api\services\conflict_checks.py apps\api\src\caseops_api\services\matters.py apps\api\tests\test_conflict_checks.py` - PASS.
- `npm --prefix apps/web test -- app/app/matters/[id]/page.test.tsx` - PASS, 6 tests.
- `npx tsc --noEmit --pretty false --project apps/web/tsconfig.json` - PASS.
- `npm --prefix apps/web run build` - PASS.
- `npx playwright test tests/e2e/hari-2026-07-07-bugs.spec.ts --config playwright.app.config.ts --project app-chromium --reporter=line` with `DEBUG=pw:webserver` - PASS, 1 test.

## Current Verdict

Both July 7 conflict-check rows are valid and fixed locally. Production verification must be repeated after the commit is merged and deployed because the original Ram failure reproduced only on the shipped production API.
