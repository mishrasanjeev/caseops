# Bug Reopen Learnings - Hari 2026-06-24

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari24Jun2026.xlsx`.

## Reported Item

- `BUG-001` - P1 High - Matters / Add Matters - District Court state dropdown only exposed Delhi, Tamil Nadu, Karnataka, and Maharashtra. Expected all Indian states and usable district/court selection for the selected state.

## Validity

Valid bug. It blocked matter creation for district court matters outside the few states present in the seed catalog.

The source-of-truth check was the eCourts Services case-status state selector, which exposes the official state/UT jurisdiction set used by district court services: https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index. A secondary public cross-check was the district-courts overview at https://en.wikipedia.org/wiki/List_of_district_courts_in_India.

## Brutal Root Cause

1. I treated the forum catalog seed as if it were product truth. It was only a partial seed: a handful of district court entries plus the June 23 Delhi expansion.
2. The June 23 regression closed the visible Delhi gap but encoded the wrong invariant. It proved "all seven Delhi complexes" instead of "District Court must support all Indian jurisdictions and must not block when seed data is incomplete."
3. The frontend selector rendered only states present in `/api/courts/forum-catalog`, so missing seed rows became missing workflow capability.
4. The first local fix almost repeated the same mistake in a different place: New Matter's default-forum `useEffect` reset uncatalogued district fallback selections back to Delhi High Court because the fallback intentionally has no catalog ID.
5. The adjacent edit path would have drifted because no-catalog lower-court matters were reconstructed as generic legacy selections instead of District Court fallback selections.

## Permanent Rules

- Catalog-backed selectors must assert the full user-facing invariant, not just current seed rows.
- If a legal catalog can be incomplete, the workflow must be fail-open with explicit typed metadata rather than blocking the user.
- Any seed-data fix must include a regression for the future-missing-data path.
- Shared selectors require consumer-level tests for every consuming surface, not only the originally reported dialog.
- Defaulting/hydration effects must be audited for fallback selections; a missing catalog ID is not the same as an empty selection.
- District Court regressions must be checked with Playwright through `/app/matters`, not only with component tests.

## Regression Anchors Added

- `apps/web/components/matters/ForumSelector.test.tsx` asserts the complete eCourts state/UT jurisdiction list and the Assam uncatalogued fallback UI.
- `apps/web/components/app/NewMatterDialog.test.tsx` creates a matter for uncatalogued Assam District Court metadata and verifies empty fallback data blocks submission.
- `apps/web/components/matters/MatterForumCard.test.tsx` edits a no-catalog lower-court matter without losing state/district/court metadata.
- `apps/api/tests/test_legalworkspace_forum_selector.py` verifies the API accepts and preserves uncatalogued lower-court state and district metadata.
- `tests/e2e/hari-2026-06-24-bugs.spec.ts` verifies the browser workflow: all jurisdictions are present, Assam fallback appears, district and court names are required, and the matter is created.
- `tests/e2e/hari-2026-06-23-bugs.spec.ts` was updated so the prior Delhi-complex regression remains valid with the new explicit fallback option.

## Current Verdict

`Partially fixed` by strict CaseOps bug protocol: local implementation, unit/API tests, build, and local Playwright verification passed. The remaining blocker to `Properly fixed` is deployed production Playwright verification on the shipped commit.

Local proof captured on 2026-06-24:

- `npm run test:web -- ForumSelector.test.tsx NewMatterDialog.test.tsx MatterForumCard.test.tsx` - PASS, 16 tests.
- `uv --directory apps/api run pytest tests/test_legalworkspace_forum_selector.py` - PASS, 4 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-24-bugs.spec.ts --project app-chromium` - PASS, 1 test.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-23-bugs.spec.ts --project app-chromium` - PASS, 1 test.