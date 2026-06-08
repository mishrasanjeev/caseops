from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.drive import (
    GoogleDriveConnectionCallbackResponse,
    GoogleDriveConnectionRecord,
    GoogleDriveConnectionStartResponse,
    GoogleDriveFileListResponse,
    GoogleDriveStatusResponse,
)
from caseops_api.services.drive_sync import (
    complete_google_drive_connection,
    list_google_drive_files,
    list_google_drive_status,
    revoke_google_drive_connection,
    start_google_drive_connection,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
DriveViewer = Annotated[SessionContext, Depends(require_capability("documents:upload"))]


@router.get(
    "/google/status",
    response_model=GoogleDriveStatusResponse,
    summary="List the caller's Google Drive connector status.",
)
async def get_google_drive_status(
    context: DriveViewer,
    session: DbSession,
) -> GoogleDriveStatusResponse:
    return list_google_drive_status(session, context=context)


@router.post(
    "/google/start",
    response_model=GoogleDriveConnectionStartResponse,
    summary="Start Google Drive OAuth without exposing tokens.",
)
async def start_google_drive(
    context: DriveViewer,
    session: DbSession,
) -> GoogleDriveConnectionStartResponse:
    return start_google_drive_connection(session, context=context)


@router.get(
    "/google/callback",
    response_model=GoogleDriveConnectionCallbackResponse,
    summary="Complete Google Drive OAuth callback.",
)
async def complete_google_drive(
    context: DriveViewer,
    session: DbSession,
    code: Annotated[str, Query(min_length=1)],
    state: Annotated[str, Query(min_length=1)],
) -> GoogleDriveConnectionCallbackResponse:
    return complete_google_drive_connection(
        session,
        context=context,
        code=code,
        state=state,
    )


@router.delete(
    "/connections/{connection_id}",
    response_model=GoogleDriveConnectionRecord,
    summary="Revoke a Google Drive connection for the current user.",
)
async def revoke_google_drive(
    connection_id: str,
    context: DriveViewer,
    session: DbSession,
) -> GoogleDriveConnectionRecord:
    return revoke_google_drive_connection(
        session,
        context=context,
        connection_id=connection_id,
    )


@router.get(
    "/google/files",
    response_model=GoogleDriveFileListResponse,
    summary="List recent Google Drive file metadata for the current user.",
)
async def get_google_drive_files(
    context: DriveViewer,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> GoogleDriveFileListResponse:
    return list_google_drive_files(session, context=context, limit=limit)
