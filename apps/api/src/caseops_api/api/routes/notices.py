from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.schemas.notices import (
    NoticeCreateRequest,
    NoticeListFilters,
    NoticeListResponse,
    NoticeOwnerOption,
    NoticeRecord,
    NoticeUpdateRequest,
)
from caseops_api.services.notices import (
    create_notice,
    get_notice,
    get_notice_download,
    list_notice_owners,
    list_notices,
    update_notice,
    upload_notice_file,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()

CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
NoticeCreator = Annotated[
    SessionContext,
    Depends(require_capability("documents:upload")),
]
NoticeManager = Annotated[
    SessionContext,
    Depends(require_capability("documents:manage")),
]
NoticeFileUploader = Annotated[
    SessionContext,
    Depends(require_capability("documents:upload")),
]


@router.get(
    "/",
    response_model=NoticeListResponse,
    summary="List standalone and legacy notices visible to the current company member",
)
async def current_company_notices(
    context: CurrentContext,
    session: DbSession,
    filters: Annotated[NoticeListFilters, Depends()],
) -> NoticeListResponse:
    return list_notices(session, context=context, filters=filters)


@router.post(
    "/",
    response_model=NoticeRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a standalone notice without requiring a document",
)
async def post_current_company_notice(
    payload: NoticeCreateRequest,
    context: NoticeCreator,
    session: DbSession,
) -> NoticeRecord:
    return create_notice(session, context=context, payload=payload)


@router.get(
    "/owners",
    response_model=list[NoticeOwnerOption],
    summary="List active company members eligible for notice assignment",
)
async def get_current_company_notice_owners(
    context: NoticeManager,
    session: DbSession,
) -> list[NoticeOwnerOption]:
    return list_notice_owners(session, context=context)


@router.get(
    "/{notice_id}",
    response_model=NoticeRecord,
    summary="Get a visible standalone or primary legacy notice",
)
async def get_current_company_notice(
    notice_id: str,
    context: CurrentContext,
    session: DbSession,
) -> NoticeRecord:
    return get_notice(
        session,
        context=context,
        notice_id=notice_id,
    )


@router.patch(
    "/{notice_id}",
    response_model=NoticeRecord,
    summary="Update standalone notice metadata, assignment, or matter links",
)
async def patch_current_company_notice(
    notice_id: str,
    payload: NoticeUpdateRequest,
    context: NoticeManager,
    session: DbSession,
) -> NoticeRecord:
    return update_notice(
        session,
        context=context,
        notice_id=notice_id,
        payload=payload,
    )


@router.post(
    "/{notice_id}/file",
    response_model=NoticeRecord,
    summary="Upload or replace the optional file on a standalone notice",
)
async def post_current_company_notice_file(
    notice_id: str,
    expected_updated_at: Annotated[datetime, Form(...)],
    file: Annotated[UploadFile, File(...)],
    context: NoticeFileUploader,
    session: DbSession,
) -> NoticeRecord:
    return upload_notice_file(
        session,
        context=context,
        notice_id=notice_id,
        filename=file.filename or "document",
        content_type=file.content_type,
        expected_updated_at=expected_updated_at,
        stream=file.file,
    )


@router.get(
    "/{notice_id}/download",
    response_class=FileResponse,
    responses={
        200: {
            "description": "Notice document bytes",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
    summary="Download a standalone or legacy notice file",
)
async def download_current_company_notice_file(
    notice_id: str,
    context: CurrentContext,
    session: DbSession,
) -> FileResponse:
    storage_path, filename, content_type = get_notice_download(
        session,
        context=context,
        notice_id=notice_id,
    )
    return FileResponse(
        path=storage_path,
        media_type=content_type or "application/octet-stream",
        filename=filename,
    )


__all__ = ["router"]
