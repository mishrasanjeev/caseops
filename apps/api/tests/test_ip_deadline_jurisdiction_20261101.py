"""B4-ADJ-08: a governed deadline is counted on a calendar of its rule's jurisdiction.

Rule and calendar jurisdictions were never compared, so an IN rule could be
proposed with fixtures on, and deadlines counted on, any active working
calendar of the company, and an opposition deadline could use a rule of
another jurisdiction than its proceeding. The server now refuses each with a
typed error naming the field to change; nothing is written.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import IpDeadline, IpProceeding, IpRuleSet, IpRuleVersion
from caseops_api.db.session import get_session_factory
from tests.ip_rule_governance_support import (
    activated_calendar,
    grant_ip_rule_governance_entitlement,
    rule_payload_on_calendar,
)
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _member,
    _rule_payload,
)
from tests.test_ip_opposition_opponent_workflow import (
    _OPPONENT_DEADLINES_ROUTE,
    _governed_rule,
    _profile,
    _route,
)
from tests.test_ip_opposition_opponent_workflow import (
    _fixture as _opponent_fixture,
)


@pytest.fixture(autouse=True)
def _governance_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _uk_calendar_payload() -> dict:
    return {
        **_calendar_payload(),
        "key": "uk-ipo-2026",
        "name": "UK IPO working calendar 2026",
        "jurisdiction": "GB",
        "office": "UK IPO",
        "timezone": "Europe/London",
        "holidays": ["2026-08-31"],
        "source_reference": "https://official.example/uk-ipo/calendar/2026",
        "source_hash": "c" * 64,
    }


def _rule_count(company_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(IpRuleVersion)
                .join(IpRuleSet, IpRuleSet.id == IpRuleVersion.rule_set_id)
                .where(IpRuleSet.company_id == company_id)
            )
            or 0
        )


def _deadline_count(company_id: str) -> int:
    with get_session_factory()() as session:
        return int(
            session.scalar(
                select(func.count())
                .select_from(IpDeadline)
                .where(IpDeadline.company_id == company_id)
            )
            or 0
        )


def _activate(client: TestClient, headers: dict, rule_id: str, reviewer_id: str):
    return client.post(
        f"/api/ip/deadline-rules/{rule_id}/activate",
        headers=headers,
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )


def test_rule_fixtures_and_deadlines_refuse_a_calendar_of_another_jurisdiction(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    grant_ip_rule_governance_entitlement(company_id)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    _legal_id, legal_token = _member(
        client, owner_token, name="Jurisdiction Approver", email="jur-approver@asterlegal.in"
    )
    reviewer_id, _ = _member(
        client, owner_token, name="Jurisdiction Reviewer", email="jur-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    india = activated_calendar(client, owner_headers, legal_headers)
    uk = activated_calendar(client, owner_headers, legal_headers, _uk_calendar_payload())

    # An IN rule whose fixture runs on the active GB calendar.
    refused = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), uk),
    )
    assert refused.status_code == 422, refused.text
    error = refused.json()["errors"][0]
    assert error["loc"] == [
        "body",
        "fixtures",
        0,
        "calculation",
        "calendar",
        "calendar_version_id",
    ]
    assert error["type"] == "ip_rule_fixture_calendar_jurisdiction_mismatch"
    assert "another jurisdiction than the rule (IN)" in error["msg"]
    assert _rule_count(company_id) == 0

    # Jurisdiction is compared case-insensitively, as both writers store it upper-cased.
    lower = rule_payload_on_calendar({**_rule_payload(), "jurisdiction": " in "}, india)
    proposed = client.post("/api/ip/deadline-rules", headers=owner_headers, json=lower)
    assert proposed.status_code == 201, proposed.text
    assert "fixture_calendar_jurisdiction_mismatch" not in (
        proposed.json()["activation_blocked_reasons"]
    )
    rule = _activate(client, legal_headers, proposed.json()["id"], reviewer_id)
    assert rule.status_code == 200, rule.text

    matter = _mk_matter(client, owner_token, "IP-ADJ08-JUR")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])
    proposal = {
        "title": "Respond to examination report",
        "rule_version_id": rule.json()["id"],
        "base_date": "2026-08-14",
        "base_date_certainty": "certain",
        "is_critical": True,
    }
    wrong_calendar = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={**proposal, "calendar_version_id": uk["id"]},
    )
    assert wrong_calendar.status_code == 409, wrong_calendar.text
    body = wrong_calendar.json()
    assert body["code"] == "ip_deadline_calendar_jurisdiction_mismatch"
    assert body["field"] == "calendar_version_id"
    assert _deadline_count(company_id) == 0

    counted = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={**proposal, "calendar_version_id": india["id"]},
    )
    assert counted.status_code == 201, counted.text
    assert counted.json()["result_on"] == "2026-08-18"


def test_activation_refuses_a_rule_whose_fixture_calendar_is_another_jurisdiction(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    grant_ip_rule_governance_entitlement(company_id)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    _legal_id, legal_token = _member(
        client, owner_token, name="Legacy Approver", email="legacy-approver@asterlegal.in"
    )
    reviewer_id, _ = _member(
        client, owner_token, name="Legacy Reviewer", email="legacy-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    india = activated_calendar(client, owner_headers, legal_headers)
    proposed = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), india),
    )
    assert proposed.status_code == 201, proposed.text
    rule_id = proposed.json()["id"]
    # A candidate proposed before jurisdictions were compared: its rule set is
    # GB while its fixtures ran on the IN calendar.
    with get_session_factory()() as session:
        version = session.get(IpRuleVersion, rule_id)
        assert version is not None
        rule_set = session.get(IpRuleSet, version.rule_set_id)
        assert rule_set is not None
        rule_set.jurisdiction = "GB"
        session.commit()

    matter = _mk_matter(client, owner_token, "IP-ADJ08-LEGACY")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])
    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace", headers=legal_headers
    )
    assert workspace.status_code == 200, workspace.text
    record = next(row for row in workspace.json()["rules"] if row["id"] == rule_id)
    assert record["can_activate"] is False
    assert "fixture_calendar_jurisdiction_mismatch" in record["activation_blocked_reasons"]
    assert "fixture_calendar_not_active" not in record["activation_blocked_reasons"]

    refused = _activate(client, legal_headers, rule_id, reviewer_id)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_rule_fixture_calendar_jurisdiction_mismatch"
    with get_session_factory()() as session:
        stored = session.get(IpRuleVersion, rule_id)
        assert stored is not None and stored.status == "candidate"


def test_opposition_deadline_refuses_a_rule_of_another_jurisdiction_than_the_proceeding(
    client: TestClient,
) -> None:
    bootstrap, _, docket, proceeding = _opponent_fixture(client)
    company_id = str(bootstrap["company"]["id"])
    workspace = _profile(client, bootstrap=bootstrap, docket=docket, proceeding=proceeding)
    rule, calendar, _primary, _backup = _governed_rule(
        client, bootstrap=bootstrap, workflow_stage="notice_filing_due"
    )
    assert rule["jurisdiction"] == "IN"
    with get_session_factory()() as session:
        row = session.get(IpProceeding, proceeding["id"])
        assert row is not None
        row.jurisdiction = "GB"
        session.commit()

    headers = auth_headers(str(bootstrap["access_token"]))
    payload = {
        "workflow_stage": "notice_filing_due",
        "trigger_event_id": workspace["profile_event"]["id"],
        "rule_version_id": rule["id"],
        "calendar_version_id": calendar["id"],
        "base_date": "2026-08-23",
        "base_date_certainty": "certain",
        "date_precision": "date",
        "is_critical": True,
    }
    route = _route(_OPPONENT_DEADLINES_ROUTE, docket, proceeding)
    refused = client.post(route, headers=headers, json=payload)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_deadline_rule_jurisdiction_mismatch"
    assert refused.json()["field"] == "rule_version_id"
    assert _deadline_count(company_id) == 0

    # The proceeding's free-text jurisdiction is compared normalized.
    with get_session_factory()() as session:
        row = session.get(IpProceeding, proceeding["id"])
        assert row is not None
        row.jurisdiction = " in "
        session.commit()
    accepted = client.post(route, headers=headers, json=payload)
    assert accepted.status_code == 201, accepted.text
    assert _deadline_count(company_id) == 1


def test_another_tenants_calendar_jurisdiction_is_never_consulted(client: TestClient) -> None:
    """The deadline calendar lookup stays company-scoped: another tenant's
    active calendar answers like a missing one, before any jurisdiction text."""

    first = bootstrap_company(client)
    grant_ip_rule_governance_entitlement(str(first["company"]["id"]))
    first_token = str(first["access_token"])
    _l, first_legal = _member(
        client, first_token, name="First Legal", email="first-legal@asterlegal.in"
    )
    reviewer_id, _ = _member(
        client, first_token, name="First Reviewer", email="first-reviewer@asterlegal.in"
    )
    first_headers = auth_headers(first_token)
    india = activated_calendar(client, first_headers, auth_headers(first_legal))
    proposed = client.post(
        "/api/ip/deadline-rules",
        headers=first_headers,
        json=rule_payload_on_calendar(_rule_payload(), india),
    )
    assert proposed.status_code == 201, proposed.text
    assert _activate(
        client, auth_headers(first_legal), proposed.json()["id"], reviewer_id
    ).status_code == 200

    client.cookies.clear()
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Calendars LLP",
            "company_slug": "second-calendars",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondcalendars.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert second.status_code == 200, second.text
    client.cookies.clear()
    second_token = str(second.json()["access_token"])
    matter = _mk_matter(client, second_token, "IP-ADJ08-TENANT")
    docket = _docket_for_matter(client, auth_headers(second_token), matter_id=matter["id"])
    refused = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=auth_headers(second_token),
        json={
            "title": "Foreign rule and calendar",
            "rule_version_id": proposed.json()["id"],
            "calendar_version_id": india["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    )
    assert refused.status_code == 409, refused.text
    assert "jurisdiction" not in refused.text.lower()
    assert _deadline_count(str(second.json()["company"]["id"])) == 0
