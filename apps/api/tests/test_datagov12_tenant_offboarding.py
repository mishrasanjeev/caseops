"""DATA-GOV-12: what a tenant offboarding would revoke, stop, and preserve.

The requirement: offboarding "revokes users/sessions/connectors/portal
links/provider callbacks, stops polling/reminders/reports, resolves ownership,
exports as approved, preserves holds and produces a signed completion/exception
manifest".

Two properties carry more weight than the counts.

**Holds are preserved, not revoked.** Offboarding a tenant does not lift a
court's preservation order - if anything it raises the stakes, because nobody
is left to notice. A plan that listed legal holds among the things to remove
would be quietly destructive in exactly the situation where destruction is
least recoverable.

**A category with no tenant-scoped store says so.** Sessions are stateless;
some portal and webhook tables scope through a parent rather than by
company_id. Omitting them silently would read as "nothing to revoke there",
which is the reassuring-zero this programme keeps designing against.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    LegalHold,
    LegalHoldStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.tenant_offboarding import (
    build_offboarding_plan,
    offboarding_plan_is_blocked,
)
from tests.test_auth_company import bootstrap_company


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def company_id(client) -> str:
    return str(bootstrap_company(client)["company"]["id"])


def _by_category(session: Session, company_id: str) -> dict:
    return {c.category: c for c in build_offboarding_plan(session, company_id=company_id)}


def _active_hold(session: Session, company_id: str) -> LegalHold:
    now = datetime.now(UTC)
    ids = []
    for index in range(2):
        user = User(
            email=f"off-{index}-{uuid4().hex[:8]}@fixture.example",
            full_name=f"Offboard Actor {index}",
            password_hash="fixture-only",
        )
        session.add(user)
        session.flush()
        membership = CompanyMembership(company_id=company_id, user_id=user.id, role="admin")
        session.add(membership)
        session.flush()
        ids.append(membership.id)
    hold = LegalHold(
        company_id=company_id,
        key=f"off-{uuid4().hex[:8]}",
        title="Preservation order",
        authority_reference="Court order 2026/12",
        status=LegalHoldStatus.ACTIVE,
        activated_at=now,
        created_by_membership_id=ids[0],
        created_by_membership_company_id=company_id,
        creator_label_snapshot="Records owner",
        approved_by_membership_id=ids[1],
        approved_by_membership_company_id=company_id,
        approver_label_snapshot="Approver",
        created_at=now,
        updated_at=now,
    )
    session.add(hold)
    session.flush()
    return hold


class TestHoldsArePreserved:
    """The property that stops this plan being destructive."""

    def test_legal_holds_are_preserved_never_revoked(
        self, session: Session, company_id: str
    ) -> None:
        _active_hold(session, company_id)

        holds = _by_category(session, company_id)["legal_holds"]

        assert holds.disposition == "preserve"
        assert holds.disposition not in {"revoke", "stop"}
        assert holds.record_count == 1

    def test_an_active_hold_blocks_the_offboarding(
        self, session: Session, company_id: str
    ) -> None:
        # An operator scheduling a tenant exit needs to learn about an
        # outstanding preservation order at PLAN time, not at execute time.
        _active_hold(session, company_id)

        assert offboarding_plan_is_blocked(
            build_offboarding_plan(session, company_id=company_id)
        )

    def test_no_hold_means_not_blocked(self, session: Session, company_id: str) -> None:
        assert not offboarding_plan_is_blocked(
            build_offboarding_plan(session, company_id=company_id)
        )


class TestRevokeAndStopCategories:
    def test_every_category_the_requirement_names_is_present(
        self, session: Session, company_id: str
    ) -> None:
        categories = _by_category(session, company_id)

        for expected in (
            "users_and_memberships",
            "sessions",
            "connectors",
            "portal_links",
            "portal_users",
            "provider_callbacks",
            "polling",
            "reminders",
            "reports",
            "legal_holds",
        ):
            assert expected in categories, f"{expected} is named by DATA-GOV-12"

    def test_memberships_are_counted_for_this_tenant(
        self, session: Session, company_id: str
    ) -> None:
        before = _by_category(session, company_id)["users_and_memberships"].record_count
        _active_hold(session, company_id)  # adds two memberships

        after = _by_category(session, company_id)["users_and_memberships"].record_count

        assert after == (before or 0) + 2

    def test_another_tenants_records_are_not_counted(self, session: Session) -> None:
        # A plan that counted another firm's logins would overstate the blast
        # radius of this offboarding.
        categories = _by_category(session, str(uuid4()))

        assert categories["users_and_memberships"].record_count == 0
        assert categories["legal_holds"].record_count == 0


class TestUnenumerableIsExplicit:
    def test_categories_without_a_tenant_scoped_store_report_unenumerable(
        self, session: Session, company_id: str
    ) -> None:
        categories = _by_category(session, company_id)

        for category in ("sessions", "portal_links", "connectors"):
            entry = categories[category]
            assert entry.disposition == "unenumerable", (
                f"{category} has no tenant-scoped store; reporting it as a count "
                "would claim knowledge the plan does not have"
            )
            # None, not zero: zero would read as "nothing to revoke".
            assert entry.record_count is None
            assert entry.detail.strip()

    def test_unenumerable_is_distinguishable_from_empty(
        self, session: Session, company_id: str
    ) -> None:
        categories = _by_category(session, company_id)

        # A genuinely empty countable category reports 0, not None.
        assert categories["reminders"].record_count == 0
        assert categories["sessions"].record_count is None


class TestManifestIntegration:
    def test_an_offboarding_dry_run_carries_the_plan(self, client) -> None:
        from caseops_api.db.models import Company
        from caseops_api.db.models import User as UserModel
        from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
        from caseops_api.services.data_governance import create_dry_run_manifest
        from caseops_api.services.session_context import SessionContext

        bootstrap = bootstrap_company(client)
        with get_session_factory()() as setup:
            company = setup.get(Company, str(bootstrap["company"]["id"]))
            membership = setup.get(CompanyMembership, str(bootstrap["membership"]["id"]))
            assert company is not None and membership is not None
            user = setup.get(UserModel, membership.user_id)
            assert user is not None
            setup.expunge_all()
        context = SessionContext(company=company, user=user, membership=membership)

        with get_session_factory()() as active:
            record = create_dry_run_manifest(
                active,
                context=context,
                payload=TenantDataOperationDryRunRequest.model_validate(
                    {
                        "operation_type": "tenant_offboarding",
                        "request_evidence_ref": "ticket://offboard-1",
                        "items": [
                            {
                                "data_class_id": "legal_holds",
                                "target_type": "tenant",
                                "target_reference_hash": "a" * 64,
                            }
                        ],
                    }
                ),
            )

        categories = {entry.category for entry in record.offboarding_plan}
        assert "legal_holds" in categories
        assert record.execution_mode == "dry_run"

    def test_an_export_dry_run_carries_no_offboarding_plan(self, client) -> None:
        # Each operation type carries only the plan that belongs to it, or the
        # manifest describes work that operation never performs.
        from caseops_api.db.models import Company
        from caseops_api.db.models import User as UserModel
        from caseops_api.schemas.data_governance import TenantDataOperationDryRunRequest
        from caseops_api.services.data_governance import create_dry_run_manifest
        from caseops_api.services.session_context import SessionContext

        bootstrap = bootstrap_company(client)
        with get_session_factory()() as setup:
            company = setup.get(Company, str(bootstrap["company"]["id"]))
            membership = setup.get(CompanyMembership, str(bootstrap["membership"]["id"]))
            assert company is not None and membership is not None
            user = setup.get(UserModel, membership.user_id)
            assert user is not None
            setup.expunge_all()
        context = SessionContext(company=company, user=user, membership=membership)

        with get_session_factory()() as active:
            record = create_dry_run_manifest(
                active,
                context=context,
                payload=TenantDataOperationDryRunRequest.model_validate(
                    {
                        "operation_type": "tenant_export",
                        "request_evidence_ref": "ticket://export-1",
                        "items": [
                            {
                                "data_class_id": "legal_holds",
                                "target_type": "tenant",
                                "target_reference_hash": "a" * 64,
                            }
                        ],
                    }
                ),
            )

        assert record.offboarding_plan == []
