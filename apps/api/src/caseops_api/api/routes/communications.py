"""Phase B / J12 / M11 — communications log routes.

Mounted under ``/api/matters`` so the URLs stay consistent with the
rest of the matter cockpit surface
(``/api/matters/{matter_id}/communications``).
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.communications import (
    CommunicationCreateRequest,
    CommunicationListResponse,
    CommunicationRecord,
)
from caseops_api.services.communications import (
    create_matter_communication,
    list_matter_communications,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()

CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
CommunicationsViewer = Annotated[
    SessionContext, Depends(require_capability("communications:view")),
]
CommunicationsWriter = Annotated[
    SessionContext, Depends(require_capability("communications:write")),
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
