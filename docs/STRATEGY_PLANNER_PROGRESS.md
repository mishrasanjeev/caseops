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

- No dedicated `strategy:read` / `strategy:approve` capability split —
  reuses `recommendations:generate` / `recommendations:decide`. PRD §10.4
  trade-off; tracked for a future capability-graph upgrade.
- Strategy export (PDF / DOCX) is not in this PR. Each draft generated
  from the strategy keeps the existing per-draft export path.
- Bench-strategy enrichment is read-only; no two-way wiring back into
  bench-strategy yet (that remains a follow-up under MOD-TS-018).

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
