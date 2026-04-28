# CaseOps Bug Verification - Hari Batch II

Source sheet: `C:\Users\mishr\Downloads\CaseOps Bugs list II_Hari21Apr2026.xlsx`

Verification date: 2026-04-21

Rule used for classification:
- `Properly fixed`: the intended workflow now works in-product.
- `Partially fixed`: the raw failure was softened, but the intended workflow still does not fully work.
- `Not properly fixed`: the feature still fails in the product path that the bug reported.

## Verification Summary

Properly fixed:
- `BUG-011`
- `BUG-012`
- `BUG-014`
- `BUG-017`
- `BUG-018`

Partially fixed:
- `BUG-016`
- `BUG-019`

Not properly fixed:
- `BUG-013`
- `BUG-015`

## Evidence Run

Backend regression file:
- Command: `apps/api/.venv/Scripts/python.exe -m pytest -q apps/api/tests/test_hari_ii_regressions.py --basetemp .tmp-pytest-hari -o cache_dir=.tmp-pytest-cache-hari`
- Result: `10 passed`

Focused web unit tests:
- Command: `npm run test --workspace @caseops/web -- app/app/intake/page.test.tsx app/app/research/page.test.tsx app/app/matters/[id]/hearings/page.test.tsx`
- Result: `7 passed`

Playwright note:
- A dedicated file exists at [tests/e2e/hari-ii-bugs.spec.ts](/C:/Users/mishr/caseops/tests/e2e/hari-ii-bugs.spec.ts:48), but the normal app Playwright config at [playwright.app.config.ts](/C:/Users/mishr/caseops/playwright.app.config.ts:21) does not include `hari-ii-bugs.spec.ts` in `testMatch`. So those Hari e2e regressions are present in-repo, but they are not part of the standard `npm run test:e2e:app` execution today.

## Per-Bug Verdict

### BUG-011 - Overview shows unavailable sections
Verdict: `Properly fixed`

Why:
- The matter overview now hides the `Open tasks` card when there are no active tasks, instead of showing an empty broken-looking section. See [apps/web/app/app/matters/[id]/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/page.tsx:124).
- The empty-state actions are now explicit and useful:
  - `Go to court sync` for the court-order area at [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/page.tsx:116)
  - `Schedule hearing` for hearings at [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/page.tsx:173)

Assessment:
- The reported UI problem is fixed in the shipped page code.

### BUG-012 - Recommendations fail with "Refused on purpose"
Verdict: `Properly fixed` for the reported defect

Why:
- The recommendations page no longer hard-codes `Refused on purpose` for every 422. It now surfaces the backend's real actionable detail. See [apps/web/app/app/matters/[id]/recommendations/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/recommendations/page.tsx:93).
- Backend regression coverage exists specifically for this issue in [apps/api/tests/test_hari_ii_regressions.py](/C:/Users/mishr/caseops/apps/api/tests/test_hari_ii_regressions.py:115).
- Additional recommendation copy checks exist in [apps/api/tests/test_recommendations.py](/C:/Users/mishr/caseops/apps/api/tests/test_recommendations.py:182).

Assessment:
- The bug that the user saw, a vague non-actionable refusal, is fixed.
- This does not mean recommendations can never legitimately refuse; it means the user now gets the real reason and next step.

### BUG-013 - No hearing reminders after adding a hearing
Verdict: `Not properly fixed`

Why:
- The current code explicitly states that reminders are still not implemented. See [apps/web/app/app/matters/[id]/hearings/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/hearings/page.tsx:431).
- The UI note says: reminders are not sent yet; users should check back on the page and matter overview.

Assessment:
- This is a mitigation, not a fix.
- The product now warns the user honestly, but reminder delivery is still absent.

### BUG-014 - Run Sync fails with 400 for missing/unsupported adapter
Verdict: `Properly fixed`

Why:
- The hearings page now disables `Run Sync` when the matter has no court or the court has no live adapter, instead of allowing the user to hit a bad API path. See [apps/web/app/app/matters/[id]/hearings/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/hearings/page.tsx:81).
- The disabled-state reason is explicit:
  - no court set: [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/hearings/page.tsx:98)
  - unsupported court list: [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/hearings/page.tsx:101)
- Backend regressions cover:
  - no court set
  - unmapped court
  - supported-court happy path
  - frontend/backend supported-court sync
  These live in [apps/api/tests/test_hari_ii_regressions.py](/C:/Users/mishr/caseops/apps/api/tests/test_hari_ii_regressions.py:41).

Assessment:
- This bug is properly fixed in both UI and backend behavior.

### BUG-015 - Billing Pay Link fails with 503: gateway not configured
Verdict: `Not properly fixed`

Why:
- The backend error message is cleaner and more user-facing now. See [apps/api/src/caseops_api/services/pine_labs.py](/C:/Users/mishr/caseops/apps/api/src/caseops_api/services/pine_labs.py:185).
- But the product still depends on Pine Labs configuration being present. If it is not configured, the feature still fails with 503.
- The billing UI still renders a `Pay link` button whenever the invoice is collectible; it does not hide/disable the action based on gateway readiness. See [apps/web/app/app/matters/[id]/billing/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/billing/page.tsx:202).
- The included e2e billing spec explicitly skips the payment-link part when Pine Labs sandbox keys are not provisioned. See [tests/e2e/billing-payment.spec.ts](/C:/Users/mishr/caseops/tests/e2e/billing-payment.spec.ts:39).

Assessment:
- The message is improved.
- The workflow is not reliably fixed in-product. In an unconfigured environment the user still hits a failing action.

### BUG-016 - Billing Sync fails with 404: no Pine Labs payment attempt found
Verdict: `Partially fixed`

Why:
- The backend no longer throws the confusing raw 404 path. It now returns a 409 with a clear instruction to issue a pay link first. See [apps/api/src/caseops_api/services/payments.py](/C:/Users/mishr/caseops/apps/api/src/caseops_api/services/payments.py:255).
- However, the billing UI still shows the `Sync` button whenever balance is due and the invoice is not void, regardless of whether any pay link exists. See [apps/web/app/app/matters/[id]/billing/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/billing/page.tsx:219).

Assessment:
- The bad backend message is fixed.
- The end-to-end product workflow is not fully fixed because the UI still invites the user into a preventable failure state.

### BUG-017 - Intake promote fails when matter code already exists
Verdict: `Properly fixed`

Why:
- The intake promote flow now detects the backend `already in use` error and offers a one-click suggested next code. See [apps/web/app/app/intake/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/intake/page.tsx:408).
- The suggestion button is rendered inline at [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/intake/page.tsx:454).
- The helper logic is unit-tested in [apps/web/app/app/intake/page.test.tsx](/C:/Users/mishr/caseops/apps/web/app/app/intake/page.test.tsx:54).
- Backend detail format is pinned in [apps/api/tests/test_hari_ii_regressions.py](/C:/Users/mishr/caseops/apps/api/tests/test_hari_ii_regressions.py:423).

Assessment:
- This is properly fixed in the user flow.

### BUG-018 - Research page not working
Verdict: `Properly fixed`

Why:
- The research page now renders the search UI even when corpus stats fail, and surfaces stats failure as a non-blocking banner with retry. See [apps/web/app/app/research/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/research/page.tsx:150).
- The page still exposes the research query input at [page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/research/page.tsx:197).
- Basic render coverage exists in [apps/web/app/app/research/page.test.tsx](/C:/Users/mishr/caseops/apps/web/app/app/research/page.test.tsx:47).

Assessment:
- The route is usable again and no longer looks silently broken if stats fail.

### BUG-019 - Matter-level Outside Counsel module not implemented/usable
Verdict: `Partially fixed`

Why:
- The broken per-matter route now redirects to the workspace-level outside-counsel page instead of 404ing. See [apps/web/app/app/matters/[id]/outside-counsel/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/outside-counsel/page.tsx:7).
- But the file itself explicitly says that a true per-matter outside-counsel surface is still a follow-up item. See [outside-counsel/page.tsx](/C:/Users/mishr/caseops/apps/web/app/app/matters/[id]/outside-counsel/page.tsx:14).

Assessment:
- The dead route is mitigated.
- The matter-level module described by the bug is still not actually implemented.

## Final Call

If the question is "were the exact raw failures softened or reworded?", then most of them were.

If the question is "can users now complete the intended workflows properly in the product?", then the unresolved items are:
- `BUG-013` reminders still do not exist
- `BUG-015` Pay Link still fails when Pine Labs is not configured
- `BUG-016` Sync still remains clickable before a pay link exists
- `BUG-019` matter-level outside-counsel is still not a real feature, only redirected
