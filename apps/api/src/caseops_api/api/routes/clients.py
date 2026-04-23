"""Clients CRUD routes (MOD-TS-009 / Sprint S1+S2)."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.clients import (
    ClientCreateRequest,
    ClientListResponse,
    ClientRecord,
    ClientUpdateRequest,
    KycRejectRequest,
    KycSubmitRequest,
    MatterClientAssignmentRecord,
    MatterClientAssignRequest,
)
from caseops_api.services.clients import (
    archive_client,
    assign_client_to_matter,
    create_client,
    get_client,
    list_clients,
    reject_client_kyc,
    remove_client_from_matter,
    submit_client_kyc,
    unarchive_client,
    update_client,
    verify_client_kyc,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()

ClientViewer = Annotated[SessionContext, Depends(require_capability("clients:view"))]
ClientCreator = Annotated[SessionContext, Depends(require_capability("clients:create"))]
ClientEditor = Annotated[SessionContext, Depends(require_capability("clients:edit"))]
ClientArchiver = Annotated[SessionContext, Depends(require_capability("clients:archive"))]
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get("/", response_model=ClientListResponse, summary="List clients")
async def get_current_company_clients(
    context: ClientViewer,
    session: DbSession,
) -> ClientListResponse:
    return list_clients(session, context=context)


@router.post("/", response_model=ClientRecord, summary="Create a client")
async def post_current_company_client(
    payload: ClientCreateRequest,
    context: ClientCreator,
    session: DbSession,
) -> ClientRecord:
    return create_client(session, context=context, payload=payload)


@router.get(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Fetch a client profile",
)
async def get_current_company_client(
    client_id: str,
    context: ClientViewer,
    session: DbSession,
) -> ClientRecord:
    return get_client(session, context=context, client_id=client_id)


@router.patch(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Update a client",
)
async def patch_current_company_client(
    client_id: str,
    payload: ClientUpdateRequest,
    context: ClientEditor,
    session: DbSession,
) -> ClientRecord:
    return update_client(
        session, context=context, client_id=client_id, payload=payload,
    )


@router.delete(
    "/{client_id}",
    response_model=ClientRecord,
    summary="Archive a client (soft-delete)",
)
async def archive_current_company_client(
    client_id: str,
    context: ClientArchiver,
    session: DbSession,
) -> ClientRecord:
    return archive_client(session, context=context, client_id=client_id)


@router.post(
    "/{client_id}/unarchive",
    response_model=ClientRecord,
    summary="Restore an archived client (BUG-025).",
)
async def unarchive_current_company_client(
    client_id: str,
    context: ClientArchiver,
    session: DbSession,
) -> ClientRecord:
    # Same capability as archive — only the staff role-set that can
    # archive a client can put one back. Phase B / BUG-025.
    return unarchive_client(session, context=context, client_id=client_id)


# Phase B M11 slice 3 — KYC lifecycle (US-037 / FT-049 / MOD-TS-013).

KycSubmitter = Annotated[
    SessionContext, Depends(require_capability("clients:kyc_submit")),
]
KycReviewer = Annotated[
    SessionContext, Depends(require_capability("clients:kyc_review")),
]


@router.post(
    "/{client_id}/kyc/submit",
    response_model=ClientRecord,
    summary="Submit a KYC pack for review (moves status to pending).",
)
async def submit_current_company_client_kyc(
    client_id: str,
    payload: KycSubmitRequest,
    context: KycSubmitter,
    session: DbSession,
) -> ClientRecord:
    return submit_client_kyc(
        session, context=context, client_id=client_id, payload=payload,
    )


@router.post(
    "/{client_id}/kyc/verify",
    response_model=ClientRecord,
    summary="Approve a submitted KYC pack (staff only).",
)
async def verify_current_company_client_kyc(
    client_id: str,
    context: KycReviewer,
    session: DbSession,
) -> ClientRecord:
    return verify_client_kyc(session, context=context, client_id=client_id)


@router.post(
    "/{client_id}/kyc/reject",
    response_model=ClientRecord,
    summary="Reject a submitted KYC pack with a reason (staff only).",
)
async def reject_current_company_client_kyc(
    client_id: str,
    payload: KycRejectRequest,
    context: KycReviewer,
    session: DbSession,
) -> ClientRecord:
    return reject_client_kyc(
        session, context=context, client_id=client_id, payload=payload,
    )


# ---------------------------------------------------------------
# Per-matter assignment — mounted under /api/matters/… via
# the same router include. Kept here so the full clients surface
# lives in one file.
# ---------------------------------------------------------------


matter_scoped_router = APIRouter()


@matter_scoped_router.post(
    "/{matter_id}/clients",
    response_model=MatterClientAssignmentRecord,
    summary="Link a client to a matter",
)
async def post_matter_client_assignment(
    matter_id: str,
    payload: MatterClientAssignRequest,
    context: ClientEditor,
    session: DbSession,
) -> MatterClientAssignmentRecord:
    return assign_client_to_matter(
        session, context=context, matter_id=matter_id, payload=payload,
    )


@matter_scoped_router.delete(
    "/{matter_id}/clients/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a client from a matter",
)
async def delete_matter_client_assignment(
    matter_id: str,
    client_id: str,
    context: ClientEditor,
    session: DbSession,
) -> Response:
    remove_client_from_matter(
        session, context=context, matter_id=matter_id, client_id=client_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
