"""Approval workflow for tenant data operations (DATA-GOV-05).

The database already refuses an execute row without a distinct, company-scoped
approver and without a link to the manifest that was reviewed. Those constraints
are the guarantee, because they survive a bug in this file. What lives here are
the controls a CHECK constraint cannot express: step-up, which is a property of
the session rather than the row, and the transition rules - who may submit, who
may approve, and in what order.

Approval creates a SEPARATE execute row rather than flipping a flag on the dry
run. The schema forces that shape and it is the right one: a dry run may never
hold 'approved', so an approved execution can never be relabelled a simulation
while keeping the approver's signature.

A rejection is recorded, not deleted. Evidence that someone asked to export or
purge a tenant and was refused is exactly what an audit needs to see later.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import TenantDataOperation
from caseops_api.services.audit import record_from_context
from caseops_api.services.security import require_recent_step_up
from caseops_api.services.session_context import SessionContext

STEP_UP_PURPOSE = "data_operation_execution"
_MAX_REASON_LENGTH = 500


def _now() -> datetime:
    return datetime.now(UTC)


def _load(session: Session, *, context: SessionContext, operation_id: str) -> TenantDataOperation:
    operation = session.get(TenantDataOperation, operation_id)
    if operation is None or operation.company_id != context.company.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Data operation not found."
        )
    return operation


def _conflict(code: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail={"type": code, "detail": detail}
    )


def _require_submitted(operation: TenantDataOperation, *, verb: str) -> None:
    if operation.approval_status != "requested":
        raise _conflict(
            "data_operation_not_awaiting_approval",
            f"Only a submitted manifest can be {verb}; this one is "
            f"{operation.approval_status}.",
        )


def request_execution(
    session: Session, *, context: SessionContext, operation_id: str
) -> TenantDataOperation:
    """Submit a completed dry-run manifest for execution approval.

    No step-up here. Submitting authorises nothing on its own - the manifest
    still cannot execute until a second person approves it under step-up - and
    gating the first half of a two-person control twice buys nothing.
    """

    operation = _load(session, context=context, operation_id=operation_id)
    if operation.execution_mode != "dry_run":
        raise _conflict(
            "data_operation_not_a_dry_run",
            "Only a dry run can be submitted for approval; an execute row is already approved.",
        )
    if operation.status != "dry_run_complete":
        raise _conflict(
            "data_operation_dry_run_incomplete",
            f"The dry run is {operation.status}; only a completed manifest can be submitted.",
        )
    if operation.approval_status != "not_requested":
        raise _conflict(
            "data_operation_already_submitted",
            f"This manifest is already {operation.approval_status}.",
        )

    # The requester is recorded when the dry run is created, and it is what the
    # four-eyes check is measured against. Preserve it rather than overwriting
    # with whoever happens to submit - otherwise the operator who produced the
    # manifest could hand submission to a colleague and then approve it.
    if operation.requested_by_membership_id is None:
        operation.requested_by_membership_id = context.membership.id
        operation.requested_by_membership_company_id = context.company.id

    operation.approval_status = "requested"
    operation.updated_at = _now()
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.operation.execution_requested",
        target_type="tenant_data_operation",
        target_id=operation.id,
        metadata={
            "operation_type": operation.operation_type,
            "manifest_hash": operation.manifest_hash,
            "request_scope_hash": operation.request_scope_hash,
        },
    )
    return operation


def reject_execution(
    session: Session, *, context: SessionContext, operation_id: str, reason: str
) -> TenantDataOperation:
    """Refuse a submitted manifest, keeping the record of the refusal.

    No step-up, deliberately. Refusal is the safe direction: it authorises
    nothing and stops something. Gating it behind a control that can be
    unavailable would mean an operator unable to complete MFA is also unable to
    stop a pending export - the wrong failure mode. Approval, which does
    authorise, is gated. The refusal is audited either way.

    Rejection is terminal. A refused manifest is not re-submittable; the
    operator produces a fresh dry run, which is correct because whatever the
    approver objected to may well change what the manifest should contain.
    """

    operation = _load(session, context=context, operation_id=operation_id)
    _require_submitted(operation, verb="rejected")
    cleaned = reason.strip()
    if not cleaned:
        raise _conflict(
            "data_operation_rejection_needs_a_reason",
            "A refusal must say why, or the record of it cannot be acted on later.",
        )

    operation.approval_status = "rejected"
    operation.rejection_reason = cleaned[:_MAX_REASON_LENGTH]
    operation.updated_at = _now()
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.operation.execution_rejected",
        target_type="tenant_data_operation",
        target_id=operation.id,
        metadata={
            "operation_type": operation.operation_type,
            "manifest_hash": operation.manifest_hash,
            "rejection_reason": operation.rejection_reason,
        },
    )
    return operation


def approve_execution(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
    approver_label: str,
) -> TenantDataOperation:
    """Approve a submitted manifest and create the execute operation.

    The caller IS the approver. Taking an approver id as a parameter would let
    one person record another as having approved, and the step-up satisfied
    would be the caller's rather than the approver's - which is most of the
    control. Four eyes is enforced against the manifest's recorded requester,
    and again by the database.
    """

    require_recent_step_up(session, context=context, purpose=STEP_UP_PURPOSE)
    dry_run = _load(session, context=context, operation_id=operation_id)
    _require_submitted(dry_run, verb="approved")
    if dry_run.requested_by_membership_id is None:
        raise _conflict(
            "data_operation_has_no_recorded_requester",
            "Dual approval is meaningless without a recorded first party.",
        )
    if dry_run.requested_by_membership_id == context.membership.id:
        raise _conflict(
            "data_operation_approver_must_be_distinct",
            "The person who requested this operation cannot approve it.",
        )

    # An approved dry run keeps `approval_status = 'requested'` - it may never
    # hold 'approved', and the execute row IS the record of the outcome. So the
    # state alone cannot say whether this manifest was already approved, and
    # without this check a second call would produce a second authorised
    # execution from one review. uq_tenant_data_operation_approves_operation is
    # the backstop for the concurrent case; this is the clean answer.
    already = session.scalar(
        select(TenantDataOperation).where(
            TenantDataOperation.company_id == context.company.id,
            TenantDataOperation.approves_operation_id == dry_run.id,
        )
    )
    if already is not None:
        raise _conflict(
            "data_operation_already_approved",
            "This manifest has already been approved; execution "
            f"{already.id} authorises it.",
        )

    now = _now()
    execute = TenantDataOperation(
        company_id=dry_run.company_id,
        operation_type=dry_run.operation_type,
        execution_mode="execute",
        status="planned",
        approval_status="approved",
        approves_operation_id=dry_run.id,
        # The execute row carries the SAME scope and manifest as the thing that
        # was reviewed. Approval of one manifest must not license execution of
        # a different one.
        request_scope_json=dry_run.request_scope_json,
        request_scope_hash=dry_run.request_scope_hash,
        request_evidence_ref=dry_run.request_evidence_ref,
        retention_policy_version_id=dry_run.retention_policy_version_id,
        manifest_json=dry_run.manifest_json,
        manifest_hash=dry_run.manifest_hash,
        requested_by_membership_id=dry_run.requested_by_membership_id,
        requested_by_membership_company_id=dry_run.requested_by_membership_company_id,
        requester_label_snapshot=dry_run.requester_label_snapshot,
        approved_by_membership_id=context.membership.id,
        approved_by_membership_company_id=context.company.id,
        approver_label_snapshot=approver_label,
        approved_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(execute)
    session.flush()
    record_from_context(
        session,
        context,
        action="data_governance.operation.execution_approved",
        target_type="tenant_data_operation",
        target_id=execute.id,
        metadata={
            "operation_type": execute.operation_type,
            "approves_operation_id": dry_run.id,
            "manifest_hash": execute.manifest_hash,
            "request_scope_hash": execute.request_scope_hash,
        },
    )
    return execute
