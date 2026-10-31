"""IPLF-027B A1 rule-governance ownership slice (RULE-GOV-01..08, UJ-47).

The A1 section of ``docs/ip-implementation/evidence/m2/IPLF-027B/
a0-quiescence-2026-08-14.md`` lists what must hold before rule governance may
be enabled in production. Each test here proves one of those invariants from
the user-facing API (or, where the invariant is about ordering before any
database access, from the service boundary):

* ``A1-DECISION-01`` an unentitled company is refused before any governance read
* ``A1-DECISION-02`` an expired rollout is refused before any database access
* ``A1-DECISION-03`` calendar writers need the entitlement but not the rollout
* ``A1-OWNERSHIP-01`` a rule key is owned per company; nothing leaks across tenants
* ``A1-REVIEWER-01`` the fixture reviewer must actually hold ``ip:rules_activate``
* ``A1-REVIEWER-02`` the same refusal at the service boundary with a custom role
* ``A1-KIND-01`` fixtures must exercise the definition being activated
* ``A1-LOCK-01`` every rule writer takes the rule-set lock before sibling/policy work

Unsupported-kind activation and policy compare-and-swap are covered in
``test_ip_rule_governance.py`` (RULE-GOV-08 / RULE-GOV-04).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import NoReturn

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyIpRulePolicy,
    CompanyMembership,
    IpRuleSet,
    IpRuleVersion,
    LegalWorkingCalendar,
    LegalWorkingCalendarVersion,
    User,
)
from caseops_api.db.session import get_engine, get_session_factory
from caseops_api.schemas.ip_deadlines import (
    IpCompanyRuleSelectionRequest,
    IpRuleActivationRequest,
    IpRuleTransitionRequest,
)
from caseops_api.services import ip_deadline_workflow
from caseops_api.services.session_context import SessionContext
from tests.ip_rule_governance_support import grant_ip_rule_governance_entitlement
from tests.test_auth_company import auth_headers
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _rule_payload,
)

_GOVERNANCE_TABLES = (
    "ip_rule_sets",
    "ip_rule_versions",
    "company_ip_rule_policies",
    "legal_working_calendars",
    "legal_working_calendar_versions",
)


@pytest.fixture(autouse=True)
def _rollout_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open the platform rollout; tests that prove a closed rollout reset it."""

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    monkeypatch.delenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", raising=False)
    get_settings.cache_clear()


# --------------------------------------------------------------------------- helpers


def _company(client: TestClient, slug: str, *, entitled: bool = True) -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": f"{slug} Owner",
            "owner_email": f"owner@{slug}.example",
            "owner_password": "A1GovernanceOwner123!",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    if entitled:
        grant_ip_rule_governance_entitlement(str(body["company"]["id"]))
    client.cookies.clear()
    return {
        "slug": slug,
        "company_id": str(body["company"]["id"]),
        "owner_id": str(body["membership"]["id"]),
        "token": str(body["access_token"]),
        "headers": auth_headers(str(body["access_token"])),
    }


def _user(
    client: TestClient,
    company: dict,
    *,
    name: str,
    role: str = "admin",
) -> dict:
    email = f"{name.lower().replace(' ', '-')}@{company['slug']}.example"
    created = client.post(
        "/api/companies/current/users",
        headers=company["headers"],
        json={
            "full_name": name,
            "email": email,
            "password": "A1GovernanceUser123!",
            "role": role,
        },
    )
    assert created.status_code == 200, created.text
    user = {
        "membership_id": str(created.json()["membership_id"]),
        "name": name,
        "email": email,
    }
    return _login(client, company, user)


def _login(client: TestClient, company: dict, user: dict) -> dict:
    """Sign in again; a role change revokes the member's earlier sessions."""

    login = client.post(
        "/api/auth/login",
        json={
            "email": user["email"],
            "password": "A1GovernanceUser123!",
            "company_slug": company["slug"],
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    return {**user, "headers": auth_headers(str(login.json()["access_token"]))}


def _custom_role(client: TestClient, company: dict, *, name: str, permissions: list[str]) -> str:
    response = client.post(
        "/api/companies/current/roles",
        headers=company["headers"],
        json={
            "name": name,
            "description": "IPLF-027B A1 reviewer qualification",
            "base_role": "member",
            "permissions": permissions,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["id"])


def _assign_role(client: TestClient, company: dict, membership_id: str, role_id: str) -> None:
    response = client.post(
        f"/api/companies/current/employees/{membership_id}/role",
        headers=company["headers"],
        json={"custom_role_id": role_id},
    )
    assert response.status_code == 200, response.text


def _propose(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = _rule_payload()
    payload.update(overrides)
    response = client.post("/api/ip/deadline-rules", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _activate(client: TestClient, headers: dict[str, str], rule_id: str, reviewer_id: str):
    return client.post(
        f"/api/ip/deadline-rules/{rule_id}/activate",
        headers=headers,
        json={"reviewer_membership_id": reviewer_id},
    )


def _governance_snapshot() -> dict[str, int]:
    with get_session_factory()() as session:
        counts = {
            model.__tablename__: int(
                session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (
                IpRuleSet,
                IpRuleVersion,
                CompanyIpRulePolicy,
                LegalWorkingCalendar,
                LegalWorkingCalendarVersion,
            )
        }
        counts["governance_audit"] = int(
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.action.like("ip.rule_%")
                    | AuditEvent.action.like("ip.working_calendar.%")
                )
            )
            or 0
        )
    return counts


@contextmanager
def _recorded_sql() -> Iterator[list[str]]:
    statements: list[str] = []
    engine = get_engine()

    def record(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        statements.append(" ".join(statement.casefold().split()))

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _governance_statements(statements: list[str]) -> list[str]:
    return [
        statement
        for statement in statements
        if any(table in statement for table in _GOVERNANCE_TABLES)
        or statement.startswith("insert into audit_events")
    ]


def _context(session: Session, membership_id: str) -> SessionContext:
    membership = session.get(CompanyMembership, membership_id)
    assert membership is not None
    company = session.get(Company, membership.company_id)
    user = session.get(User, membership.user_id)
    assert company is not None and user is not None
    return SessionContext(company=company, membership=membership, user=user)


class _NoDatabaseAccess:
    def __init__(self) -> None:
        self.accesses: list[str] = []

    def _fail(self, name: str) -> NoReturn:
        self.accesses.append(name)
        raise AssertionError(f"database access before the rollout fence: {name}")

    def __getattr__(self, name: str) -> NoReturn:
        self._fail(name)


# --------------------------------------------------------------------------- decision


def test_a1_decision_01_unentitled_company_is_refused_before_governance_access(
    client: TestClient,
) -> None:
    """Flag on, company not entitled: every governance writer refuses first."""

    company = _company(client, "a1-unentitled", entitled=False)
    headers = company["headers"]
    before = _governance_snapshot()
    rule_version_id = "00000000-0000-4000-8000-000000000001"
    calls: list[tuple[str, Callable[[], object]]] = [
        (
            "propose rule",
            lambda: client.post("/api/ip/deadline-rules", headers=headers, json=_rule_payload()),
        ),
        (
            "activate rule",
            lambda: client.post(
                f"/api/ip/deadline-rules/{rule_version_id}/activate",
                headers=headers,
                json={"reviewer_membership_id": company["owner_id"]},
            ),
        ),
        (
            "transition rule",
            lambda: client.post(
                f"/api/ip/deadline-rules/{rule_version_id}/transition",
                headers=headers,
                json={"impact_token": "probe", "reason": "Unentitled probe of the decision."},
            ),
        ),
        (
            "select company policy",
            lambda: client.put(
                "/api/ip/rule-policies",
                headers=headers,
                json={"rule_version_id": rule_version_id},
            ),
        ),
        (
            "propose calendar",
            lambda: client.post(
                "/api/ip/working-calendars", headers=headers, json=_calendar_payload()
            ),
        ),
        (
            "activate calendar",
            lambda: client.post(
                f"/api/ip/working-calendars/{rule_version_id}/activate",
                headers=headers,
                json={"reason": "Unentitled probe of the decision."},
            ),
        ),
    ]
    for label, call in calls:
        with _recorded_sql() as statements:
            response = call()
        assert response.status_code == 403, (label, response.text)
        body = response.json()
        assert body["code"] == "ip_feature_unavailable", label
        assert body["reason"] == "missing_entitlement", label
        assert body["feature_id"] == "rule_governance", label
        assert body["entitlement_key"] == "ip_rule_governance", label
        assert _governance_statements(statements) == [], label
    assert _governance_snapshot() == before

    # The same refusal is what readiness already reports for this workspace.
    readiness = client.get("/api/ip/readiness", headers=headers)
    assert readiness.status_code == 200, readiness.text


_RULE_WRITERS: tuple[tuple[str, Callable[[_NoDatabaseAccess], object]], ...] = (
    (
        "propose_rule_version",
        lambda session: ip_deadline_workflow.propose_rule_version(
            session, context=object(), payload=object()
        ),
    ),
    (
        "activate_rule_version",
        lambda session: ip_deadline_workflow.activate_rule_version(
            session, context=object(), rule_version_id="rule-version", payload=object()
        ),
    ),
    (
        "transition_rule_version",
        lambda session: ip_deadline_workflow.transition_rule_version(
            session, context=object(), rule_version_id="rule-version", payload=object()
        ),
    ),
    (
        "select_company_rule_version",
        lambda session: ip_deadline_workflow.select_company_rule_version(
            session, context=object(), payload=object()
        ),
    ),
)


@pytest.mark.parametrize(("name", "writer"), _RULE_WRITERS, ids=[row[0] for row in _RULE_WRITERS])
def test_a1_decision_02_expired_rollout_refuses_before_any_database_access(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    writer: Callable[[_NoDatabaseAccess], object],
) -> None:
    expired = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", expired)
    get_settings.cache_clear()
    session = _NoDatabaseAccess()

    with pytest.raises(HTTPException) as caught:
        writer(session)

    assert caught.value.status_code == 503, name
    assert caught.value.detail["code"] == "ip_rule_governance_quiesced"
    assert caught.value.detail["reason"] == "rollout_expired"
    assert caught.value.detail["rollout_expiry"] == "ip_rule_governance_rollout_expires_at"
    assert session.accesses == [], name


def test_a1_decision_02_expired_rollout_api_writes_nothing_for_an_entitled_company(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = _company(client, "a1-expired")
    before = _governance_snapshot()
    monkeypatch.setenv(
        "CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT",
        (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
    )
    get_settings.cache_clear()

    with _recorded_sql() as statements:
        response = client.post(
            "/api/ip/deadline-rules", headers=company["headers"], json=_rule_payload()
        )

    assert response.status_code == 503, response.text
    assert response.json()["reason"] == "rollout_expired"
    assert _governance_statements(statements) == []
    assert _governance_snapshot() == before

    # A future expiry is an open window: the same request now succeeds.
    monkeypatch.setenv(
        "CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT",
        (datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )
    get_settings.cache_clear()
    allowed = client.post(
        "/api/ip/deadline-rules", headers=company["headers"], json=_rule_payload()
    )
    assert allowed.status_code == 201, allowed.text


def test_a1_decision_03_calendar_writers_need_entitlement_but_not_rollout(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "false")
    get_settings.cache_clear()

    unentitled = _company(client, "a1-calendar-unentitled", entitled=False)
    refused = client.post(
        "/api/ip/working-calendars", headers=unentitled["headers"], json=_calendar_payload()
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["reason"] == "missing_entitlement"

    entitled = _company(client, "a1-calendar-entitled")
    approver = _user(client, entitled, name="Calendar Approver")
    # Rollout closed, entitlement present: calendars are outside the A0 drain.
    proposed = client.post(
        "/api/ip/working-calendars", headers=entitled["headers"], json=_calendar_payload()
    )
    assert proposed.status_code == 201, proposed.text
    rule_refused = client.post(
        "/api/ip/deadline-rules", headers=entitled["headers"], json=_rule_payload()
    )
    assert rule_refused.status_code == 503
    assert rule_refused.json()["code"] == "ip_rule_governance_quiesced"

    # Losing the entitlement stops activation of an already proposed calendar.
    with get_session_factory()() as session:
        from caseops_api.db.models import BillingSubscription

        subscription = session.scalar(
            select(BillingSubscription).where(
                BillingSubscription.company_id == entitled["company_id"]
            )
        )
        assert subscription is not None
        subscription.entitlement_overrides_json = {"ip_rule_governance": False}
        session.commit()
    revoked = client.post(
        f"/api/ip/working-calendars/{proposed.json()['id']}/activate",
        headers=approver["headers"],
        json={"reason": "Independent calendar review is complete."},
    )
    assert revoked.status_code == 403, revoked.text
    with get_session_factory()() as session:
        row = session.get(LegalWorkingCalendarVersion, proposed.json()["id"])
        assert row is not None and row.status == "candidate"

    grant_ip_rule_governance_entitlement(entitled["company_id"])
    activated = client.post(
        f"/api/ip/working-calendars/{proposed.json()['id']}/activate",
        headers=approver["headers"],
        json={"reason": "Independent calendar review is complete."},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"


# --------------------------------------------------------------------------- ownership


def test_a1_ownership_01_rule_keys_are_owned_per_company_without_leaks(
    client: TestClient,
) -> None:
    first = _company(client, "a1-owner-first")
    first_legal = _user(client, first, name="First Legal")
    first_reviewer = _user(client, first, name="First Reviewer")
    second = _company(client, "a1-owner-second")

    first_rule = _propose(client, first["headers"])
    assert _activate(
        client, first_legal["headers"], first_rule["id"], first_reviewer["membership_id"]
    ).status_code == 200

    # Same key, different scope: the second company is neither blocked nor
    # told that a rule with this key exists elsewhere.
    second_rule = _propose(client, second["headers"], stage="hearing")
    assert second_rule["key"] == first_rule["key"]
    assert second_rule["rule_set_id"] != first_rule["rule_set_id"]
    assert second_rule["version"] == 1
    assert second_rule["stage"] == "hearing"

    # Within one company a key still has exactly one scope.
    same_company_conflict = client.post(
        "/api/ip/deadline-rules",
        headers=second["headers"],
        json={**_rule_payload(), "stage": "examination"},
    )
    assert same_company_conflict.status_code == 409
    assert "this workspace" in same_company_conflict.json()["detail"].lower()

    with get_session_factory()() as session:
        owners = dict(
            session.execute(
                select(IpRuleSet.id, IpRuleSet.company_id).where(
                    IpRuleSet.id.in_([first_rule["rule_set_id"], second_rule["rule_set_id"]])
                )
            ).all()
        )
    assert owners == {
        first_rule["rule_set_id"]: first["company_id"],
        second_rule["rule_set_id"]: second["company_id"],
    }

    # Every read and write path answers the other tenant's id like a missing one.
    missing_id = "00000000-0000-4000-8000-00000000abcd"
    for rule_id in (first_rule["id"], missing_id):
        assert client.get(
            f"/api/ip/deadline-rules/{rule_id}/impact", headers=second["headers"]
        ).status_code == 404
        assert client.post(
            f"/api/ip/deadline-rules/{rule_id}/activate",
            headers=second["headers"],
            json={"reviewer_membership_id": second["owner_id"]},
        ).status_code == 404
        assert client.post(
            f"/api/ip/deadline-rules/{rule_id}/transition",
            headers=second["headers"],
            json={"impact_token": "x", "reason": "Cross-tenant probe must not resolve."},
        ).status_code == 404
        assert client.put(
            "/api/ip/rule-policies",
            headers=second["headers"],
            json={"rule_version_id": rule_id},
        ).status_code == 404

    matter = _mk_matter(client, second["token"], "A1-OWNERSHIP")
    docket = _docket_for_matter(client, second["headers"], matter_id=matter["id"])
    deadline_answers = []
    for rule_id in (first_rule["id"], missing_id):
        response = client.post(
            f"/api/ip/dockets/{docket['id']}/deadlines",
            headers=second["headers"],
            json={
                "title": "Cross-tenant rule must not calculate",
                "rule_version_id": rule_id,
                "calendar_version_id": missing_id,
                "base_date": "2026-08-14",
                "base_date_certainty": "certain",
            },
        )
        deadline_answers.append((response.status_code, response.json()["detail"]))
    assert deadline_answers[0] == deadline_answers[1] == (
        409,
        "An active rule version is required.",
    )

    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace", headers=second["headers"]
    )
    assert workspace.status_code == 200, workspace.text
    assert [row["id"] for row in workspace.json()["rules"]] == [second_rule["id"]]
    assert workspace.json()["eligible_rule_version_ids"] == []
    assert client.get("/api/ip/rule-policies", headers=second["headers"]).json() == []


# --------------------------------------------------------------------------- reviewer


def test_a1_reviewer_01_reviewer_must_hold_rules_activate(client: TestClient) -> None:
    company = _company(client, "a1-reviewer")
    other = _company(client, "a1-reviewer-other")
    legal = _user(client, company, name="Legal Approver")
    viewer = _user(client, company, name="Plain Viewer", role="viewer")
    member = _user(client, company, name="Plain Member", role="member")
    stripped_admin = _user(client, company, name="Stripped Admin")
    _assign_role(
        client,
        company,
        stripped_admin["membership_id"],
        _custom_role(client, company, name="IP reader only", permissions=["ip:read"]),
    )
    inactive_admin = _user(client, company, name="Former Admin")
    deactivated = client.patch(
        f"/api/companies/current/users/{inactive_admin['membership_id']}",
        headers=company["headers"],
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    foreign_admin = _user(client, other, name="Foreign Admin")
    qualified_member = _user(client, company, name="Rule Reviewer Member", role="member")
    _assign_role(
        client,
        company,
        qualified_member["membership_id"],
        _custom_role(
            client,
            company,
            name="IP rule reviewer",
            permissions=["ip:read", "ip:rules_activate"],
        ),
    )

    rule = _propose(client, company["headers"])
    before = _governance_snapshot()
    for reviewer in (viewer, member, stripped_admin, inactive_admin, foreign_admin):
        refused = _activate(client, legal["headers"], rule["id"], reviewer["membership_id"])
        assert refused.status_code == 409, (reviewer["name"], refused.text)
        body = refused.json()
        assert body["code"] == "ip_rule_reviewer_unqualified", reviewer["name"]
        assert body["field"] == "reviewer_membership_id", reviewer["name"]
        assert body["required_capability"] == "ip:rules_activate", reviewer["name"]
    assert _governance_snapshot() == before

    # Distinctness still applies to qualified members.
    assert _activate(client, legal["headers"], rule["id"], company["owner_id"]).status_code == 409
    assert _activate(
        client, legal["headers"], rule["id"], legal["membership_id"]
    ).status_code == 409

    activated = _activate(client, legal["headers"], rule["id"], qualified_member["membership_id"])
    assert activated.status_code == 200, activated.text
    assert activated.json()["reviewer_label_snapshot"] == "Rule Reviewer Member"


def test_a1_reviewer_02_custom_role_refusals_at_the_service_boundary(
    client: TestClient,
) -> None:
    company = _company(client, "a1-reviewer-service")
    legal = _user(client, company, name="Service Legal")
    proposer = _user(client, company, name="Custom Proposer", role="member")
    _assign_role(
        client,
        company,
        proposer["membership_id"],
        _custom_role(
            client,
            company,
            name="IP rule author and approver",
            permissions=["ip:read", "ip:rules_propose", "ip:rules_activate"],
        ),
    )
    proposer = _login(client, company, proposer)
    unqualified = _user(client, company, name="Custom Reader", role="member")
    _assign_role(
        client,
        company,
        unqualified["membership_id"],
        _custom_role(client, company, name="IP rule reader", permissions=["ip:read"]),
    )
    rule = _propose(client, proposer["headers"])

    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as caught:
            ip_deadline_workflow.activate_rule_version(
                session,
                context=_context(session, legal["membership_id"]),
                rule_version_id=rule["id"],
                payload=IpRuleActivationRequest(
                    reviewer_membership_id=unqualified["membership_id"]
                ),
            )
        session.rollback()
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "ip_rule_reviewer_unqualified"

    # A custom-role proposer that also holds ip:rules_activate still cannot
    # approve its own proposal, as legal approver or as fixture reviewer.
    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as self_approval:
            ip_deadline_workflow.activate_rule_version(
                session,
                context=_context(session, proposer["membership_id"]),
                rule_version_id=rule["id"],
                payload=IpRuleActivationRequest(reviewer_membership_id=legal["membership_id"]),
            )
        session.rollback()
    assert self_approval.value.status_code == 409
    assert "independent" in str(self_approval.value.detail).lower()

    with get_session_factory()() as session:
        with pytest.raises(HTTPException) as proposer_as_reviewer:
            ip_deadline_workflow.activate_rule_version(
                session,
                context=_context(session, legal["membership_id"]),
                rule_version_id=rule["id"],
                payload=IpRuleActivationRequest(
                    reviewer_membership_id=proposer["membership_id"]
                ),
            )
        session.rollback()
    assert proposer_as_reviewer.value.status_code == 409
    assert "independent" in str(proposer_as_reviewer.value.detail).lower()

    with get_session_factory()() as session:
        row = session.get(IpRuleVersion, rule["id"])
        assert row is not None and row.status == "candidate"
        assert row.reviewed_by_membership_id is None


# --------------------------------------------------------------------------- fixtures


def test_a1_kind_01_fixture_must_exercise_the_definition_being_activated(
    client: TestClient,
) -> None:
    company = _company(client, "a1-fixture-binding")
    legal = _user(client, company, name="Fixture Legal")
    reviewer = _user(client, company, name="Fixture Reviewer")

    payload = _rule_payload()
    # Self-consistent but irrelevant: two business days really do land on
    # 2026-08-19, yet the rule being activated says one business day.
    payload["fixtures"][0]["calculation"]["duration_value"] = 2
    payload["fixtures"][0]["expected_result_on"] = "2026-08-19"
    rule = _propose(client, company["headers"], fixtures=payload["fixtures"])

    blocked = _activate(client, legal["headers"], rule["id"], reviewer["membership_id"])
    assert blocked.status_code == 409, blocked.text
    assert "fixture" in blocked.json()["detail"].lower()

    honest = _propose(client, company["headers"], key="in-tm-examination-response-v2")
    assert _activate(
        client, legal["headers"], honest["id"], reviewer["membership_id"]
    ).status_code == 200


# --------------------------------------------------------------------------- locks


@contextmanager
def _orm_statements(session: Session) -> Iterator[list[str]]:
    compiled: list[str] = []

    def record(state) -> None:
        if state.is_select:
            compiled.append(
                " ".join(str(state.statement.compile(dialect=postgresql.dialect())).split())
            )

    event.listen(session, "do_orm_execute", record)
    try:
        yield compiled
    finally:
        event.remove(session, "do_orm_execute", record)


def _assert_rule_set_lock_first(statements: list[str], label: str) -> None:
    lock_positions = [
        index
        for index, statement in enumerate(statements)
        if "FROM ip_rule_sets" in statement
        and "FOR UPDATE" in statement
        and "JOIN" not in statement
    ]
    assert lock_positions, (label, statements)
    lock = lock_positions[0]
    for index, statement in enumerate(statements):
        # A transition plans its alert recipients with one unlocked read of
        # the policy selectors so it can fence them before any rule lock
        # (F4b deadlock fix); every policy lock, write or decision read
        # still follows the rule-set lock.
        planning_read = (
            label == "transition"
            and statement.startswith("SELECT company_ip_rule_policies.updated_by_membership_id")
            and "FOR UPDATE" not in statement
        )
        if ("company_ip_rule_policies" in statement and not planning_read) or (
            "FROM ip_rule_versions" in statement and "FOR UPDATE" in statement
        ):
            assert index > lock, (label, statement)
        if "ip_rule_versions.status =" in statement and "FOR UPDATE" not in statement:
            # The sibling (overlap) scan.
            assert index > lock, (label, statement)


def test_a1_lock_01_rule_writers_take_the_rule_set_lock_first(client: TestClient) -> None:
    company = _company(client, "a1-lock-order")
    legal = _user(client, company, name="Lock Legal")
    reviewer = _user(client, company, name="Lock Reviewer")
    first = _propose(client, company["headers"])
    assert _activate(
        client, legal["headers"], first["id"], reviewer["membership_id"]
    ).status_code == 200
    successor = _propose(client, company["headers"], effective_from="2027-01-01")
    successor_impact = client.get(
        f"/api/ip/deadline-rules/{successor['id']}/impact", headers=legal["headers"]
    ).json()

    with get_session_factory()() as session, _orm_statements(session) as statements:
        ip_deadline_workflow.activate_rule_version(
            session,
            context=_context(session, legal["membership_id"]),
            rule_version_id=successor["id"],
            payload=IpRuleActivationRequest(
                reviewer_membership_id=reviewer["membership_id"],
                supersede_overlapping=True,
                select_for_company=False,
                impact_acknowledged=True,
                impact_reason="Lock-order proof supersedes the 2026 version.",
                impact_token=successor_impact["impact_token"],
            ),
        )
    _assert_rule_set_lock_first(statements, "activate")

    with get_session_factory()() as session, _orm_statements(session) as statements:
        policy_version = session.scalar(
            select(CompanyIpRulePolicy.version).where(
                CompanyIpRulePolicy.company_id == company["company_id"]
            )
        )
        statements.clear()
        ip_deadline_workflow.select_company_rule_version(
            session,
            context=_context(session, legal["membership_id"]),
            payload=IpCompanyRuleSelectionRequest(
                rule_version_id=successor["id"],
                expected_policy_version=policy_version,
            ),
        )
    _assert_rule_set_lock_first(statements, "select policy")

    impact = client.get(
        f"/api/ip/deadline-rules/{successor['id']}/impact", headers=legal["headers"]
    ).json()
    with get_session_factory()() as session, _orm_statements(session) as statements:
        ip_deadline_workflow.transition_rule_version(
            session,
            context=_context(session, legal["membership_id"]),
            rule_version_id=successor["id"],
            payload=IpRuleTransitionRequest(
                impact_token=impact["impact_token"],
                reason="Lock-order proof for emergency disable.",
                emergency_disable=True,
            ),
        )
    _assert_rule_set_lock_first(statements, "transition")


def test_a1_decision_order_is_one_function_whose_first_statement_is_the_fence() -> None:
    """Every rule writer starts with the one decision; it starts with the fence."""

    import ast
    import inspect
    import textwrap

    def first_call(function) -> str:
        tree = ast.parse(textwrap.dedent(inspect.getsource(function)))
        body = tree.body[0].body
        statements = [
            node
            for node in body
            if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
        ]
        call = statements[0].value
        assert isinstance(call, ast.Call)
        return call.func.id

    for writer in (
        ip_deadline_workflow.propose_rule_version,
        ip_deadline_workflow.activate_rule_version,
        ip_deadline_workflow.transition_rule_version,
        ip_deadline_workflow.select_company_rule_version,
    ):
        assert first_call(writer) == "_assert_rule_governance_writer_allowed", writer.__name__
    for writer in (
        ip_deadline_workflow.propose_calendar_version,
        ip_deadline_workflow.activate_calendar_version,
    ):
        assert first_call(writer) == "_assert_rule_governance_entitled", writer.__name__
    assert (
        first_call(ip_deadline_workflow._assert_rule_governance_writer_allowed)
        == "_assert_rule_governance_mutation_enabled"
    )


def test_a1_owned_rule_version_hides_unowned_legacy_rows(client: TestClient) -> None:
    """Dual-read: a rule set with no backfilled owner is invisible, not guessed."""

    company = _company(client, "a1-legacy-null")
    rule = _propose(client, company["headers"])
    with get_session_factory()() as session:
        rule_set = session.get(IpRuleSet, rule["rule_set_id"])
        assert rule_set is not None
        rule_set.company_id = None
        session.commit()
    assert client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact", headers=company["headers"]
    ).status_code == 404
    assert client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=company["headers"],
        json={"reviewer_membership_id": company["owner_id"]},
    ).status_code == 404
    with get_session_factory()() as session:
        assert (
            ip_deadline_workflow.owned_rule_version(
                session,
                company_id=company["company_id"],
                rule_version_id=rule["id"],
            )
            is None
        )
