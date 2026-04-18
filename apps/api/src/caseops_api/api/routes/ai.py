from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
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
from caseops_api.schemas.contracts import (
    ClauseExtractionResponse,
    ObligationExtractionResponse,
    PlaybookComparisonFindingRecord,
    PlaybookComparisonResponse,
    PlaybookInstallResponse,
)
from caseops_api.services.briefing import generate_matter_brief
from caseops_api.services.contract_intelligence import (
    compare_playbook,
    extract_clauses,
    extract_obligations,
    install_default_playbook_rules,
)
from caseops_api.services.contract_review import generate_contract_review
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_review import (
    generate_matter_document_review,
    search_matter_documents,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
AIGenerator = Annotated[SessionContext, Depends(require_capability('ai:generate'))]
# Sprint 5 BG-011 — contract intelligence endpoints:
#   extract / obligation-extract / playbook-install are edits
#   (they write rows), so they sit on contracts:edit. The playbook
#   comparison endpoint is an LLM call that only reads; ai:generate
#   is the right gate.
ContractEditor = Annotated[
    SessionContext, Depends(require_capability("contracts:edit"))
]
ContractRuleManager = Annotated[
    SessionContext, Depends(require_capability("contracts:manage_rules"))
]


@router.post(
    "/matters/{matter_id}/briefs/generate",
    response_model=MatterBriefResponse,
    summary="Generate a matter summary or hearing preparation brief",
)
async def generate_current_company_matter_brief(
    matter_id: str,
    payload: MatterBriefGenerateRequest,
    context: AIGenerator,
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
    context: AIGenerator,
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
    context: AIGenerator,
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
    context: AIGenerator,
    session: DbSession,
) -> ContractReviewResponse:
    return generate_contract_review(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


# --- Sprint 5 BG-011 endpoints -----------------------------------------


@router.post(
    "/contracts/{contract_id}/clauses/extract",
    response_model=ClauseExtractionResponse,
    summary="Auto-extract clauses from the contract's uploaded text",
)
async def extract_current_company_contract_clauses(
    contract_id: str,
    context: ContractEditor,
    session: DbSession,
) -> ClauseExtractionResponse:
    result = extract_clauses(session, context=context, contract_id=contract_id)
    session.commit()
    return ClauseExtractionResponse(
        contract_id=result.contract_id,
        inserted=result.inserted,
        removed=result.removed,
        provider=result.provider,
        model=result.model,
    )


@router.post(
    "/contracts/{contract_id}/obligations/extract",
    response_model=ObligationExtractionResponse,
    summary="Auto-extract obligations (payments, notices, renewals) from the contract",
)
async def extract_current_company_contract_obligations(
    contract_id: str,
    context: ContractEditor,
    session: DbSession,
) -> ObligationExtractionResponse:
    result = extract_obligations(session, context=context, contract_id=contract_id)
    session.commit()
    return ObligationExtractionResponse(
        contract_id=result.contract_id,
        inserted=result.inserted,
        removed=result.removed,
        provider=result.provider,
        model=result.model,
    )


@router.post(
    "/contracts/{contract_id}/playbook/install-default",
    response_model=PlaybookInstallResponse,
    summary="Install the default Indian-commercial playbook onto this contract",
)
async def install_default_playbook(
    contract_id: str,
    context: ContractRuleManager,
    session: DbSession,
) -> PlaybookInstallResponse:
    rules = install_default_playbook_rules(
        session, context=context, contract_id=contract_id
    )
    session.commit()
    return PlaybookInstallResponse(contract_id=contract_id, installed=len(rules))


@router.post(
    "/contracts/{contract_id}/playbook/compare",
    response_model=PlaybookComparisonResponse,
    summary="Compare extracted clauses against this contract's playbook rules",
)
async def compare_contract_playbook(
    contract_id: str,
    context: AIGenerator,
    session: DbSession,
) -> PlaybookComparisonResponse:
    result = compare_playbook(session, context=context, contract_id=contract_id)
    return PlaybookComparisonResponse(
        contract_id=result.contract_id,
        findings=[
            PlaybookComparisonFindingRecord(**finding.model_dump())
            for finding in result.findings
        ],
        provider=result.provider,
        model=result.model,
    )
