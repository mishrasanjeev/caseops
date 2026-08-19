"""The approval request and rejection states must be reachable.

20260818_0001 shipped an approval_status enum of four values alongside two
constraints that, together, made two of them impossible:

    dry_run  =>  approval_status = 'not_requested'
    execute  =>  approval_status = 'approved'

A dry run could not hold 'requested' or 'rejected', and an execute row had to be
approved already. So there was no way to record that an operator submitted a
manifest for approval, or that an approver refused it - a rejection would have
had to be represented by deleting the dry run, destroying the evidence that
someone asked and was told no.

The intended property was narrower than what was written: a dry run must never
be APPROVED, so an approved execute cannot be relabelled a simulation while
keeping its signature. These tests assert the narrow property still holds and
that the two states are now reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import CompanyMembership, TenantDataOperation, User
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def company_id(client) -> str:
    return str(bootstrap_company(client)["company"]["id"])


def _membership(session: Session, company_id: str) -> str:
    user = User(
        email=f"appr-{uuid4().hex[:8]}@fixture.example",
        full_name="Approval Actor",
        password_hash="fixture-only",
    )
    session.add(user)
    session.flush()
    membership = CompanyMembership(company_id=company_id, user_id=user.id, role="admin")
    session.add(membership)
    session.flush()
    return membership.id


def _reviewed_manifest(session: Session, company_id: str) -> str:
    """A completed dry run for an execute row to cite.

    20260820_0001 requires every execute row to name the manifest it was
    approved against, so these fixtures now build the thing that was reviewed
    instead of an execute row that appeared from nowhere.
    """
    dry_run = _operation(company_id, approval_status="requested")
    session.add(dry_run)
    session.flush()
    return dry_run.id


def _operation(company_id: str, **overrides: object) -> TenantDataOperation:
    now = datetime.now(UTC)
    values: dict = {
        "company_id": company_id,
        "operation_type": "tenant_export",
        "execution_mode": "dry_run",
        "status": "dry_run_complete",
        "approval_status": "not_requested",
        "request_scope_json": {"schema_version": 2},
        "request_scope_hash": "a" * 64,
        "request_evidence_ref": "ticket://approval",
        "requester_label_snapshot": "Requester",
        "dry_run_completed_at": now,
        "manifest_hash": "b" * 64,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return TenantDataOperation(**values)  # type: ignore[arg-type]


class TestRequestStatesAreReachable:
    @pytest.mark.parametrize("status", ["requested", "rejected"])
    def test_a_dry_run_can_hold_the_state(
        self, session: Session, company_id: str, status: str
    ) -> None:
        # Both of these raised ck_tenant_data_operation_dry_run_unapproved before.
        session.add(
            _operation(
                company_id,
                approval_status=status,
                rejection_reason="scope too broad" if status == "rejected" else None,
            )
        )
        session.flush()

    def test_a_rejection_preserves_the_manifest(
        self, session: Session, company_id: str
    ) -> None:
        # The point of a reachable 'rejected': the record of someone asking and
        # being refused survives, instead of the manifest being deleted.
        operation = _operation(company_id, approval_status="requested")
        session.add(operation)
        session.flush()

        operation.approval_status = "rejected"
        operation.rejection_reason = "scope too broad"
        session.flush()

        assert operation.manifest_hash == "b" * 64
        assert operation.request_evidence_ref == "ticket://approval"


class TestTheSafetyPropertyStillHolds:
    def test_a_dry_run_still_cannot_be_approved(
        self, session: Session, company_id: str
    ) -> None:
        # The narrow property the original constraint was reaching for. If this
        # ever passes, an approved execute could be relabelled a simulation
        # while keeping its approver's signature.
        session.add(_operation(company_id, approval_status="approved"))

        with pytest.raises(IntegrityError):
            session.flush()

    def test_execute_still_requires_a_distinct_approver(
        self, session: Session, company_id: str
    ) -> None:
        requester = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approval_status="approved",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=requester,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Self",
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_execute_still_requires_approval(
        self, session: Session, company_id: str
    ) -> None:
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approval_status="requested",
                approves_operation_id=_reviewed_manifest(session, company_id),
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_the_approved_execute_path_still_works(
        self, session: Session, company_id: str
    ) -> None:
        # The positive case must survive a constraint change, or the fence has
        # quietly become a wall.
        requester = _membership(session, company_id)
        approver = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approval_status="approved",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=approver,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Approver",
            )
        )
        session.flush()


class TestEveryEnumValueIsNowReachable:
    def test_no_declared_approval_status_is_dead(
        self, session: Session, company_id: str
    ) -> None:
        # The regression that started this: an enum value no row can hold is a
        # promise the schema cannot keep.
        reachable = set()

        for status in ("not_requested", "requested", "rejected"):
            session.add(
                _operation(
                    company_id,
                    approval_status=status,
                    rejection_reason="scope too broad" if status == "rejected" else None,
                )
            )
            session.flush()
            reachable.add(status)

        requester = _membership(session, company_id)
        approver = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approval_status="approved",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=approver,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Approver",
            )
        )
        session.flush()
        reachable.add("approved")

        assert reachable == {"not_requested", "requested", "approved", "rejected"}
