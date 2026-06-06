from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.cause_lists import (
    CauseListDownloadResponse,
    CauseListPreviewRequest,
    CauseListPreviewResponse,
)
from caseops_api.services.cause_lists import (
    preview_cause_list,
    render_cause_list_pdf,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
CauseListViewer = Annotated[SessionContext, Depends(require_capability("calendar:view"))]


@router.post(
    "/preview",
    response_model=CauseListPreviewResponse,
    summary="Preview a date-wise cause list for visible matters",
)
async def post_cause_list_preview(
    payload: CauseListPreviewRequest,
    context: CauseListViewer,
    session: DbSession,
) -> CauseListPreviewResponse:
    return preview_cause_list(session, context=context, payload=payload)


@router.post(
    "/download",
    summary="Download a date-wise cause list PDF",
    responses={200: {"content": {"application/pdf": {}}}},
)
async def post_cause_list_download(
    payload: CauseListPreviewRequest,
    context: CauseListViewer,
    session: DbSession,
) -> Response:
    body, filename, checksum, row_count = render_cause_list_pdf(
        session,
        context=context,
        payload=payload,
    )
    _ = CauseListDownloadResponse(
        file_name=filename,
        checksum=checksum,
        row_count=row_count,
    )
    return Response(
        content=body,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-CaseOps-Checksum": checksum,
            "X-CaseOps-Row-Count": str(row_count),
        },
    )
