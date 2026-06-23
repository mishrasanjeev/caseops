# Bug Reopen Learnings - Hari 2026-06-23

Source: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari23Jun2026.xlsx`.

## Where I Went Wrong

1. I accepted a seed sample as a complete court catalog. The Delhi District Court list had three entries, and those three matched the UI path well enough that the defect hid in plain sight.
2. I tested the selector shape, not the jurisdiction invariant. Existing tests proved "a District Court option can be selected"; they did not prove "Delhi exposes all seven district court complexes."
3. I let display metadata drift from lawyer language. The dropdown showed district/city fragments instead of the court-complex names lawyers actually recognize, making missing coverage harder to spot.
4. I treated the catalog as static product copy. Court/forum catalogs are legal operating data; partial data blocks matter creation just as surely as a broken POST route.
5. I failed the adjacent-path audit the first time: the same `ForumSelector` powers New Matter and Matter Forum editing, so fixing only the New Matter surface would have reopened the bug.

## Permanent Rules

- Product catalogs that gate workflow completion need completeness invariants in tests, not only example-row tests.
- For court/forum selectors, every supported state or forum family must have at least one explicit count/content regression for high-usage jurisdictions.
- Dropdown labels must use user-recognizable legal names first, with district/city as context.
- A seed-data bug needs a forward migration for already-migrated environments; changing old seed code alone is not a fix.
- Every catalog fix must audit every consumer of the same catalog API and add Playwright coverage for the highest-risk user-visible workflow.

## Regression Anchors Added

- BUG-001: `/api/courts/forum-catalog` returns all seven Delhi district court complexes.
- BUG-001: `ForumSelector` renders all seven Delhi District Court options with court-complex names.
- BUG-001: `NewMatterDialog` can submit a previously missing Delhi District Court entry.
- BUG-001: Playwright opens `/app/matters`, selects District Court > Delhi > Dwarka Courts Complex, and creates the matter.
