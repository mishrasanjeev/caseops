"""DATA-GOV-17: a nightly scan that cannot lie about what it did not check.

The requirement names six checks. Three of them cannot be evaluated yet - there
is no approved retention schedule, no purge execute path, and no provider
deletion path - and how that is reported is the whole point of this module.

A scan returning "0 expired-unpurged" while having no definition of *expired*
is worse than no scan at all. It reads as "nothing is overdue" when the truth is
"we cannot tell", and a reassuring zero from a detective control is precisely
the failure the control exists to prevent.

So the tests below care as much about the three checks that DON'T run as the
three that do.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    LegalHold,
    LegalHoldItem,
    LegalHoldStatus,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.governance_integrity_scan import run_integrity_scan
from tests.test_auth_company import bootstrap_company

_BLOCKED = {
    "expired_unpurged": "DATA-GOV-02",
    "purged_still_searchable": "DATA-GOV-08",
    "provider_deletion_exceptions": "DATA-GOV-09",
}


@pytest.fixture()
def session(client) -> Session:  # noqa: ARG001 - client configures the test database
    with get_session_factory()() as active:
        yield active


@pytest.fixture()
def company_id(client) -> str:
    return str(bootstrap_company(client)["company"]["id"])


def _by_id(report) -> dict:
    return {check.check_id: check for check in report.checks}


def _approval_pair(session: Session, company_id: str) -> tuple[str, str]:
    ids: list[str] = []
    for index in range(2):
        user = User(
            email=f"scan-{index}-{uuid4().hex[:8]}@fixture.example",
            full_name=f"Scan Actor {index}",
            password_hash="fixture-only",
        )
        session.add(user)
        session.flush()
        membership = CompanyMembership(company_id=company_id, user_id=user.id, role="admin")
        session.add(membership)
        session.flush()
        ids.append(membership.id)
    return ids[0], ids[1]


def _hold(session: Session, company_id: str, status: str = LegalHoldStatus.ACTIVE) -> LegalHold:
    now = datetime.now(UTC)
    creator, approver = _approval_pair(session, company_id)
    active = status == LegalHoldStatus.ACTIVE
    hold = LegalHold(
        company_id=company_id,
        key=f"scan-{uuid4().hex[:8]}",
        title="Preservation order",
        authority_reference="Court order 2026/11",
        status=status,
        activated_at=now if active else None,
        released_at=now if status == LegalHoldStatus.RELEASED else None,
        created_by_membership_id=creator,
        created_by_membership_company_id=company_id,
        creator_label_snapshot="Records owner",
        approved_by_membership_id=approver if active else None,
        approved_by_membership_company_id=company_id if active else None,
        approver_label_snapshot="Approver" if active else None,
        created_at=now,
        updated_at=now,
    )
    session.add(hold)
    session.flush()
    return hold


def _item(session: Session, hold: LegalHold, data_class_id: str) -> LegalHoldItem:
    item = LegalHoldItem(
        company_id=hold.company_id,
        legal_hold_id=hold.id,
        data_class_id=data_class_id,
        target_type="tenant",
        target_reference_hash="a" * 64,
        created_at=datetime.now(UTC),
    )
    session.add(item)
    session.flush()
    return item


class TestUnavailableIsNotHealthy:
    """The central property."""

    def test_the_three_blocked_checks_report_unavailable_not_ok(
        self, session: Session
    ) -> None:
        checks = _by_id(run_integrity_scan(session))

        for check_id, blocker in _BLOCKED.items():
            assert checks[check_id].status == "unavailable", (
                f"{check_id} must not report ok - it cannot run"
            )
            assert checks[check_id].blocked_by == blocker
            # And it must say what is missing, or an operator cannot act.
            assert checks[check_id].summary.strip()

    def test_an_unavailable_check_is_never_counted_as_ok(self, session: Session) -> None:
        report = run_integrity_scan(session)

        assert report.unavailable_count == len(_BLOCKED)
        assert report.ok_count + report.finding_count + report.unavailable_count == len(
            report.checks
        )

    def test_a_scan_with_unavailable_checks_is_not_complete(self, session: Session) -> None:
        # is_complete is what a caller should gate on. "No findings" while three
        # checks never ran says something very different about the estate.
        report = run_integrity_scan(session)

        assert report.is_complete is False, (
            "a scan cannot be complete while three of its six checks cannot run"
        )


class TestChecksThatDoRun:
    def test_every_live_table_is_registered_in_the_map(self, session: Session) -> None:
        # The repo is expected to be clean here; the governance change gate
        # enforces it on every PR. If this fails, a table shipped unregistered.
        check = _by_id(run_integrity_scan(session))["missing_data_map"]

        assert check.status == "ok", f"unregistered tables: {check.findings[:5]}"

    def test_an_unresolvable_hold_class_is_reported(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(session, hold, "a_class_the_registry_does_not_know")

        check = _by_id(run_integrity_scan(session, company_id=company_id))["held_at_risk"]

        assert check.status == "findings"
        assert any(hold.id in finding for finding in check.findings)

    def test_a_registered_hold_class_is_clean(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(session, hold, "legal_holds")

        check = _by_id(run_integrity_scan(session, company_id=company_id))["held_at_risk"]

        assert check.status == "ok"

    def test_hold_items_under_a_released_hold_are_orphans(
        self, session: Session, company_id: str
    ) -> None:
        # Preservation evidence pointing at a released hold protects nothing and
        # inflates any count of what is preserved.
        released = _hold(session, company_id, status=LegalHoldStatus.RELEASED)
        item = _item(session, released, "legal_holds")

        check = _by_id(run_integrity_scan(session, company_id=company_id))["orphan_hold_items"]

        assert check.status == "findings"
        assert item.id in check.findings

    def test_items_under_an_active_hold_are_not_orphans(
        self, session: Session, company_id: str
    ) -> None:
        hold = _hold(session, company_id)
        _item(session, hold, "legal_holds")

        check = _by_id(run_integrity_scan(session, company_id=company_id))["orphan_hold_items"]

        assert check.status == "ok"


class TestContentIsNotExposed:
    def test_findings_carry_identifiers_not_content(
        self, session: Session, company_id: str
    ) -> None:
        # The requirement says "without exposing content". A hold's title and
        # authority reference must not travel into a nightly report that is read
        # far more widely than the hold itself.
        hold = _hold(session, company_id)
        _item(session, hold, "a_class_the_registry_does_not_know")

        report = run_integrity_scan(session, company_id=company_id)
        blob = " ".join(
            check.summary + " " + " ".join(check.findings) for check in report.checks
        )

        assert "Preservation order" not in blob
        assert "Court order 2026/11" not in blob
        assert "Records owner" not in blob


class TestTenantScope:
    def test_another_companys_holds_do_not_appear(
        self, session: Session, company_id: str
    ) -> None:
        other = str(uuid4())
        # A hold in a company the caller did not ask about must not surface.
        report = run_integrity_scan(session, company_id=other)
        checks = _by_id(report)

        assert checks["held_at_risk"].status == "ok"
        assert checks["orphan_hold_items"].status == "ok"
