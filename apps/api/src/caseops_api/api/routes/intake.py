"""GC intake queue endpoints (Sprint 8b BG-025)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.intake import (
    IntakeRequestCreateRequest,
    IntakeRequestListResponse,
    IntakeRequestPromoteRequest,
    IntakeRequestRecord,
    IntakeRequestUpdateRequest,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.intake import (
    create_intake_request,
    list_intake_requests,
    promote_intake_request,
    update_intake_request,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
IntakeSubmitter = Annotated[
    SessionContext, Depends(require_capability("intake:submit"))
]
IntakeTriager = Annotated[
    SessionContext, Depends(require_capability("intake:triage"))
]
IntakePromoter = Annotated[
    SessionContext, Depends(require_capability("intake:promote"))
]


@router.get(
    "/requests",
    response_model=IntakeRequestListResponse,
    summary="List intake requests for the current company",
)
async def get_intake_requests(
    context: CurrentContext,
    session: DbSession,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    assigned_to_me: Annotated[bool, Query()] = False,
) -> IntakeRequestListResponse:
    return list_intake_requests(
        session,
        context=context,
        status_filter=status_filter,
        assigned_to_me=assigned_to_me,
    )


@router.post(
    "/requests",
    response_model=IntakeRequestRecord,
    summary="File a new intake request",
)
async def post_intake_request(
    payload: IntakeRequestCreateRequest,
    context: IntakeSubmitter,
    session: DbSession,
) -> IntakeRequestRecord:
    result = create_intake_request(session, context=context, payload=payload)
    session.commit()
    return result


@router.patch(
    "/requests/{request_id}",
    response_model=IntakeRequestRecord,
    summary="Triage, reassign, or update an intake request",
)
async def patch_intake_request(
    request_id: str,
    payload: IntakeRequestUpdateRequest,
    context: IntakeTriager,
    session: DbSession,
) -> IntakeRequestRecord:
    result = update_intake_request(
        session, context=context, request_id=request_id, payload=payload
    )
    session.commit()
    return result


@router.post(
    "/requests/{request_id}/promote",
    response_model=IntakeRequestRecord,
    summary="Promote an intake request into a matter",
)
async def post_intake_promote(
    request_id: str,
    payload: IntakeRequestPromoteRequest,
    context: IntakePromoter,
    session: DbSession,
) -> IntakeRequestRecord:
    result = promote_intake_request(
        session, context=context, request_id=request_id, payload=payload
    )
    session.commit()
    return result
