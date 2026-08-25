"""IPLF-057A Madrid registration/designation API."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_international import (
    TrademarkInternationalActionRequest,
    TrademarkInternationalActionResponse,
    TrademarkInternationalRecordCreateRequest,
    TrademarkInternationalRecordPageResponse,
    TrademarkInternationalRecordResponse,
    TrademarkInternationalWorkspaceResponse,
)
from caseops_api.services.ip_international import (
    create_international_record,
    get_international_record,
    international_workspace,
    list_international_records,
    record_international_action,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


@router.get(
    "/international-registrations",
    response_model=TrademarkInternationalRecordPageResponse,
)
def international_registration_list(
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    record_kind: Annotated[
        Literal["international_registration", "international_designation"] | None,
        Query(),
    ] = None,
    parent_registration_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrademarkInternationalRecordPageResponse:
    return list_international_records(
        session,
        context=context,
        record_kind=record_kind,
        parent_registration_id=parent_registration_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/international-registrations/{record_id}",
    response_model=TrademarkInternationalRecordResponse,
)
def international_registration_get(
    record_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> TrademarkInternationalRecordResponse:
    return TrademarkInternationalRecordResponse.model_validate(
        get_international_record(session, context=context, record_id=record_id)
    )


@router.get(
    "/international-registrations/{record_id}/workspace",
    response_model=TrademarkInternationalWorkspaceResponse,
)
def international_registration_workspace(
    record_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> TrademarkInternationalWorkspaceResponse:
    return international_workspace(
        session,
        context=context,
        record_id=record_id,
    )


@router.post(
    "/international-registrations/{record_id}/actions",
    response_model=TrademarkInternationalActionResponse,
    status_code=status.HTTP_201_CREATED,
)
def international_registration_action(
    record_id: str,
    payload: TrademarkInternationalActionRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:write"))],
) -> TrademarkInternationalActionResponse:
    return record_international_action(
        session,
        context=context,
        record_id=record_id,
        payload=payload,
    )


@router.post(
    "/international-registrations",
    response_model=TrademarkInternationalRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
def international_registration_create(
    payload: TrademarkInternationalRecordCreateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:write"))],
) -> TrademarkInternationalRecordResponse:
    return TrademarkInternationalRecordResponse.model_validate(
        create_international_record(session, context=context, payload=payload)
    )
