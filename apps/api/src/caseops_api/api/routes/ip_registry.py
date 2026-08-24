"""IPLF-051 registry reconciliation and court-reference API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.ip_registry import (
    IpRegistryDiffPageResponse,
    IpRegistryDiffResolveRequest,
    IpRegistryDiffResponse,
    IpRegistryFailureRequest,
    IpRegistryLinkCreateRequest,
    IpRegistryLinkMatchDecisionRequest,
    IpRegistryLinkResponse,
    IpRegistryManualSnapshotRequest,
    IpRegistrySnapshotResult,
    IpRegistryWorkspacePageResponse,
    IpTrackedCaseLinkCreateRequest,
    IpTrackedCaseLinkDecisionRequest,
    IpTrackedCaseReferenceResponse,
)
from caseops_api.services.ip_registry import (
    create_registry_link,
    create_tracked_case_reference,
    decide_registry_match,
    decide_tracked_case_reference,
    list_registry_diffs,
    list_registry_workspaces,
    list_tracked_case_references,
    record_manual_snapshot,
    record_registry_failure,
    resolve_registry_diff,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()


@router.get("/registry-links", response_model=IpRegistryWorkspacePageResponse)
def registry_links(
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    docket_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IpRegistryWorkspacePageResponse:
    return list_registry_workspaces(
        session,
        context=context,
        docket_id=docket_id,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/registry-links/{link_id}/diffs",
    response_model=IpRegistryDiffPageResponse,
)
def registry_link_diffs(
    link_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
    resolution: Annotated[str, Query(pattern="^(unresolved|all)$")] = "unresolved",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> IpRegistryDiffPageResponse:
    return list_registry_diffs(
        session,
        context=context,
        link_id=link_id,
        unresolved_only=resolution == "unresolved",
        limit=limit,
        offset=offset,
    )


@router.post(
    "/dockets/{docket_id}/registry-links",
    response_model=IpRegistryLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
def registry_link_create(
    docket_id: str,
    payload: IpRegistryLinkCreateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpRegistryLinkResponse:
    return IpRegistryLinkResponse.model_validate(
        create_registry_link(
            session,
            context=context,
            docket_id=docket_id,
            payload=payload,
        )
    )


@router.post(
    "/registry-links/{link_id}/match-decision",
    response_model=IpRegistryLinkResponse,
)
def registry_link_match_decision(
    link_id: str,
    payload: IpRegistryLinkMatchDecisionRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpRegistryLinkResponse:
    return IpRegistryLinkResponse.model_validate(
        decide_registry_match(
            session,
            context=context,
            link_id=link_id,
            payload=payload,
        )
    )


@router.post(
    "/registry-links/{link_id}/snapshots/manual",
    response_model=IpRegistrySnapshotResult,
    status_code=status.HTTP_201_CREATED,
)
def registry_manual_snapshot(
    link_id: str,
    payload: IpRegistryManualSnapshotRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpRegistrySnapshotResult:
    return record_manual_snapshot(
        session,
        context=context,
        link_id=link_id,
        payload=payload,
    )


@router.post(
    "/registry-links/{link_id}/failures",
    response_model=IpRegistrySnapshotResult,
    status_code=status.HTTP_201_CREATED,
)
def registry_failure(
    link_id: str,
    payload: IpRegistryFailureRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpRegistrySnapshotResult:
    return record_registry_failure(
        session,
        context=context,
        link_id=link_id,
        payload=payload,
    )


@router.post(
    "/registry-diffs/{diff_id}/resolve",
    response_model=IpRegistryDiffResponse,
)
def registry_diff_resolve(
    diff_id: str,
    payload: IpRegistryDiffResolveRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpRegistryDiffResponse:
    return IpRegistryDiffResponse.model_validate(
        resolve_registry_diff(
            session,
            context=context,
            diff_id=diff_id,
            payload=payload,
        )
    )


@router.get(
    "/dockets/{docket_id}/tracked-case-references",
    response_model=list[IpTrackedCaseReferenceResponse],
)
def tracked_case_references(
    docket_id: str,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:read"))],
) -> list[IpTrackedCaseReferenceResponse]:
    return list_tracked_case_references(
        session,
        context=context,
        docket_id=docket_id,
    )


@router.post(
    "/dockets/{docket_id}/tracked-case-references",
    response_model=IpTrackedCaseReferenceResponse,
    status_code=status.HTTP_201_CREATED,
)
def tracked_case_reference_create(
    docket_id: str,
    payload: IpTrackedCaseLinkCreateRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpTrackedCaseReferenceResponse:
    row = create_tracked_case_reference(
        session,
        context=context,
        docket_id=docket_id,
        payload=payload,
    )
    return next(
        item
        for item in list_tracked_case_references(
            session,
            context=context,
            docket_id=row.docket_id,
        )
        if item.id == row.id
    )


@router.post(
    "/tracked-case-references/{link_id}/decision",
    response_model=IpTrackedCaseReferenceResponse,
)
def tracked_case_reference_decision(
    link_id: str,
    payload: IpTrackedCaseLinkDecisionRequest,
    session: DbSession,
    context: Annotated[SessionContext, Depends(require_capability("ip:registry_sync"))],
) -> IpTrackedCaseReferenceResponse:
    row = decide_tracked_case_reference(
        session,
        context=context,
        link_id=link_id,
        payload=payload,
    )
    return next(
        item
        for item in list_tracked_case_references(
            session,
            context=context,
            docket_id=row.docket_id,
        )
        if item.id == row.id
    )
