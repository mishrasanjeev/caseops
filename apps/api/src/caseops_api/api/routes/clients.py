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
    MatterClientAssignmentRecord,
    MatterClientAssignRequest,
)
from caseops_api.services.clients import (
    archive_client,
    assign_client_to_matter,
    create_client,
    get_client,
    list_clients,
    remove_client_from_matter,
    update_client,
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
