"""Matter Documents "OCR & Translate" routes.

Handlers are synchronous so FastAPI runs their database and storage work in
its threadpool, never on the event loop. Provider calls happen only in the
document-processing worker; these routes record and queue work.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status
from fastapi.responses import FileResponse

from caseops_api.api.dependencies import DbSession, get_current_context, require_capability
from caseops_api.schemas.document_renditions import (
    AttachmentRenditionsResponse,
    MatterRenditionsResponse,
    RenditionCreateRequest,
    RenditionDetail,
    RenditionMutationResponse,
    RenditionReviewRequest,
    RenditionSummary,
    TranslationCreateRequest,
)
from caseops_api.services import document_renditions as service
from caseops_api.services.document_dispatch import dispatch_document_processing_job
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
DocumentUploader = Annotated[SessionContext, Depends(require_capability("documents:upload"))]
DocumentManager = Annotated[SessionContext, Depends(require_capability("documents:manage"))]
_BASE = "/{matter_id}/attachments/{attachment_id}/renditions"


def _dispatch(
    session: DbSession, background_tasks: BackgroundTasks, job_id: str | None,
    response: Response,
) -> None:
    if job_id is None:
        # Duplicate request: the open run is returned and nothing new is queued.
        response.status_code = status.HTTP_200_OK
        return
    dispatch_document_processing_job(
        session=session, background_tasks=background_tasks, job_id=job_id,
    )


@router.get(
    "/{matter_id}/document-renditions",
    response_model=MatterRenditionsResponse,
    summary="List the latest OCR and translation version of each matter document",
)
def list_matter_document_renditions(
    matter_id: str, context: CurrentContext, session: DbSession,
) -> MatterRenditionsResponse:
    return service.list_matter_renditions(session, context=context, matter_id=matter_id)


@router.get(
    _BASE,
    response_model=AttachmentRenditionsResponse,
    summary="List OCR and translation versions of a matter document",
)
def list_attachment_renditions(
    matter_id: str, attachment_id: str, context: CurrentContext, session: DbSession,
) -> AttachmentRenditionsResponse:
    return service.get_attachment_renditions(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
    )


@router.post(
    _BASE,
    response_model=RenditionMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run OCR on a matter document, optionally followed by translation",
    responses={200: {"description": "An OCR run is already in progress; it is returned."}},
)
def create_attachment_rendition(
    matter_id: str,
    attachment_id: str,
    payload: RenditionCreateRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    context: DocumentUploader,
    session: DbSession,
) -> RenditionMutationResponse:
    result, job_id = service.create_ocr_rendition(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        payload=payload,
    )
    _dispatch(session, background_tasks, job_id, response)
    return result


@router.post(
    _BASE + "/{rendition_id}/translations",
    response_model=RenditionMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Translate a finished OCR version of a matter document",
    responses={200: {"description": "A translation is already in progress; it is returned."}},
)
def create_rendition_translation(
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    payload: TranslationCreateRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    context: DocumentUploader,
    session: DbSession,
) -> RenditionMutationResponse:
    result, job_id = service.create_translation_rendition(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        ocr_rendition_id=rendition_id, payload=payload,
    )
    _dispatch(session, background_tasks, job_id, response)
    return result


@router.post(
    _BASE + "/{rendition_id}/retry",
    response_model=RenditionMutationResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a failed or partly failed OCR or translation version",
    responses={200: {"description": "The version is already running; it is returned."}},
)
def retry_attachment_rendition(
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    background_tasks: BackgroundTasks,
    response: Response,
    context: DocumentUploader,
    session: DbSession,
) -> RenditionMutationResponse:
    result, job_id = service.retry_rendition(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        rendition_id=rendition_id,
    )
    _dispatch(session, background_tasks, job_id, response)
    return result


@router.post(
    _BASE + "/{rendition_id}/review",
    response_model=RenditionSummary,
    summary="Mark an OCR or translation version reviewed or needing correction",
)
def review_attachment_rendition(
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    payload: RenditionReviewRequest,
    context: DocumentManager,
    session: DbSession,
) -> RenditionSummary:
    return service.review_rendition(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        rendition_id=rendition_id, payload=payload,
    )


@router.get(
    _BASE + "/{rendition_id}",
    response_model=RenditionDetail,
    summary="Read an OCR or translation version page by page",
)
def get_attachment_rendition(
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    context: CurrentContext,
    session: DbSession,
) -> RenditionDetail:
    return service.get_rendition_detail(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        rendition_id=rendition_id,
    )


@router.get(
    _BASE + "/{rendition_id}/download",
    response_class=FileResponse,
    summary="Download the translated PDF of a matter document",
    responses={200: {"content": {"application/pdf": {}}, "description": "Translated PDF."}},
)
def download_attachment_rendition(
    matter_id: str,
    attachment_id: str,
    rendition_id: str,
    context: CurrentContext,
    session: DbSession,
) -> FileResponse:
    path, filename = service.get_rendition_download(
        session, context=context, matter_id=matter_id, attachment_id=attachment_id,
        rendition_id=rendition_id,
    )
    return FileResponse(
        path=path,
        media_type="application/pdf",
        filename=filename,
        content_disposition_type="attachment",
        headers={
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
        },
    )
