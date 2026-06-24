# Bug Reopen Learnings - Hari 2026-06-24

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari24Jun2026.xlsx`.

## Reported Item

- `BUG-001` - P1 High - Matters / Add Matters - District Court state dropdown only exposed Delhi, Tamil Nadu, Karnataka, and Maharashtra. Expected all Indian states and usable district/court selection for the selected state.

## Validity

Valid bug. It blocked matter creation for district court matters outside the few states present in the seed catalog.

The first source-of-truth check was the eCourts Services case-status state selector, which exposes the official state/UT jurisdiction set used by district court services: https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index. The stricter follow-up source was the India.gov.in District Courts Contact Directory: https://www.india.gov.in/directory/contact-directory/district-courts. On 2026-06-24 the directory was scraped into a structured seed with 36 states/UTs, 724 listed rows, and 723 unique active catalog entries after de-duplicating the duplicate Sheikhpura listing in Bihar.

## Brutal Root Cause

1. I treated the forum catalog seed as if it were product truth. It was only a partial seed: a handful of district court entries plus the June 23 Delhi expansion.
2. The June 23 regression closed the visible Delhi gap but encoded the wrong invariant. It proved "all seven Delhi complexes" instead of "District Court must support all Indian jurisdictions and must not block when seed data is incomplete."
3. The frontend selector rendered only states present in `/api/courts/forum-catalog`, so missing seed rows became missing workflow capability.
4. The first local fix almost repeated the same mistake in a different place: New Matter's default-forum `useEffect` reset uncatalogued district fallback selections back to Delhi High Court because the fallback intentionally has no catalog ID.
5. The adjacent edit path would have drifted because no-catalog lower-court matters were reconstructed as generic legacy selections instead of District Court fallback selections.
6. The all-state fallback was still shallow: it let users type missing courts but did not populate the real state/district court mapping. The correct fix needed a source-backed catalog seed, not only a fail-open UI.
7. Playwright caught a second reopen path after the India.gov seed: switching from a catalogued district court to "Other" preserved the catalogued court's district/name, enabling Create Matter without typed fallback metadata. Catalog-to-fallback transitions must clear inherited catalog data; only existing manual fallback/stale metadata may be preserved.
8. `next start` serves the last production build, so frontend Playwright proof after TS edits is invalid unless `npm run build:web` is rerun first.

## Permanent Rules

- Catalog-backed selectors must assert the full user-facing invariant, not just current seed rows.
- If a legal catalog can be incomplete, the workflow must be fail-open with explicit typed metadata rather than blocking the user.
- Any seed-data fix must include a regression for the future-missing-data path.
- Shared selectors require consumer-level tests for every consuming surface, not only the originally reported dialog.
- Defaulting/hydration effects must be audited for fallback selections; a missing catalog ID is not the same as an empty selection.
- District Court regressions must be checked with Playwright through `/app/matters`, not only with component tests.
- When a public government directory exists for a legal catalog, seed the product from that structured source and validate row counts in migration/tests.
- Switching from a catalog entry to an uncatalogued fallback must clear catalog-derived district/court values and re-require manual input.
- Rebuild the production web bundle before any Playwright run that uses `next start`; otherwise stale UI can produce false proof or false failures.

## Regression Anchors Added

- `apps/api/alembic/versions/20260624_0001_seed_india_gov_district_courts.py` seeds the active district court catalog from the scraped India.gov directory and validates the expected 724 scraped rows.
- `apps/api/src/caseops_api/scripts/seed_data/india_gov_district_courts.json` stores the scraped 36-state/UT, 724-row source snapshot.
- `apps/web/components/matters/ForumSelector.test.tsx` asserts the India.gov state/UT jurisdiction list, Assam uncatalogued fallback UI, and that catalog-to-Other clears inherited catalog metadata.
- `apps/web/components/app/NewMatterDialog.test.tsx` creates a matter for uncatalogued Assam District Court metadata and verifies empty fallback data blocks submission.
- `apps/web/components/matters/MatterForumCard.test.tsx` edits no-catalog and stale-catalog lower-court matters without losing state/district/court metadata or resubmitting inactive catalog IDs.
- `apps/api/tests/test_legalworkspace_forum_selector.py` verifies the API exposes 723 active India.gov district court entries and still accepts uncatalogued lower-court state/district metadata.
- `tests/e2e/hari-2026-06-24-bugs.spec.ts` verifies the browser workflow: all India.gov jurisdictions are present, Assam has 34 catalog entries plus fallback, fallback district/court names are required, and the matter is created.
- `tests/e2e/hari-2026-06-23-bugs.spec.ts` verifies the prior Delhi regression against the India.gov Delhi directory entries.

## Current Verdict

`Locally fixed` after the India.gov scrape and fallback-preservation audit. Strictly, this should not be called `Properly fixed` until the new seed migration is merged, CI is green, production is redeployed, and production Playwright verifies the shipped commit.

Local proof captured on 2026-06-24:

- `uv --directory apps/api run ruff check alembic/versions/20260624_0001_seed_india_gov_district_courts.py tests/test_legalworkspace_forum_selector.py` - PASS.
- `uv --directory apps/api run pytest tests/test_legalworkspace_forum_selector.py` - PASS, 4 tests.
- `npm run test:web -- ForumSelector.test.tsx MatterForumCard.test.tsx` - PASS, 9 tests.
- `npm run typecheck:web` - PASS.
- `npm run build:web` - PASS.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-24-bugs.spec.ts --project app-chromium` - PASS, 1 test.
- `npx playwright test --config playwright.app.config.ts tests/e2e/hari-2026-06-23-bugs.spec.ts --project app-chromium` - PASS, 1 test.