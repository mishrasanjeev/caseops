# CaseOps Critical Review

**Date:** 2026-04-18  
**Reviewer:** Codex  
**Scope:** Entire current repo, with emphasis on shipped functionality, UI/UX, PRD fidelity, and whether the repo contains evidence that outputs are better than expert-lawyer quality.

## Rules Used For This Review

- I reviewed `docs/PRD.md` and `docs/WORK_TO_BE_DONE.md` first.
- I did **not** count items already called out as incomplete in `docs/WORK_TO_BE_DONE.md` as fresh gaps.
- I did count:
  - shipped-surface defects
  - fidelity mismatches
  - misleading UX and product claims
  - places where the code contradicts the product promise

## Verification Performed

- `npm run typecheck:web` - passed
- `npm test` in `apps/web` - passed (`14/14`)
- `npm run build` in `apps/web` - passed
- `uv run pytest` in `apps/api` - passed (`252 passed, 1 skipped`)
- Manual code review across marketing, auth, matters, drafting, recommendations, contracts, outside counsel, admin, evaluation, and capability/auth surfaces

## Findings

### 1. Critical - Recommendation engine can fail open and persist uncited legal advice when retrieval is empty

- **Evidence:** `apps/api/src/caseops_api/services/recommendations.py:342-346`
- **What is wrong:** the refusal gate only triggers when `total_verified_citations == 0 and retrieved`. If retrieval returns no authorities at all, the code can still persist a recommendation with zero verified citations.
- **Why this matters:** the PRD and landing-page promise is citation-grounded output with explicit refusal when evidence is weak. This path does the opposite: it stores a recommendation even when there is no verified authority base.
- **PRD conflict:** `docs/PRD.md` sections 6.1, 9.4, 11, 17.4
- **Impact:** this is the most serious product-trust defect I found in shipped AI behavior.

### 2. High - Recommendation citation verification corrupts option-level evidence when multiple options cite the same authority

- **Evidence:** `apps/api/src/caseops_api/services/recommendations.py:263-278`
- **What is wrong:** `citation_to_option` is a `dict[str, int]`, so the last option using a citation overwrites earlier ones. If two options cite the same case, verification can assign that case only to the last option and silently strip support from the earlier option.
- **Why this matters:** the UI is built around comparing recommendation options by their supporting authorities. This bug can make a well-supported option look unsupported and distort acceptance/rejection decisions.
- **PRD conflict:** `docs/PRD.md` sections 9.7, 11.3, 11.5

### 3. High - Draft review surface hides validator findings from the reviewer

- **Evidence:** `apps/api/src/caseops_api/api/routes/matters.py:566-568`, `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx:284-342`
- **What is wrong:** the backend explicitly says draft validators append findings to the summary so the reviewing partner sees them, but the draft-detail page never renders `currentVersion.summary`.
- **Why this matters:** the backend already detects issues like statute confusion, UUID leakage, and citation coverage gaps. Hiding those findings from the actual reviewer weakens the human-review loop and makes approval less informed than the code intends.
- **PRD conflict:** `docs/PRD.md` sections 9.5, 17.4, 19.6

### 4. High - Audit export is not reliable enough for governance use

- **Evidence:** `apps/web/app/app/admin/page.tsx:23-26,47-50,107-115`, `apps/api/src/caseops_api/api/dependencies.py:87`
- **What is wrong:**
  - The UI converts both `since` and `until` from `<input type="date">` to `YYYY-MM-DDT00:00:00Z`. That makes `until=2026-05-02` mean the very start of May 2, 2026 UTC, excluding the rest of that day.
  - The UI text says audit export is for "Admin or owner only", but the actual capability table grants `audit:export` only to `owner`.
- **Why this matters:** audit export is the governance artifact. If the end-date truncates the selected day, the export is incomplete; if the role promise is wrong, admins are told they can do something the backend forbids.
- **PRD conflict:** `docs/PRD.md` sections 17.2, 18.3, 19.1

### 5. High - Date-only legal fields are rendered in a timezone-unsafe way and can show the wrong day

- **Evidence:** `apps/web/app/app/page.tsx:209-211`, `apps/web/app/app/matters/page.tsx:23-28`, `apps/web/components/app/MatterHeader.tsx:17-20`, `apps/web/app/app/contracts/page.tsx:23-28`
- **What is wrong:** the UI uses `new Date("YYYY-MM-DD")` on fields that are stored as SQL `Date` values, including `next_hearing_on`, `hearing_on`, `listing_date`, `effective_on`, and `expires_on`.
- **Concrete failure:** in a U.S. timezone such as `America/New_York`, `new Date("2026-05-02").toLocaleDateString(...)` renders as **May 01, 2026**, not May 02, 2026.
- **Why this matters:** off-by-one hearing dates, cause-list dates, and contract dates are not cosmetic defects in a legal product.
- **PRD conflict:** `docs/PRD.md` sections 8.3, 9.6, 19.7

### 6. Medium - Shipped UI and marketing overstate maturity and leak internal engineering artifacts into the product

- **Evidence:** `apps/web/components/marketing/Features.tsx:24-60`, `apps/api/src/caseops_api/schemas/recommendations.py:8`, `apps/web/app/app/page.tsx:66-80`, `apps/web/app/app/contracts/page.tsx:138-164`, `apps/web/app/app/matters/[id]/page.tsx:71,122,158`, `apps/web/components/app/Sidebar.tsx:140-144,181`, `apps/web/components/app/RoadmapStub.tsx:50-55`
- **What is wrong:**
  - Marketing claims recommendation breadth that is not actually modeled in the API today. The site advertises "forum, remedy, authority, next-best action and counsel", while the shipped recommendation schema only supports `forum` and `authority`.
  - Multiple product screens reference internal roadmap sections (`12.1`, `4.2`, `5.3`), `WORK_TO_BE_DONE.md`, and the "legacy console".
  - `RoadmapStub` sends "View work plan" to `https://github.com/`, which is a placeholder, not a real work plan.
- **Why this matters:** for a legal buyer, trust erosion starts long before a model hallucinates. Product copy that sounds enterprise-ready while routing the user through preview badges, internal sprint references, and placeholder links makes the whole system feel less credible.
- **PRD conflict:** `docs/PRD.md` sections 1.4, 2.2, 8, 9

### 7. Medium - Solo practitioner is not a first-class product type despite being treated as a first-class persona

- **Evidence:** `apps/api/src/caseops_api/schemas/companies.py:8`, `tests/e2e/personas.spec.ts:18,115-119`
- **What is wrong:** the company-type schema only allows `law_firm` and `corporate_legal`. The "solo practitioner" persona test works by bootstrapping the solo user as `law_firm`.
- **Why this matters:** the PRD calls out a distinct solo workflow and home variant. Without a first-class `solo` type, the product cannot cleanly support solo-specific defaults, onboarding, analytics, entitlements, or UX branching.
- **PRD conflict:** `docs/PRD.md` sections 4.1.C, 8.3, 9.1

## Overall Assessment

### PRD fidelity

This repo is **not** at 100% fidelity with the PRD, even after excluding all backlog already declared in `docs/WORK_TO_BE_DONE.md`.

The main reason is not only breadth. It is that some shipped surfaces already contradict the PRD's trust model:

- recommendation refusal is fail-open in one no-retrieval path
- evidence attribution is incorrect in a multi-option path
- governance export behavior is misleading
- date rendering is unsafe for legal calendaring
- review surfaces hide reviewer-critical AI findings

### "Better than expert lawyer" claim

I found **no repo evidence** that this claim is currently supportable.

- `apps/api/src/caseops_api/services/evaluation.py:8-17` explicitly says the service does **not** drive a benchmark loop and only stores thin primitives plus small aggregate metrics.
- `apps/api/tests/test_evaluation.py:27-50` uses synthetic cases such as `bail-clean`, `bail-hallucinated-statute`, and `bail-provider-crashed`; it does not compare outputs against expert-lawyer gold standards.
- `apps/api/tests/conftest.py:35-36` forces the test suite onto the mock LLM provider, which is correct for CI but means the passing suite is not evidence of real-model legal superiority.

The strongest defensible statement today is:

> The repo contains meaningful guardrails and a serious founder-stage legal-work skeleton, but it does **not** contain proof that outputs are better than an expert lawyer, and it does **not** yet justify making that claim.

## Bottom Line

The project has real substance, real tests, and real progress. But the current product still has several shipped trust defects that are more important than simple feature breadth.

If I were prioritizing immediately, I would fix these first:

1. recommendation fail-open on empty retrieval
2. recommendation shared-citation attribution bug
3. timezone-unsafe date rendering
4. audit export end-date and role-policy mismatch
5. draft-review surface hiding validator findings
