# PRD — Litigation Strategy and Escalation Planner

Date: 2026-05-03
Status: In implementation (feature/litigation-strategy-escalation-planner)
Owner: CaseOps product

This PRD captures the implementation contract for the matter-level
**Litigation Strategy and Escalation Planner**. It complements
`docs/PRD_CODEX_2026-04-23.md` (the execution PRD) and slots into
the matter cockpit alongside Documents, Drafts, Hearings, Recommendations,
and Statutes.

## 1. Purpose

Indian litigators routinely think in routes — "we file the SLP first,
then the stay, then the review if needed". They also think in
escalation ladders — trial court → high court → division bench →
supreme court → review → curative. CaseOps already supports per-step
artefacts (drafts, recommendations, hearing packs). It does not yet
package those steps into an *integrated route plan with escalation
to Supreme Court level where legally available*.

The Strategy and Escalation Planner closes that gap.

## 2. Hard product rule (non-negotiable)

The strategy planner is **citation-grounded, lawyer-reviewed**.

- Every output is `review_required = true`.
- Every legal route, remedy, limitation flag, or forum recommendation
  must cite at least one verified authority. Zero verified citations
  must fail closed (HTTP 422), exactly as `recommendation:authority`
  already does.
- The output must list missing facts rather than invent them.
- The output must not invent authorities, dates, forum names, or
  remedies.
- The output must not contain language like "perfect strategy",
  "guaranteed success", "will win", "will be granted", "certain
  outcome", "no lawyer needed", "replace advocate". A structural test
  scans every generated payload (and every test fixture) and rejects
  these phrases.
- Supreme Court routes are surfaced only where they are legally
  plausible (Article 132 / 133 / 134 / 136 / 137 / 142 etc.).

## 3. User journeys

| Journey | User | Trigger | Outcome |
| --- | --- | --- | --- |
| J-LSE-1 | Partner | "What's the playbook on this matter?" | Strategy with primary route + alternatives |
| J-LSE-2 | Member | "Do we have an SC route here?" | Escalation ladder, gated on legal plausibility |
| J-LSE-3 | Member | "Generate an SLP from this strategy" | Pre-selected `special_leave_petition` template, matter pre-filled |
| J-LSE-4 | Partner | Approve / request changes | Decision recorded; audit row written |

## 4. Modules

| Module | Code |
| --- | --- |
| MOD-LSE-1 | `litigation_strategy` recommendation type |
| MOD-LSE-2 | `services/litigation_strategy.py` — context assembly + structured output |
| MOD-LSE-3 | 11 SC and escalation drafting templates |
| MOD-LSE-4 | Template recommender SC / HC escalation update |
| MOD-LSE-5 | Frontend Strategy tab on the matter cockpit |
| MOD-LSE-6 | Draft generation from strategy (template recommender wiring) |
| MOD-LSE-7 | RBAC + audit + tenant isolation |
| MOD-LSE-8 | Prompt guardrails |

## 5. Modular design

### 5.1 Recommendation type

`type = "litigation_strategy"` is added to `SUPPORTED_TYPES` in
`services/recommendations.py`. Strategy generation is implemented by
the new service `services/litigation_strategy.py` and the
recommendation route fans out by type so the existing
`forum / authority / remedy / next_best_action` paths are unchanged.

### 5.2 Strategy payload

A strategy output is richer than a list of options. It is persisted
on `Recommendation.strategy_payload_json` (new TEXT column, default
`null`, nullable). Shape (Pydantic-validated on read and write):

```
LitigationStrategyPayload {
    current_posture: str
    recommended_route: StrategyRoute
    alternative_routes: list[StrategyRoute]
    forum_sequence: list[ForumStep]      # the escalation ladder
    recommended_drafts: list[RecommendedDraft]
    limitation_flags: list[LimitationFlag]
    required_documents: list[str]
    missing_facts: list[str]
    risks: list[StrategyRisk]
    next_best_actions: list[str]
    disclaimer: str
}
```

A `StrategyRoute` is rendered as a single `RecommendationOption` row
on the existing recommendations table. The remaining structure is
read from `strategy_payload_json` and JSON-validated on every read.

### 5.3 Drafting templates

11 new `DraftTemplateType` enum values:

```
special_leave_petition       Article 136 SLP (civil + criminal)
supreme_court_appeal         Article 132 / 133 / 134 substantial-question appeal
review_petition              Article 137 review (SC/HC)
curative_petition            Rupa Ashok Hurra curative jurisdiction
transfer_petition            Article 139A / s.25 CPC / s.406 BNSS / 527 CrPC
contempt_petition            Contempt of Courts Act 1971 / Article 129/215
interim_relief_application   Stay / status quo / injunction (SC + HC + lower)
condonation_of_delay         s.5 Limitation Act condonation
exemption_application        SC exemption (filing / certified copy / pages)
synopsis_list_of_dates       Mandatory SC filing accompaniment
filing_index_checklist       SC + HC registry index / paginated checklist
```

Each ships:

- A Pydantic facts model under `_TemplateFactsBase`.
- A field-spec list (`DraftingFieldSpec`) for the stepper.
- A registry entry via `_register(...)` in `schemas/drafting_templates.py`.
- A specialised system prompt in `services/drafting_prompts.py`.

The service `template_recommender.py` is updated so an SC matter or
an HC writ/appeal matter surfaces an SC draft pack including SLP +
condonation + exemption + synopsis + index where appropriate.

### 5.4 Frontend

A new Strategy tab on the matter cockpit:
`apps/web/app/app/matters/[id]/strategy/page.tsx`. Lists the latest
strategy if one exists, plus a generate button. The strategy card
renders the route timeline, primary route, alternatives, limitation
flags, missing facts, risks, authority citations, and a recommended
draft pack with one-click "Generate this draft" buttons that
deep-link into the existing drafts/new flow with the right template
preselected.

### 5.5 Capabilities

`recommendations:generate` and `recommendations:decide` already gate
strategy generation and approval respectively (the strategy is a
recommendation underneath). No new capability strings are added —
the existing capabilities map cleanly onto the strategy's read /
generate / approve / export operations. (Export reuses the standard
audit-export gate.)

## 6. Tests

Backend:

- `tests/test_litigation_strategy.py`
  - successful generation populates `strategy_payload_json`
  - zero verified citations refuses with 422
  - `review_required=true` always
  - missing facts present in payload
  - SC routes only when legally plausible
  - structural forbid-language scan passes
- `tests/test_drafting_templates.py` (extended) — every new template
  has a registry entry + facts model + JSON schema.
- `tests/test_template_recommender.py` (extended) — SC / HC escalation
  packs include SLP + condonation + synopsis where appropriate.
- `tests/test_recommendations.py` — existing four types still work.

Frontend:

- `apps/web/app/app/matters/[id]/strategy/page.test.tsx`
  - empty state renders
  - generated strategy renders route timeline + recommended drafts
  - refusal copy renders
  - forbidden-language scan over fixture passes

## 7. Out of scope (v1)

- Multi-tenant cross-matter strategy comparison (would need a
  cross-matter retrieval boundary).
- Predictive bench-strategy reasoning beyond what
  `services/bench_strategy.py` already provides.
- Automated SC e-filing integration.
- Cost / quantum modelling.
