from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.drive import (
    DriveCandidateListResponse,
    DriveCandidateReviewRequest,
    DriveCandidateReviewResponse,
    DriveCandidateSyncRequest,
    DriveCandidateSyncResponse,
    DriveSyncControlRecord,
    DriveSyncControlUpdateRequest,
    GoogleDriveConnectionCallbackResponse,
    GoogleDriveConnectionRecord,
    GoogleDriveConnectionStartResponse,
    GoogleDriveFileListResponse,
    GoogleDriveStatusResponse,
)
from caseops_api.services.drive_sync import (
    complete_google_drive_connection,
    get_drive_sync_control,
    list_drive_candidates,
    list_google_drive_files,
    list_google_drive_status,
    review_drive_candidate,
    revoke_google_drive_connection,
    start_google_drive_connection,
    sync_google_drive_candidates,
    update_drive_sync_control,
)
from caseops_api.services.identity import SessionContext

router = APIRouter()
DriveViewer = Annotated[SessionContext, Depends(require_capability("documents:upload"))]
WorkspaceAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]


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


@router.get(
    "/google/controls",
    response_model=DriveSyncControlRecord,
    summary="Read tenant Google Drive review/import controls.",
)
async def get_google_drive_controls(
    context: WorkspaceAdmin,
    session: DbSession,
) -> DriveSyncControlRecord:
    return get_drive_sync_control(session, context=context)


@router.patch(
    "/google/controls",
    response_model=DriveSyncControlRecord,
    summary="Update tenant Google Drive controls without enabling auto-import.",
)
async def patch_google_drive_controls(
    payload: DriveSyncControlUpdateRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> DriveSyncControlRecord:
    return update_drive_sync_control(session, context=context, payload=payload)


@router.post(
    "/google/candidates/sync",
    response_model=DriveCandidateSyncResponse,
    summary="Sync Google Drive file metadata into a review-first queue.",
)
async def post_google_drive_candidate_sync(
    payload: DriveCandidateSyncRequest,
    context: DriveViewer,
    session: DbSession,
) -> DriveCandidateSyncResponse:
    return sync_google_drive_candidates(session, context=context, payload=payload)


@router.get(
    "/candidates",
    response_model=DriveCandidateListResponse,
    summary="List tenant-safe Drive file candidates.",
)
async def get_drive_candidates(
    context: DriveViewer,
    session: DbSession,
    provider: str | None = Query(default=None),
    matter_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DriveCandidateListResponse:
    return list_drive_candidates(
        session,
        context=context,
        provider=provider,
        matter_id=matter_id,
        status_filter=status_filter,
        q=q,
        limit=limit,
    )


@router.patch(
    "/candidates/{candidate_id}",
    response_model=DriveCandidateReviewResponse,
    summary="Review one Drive candidate and optionally import its content.",
)
async def patch_drive_candidate(
    candidate_id: str,
    payload: DriveCandidateReviewRequest,
    context: DriveViewer,
    session: DbSession,
) -> DriveCandidateReviewResponse:
    return review_drive_candidate(
        session,
        context=context,
        candidate_id=candidate_id,
        payload=payload,
    )
