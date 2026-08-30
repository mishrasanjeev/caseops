# Bench-Aware Appeal Drafting Tasklist

Date: 2026-04-24
Status: Queued
Priority: P1 product-scope gap
Owner: Codex

## Verdict

Judge profiling and bench matching exist, but appeal drafting is not yet
bench-aware end to end.

Current repo state:

- Implemented: judge profile backend at `GET /api/courts/judges/{judge_id}`.
- Implemented: matter bench matcher at `GET /api/matters/{matter_id}/bench-match`.
- Implemented: generic drafting pipeline with citation verification, model-run
  audit, draft state machine, and eight specialized draft templates.
- Missing: appeal-specific draft template.
- Missing: service that converts judge or bench history into evidence-backed
  drafting context.
- Missing: injection of judge or bench history into appeal draft generation.
- Missing: UI that lets a lawyer review the bench-history evidence before using
  it in a draft.
- Missing: tests proving the draft is shaped by cited bench history without
  inventing judicial tendencies or favorability claims.

This task is not complete until a lawyer can start an appeal draft from a
matter, see the assigned judge or likely bench, review relevant historical
judgments from that bench, and generate an appeal draft whose grounds,
framing, authorities, and caution notes are grounded in that history.

## PRD Mapping

Journeys:

- `J06` Court, judge, bench, and tribunal intelligence.
- `J07` Drafting studio, template library, and notice factory.
- `J09` Recommendations and legal strategy.

Modules:

- `M05` Court, judge, bench, tribunal intelligence.
- `M06` Drafting, templates, and notice factory.
- `M07` Recommendations and strategy.
- `M04` Research and authority retrieval.

User stories:

- `US-014` Judge profile with recent matters, authorities, and issue patterns.
- `US-015` Bench-aware strategy support in hearing prep and recommendations.
- `US-017` Step-by-step drafting flow that reduces legal drafting errors.
- `US-018` Reviewer sees citations, findings, and version history before
  approval.
- `US-021` Format selection aligns with forum, judge, and issue context where
  evidence supports it.
- `US-027` Recommendations incorporate bench context once data is reliable.

Existing functional tests touched:

- `FT-023` Judge profile page loads recent authorities and matter context.
- `FT-024` Bench-match endpoint returns a scoped match explanation.
- `FT-025` Draft template list route returns available templates.
- `FT-026` Draft stepper preview renders partial draft safely.
- `FT-027` Draft generation persists a new version.
- `FT-029` Draft approve fails closed without verified citations.
- `FT-031` Each draft type generates with the right schema.

New functional tests to add:

- `FT-024A` Bench strategy context endpoint returns cited prior-judgment
  patterns for the same judge or likely bench.
- `FT-031A` Appeal draft generation consumes bench strategy context when
  available and refuses unsupported judge-tendency claims.

## Product Requirement

Build an evidence-backed appeal drafting flow that adapts to the judge or bench
history for the matter.

The product must answer:

- Which court and bench is this appeal likely before?
- Which indexed judgments from that judge or bench are similar on issue,
  statute, posture, or relief?
- What legal tests has that judge or bench emphasized in those judgments?
- Which authorities did that judge or bench rely on?
- What framing risks should the lawyer consider?
- How should the appeal draft present grounds without making unsupported
  predictions about outcome or judicial preference?

The product must not answer:

- Whether the judge is favorable or unfavorable.
- Whether the appeal will win.
- How to manipulate a judge.
- Reputation-based, anecdotal, or uncited claims about a judge.

## Required User Journey

1. User opens a matter that has `court_name`, `forum_level`, `practice_area`,
   and optionally `judge_name`.
2. If the matter lacks a specific judge, the system calls the existing
   bench-match path and shows the likely bench and judge candidates with
   confidence.
3. User starts a new draft and selects `Appeal Memorandum` or
   `Appeal Grounds`.
4. The draft stepper collects appeal-specific facts: impugned order, order
   date, lower forum, limitation posture, appellant, respondent, questions of
   law, grounds, interim relief, delay-condonation need, and record references.
5. The system fetches bench strategy context for the matter.
6. User sees a reviewable "Bench history context" panel before generation.
7. The panel separates high-confidence structured matches from weaker
   freeform bench-name matches.
8. User can generate with bench context or generate without it.
9. The generated draft includes only cited bench-history claims and flags gaps
   in the draft summary.
10. Reviewer can see which context items were used and which authorities were
    cited.

## Backend Scope

### 1. Add Appeal Draft Template

Add a new template type:

- `appeal_memorandum`

Suggested files:

- `apps/api/src/caseops_api/schemas/drafting_templates.py`
- `apps/api/src/caseops_api/services/drafting_prompts.py`
- `apps/api/src/caseops_api/services/draft_validators.py`
- `apps/api/tests/test_draft_type_validators.py`
- `apps/api/tests/fixtures/drafting/appeal_memorandum.json`

Required appeal facts:

- `appellant_name`
- `respondent_name`
- `impugned_order_date`
- `impugned_order_forum`
- `impugned_order_summary`
- `appeal_forum`
- `appeal_type`
- `limitation_last_date`
- `delay_days`
- `delay_condonation_required`
- `questions_of_law`
- `grounds_brief`
- `interim_relief_sought`
- `record_references`
- `court_name`
- `judge_or_bench_name`
- `focus_note`

Validation rules:

- If `delay_condonation_required` is true, draft must include a delay
  condonation section.
- If `interim_relief_sought` is provided, draft must include an interim relief
  prayer.
- Questions of law must not be empty for second appeal, SLP, or substantial
  question flows.
- The draft must not cite an authority that is absent from the retrieved
  authority block.
- The draft must not invent lower-court findings, order dates, or record page
  numbers.

### 2. Add Bench Strategy Context Service

Add service:

- `apps/api/src/caseops_api/services/bench_strategy_context.py`

Core function:

- `build_bench_strategy_context(session, context, matter_id, judge_limit=5,
  authority_limit=12) -> BenchStrategyContext`

The service must:

- Resolve the tenant-scoped matter.
- Use exact `Matter.judge_name` when present.
- Fall back to `suggest_bench_for_matter_id` when no judge is present.
- Match authorities through structured `AuthorityDocument.judges_json` first.
- Use `AuthorityDocument.bench_name` fallback only with explicit confidence
  labels.
- Filter or rerank by same `practice_area`, issue keywords, statute sections,
  forum, and appeal posture.
- Prefer citable authorities with `neutral_citation` or `case_reference`.
- Return transparent evidence, not conclusions.

Suggested response model:

- `matter_id`
- `court`
- `bench_match`
- `judge_candidates`
- `structured_match_coverage_percent`
- `context_quality`
- `similar_authorities`
- `practice_area_patterns`
- `recurring_tests`
- `authorities_frequently_cited`
- `drafting_cautions`
- `unsupported_gaps`

Context quality values:

- `high`: structured judge match, same court, same practice area, 5 or more
  citable authorities.
- `medium`: mixed structured and fallback matches, 2-4 citable authorities.
- `low`: only freeform bench-name matches or fewer than 2 citable authorities.
- `none`: no usable judge or bench history.

### 3. Add API Endpoint

Add route:

- `GET /api/matters/{matter_id}/bench-strategy-context`

Requirements:

- Auth required.
- Matter access required.
- Cross-tenant matter must return 404.
- Endpoint is read-only.
- Response must include confidence and unsupported gaps.
- Response must not include tenant-private data from other tenants.
- Response must not expose raw prompt text or provider errors.

### 4. Integrate With Draft Generation

Update drafting generation so appeal drafts can include bench context.

Suggested file:

- `apps/api/src/caseops_api/services/drafting.py`

Required behavior:

- When `draft.template_type == "appeal_memorandum"`, build bench context.
- Add a `BENCH HISTORY CONTEXT` block to `_build_messages`.
- Include only citable authorities in the context block.
- Clearly label match confidence.
- If context quality is `low` or `none`, the prompt must tell the model to
  avoid bench-specific claims and use normal appeal drafting.
- Persist enough metadata on the draft version or model run to audit whether
  bench context was used.

Prompt hard rules:

- Do not say "this judge prefers", "this bench is favorable", or "this bench
  usually grants".
- Use language like: "In the indexed decisions provided below, the bench
  emphasized..." only when supported by citations.
- Every bench-history observation must cite a supplied authority.
- If a pattern is based on fewer than 3 authorities, label it as limited.
- If structured coverage is low, say so in the draft summary.

### 5. UI Scope

Suggested files:

- `apps/web/app/app/matters/[id]/drafts/new/page.tsx`
- `apps/web/app/app/matters/[id]/drafts/[draftId]/page.tsx`
- `apps/web/app/app/matters/[id]/page.tsx`
- `apps/web/lib/api/endpoints.ts`
- `apps/web/lib/api/openapi-types.ts`

Required UI:

- Add `Appeal Memorandum` to drafting template list.
- Add an appeal-specific stepper.
- Add a "Bench history context" card.
- Show context quality: high, medium, low, none.
- Show judge candidates and why they matched.
- Show similar authorities with citation, date, court, judge/bench match type,
  and issue/practice-area match.
- Let user generate with or without bench context.
- Warn when context is weak.
- Do not display favorability scores.

Required UX copy:

- "Evidence-backed bench context"
- "This is not an outcome prediction."
- "Only indexed, citable judgments are used."
- "Low coverage: the draft will avoid bench-specific claims."

### 6. Corpus And Retrieval Requirements

This feature depends on judge and bench metadata quality.

Required source fields:

- `AuthorityDocument.judges_json`
- `AuthorityDocument.bench_name`
- `AuthorityDocument.court_name`
- `AuthorityDocument.forum_level`
- `AuthorityDocument.decision_date`
- `AuthorityDocument.neutral_citation`
- `AuthorityDocument.case_reference`
- `AuthorityDocument.summary`
- `AuthorityDocumentChunk.sections_cited_json`

Do not block the feature on perfect corpus coverage. Instead:

- Use structured matches when available.
- Label fallback matches.
- Surface coverage percentage.
- Fail soft to normal appeal drafting when evidence is weak.
- Add evaluation fixtures that simulate high, medium, low, and no-context
  corpora.

## Test Plan

### Backend Unit Tests

- `test_appeal_template_schema_requires_core_fields`
- `test_appeal_template_rejects_unknown_fields`
- `test_appeal_validator_requires_delay_condonation_when_delay_present`
- `test_appeal_validator_requires_questions_of_law_for_second_appeal`
- `test_bench_context_prefers_structured_judges_json`
- `test_bench_context_labels_bench_name_fallback`
- `test_bench_context_returns_none_quality_without_authorities`
- `test_bench_context_filters_by_same_practice_area`
- `test_bench_context_prefers_citable_authorities`
- `test_bench_context_deduplicates_structured_and_fallback_matches`

### Backend Route Tests

- Authenticated user can fetch context for own matter.
- Anonymous user gets 401.
- Cross-tenant matter returns 404.
- Matter with explicit judge uses that judge first.
- Matter without judge falls back to bench match.
- Low-evidence response is explicit and safe.
- Endpoint response matches OpenAPI schema.

### Drafting Integration Tests

- Appeal draft includes `BENCH HISTORY CONTEXT` when context is high.
- Appeal draft omits bench-specific claims when context is none.
- Draft summary warns when context quality is low.
- Generated citations are verified against supplied authorities.
- Approval still fails closed without verified citations.
- Model run records whether bench context was used.
- Prompt does not include uncitable UUID-only authorities.

### Security And AI Safety Tests

- Cross-tenant bench context cannot leak matter data.
- Prompt-injection text inside an authority summary cannot override system
  rules.
- Bench context never produces favorability or outcome prediction labels.
- Raw provider errors are not returned.
- Rate limits apply to generation and preview paths.
- Audit rows are written for generation using bench context.

### Frontend Tests

- Appeal template appears in template list.
- Appeal stepper renders required fields.
- Bench context card renders high, medium, low, and none states.
- Generate-with-context and generate-without-context paths are visible.
- Weak context warning is visible and plain-language.
- Judge candidates link to judge profiles.
- Similar authorities render citation/date/match confidence.
- Mobile layout keeps the context card usable without horizontal scroll.

### E2E Tests

- Create matter with court, judge, and appeal facts.
- Open new appeal draft.
- Review bench history context.
- Generate with context.
- Confirm draft version persists.
- Confirm citations and context warning render.
- Confirm approval is blocked if citations are not verified.

## Acceptance Criteria

The feature is implemented only when all of the following are true:

- `appeal_memorandum` template exists in API and UI.
- `GET /api/matters/{matter_id}/bench-strategy-context` exists and is
  tenant-safe.
- Draft generation uses bench context only for appeal drafts.
- Weak or absent context degrades to normal appeal drafting.
- Draft prompt forbids favorability, outcome prediction, and uncited judge
  tendency claims.
- Reviewer can see context quality and authorities used.
- Backend, frontend, and E2E tests cover positive, negative, edge, security,
  and weak-evidence paths.
- OpenAPI types are regenerated and drift gate passes.
- Documentation and PRD queue entries are updated.

## Recommended Implementation Order

1. Add template schema, prompt, validator, fixtures, and tests.
2. Add bench strategy context service with pure unit tests.
3. Add API route and route tests.
4. Integrate context into appeal draft generation.
5. Add UI context card and appeal stepper support.
6. Add E2E and mobile tests.
7. Regenerate OpenAPI types and update audit ledger.

## Development Queue

Queue ID: `BAAD-001`

Recommended placement:

- Start after C-2 review fixes are stable.
- Can run in parallel with Phase C-3 if a separate worker owns only judge,
  drafting, and matter UI files.
- Should not replace current enterprise hardening work. Historical note:
  P1-006 Postgres CI and P1-009 backup/restore were open when this tasklist was
  written; the current strict enterprise ledger now marks both implemented.

Suggested branch name:

- `feature/bench-aware-appeal-drafting`

Suggested commit slices:

- `BAAD-001 template`: appeal template, prompt, validators, fixtures.
- `BAAD-001 context`: bench strategy context service and API.
- `BAAD-001 draft`: drafting integration and audit metadata.
- `BAAD-001 web`: UI and generated OpenAPI client.
- `BAAD-001 tests`: E2E, mobile, security, and doc closure.
