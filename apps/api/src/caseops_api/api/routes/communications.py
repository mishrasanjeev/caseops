"""Phase B / J12 / M11 — communications log routes.

Mounted under ``/api/matters`` so the URLs stay consistent with the
rest of the matter cockpit surface
(``/api/matters/{matter_id}/communications``).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.communications import (
    CommunicationCreateRequest,
    CommunicationListResponse,
    CommunicationRecord,
    CommunicationTimelineFilter,
    CommunicationTimelineResponse,
    InboundEmailImportRequest,
    InboundEmailImportResponse,
)
from caseops_api.schemas.email_templates import EmailSendRequest
from caseops_api.services.communications import (
    create_matter_communication,
    import_inbound_email,
    list_matter_communication_timeline,
    list_matter_communications,
    send_matter_email,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()

CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
CommunicationsViewer = Annotated[
    SessionContext, Depends(require_capability("communications:view")),
]
CommunicationsWriter = Annotated[
    SessionContext, Depends(require_capability("communications:write")),
]
CommunicationTimelineQuery = Annotated[
    CommunicationTimelineFilter,
    Query(alias="filter"),
]


@router.get(
    "/{matter_id}/communications",
    response_model=CommunicationListResponse,
    summary="List communications recorded against a matter (J12 / M11).",
)
async def list_current_matter_communications(
    matter_id: str,
    context: CommunicationsViewer,
    session: DbSession,
) -> CommunicationListResponse:
    return list_matter_communications(
        session, context=context, matter_id=matter_id,
    )


@router.get(
    "/{matter_id}/communications/timeline",
    response_model=CommunicationTimelineResponse,
    summary="List the unified communications timeline for a matter (ADP-05).",
)
async def list_current_matter_communication_timeline(
    matter_id: str,
    context: CommunicationsViewer,
    session: DbSession,
    selected_filter: CommunicationTimelineQuery = "all",
) -> CommunicationTimelineResponse:
    return list_matter_communication_timeline(
        session,
        context=context,
        matter_id=matter_id,
        selected_filter=selected_filter,
    )


@router.post(
    "/{matter_id}/communications",
    response_model=CommunicationRecord,
    summary="Log a communication against a matter (slice 1: manual entry).",
)
async def post_current_matter_communication(
    matter_id: str,
    payload: CommunicationCreateRequest,
    context: CommunicationsWriter,
    session: DbSession,
) -> CommunicationRecord:
    return create_matter_communication(
        session, context=context, matter_id=matter_id, payload=payload,
    )


@router.post(
    "/{matter_id}/communications/import-email",
    response_model=InboundEmailImportResponse,
    summary="Manually import one inbound email into an explicitly selected matter.",
)
async def import_current_matter_inbound_email(
    matter_id: str,
    payload: InboundEmailImportRequest,
    context: CommunicationsWriter,
    session: DbSession,
) -> InboundEmailImportResponse:
    return import_inbound_email(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/communications/send-email",
    response_model=CommunicationRecord,
    summary="Compose & send an email via a template (Phase B M11 slice 2).",
)
async def send_current_matter_email(
    matter_id: str,
    payload: EmailSendRequest,
    context: CommunicationsWriter,
    session: DbSession,
) -> CommunicationRecord:
    return send_matter_email(
        session, context=context, matter_id=matter_id, payload=payload,
    )
