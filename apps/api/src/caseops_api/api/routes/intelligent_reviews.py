from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from caseops_api.api.dependencies import DbSession, get_current_context, require_capability
from caseops_api.core.rate_limit import ai_route_rate_limit, limiter, tenant_aware_key
from caseops_api.schemas.intelligent_reviews import (
    IntelligentReviewCreateRequest,
    IntelligentReviewFinalizeRequest,
    IntelligentReviewListResponse,
    IntelligentReviewPublishRequest,
    IntelligentReviewPublishResponse,
    IntelligentReviewRecord,
    IntelligentReviewSelectionRequest,
)
from caseops_api.services.intelligent_reviews import (
    enqueue_intelligent_review,
    finalize_intelligent_review,
    get_intelligent_review,
    list_intelligent_reviews,
    publish_intelligent_review,
    run_intelligent_review_job,
    serialize_intelligent_review,
    update_intelligent_review_selection,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
ReviewGenerator = Annotated[SessionContext, Depends(require_capability("recommendations:generate"))]
ReviewFinalizer = Annotated[SessionContext, Depends(require_capability("recommendations:decide"))]
ReviewPublisher = Annotated[SessionContext, Depends(require_capability("drafts:review"))]


@router.post(
    "/reviews",
    response_model=IntelligentReviewRecord,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a frozen, source-grounded intelligent review",
)
@limiter.limit(ai_route_rate_limit, key_func=tenant_aware_key)
async def create_intelligent_review(
    request: Request,
    payload: IntelligentReviewCreateRequest,
    background_tasks: BackgroundTasks,
    context: ReviewGenerator,
    session: DbSession,
) -> IntelligentReviewRecord:
    review = enqueue_intelligent_review(session, context=context, payload=payload)
    review_id = review.id
    record = serialize_intelligent_review(session, review=review)
    # Starlette runs BackgroundTasks before FastAPI closes yielded request
    # dependencies. End the serialization read transaction before a model call
    # that can legitimately outlive PostgreSQL's idle-transaction boundary.
    session.rollback()
    background_tasks.add_task(run_intelligent_review_job, review_id)
    return record


@router.get(
    "/reviews",
    response_model=IntelligentReviewListResponse,
    summary="List permission-visible intelligent reviews",
)
async def get_intelligent_reviews(
    context: CurrentContext,
    session: DbSession,
    matter_id: str | None = Query(default=None),
    ip_docket_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
) -> IntelligentReviewListResponse:
    return list_intelligent_reviews(
        session,
        context=context,
        matter_id=matter_id,
        ip_docket_id=ip_docket_id,
        limit=limit,
    )


@router.get(
    "/reviews/{review_id}",
    response_model=IntelligentReviewRecord,
    summary="Read one source-frozen intelligent review",
)
async def get_intelligent_review_by_id(
    review_id: str,
    context: CurrentContext,
    session: DbSession,
) -> IntelligentReviewRecord:
    return get_intelligent_review(
        session,
        context=context,
        review_id=review_id,
    )


@router.patch(
    "/reviews/{review_id}/authorities",
    response_model=IntelligentReviewRecord,
    summary="Include or exclude authorities before finalization",
)
async def patch_intelligent_review_authorities(
    review_id: str,
    payload: IntelligentReviewSelectionRequest,
    context: ReviewFinalizer,
    session: DbSession,
) -> IntelligentReviewRecord:
    return update_intelligent_review_selection(
        session,
        context=context,
        review_id=review_id,
        included_authority_ids=payload.included_authority_ids,
        lawyer_notes=payload.lawyer_notes,
    )


@router.post(
    "/reviews/{review_id}/finalize",
    response_model=IntelligentReviewRecord,
    summary="Finalize a complete review as an authorized lawyer",
)
async def post_intelligent_review_finalize(
    review_id: str,
    payload: IntelligentReviewFinalizeRequest,
    context: ReviewFinalizer,
    session: DbSession,
) -> IntelligentReviewRecord:
    return finalize_intelligent_review(
        session,
        context=context,
        review_id=review_id,
        lawyer_notes=payload.lawyer_notes,
    )


@router.post(
    "/reviews/{review_id}/publish",
    response_model=IntelligentReviewPublishResponse,
    summary="Publish a finalized review into the existing Draft lifecycle",
)
async def post_intelligent_review_publish(
    review_id: str,
    payload: IntelligentReviewPublishRequest,
    context: ReviewPublisher,
    session: DbSession,
) -> IntelligentReviewPublishResponse:
    return publish_intelligent_review(
        session,
        context=context,
        review_id=review_id,
        title=payload.title,
    )
