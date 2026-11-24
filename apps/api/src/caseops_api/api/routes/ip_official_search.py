"""IPLF-052D assisted IP India official search API (UJ-07, UJ-31)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import ValidationError

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_official_search import (
    IpOfficialSearchDismissRequest,
    IpOfficialSearchImportPage,
    IpOfficialSearchImportRecord,
    IpOfficialSearchLinkRequest,
    IpOfficialSearchLinkResponse,
    IpOfficialSearchStageRequest,
    IpOfficialSearchUploadMetadata,
    IpOfficialSearchUploadResponse,
)
from caseops_api.services.ip_official_search import (
    create_official_search_import,
    dismiss_official_search_import,
    get_official_search_import,
    link_official_search_import,
    list_official_search_imports,
    stage_official_search_import,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()

IpReader = Annotated[SessionContext, Depends(require_capability("ip:read"))]
IpWriter = Annotated[SessionContext, Depends(require_capability("ip:write"))]
IpRegistrySync = Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))]


@router.get("/official-search/imports", response_model=IpOfficialSearchImportPage)
def official_search_imports(
    session: DbSession,
    context: IpReader,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IpOfficialSearchImportPage:
    return list_official_search_imports(session, context=context, limit=limit, offset=offset)


@router.post(
    "/official-search/imports",
    response_model=IpOfficialSearchUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_official_search_page(
    session: DbSession,
    context: IpWriter,
    metadata_json: Annotated[str, Form()],
    upload: Annotated[UploadFile, File()],
) -> IpOfficialSearchUploadResponse:
    try:
        metadata = IpOfficialSearchUploadMetadata.model_validate_json(metadata_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=exc.errors(include_url=False, include_context=False)
        ) from exc
    return create_official_search_import(
        session,
        context=context,
        metadata=metadata,
        filename=upload.filename or "saved-page",
        content_type=upload.content_type,
        stream=upload.file,
    )


@router.get(
    "/official-search/imports/{import_id}", response_model=IpOfficialSearchImportRecord
)
def official_search_import(
    import_id: str, session: DbSession, context: IpReader
) -> IpOfficialSearchImportRecord:
    return get_official_search_import(session, context=context, import_id=import_id)


@router.post(
    "/official-search/imports/{import_id}/link", response_model=IpOfficialSearchLinkResponse
)
def link_official_search_page(
    import_id: str,
    payload: IpOfficialSearchLinkRequest,
    session: DbSession,
    context: IpRegistrySync,
) -> IpOfficialSearchLinkResponse:
    return link_official_search_import(
        session, context=context, import_id=import_id, payload=payload
    )


@router.post(
    "/official-search/imports/{import_id}/stage-new-record",
    response_model=IpOfficialSearchImportRecord,
)
def stage_official_search_page(
    import_id: str,
    payload: IpOfficialSearchStageRequest,
    session: DbSession,
    context: IpWriter,
) -> IpOfficialSearchImportRecord:
    return stage_official_search_import(
        session, context=context, import_id=import_id, payload=payload
    )


@router.post(
    "/official-search/imports/{import_id}/dismiss",
    response_model=IpOfficialSearchImportRecord,
)
def dismiss_official_search_page(
    import_id: str,
    payload: IpOfficialSearchDismissRequest,
    session: DbSession,
    context: IpWriter,
) -> IpOfficialSearchImportRecord:
    return dismiss_official_search_import(
        session, context=context, import_id=import_id, payload=payload
    )
