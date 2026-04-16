from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.ai import MatterBriefGenerateRequest, MatterBriefResponse
from caseops_api.services.briefing import generate_matter_brief
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.post(
    "/matters/{matter_id}/briefs/generate",
    response_model=MatterBriefResponse,
    summary="Generate a matter summary or hearing preparation brief",
)
async def generate_current_company_matter_brief(
    matter_id: str,
    payload: MatterBriefGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterBriefResponse:
    return generate_matter_brief(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )
