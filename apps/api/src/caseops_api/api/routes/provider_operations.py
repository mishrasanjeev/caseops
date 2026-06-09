from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.provider_operations import (
    ProviderOperationActionRequest,
    ProviderOperationActionResponse,
    ProviderOperationListResponse,
    ProviderReadinessListResponse,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.provider_operations import (
    list_provider_operations,
    provider_readiness_status,
    replay_provider_operation,
    update_provider_operation_state,
)

router = APIRouter()
WorkspaceAdmin = Annotated[
    SessionContext, Depends(require_capability("workspace:admin"))
]


@router.get(
    "/jobs",
    response_model=ProviderOperationListResponse,
    summary="List tenant-scoped failed, blocked, or dead-letter provider operations.",
)
def get_provider_operation_jobs(
    context: WorkspaceAdmin,
    session: DbSession,
    include_resolved: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ProviderOperationListResponse:
    return list_provider_operations(
        session,
        context=context,
        include_resolved=include_resolved,
        limit=limit,
    )


@router.get(
    "/readiness",
    response_model=ProviderReadinessListResponse,
    summary="Read provider readiness gates without exposing secret values.",
)
def get_provider_readiness(
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderReadinessListResponse:
    return provider_readiness_status(session, context=context)


@router.post(
    "/jobs/{operation_id}/replay",
    response_model=ProviderOperationActionResponse,
    summary="Request a safe replay for a tenant-scoped provider operation.",
)
def post_provider_operation_replay(
    operation_id: str,
    payload: ProviderOperationActionRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationActionResponse:
    return replay_provider_operation(
        session,
        context=context,
        operation_id=operation_id,
        reason=payload.reason,
    )


@router.post(
    "/jobs/{operation_id}/ignore",
    response_model=ProviderOperationActionResponse,
    summary="Mark a provider operation ignored with an audit event.",
)
def post_provider_operation_ignore(
    operation_id: str,
    payload: ProviderOperationActionRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationActionResponse:
    return update_provider_operation_state(
        session,
        context=context,
        operation_id=operation_id,
        action="ignore",
        reason=payload.reason,
    )


@router.post(
    "/jobs/{operation_id}/mark-resolved",
    response_model=ProviderOperationActionResponse,
    summary="Mark a provider operation resolved with an audit event.",
)
def post_provider_operation_mark_resolved(
    operation_id: str,
    payload: ProviderOperationActionRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationActionResponse:
    return update_provider_operation_state(
        session,
        context=context,
        operation_id=operation_id,
        action="mark_resolved",
        reason=payload.reason,
    )
