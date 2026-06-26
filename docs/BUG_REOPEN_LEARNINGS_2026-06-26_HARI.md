# Bug Reopen Learnings - Hari 2026-06-26

Source workbook: `C:\Users\mishr\Downloads\CaseOps Bugs_Hari26Jun2026.xlsx`.

## Reported Items

- `bug-001` - Medium - Research / Context Research - natural-language cheque dishonour queries show irrelevant or unreadable OCR snippets despite high relevance.
- `bug-002` - Low - Matters / New Matter - Matter Code accepts spaces or invalid special characters and form validation is not enforced consistently.

## Validity

- `bug-001`: Valid. The frontend already had a garbled-snippet placeholder, but that was a symptom mask. The server retrieval path could still rank low-quality OCR chunks highly and page them ahead of readable Section 138 / Section 142 authorities.
- `bug-002`: Valid. New Matter had required-field validation, but `matter_code` did not enforce the same grammar in the UI. Backend schemas allowed underscores and slashes, and adjacent intake promotion could drift from the New Matter form.

## Brutal Root Cause

1. I previously fixed Research at the rendering layer. That prevents raw mojibake from appearing in one component, but it does not stop low-quality OCR documents from winning retrieval or occupying the first page.
2. The Research API had no readability score in the ranker and no route-level suppression pass before pagination. A high lexical/vector match could still be a bad source for a lawyer.
3. The New Matter form treated Matter Code as "length-only" client-side and relied on a looser backend regex. That is not validation; it is an optimistic convention.
4. Adjacent paths were not treated as part of the same bug class. Intake promotion and code-availability share the same product invariant and must enforce the same grammar.
5. Existing tests proved examples, not invariants. The missing invariant was "matter codes are uppercase letters/numbers/hyphens only across every create path" and "Research prefers readable source text when readable matches exist."

## Permanent Rules

- Never close a Research quality bug with only a UI placeholder. Ranking, pagination, and snippet selection must be audited.
- OCR/readability fixes belong in retrieval or route filtering when bad text can affect result order.
- Any identifier validation bug must define one backend grammar and apply it to every create/promote/import/availability path.
- New Matter fixes must audit intake promotion and bulk import because they also create `Matter` rows.
- Playwright coverage must exercise the visible workflow; API/unit tests must cover the underlying invariant.

## Regression Anchors Added

- `apps/api/src/caseops_api/services/retrieval.py` adds server-side OCR readability detection and rank penalties.
- `apps/api/src/caseops_api/services/authorities.py` sends low-quality OCR results behind readable results before pagination.
- `apps/api/src/caseops_api/schemas/matters.py` defines the shared backend Matter Code grammar and normalization.
- `apps/api/src/caseops_api/schemas/intake.py` reuses the same grammar for intake promotion.
- `apps/api/tests/test_authorities.py` verifies readable Section 138 / Section 142 context search outranks a matching garbled OCR authority.
- `apps/api/tests/test_matter_code_validation.py` verifies direct create, availability, and intake promotion reject invalid codes.
- `apps/web/lib/matter-code.ts` centralizes the frontend Matter Code grammar.
- `apps/web/components/app/NewMatterDialog.test.tsx` verifies New Matter blocks invalid matter codes before submit.
- `apps/web/app/app/intake/page.test.tsx` verifies Intake promotion blocks invalid matter codes before availability checks or submit.
- `tests/e2e/hari-2026-06-26-bugs.spec.ts` verifies the Research and New Matter workflows in Playwright.

## Current Verdict

Fixed locally once the targeted pytest, Vitest, and Playwright runs pass. Per the CaseOps bug-fixing skill, do not call either item `Properly fixed` on production until the deployed build identity is proven and the committed Playwright probe passes against `caseops.ai` with valid QA credentials.
