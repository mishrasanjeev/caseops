"""B4-ADJ-08: a deadline rule's fixtures run on an active working calendar.

The governance card refused to propose a rule without an active working
calendar, but the API accepted any embedded calendar snapshot, including a
made-up calendar id, a candidate calendar or another tenant's calendar. The
server now enforces it on proposal (field-anchored 422) and on activation
(typed 409, predicted by the rule record's ``activation_blocked_reasons``).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import IpRuleSet, IpRuleVersion
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


@pytest.fixture(autouse=True)
def _governance_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


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


def _calendar_error(response) -> dict:
    assert response.status_code == 422, response.text
    error = response.json()["errors"][0]
    assert error["loc"] == [
        "body",
        "fixtures",
        0,
        "calculation",
        "calendar",
        "calendar_version_id",
    ]
    return error


def test_rule_proposal_refuses_a_calendar_that_is_not_active_in_this_workspace(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    grant_ip_rule_governance_entitlement(company_id)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    _legal_id, legal_token = _member(
        client, owner_token, name="Calendar Approver", email="cal-approver@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)

    # A made-up calendar id: the shape the browser alone used to refuse.
    made_up = client.post("/api/ip/deadline-rules", headers=owner_headers, json=_rule_payload())
    assert _calendar_error(made_up)["type"] == "ip_rule_fixture_calendar_not_active"

    # A candidate calendar of this workspace is not active yet.
    candidate = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    )
    assert candidate.status_code == 201, candidate.text
    on_candidate = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), candidate.json()),
    )
    assert _calendar_error(on_candidate)["type"] == "ip_rule_fixture_calendar_not_active"
    assert _rule_count(company_id) == 0

    activated = client.post(
        f"/api/ip/working-calendars/{candidate.json()['id']}/activate",
        headers=legal_headers,
        json={"reason": "Reviewed official calendar source and conflicts."},
    )
    assert activated.status_code == 200, activated.text
    calendar = activated.json()

    # The embedded snapshot must be the stored version, not an edited copy.
    tampered = rule_payload_on_calendar(_rule_payload(), calendar)
    tampered["fixtures"][0]["calculation"]["calendar"]["holidays"] = []
    mismatch = client.post("/api/ip/deadline-rules", headers=owner_headers, json=tampered)
    assert _calendar_error(mismatch)["type"] == "ip_rule_fixture_calendar_snapshot_mismatch"
    assert _rule_count(company_id) == 0

    accepted = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), calendar),
    )
    assert accepted.status_code == 201, accepted.text
    assert "fixture_calendar_not_active" not in accepted.json()["activation_blocked_reasons"]
    assert _rule_count(company_id) == 1


def test_another_tenants_active_calendar_is_not_this_workspaces_calendar(
    client: TestClient,
) -> None:
    first = bootstrap_company(client)
    grant_ip_rule_governance_entitlement(str(first["company"]["id"]))
    first_token = str(first["access_token"])
    _first_legal, first_legal_token = _member(
        client, first_token, name="First Approver", email="first-approver@asterlegal.in"
    )
    foreign_calendar = activated_calendar(
        client, auth_headers(first_token), auth_headers(first_legal_token)
    )

    client.cookies.clear()
    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Rules LLP",
            "company_slug": "second-rules",
            "company_type": "law_firm",
            "owner_full_name": "Second Owner",
            "owner_email": "owner@secondrules.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert second.status_code == 200, second.text
    client.cookies.clear()
    second_company = str(second.json()["company"]["id"])
    grant_ip_rule_governance_entitlement(second_company)
    refused = client.post(
        "/api/ip/deadline-rules",
        headers=auth_headers(str(second.json()["access_token"])),
        json=rule_payload_on_calendar(_rule_payload(), foreign_calendar),
    )
    assert _calendar_error(refused)["type"] == "ip_rule_fixture_calendar_not_active"
    assert _rule_count(second_company) == 0


def test_activation_refuses_a_rule_whose_fixture_calendar_was_superseded(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    grant_ip_rule_governance_entitlement(company_id)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    _legal_id, legal_token = _member(
        client, owner_token, name="Rule Legal Approver", email="rule-legal@asterlegal.in"
    )
    reviewer_id, _reviewer_token = _member(
        client, owner_token, name="Rule Reviewer", email="rule-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-ADJ08")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])
    calendar = activated_calendar(client, owner_headers, legal_headers)
    proposed = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), calendar),
    )
    assert proposed.status_code == 201, proposed.text
    rule = proposed.json()

    # A newer calendar version supersedes the one the fixtures ran on.
    newer = client.post(
        "/api/ip/working-calendars",
        headers=owner_headers,
        json={**_calendar_payload(), "holidays": ["2026-08-17", "2026-10-02"]},
    )
    assert newer.status_code == 201, newer.text
    superseded = client.post(
        f"/api/ip/working-calendars/{newer.json()['id']}/activate",
        headers=legal_headers,
        json={"reason": "Gazette added a holiday.", "conflict_reviewed": True},
    )
    assert superseded.status_code == 200, superseded.text

    workspace = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace", headers=legal_headers
    )
    assert workspace.status_code == 200, workspace.text
    record = next(row for row in workspace.json()["rules"] if row["id"] == rule["id"])
    assert record["can_activate"] is False
    assert "fixture_calendar_not_active" in record["activation_blocked_reasons"]

    refused = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ip_rule_fixture_calendar_not_active"
    with get_session_factory()() as session:
        stored = session.get(IpRuleVersion, rule["id"])
        assert stored is not None and stored.status == "candidate"

    # Proposed again on the current calendar, the rule activates.
    again = client.post(
        "/api/ip/deadline-rules",
        headers=owner_headers,
        json=rule_payload_on_calendar(_rule_payload(), superseded.json()),
    )
    assert again.status_code == 201, again.text
    activated = client.post(
        f"/api/ip/deadline-rules/{again.json()['id']}/activate",
        headers=legal_headers,
        json={
            "reviewer_membership_id": reviewer_id,
            "select_for_company": True,
            "auto_confirm_eligible": False,
        },
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
