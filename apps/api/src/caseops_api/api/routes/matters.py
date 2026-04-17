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
from caseops_api.schemas.drafts import (
    DraftCreateRequest,
    DraftGenerateRequest,
    DraftListResponse,
    DraftRecord,
    DraftReviewRequest,
)
from caseops_api.schemas.hearing_packs import (
    HearingPackGenerateRequest,
    HearingPackRecord,
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
    MatterHearingUpdateRequest,
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
from caseops_api.services.drafting import (
    create_draft,
    generate_draft_version,
    get_draft,
    list_drafts,
    load_draft_record,
    transition_draft,
)
from caseops_api.services.hearing_packs import (
    generate_hearing_pack,
    get_latest_hearing_pack,
    mark_hearing_pack_reviewed,
)
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
    update_matter_hearing,
    update_matter_task,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


@router.get("/", response_model=MatterListResponse, summary="List matters for the current company")
async def current_company_matters(
    context: CurrentContext,
    session: DbSession,
    limit: int | None = None,
    cursor: str | None = None,
) -> MatterListResponse:
    return list_matters(session, context=context, limit=limit, cursor=cursor)


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


@router.patch(
    "/{matter_id}/hearings/{hearing_id}",
    response_model=MatterHearingRecord,
    summary="Update a hearing entry (status, outcome, reschedule)",
)
async def patch_current_company_matter_hearing(
    matter_id: str,
    hearing_id: str,
    payload: MatterHearingUpdateRequest,
    context: CurrentContext,
    session: DbSession,
) -> MatterHearingRecord:
    return update_matter_hearing(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
        payload=payload,
    )


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


@router.post(
    "/{matter_id}/hearings/{hearing_id}/pack",
    response_model=HearingPackRecord,
    summary="Generate a hearing pack for this hearing",
)
async def post_current_company_matter_hearing_pack(
    matter_id: str,
    hearing_id: str,
    payload: HearingPackGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> HearingPackRecord:
    # `payload` is accepted for future hooks (focus_note, etc.) but is not
    # used yet; keeping the POST body non-empty gives us room to grow.
    _ = payload
    pack = generate_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
    )
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/pack",
    response_model=HearingPackRecord,
    summary="Generate a hearing pack for the matter's next hearing",
)
async def post_current_company_matter_pack(
    matter_id: str,
    payload: HearingPackGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> HearingPackRecord:
    _ = payload
    pack = generate_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=None,
    )
    return HearingPackRecord.model_validate(pack)


@router.get(
    "/{matter_id}/hearings/{hearing_id}/pack",
    response_model=HearingPackRecord | None,
    summary="Fetch the latest generated pack for this hearing",
)
async def get_current_company_matter_hearing_pack(
    matter_id: str,
    hearing_id: str,
    context: CurrentContext,
    session: DbSession,
) -> HearingPackRecord | None:
    pack = get_latest_hearing_pack(
        session,
        context=context,
        matter_id=matter_id,
        hearing_id=hearing_id,
    )
    if pack is None:
        return None
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/hearing-packs/{pack_id}/review",
    response_model=HearingPackRecord,
    summary="Mark a hearing pack as reviewed by the current user",
)
async def post_current_company_hearing_pack_review(
    matter_id: str,
    pack_id: str,
    context: CurrentContext,
    session: DbSession,
) -> HearingPackRecord:
    pack = mark_hearing_pack_reviewed(
        session,
        context=context,
        matter_id=matter_id,
        pack_id=pack_id,
    )
    return HearingPackRecord.model_validate(pack)


@router.post(
    "/{matter_id}/drafts",
    response_model=DraftRecord,
    summary="Create a new draft shell on a matter",
)
async def post_current_company_matter_draft(
    matter_id: str,
    payload: DraftCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = create_draft(
        session,
        context=context,
        matter_id=matter_id,
        title=payload.title,
        draft_type=payload.draft_type,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.get(
    "/{matter_id}/drafts",
    response_model=DraftListResponse,
    summary="List drafts for this matter",
)
async def get_current_company_matter_drafts(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> DraftListResponse:
    drafts = list_drafts(session, context=context, matter_id=matter_id)
    records = [DraftRecord.model_validate(load_draft_record(d)) for d in drafts]
    return DraftListResponse(drafts=records, next_cursor=None)


@router.get(
    "/{matter_id}/drafts/{draft_id}",
    response_model=DraftRecord,
    summary="Get a specific draft with its version and review history",
)
async def get_current_company_matter_draft(
    matter_id: str,
    draft_id: str,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = get_draft(
        session, context=context, matter_id=matter_id, draft_id=draft_id
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/generate",
    response_model=DraftRecord,
    summary="Generate a new draft version using the LLM",
)
async def post_current_company_matter_draft_generate(
    matter_id: str,
    draft_id: str,
    payload: DraftGenerateRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = generate_draft_version(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        focus_note=payload.focus_note,
        template_key=payload.template_key,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/submit",
    response_model=DraftRecord,
    summary="Submit a draft for partner review",
)
async def post_current_company_matter_draft_submit(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="submit",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/request-changes",
    response_model=DraftRecord,
    summary="Reviewer requests changes on the draft",
)
async def post_current_company_matter_draft_request_changes(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="request_changes",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/approve",
    response_model=DraftRecord,
    summary="Approve an in-review draft (fails closed without verified citations)",
)
async def post_current_company_matter_draft_approve(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="approve",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))


@router.post(
    "/{matter_id}/drafts/{draft_id}/finalize",
    response_model=DraftRecord,
    summary="Finalize an approved draft (terminal state)",
)
async def post_current_company_matter_draft_finalize(
    matter_id: str,
    draft_id: str,
    payload: DraftReviewRequest,
    context: CurrentContext,
    session: DbSession,
) -> DraftRecord:
    draft = transition_draft(
        session,
        context=context,
        matter_id=matter_id,
        draft_id=draft_id,
        action="finalize",
        notes=payload.notes,
    )
    return DraftRecord.model_validate(load_draft_record(draft))
