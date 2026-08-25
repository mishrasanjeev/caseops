"""IPLF-059A foreign-associate coordination API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_any_capability, require_capability
from caseops_api.schemas.ip_foreign_associates import (
    IpForeignAssociateCreateRequest,
    IpForeignAssociatePageResponse,
    IpForeignAssociateResponse,
    IpForeignAssociateStatus,
    IpForeignAssociateTransactionRequest,
    IpForeignAssociateTransactionResponse,
    IpForeignAssociateWorkspaceResponse,
)
from caseops_api.services.ip_foreign_associates import (
    create_ip_foreign_associate_instruction,
    get_ip_foreign_associate_instruction,
    ip_foreign_associate_workspace,
    list_ip_foreign_associate_instructions,
    record_ip_foreign_associate_transaction,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


@router.get("/foreign-associate-instructions", response_model=IpForeignAssociatePageResponse)
def foreign_associate_instruction_list(
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    docket_id: Annotated[str | None, Query()] = None,
    instruction_status: Annotated[
        IpForeignAssociateStatus | None, Query(alias="status")
    ] = None,
    outstanding_response: Annotated[bool | None, Query()] = None,
    missing_filing_evidence: Annotated[bool | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IpForeignAssociatePageResponse:
    return list_ip_foreign_associate_instructions(
        session,
        context=context,
        docket_id=docket_id,
        instruction_status=instruction_status,
        outstanding_response=outstanding_response,
        missing_filing_evidence=missing_filing_evidence,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/foreign-associate-instructions",
    response_model=IpForeignAssociateResponse,
    status_code=status.HTTP_201_CREATED,
)
def foreign_associate_instruction_create(
    payload: IpForeignAssociateCreateRequest,
    session: DbSession,
    context: Annotated[
        SessionContext,
        Depends(require_any_capability("ip:write", "ip:approve")),
    ],
) -> IpForeignAssociateResponse:
    return IpForeignAssociateResponse.model_validate(
        create_ip_foreign_associate_instruction(session, context=context, payload=payload)
    )


@router.get(
    "/foreign-associate-instructions/{instruction_id}",
    response_model=IpForeignAssociateResponse,
)
def foreign_associate_instruction_get(
    instruction_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> IpForeignAssociateResponse:
    return IpForeignAssociateResponse.model_validate(
        get_ip_foreign_associate_instruction(
            session, context=context, instruction_id=instruction_id
        )
    )


@router.get(
    "/foreign-associate-instructions/{instruction_id}/workspace",
    response_model=IpForeignAssociateWorkspaceResponse,
)
def foreign_associate_instruction_workspace(
    instruction_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> IpForeignAssociateWorkspaceResponse:
    return ip_foreign_associate_workspace(
        session, context=context, instruction_id=instruction_id
    )


@router.post(
    "/foreign-associate-instructions/{instruction_id}/transactions",
    response_model=IpForeignAssociateTransactionResponse,
    status_code=status.HTTP_201_CREATED,
)
def foreign_associate_instruction_transaction(
    instruction_id: str,
    payload: IpForeignAssociateTransactionRequest,
    session: DbSession,
    context: Annotated[
        SessionContext,
        Depends(require_any_capability("ip:write", "ip:approve")),
    ],
) -> IpForeignAssociateTransactionResponse:
    return record_ip_foreign_associate_transaction(
        session,
        context=context,
        instruction_id=instruction_id,
        payload=payload,
    )
