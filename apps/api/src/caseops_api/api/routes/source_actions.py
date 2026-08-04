from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from caseops_api.api.dependencies import DbSession, get_current_context, require_capability
from caseops_api.db.models import AuditResult
from caseops_api.schemas.source_actions import (
    SourceActionInspectRequest,
    SourceActionRecord,
    SourceLinkReportCreateRequest,
    SourceLinkReportRecord,
    SourceOriginSurface,
    SourceTargetType,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import (
    assert_safe_source_redirect,
    audit_source_open,
    create_source_link_report,
    inspect_resolved_source_target,
    inspect_source_action,
    resolve_source_target,
)

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
SourceInspector = Annotated[
    SessionContext, Depends(require_capability("authorities:search"))
]


@router.post("/inspect", response_model=SourceActionRecord)
async def inspect_source(
    payload: SourceActionInspectRequest,
    context: SourceInspector,
) -> SourceActionRecord:
    del context
    return inspect_source_action(
        payload.source_reference,
        verified=payload.verified,
        quarantined=payload.quarantined,
    )


@router.get("/open", response_class=RedirectResponse)
async def open_source(
    context: CurrentContext,
    url: Annotated[str, Query(min_length=8, max_length=1000)],
) -> RedirectResponse:
    del context
    try:
        target = assert_safe_source_redirect(url)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return RedirectResponse(
        target,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get(
    "/targets/{target_type}/{target_id}/open",
    response_class=RedirectResponse,
    summary="Open a canonical source without exposing its destination in the request URL",
)
async def open_source_target(
    target_type: SourceTargetType,
    target_id: str,
    context: CurrentContext,
    session: DbSession,
    origin: Annotated[SourceOriginSurface, Query()] = "other",
) -> RedirectResponse:
    target = resolve_source_target(
        session,
        target_type=target_type,
        target_id=target_id,
    )
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source target was not found.",
        )
    action = inspect_resolved_source_target(target)
    if action.state != "available" or not action.source_reference:
        audit_source_open(
            session,
            context=context,
            target=target,
            action=action,
            origin_surface=origin,
            outcome=AuditResult.FAILED,
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"state": action.state, "reason": action.reason},
            headers={"X-Source-State": action.state},
        )
    try:
        destination = assert_safe_source_redirect(action.source_reference)
    except ValueError as exc:
        audit_source_open(
            session,
            context=context,
            target=target,
            action=action,
            origin_surface=origin,
            outcome=AuditResult.FAILED,
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    audit_source_open(
        session,
        context=context,
        target=target,
        action=action,
        origin_surface=origin,
        outcome=AuditResult.SUCCESS,
    )
    session.commit()
    return RedirectResponse(
        destination,
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post(
    "/reports",
    response_model=SourceLinkReportRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Report a wrong or unavailable canonical source",
)
async def report_source_link(
    payload: SourceLinkReportCreateRequest,
    context: CurrentContext,
    session: DbSession,
) -> SourceLinkReportRecord:
    try:
        return create_source_link_report(
            session,
            context=context,
            payload=payload,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
