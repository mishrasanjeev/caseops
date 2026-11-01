"""IPLF-027B A1 rule-governance proofs on real PostgreSQL row locks.

The A1 gate requires real PostgreSQL evidence, not SQLite, for:

* ``A1-PG-OWNERSHIP`` after migration/backfill (and after concurrent traffic)
  there are zero NULL, missing, mixed or cross-company ownership, policy or
  deadline rows;
* ``A1-PG-PROPOSAL`` concurrent first proposals of one key in two companies do
  not collide, and within one company the loser gets a typed 409;
* ``A1-PG-OVERLAP`` two concurrent activations of overlapping versions leave
  exactly one active version (effective-range overlap fails closed);
* ``A1-PG-CAS`` concurrent policy selections with the same expected version
  produce one write and one ``ip_rule_policy_version_conflict``;
* ``A1-PG-DISABLE-SELECT`` emergency disable racing policy selection, both
  orders, never leaves auto-confirmation enabled on a disabled version;
* ``A1-PG-DISABLE-DEADLINE`` emergency disable racing deadline proposal and
  confirmation, both orders: either the deadline commits first and the disable
  sees it, or the disable commits first and the writer refuses.

Each race holds the first writer inside its lock with a gate, proves the second
writer is blocked on a real PostgreSQL lock (``pg_stat_activity``), then
releases the gate. Writers are the production service functions.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingSubscription,
    CompanyIpRulePolicy,
    IpDeadline,
    IpDocketRecord,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
    NotificationDeliveryIntent,
)
from caseops_api.db.session import clear_engine_cache
from caseops_api.schemas.ip_deadlines import (
    IpCompanyRuleSelectionRequest,
    IpDeadlineConfirmRequest,
    IpDeadlineProposalRequest,
    IpRuleActivationRequest,
    IpRuleTransitionRequest,
    IpRuleVersionProposalRequest,
    LegalCalendarActivationRequest,
    LegalCalendarVersionProposalRequest,
)
from caseops_api.services import ip_deadline_workflow as workflow
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_20261031_ip_rule_set_ownership_migration import (
    _legacy_policy,
    _legacy_rule_set,
    _legacy_version,
)
from tests.test_ip_deadline_workflow import _calendar_payload, _rule_payload
from tests.test_postgres_validation import (  # noqa: F401 - module fixture import
    _ensure_migrations,
    _ip_race_context,
    _seed_company,
    _seed_matter,
    _seed_membership,
    _wait_for_postgres_lock_wait,
)

pytestmark = pytest.mark.postgres

REVISION = "20261031_0002"
_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- audit


def ownership_audit(connection) -> dict[str, int]:
    """Read-only A1 ownership audit; every count must be zero.

    The same queries are the pre-traffic production audit: run them in a
    ``REPEATABLE READ, READ ONLY`` transaction against the migrated database.
    """

    queries = {
        "rule_sets_without_owner": "SELECT count(*) FROM ip_rule_sets WHERE company_id IS NULL",
        "rule_sets_with_missing_owner": (
            "SELECT count(*) FROM ip_rule_sets s LEFT JOIN companies c ON c.id = s.company_id "
            "WHERE s.company_id IS NOT NULL AND c.id IS NULL"
        ),
        "versions_without_rule_set": (
            "SELECT count(*) FROM ip_rule_versions v LEFT JOIN ip_rule_sets s "
            "ON s.id = v.rule_set_id WHERE s.id IS NULL"
        ),
        "version_principals_in_other_company": (
            "SELECT count(*) FROM ip_rule_versions v "
            "JOIN ip_rule_sets s ON s.id = v.rule_set_id "
            "JOIN company_memberships m ON m.id IN (v.proposed_by_membership_id, "
            "v.reviewed_by_membership_id, v.legal_approved_by_membership_id) "
            "WHERE m.company_id <> s.company_id"
        ),
        "policies_on_other_company_rule_set": (
            "SELECT count(*) FROM company_ip_rule_policies p "
            "JOIN ip_rule_sets s ON s.id = p.rule_set_id WHERE s.company_id <> p.company_id"
        ),
        "policies_pointing_outside_their_rule_set": (
            "SELECT count(*) FROM company_ip_rule_policies p "
            "JOIN ip_rule_versions v ON v.id = p.active_rule_version_id "
            "WHERE v.rule_set_id <> p.rule_set_id"
        ),
        "deadlines_on_other_company_rule": (
            "SELECT count(*) FROM ip_deadlines d "
            "JOIN ip_rule_versions v ON v.id = d.rule_version_id "
            "JOIN ip_rule_sets s ON s.id = v.rule_set_id WHERE s.company_id <> d.company_id"
        ),
        "deadlines_without_rule_version": (
            "SELECT count(*) FROM ip_deadlines d LEFT JOIN ip_rule_versions v "
            "ON v.id = d.rule_version_id WHERE v.id IS NULL"
        ),
        "rule_sets_with_mixed_evidence": (
            "SELECT count(*) FROM (SELECT v.rule_set_id FROM ip_rule_versions v "
            "JOIN company_memberships m ON m.id = v.proposed_by_membership_id "
            "GROUP BY v.rule_set_id HAVING count(DISTINCT m.company_id) > 1) mixed"
        ),
    }
    return {name: int(connection.execute(text(sql)).scalar_one()) for name, sql in queries.items()}


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _rollout_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    monkeypatch.delenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", raising=False)
    get_settings.cache_clear()


_paused = threading.local()


class _Gate:
    """Hold one marked worker inside a lock until the test releases it."""

    def __init__(self) -> None:
        self.reached = Event()
        self.release = Event()

    def hold(self) -> None:
        self.reached.set()
        if not self.release.wait(timeout=20):
            raise TimeoutError("The gated writer was never released.")


def _pause_after(monkeypatch: pytest.MonkeyPatch, name: str, gate: _Gate) -> None:
    """Pause the first marked thread right after ``workflow.<name>`` returns."""

    original = getattr(workflow, name)

    def gated(*args, **kwargs):
        result = original(*args, **kwargs)
        if getattr(_paused, "marked", False) and not gate.reached.is_set():
            gate.hold()
        return result

    monkeypatch.setattr(workflow, name, gated)


def _run(
    pg_engine,
    *,
    membership_id: str,
    company_id: str,
    action: Callable,
    marked: bool,
    application_name: str,
) -> tuple[int, object]:
    _paused.marked = marked
    try:
        with Session(pg_engine) as session:
            session.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": application_name},
            )
            context = _ip_race_context(
                session, company_id=company_id, membership_id=membership_id
            )
            try:
                return 200, action(session, context)
            except HTTPException as exc:
                session.rollback()
                return exc.status_code, exc.detail
    finally:
        _paused.marked = False


def _race(
    pg_engine,
    *,
    gate: _Gate,
    first: dict,
    second: dict,
) -> tuple[tuple[int, object], tuple[int, object]]:
    """Run ``first`` until it holds the gate, prove ``second`` waits, release."""

    second_name = f"caseops-a1-race-{uuid4().hex[:10]}"
    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(
            _run,
            pg_engine,
            marked=True,
            application_name=f"caseops-a1-first-{uuid4().hex[:10]}",
            **first,
        )
        second_future = None
        try:
            assert gate.reached.wait(timeout=20), "first writer never reached its lock"
            second_future = executor.submit(
                _run, pg_engine, marked=False, application_name=second_name, **second
            )
            _wait_for_postgres_lock_wait(pg_engine, application_name=second_name)
        finally:
            gate.release.set()
        first_result = first_future.result(timeout=30)
        assert second_future is not None
        second_result = second_future.result(timeout=30)
    return first_result, second_result


def _company(session: Session, roles: dict[str, str]) -> dict[str, str]:
    company_id = _seed_company(session)
    ids = {name: _seed_membership(session, company_id, role=role) for name, role in roles.items()}
    session.add(
        BillingSubscription(
            company_id=company_id,
            status="manual_active",
            segment="law_firm",
            source="a1-postgres-proof",
            externally_billable=False,
            entitlement_overrides_json={"ip_rule_governance": True},
        )
    )
    session.commit()
    return {"company_id": company_id, **ids}


def _call(pg_engine, company: dict, member: str, action: Callable):
    with Session(pg_engine) as session:
        context = _ip_race_context(
            session, company_id=company["company_id"], membership_id=company[member]
        )
        return action(session, context)


def _rule_request(**overrides) -> IpRuleVersionProposalRequest:
    payload = _rule_payload()
    payload.update(overrides)
    return IpRuleVersionProposalRequest.model_validate(payload)


def _propose_rule(pg_engine, company: dict, member: str, **overrides):
    return _call(
        pg_engine,
        company,
        member,
        lambda session, context: workflow.propose_rule_version(
            session, context=context, payload=_rule_request(**overrides)
        ),
    )


def _activate(pg_engine, company, approver, rule_id, reviewer, **extra):
    return _call(
        pg_engine,
        company,
        approver,
        lambda session, context: workflow.activate_rule_version(
            session,
            context=context,
            rule_version_id=rule_id,
            payload=IpRuleActivationRequest(reviewer_membership_id=company[reviewer], **extra),
        ),
    )


def _governed(pg_engine) -> dict[str, str]:
    """Owner proposes; approver activates with reviewer; clerk handles deadlines."""

    with Session(pg_engine) as session:
        company = _company(
            session,
            {
                "owner": "owner",
                "approver": "admin",
                "reviewer": "admin",
                "clerk": "admin",
                "selector": "admin",
                "backup": "admin",
            },
        )
        matter_id = _seed_matter(session, company["company_id"])
        docket = IpDocketRecord(
            company_id=company["company_id"],
            matter_id=matter_id,
            record_type="trademark_application",
            title="A1 PostgreSQL governance docket",
            primary_identifier=f"PG-A1-{uuid4().hex[:8]}",
            status="ready",
            is_active=True,
            restricted=False,
            created_by_membership_id=company["owner"],
        )
        session.add(docket)
        session.commit()
        company["docket_id"] = docket.id
    calendar = _call(
        pg_engine,
        company,
        "owner",
        lambda session, context: workflow.propose_calendar_version(
            session,
            context=context,
            payload=LegalCalendarVersionProposalRequest.model_validate(_calendar_payload()),
        ),
    )
    _call(
        pg_engine,
        company,
        "approver",
        lambda session, context: workflow.activate_calendar_version(
            session,
            context=context,
            calendar_version_id=calendar.id,
            payload=LegalCalendarActivationRequest(reason="Independent calendar review."),
        ),
    )
    rule = _propose_rule(pg_engine, company, "owner")
    _activate(
        pg_engine,
        company,
        "approver",
        rule.id,
        "reviewer",
        select_for_company=True,
        auto_confirm_eligible=True,
    )
    company["calendar_id"] = calendar.id
    company["rule_id"] = rule.id
    return company


def _proposal(company: dict) -> Callable:
    def propose(session, context):
        return workflow.propose_deadline(
            session,
            context=context,
            docket_id=company["docket_id"],
            payload=IpDeadlineProposalRequest(
                title="Respond to examination report",
                rule_version_id=company["rule_id"],
                calendar_version_id=company["calendar_id"],
                base_date=date(2026, 8, 14),
                base_date_certainty="certain",
            ),
        )

    return propose


def _impact_token(pg_engine, company: dict) -> str:
    return _call(
        pg_engine,
        company,
        "approver",
        lambda session, context: workflow.rule_impact(
            session, context=context, rule_version_id=company["rule_id"]
        ),
    ).impact_token


def _disable(company: dict, token: str) -> Callable:
    def disable(session, context):
        return workflow.transition_rule_version(
            session,
            context=context,
            rule_version_id=company["rule_id"],
            payload=IpRuleTransitionRequest(
                impact_token=token,
                reason="Official source withdrew the rule text.",
                emergency_disable=True,
            ),
        )

    return disable


def _policy(pg_engine, company: dict) -> CompanyIpRulePolicy:
    with Session(pg_engine) as session:
        policy = session.scalar(
            select(CompanyIpRulePolicy).where(
                CompanyIpRulePolicy.company_id == company["company_id"]
            )
        )
        assert policy is not None
        session.expunge(policy)
        return policy


def _status(pg_engine, version_id: str) -> str:
    with Session(pg_engine) as session:
        return str(session.get(IpRuleVersion, version_id).status)


# --------------------------------------------------------------------------- ownership


def test_a1_pg_backfill_leaves_no_unowned_mixed_or_cross_company_rows(pg_engine) -> None:
    """Legacy rows with every evidence kind migrate to exactly one owner each."""

    with temporary_http_database(pg_engine.url) as engine:
        url = engine.url.render_as_string(hide_password=False)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("CASEOPS_DATABASE_URL", url)
            patch.setenv("CASEOPS_ENV", "local")
            get_settings.cache_clear()
            clear_engine_cache()
            config = Config(str(_ROOT / "alembic.ini"))
            config.set_main_option("script_location", str(_ROOT / "alembic"))
            config.set_main_option("sqlalchemy.url", url)
            parent = ScriptDirectory.from_config(config).get_revision(REVISION).down_revision
            try:
                command.upgrade(config, parent)
                companies = []
                for index in range(2):
                    with Session(engine) as session:
                        company_id = _seed_company(session)
                        members = [
                            _seed_membership(session, company_id, role="admin") for _ in range(3)
                        ]
                        matter_id = _seed_matter(session, company_id)
                        session.commit()
                    # Two companies independently used the same legacy key
                    # name in distinct rule sets (the pre-A1 global key was
                    # suffixed per company in practice), plus a reviewer and
                    # an approver recorded on each version.
                    rule_set = _legacy_rule_set(engine, key=f"in-tm-legacy-{index}")
                    version = _legacy_version(
                        engine,
                        rule_set_id=rule_set,
                        version=1,
                        proposer_id=members[0],
                        status="active",
                    )
                    with engine.begin() as connection:
                        connection.execute(
                            text(
                                "UPDATE ip_rule_versions SET reviewed_by_membership_id = :r, "
                                "legal_approved_by_membership_id = :a WHERE id = :v"
                            ),
                            {"r": members[1], "a": members[2], "v": version},
                        )
                    _legacy_policy(
                        engine,
                        company_id=company_id,
                        rule_set_id=rule_set,
                        version_id=version,
                        updater_id=members[2],
                    )
                    _legacy_deadline(
                        engine,
                        company_id=company_id,
                        member_id=members[0],
                        matter_id=matter_id,
                        rule_version_id=version,
                    )
                    companies.append((company_id, rule_set))

                command.upgrade(config, REVISION)

                from alembic.util import load_python_file

                migration = load_python_file(
                    str(_ROOT / "alembic" / "versions"),
                    "20261031_0002_ip_rule_set_company_ownership.py",
                )
                with engine.connect() as connection:
                    resolved, findings = migration.ownership_findings(connection)
                    assert findings == []
                    assert resolved == {rule_set: company for company, rule_set in companies}
                    owners = dict(
                        connection.execute(text("SELECT id, company_id FROM ip_rule_sets")).all()
                    )
                    assert owners == {rule_set: company for company, rule_set in companies}
                    assert set(ownership_audit(connection).values()) == {0}
            finally:
                clear_engine_cache()
                get_settings.cache_clear()


def _legacy_deadline(engine, *, company_id, member_id, matter_id, rule_version_id) -> None:
    """A confirmed-shape legal deadline written with the unchanged ORM tables."""

    with Session(engine) as session:
        docket = IpDocketRecord(
            company_id=company_id,
            matter_id=matter_id,
            record_type="trademark_application",
            title="Legacy docket",
            primary_identifier=f"PG-LEGACY-{uuid4().hex[:8]}",
            status="ready",
            is_active=True,
            restricted=False,
            created_by_membership_id=member_id,
        )
        calendar = LegalWorkingCalendar(
            company_id=company_id,
            key=f"legacy-calendar-{uuid4().hex[:6]}",
            name="Legacy calendar",
            jurisdiction="IN",
            created_by_membership_id=member_id,
        )
        session.add_all([docket, calendar])
        session.flush()
        calendar_version = LegalWorkingCalendarVersion(
            company_id=company_id,
            calendar_id=calendar.id,
            version=1,
            status="active",
            timezone="Asia/Kolkata",
            weekend_days_json=[5, 6],
            holidays_json=[],
            exceptional_working_days_json=[],
            source_priority_json=["official_gazette"],
            source_reference="https://official.example/legacy-calendar",
            source_hash="a" * 64,
            effective_from=date(2026, 1, 1),
            proposed_by_membership_id=member_id,
            proposer_label_snapshot="Legacy proposer",
        )
        session.add(calendar_version)
        session.flush()
        session.add(
            IpDeadline(
                company_id=company_id,
                docket_id=docket.id,
                rule_version_id=rule_version_id,
                calendar_version_id=calendar_version.id,
                deadline_kind="legal_deadline",
                title="Legacy deadline",
                trigger_kind="examination_report_received",
                base_date=date(2026, 8, 14),
                duration_value=1,
                duration_unit="days",
                calendar_method="business_days",
                timezone="Asia/Kolkata",
                date_precision="date",
                certainty="certain",
                result_on=date(2026, 8, 18),
                calculation_inputs_json={},
                calculation_trace_json=[],
                explanation="Legacy evidence",
                rule_citation="Legacy citation",
                engine_version="caseops-ip-deadline-v1",
                source_version="legacy-source",
                is_critical=True,
                state="candidate",
                version=1,
                created_by_membership_id=member_id,
                creator_label_snapshot="Legacy proposer",
            )
        )
        session.commit()


# --------------------------------------------------------------------------- proposals


def test_a1_pg_same_key_in_two_companies_does_not_collide(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Company A holds its uncommitted first proposal; company B is not blocked."""

    with Session(pg_engine) as session:
        first = _company(session, {"owner": "owner"})
        second = _company(session, {"owner": "owner"})
    key = f"in-tm-shared-{uuid4().hex[:8]}"
    gate = _Gate()
    _pause_after(monkeypatch, "record_from_context", gate)

    def propose(session, context):
        return workflow.propose_rule_version(
            session, context=context, payload=_rule_request(key=key)
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        held = executor.submit(
            _run,
            pg_engine,
            membership_id=first["owner"],
            company_id=first["company_id"],
            action=propose,
            marked=True,
            application_name=f"caseops-a1-key-{uuid4().hex[:8]}",
        )
        try:
            assert gate.reached.wait(timeout=20)
            # Company B completes while A's insert of the same key is uncommitted.
            other_status, other = _run(
                pg_engine,
                membership_id=second["owner"],
                company_id=second["company_id"],
                action=propose,
                marked=False,
                application_name=f"caseops-a1-key-{uuid4().hex[:8]}",
            )
        finally:
            gate.release.set()
        held_status, held_rule = held.result(timeout=30)

    assert (held_status, other_status) == (200, 200)
    assert held_rule.version == other.version == 1
    assert held_rule.rule_set_id != other.rule_set_id
    with Session(pg_engine) as session:
        owners = dict(
            session.execute(
                select(IpRuleSet.id, IpRuleSet.company_id).where(IpRuleSet.key == key)
            ).all()
        )
    assert owners == {
        held_rule.rule_set_id: first["company_id"],
        other.rule_set_id: second["company_id"],
    }


def test_a1_pg_concurrent_first_proposal_in_one_company_is_a_typed_409(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(pg_engine) as session:
        company = _company(session, {"first": "owner", "second": "admin"})
    key = f"in-tm-concurrent-{uuid4().hex[:8]}"
    gate = _Gate()
    _pause_after(monkeypatch, "record_from_context", gate)

    def propose(session, context):
        return workflow.propose_rule_version(
            session, context=context, payload=_rule_request(key=key)
        )

    winner, loser = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["first"],
            "company_id": company["company_id"],
            "action": propose,
        },
        second={
            "membership_id": company["second"],
            "company_id": company["company_id"],
            "action": propose,
        },
    )
    assert winner[0] == 200 and winner[1].version == 1
    assert loser == (409, "This rule key was created by a concurrent proposal; reload and retry.")
    with Session(pg_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpRuleVersion)
                .join(IpRuleSet, IpRuleSet.id == IpRuleVersion.rule_set_id)
                .where(IpRuleSet.company_id == company["company_id"], IpRuleSet.key == key)
            )
            == 1
        )


# --------------------------------------------------------------------------- activation


def test_a1_pg_overlapping_activation_fails_closed(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(pg_engine) as session:
        company = _company(
            session,
            {
                "proposer_one": "owner",
                "proposer_two": "admin",
                "approver_one": "admin",
                "approver_two": "admin",
                "reviewer_one": "admin",
                "reviewer_two": "admin",
            },
        )
    key = f"in-tm-overlap-{uuid4().hex[:8]}"
    one = _propose_rule(pg_engine, company, "proposer_one", key=key)
    two = _propose_rule(pg_engine, company, "proposer_two", key=key)
    assert (one.version, two.version) == (1, 2)
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    def activation(rule_id: str, reviewer: str) -> Callable:
        def activate(session, context):
            return workflow.activate_rule_version(
                session,
                context=context,
                rule_version_id=rule_id,
                payload=IpRuleActivationRequest(
                    reviewer_membership_id=company[reviewer], select_for_company=False
                ),
            )

        return activate

    first, second = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["approver_one"],
            "company_id": company["company_id"],
            "action": activation(one.id, "reviewer_one"),
        },
        second={
            "membership_id": company["approver_two"],
            "company_id": company["company_id"],
            "action": activation(two.id, "reviewer_two"),
        },
    )
    assert first[0] == 200 and first[1].status == "active"
    assert second[0] == 409
    assert "overlaps active version(s) 1" in str(second[1])
    assert (_status(pg_engine, one.id), _status(pg_engine, two.id)) == ("active", "candidate")


# --------------------------------------------------------------------------- policy CAS


@pytest.mark.parametrize("existing_policy", [True, False], ids=["swap", "first-selection"])
def test_a1_pg_policy_compare_and_swap_admits_one_writer(
    pg_engine, monkeypatch: pytest.MonkeyPatch, existing_policy: bool
) -> None:
    with Session(pg_engine) as session:
        company = _company(
            session,
            {"owner": "owner", "approver": "admin", "reviewer": "admin", "other": "admin"},
        )
    rule = _propose_rule(pg_engine, company, "owner", key=f"in-tm-cas-{uuid4().hex[:8]}")
    _activate(
        pg_engine, company, "approver", rule.id, "reviewer", select_for_company=existing_policy
    )
    expected = 1 if existing_policy else None
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    def select_version(auto_confirm: bool) -> Callable:
        def select_policy(session, context):
            return workflow.select_company_rule_version(
                session,
                context=context,
                payload=IpCompanyRuleSelectionRequest(
                    rule_version_id=rule.id,
                    auto_confirm_eligible=auto_confirm,
                    expected_policy_version=expected,
                ),
            )

        return select_policy

    first, second = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": select_version(True),
        },
        second={
            "membership_id": company["other"],
            "company_id": company["company_id"],
            "action": select_version(False),
        },
    )
    winning_version = 2 if existing_policy else 1
    assert first[0] == 200 and first[1].version == winning_version
    assert second[0] == 409
    assert second[1]["code"] == "ip_rule_policy_version_conflict"
    assert second[1]["current_policy_version"] == winning_version
    policy = _policy(pg_engine, company)
    assert (policy.version, policy.auto_confirm_eligible) == (winning_version, True)


# --------------------------------------------------------------------------- disable races


def test_a1_pg_selection_then_disable_suspends_auto_confirm(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _governed(pg_engine)
    token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    def reselect(session, context):
        return workflow.select_company_rule_version(
            session,
            context=context,
            payload=IpCompanyRuleSelectionRequest(
                rule_version_id=company["rule_id"],
                auto_confirm_eligible=True,
                expected_policy_version=1,
            ),
        )

    selection, disable = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["selector"],
            "company_id": company["company_id"],
            "action": reselect,
        },
        second={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, token),
        },
    )
    assert selection[0] == 200 and selection[1].auto_confirm_eligible is True
    assert disable[0] == 200 and disable[1].status == "disabled"
    policy = _policy(pg_engine, company)
    assert policy.auto_confirm_eligible is False
    assert policy.version == 3


def test_a1_pg_disable_then_selection_is_refused(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _governed(pg_engine)
    token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    def reselect(session, context):
        return workflow.select_company_rule_version(
            session,
            context=context,
            payload=IpCompanyRuleSelectionRequest(
                rule_version_id=company["rule_id"],
                auto_confirm_eligible=True,
                expected_policy_version=1,
            ),
        )

    disable, selection = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, token),
        },
        second={
            "membership_id": company["selector"],
            "company_id": company["company_id"],
            "action": reselect,
        },
    )
    assert disable[0] == 200
    assert selection[0] == 409
    policy = _policy(pg_engine, company)
    assert (policy.auto_confirm_eligible, policy.version) == (False, 2)


def test_a1_pg_deadline_proposal_then_disable_sees_the_new_candidate(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _governed(pg_engine)
    stale_token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_share_lock_rule_version", gate)

    proposal, disable = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["clerk"],
            "company_id": company["company_id"],
            "action": _proposal(company),
        },
        second={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, stale_token),
        },
    )
    assert proposal[0] == 200 and proposal[1].state == "candidate"
    # The disable serialized behind the proposal and saw a changed impact.
    assert disable == (409, "Rule impact changed; preview again.")
    assert _status(pg_engine, company["rule_id"]) == "active"

    fresh_token = _impact_token(pg_engine, company)
    retry = _call(pg_engine, company, "approver", _disable(company, fresh_token))
    assert retry.status == "disabled"
    with Session(pg_engine) as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "ip.rule_version.disabled",
                AuditEvent.target_id == company["rule_id"],
            )
        )
        metadata = json.loads(audit.metadata_json)
        assert metadata["dependent_candidate_deadline_ids"] == [proposal[1].id]
        recipients = set(
            session.scalars(
                select(NotificationDeliveryIntent.recipient_membership_id).where(
                    NotificationDeliveryIntent.company_id == company["company_id"],
                    NotificationDeliveryIntent.event_type == "ip_rule_version_disabled",
                )
            ).all()
        )
    assert company["clerk"] in recipients and company["approver"] in recipients


def test_a1_pg_disable_then_deadline_proposal_is_refused(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    company = _governed(pg_engine)
    token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    disable, proposal = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, token),
        },
        second={
            "membership_id": company["clerk"],
            "company_id": company["company_id"],
            "action": _proposal(company),
        },
    )
    assert disable[0] == 200
    assert proposal == (409, "An active rule version is required.")
    with Session(pg_engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpDeadline)
                .where(IpDeadline.rule_version_id == company["rule_id"])
            )
            == 0
        )


def _confirmation(company: dict, candidate, confirmer: str) -> Callable:
    def confirm(session, context):
        return workflow.confirm_deadline(
            session,
            context=context,
            deadline_id=candidate.id,
            payload=IpDeadlineConfirmRequest(
                expected_version=candidate.version,
                responsibilities=[
                    {"membership_id": company[confirmer], "role": "primary", "accepted": True},
                    {"membership_id": company["backup"], "role": "backup", "accepted": True},
                ],
            ),
        )

    return confirm


@pytest.mark.parametrize(
    "confirmer",
    ["clerk", "selector"],
    ids=["confirmer-is-alerted-owner", "confirmer-shares-no-membership"],
)
def test_a1_pg_disable_then_confirmation_is_refused(
    pg_engine, monkeypatch: pytest.MonkeyPatch, confirmer: str
) -> None:
    """Both lock paths: the confirmer is the candidate owner the disable alerts
    (it serializes on the fenced membership), or shares no membership with the
    disable (it serializes on the version share lock). Neither deadlocks."""

    company = _governed(pg_engine)
    candidate = _call(pg_engine, company, "clerk", _proposal(company))
    token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_lock_owned_rule_version", gate)

    disable, confirmation = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, token),
        },
        second={
            "membership_id": company[confirmer],
            "company_id": company["company_id"],
            "action": _confirmation(company, candidate, confirmer),
        },
    )
    assert disable[0] == 200
    assert confirmation == (409, "The governing rule is not active.")
    with Session(pg_engine) as session:
        row = session.get(IpDeadline, candidate.id)
        assert row.state == "candidate" and row.matter_deadline_id is None
        recipients = set(
            session.scalars(
                select(NotificationDeliveryIntent.recipient_membership_id).where(
                    NotificationDeliveryIntent.company_id == company["company_id"],
                    NotificationDeliveryIntent.event_type == "ip_rule_version_disabled",
                )
            ).all()
        )
    assert recipients == {company["approver"], company["clerk"]}


def test_a1_pg_confirmation_then_disable_sees_the_confirmed_owners(
    pg_engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A confirmation holding the version share lock commits first; the disable
    then refuses its stale preview, and a fresh disable alerts the new owners."""

    company = _governed(pg_engine)
    candidate = _call(pg_engine, company, "clerk", _proposal(company))
    stale_token = _impact_token(pg_engine, company)
    gate = _Gate()
    _pause_after(monkeypatch, "_share_lock_rule_version", gate)

    confirmation, disable = _race(
        pg_engine,
        gate=gate,
        first={
            "membership_id": company["selector"],
            "company_id": company["company_id"],
            "action": _confirmation(company, candidate, "selector"),
        },
        second={
            "membership_id": company["approver"],
            "company_id": company["company_id"],
            "action": _disable(company, stale_token),
        },
    )
    assert confirmation[0] == 200 and confirmation[1].state == "confirmed"
    assert disable == (409, "Rule impact changed; preview again.")

    fresh_token = _impact_token(pg_engine, company)
    retry = _call(pg_engine, company, "approver", _disable(company, fresh_token))
    assert retry.status == "disabled"
    with Session(pg_engine) as session:
        recipients = set(
            session.scalars(
                select(NotificationDeliveryIntent.recipient_membership_id).where(
                    NotificationDeliveryIntent.company_id == company["company_id"],
                    NotificationDeliveryIntent.event_type == "ip_rule_version_disabled",
                )
            ).all()
        )
        confirmed = session.get(IpDeadline, candidate.id)
        assert confirmed.state == "confirmed" and confirmed.matter_deadline_id is not None
    assert recipients == {company["approver"], company["selector"], company["backup"]}


def test_a1_pg_runtime_writers_left_no_ownership_violations(pg_engine) -> None:
    """The same audit over every row the runtime writers created.

    CI shards this module, so the writers above may run in another shard; one
    governed company is written here so the audit never runs over nothing.
    """

    _governed(pg_engine)
    with pg_engine.connect() as connection:
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        audit = ownership_audit(connection)
        connection.rollback()
    assert audit == dict.fromkeys(audit, 0)
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(IpRuleSet)) > 0
        recent = datetime.now(UTC) - timedelta(hours=6)
        assert (
            session.scalar(
                select(func.count())
                .select_from(IpRuleVersion)
                .where(IpRuleVersion.created_at >= recent)
            )
            > 0
        )
