"""IPLF-058A post-registration recordal API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, get_current_context, require_capability
from caseops_api.schemas.ip_recordals import (
    IpRecordalCreateRequest,
    IpRecordalPageResponse,
    IpRecordalResponse,
    IpRecordalStatus,
    IpRecordalTransactionRequest,
    IpRecordalTransactionResponse,
    IpRecordalType,
    IpRecordalWorkspaceResponse,
)
from caseops_api.services.ip_recordals import (
    create_ip_recordal,
    get_ip_recordal,
    ip_recordal_workspace,
    list_ip_recordals,
    record_ip_recordal_transaction,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


@router.get("/recordals", response_model=IpRecordalPageResponse)
def recordal_list(
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    docket_id: Annotated[str | None, Query()] = None,
    recordal_type: Annotated[IpRecordalType | None, Query()] = None,
    recordal_status: Annotated[IpRecordalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IpRecordalPageResponse:
    return list_ip_recordals(
        session,
        context=context,
        docket_id=docket_id,
        recordal_type=recordal_type,
        recordal_status=recordal_status,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/recordals",
    response_model=IpRecordalResponse,
    status_code=status.HTTP_201_CREATED,
)
def recordal_create(
    payload: IpRecordalCreateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:write"))],
) -> IpRecordalResponse:
    return IpRecordalResponse.model_validate(
        create_ip_recordal(session, context=context, payload=payload)
    )


@router.get("/recordals/{recordal_id}", response_model=IpRecordalResponse)
def recordal_get(
    recordal_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> IpRecordalResponse:
    return IpRecordalResponse.model_validate(
        get_ip_recordal(session, context=context, recordal_id=recordal_id)
    )


@router.get(
    "/recordals/{recordal_id}/workspace",
    response_model=IpRecordalWorkspaceResponse,
)
def recordal_workspace(
    recordal_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> IpRecordalWorkspaceResponse:
    return ip_recordal_workspace(
        session,
        context=context,
        recordal_id=recordal_id,
    )


@router.post(
    "/recordals/{recordal_id}/transactions",
    response_model=IpRecordalTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def recordal_transaction(
    recordal_id: str,
    payload: IpRecordalTransactionRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(get_current_context)],
) -> IpRecordalTransactionResponse:
    return record_ip_recordal_transaction(
        session,
        context=context,
        recordal_id=recordal_id,
        payload=payload,
    )
