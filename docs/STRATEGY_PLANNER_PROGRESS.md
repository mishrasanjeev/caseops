# Litigation Strategy Planner — Progress Log

Live status of the `feature/litigation-strategy-escalation-planner`
branch. Each phase appends a checkpoint with files touched, tests
added, and any deviation from the plan in
`docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03_IMPLEMENTATION_PLAN.md`.

## Phase 0 — Plan committed (2026-05-03)

- Persistence decision: reuse `recommendations` + nullable
  `strategy_payload_json` (Option A from PRD §10.1).
- Repo scan complete: existing recommendation pipeline owns
  retrieval, citation verification, model-run accounting, audit,
  rate-limit, capability gates, and tenant isolation. Strategy
  rides those rails; only the structured payload is new.

## Phase A — Backend strategy support (2026-05-03)

Files touched:
- `apps/api/alembic/versions/20260503_0001_litigation_strategy_payload.py` (new — adds nullable TEXT column)
- `apps/api/src/caseops_api/db/models.py` (M — `Recommendation.strategy_payload_json` column)
- `apps/api/src/caseops_api/schemas/litigation_strategy.py` (new — `LitigationStrategyPayload` + `assert_no_forbidden_phrases` + `FORBIDDEN_OUTCOME_PHRASES`)
- `apps/api/src/caseops_api/schemas/recommendations.py` (M — `litigation_strategy` literal + `strategy_payload` field)
- `apps/api/src/caseops_api/services/recommendations.py` (M — `SUPPORTED_TYPES` + dispatch + retrieval-query expansion)
- `apps/api/src/caseops_api/services/litigation_strategy.py` (new — full strategy service)
- `apps/api/src/caseops_api/api/routes/recommendations.py` (M — hydrates `strategy_payload` on response)

Guardrails:
- Zero verified citations → 422 + `ModelRun.status='rejected_no_verified_citations'`.
- Forbidden phrase scan post-LLM, pre-persist → 422 + `ModelRun.status='rejected_forbidden_phrase'`.
- `review_required=True` always.
- Tenant + matter access enforced via existing `_load_matter` / `assert_access`.

## Phase B — SC + escalation drafting templates (2026-05-03)

Files touched:
- `apps/api/src/caseops_api/schemas/drafting_templates.py` (M — 11 enum entries + facts models + field specs + registry)
- `apps/api/src/caseops_api/services/drafting_prompts.py` (M — 11 specialised system prompts)
- `apps/api/src/caseops_api/services/template_recommender.py` (M — SC pack + escalation entries on HC writ / appellate / arbitration / tribunal; unknown-forum fallback)

11 new templates: `special_leave_petition`, `supreme_court_appeal`,
`review_petition`, `curative_petition`, `transfer_petition`,
`contempt_petition`, `interim_relief_application`,
`condonation_of_delay`, `exemption_application`,
`synopsis_list_of_dates`, `filing_index_checklist`.

## Phase C — Frontend Strategy tab (2026-05-03)

Files touched:
- `apps/web/app/app/matters/[id]/strategy/page.tsx` (new)
- `apps/web/app/app/matters/[id]/strategy/page.test.tsx` (new — 7 tests)
- `apps/web/components/app/MatterCockpitNav.tsx` (M — adds Strategy tab)
- `apps/web/lib/api/schemas.ts` (M — extends recommendationType + adds `litigationStrategyPayload` zod)
- `apps/web/lib/api/openapi-types.ts` (M — regenerated)
- `apps/web/app/app/matters/[id]/recommendations/page.tsx` (M — adds Strategy label so historical strategy rows render)

UI surfaces:
- Generate / Re-generate button (capability-gated via the existing
  recommendations route)
- Current posture
- Recommended route + alternatives with verified citations
- Forum sequence escalation timeline
- Recommended draft pack with one-click drafts/new deep-link
- Unavailable SC drafts grey out with explanation
- Limitation flags, required documents, missing facts, risks,
  authorities considered, next-best actions, disclaimer
- Persistent error banner with actionable backend copy

## Phase D — Tests (2026-05-03)

Backend:
- `apps/api/tests/test_litigation_strategy.py` (new — 14 tests)
- `apps/api/tests/test_sc_strategy_templates.py` (new — 61 tests)
- `apps/api/tests/test_template_recommender.py` (M — SC pack + unknown-forum fallback)
- `apps/api/tests/test_drafting_templates.py` (M — count: 20 → 31)

Frontend:
- `apps/web/app/app/matters/[id]/strategy/page.test.tsx` (new — 7 tests)

Verification:
- `scripts/verify-backend.sh tests/test_recommendations.py tests/test_litigation_strategy.py tests/test_sc_strategy_templates.py tests/test_template_recommender.py tests/test_drafting_templates.py` — 153 passed.
- `cd apps/web && npm run typecheck` — clean.
- `cd apps/web && npm run test -- strategy` — 10 / 10.
- `cd apps/web && npm run build` — succeeds; `/app/matters/[id]/strategy` route registered.

## Phase E — Documentation (2026-05-03)

Files touched:
- `README.md` (M — Litigation Strategy section + 11 SC templates table)
- `docs/PRD_LITIGATION_STRATEGY_ESCALATION_PLANNER_2026-05-03.md` (already on the branch)
- `docs/STRATEGY_PLANNER_PROGRESS.md` (this file — final phase log)

## Known limitations

- Strategy export (PDF / DOCX) is not in this PR. Each draft generated
  from the strategy keeps the existing per-draft export path.
- Bench-strategy enrichment is read-only; no two-way wiring back into
  bench-strategy yet (that remains a follow-up under MOD-TS-018).

## Round 2 fixes (2026-05-03 — addressing PR #7 review)

User-driven code review of the first cut surfaced 4 P1 + 3 P2 blockers.
All seven are addressed below. Each lands as a separate commit so a
reviewer can map fix → commit one-to-one. Backend test count went from
153 to 173 across the touched modules; frontend strategy tests from
10 to 17.

### P1 #1 — Per-route citation verification on the primary
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Behaviour: if `recommended_route` has zero verified citations the
  strategy is refused with HTTP 422 + `ModelRun.status =
  rejected_primary_route_uncited`, even when an alternative route
  carries a verified citation.
- Test: `test_strategy_refuses_when_primary_route_uncited_even_if_alternative_cited`.

### P1 #2 — SC plausibility / SC template availability lock-step
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Behaviour: `_is_template_available` now allows tribunal matters to
  draft the SC pack (NCLAT/AFT/APTEL → Article 136 SLP). Mirrors the
  forum set in `_assemble_context.sc_route_plausible`.
- Test: `test_sc_plausible_forums_can_draft_the_sc_template_pack`.

### P1 #3 — Partner review completes on accept
- Files: `apps/api/src/caseops_api/services/recommendations.py`,
  `apps/api/tests/test_recommendations.py`,
  `apps/web/app/app/matters/[id]/strategy/page.tsx`,
  `apps/web/app/app/matters/[id]/strategy/page.test.tsx`.
- Backend: `record_recommendation_decision` clears
  `review_required=False` on `accepted`. Other decisions keep the flag.
- Frontend: Approve / Request changes bar inside the strategy card
  header, gated on `useCapability("strategy:approve")` (the cap added
  in P2 #7 below). Approve calls `recordRecommendationDecision`,
  re-fetch drops the partner-review badge and renders an Approved
  badge.
- Tests: `test_accepted_decision_clears_review_required`,
  `test_non_accept_decisions_keep_review_required`, plus four frontend
  tests covering approve / request-changes / loading / no-cap states.

### P1 #4 — Per-item citation verification on every persisted legal claim
- Files: `apps/api/src/caseops_api/schemas/litigation_strategy.py`,
  `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`,
  `apps/web/lib/api/schemas.ts`,
  `apps/web/app/app/matters/[id]/strategy/page.tsx`,
  `apps/web/app/app/matters/[id]/strategy/page.test.tsx`.
- Approach (per the brief: "mark unverified rather than drop"):
  add `supporting_citations` + `unverified` to ForumStep,
  LimitationFlag, StrategyRisk; convert `next_best_actions` from
  `list[str]` → `list[NextBestAction]`. After LLM response, route each
  item's citations through the existing verifier. Failed items keep
  their narrative content, are flagged `unverified=True`, and have
  citations stripped.
- Convention: forum steps + limitation flags default to
  `unverified=True` when no citation survives (always legal claims).
  Risks + next-best actions only flip to `unverified=True` when the
  LLM emitted citations and none survived (factual items stay
  verified).
- Frontend renders an amber Unverified badge on each item kind.
- Tests:
  `test_strategy_persists_verified_citations_on_every_item_kind`,
  `test_strategy_flags_unverified_when_forum_step_citation_does_not_match`,
  `test_strategy_flags_unverified_on_legal_risk_with_bad_citation`,
  plus the frontend Unverified-badge test.

### P2 #5 — Reframe strategy + reject probability framing
- Files: `apps/api/src/caseops_api/schemas/litigation_strategy.py`,
  `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Prompt rewrites strategy as "routes, risks, procedural posture, and
  evidence gaps — NOT outcome prediction".
- New `assert_no_probability_language` scans narrative fields
  (current_posture, route rationale + risk_notes, alt-route rationale
  + risk_notes, forum-step rationale, limitation-flag description,
  risk description + mitigation, next-best-action text, disclaimer)
  with strict regex patterns: `\d{1,3}% chance|likelihood|probability|
  odds|likely`, `likely to win`, `likelihood of success`, etc. Service
  rejects with HTTP 422 + `ModelRun.status =
  rejected_probability_language`.
- Tests:
  `test_assert_no_probability_language_blocks_percent_chance`,
  `test_assert_no_probability_language_passes_clean_strategy`,
  `test_strategy_refuses_when_probability_language_in_payload`,
  `test_strategy_test_fixture_has_no_probability_language`.

### P2 #6 — PRD context ingestion (attachments + statutes + cause-list)
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- `_assemble_context` now pulls (a) recent matter_attachments where
  `extracted_text` exists (capped at 6 docs × 600-char excerpts),
  (b) linked matter_statute_references joined with statute_sections +
  statutes (capped at 8, 600-char section_text slice, with relevance
  label), (c) recent matter_cause_list_entries (capped at 4, includes
  bench_name + stage). Prompt surfaces them as MATTER_ATTACHMENTS,
  LINKED_STATUTE_REFERENCES, and CAUSE_LIST_NEXT_BENCH blocks.
- Empty-block path: prompt explicitly says "no X on file" and
  instructs the model to surface the gap under `missing_facts`.
- Tests:
  `test_strategy_context_includes_attachments_statutes_and_cause_list_when_present`,
  `test_strategy_context_says_none_on_file_when_no_attachments_statutes_or_cause_list`.

### P2 #7 — Dedicated `strategy:generate` / `strategy:approve` capabilities
- Files: `apps/api/src/caseops_api/api/dependencies.py`,
  `apps/api/src/caseops_api/api/routes/recommendations.py`,
  `apps/api/tests/test_litigation_strategy.py`,
  `apps/web/lib/capabilities.ts`,
  `apps/web/app/app/matters/[id]/strategy/page.tsx`,
  `apps/web/app/app/matters/[id]/strategy/page.test.tsx`.
- Two new caps in the registry:
  - `strategy:generate` (owner / admin / partner / member) — same
    role tier as `recommendations:generate`.
  - `strategy:approve` (owner / admin / partner) — same tier as
    `recommendations:decide`.
- Additive: a litigation_strategy POST still requires
  `recommendations:generate` (dependency-level gate), then runs an
  inline `strategy:generate` check. Decision endpoint adds
  `strategy:approve` for accepts on type='litigation_strategy'.
- Frontend mirrors via `useCapability('strategy:generate')` for the
  Generate button and `useCapability('strategy:approve')` for the
  Approve / Request changes bar.
- The capability strings are registry-only — no DB seed migration
  needed (CaseOps capabilities are pure code-level lookups).
- Tests:
  `test_strategy_generate_returns_403_when_role_lacks_strategy_generate`,
  `test_strategy_approve_returns_403_when_role_lacks_strategy_approve`,
  `test_strategy_approve_succeeds_when_role_has_strategy_approve`,
  plus two frontend cap-gate tests.

### Verification

- Full backend touched-module suite:
  `scripts/verify-backend.sh tests/test_litigation_strategy.py
   tests/test_recommendations.py tests/test_role_guards.py
   tests/test_sc_strategy_templates.py tests/test_template_recommender.py
   tests/test_drafting_templates.py` — 173 passed.
- `cd apps/web && npm run typecheck` — clean.
- `cd apps/web && npm run test` — 223 / 223.
- `cd apps/web && npm run build` — clean.
- Forbidden-outcome-phrase audit (`rg -i ...` across `apps/api/src` and
  `apps/web`): every hit is inside the FORBIDDEN_OUTCOME_PHRASES list,
  the prompt that instructs the LLM not to use them, or the test
  fixture's self-check FORBIDDEN_PHRASES list.
- Forbidden-probability-phrase audit (`rg -i 'likely to win|
  likelihood of success|...'`): every hit is inside
  FORBIDDEN_PROBABILITY_PATTERNS, the prompt instructing the LLM, the
  service refusal copy, or an unrelated `appeal_strength.py` module.

## Round 3 fixes (2026-05-03 — addressing PR #7 second-pass review)

User-driven careful review of HEAD `1e9088d` surfaced 4 more issues (2 P1
+ 2 P2). All four landed as separate commits so the reviewer can map
fix → commit one-to-one. No new Pydantic shape on the API contract, so
`apps/web/lib/api/openapi-types.ts` did NOT need to be regenerated.

### P1 #R3-1 — Drop uncited alternative routes
- File: `apps/api/src/caseops_api/services/litigation_strategy.py`.
- Approach (option (a) from the brief): drop alternative routes whose
  citations all fail verification. The simpler, fail-closed answer.
  Persisting an alternative with `supporting_citations=[]` showed an
  uncited route to the lawyer as an available legal strategy.
- Effect: `cleaned_alternatives` is filtered post-verification;
  `Recommendation.options` ranks shrink with the surviving routes;
  no frontend change needed (the contract is unchanged, the dropped
  routes simply don't appear).
- Test: `test_strategy_drops_uncited_alternative_routes` mocks 2 LLM
  alternatives — 1 verifiable + 1 fictitious — and asserts persistence
  keeps only the verified one (and that `Recommendation.options.rank`
  collapses to `[0, 1]`).

### P1 #R3-2 — Bare-string next_best_actions coerce to unverified=True
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Approach (option (ii) from the brief): keep the schema flexible for
  legacy LLM outputs but coerce every bare-string entry to
  `unverified=True`. Round-2's path persisted bare strings as
  `unverified=False`, which made an LLM emitting "File SLP within 60
  days" as a bare string look corpus-grounded.
- Also tightens the system prompt: instructs the model that
  `next_best_actions` MUST be the structured object form. The post-
  processor still tolerates bare strings (so a sloppy model does not
  502 the request) — they are flagged.
- Tests:
  `test_strategy_marks_bare_string_next_best_actions_unverified`
  covers the brief's exact example plus structured factual + structured
  legal claim cases;
  `test_strategy_marks_structured_action_with_uncited_citation_unverified`
  is a regression so the bare-string coercion does not accidentally
  widen to cover the structured form.

### P2 #R3-3 — Drop unverified limitation flags + uncited legal forum steps
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Approach (option (a) for limitation flags + legal-vs-operational
  split for forum steps):
  - `_build_limitation_flags`: drop any flag whose citations all fail
    verification. No "Unverified" deadlines in the persisted payload.
  - `_build_forum_steps`: split legal vs operational by the
    `statutory_basis` signal. Non-empty = legal claim, fail-closed.
    Empty = operational ("Pay court fees"), keep with
    `unverified=True` so the procedural narrative is still visible.
- Tests:
  `test_strategy_drops_unverified_limitation_flag` (LLM emits 2 flags,
  one verifiable + one fictitious; only the verified one persists);
  `test_strategy_drops_legal_forum_step_with_uncited_citation` (poison
  the BNSS s.528 step's citation; it disappears, the SC step
  survives);
  `test_strategy_flags_unverified_when_forum_step_citation_does_not_match`
  updated to use an OPERATIONAL step (`statutory_basis=[]`) so it still
  exercises the kept-with-unverified path.

### P2 #R3-4 — Court orders in strategy context
- Files: `apps/api/src/caseops_api/services/litigation_strategy.py`,
  `apps/api/tests/test_litigation_strategy.py`.
- Approach: `_assemble_context` pulls the most recent 5
  `MatterCourtOrder` rows (ordered by `order_date desc, created_at
  desc`); `_CourtOrderSnippet` bounds summary at 200 chars and
  order_text excerpt at 500 chars; `_build_prompt` renders a
  `RECENT_COURT_ORDERS` block. Empty path emits explicit copy and, at
  appellate forum levels (HC / SC / tribunal), instructs the model to
  add 'impugned order' to `missing_facts`.
- Heuristic for the missing-facts hint: forum_level in
  `{high_court, supreme_court, tribunal, high_court_*_bench}`. At
  trial / lower-court forums the empty branch is silent — those
  matters often pre-date any order.
- Tests:
  `test_strategy_context_includes_court_orders_when_present` (3 orders
  seeded; asserts each title + EXCERPT renders, most-recent-first
  ordering by string position);
  `test_strategy_context_says_none_for_court_orders_and_flags_missing_at_appellate_forum`
  (zero orders at `high_court`; asserts the empty block + missing-facts
  hint).

### Round 3 verification
- Touched-modules backend suite:
  `scripts/verify-backend.sh tests/test_litigation_strategy.py
   tests/test_recommendations.py tests/test_role_guards.py
   tests/test_sc_strategy_templates.py tests/test_template_recommender.py
   tests/test_drafting_templates.py` — 180 passed.
- Forbidden-phrase audit: every hit is FORBIDDEN_OUTCOME_PHRASES
  itself, the prompt instructing the LLM, the docstring describing
  the rule, drafting_prompts.py / drafting.py "do NOT promise..."
  guidance, the seed data (statute names), or the frontend
  forbidden-phrases test fixture.
- Probability-phrase audit: every hit is FORBIDDEN_PROBABILITY_PATTERNS,
  the prompt instructing the LLM, the refusal copy, docstrings, or the
  unrelated `appeal_strength.py` module's own banned-phrase scrub.
- `apps/web/lib/api/openapi-types.ts` is NOT regenerated. The fixes
  are service-internal — `LitigationStrategyPayload`, `ForumStep`,
  `LimitationFlag`, `NextBestAction` Pydantic models are unchanged on
  the API contract. Service-internal `_LLMStrategyResponse` is not
  exposed via the FastAPI app schema.

## Rollout notes

1. Run the alembic migration `20260503_0001` on each environment:
   `alembic upgrade head` adds `recommendations.strategy_payload_json TEXT NULL`.
2. No new env vars; the strategy LLM call rides the existing
   `PURPOSE_RECOMMENDATIONS` provider routing (gpt-5-mini per the
   2026-05-02 cutover).
3. No new capability strings — `recommendations:generate` and
   `recommendations:decide` already gate the strategy planner.
4. The Strategy tab appears on every matter cockpit on first load
   after deploy.
