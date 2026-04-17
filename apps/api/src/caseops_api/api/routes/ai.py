from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.ai import (
    ContractReviewGenerateRequest,
    ContractReviewResponse,
    MatterBriefGenerateRequest,
    MatterBriefResponse,
    MatterDocumentReviewGenerateRequest,
    MatterDocumentReviewResponse,
    MatterDocumentSearchRequest,
    MatterDocumentSearchResponse,
)
from caseops_api.services.briefing import generate_matter_brief
from caseops_api.services.contract_review import generate_contract_review
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_review import (
    generate_matter_document_review,
    search_matter_documents,
)

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


@router.post(
    "/matters/{matter_id}/documents/review",
    response_model=MatterDocumentReviewResponse,
    summary="Generate a structured matter document review from uploaded files",
)
async def generate_current_company_matter_document_review(
    matter_id: str,
    payload: MatterDocumentReviewGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterDocumentReviewResponse:
    return generate_matter_document_review(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.post(
    "/matters/{matter_id}/search",
    response_model=MatterDocumentSearchResponse,
    summary="Search uploaded matter documents for relevant snippets",
)
async def search_current_company_matter_documents(
    matter_id: str,
    payload: MatterDocumentSearchRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterDocumentSearchResponse:
    return search_matter_documents(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.post(
    "/contracts/{contract_id}/reviews/generate",
    response_model=ContractReviewResponse,
    summary="Generate a contract intake review from workspace data and uploaded documents",
)
async def generate_current_company_contract_review(
    contract_id: str,
    payload: ContractReviewGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> ContractReviewResponse:
    return generate_contract_review(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )
