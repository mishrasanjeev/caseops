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

Approving is not executing. `approve_execution` produces an authorised operation
in status 'planned' and nothing more - no export is written, no record is
deleted. Execution itself remains unimplemented and still fails closed through
`data_governance.reject_data_operation_execution`. Read the name as "approve the
execution", not "approve and execute".
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    DataRetentionPolicyVersion,
    DataRetentionPolicyVersionStatus,
    TenantDataOperation,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.security import recent_step_up_expires_at
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


def _approved_execution(
    session: Session, *, context: SessionContext, dry_run_id: str
) -> TenantDataOperation | None:
    """The execute row a manifest's approval created, if one exists.

    This is the only durable record that a manifest was approved: the dry run
    itself may never hold 'approved'. Anything that needs to know the review
    outcome has to ask this question rather than read the manifest's status.
    """

    return session.scalar(
        select(TenantDataOperation).where(
            TenantDataOperation.company_id == context.company.id,
            TenantDataOperation.approves_operation_id == dry_run_id,
        )
    )


def _require_step_up_unconditionally(session: Session, *, context: SessionContext) -> None:
    """Demand a recent step-up from the approver, enrolled in MFA or not.

    ``require_recent_step_up`` is conditional by design: it only requires a
    step-up when the caller already has MFA *enrolled*, or when tenant policy
    mandates MFA. That is the right default for ordinary sensitive actions - it
    cannot lock out a tenant that has not adopted MFA yet.

    It is the wrong default here. Authorising an export, purge or offboarding is
    the single most destructive thing this system can be asked to permit, and
    under the conditional rule an approver with no MFA enrolment satisfied the
    control by not having one. The advertised second factor was absent exactly
    where it mattered most, and the existing service tests did not notice
    because each one enrols MFA on the approver first.

    So this fails closed instead: no recent step-up for this purpose, no
    approval. A tenant that has not adopted MFA cannot approve a data operation
    until someone enrols, which is the correct answer rather than an obstacle.
    Rejection stays ungated - refusing is the safe direction, and an approver
    who cannot complete MFA must still be able to stop a pending export.
    """

    if recent_step_up_expires_at(session, context=context, purpose=STEP_UP_PURPOSE):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Approving a tenant data operation always requires a recent MFA "
            f"step-up. Purpose: {STEP_UP_PURPOSE}."
        ),
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

    # An approved manifest KEEPS approval_status 'requested' - the execute row is
    # the record of the outcome - so `_require_submitted` alone lets an approved
    # manifest be rejected afterwards. That would leave the manifest reading
    # 'rejected' beside a live authorised execution in 'planned': two
    # contradictory pieces of approval evidence, with the dangerous one silent.
    #
    # Refuse rather than neutralise. Withdrawing an authorisation someone has
    # already signed is a revocation, and a revocation needs its own recorded
    # actor, reason and audit rather than being a side effect of a reject call.
    # Refusing keeps both records true and names the operation to look at.
    authorised = _approved_execution(session, context=context, dry_run_id=operation.id)
    if authorised is not None:
        raise _conflict(
            "data_operation_already_approved",
            "This manifest was already approved; execution "
            f"{authorised.id} authorises it. A signed authorisation is revoked "
            "explicitly, not by rejecting the manifest afterwards.",
        )

    cleaned = reason.strip()
    if not cleaned:
        raise _conflict(
            "data_operation_rejection_needs_a_reason",
            "A refusal must say why, or the record of it cannot be acted on later.",
        )
    if len(cleaned) > _MAX_REASON_LENGTH:
        # Truncating to fit would silently discard the end of an explanation
        # that exists to be read months from now. Say so instead.
        raise _conflict(
            "data_operation_rejection_reason_too_long",
            f"A refusal reason is limited to {_MAX_REASON_LENGTH} characters; "
            f"this one is {len(cleaned)}.",
        )

    operation.approval_status = "rejected"
    operation.rejection_reason = cleaned
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

    _require_step_up_unconditionally(session, context=context)
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
    already = _approved_execution(session, context=context, dry_run_id=dry_run.id)
    if already is not None:
        raise _conflict(
            "data_operation_already_approved",
            "This manifest has already been approved; execution "
            f"{already.id} authorises it.",
        )

    # A retention purge is BY DEFINITION an act under a retention schedule, and
    # this is the point where it stops being a simulation. Omitting the field was
    # strictly easier than citing an unapproved one - the dry run only checks a
    # version it was given - so the way to skip authorization entirely was to say
    # nothing. Checked here rather than at dry-run time because a dry run is
    # explicitly non-executable: refusing to let an operator SIMULATE a purge
    # before a schedule exists blocks the exploration the manifest is for, while
    # authorizing one without a schedule is the thing DATA-GOV-02 forbids.
    #
    # While no schedule is approved, this makes retention purges unauthorizable.
    # That is the honest consequence of having no schedule.
    if dry_run.operation_type == "retention_purge":
        version_id = dry_run.retention_policy_version_id
        active = None
        if version_id is not None:
            active = session.scalar(
                select(DataRetentionPolicyVersion).where(
                    DataRetentionPolicyVersion.id == version_id,
                    DataRetentionPolicyVersion.company_id == context.company.id,
                    DataRetentionPolicyVersion.status
                    == DataRetentionPolicyVersionStatus.ACTIVE,
                )
            )
        if active is None:
            raise _conflict(
                "retention_purge_requires_an_active_policy_version",
                "A retention purge can only be authorized under an active retention "
                "policy version; this manifest names "
                + (f"{version_id}, which is not active." if version_id else "none."),
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
