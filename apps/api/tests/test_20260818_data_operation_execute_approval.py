"""The dry-run-only fence is replaced by a four-eyes fence, not removed.

``tenant_data_operations`` governs tenant export, retention purge, offboarding
and restore validation - the operations that can destroy or export a client's
entire record set. Three CHECK constraints pinned it to dry run, and
DATA-GOV-06/08 require an execute path, so those constraints had to move.

The dangerous way to do that is to drop them. The table had no approver columns,
so relaxing the fence would have removed the last-resort guarantee and put
nothing in its place - every control would then live in application code, on the
one table where a bug deletes a firm's matters.

These tests assert the replacement is strictly stronger where it matters: a
dry-run row is exactly as constrained as before, and an execute row is
impossible without a distinct, company-scoped approver. They talk to the
database directly rather than through a service, because a CHECK constraint is
the guarantee that survives a service bug.
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
def company_id(client) -> str:
    return str(bootstrap_company(client)["company"]["id"])


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    # Without depending on `client` this reaches for the configured production
    # DSN and times out against Postgres rather than using the test schema.
    with get_session_factory()() as active:
        yield active


def _membership(session: Session, company_id: str) -> str:
    user = User(
        email=f"op-{uuid4().hex[:8]}@fixture.example",
        full_name="Operation Actor",
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
    approved against. Each negative case below must still fail for the reason
    it is testing, not because it forgot to cite one.
    """
    dry_run = _operation(company_id)
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
        "request_evidence_ref": "ticket://fence",
        "requester_label_snapshot": "Requester",
        "dry_run_completed_at": now,
        "manifest_hash": "b" * 64,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return TenantDataOperation(**values)  # type: ignore[arg-type]


class TestDryRunIsStillFenced:
    def test_a_plain_dry_run_still_inserts(self, session: Session, company_id: str) -> None:
        session.add(_operation(company_id))
        session.flush()

    def test_a_dry_run_cannot_carry_an_approval(
        self, session: Session, company_id: str
    ) -> None:
        # Otherwise an approved execute could be relabelled a simulation while
        # keeping its signature, or a simulation could accrue one for later use.
        session.add(_operation(company_id, approval_status="approved"))

        with pytest.raises(IntegrityError):
            session.flush()


class TestExecuteRequiresASecondPerson:
    def test_execute_without_approval_is_rejected(
        self, session: Session, company_id: str
    ) -> None:
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approves_operation_id=_reviewed_manifest(session, company_id),
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_execute_with_approved_status_but_no_approver_is_rejected(
        self, session: Session, company_id: str
    ) -> None:
        # The status alone must not be sufficient - it is a string a bug can set.
        requester = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approval_status="approved",
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_execute_approved_by_the_requester_is_rejected(
        self, session: Session, company_id: str
    ) -> None:
        # Four eyes. The person who asks for a purge cannot authorise it.
        requester = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approval_status="approved",
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=requester,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Requester",
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()

    def test_execute_with_a_distinct_company_scoped_approver_is_accepted(
        self, session: Session, company_id: str
    ) -> None:
        # The positive case must work, or the fence is just a wall.
        requester = _membership(session, company_id)
        approver = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approval_status="approved",
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=approver,
                approved_by_membership_company_id=company_id,
                approver_label_snapshot="Approver",
            )
        )
        session.flush()

    def test_an_approver_from_another_company_is_rejected(
        self, session: Session, company_id: str
    ) -> None:
        # Cross-tenant approval would let one firm authorise another firm's purge.
        requester = _membership(session, company_id)
        approver = _membership(session, company_id)
        session.add(
            _operation(
                company_id,
                execution_mode="execute",
                status="planned",
                approves_operation_id=_reviewed_manifest(session, company_id),
                approval_status="approved",
                approved_at=datetime.now(UTC),
                requested_by_membership_id=requester,
                requested_by_membership_company_id=company_id,
                approved_by_membership_id=approver,
                approved_by_membership_company_id=str(uuid4()),
                approver_label_snapshot="Foreign approver",
            )
        )

        with pytest.raises(IntegrityError):
            session.flush()


class TestItemsRemainNonExecutable:
    def test_safe_to_execute_is_still_pinned_false(self) -> None:
        # This migration deliberately does NOT touch
        # ck_tenant_data_operation_item_never_execute. Items become executable
        # when the execute SERVICE exists, not when the schema can express it.
        from caseops_api.db.models import TenantDataOperationItem

        names = {
            constraint.name
            for constraint in TenantDataOperationItem.__table__.constraints
            if type(constraint).__name__ == "CheckConstraint"
        }

        assert "ck_tenant_data_operation_item_never_execute" in names
