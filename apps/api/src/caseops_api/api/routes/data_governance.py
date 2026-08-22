"""Evidence-only tenant data-operation routes for IPLF-028B."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from caseops_api.api.dependencies import (
    DbSession,
    require_any_capability,
    require_capability,
)
from caseops_api.db.models import TenantDataOperation
from caseops_api.schemas.data_governance import (
    TenantDataGovernanceIntegrityReport,
    TenantDataOperationApprovalRequest,
    TenantDataOperationDryRunListResponse,
    TenantDataOperationDryRunRecord,
    TenantDataOperationDryRunRequest,
    TenantDataOperationRejectionRequest,
    TenantDataOperationReviewRecord,
    TenantLegalHoldSummary,
)
from caseops_api.services.data_governance import (
    create_dry_run_manifest,
    get_dry_run_manifest,
    get_tenant_integrity_report,
    get_tenant_legal_hold_summary,
    list_dry_run_manifests,
    reject_data_operation_execution,
)
from caseops_api.services.data_operation_approval import (
    approve_execution,
    reject_execution,
    request_execution,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
DataGovernanceOperator = Annotated[
    SessionContext,
    Depends(require_capability("audit:export")),
]
#: The review contract is gated separately from the read-only routes above.
#: Those use ``audit:export``, which is owner-only; a four-eyes control behind
#: an owner-only capability is unsatisfiable for a tenant with one owner,
#: because the only role that can reach it is the role that made the request.
DataOperationReviewer = Annotated[
    SessionContext,
    Depends(require_capability("data_operations:review")),
]
#: Reading a manifest is not exporting a tenant. An owner reads these as
#: oversight; a reviewer reads them because they are being asked to sign one,
#: and an approver who cannot see what needs review or read what they are
#: signing has a signature and nothing to base it on. Gating the read on
#: audit:export alone made the second pair of eyes blind - the same
#: unsatisfiable-four-eyes shape as gating the approval itself would have.
DataOperationManifestReader = Annotated[
    SessionContext,
    Depends(require_any_capability("audit:export", "data_operations:review")),
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


@router.get(
    "/operations/dry-runs",
    response_model=TenantDataOperationDryRunListResponse,
    summary="List reviewable non-executable tenant data-operation dry runs",
)
def list_operation_dry_runs(
    context: DataOperationManifestReader,
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
    context: DataOperationManifestReader,
    session: DbSession,
) -> TenantDataOperationDryRunRecord:
    return get_dry_run_manifest(session, context=context, operation_id=operation_id)


def _review_record(operation: TenantDataOperation) -> TenantDataOperationReviewRecord:
    """Report review state against the MANIFEST id, whichever row we hold.

    ``request_execution`` and ``reject_execution`` return the dry run itself,
    while ``approve_execution`` returns the separate execute row it created. A
    client correlates on the manifest it submitted, so the response always keys
    on that: for an approval the manifest id is the execute row's
    ``approves_operation_id``, and the execute row's own id is reported beside
    it as what the approval authorised.
    """

    if operation.approves_operation_id is not None:
        return TenantDataOperationReviewRecord(
            id=operation.approves_operation_id,
            operation_type=operation.operation_type,
            # The dry run keeps 'requested'; the execute row IS the record that
            # it was approved, so do not invent an 'approved' status here.
            approval_status="requested",
            rejection_reason=None,
            # Copied onto the execute row at approval, so reading them from it
            # reports the manifest that was actually reviewed.
            manifest_hash=operation.manifest_hash,
            request_scope_hash=operation.request_scope_hash,
            approved_operation_id=operation.id,
        )
    return TenantDataOperationReviewRecord(
        id=operation.id,
        operation_type=operation.operation_type,
        approval_status=operation.approval_status,
        rejection_reason=operation.rejection_reason,
        manifest_hash=operation.manifest_hash,
        request_scope_hash=operation.request_scope_hash,
        approved_operation_id=None,
    )


@router.post(
    "/operations/{operation_id}/review/request",
    response_model=TenantDataOperationReviewRecord,
    summary="Submit a completed dry-run manifest for execution approval",
)
def request_operation_review(
    operation_id: str,
    context: DataOperationReviewer,
    session: DbSession,
) -> TenantDataOperationReviewRecord:
    operation = request_execution(session, context=context, operation_id=operation_id)
    session.commit()
    return _review_record(operation)


@router.post(
    "/operations/{operation_id}/review/reject",
    response_model=TenantDataOperationReviewRecord,
    summary="Refuse a submitted manifest, keeping the record of the refusal",
)
def reject_operation_review(
    operation_id: str,
    payload: TenantDataOperationRejectionRequest,
    context: DataOperationReviewer,
    session: DbSession,
) -> TenantDataOperationReviewRecord:
    operation = reject_execution(
        session,
        context=context,
        operation_id=operation_id,
        reason=payload.reason,
    )
    session.commit()
    return _review_record(operation)


@router.post(
    "/operations/{operation_id}/review/approve",
    response_model=TenantDataOperationReviewRecord,
    summary="Approve a submitted manifest under step-up and four eyes",
)
def approve_operation_review(
    operation_id: str,
    payload: TenantDataOperationApprovalRequest,
    context: DataOperationReviewer,
    session: DbSession,
) -> TenantDataOperationReviewRecord:
    """Authorise an execution. This does not perform one.

    The execute route below still refuses unconditionally, and the response
    carries ``executed: false`` so a 200 here cannot be read as "it ran".
    """

    operation = approve_execution(
        session,
        context=context,
        operation_id=operation_id,
        approver_label=payload.approver_label,
    )
    session.commit()
    return _review_record(operation)


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
