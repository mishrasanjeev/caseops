"""DATA-GOV-05: step-up and dual approval on hold activation and release.

The requirement has three clauses. The middle one was already enforced in the
database - ``ck_legal_hold_activation_approval`` and
``ck_legal_hold_approver_distinct`` refuse an active hold without a distinct,
company-scoped approver - and that constraint is the guarantee, because it
survives a service bug.

The other two could not be enforced there:

- **step-up** is a property of the SESSION, not of the row, so no CHECK
  constraint can express it
- **release never deletes immediately without a new dry-run** is a relationship
  between two records and a clock

Before this there was no hold activation or release path at all, so neither
clause had anywhere to live. These tests assert the service refuses each way it
can be misused, and - equally - that the legitimate path still completes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    LegalHold,
    LegalHoldStatus,
    TenantDataOperation,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.data_governance import activate_legal_hold, release_legal_hold
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def context(client: TestClient) -> SessionContext:
    bootstrap = bootstrap_company(client)
    with get_session_factory()() as session:
        company = session.get(Company, str(bootstrap["company"]["id"]))
        membership = session.get(CompanyMembership, str(bootstrap["membership"]["id"]))
        assert company is not None and membership is not None
        user = session.get(User, membership.user_id)
        assert user is not None
        session.expunge_all()
    return SessionContext(company=company, user=user, membership=membership)


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


def _approver(session: Session, company_id: str) -> str:
    user = User(
        email=f"approver-{uuid4().hex[:8]}@fixture.example",
        full_name="Hold Approver",
        password_hash="fixture-only",
    )
    session.add(user)
    session.flush()
    membership = CompanyMembership(company_id=company_id, user_id=user.id, role="admin")
    session.add(membership)
    session.flush()
    return membership.id


def _draft_hold(session: Session, company_id: str, *, creator_membership_id: str) -> LegalHold:
    # The creator is recorded at DRAFT time and is immutable thereafter, which
    # is how the schema guarantees a first party exists before anyone approves.
    now = datetime.now(UTC)
    hold = LegalHold(
        company_id=company_id,
        key=f"hold-{uuid4().hex[:8]}",
        title="Preservation order",
        authority_reference="Court order 2026/11",
        status=LegalHoldStatus.DRAFT,
        created_by_membership_id=creator_membership_id,
        created_by_membership_company_id=company_id,
        creator_label_snapshot="Records owner",
        created_at=now,
        updated_at=now,
    )
    session.add(hold)
    session.flush()
    return hold


def _dry_run(session: Session, company_id: str, *, completed_at: datetime) -> str:
    now = datetime.now(UTC)
    operation = TenantDataOperation(
        company_id=company_id,
        operation_type="retention_purge",
        execution_mode="dry_run",
        status="dry_run_complete",
        approval_status="not_requested",
        request_scope_json={"schema_version": 2},
        request_scope_hash="a" * 64,
        request_evidence_ref="ticket://release",
        requester_label_snapshot="Requester",
        manifest_hash="b" * 64,
        dry_run_completed_at=completed_at,
        created_at=now,
        updated_at=now,
    )
    session.add(operation)
    session.flush()
    return operation.id


class TestDualApproval:
    def test_the_requester_cannot_approve_their_own_activation(
        self, session: Session, context: SessionContext
    ) -> None:
        hold = _draft_hold(session, context.company.id, creator_membership_id=context.membership.id)

        with pytest.raises(HTTPException) as excinfo:
            activate_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=context.membership.id,
                approver_label="Self",
            )

        assert excinfo.value.status_code == 409
        assert excinfo.value.detail["type"] == "legal_hold_approver_must_be_distinct"

    def test_a_distinct_approver_activates(
        self, session: Session, context: SessionContext
    ) -> None:
        hold = _draft_hold(session, context.company.id, creator_membership_id=context.membership.id)
        approver = _approver(session, context.company.id)

        activated = activate_legal_hold(
            session,
            context=context,
            hold_id=hold.id,
            approver_membership_id=approver,
            approver_label="Approver",
        )

        assert activated.status == LegalHoldStatus.ACTIVE
        assert activated.activated_at is not None
        assert activated.approved_by_membership_id == approver

    def test_only_a_draft_can_be_activated(
        self, session: Session, context: SessionContext
    ) -> None:
        hold = _draft_hold(session, context.company.id, creator_membership_id=context.membership.id)
        approver = _approver(session, context.company.id)
        activate_legal_hold(
            session,
            context=context,
            hold_id=hold.id,
            approver_membership_id=approver,
            approver_label="Approver",
        )

        with pytest.raises(HTTPException) as excinfo:
            activate_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=approver,
                approver_label="Approver",
            )

        assert excinfo.value.detail["type"] == "legal_hold_not_draft"


class TestReleaseRequiresACurrentDryRun:
    """The clause with teeth.

    Releasing a hold does not delete anything by itself - it removes the thing
    that was BLOCKING deletion. So the operator must have seen a current
    manifest of what becomes eligible the moment the hold lifts.
    """

    def _active_hold(self, session: Session, context: SessionContext) -> tuple[LegalHold, str]:
        hold = _draft_hold(session, context.company.id, creator_membership_id=context.membership.id)
        approver = _approver(session, context.company.id)
        activate_legal_hold(
            session,
            context=context,
            hold_id=hold.id,
            approver_membership_id=approver,
            approver_label="Approver",
        )
        return hold, approver

    def test_release_without_a_dry_run_is_refused(
        self, session: Session, context: SessionContext
    ) -> None:
        hold, approver = self._active_hold(session, context)

        with pytest.raises(HTTPException) as excinfo:
            release_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=approver,
                approver_label="Approver",
                release_dry_run_id=str(uuid4()),
            )

        assert excinfo.value.detail["type"] == "legal_hold_release_requires_dry_run"

    def test_a_dry_run_predating_the_hold_is_refused(
        self, session: Session, context: SessionContext
    ) -> None:
        # Otherwise the control is satisfied by a manifest generated before the
        # preserved data even existed.
        hold, approver = self._active_hold(session, context)
        stale = _dry_run(
            session,
            context.company.id,
            completed_at=datetime.now(UTC) - timedelta(days=30),
        )

        with pytest.raises(HTTPException) as excinfo:
            release_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=approver,
                approver_label="Approver",
                release_dry_run_id=stale,
            )

        assert excinfo.value.detail["type"] == "legal_hold_release_dry_run_stale"

    def test_another_companys_dry_run_is_refused(
        self, session: Session, context: SessionContext
    ) -> None:
        # A real second company, not a fabricated id: tenant_data_operations has
        # a foreign key on company_id, so a fake tenant proves nothing about
        # cross-tenant behaviour - it just fails at insert.
        hold, approver = self._active_hold(session, context)
        other = Company(
            name="Other Firm LLP",
            slug=f"other-{uuid4().hex[:8]}",
            company_type="law_firm",
            tenant_key=uuid4().hex,
        )
        session.add(other)
        session.flush()
        foreign = _dry_run(session, other.id, completed_at=datetime.now(UTC))

        with pytest.raises(HTTPException) as excinfo:
            release_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=approver,
                approver_label="Approver",
                release_dry_run_id=foreign,
            )

        assert excinfo.value.detail["type"] == "legal_hold_release_requires_dry_run"

    def test_a_current_dry_run_releases(
        self, session: Session, context: SessionContext
    ) -> None:
        # The positive path must complete, or the control is an outage.
        hold, approver = self._active_hold(session, context)
        current = _dry_run(
            session,
            context.company.id,
            completed_at=datetime.now(UTC) + timedelta(seconds=1),
        )

        released = release_legal_hold(
            session,
            context=context,
            hold_id=hold.id,
            approver_membership_id=approver,
            approver_label="Approver",
            release_dry_run_id=current,
        )

        assert released.status == LegalHoldStatus.RELEASED
        assert released.released_at is not None

    def test_the_requester_cannot_approve_their_own_release(
        self, session: Session, context: SessionContext
    ) -> None:
        hold, _ = self._active_hold(session, context)
        current = _dry_run(
            session, context.company.id, completed_at=datetime.now(UTC) + timedelta(seconds=1)
        )

        with pytest.raises(HTTPException) as excinfo:
            release_legal_hold(
                session,
                context=context,
                hold_id=hold.id,
                approver_membership_id=context.membership.id,
                approver_label="Self",
                release_dry_run_id=current,
            )

        assert excinfo.value.detail["type"] == "legal_hold_approver_must_be_distinct"


class TestStepUpIsWired:
    def test_both_lifecycle_paths_demand_step_up(self) -> None:
        # Step-up is a property of the session, so no CHECK constraint can
        # enforce it. Assert the call exists rather than only its effect.
        import inspect

        from caseops_api.services import data_governance

        for name in ("activate_legal_hold", "release_legal_hold"):
            source = inspect.getsource(getattr(data_governance, name))
            assert 'require_recent_step_up' in source, f"{name} does not require step-up"
            assert 'purpose="legal_hold_change"' in source

    def test_the_purpose_is_registered(self) -> None:
        # An unregistered purpose would be rejected by the step-up service, so
        # the control would fail at runtime rather than at import.
        from caseops_api.services.security import STEP_UP_PURPOSES

        assert "legal_hold_change" in STEP_UP_PURPOSES
        assert "retention_policy_activation" in STEP_UP_PURPOSES
