from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
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
    MatterCreateRequest,
    MatterHearingCreateRequest,
    MatterHearingRecord,
    MatterListResponse,
    MatterNoteCreateRequest,
    MatterNoteRecord,
    MatterRecord,
    MatterUpdateRequest,
    MatterWorkspaceResponse,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matters import (
    create_matter,
    create_matter_attachment,
    create_matter_hearing,
    create_matter_invoice,
    create_matter_note,
    create_time_entry,
    get_matter,
    get_matter_attachment_download,
    get_matter_workspace,
    list_matters,
    update_matter,
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
    context: CurrentContext,
    session: DbSession,
) -> MatterAttachmentRecord:
    return create_matter_attachment(
        session,
        context=context,
        matter_id=matter_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        stream=file.file,
    )


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
