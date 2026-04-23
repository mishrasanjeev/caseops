from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from caseops_api.api.dependencies import (
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
    recommendation = record_recommendation_decision(
        session,
        context=context,
        recommendation_id=recommendation_id,
        decision=payload.decision,
        selected_option_index=payload.selected_option_index,
        notes=payload.notes,
    )
    return _recommendation_record(recommendation)
