# Litigation Strategy & Escalation Planner — Implementation Plan

Branch: `feature/litigation-strategy-escalation-planner`
Date: 2026-05-03
PRD: `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md`

This plan answers the five pre-implementation questions the user
required before any large change is committed, lists files in/out of
scope, and records the test strategy. Phase progress is appended to
`docs/STRATEGY_PLANNER_PROGRESS.md`.

---

## 1. Persistence: reuse Recommendation, with one nullable JSON column

**Decision: Option A** (PRD §10.1) — extend the existing `recommendations`
table with a single nullable `strategy_payload_json TEXT` column,
add `litigation_strategy` as the fifth `RecommendationTypeLiteral`,
and dispatch generation to a dedicated service that produces the
richer structured payload.

Reasons:

- The recommendation pipeline already enforces every guardrail the
  PRD demands — citation verification, `review_required=true`,
  capability gates (`recommendations:generate` / `recommendations:decide`),
  audit (`recommendation.generated`), tenant isolation via
  `_load_matter` + `assert_access`, model-run accounting, and rate
  limiting. Re-implementing those for a parallel `matter_strategies`
  table is duplicative and PRD §16 explicitly recommends starting
  with Option A.
- Strategy still needs ~12 additional structured fields the
  Recommendation schema cannot carry cleanly (forum_sequence,
  recommended_drafts, limitation_flags, required_documents, risks,
  …). One nullable JSON column on the same row carries the payload
  without a parallel persistence model. Pydantic
  `LitigationStrategyPayload` validates the shape on read AND write.
- The decision/approval workflow (`accepted | rejected | edited |
  deferred`) already exists on `RecommendationDecision` and maps
  cleanly to the PRD's lawyer-review requirement. Strategy reuses
  it; PRD §16 calls this out as the v1 path.

Trade-offs accepted:

- Migration footprint is one column (`alembic 20260503_0001`).
- The recommendation `options[]` rows still exist for strategy rows;
  they hold the alternative routes' headline rationale (so the
  existing UI keeps rendering them), with the structured payload
  on top of that for the new Strategy page.
- A future move to dedicated `matter_strategies` tables remains a
  data migration, not a redesign — the structured payload is
  already validated against a stable Pydantic schema.

## 2. Backend files touched

Status legend: M = modified, N = new, ✓ = already in flight on
this branch.

```
apps/api/alembic/versions/20260503_0001_litigation_strategy_payload.py    N ✓
apps/api/src/caseops_api/schemas/litigation_strategy.py                   N ✓
apps/api/src/caseops_api/schemas/recommendations.py                       M ✓ (adds litigation_strategy literal + strategy_payload field)
apps/api/src/caseops_api/db/models.py                                     M ✓ (adds strategy_payload_json column)
apps/api/src/caseops_api/api/routes/recommendations.py                    M ✓ (hydrates strategy_payload on response)
apps/api/src/caseops_api/services/recommendations.py                      M ✓ (dispatch + retrieval-query expansion + SUPPORTED_TYPES)

apps/api/src/caseops_api/services/litigation_strategy.py                  N   (Phase A)
apps/api/src/caseops_api/services/drafting_prompts.py                     M   (Phase B — 11 SC prompt parts)
apps/api/src/caseops_api/services/draft_type_validators.py                M   (Phase B — SC-template validators)
apps/api/src/caseops_api/services/template_recommender.py                 M   (Phase B — SC + escalation packs)
apps/api/src/caseops_api/schemas/drafting_templates.py                    M   (Phase B — 11 enums + facts models + field specs + registry)

apps/api/tests/test_litigation_strategy.py                                N   (Phase E)
apps/api/tests/test_litigation_strategy_recommendations.py                N   (Phase E)
apps/api/tests/test_sc_strategy_templates.py                              N   (Phase E)
apps/api/tests/test_template_recommender.py                               M   (Phase E — SC packs + escalation)
```

Out of scope (per the user's hard rule):

- `apps/api/src/caseops_api/scripts/backfill_corpus_quality.py` — DO NOT TOUCH.
- `apps/api/src/caseops_api/services/corpus_structured.py` — DO NOT TOUCH.

## 3. Frontend files touched

```
apps/web/app/app/matters/[id]/strategy/page.tsx                           N   (Phase C)
apps/web/app/app/matters/[id]/strategy/page.test.tsx                      N   (Phase C tests)
apps/web/components/strategy/StrategyRouteTimeline.tsx                    N   (Phase C)
apps/web/components/strategy/StrategyAlternativeRoutes.tsx                N   (Phase C)
apps/web/components/strategy/StrategyDraftPack.tsx                        N   (Phase C)
apps/web/components/strategy/StrategyLimitationFlags.tsx                  N   (Phase C)
apps/web/components/strategy/StrategyRisksAndMissingFacts.tsx             N   (Phase C)
apps/web/components/strategy/StrategyAuthorities.tsx                      N   (Phase C)
apps/web/components/strategy/StrategyApprovalBar.tsx                      N   (Phase C)

apps/web/components/app/MatterCockpitNav.tsx                              M   (Phase C — adds "Strategy" tab)
apps/web/lib/api/schemas.ts                                               M   (Phase C — extends recommendationType + strategyPayload zod)
apps/web/lib/api/endpoints.ts                                             M   (Phase C — generateStrategy thin wrapper)
apps/web/lib/api/openapi-types.ts                                         M   (Phase E — regenerated from updated FastAPI)
```

## 4. Migration

**Yes — one migration.**

- Version filename: `apps/api/alembic/versions/20260503_0001_litigation_strategy_payload.py`
- Revises: `20260501_0004` (current head on `main`)
- Up: adds `recommendations.strategy_payload_json TEXT NULL`
- Down: drops the column

Already in flight on the branch.

## 5. Test plan

### Phase A (backend strategy support)

`apps/api/tests/test_litigation_strategy.py`
- `test_litigation_strategy_is_supported_recommendation_type`
- `test_strategy_retrieval_query_expansion_includes_escalation_terms`
- `test_strategy_prompt_excludes_outcome_guarantees`
- `test_zero_verified_citations_refuses_strategy`
- `test_verified_citation_strategy_persists_with_review_required`
- `test_strategy_payload_round_trips_through_persistence`
- `test_strategy_includes_current_posture_forum_stage`
- `test_strategy_includes_recommended_draft_pack`
- `test_strategy_lists_missing_facts_when_limitation_dates_unknown`
- `test_assert_no_forbidden_phrases_blocks_perfect_strategy`
- `test_assert_no_forbidden_phrases_blocks_will_be_granted`
- `test_strategy_is_tenant_isolated`

### Phase B (SC + escalation templates)

`apps/api/tests/test_sc_strategy_templates.py`
- For each of the 11 new templates: registry lookup, schema includes
  required fields, pydantic facts model rejects unknown keys, prompt
  registered.
- `test_slp_requires_impugned_order_details`
- `test_review_petition_requires_review_grounds`
- `test_curative_petition_requires_review_dismissal`
- `test_condonation_does_not_invent_delay_days`
- `test_synopsis_preserves_chronology`
- `test_filing_index_lists_missing_documents`

`apps/api/tests/test_template_recommender.py` (extend)
- `test_supreme_court_appellate_recommends_slp_pack`
- `test_supreme_court_writ_recommends_article_32`
- `test_high_court_writ_recommends_writ_and_appeal_routes`
- `test_arbitration_commercial_recommends_section_9_and_appeal`
- `test_tribunal_commercial_recommends_appellate_route`
- `test_unknown_forum_falls_back_safely`

### Phase C (frontend)

`apps/web/app/app/matters/[id]/strategy/page.test.tsx`
- Strategy tab renders for a matter
- Generate button calls `generateRecommendation({type: "litigation_strategy"})`
- Loading state renders
- Strategy payload renders: route timeline, primary route,
  alternatives, draft-pack buttons, missing-facts list, limitation
  flags, risks, authorities, review-required banner, disclaimer
- Refusal state renders when API returns 422
- Empty state renders when no strategy yet
- Approval-only controls hidden when capability missing

### Phase D (security / RBAC / audit)

Cross-cutting tests asserted in Phase A files (test cases above).

### Phase E (final pass)

- `npm run gen:api-types` — capture line-count delta of
  `apps/web/lib/api/openapi-types.ts`
- `scripts/verify-backend.sh tests/test_litigation_strategy.py
   tests/test_litigation_strategy_recommendations.py
   tests/test_sc_strategy_templates.py
   tests/test_template_recommender.py` — full pass + coverage
- `npm run typecheck` (web)
- `npm run test -- strategy` (vitest)
- `npm run build` (web)
- `rg -i` forbidden-phrase scan over `apps/api/src` and `apps/web` to
  prove product code carries no outcome-guarantee language outside
  the structural test fixture in `schemas/litigation_strategy.py`
  (`FORBIDDEN_OUTCOME_PHRASES`).

---

## Phase sequencing & guardrails

- Phase A runs first; persistence groundwork is already in flight in
  the worktree (5 files staged, 1 migration file, 2 schema files).
- Phase B is independent of Phase A's service body but depends on
  the new draft-template enum entries existing before
  `template_recommender` and `litigation_strategy.py` recommend
  them.
- Phase C cannot be built before Phase A's API response shape is
  stable.
- Phase D guardrails (forbidden-phrase scrub, `assert_access`
  re-check, audit events) are folded into Phases A and C — no
  separate code commit, but covered by tests.
- Phase E (regen openapi-types + final tests + docs + README) is the
  last commit before push + PR.

## What this plan deliberately does NOT do

- No `matter_strategies` / `matter_strategy_routes` /
  `matter_strategy_drafts` tables. Reuses Recommendation per PRD §16.
- No automated court filing, paid database integrations, or
  cross-tenant analytics (PRD §4.2 out-of-scope).
- ~~No `strategy:read` / `strategy:generate` / `strategy:approve`
  capability split — reuses `recommendations:generate` /
  `recommendations:decide`.~~ Resolved in Round-2 P2 #7:
  `strategy:generate` + `strategy:approve` are now distinct
  capabilities, additive on top of `recommendations:*`. See
  `STRATEGY_PLANNER_PROGRESS.md` Round-2 fixes section.
- No PDF/DOCX export of the strategy itself in this PR (PRD §18 Q5
  remains open). The existing draft-export path covers each draft
  generated from the strategy.
- No automatic task creation on approval (PRD §18 Q6 remains open).
- No deploy. No merge.

## Round-2 fixes — citation-verification scope (P1 #4)

The first cut verified citations only on `recommended_route` +
`alternative_routes`. Round-2 extends the verifier to `forum_sequence`,
`limitation_flags`, `risks`, and `next_best_actions`.

Approach picked (per the brief): **mark items as `unverified=True`
rather than drop them.** Failed items keep their narrative content so
the partner-reviewer can still see what to vet, but the
`supporting_citations` list is stripped to canonical verified entries
only and `unverified` flips to `True`. The frontend renders an amber
"Unverified" badge.

Convention by item kind:
- `forum_sequence` + `limitation_flags`: legal claims by definition.
  Default `unverified=True` unless at least one citation survives.
- `risks` + `next_best_actions`: factual when the LLM emits no
  citation (`unverified=False`); legal claim flagged
  `unverified=True` only when the LLM tried to ground a claim and
  every citation failed verification.

The `_StrategyOption` shape on `recommended_route` /
`alternative_routes` keeps its existing semantics — the citation list
gets stripped in place but the narrative is preserved. The new P1 #1
gate adds the per-route refusal: a primary with zero verified
citations is rejected before the payload is built.
