from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
    require_role,
)
from caseops_api.db.models import MembershipRole
from caseops_api.schemas.ai_feedback import (
    AIFeedbackCategory,
    AIFeedbackListResponse,
    AIFeedbackRecord,
    AIFeedbackReviewRequest,
    AIFeedbackStatus,
    AIFeedbackSurface,
    AIOutcomeAnalyticsResponse,
    ProductGuideFeedbackCreateRequest,
    WorkspaceAssistantFeedbackCreateRequest,
)
from caseops_api.services.ai_feedback import (
    get_ai_outcome_analytics,
    list_feedback,
    review_feedback,
    submit_product_guide_feedback,
    submit_workspace_assistant_feedback,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
admin_router = APIRouter()
GuideFeedbackUser = Annotated[
    SessionContext,
    Depends(require_role(*tuple(MembershipRole))),
]
AssistantFeedbackUser = Annotated[
    SessionContext,
    Depends(require_capability("ai:generate")),
]
FeedbackAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


@router.post(
    "/product-guide",
    response_model=AIFeedbackRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Submit idempotent feedback for a current Product Guide target",
)
async def post_product_guide_feedback(
    payload: ProductGuideFeedbackCreateRequest,
    context: GuideFeedbackUser,
    session: DbSession,
) -> AIFeedbackRecord:
    return AIFeedbackRecord.model_validate(
        submit_product_guide_feedback(session, context=context, payload=payload)
    )


@router.post(
    "/workspace-assistant",
    response_model=AIFeedbackRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Submit idempotent feedback for a private assistant turn",
)
async def post_workspace_assistant_feedback(
    payload: WorkspaceAssistantFeedbackCreateRequest,
    context: AssistantFeedbackUser,
    session: DbSession,
) -> AIFeedbackRecord:
    return AIFeedbackRecord.model_validate(
        submit_workspace_assistant_feedback(session, context=context, payload=payload)
    )


@admin_router.get(
    "/ai-outcomes",
    response_model=AIOutcomeAnalyticsResponse,
    summary="Read privacy-bounded tenant AI outcome aggregates",
)
async def get_ai_outcomes(
    context: FeedbackAdmin,
    session: DbSession,
    window_days: Annotated[int, Query(ge=1, le=90)] = 30,
) -> AIOutcomeAnalyticsResponse:
    return get_ai_outcome_analytics(
        session,
        context=context,
        window_days=window_days,
    )


@admin_router.get(
    "/ai-feedback",
    response_model=AIFeedbackListResponse,
    summary="List the bounded workspace AI feedback review queue",
)
async def get_ai_feedback(
    context: FeedbackAdmin,
    session: DbSession,
    item_status: Annotated[AIFeedbackStatus | None, Query(alias="status")] = None,
    surface: AIFeedbackSurface | None = None,
    category: AIFeedbackCategory | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> AIFeedbackListResponse:
    items, has_more = list_feedback(
        session,
        context=context,
        item_status=item_status,
        surface=surface,
        category=category,
        limit=limit,
    )
    return AIFeedbackListResponse(
        items=[AIFeedbackRecord.model_validate(item) for item in items],
        limit=limit,
        has_more=has_more,
    )


@admin_router.patch(
    "/ai-feedback/{feedback_id}",
    response_model=AIFeedbackRecord,
    summary="Review feedback with optimistic concurrency",
)
async def patch_ai_feedback(
    feedback_id: str,
    payload: AIFeedbackReviewRequest,
    context: FeedbackAdmin,
    session: DbSession,
) -> AIFeedbackRecord:
    return AIFeedbackRecord.model_validate(
        review_feedback(
            session,
            context=context,
            feedback_id=feedback_id,
            payload=payload,
        )
    )
