from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.outside_counsel import (
    OutsideCounselAssignmentCreateRequest,
    OutsideCounselAssignmentRecord,
    OutsideCounselCreateRequest,
    OutsideCounselRecommendationRequest,
    OutsideCounselRecommendationResponse,
    OutsideCounselRecord,
    OutsideCounselSpendRecord,
    OutsideCounselSpendRecordCreateRequest,
    OutsideCounselUpdateRequest,
    OutsideCounselWorkspaceResponse,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.outside_counsel import (
    create_outside_counsel_assignment,
    create_outside_counsel_profile,
    create_outside_counsel_spend_record,
    get_outside_counsel_recommendations,
    get_outside_counsel_workspace,
    update_outside_counsel_profile,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get(
    "/workspace",
    response_model=OutsideCounselWorkspaceResponse,
    summary="Get outside counsel, spend, and portfolio analytics for the current company",
)
async def get_current_company_outside_counsel_workspace(
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselWorkspaceResponse:
    return get_outside_counsel_workspace(session, context=context)


@router.post(
    "/profiles",
    response_model=OutsideCounselRecord,
    summary="Create an outside counsel profile",
)
async def post_current_company_outside_counsel_profile(
    payload: OutsideCounselCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselRecord:
    return create_outside_counsel_profile(session, context=context, payload=payload)


@router.patch(
    "/profiles/{counsel_id}",
    response_model=OutsideCounselRecord,
    summary="Update an outside counsel profile",
)
async def patch_current_company_outside_counsel_profile(
    counsel_id: str,
    payload: OutsideCounselUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselRecord:
    return update_outside_counsel_profile(
        session,
        context=context,
        counsel_id=counsel_id,
        payload=payload,
    )


@router.post(
    "/assignments",
    response_model=OutsideCounselAssignmentRecord,
    summary="Link outside counsel to a matter",
)
async def post_current_company_outside_counsel_assignment(
    payload: OutsideCounselAssignmentCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselAssignmentRecord:
    return create_outside_counsel_assignment(session, context=context, payload=payload)


@router.post(
    "/spend-records",
    response_model=OutsideCounselSpendRecord,
    summary="Record outside counsel spend against a matter",
)
async def post_current_company_outside_counsel_spend_record(
    payload: OutsideCounselSpendRecordCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselSpendRecord:
    return create_outside_counsel_spend_record(session, context=context, payload=payload)


@router.post(
    "/recommendations",
    response_model=OutsideCounselRecommendationResponse,
    summary="Rank outside counsel options for a matter",
)
async def post_current_company_outside_counsel_recommendations(
    payload: OutsideCounselRecommendationRequest,
    context: CurrentContext,
    session: DbSession,
) -> OutsideCounselRecommendationResponse:
    return get_outside_counsel_recommendations(session, context=context, payload=payload)
