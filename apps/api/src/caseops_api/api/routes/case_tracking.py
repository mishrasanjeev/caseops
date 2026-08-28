from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.case_tracking import (
    CaseTrackingBookmarkCreateRequest,
    CaseTrackingBookmarkListResponse,
    CaseTrackingBookmarkRecord,
    CaseTrackingBookmarkUpdateRequest,
    CaseTrackingProviderStatusResponse,
    CaseTrackingRefreshResponse,
    CaseTrackingReleaseSmokeRequest,
    CaseTrackingReleaseSmokeResponse,
    CaseTrackingSearchRequest,
    CaseTrackingSearchResponse,
    CaseTrackingUpdateListResponse,
)
from caseops_api.schemas.production_safety import CaseTrackingTenantSupportMatrixResponse
from caseops_api.services.case_tracking import (
    create_bookmark,
    download_case_tracking_source,
    list_bookmarks,
    list_updates,
    provider_status_response,
    refresh_bookmark,
    run_release_smoke,
    search_cases,
    update_bookmark,
)
from caseops_api.services.production_safety import (
    list_support_matrix,
    support_matrix_tenant_record,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
CaseTrackingUser = Annotated[
    SessionContext,
    Depends(require_capability("authorities:search")),
]
CaseTrackingAdmin = Annotated[
    SessionContext,
    Depends(require_capability("workspace:admin")),
]


@router.get(
    "/status",
    response_model=CaseTrackingProviderStatusResponse,
    summary="Return case tracking provider availability without exposing credentials.",
)
def get_case_tracking_status(
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingProviderStatusResponse:
    _ = (context, session)
    return provider_status_response()


@router.get(
    "/support-matrix",
    response_model=CaseTrackingTenantSupportMatrixResponse,
    summary="List tenant-visible court support before a user tracks a case.",
)
def get_case_tracking_support_matrix(
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingTenantSupportMatrixResponse:
    _ = context
    rows = list_support_matrix(session, tenant_visible_only=True)
    return CaseTrackingTenantSupportMatrixResponse(
        rows=[support_matrix_tenant_record(row) for row in rows]
    )


@router.post(
    "/search",
    response_model=CaseTrackingSearchResponse,
    summary="Search configured provider by CNR or case number.",
)
def post_case_tracking_search(
    payload: CaseTrackingSearchRequest,
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingSearchResponse:
    return search_cases(session, context=context, payload=payload)


@router.post(
    "/bookmarks",
    response_model=CaseTrackingBookmarkRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tracked-case bookmark from a provider result.",
)
def post_case_tracking_bookmark(
    payload: CaseTrackingBookmarkCreateRequest,
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingBookmarkRecord:
    return create_bookmark(session, context=context, payload=payload)


@router.get(
    "/bookmarks",
    response_model=CaseTrackingBookmarkListResponse,
    summary="List active case tracking bookmarks for the current user.",
)
def get_case_tracking_bookmarks(
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingBookmarkListResponse:
    return list_bookmarks(session, context=context)


@router.patch(
    "/bookmarks/{bookmark_id}",
    response_model=CaseTrackingBookmarkRecord,
    summary="Rename, toggle notifications, or archive a case tracking bookmark.",
)
def patch_case_tracking_bookmark(
    bookmark_id: str,
    payload: CaseTrackingBookmarkUpdateRequest,
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingBookmarkRecord:
    return update_bookmark(
        session,
        context=context,
        bookmark_id=bookmark_id,
        payload=payload,
    )


@router.post(
    "/bookmarks/{bookmark_id}/refresh",
    response_model=CaseTrackingRefreshResponse,
    summary="Refresh one bookmarked case against the configured provider.",
)
def post_case_tracking_bookmark_refresh(
    bookmark_id: str,
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingRefreshResponse:
    return refresh_bookmark(session, context=context, bookmark_id=bookmark_id)


@router.post(
    "/bookmarks/{bookmark_id}/release-smoke",
    response_model=CaseTrackingReleaseSmokeResponse,
    summary="Run one costed tracked-case canary for the exact deployed release.",
)
def post_case_tracking_release_smoke(
    bookmark_id: str,
    payload: CaseTrackingReleaseSmokeRequest,
    context: CaseTrackingAdmin,
    session: DbSession,
) -> CaseTrackingReleaseSmokeResponse:
    return run_release_smoke(
        session,
        context=context,
        bookmark_id=bookmark_id,
        release_sha=payload.release_sha,
    )


@router.get(
    "/bookmarks/{bookmark_id}/updates",
    response_model=CaseTrackingUpdateListResponse,
    summary="List detected updates for a bookmarked case.",
)
def get_case_tracking_bookmark_updates(
    bookmark_id: str,
    context: CaseTrackingUser,
    session: DbSession,
) -> CaseTrackingUpdateListResponse:
    return list_updates(session, context=context, bookmark_id=bookmark_id)


@router.get(
    "/bookmarks/{bookmark_id}/updates/{update_id}/source",
    summary="Download a tracked-case source document through CaseOps provider auth.",
)
def get_case_tracking_update_source(
    bookmark_id: str,
    update_id: str,
    context: CaseTrackingUser,
    session: DbSession,
) -> Response:
    download = download_case_tracking_source(
        session,
        context=context,
        bookmark_id=bookmark_id,
        update_id=update_id,
    )
    return Response(
        content=download.content,
        media_type=download.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{download.filename}"',
            "X-CaseOps-Source-Format": download.source_format,
        },
    )
