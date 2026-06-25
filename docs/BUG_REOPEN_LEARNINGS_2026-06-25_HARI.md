# Bug Reopen Learnings - Hari 2026-06-25

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari25Jun2026.xlsx`.

## Reported Item

- `BUG-001` - P1 High - Matters / Add Matters - Consumer Forum selection exposed only Delhi, Karnataka, and Maharashtra for SCDRC/DCDRC, and DCDRC district lists were incomplete.

## Validity

Valid bug. The Add Matter workflow was blocked for consumer matters outside the three baseline seed states and for most district consumer commissions inside those states.

The source-of-truth correction is the public e-Jagriti master commission directory exposed by the Government of India e-Jagriti app:

- `https://e-jagriti.gov.in/services/master/master/v2/getAllCommission`
- `https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=<id>`

The 2026-06-25 snapshot contains 36 state/UT jurisdictions, 54 SCDRC/state-bench rows, and 676 DCDRC rows. No state/UT in the snapshot is missing DCDRC rows.

## Brutal Root Cause

1. The June 24 district-court fix addressed the nearest visible catalog, but did not audit every forum selector branch that used the same partial seed table.
2. The original LW-S4 Consumer Forum seed was demo-sized: NCDRC plus three SCDRCs and three DCDRCs. Treating that as product truth repeated the exact seed-as-capability mistake.
3. The frontend rendered only states present in `/api/courts/forum-catalog`, so missing backend seed rows became missing user capability.
4. There was no fail-open DCDRC path. If a future official row is absent or stale, users should be able to create the matter with explicit state/district/forum metadata.
5. API validation was weaker than UI intent for uncatalogued consumer forums; a shallow UI-only fix would have allowed bad tribunal metadata through direct API callers.
6. Prior regressions asserted example rows, not invariants. The right invariant is all official consumer jurisdictions plus complete per-state DCDRC lists.

## Permanent Rules

- Any catalog bug fix must audit every branch of the shared selector, not only the branch named in the report.
- Catalog seed regressions must assert source-backed counts and state coverage.
- Legal forum workflows must fail open with explicit metadata when catalog data can be incomplete.
- Backend validation must enforce the same fallback shape as the UI.
- Stale catalog IDs from replaced seed rows must become editable fallbacks, not dead selections.
- Add Matter bugs require Playwright proof through `/app/matters`; component/API tests are not enough.

## Regression Anchors Added

- `apps/api/src/caseops_api/scripts/seed_data/e_jagriti_consumer_commissions.json` stores the e-Jagriti source snapshot.
- `apps/api/alembic/versions/20260625_0001_seed_e_jagriti_consumer_commissions.py` deactivates the partial Consumer Forum seed and upserts official e-Jagriti SCDRC/DCDRC rows.
- `apps/api/tests/test_legalworkspace_forum_selector.py` asserts 36 consumer jurisdictions, 54 SCDRC/state-bench rows, 676 DCDRC rows, catalogued DCDRC matter creation, and API rejection of incomplete DCDRC fallback metadata.
- `apps/web/components/matters/ForumSelector.test.tsx` asserts all consumer states are selectable and DCDRC fallback clears inherited catalog metadata.
- `apps/web/components/app/NewMatterDialog.test.tsx` covers catalogued and uncatalogued DCDRC matter creation.
- `apps/web/components/matters/MatterForumCard.test.tsx` covers stale inactive consumer catalog IDs and edit-time fallback saves.
- `tests/e2e/hari-2026-06-25-bugs.spec.ts` verifies Add Matter in browser with all consumer states, Rajasthan DCDRC options, catalogued creation, and fallback validation.

## Current Verdict

Fixed locally once tests and Playwright pass against the rebuilt app bundle. Do not mark production fixed until the migration is deployed and the same Playwright flow passes against the shipped environment.
