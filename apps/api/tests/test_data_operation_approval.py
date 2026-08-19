"""DATA-GOV-05: the approval workflow for tenant data operations.

The schema fences were built first (20260818_0001, corrected by 20260819_0001):
an execute row is expressible only with a distinct, company-scoped approver, and
a dry run may never hold 'approved'. What had no home until now was the workflow
those fences exist to protect - submitting a manifest, approving it, refusing it.

Two design decisions here are worth stating because a future reader will
otherwise assume they were oversights:

* **Approval requires step-up; refusal does not.** Refusal authorises nothing
  and stops something. Gating the safe direction behind a control that can be
  unavailable would mean an operator who cannot complete MFA also cannot stop a
  pending export.
* **An approved dry run stays 'requested'.** It cannot hold 'approved' by
  constraint, and the execute row is the record of the outcome. So double
  approval is caught by looking for that row, not by reading the state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    TenantDataOperation,
    User,
    UserMFASetting,
    UserMFAStepUp,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_operation_approval import (
    STEP_UP_PURPOSE,
    approve_execution,
    reject_execution,
    request_execution,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def requester(client: TestClient) -> SessionContext:
    bootstrap = bootstrap_company(client)
    with get_session_factory()() as active:
        company = active.get(Company, str(bootstrap["company"]["id"]))
        membership = active.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None and membership is not None
        user = active.get(User, membership.user_id)
        assert user is not None
        active.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


def _colleague(session: Session, company: Company, *, label: str = "Approver") -> SessionContext:
    user = User(
        email=f"{label.lower().replace(' ', '-')}-{uuid4().hex[:8]}@fixture.example",
        full_name=label,
        password_hash="fixture-only",
    )
    session.add(user)
    session.flush()
    membership = CompanyMembership(company_id=company.id, user_id=user.id, role="admin")
    session.add(membership)
    session.flush()
    return SessionContext(company=company, user=user, membership=membership)


def _dry_run(
    session: Session, context: SessionContext, **overrides: object
) -> TenantDataOperation:
    now = datetime.now(UTC)
    values: dict = {
        "company_id": context.company.id,
        "operation_type": "retention_purge",
        "execution_mode": "dry_run",
        "status": "dry_run_complete",
        "approval_status": "not_requested",
        "request_scope_json": {"schema_version": 2},
        "request_scope_hash": "a" * 64,
        "request_evidence_ref": "ticket://purge-4471",
        "requester_label_snapshot": "Records owner",
        "requested_by_membership_id": context.membership.id,
        "requested_by_membership_company_id": context.company.id,
        "manifest_json": {"items": []},
        "manifest_hash": "b" * 64,
        "dry_run_completed_at": now,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    operation = TenantDataOperation(**values)  # type: ignore[arg-type]
    session.add(operation)
    session.flush()
    return operation


def _enrol_mfa(session: Session, context: SessionContext) -> None:
    session.add(UserMFASetting(user_id=context.user.id, status="enrolled"))
    session.flush()


def _complete_step_up(session: Session, context: SessionContext, *, purpose: str) -> None:
    now = datetime.now(UTC)
    session.add(
        UserMFAStepUp(
            user_id=context.user.id,
            membership_id=context.membership.id,
            purpose=purpose,
            method="totp",
            completed_at=now,
            expires_at=now + timedelta(minutes=10),
        )
    )
    session.flush()


def _audit(session: Session, operation_id: str, action: str) -> AuditEvent | None:
    return session.scalar(
        select(AuditEvent).where(
            AuditEvent.target_id == operation_id, AuditEvent.action == action
        )
    )


class TestSubmitting:
    def test_a_completed_manifest_can_be_submitted(
        self, session: Session, requester: SessionContext
    ) -> None:
        operation = _dry_run(session, requester)

        submitted = request_execution(
            session, context=requester, operation_id=operation.id
        )

        assert submitted.approval_status == "requested"
        assert submitted.requested_by_membership_id == requester.membership.id
        audit = _audit(
            session, operation.id, "data_governance.operation.execution_requested"
        )
        assert audit is not None

    def test_an_incomplete_manifest_cannot_be_submitted(
        self, session: Session, requester: SessionContext
    ) -> None:
        # There is nothing to review yet, so there is nothing to approve.
        operation = _dry_run(
            session, requester, status="planned", dry_run_completed_at=None, manifest_hash=None
        )

        with pytest.raises(HTTPException) as excinfo:
            request_execution(session, context=requester, operation_id=operation.id)

        assert excinfo.value.detail["type"] == "data_operation_dry_run_incomplete"

    def test_a_blocked_manifest_cannot_be_submitted(
        self, session: Session, requester: SessionContext
    ) -> None:
        # A manifest blocked by a legal hold must not become approvable by
        # submitting it - the hold is resolved first, or not at all.
        operation = _dry_run(
            session,
            requester,
            status="blocked",
            blocked_reason="active preservation order",
            dry_run_completed_at=None,
            manifest_hash=None,
        )

        with pytest.raises(HTTPException) as excinfo:
            request_execution(session, context=requester, operation_id=operation.id)

        assert excinfo.value.detail["type"] == "data_operation_dry_run_incomplete"

    def test_a_manifest_cannot_be_submitted_twice(
        self, session: Session, requester: SessionContext
    ) -> None:
        operation = _dry_run(session, requester, approval_status="requested")

        with pytest.raises(HTTPException) as excinfo:
            request_execution(session, context=requester, operation_id=operation.id)

        assert excinfo.value.detail["type"] == "data_operation_already_submitted"

    def test_an_execute_row_cannot_be_submitted(
        self, session: Session, requester: SessionContext
    ) -> None:
        # It is already approved; re-submitting it would restart a review that
        # its own existence says has finished.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)
        execution = approve_execution(
            session,
            context=approver,
            operation_id=reviewed.id,
            approver_label="Partner",
        )

        with pytest.raises(HTTPException) as excinfo:
            request_execution(session, context=requester, operation_id=execution.id)

        assert excinfo.value.detail["type"] == "data_operation_not_a_dry_run"

    def test_submitting_does_not_overwrite_the_recorded_requester(
        self, session: Session, requester: SessionContext
    ) -> None:
        # Otherwise the operator who produced the manifest could hand
        # submission to a colleague and then approve it themselves - four eyes
        # measured against the wrong first party.
        operation = _dry_run(session, requester)
        colleague = _colleague(session, requester.company, label="Colleague")

        request_execution(session, context=colleague, operation_id=operation.id)

        assert operation.requested_by_membership_id == requester.membership.id

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=requester,
                operation_id=operation.id,
                approver_label="Records owner",
            )

        assert excinfo.value.detail["type"] == "data_operation_approver_must_be_distinct"


class TestApproving:
    def test_approval_creates_an_execution_citing_the_reviewed_manifest(
        self, session: Session, requester: SessionContext
    ) -> None:
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)

        execution = approve_execution(
            session,
            context=approver,
            operation_id=reviewed.id,
            approver_label="Partner",
        )

        assert execution.id != reviewed.id
        assert execution.execution_mode == "execute"
        assert execution.approval_status == "approved"
        assert execution.status == "planned"
        assert execution.approves_operation_id == reviewed.id
        assert execution.approved_by_membership_id == approver.membership.id
        assert execution.requested_by_membership_id == requester.membership.id
        # The approval covers the manifest that was actually read.
        assert execution.manifest_hash == reviewed.manifest_hash
        assert execution.request_scope_hash == reviewed.request_scope_hash
        assert execution.request_evidence_ref == reviewed.request_evidence_ref
        audit = _audit(
            session, execution.id, "data_governance.operation.execution_approved"
        )
        assert audit is not None

    def test_the_requester_cannot_approve_their_own_manifest(
        self, session: Session, requester: SessionContext
    ) -> None:
        reviewed = _dry_run(session, requester, approval_status="requested")

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=requester,
                operation_id=reviewed.id,
                approver_label="Records owner",
            )

        assert excinfo.value.detail["type"] == "data_operation_approver_must_be_distinct"

    def test_a_manifest_with_no_recorded_requester_cannot_be_approved(
        self, session: Session, requester: SessionContext
    ) -> None:
        # Dual approval is meaningless without a first party, so this fails
        # closed rather than treating the approver as both.
        orphan = _dry_run(
            session,
            requester,
            approval_status="requested",
            requested_by_membership_id=None,
            requested_by_membership_company_id=None,
        )
        approver = _colleague(session, requester.company)

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=approver,
                operation_id=orphan.id,
                approver_label="Partner",
            )

        assert excinfo.value.detail["type"] == "data_operation_has_no_recorded_requester"

    def test_an_unsubmitted_manifest_cannot_be_approved(
        self, session: Session, requester: SessionContext
    ) -> None:
        operation = _dry_run(session, requester)
        approver = _colleague(session, requester.company)

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=approver,
                operation_id=operation.id,
                approver_label="Partner",
            )

        assert excinfo.value.detail["type"] == "data_operation_not_awaiting_approval"

    def test_one_review_cannot_authorise_two_executions(
        self, session: Session, requester: SessionContext
    ) -> None:
        # The dry run stays 'requested' after approval - it may never hold
        # 'approved' - so nothing in its own state stops a second call.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)
        approve_execution(
            session, context=approver, operation_id=reviewed.id, approver_label="Partner"
        )

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=approver,
                operation_id=reviewed.id,
                approver_label="Partner",
            )

        assert excinfo.value.detail["type"] == "data_operation_already_approved"


class TestRefusing:
    def test_a_refusal_is_recorded_with_its_reason(
        self, session: Session, requester: SessionContext
    ) -> None:
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)

        refused = reject_execution(
            session,
            context=approver,
            operation_id=reviewed.id,
            reason="  scope covers matters under an unresolved preservation order  ",
        )

        assert refused.approval_status == "rejected"
        assert refused.rejection_reason == (
            "scope covers matters under an unresolved preservation order"
        )
        # The manifest survives the refusal; that IS the evidence.
        assert refused.manifest_hash == "b" * 64
        assert refused.request_evidence_ref == "ticket://purge-4471"
        audit = _audit(
            session, reviewed.id, "data_governance.operation.execution_rejected"
        )
        assert audit is not None

    def test_a_refusal_must_say_why(
        self, session: Session, requester: SessionContext
    ) -> None:
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)

        with pytest.raises(HTTPException) as excinfo:
            reject_execution(
                session, context=approver, operation_id=reviewed.id, reason="   "
            )

        assert excinfo.value.detail["type"] == "data_operation_rejection_needs_a_reason"
        assert reviewed.approval_status == "requested"

    def test_an_over_long_reason_is_refused_rather_than_truncated(
        self, session: Session, requester: SessionContext
    ) -> None:
        # Cutting it to fit would silently discard the end of an explanation
        # written to be read months from now.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)

        with pytest.raises(HTTPException) as excinfo:
            reject_execution(
                session, context=approver, operation_id=reviewed.id, reason="x" * 501
            )

        assert excinfo.value.detail["type"] == "data_operation_rejection_reason_too_long"
        assert reviewed.approval_status == "requested"
        assert reviewed.rejection_reason is None

    def test_a_refused_manifest_is_terminal(
        self, session: Session, requester: SessionContext
    ) -> None:
        # Whatever the approver objected to may change what the manifest should
        # contain, so the operator produces a fresh dry run rather than
        # re-submitting the one that was refused.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)
        reject_execution(
            session, context=approver, operation_id=reviewed.id, reason="scope too broad"
        )

        with pytest.raises(HTTPException) as resubmit:
            request_execution(session, context=requester, operation_id=reviewed.id)
        assert resubmit.value.detail["type"] == "data_operation_already_submitted"

        with pytest.raises(HTTPException) as approve:
            approve_execution(
                session,
                context=approver,
                operation_id=reviewed.id,
                approver_label="Partner",
            )
        assert approve.value.detail["type"] == "data_operation_not_awaiting_approval"


class TestStepUp:
    def test_step_up_gates_approval_but_not_refusal(
        self, session: Session, requester: SessionContext
    ) -> None:
        # The deliberate asymmetry. An approver who cannot complete MFA must
        # still be able to STOP a pending export; only authorising it is gated.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)
        _enrol_mfa(session, approver)

        with pytest.raises(HTTPException) as excinfo:
            approve_execution(
                session,
                context=approver,
                operation_id=reviewed.id,
                approver_label="Partner",
            )
        assert excinfo.value.status_code == 403

        refused = reject_execution(
            session, context=approver, operation_id=reviewed.id, reason="not now"
        )
        assert refused.approval_status == "rejected"

    def test_a_recent_step_up_admits_the_approval(
        self, session: Session, requester: SessionContext
    ) -> None:
        # The gate must open as well as close, or it is a wall.
        reviewed = _dry_run(session, requester, approval_status="requested")
        approver = _colleague(session, requester.company)
        _enrol_mfa(session, approver)
        _complete_step_up(session, approver, purpose=STEP_UP_PURPOSE)

        execution = approve_execution(
            session,
            context=approver,
            operation_id=reviewed.id,
            approver_label="Partner",
        )

        assert execution.approval_status == "approved"

    def test_the_purpose_is_registered(self) -> None:
        # An unregistered purpose is silently downgraded to a generic "step_up"
        # when recorded, so the audit trail would stop naming this control.
        from caseops_api.services.security import STEP_UP_PURPOSES

        assert STEP_UP_PURPOSE in STEP_UP_PURPOSES


class TestTenantIsolation:
    @pytest.fixture()
    def neighbour(self, session: Session) -> SessionContext:
        company = Company(
            name="Neighbour Legal",
            slug=f"neighbour-{uuid4().hex[:8]}",
            company_type="law_firm",
            tenant_key=f"neighbour-{uuid4().hex[:8]}",
        )
        session.add(company)
        session.flush()
        return _colleague(session, company, label="Neighbour")

    @pytest.mark.parametrize("action", ["request", "approve", "reject"])
    def test_another_tenants_manifest_is_not_found(
        self,
        session: Session,
        requester: SessionContext,
        neighbour: SessionContext,
        action: str,
    ) -> None:
        reviewed = _dry_run(session, requester, approval_status="requested")

        with pytest.raises(HTTPException) as excinfo:
            if action == "request":
                request_execution(session, context=neighbour, operation_id=reviewed.id)
            elif action == "approve":
                approve_execution(
                    session,
                    context=neighbour,
                    operation_id=reviewed.id,
                    approver_label="Neighbour",
                )
            else:
                reject_execution(
                    session,
                    context=neighbour,
                    operation_id=reviewed.id,
                    reason="not mine to refuse",
                )

        assert excinfo.value.status_code == 404


class TestTheSchemaBacksTheService:
    def test_an_execution_must_cite_a_manifest(
        self, session: Session, requester: SessionContext
    ) -> None:
        # Without this an execute row could exist with no reviewed manifest at
        # all, bypassing the review the whole workflow exists to enforce.
        approver = _colleague(session, requester.company)
        now = datetime.now(UTC)
        session.add(
            TenantDataOperation(
                company_id=requester.company.id,
                operation_type="retention_purge",
                execution_mode="execute",
                status="planned",
                approval_status="approved",
                approves_operation_id=None,
                request_scope_json={"schema_version": 2},
                request_scope_hash="a" * 64,
                request_evidence_ref="ticket://forged",
                requester_label_snapshot="Records owner",
                requested_by_membership_id=requester.membership.id,
                requested_by_membership_company_id=requester.company.id,
                approved_by_membership_id=approver.membership.id,
                approved_by_membership_company_id=requester.company.id,
                approver_label_snapshot="Partner",
                approved_at=now,
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_a_refusal_cannot_be_recorded_without_a_reason(
        self, session: Session, requester: SessionContext
    ) -> None:
        session.add(
            TenantDataOperation(
                company_id=requester.company.id,
                operation_type="retention_purge",
                execution_mode="dry_run",
                status="dry_run_complete",
                approval_status="rejected",
                rejection_reason=None,
                request_scope_json={"schema_version": 2},
                request_scope_hash="a" * 64,
                request_evidence_ref="ticket://silent-refusal",
                requester_label_snapshot="Records owner",
                manifest_hash="b" * 64,
                dry_run_completed_at=datetime.now(UTC),
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()
