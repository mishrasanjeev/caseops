from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.schemas.billing import (
    InvoiceCreateRequest,
    InvoiceRecord,
    TimeEntryCreateRequest,
    TimeEntryRecord,
)
from caseops_api.schemas.matters import (
    MatterAttachmentRecord,
    MatterCourtSyncImportRequest,
    MatterCourtSyncJobRecord,
    MatterCourtSyncPullRequest,
    MatterCourtSyncRunRecord,
    MatterCreateRequest,
    MatterHearingCreateRequest,
    MatterHearingRecord,
    MatterListResponse,
    MatterNoteCreateRequest,
    MatterNoteRecord,
    MatterRecord,
    MatterTaskCreateRequest,
    MatterTaskRecord,
    MatterTaskUpdateRequest,
    MatterUpdateRequest,
    MatterWorkspaceResponse,
)
from caseops_api.services.court_sync_jobs import (
    create_matter_court_sync_job,
    run_matter_court_sync_job,
)
from caseops_api.services.document_jobs import run_document_processing_job
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import (
    create_matter,
    create_matter_attachment,
    create_matter_court_sync_import,
    create_matter_hearing,
    create_matter_invoice,
    create_matter_note,
    create_matter_task,
    create_time_entry,
    get_matter,
    get_matter_attachment_download,
    get_matter_workspace,
    list_matters,
    request_matter_attachment_processing,
    update_matter,
    update_matter_task,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get("/", response_model=MatterListResponse, summary="List matters for the current company")
async def current_company_matters(
    context: CurrentContext,
    session: DbSession,
) -> MatterListResponse:
    return list_matters(session, context=context)


@router.post("/", response_model=MatterRecord, summary="Create a matter in the current company")
async def create_current_company_matter(
    payload: MatterCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterRecord:
    return create_matter(session, context=context, payload=payload)


@router.get("/{matter_id}", response_model=MatterRecord, summary="Get a matter by id")
async def get_current_company_matter(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterRecord:
    return get_matter(session, context=context, matter_id=matter_id)


@router.get(
    "/{matter_id}/workspace",
    response_model=MatterWorkspaceResponse,
    summary="Get the full workspace for a matter",
)
async def get_current_company_matter_workspace(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterWorkspaceResponse:
    return get_matter_workspace(session, context=context, matter_id=matter_id)


@router.patch("/{matter_id}", response_model=MatterRecord, summary="Update a matter")
async def patch_current_company_matter(
    matter_id: str,
    payload: MatterUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterRecord:
    return update_matter(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/notes",
    response_model=MatterNoteRecord,
    summary="Add an internal note to a matter",
)
async def post_current_company_matter_note(
    matter_id: str,
    payload: MatterNoteCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterNoteRecord:
    return create_matter_note(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/tasks",
    response_model=MatterTaskRecord,
    summary="Add a task to a matter workspace",
)
async def post_current_company_matter_task(
    matter_id: str,
    payload: MatterTaskCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterTaskRecord:
    return create_matter_task(session, context=context, matter_id=matter_id, payload=payload)


@router.patch(
    "/{matter_id}/tasks/{task_id}",
    response_model=MatterTaskRecord,
    summary="Update a matter task",
)
async def patch_current_company_matter_task(
    matter_id: str,
    task_id: str,
    payload: MatterTaskUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterTaskRecord:
    return update_matter_task(
        session,
        context=context,
        matter_id=matter_id,
        task_id=task_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/time-entries",
    response_model=TimeEntryRecord,
    summary="Log a time entry against a matter",
)
async def post_current_company_matter_time_entry(
    matter_id: str,
    payload: TimeEntryCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> TimeEntryRecord:
    return create_time_entry(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/hearings",
    response_model=MatterHearingRecord,
    summary="Add a hearing entry to a matter",
)
async def post_current_company_matter_hearing(
    matter_id: str,
    payload: MatterHearingCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterHearingRecord:
    return create_matter_hearing(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/court-sync/import",
    response_model=MatterCourtSyncRunRecord,
    summary="Import cause list and court order data into a matter workspace",
)
async def import_current_company_matter_court_sync(
    matter_id: str,
    payload: MatterCourtSyncImportRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterCourtSyncRunRecord:
    return create_matter_court_sync_import(
        session,
        context=context,
        matter_id=matter_id,
        payload=payload,
    )


@router.post(
    "/{matter_id}/court-sync/pull",
    response_model=MatterCourtSyncJobRecord,
    summary="Queue a live court-data pull for the selected matter",
)
async def pull_current_company_matter_court_sync(
    matter_id: str,
    payload: MatterCourtSyncPullRequest,
    background_tasks: BackgroundTasks,
    context: CurrentContext,
    session: DbSession,
) -> MatterCourtSyncJobRecord:
    job = create_matter_court_sync_job(
        session,
        context=context,
        matter_id=matter_id,
        source=payload.source,
        source_reference=payload.source_reference,
    )
    background_tasks.add_task(run_matter_court_sync_job, job.id)
    return job


@router.post(
    "/{matter_id}/invoices",
    response_model=InvoiceRecord,
    summary="Create a matter invoice",
)
async def post_current_company_matter_invoice(
    matter_id: str,
    payload: InvoiceCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> InvoiceRecord:
    return create_matter_invoice(session, context=context, matter_id=matter_id, payload=payload)


@router.post(
    "/{matter_id}/attachments",
    response_model=MatterAttachmentRecord,
    summary="Upload an attachment into a matter workspace",
)
async def post_current_company_matter_attachment(
    matter_id: str,
    file: Annotated[UploadFile, File(...)],
    background_tasks: BackgroundTasks,
    context: CurrentContext,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = create_matter_attachment(
        session,
        context=context,
        matter_id=matter_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{matter_id}/attachments/{attachment_id}/retry",
    response_model=MatterAttachmentRecord,
    summary="Retry matter attachment processing",
)
async def retry_current_company_matter_attachment_processing(
    matter_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: CurrentContext,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = request_matter_attachment_processing(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        action="retry",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.post(
    "/{matter_id}/attachments/{attachment_id}/reindex",
    response_model=MatterAttachmentRecord,
    summary="Reindex a matter attachment",
)
async def reindex_current_company_matter_attachment(
    matter_id: str,
    attachment_id: str,
    background_tasks: BackgroundTasks,
    context: CurrentContext,
    session: DbSession,
) -> MatterAttachmentRecord:
    attachment, job_id = request_matter_attachment_processing(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
        action="reindex",
    )
    background_tasks.add_task(run_document_processing_job, job_id)
    return attachment


@router.get(
    "/{matter_id}/attachments/{attachment_id}/download",
    response_class=FileResponse,
    summary="Download a matter attachment",
)
async def download_current_company_matter_attachment(
    matter_id: str,
    attachment_id: str,
    context: CurrentContext,
    session: DbSession,
) -> FileResponse:
    attachment, storage_path = get_matter_attachment_download(
        session,
        context=context,
        matter_id=matter_id,
        attachment_id=attachment_id,
    )
    return FileResponse(
        path=storage_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )
