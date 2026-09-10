"""Non-executable data operations and authenticated preservation for IPLF-028B."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import DbSession, require_capability
from caseops_api.schemas.data_governance import (
    TenantDataClassCatalogResponse,
    TenantDataGovernanceIntegrityReport,
    TenantDataOperationDryRunListResponse,
    TenantDataOperationDryRunRecord,
    TenantDataOperationDryRunRequest,
    TenantDataOperationTenantDryRunRequest,
    TenantLegalHoldSummary,
)
from caseops_api.schemas.legal_holds import (
    HoldDraftRequest,
    HoldListResponse,
    HoldRecord,
    HoldReleaseListResponse,
    HoldReleaseProposal,
    HoldReleaseRequest,
    HoldVersionCommand,
)
from caseops_api.services import legal_hold_workflow
from caseops_api.services.data_governance import (
    create_dry_run_manifest,
    create_tenant_scoped_dry_run_manifest,
    get_dry_run_manifest,
    get_tenant_integrity_report,
    get_tenant_legal_hold_summary,
    list_admissible_data_class_catalog,
    list_dry_run_manifests,
    reject_data_operation_execution,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
DataGovernanceOperator = Annotated[
    SessionContext,
    Depends(require_capability("audit:export")),
]
LegalHoldOperator = Annotated[
    SessionContext,
    Depends(require_capability("legal_holds:manage")),
]


@router.post(
    "/operations/dry-runs",
    response_model=TenantDataOperationDryRunRecord,
    status_code=201,
    summary="Create a non-executable tenant data-operation dry run",
)
def create_operation_dry_run(
    payload: TenantDataOperationDryRunRequest,
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return create_dry_run_manifest(session, context=context, payload=payload)


@router.get(
    "/data-classes",
    response_model=TenantDataClassCatalogResponse,
    summary="List data classes admitted by the current reviewed projection",
)
def list_data_classes(
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataClassCatalogResponse:
    return list_admissible_data_class_catalog(session, context=context)


@router.post(
    "/operations/dry-runs/tenant-scope",
    response_model=TenantDataOperationDryRunRecord,
    status_code=201,
    summary="Create a server-scoped non-executable tenant data-operation dry run",
)
def create_tenant_operation_dry_run(
    payload: TenantDataOperationTenantDryRunRequest,
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return create_tenant_scoped_dry_run_manifest(
        session,
        context=context,
        payload=payload,
    )


@router.get(
    "/integrity",
    response_model=TenantDataGovernanceIntegrityReport,
    summary="Read current tenant data-governance integrity visibility",
)
def read_data_governance_integrity(
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataGovernanceIntegrityReport:
    return get_tenant_integrity_report(session, context=context)


@router.get(
    "/holds/summary",
    response_model=TenantLegalHoldSummary,
    summary="Read aggregate tenant legal-hold preservation state",
)
def read_tenant_legal_hold_summary(
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantLegalHoldSummary:
    return get_tenant_legal_hold_summary(session, context=context)


@router.get("/holds", response_model=HoldListResponse)
def list_preservation_holds(
    context: LegalHoldOperator,
    session: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    before_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> HoldListResponse:
    return legal_hold_workflow.list_holds(
        session, context=context, limit=limit, before_id=before_id
    )


@router.post("/holds", response_model=HoldRecord, status_code=201)
def draft_preservation_hold(
    payload: HoldDraftRequest, context: DataGovernanceOperator, session: DbSession
) -> HoldRecord:
    return legal_hold_workflow.create_hold(session, context=context, payload=payload)


@router.post("/holds/{hold_id}/activate", response_model=HoldRecord)
def activate_preservation_hold(
    hold_id: str, payload: HoldVersionCommand, context: LegalHoldOperator, session: DbSession
) -> HoldRecord:
    return legal_hold_workflow.activate_hold(
        session, context=context, hold_id=hold_id, expected_updated_at=payload.expected_updated_at
    )


@router.get("/holds/{hold_id}/release-requests", response_model=HoldReleaseListResponse)
def list_preservation_release_requests(
    hold_id: str,
    context: LegalHoldOperator,
    session: DbSession,
    limit: int = Query(default=25, ge=1, le=100),
    before_id: str | None = Query(default=None, min_length=1, max_length=36),
) -> HoldReleaseListResponse:
    return legal_hold_workflow.list_release_proposals(
        session, context=context, hold_id=hold_id, limit=limit, before_id=before_id
    )


@router.post(
    "/holds/{hold_id}/release-requests", response_model=HoldReleaseProposal, status_code=201
)
def request_preservation_release(
    hold_id: str, payload: HoldReleaseRequest, context: DataGovernanceOperator, session: DbSession
) -> HoldReleaseProposal:
    return legal_hold_workflow.propose_release(
        session, context=context, hold_id=hold_id, payload=payload
    )


@router.post("/holds/{hold_id}/release-requests/{proposal_id}/approve", response_model=HoldRecord)
def approve_preservation_release(
    hold_id: str,
    proposal_id: str,
    payload: HoldVersionCommand,
    context: LegalHoldOperator,
    session: DbSession,
) -> HoldRecord:
    return legal_hold_workflow.approve_release(
        session,
        context=context,
        hold_id=hold_id,
        proposal_id=proposal_id,
        expected_updated_at=payload.expected_updated_at,
    )


@router.get(
    "/operations/dry-runs",
    response_model=TenantDataOperationDryRunListResponse,
    summary="List non-executable tenant data-operation dry runs",
)
def list_operation_dry_runs(
    context: DataGovernanceOperator,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
) -> TenantDataOperationDryRunListResponse:
    return list_dry_run_manifests(session, context=context, limit=limit)


@router.get(
    "/operations/dry-runs/{operation_id}",
    response_model=TenantDataOperationDryRunRecord,
    summary="Read a non-executable tenant data-operation dry run",
)
def read_operation_dry_run(
    operation_id: str,
    context: DataGovernanceOperator,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return get_dry_run_manifest(session, context=context, operation_id=operation_id)


@router.post(
    "/operations/{operation_id}/execute",
    response_model=None,
    summary="Refuse all tenant data-operation execution",
)
def execute_operation_is_unavailable(
    operation_id: str,
    context: DataGovernanceOperator,
) -> None:
    del context
    reject_data_operation_execution(operation_id=operation_id)
