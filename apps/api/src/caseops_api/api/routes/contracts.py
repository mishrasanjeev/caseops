from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.contracts import (
    ContractAttachmentRecord,
    ContractClauseCreateRequest,
    ContractClauseRecord,
    ContractCreateRequest,
    ContractListResponse,
    ContractObligationCreateRequest,
    ContractObligationRecord,
    ContractPlaybookRuleCreateRequest,
    ContractPlaybookRuleRecord,
    ContractRecord,
    ContractUpdateRequest,
    ContractWorkspaceResponse,
    RedlineChangeRecord,
    RedlineParseResponse,
)
from caseops_api.services.contract_redline import parse_redline_docx
from caseops_api.services.contracts import (
    create_contract,
    create_contract_attachment,
    create_contract_clause,
    create_contract_obligation,
    create_contract_playbook_rule,
    get_contract,
    get_contract_attachment_download,
    get_contract_workspace,
    list_contracts,
    request_contract_attachment_processing,
    update_contract,
)
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
ContractCreator = Annotated[SessionContext, Depends(require_capability('contracts:create'))]
ContractEditor = Annotated[SessionContext, Depends(require_capability('contracts:edit'))]
ContractRuleManager = Annotated[
    SessionContext, Depends(require_capability("contracts:manage_rules"))
]
DocumentUploader = Annotated[SessionContext, Depends(require_capability('documents:upload'))]
DocumentManager = Annotated[SessionContext, Depends(require_capability('documents:manage'))]



@router.get(
    "/",
    response_model=ContractListResponse,
    summary="List contracts for the current company",
)
async def current_company_contracts(
    context: CurrentContext,
    session: DbSession,
    limit: int | None = None,
    cursor: str | None = None,
) -> ContractListResponse:
    return list_contracts(session, context=context, limit=limit, cursor=cursor)


@router.post("/", response_model=ContractRecord, summary="Create a contract in the current company")
async def create_current_company_contract(
    payload: ContractCreateRequest,
    context: ContractCreator,
    session: DbSession,
) -> ContractRecord:
    return create_contract(session, context=context, payload=payload)


@router.get("/{contract_id}", response_model=ContractRecord, summary="Get a contract by id")
async def get_current_company_contract(
    contract_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ContractRecord:
    return get_contract(session, context=context, contract_id=contract_id)


@router.get(
    "/{contract_id}/workspace",
    response_model=ContractWorkspaceResponse,
    summary="Get the full contract workspace",
)
async def get_current_company_contract_workspace(
    contract_id: str,
    context: CurrentContext,
    session: DbSession,
) -> ContractWorkspaceResponse:
    return get_contract_workspace(session, context=context, contract_id=contract_id)


@router.patch("/{contract_id}", response_model=ContractRecord, summary="Update a contract")
async def patch_current_company_contract(
    contract_id: str,
    payload: ContractUpdateRequest,
    context: ContractEditor,
    session: DbSession,
) -> ContractRecord:
    return update_contract(session, context=context, contract_id=contract_id, payload=payload)


@router.post(
    "/{contract_id}/clauses",
    response_model=ContractClauseRecord,
    summary="Add a clause to a contract",
)
async def post_current_company_contract_clause(
    contract_id: str,
    payload: ContractClauseCreateRequest,
    context: ContractEditor,
    session: DbSession,
) -> ContractClauseRecord:
    return create_contract_clause(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


@router.post(
    "/{contract_id}/obligations",
    response_model=ContractObligationRecord,
    summary="Add an obligation to a contract",
)
async def post_current_company_contract_obligation(
    contract_id: str,
    payload: ContractObligationCreateRequest,
    context: ContractEditor,
    session: DbSession,
) -> ContractObligationRecord:
    return create_contract_obligation(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


@router.post(
    "/{contract_id}/playbook-rules",
    response_model=ContractPlaybookRuleRecord,
    summary="Add a playbook rule to a contract",
)
async def post_current_company_contract_playbook_rule(
    contract_id: str,
    payload: ContractPlaybookRuleCreateRequest,
    context: ContractRuleManager,
    session: DbSession,
) -> ContractPlaybookRuleRecord:
    return create_contract_playbook_rule(
        session,
        context=context,
        contract_id=contract_id,
        payload=payload,
    )


@router.post(
    "/{contract_id}/attachments",
    response_model=ContractAttachmentRecord,
    summary="Upload an attachment into a contract workspace",
)
async def post_current_company_contract_attachment(
    contract_id: str,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    context: DocumentUploader,
    session: DbSession,
) -> ContractAttachmentRecord:
    attachment, job_id = create_contract_attachment(
        session,
        context=context,
        contract_id=contract_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{contract_id}/attachments/{attachment_id}/retry",
    response_model=ContractAttachmentRecord,
    summary="Retry contract attachment processing",
)
async def retry_current_company_contract_attachment_processing(
    contract_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: DocumentManager,
    session: DbSession,
) -> ContractAttachmentRecord:
    attachment, job_id = request_contract_attachment_processing(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
        action="retry",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{contract_id}/attachments/{attachment_id}/reindex",
    response_model=ContractAttachmentRecord,
    summary="Reindex a contract attachment",
)
async def reindex_current_company_contract_attachment(
    contract_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: DocumentManager,
    session: DbSession,
) -> ContractAttachmentRecord:
    attachment, job_id = request_contract_attachment_processing(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
        action="reindex",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.get(
    "/{contract_id}/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Download a contract attachment",
)
async def download_current_company_contract_attachment(
    contract_id: str,
    attachment_id: str,
    context: CurrentContext,
    session: DbSession,
) -> FileResponse:
    attachment, storage_path = get_contract_attachment_download(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
    )
    return FileResponse(
        path=storage_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )


@router.get(
    "/{contract_id}/attachments/{attachment_id}/redline",
    response_model=RedlineParseResponse,
    summary="Parse tracked changes out of a counterparty-redlined DOCX",
)
async def parse_contract_attachment_redline(
    contract_id: str,
    attachment_id: str,
    context: CurrentContext,
    session: DbSession,
) -> RedlineParseResponse:
    # Reuse the download path for tenant-scoped fetch + auth; the
    # parser is a pure function over the bytes returned here.
    attachment, storage_path = get_contract_attachment_download(
        session,
        context=context,
        contract_id=contract_id,
        attachment_id=attachment_id,
    )
    result = parse_redline_docx(
        source=storage_path,
        attachment_name=attachment.original_filename,
    )
    return RedlineParseResponse(
        attachment_id=attachment.id,
        attachment_name=result.attachment_name,
        paragraph_count=result.paragraph_count,
        insertion_count=result.insertion_count,
        deletion_count=result.deletion_count,
        author_counts=result.author_counts,
        changes=[
            RedlineChangeRecord(
                index=change.index,
                kind=change.kind,
                author=change.author,
                timestamp=change.timestamp,
                text=change.text,
                paragraph_index=change.paragraph_index,
                context_before=change.context_before,
                context_after=change.context_after,
            )
            for change in result.changes
        ],
    )
