from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_patent_proceedings import (
    PatentProceedingCreateRequest,
    PatentProceedingHistory,
    PatentProceedingPage,
    PatentProceedingPreview,
    PatentProceedingRecord,
    PatentProceedingTransitionRequest,
)
from caseops_api.services.ip_patent_proceedings import (
    create_patent_proceeding,
    get_patent_proceeding_history,
    list_patent_proceedings,
    preview_patent_proceeding,
    transition_patent_proceeding,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
Reader = Annotated[SessionContext, Depends(require_capability("ip:read"))]
Writer = Annotated[SessionContext, Depends(require_capability("ip:write"))]
CommandKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=200, pattern=r"\S")
]


@router.get("/applications/{application_id}/proceedings", response_model=PatentProceedingPage)
def get_page(
    application_id: UUID,
    context: Reader,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: UUID | None = None,
    snapshot_sequence: Annotated[int | None, Query(ge=0)] = None,
):
    return list_patent_proceedings(
        session,
        context=context,
        application_id=str(application_id),
        limit=limit,
        cursor=str(cursor) if cursor else None,
        snapshot_sequence=snapshot_sequence,
    )


@router.get(
    "/applications/{application_id}/proceedings/{proceeding_id}",
    response_model=PatentProceedingHistory,
)
def get_history(application_id: UUID, proceeding_id: UUID, context: Reader, session: DbSession):
    return get_patent_proceeding_history(
        session,
        context=context,
        application_id=str(application_id),
        proceeding_id=str(proceeding_id),
    )


@router.post(
    "/applications/{application_id}/proceedings",
    response_model=PatentProceedingRecord,
    status_code=201,
)
def create(
    application_id: UUID,
    payload: PatentProceedingCreateRequest,
    context: Writer,
    session: DbSession,
    idempotency_key: CommandKey,
):
    return create_patent_proceeding(
        session,
        context=context,
        application_id=str(application_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/applications/{application_id}/proceedings/{proceeding_id}/preview",
    response_model=PatentProceedingPreview,
)
def preview(
    application_id: UUID,
    proceeding_id: UUID,
    payload: PatentProceedingTransitionRequest,
    context: Writer,
    session: DbSession,
):
    return preview_patent_proceeding(
        session,
        context=context,
        application_id=str(application_id),
        proceeding_id=str(proceeding_id),
        payload=payload,
    )


@router.post(
    "/applications/{application_id}/proceedings/{proceeding_id}/transitions",
    response_model=PatentProceedingRecord,
    status_code=201,
)
def transition(
    application_id: UUID,
    proceeding_id: UUID,
    payload: PatentProceedingTransitionRequest,
    context: Writer,
    session: DbSession,
    idempotency_key: CommandKey,
):
    return transition_patent_proceeding(
        session,
        context=context,
        application_id=str(application_id),
        proceeding_id=str(proceeding_id),
        payload=payload,
        idempotency_key=idempotency_key,
    )
