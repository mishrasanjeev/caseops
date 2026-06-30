# Bug Reopen Learnings - Hari 2026-06-30

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari30Jun2026.xlsx`.

## Reported Items

- `bug-001` - High - Matter Management / Matter Creation / eCourt Integration - newly created matters are not automatically linked with the eCourtService third-party for case synchronization.
- `case-reopening audit` - Explicit repeated user concern outside the sheet: explain why these issues keep reopening and prevent shallow fixes.

## Validity

- `bug-001`: Valid. The backend had manual court-sync jobs and a separate case-tracking bookmark/polling subsystem, but the matter creation lifecycle did not register new matters into case tracking.
- The `/app/matters` creation UI was also incomplete for this workflow: it did not collect or submit `case_number` or `cnr_number`, so even a backend-only fix would not have closed the reported browser path.

## Brutal Root Cause

1. I treated earlier eCourt work as complete because manual sync and case-tracking bookmark flows existed independently.
2. That was shallow. The user promise was a lifecycle invariant: a newly created matter with valid case identity should become tracked without a second manual registration step.
3. Prior regressions proved the manual court-sync button, proxy source links, and case-tracking page behavior. None proved the create-matter transaction produced a matter-scoped tracked-case bookmark.
4. I did not audit the UI data-entry path deeply enough. The New Matter dialog had no CNR/case-number fields, which meant API-level matter fields were unreachable from the reported page.
5. The correct fix is not to call the third-party provider synchronously during matter creation. The durable product invariant is: when case tracking is enabled/configured and the matter has a valid CNR or case number, create a tracked-case bookmark tied to that matter; polling/refresh workers then own provider synchronization.

## Permanent Rules

- Integration fixes must verify the lifecycle trigger, not just the standalone integration page or manual button.
- If an API has fields required by a reported browser workflow, the UI must expose and submit those fields or the fix is backend-only and incomplete.
- Third-party side effects must not make core matter creation fail. Auto-linking may be skipped or blocked by provider/support/billing gates, but the matter transaction should still succeed with auditable metadata.
- Case-tracking regressions must assert matter-scoped bookmarks, not only company-level/manual bookmarks.
- Reopened bugs require an adjacent-entry-point sweep: direct create, UI create, intake promotion, import/seed paths, and any background sync path that can produce the same product state.

## Regression Anchors Added

- `apps/api/src/caseops_api/services/case_tracking.py` now has a reusable bookmark upsert path and `auto_link_matter_case_tracking`.
- `apps/api/src/caseops_api/services/matters.py` calls the auto-link helper during direct matter creation and records the result in `matter.created` audit metadata.
- `apps/web/components/app/NewMatterDialog.tsx` exposes `Case number` and `CNR number` and submits them to `POST /api/matters/`.
- `apps/api/tests/test_case_tracking.py` verifies configured-provider auto-link, disabled-provider non-blocking create, and support-matrix-blocked non-blocking create.
- `apps/web/components/app/NewMatterDialog.test.tsx` verifies the UI submits case identity fields.
- `tests/e2e/hari-2026-06-30-bugs.spec.ts` drives `/app/matters`, creates a matter with CNR/case number, and verifies the resulting Case Tracking UI entry.
- `playwright.app.config.ts` registers the June 30 Playwright regression in the normal app suite.

## Product-Wide Sweep

- Direct matter creation is the only production path that currently accepts `case_number`/`cnr_number`; it is now auto-linked.
- Intake promotion creates a lean matter from an intake request and does not collect case identity. It is not eligible for eCourt auto-link until the product adds case identity to the promote dialog.
- Tests, seed scripts, and eval scripts create `Matter` rows directly but are not user workflows; they do not need provider auto-link side effects.
- Manual court-sync jobs remain separate from case tracking. They import cause-list/order artifacts when explicitly run; they are not a substitute for ongoing tracked-case bookmarks.

## Current Verdict

`bug-001` is locally fixed across backend lifecycle, New Matter UI data capture, API regressions, web unit regression, and Playwright app regression. Formal production verdict remains `Inconclusive` until the commit is merged, deployed, and production Playwright passes on the shipped build.

## Local Verification - 2026-06-30

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/services/case_tracking.py apps/api/src/caseops_api/services/matters.py apps/api/tests/test_case_tracking.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_case_tracking.py::test_matter_create_auto_links_case_tracking_bookmark_when_provider_configured apps/api/tests/test_case_tracking.py::test_matter_create_with_case_identity_does_not_fail_when_tracking_disabled apps/api/tests/test_case_tracking.py::test_matter_create_auto_link_is_non_blocking_when_support_matrix_blocks_court` - PASS, 3 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_case_tracking.py` - PASS, 11 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_audit_events.py` - PASS, 6 tests.
- `npm --prefix apps/web test -- components/app/NewMatterDialog.test.tsx` - PASS, 10 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-06-30-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 1 test.
