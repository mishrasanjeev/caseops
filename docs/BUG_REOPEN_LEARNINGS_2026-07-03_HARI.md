# Bug Reopen Learnings - Hari 2026-07-03

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari03Jul2026.xlsx`.

## Reported Items

- `BUG-003` - High - Matter Management / Matter Details - created matters cannot be edited after creation.
- `BUG-004` - Medium - Matter Management / Matter Documents - users cannot download multiple matter documents at once.
- `BUG-005` - Medium - Matter Management / Notices - notice uploads lack structured fields for source, subject/about, received date, and reply/response.

## Validity

- `BUG-003`: Valid bug. The API already had a tenant-scoped audited PATCH route, but the matter overview had no edit affordance and the PATCH schema did not allow correcting `matter_code`.
- `BUG-004`: Valid enhancement. Individual attachment download existed, but the product had no selected-document ZIP workflow.
- `BUG-005`: Valid enhancement/bug. A Notices page existed, but it only uploaded a notice-classified attachment. The notice-specific facts were not captured, persisted, or displayed.

## Brutal Root Cause

1. I treated backend capability as product completion. A PATCH route without a visible edit workflow is not a fixed matter-management bug.
2. I under-modeled correction workflows. Leaving `matter_code` immutable forced recreation for a common typo case, exactly the kind of edge that reopens "cannot edit" reports.
3. I mistook generic document metadata for notice management. Notices need durable domain fields, not a label saying `document_type: notice`.
4. I did not close the loop from storage to UI to regression. Bulk download requires a scoped ZIP endpoint, selection UI, browser proof, and cross-tenant denial tests.
5. I allowed shallow UI-only fixes in prior work. These items require DB migration, API schema, services, typed web clients, visible controls, and Playwright coverage.

## Permanent Rules

- A reported workflow is not complete until a user can perform it from the reported page, the backend persists it, and the page visibly reflects the saved state after reload.
- "Can edit" bugs must include every creation-time identity field unless there is an explicit product reason and test proving immutability.
- Domain workflows may use generic storage, but domain facts must be first-class schema fields when users need to search, review, or report on them.
- Multi-file downloads must be tenant-scoped, matter-scoped, selected-order deterministic, and tested for archive contents plus cross-tenant denial.
- Hari workbook regressions must include API tests, React tests, and Playwright tests registered in `playwright.app.config.ts`.

## Regression Anchors Added

- `apps/api/src/caseops_api/schemas/matters.py` and `apps/api/src/caseops_api/services/matters.py` allow audited `matter_code` edits with duplicate-code protection.
- `apps/web/app/app/matters/[id]/page.tsx` exposes a `matters:edit` gated matter edit form on the overview.
- `apps/api/alembic/versions/20260703_0001_notice_metadata_and_bulk_download.py` adds durable notice metadata columns.
- `apps/api/src/caseops_api/api/routes/matters.py` adds selected attachment ZIP download and accepts structured notice upload fields.
- `apps/web/app/app/matters/[id]/documents/page.tsx` adds document selection and Download selected.
- `apps/web/app/app/matters/[id]/notices/page.tsx` adds the notice upload template and displays saved notice facts.
- `apps/api/tests/test_company_profile_and_matters.py` covers matter edit fields, duplicate matter-code rejection, notice metadata round-trip, ZIP contents, and cross-tenant bulk denial.
- `apps/web/app/app/matters/[id]/page.test.tsx`, `documents/page.test.tsx`, and `notices/page.test.tsx` cover the UI affordances.
- `tests/e2e/hari-2026-07-03-bugs.spec.ts` drives the three workflows in Playwright and is registered in `playwright.app.config.ts`.

## Product-Wide Sweep

- The matter edit fix uses the existing audited matter PATCH service instead of creating a parallel editor path.
- The document bulk endpoint reuses existing attachment storage and matter-access checks rather than bypassing download authorization.
- Notice metadata is attached to `MatterAttachment` so Documents, Notices, workspace API, and future reporting read the same source of truth.

## Current Verdict

`BUG-003`, `BUG-004`, and `BUG-005` are implemented locally with migrations and regression tests. Final production verdict must remain pending until the branch is merged, deployed, and the Playwright regression passes against the shipped environment.

## Local Verification - 2026-07-03

- `apps\api\.venv\Scripts\ruff.exe check apps/api/src/caseops_api/api/routes/matters.py apps/api/src/caseops_api/db/models.py apps/api/src/caseops_api/schemas/matters.py apps/api/src/caseops_api/services/matters.py apps/api/alembic/versions/20260703_0001_notice_metadata_and_bulk_download.py apps/api/tests/test_company_profile_and_matters.py` - PASS.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_company_profile_and_matters.py::test_authenticated_user_can_update_a_matter apps/api/tests/test_company_profile_and_matters.py::test_matter_code_update_rejects_duplicate_code apps/api/tests/test_company_profile_and_matters.py::test_notice_upload_persists_structured_notice_metadata apps/api/tests/test_company_profile_and_matters.py::test_selected_matter_attachments_download_as_zip apps/api/tests/test_company_profile_and_matters.py::test_cross_tenant_user_cannot_download_another_company_attachment apps/api/tests/test_migration_order.py` - PASS, 9 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_openapi_quality.py` - PASS, 2 tests.
- `apps\api\.venv\Scripts\pytest.exe apps/api/tests/test_route_coverage_matrix.py::test_every_api_route_is_referenced_by_at_least_one_test` - PASS, 1 test.
- `npm --prefix apps/web test -- "app/app/matters/[id]/page.test.tsx" "app/app/matters/[id]/documents/page.test.tsx" "app/app/matters/[id]/notices/page.test.tsx"` - PASS, 37 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config .tmp\hari26.no-webserver.playwright.config.ts tests/e2e/hari-2026-07-03-bugs.spec.ts --project app-chromium` with manually started local e2e API/web servers - PASS, 1 test.
- Note: `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-07-03-bugs.spec.ts --project app-chromium` also passed the browser test, then hit a Windows web-server teardown timeout. The no-webserver replay above is the clean exit-code evidence.
