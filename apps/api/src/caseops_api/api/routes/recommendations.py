from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from caseops_api.api.dependencies import (
    CAPABILITY_ROLES,
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.core.rate_limit import (
    ai_route_rate_limit,
    limiter,
    tenant_aware_key,
)
from caseops_api.db.models import Recommendation
from caseops_api.schemas.recommendations import (
    RecommendationDecisionRecord,
    RecommendationDecisionRequest,
    RecommendationGenerateRequest,
    RecommendationListResponse,
    RecommendationOptionRecord,
    RecommendationRecord,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.recommendations import (
    generate_recommendation,
    list_matter_recommendations,
    parse_assumptions,
    parse_citations,
    record_recommendation_decision,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
RecommendationGenerator = Annotated[
    SessionContext, Depends(require_capability("recommendations:generate"))
]
RecommendationDecider = Annotated[
    SessionContext, Depends(require_capability("recommendations:decide"))
]


def _require_capability_inline(context: SessionContext, capability: str) -> None:
    """Round-2 P2 #7 helper. ``require_capability`` is normally a
    FastAPI dependency, but for litigation_strategy we need to run a
    SECOND capability check inside the route handler (after the type
    is known) — the dispatch is type-driven. This helper keeps the
    behaviour identical to the dependency form."""
    roles = CAPABILITY_ROLES.get(capability)
    if roles is None:
        raise RuntimeError(
            f"Unknown capability {capability!r}; add it to CAPABILITY_ROLES.",
        )
    if context.membership.role not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Capability {capability!r} requires role in "
                f"{sorted(r.value for r in roles)}; you are "
                f"{context.membership.role!r}."
            ),
        )


def _option_record(option) -> RecommendationOptionRecord:
    return RecommendationOptionRecord(
        id=option.id,
        rank=option.rank,
        label=option.label,
        rationale=option.rationale,
        confidence=option.confidence,
        supporting_citations=parse_citations(option.supporting_citations_json),
        risk_notes=option.risk_notes,
    )


def _decision_record(decision) -> RecommendationDecisionRecord:
    return RecommendationDecisionRecord(
        id=decision.id,
        actor_membership_id=decision.actor_membership_id,
        decision=decision.decision,
        selected_option_index=decision.selected_option_index,
        notes=decision.notes,
        created_at=decision.created_at,
    )


def _recommendation_record(recommendation: Recommendation) -> RecommendationRecord:
    # MOD-LSE-1 (2026-05-03): hydrate the strategy payload from the
    # opaque JSON column when present. Pydantic validation rejects any
    # legacy / corrupted payload — we surface that as ``None`` rather
    # than crashing the list endpoint, but log it so an operator can
    # follow up.
    strategy_payload = None
    raw_payload = recommendation.strategy_payload_json
    if raw_payload:
        import json as _json
        import logging as _logging

        from caseops_api.schemas.litigation_strategy import (
            LitigationStrategyPayload,
        )

        try:
            strategy_payload = LitigationStrategyPayload.model_validate(
                _json.loads(raw_payload),
            )
        except Exception:  # noqa: BLE001
            _logging.getLogger(__name__).warning(
                "recommendation %s strategy_payload_json failed to validate; "
                "returning None",
                recommendation.id,
            )
            strategy_payload = None

    return RecommendationRecord(
        id=recommendation.id,
        matter_id=recommendation.matter_id,
        type=recommendation.type,
        title=recommendation.title,
        rationale=recommendation.rationale,
        primary_option_index=recommendation.primary_option_index,
        assumptions=parse_assumptions(recommendation.assumptions_json),
        missing_facts=parse_assumptions(recommendation.missing_facts_json),
        confidence=recommendation.confidence,
        review_required=recommendation.review_required,
        status=recommendation.status,
        next_action=recommendation.next_action,
        created_at=recommendation.created_at,
        options=[_option_record(o) for o in recommendation.options],
        decisions=[_decision_record(d) for d in recommendation.decisions],
        retrieved_authorities=parse_assumptions(
            recommendation.retrieved_authorities_json,
        ),
        strategy_payload=strategy_payload,
    )


@router.get(
    "/matters/{matter_id}/recommendations",
    response_model=RecommendationListResponse,
    summary="List recommendations generated for a matter",
)
async def list_recommendations(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> RecommendationListResponse:
    recommendations = list_matter_recommendations(
        session, context=context, matter_id=matter_id
    )
    return RecommendationListResponse(
        matter_id=matter_id,
        recommendations=[_recommendation_record(r) for r in recommendations],
    )


@router.post(
    "/matters/{matter_id}/recommendations",
    response_model=RecommendationRecord,
    summary="Generate a recommendation for a matter",
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def create_recommendation(
    request: Request,
    matter_id: str,
    payload: RecommendationGenerateRequest,
    context: RecommendationGenerator,
    session: DbSession,
) -> RecommendationRecord:
    # Round-2 P2 #7. Strategy generation requires a dedicated
    # ``strategy:generate`` capability on top of the
    # ``recommendations:generate`` gate the dependency above already
    # asserted. The two are additive — if a future role tier (e.g.
    # ``junior partner``) gains ``recommendations:generate`` but NOT
    # ``strategy:generate``, the request still fails here.
    if payload.type == "litigation_strategy":
        _require_capability_inline(context, "strategy:generate")

    recommendation = generate_recommendation(
        session,
        context=context,
        matter_id=matter_id,
        rec_type=payload.type,
    )
    return _recommendation_record(recommendation)


@router.post(
    "/recommendations/{recommendation_id}/decisions",
    response_model=RecommendationRecord,
    summary="Record an accept/reject/edit decision on a recommendation",
)
async def create_decision(
    recommendation_id: str,
    payload: RecommendationDecisionRequest,
    context: RecommendationDecider,
    session: DbSession,
) -> RecommendationRecord:
    # Round-2 P2 #7. Approving a litigation_strategy requires the
    # dedicated ``strategy:approve`` capability in addition to the
    # ``recommendations:decide`` gate the dependency already asserted.
    # Non-strategy decisions and non-accept decisions on strategy rows
    # ride the existing decide cap.
    if payload.decision == "accepted":
        # Pre-load just the type so the capability check fires before
        # the full decision flow.
        from sqlalchemy import select as _select

        rec_type = session.scalar(
            _select(Recommendation.type).where(
                Recommendation.id == recommendation_id,
                Recommendation.company_id == context.company.id,
            )
        )
        if rec_type == "litigation_strategy":
            _require_capability_inline(context, "strategy:approve")

    recommendation = record_recommendation_decision(
        session,
        context=context,
        recommendation_id=recommendation_id,
        decision=payload.decision,
        selected_option_index=payload.selected_option_index,
        notes=payload.notes,
    )
    return _recommendation_record(recommendation)
