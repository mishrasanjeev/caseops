from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.provider_operations import (
    CalendarUnknownOutcomeReconciliationRequest,
    CalendarUnknownOutcomeReconciliationResponse,
    ProviderIncidentResolutionRequest,
    ProviderOperationActionRequest,
    ProviderOperationActionResponse,
    ProviderOperationListResponse,
    ProviderOperationRecord,
    ProviderOperationReplayBatchResponse,
    ProviderOperationReplayConfirmRequest,
    ProviderOperationReplayPreviewRequest,
    ProviderOperationReplayPreviewResponse,
    ProviderReadinessListResponse,
)
from caseops_api.services.provider_operations import (
    confirm_provider_operation_replay,
    get_provider_operation,
    list_provider_operations,
    preview_provider_operation_replay,
    provider_readiness_status,
    reconcile_calendar_provider_unknown_outcome,
    resolve_case_tracking_incident,
    update_provider_operation_state,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
WorkspaceAdmin = Annotated[SessionContext, Depends(require_capability("workspace:admin"))]
IpReviewer = Annotated[SessionContext, Depends(require_capability("ip:approve"))]


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
    "/jobs/replay-preview",
    response_model=ProviderOperationReplayPreviewResponse,
    summary="Preview a tenant-scoped bounded provider-operation replay.",
)
def post_provider_operation_replay_preview(
    payload: ProviderOperationReplayPreviewRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationReplayPreviewResponse:
    return preview_provider_operation_replay(
        session,
        context=context,
        operation_ids=payload.operation_ids,
    )


@router.post(
    "/jobs/replay",
    response_model=ProviderOperationReplayBatchResponse,
    summary="Confirm a previewed bounded provider-operation replay.",
)
def post_provider_operation_replay_batch(
    payload: ProviderOperationReplayConfirmRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationReplayBatchResponse:
    return confirm_provider_operation_replay(
        session,
        context=context,
        preview_token=payload.preview_token,
        reason=payload.reason,
    )


@router.post(
    "/jobs/{operation_id}/replay",
    response_model=ProviderOperationActionResponse,
    summary="Request a safe replay for a tenant-scoped provider operation.",
)
def post_provider_operation_replay(
    operation_id: str,
    payload: ProviderOperationReplayConfirmRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationActionResponse:
    response = confirm_provider_operation_replay(
        session,
        context=context,
        preview_token=payload.preview_token,
        reason=payload.reason,
        expected_operation_ids=[operation_id],
    )
    return response.operations[0]


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


@router.get(
    "/jobs/{operation_id}",
    response_model=ProviderOperationRecord,
    summary="Get one exact tenant-scoped provider operation.",
)
def get_provider_operation_job(
    operation_id: str,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationRecord:
    return get_provider_operation(
        session,
        context=context,
        operation_id=operation_id,
    )


@router.post(
    "/jobs/{operation_id}/reconcile-calendar-unknown-outcome",
    response_model=CalendarUnknownOutcomeReconciliationResponse,
    summary="Reconcile an ambiguous calendar create using verified remote evidence.",
)
def post_calendar_unknown_outcome_reconciliation(
    operation_id: str,
    payload: CalendarUnknownOutcomeReconciliationRequest,
    context: IpReviewer,
    session: DbSession,
) -> CalendarUnknownOutcomeReconciliationResponse:
    return reconcile_calendar_provider_unknown_outcome(
        session,
        context=context,
        operation_id=operation_id,
        **payload.model_dump(),
    )


@router.post(
    "/jobs/{operation_id}/resolve-incident",
    response_model=ProviderOperationActionResponse,
    summary="Close a replayed case-tracking incident with root cause and prevention evidence.",
)
def post_case_tracking_incident_resolution(
    operation_id: str,
    payload: ProviderIncidentResolutionRequest,
    context: WorkspaceAdmin,
    session: DbSession,
) -> ProviderOperationActionResponse:
    return resolve_case_tracking_incident(
        session,
        context=context,
        operation_id=operation_id,
        root_cause=payload.root_cause,
        prevention=payload.prevention,
        canary_evidence=payload.canary_evidence,
    )
