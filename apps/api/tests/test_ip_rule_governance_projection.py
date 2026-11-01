"""Server-computed rule-governance projection for the deadline workspace UI.

The IP page must never re-implement governance policy, so
``GET /api/ip/dockets/{id}/deadline-workspace`` returns, for the current
viewer, the decision each governance writer would make, and every rule and
calendar version carries a viewer-scoped ``can_activate`` with every blocking
reason. Each test pairs the projection with the real writer call, so an option
the projection enables is accepted and an option it blocks is refused:

* ``GOV-PROJ-01`` action gates (rollout, expiry, entitlement) agree with writers
* ``GOV-PROJ-02`` capability gates per role agree with writers
* ``GOV-PROJ-03`` calendar self-approval is predicted, and activation agrees
* ``GOV-PROJ-04`` the reviewer picker offers exactly what the validator accepts
* ``GOV-PROJ-05`` no qualified reviewer means activation is never offered
* ``GOV-PROJ-06`` failing fixtures, unsupported kinds and missing proposers
* ``GOV-PROJ-07`` another tenant's versions, members and entitlement never leak
* ``GOV-PROJ-08`` source hashes are SHA-256 hex: field-addressed 422s
* ``GOV-PROJ-09`` too few other approvers is named, for calendars and rules
* ``GOV-PROJ-10`` only the proposer withdraws its own candidate calendar
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from caseops_api.core.settings import get_settings
from caseops_api.db.models import AuditEvent, CompanyMembership, LegalWorkingCalendarVersion
from caseops_api.db.session import get_session_factory
from tests.ip_rule_governance_support import (
    grant_ip_rule_governance_entitlement,
    rule_payload_for_company,
)
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _calendar_payload, _docket_for_matter, _rule_payload
from tests.test_ip_rule_emergency_disable import _governed_company, _propose_deadline
from tests.test_ip_rule_governance_a1 import _company, _propose, _user

_ACTIONS = ("calendar_proposal", "calendar_activation", "rule_proposal", "rule_activation")


@pytest.fixture(autouse=True)
def _rollout_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    monkeypatch.delenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", raising=False)
    get_settings.cache_clear()


def _with_docket(client: TestClient, company: dict) -> dict:
    matter = _mk_matter(client, company["token"], f"{company['slug'].upper()}-GOV")
    company["docket"] = _docket_for_matter(client, company["headers"], matter_id=matter["id"])
    return company


def _workspace(client: TestClient, company: dict, headers: dict) -> dict:
    response = client.get(
        f"/api/ip/dockets/{company['docket']['id']}/deadline-workspace", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def _record(workspace: dict, kind: str, record_id: str) -> dict:
    return next(item for item in workspace[kind] if item["id"] == record_id)


@pytest.mark.parametrize(
    ("entitled", "rollout", "expired", "calendar_reasons", "rule_reasons"),
    [
        (False, False, False, ["missing_entitlement"], ["rollout_disabled", "missing_entitlement"]),
        (False, True, False, ["missing_entitlement"], ["missing_entitlement"]),
        (True, False, False, [], ["rollout_disabled"]),
        (True, True, True, [], ["rollout_expired"]),
        (True, True, False, [], []),
    ],
    ids=[
        "unentitled-rollout-off",
        "unentitled-rollout-on",
        "entitled-rollout-off",
        "entitled-rollout-expired",
        "entitled-rollout-on",
    ],
)
def test_gov_proj_01_action_gates_agree_with_the_writers(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    entitled: bool,
    rollout: bool,
    expired: bool,
    calendar_reasons: list[str],
    rule_reasons: list[str],
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-gates", entitled=entitled))
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true" if rollout else "false")
    if expired:
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT", past)
    get_settings.cache_clear()

    governance = _workspace(client, company, company["headers"])["governance"]
    assert set(governance) == set(_ACTIONS)
    for action in _ACTIONS:
        decision = governance[action]
        expected = calendar_reasons if action.startswith("calendar") else rule_reasons
        assert decision["reasons"] == expected, action
        assert decision["available"] is (expected == [])
        assert decision["code"] == (expected[0] if expected else "available")
        assert decision["entitlement_key"] == "ip_rule_governance"
        assert decision["rollout_flag"] == (
            None if action.startswith("calendar") else "ip_rule_governance_enabled"
        )
    assert governance["rule_activation"]["required_capability"] == "ip:rules_activate"
    assert governance["calendar_proposal"]["required_capability"] == "ip:rules_propose"

    # Agreement: each writer answers exactly what its projection predicted.
    for action, path, payload in (
        ("calendar_proposal", "/api/ip/working-calendars", _calendar_payload()),
        (
            "rule_proposal",
            "/api/ip/deadline-rules",
            rule_payload_for_company(client, company["headers"], _rule_payload()),
        ),
    ):
        response = client.post(path, headers=company["headers"], json=payload)
        decision = governance[action]
        if decision["available"]:
            assert response.status_code == 201, (action, response.text)
        else:
            assert response.status_code in {403, 503}, (action, response.text)
            assert response.json()["reason"] == decision["code"], action


def test_gov_proj_02_capability_gates_follow_the_viewer_role(client: TestClient) -> None:
    company = _with_docket(client, _company(client, "gov-proj-roles"))
    partner = _user(client, company, name="Rule Partner", role="partner")
    member = _user(client, company, name="Rule Member", role="member")

    partner_view = _workspace(client, company, partner["headers"])["governance"]
    assert partner_view["rule_proposal"]["reasons"] == ["missing_capability"]
    assert partner_view["calendar_proposal"]["reasons"] == ["missing_capability"]
    assert partner_view["rule_activation"]["available"] is True
    assert partner_view["calendar_activation"]["available"] is True
    refused = client.post(
        "/api/ip/working-calendars", headers=partner["headers"], json=_calendar_payload()
    )
    assert refused.status_code == 403, refused.text

    member_view = _workspace(client, company, member["headers"])["governance"]
    for action in _ACTIONS:
        assert member_view[action]["reasons"] == ["missing_capability"], action


def test_gov_proj_03_calendar_self_approval_is_predicted_and_enforced(
    client: TestClient,
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-calendar"))
    approver = _user(client, company, name="Calendar Approver")
    proposed = client.post(
        "/api/ip/working-calendars", headers=company["headers"], json=_calendar_payload()
    )
    assert proposed.status_code == 201, proposed.text
    calendar_id = proposed.json()["id"]
    assert proposed.json()["proposed_by_membership_id"] == company["owner_id"]
    assert proposed.json()["can_activate"] is False
    assert proposed.json()["activation_blocked_reason"] == "proposer_cannot_self_approve"

    owner_view = _record(_workspace(client, company, company["headers"]), "calendars", calendar_id)
    assert owner_view["can_activate"] is False
    assert owner_view["activation_blocked_reasons"] == ["proposer_cannot_self_approve"]
    self_approval = client.post(
        f"/api/ip/working-calendars/{calendar_id}/activate",
        headers=company["headers"],
        json={"reason": "Self approval attempt for the calendar."},
    )
    assert self_approval.status_code == 409, self_approval.text

    approver_view = _record(
        _workspace(client, company, approver["headers"]), "calendars", calendar_id
    )
    assert approver_view["can_activate"] is True
    assert approver_view["activation_blocked_reason"] is None
    assert approver_view["activation_blocked_reasons"] == []
    activated = client.post(
        f"/api/ip/working-calendars/{calendar_id}/activate",
        headers=approver["headers"],
        json={"reason": "Independent calendar review is complete."},
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["activation_blocked_reason"] == "not_candidate"


def test_gov_proj_04_reviewer_picker_offers_exactly_what_activation_accepts(
    client: TestClient,
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-reviewers"))
    approver = _user(client, company, name="Legal Approver")
    second_admin = _user(client, company, name="Second Admin")
    partner = _user(client, company, name="Rule Partner", role="partner")
    member = _user(client, company, name="Rule Member", role="member")
    viewer = _user(client, company, name="Rule Viewer", role="viewer")

    first = _propose(client, company["headers"])
    # The proposer's own response already predicts the self-approval refusal.
    assert first["proposed_by_membership_id"] == company["owner_id"]
    assert first["activation_blocked_reason"] == "proposer_cannot_self_approve"

    approver_view = _workspace(client, company, approver["headers"])
    approver_record = _record(approver_view, "rules", first["id"])
    offered = approver_record["eligible_reviewer_membership_ids"]
    assert approver_record["can_activate"] is True
    assert offered == sorted([second_admin["membership_id"], partner["membership_id"]])
    for excluded in (company["owner_id"], approver["membership_id"]):
        assert excluded not in offered
    for unqualified in (member, viewer):
        assert unqualified["membership_id"] not in offered
        refused = client.post(
            f"/api/ip/deadline-rules/{first['id']}/activate",
            headers=approver["headers"],
            json={"reviewer_membership_id": unqualified["membership_id"]},
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "ip_rule_reviewer_unqualified"

    member_record = _record(_workspace(client, company, member["headers"]), "rules", first["id"])
    assert member_record["can_activate"] is False
    assert "missing_capability" in member_record["activation_blocked_reasons"]
    assert member_record["eligible_reviewer_membership_ids"] == []

    # Every offered reviewer is accepted by the validator.
    for index, reviewer_id in enumerate(offered):
        candidate = (
            first
            if index == 0
            else _propose(client, company["headers"], key=f"in-tm-picker-agreement-{index}")
        )
        activated = client.post(
            f"/api/ip/deadline-rules/{candidate['id']}/activate",
            headers=approver["headers"],
            json={"reviewer_membership_id": reviewer_id},
        )
        assert activated.status_code == 200, (reviewer_id, activated.text)


def test_gov_proj_05_without_a_qualified_reviewer_activation_is_never_offered(
    client: TestClient,
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-alone"))
    approver = _user(client, company, name="Only Approver")
    rule = _propose(client, company["headers"])

    record = _record(_workspace(client, company, approver["headers"]), "rules", rule["id"])
    assert record["can_activate"] is False
    assert record["activation_blocked_reasons"] == ["no_qualified_reviewer"]
    assert record["eligible_reviewer_membership_ids"] == []
    for reviewer_id in (company["owner_id"], approver["membership_id"]):
        attempt = client.post(
            f"/api/ip/deadline-rules/{rule['id']}/activate",
            headers=approver["headers"],
            json={"reviewer_membership_id": reviewer_id},
        )
        assert attempt.status_code == 409, attempt.text


def test_gov_proj_06_fixture_kind_and_proposer_blockers_agree_with_activation(
    client: TestClient,
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-blockers"))
    approver = _user(client, company, name="Legal Approver")
    reviewer = _user(client, company, name="Fixture Reviewer")
    proposer = _user(client, company, name="Departing Proposer")

    wrong = rule_payload_for_company(client, company["headers"], _rule_payload())
    wrong["key"] = "in-tm-wrong-fixture"
    wrong["fixtures"][0]["expected_result_on"] = "2026-08-19"
    failing = client.post("/api/ip/deadline-rules", headers=company["headers"], json=wrong)
    assert failing.status_code == 201, failing.text
    fee = client.post(
        "/api/ip/deadline-rules",
        headers=company["headers"],
        json={
            **_rule_payload(),
            "key": "in-tm-fee-schedule",
            "rule_kind": "fee",
            "definition": {"amount_inr": 4500},
            "fixtures": [
                {
                    "id": "fee-fixture",
                    "fixture_kind": "positive",
                    "expected_outcome": 4500,
                    "observed_outcome": 4500,
                    "evidence_reference": "fixture:official-fee-schedule",
                }
            ],
        },
    )
    assert fee.status_code == 201, fee.text
    departing = _propose(client, proposer["headers"], key="in-tm-departing-proposer")
    with get_session_factory()() as session:
        session.execute(
            update(CompanyMembership)
            .where(CompanyMembership.id == proposer["membership_id"])
            .values(is_active=False)
        )
        session.commit()

    view = _workspace(client, company, approver["headers"])
    expectations = {
        failing.json()["id"]: (["fixtures_not_passing"], 409),
        fee.json()["id"]: (["rule_kind_unsupported"], 409),
        departing["id"]: (["proposer_unavailable"], 400),
    }
    for rule_id, (reasons, status) in expectations.items():
        record = _record(view, "rules", rule_id)
        assert record["can_activate"] is False, rule_id
        assert record["activation_blocked_reasons"] == reasons, rule_id
        attempt = client.post(
            f"/api/ip/deadline-rules/{rule_id}/activate",
            headers=approver["headers"],
            json={"reviewer_membership_id": reviewer["membership_id"]},
        )
        assert attempt.status_code == status, (reasons, attempt.text)


def test_gov_proj_07_another_tenant_never_sees_versions_members_or_entitlement(
    client: TestClient,
) -> None:
    tenant_a = _with_docket(client, _company(client, "gov-proj-tenant-a"))
    a_approver = _user(client, tenant_a, name="Tenant A Approver")
    a_reviewer = _user(client, tenant_a, name="Tenant A Reviewer")
    a_rule = _propose(client, tenant_a["headers"])
    a_calendar = client.post(
        "/api/ip/working-calendars", headers=tenant_a["headers"], json=_calendar_payload()
    ).json()

    # Tenant B is not entitled: its own decision, never tenant A's.
    tenant_b = _with_docket(client, _company(client, "gov-proj-tenant-b", entitled=False))
    b_approver = _user(client, tenant_b, name="Tenant B Approver")
    b_view = _workspace(client, tenant_b, b_approver["headers"])
    assert b_view["rules"] == [] and b_view["calendars"] == []
    assert b_view["governance"]["calendar_proposal"]["reasons"] == ["missing_entitlement"]
    serialized = json.dumps(b_view)
    for foreign in (
        a_rule["id"],
        a_rule["rule_set_id"],
        a_calendar["id"],
        tenant_a["owner_id"],
        a_approver["membership_id"],
        a_reviewer["membership_id"],
    ):
        assert foreign not in serialized

    # Entitled, tenant B proposes the same key and sees only its own version
    # and its own reviewers.
    grant_ip_rule_governance_entitlement(tenant_b["company_id"])
    b_reviewer = _user(client, tenant_b, name="Tenant B Reviewer")
    b_rule = _propose(client, tenant_b["headers"])
    assert b_rule["version"] == 1 and b_rule["rule_set_id"] != a_rule["rule_set_id"]
    b_view = _workspace(client, tenant_b, b_approver["headers"])
    assert [item["id"] for item in b_view["rules"]] == [b_rule["id"]]
    assert _record(b_view, "rules", b_rule["id"])["eligible_reviewer_membership_ids"] == [
        b_reviewer["membership_id"]
    ]
    assert a_rule["id"] not in json.dumps(b_view)
    a_view = _workspace(client, tenant_a, a_approver["headers"])
    assert [item["id"] for item in a_view["rules"]] == [a_rule["id"]]
    assert _record(a_view, "rules", a_rule["id"])["eligible_reviewer_membership_ids"] == [
        a_reviewer["membership_id"]
    ]


def test_gov_proj_08_source_hash_must_be_sha256_hex(client: TestClient) -> None:
    company = _company(client, "gov-proj-hash")
    bad_rule = {**_rule_payload(), "source_hash": "g" * 64}
    response = client.post("/api/ip/deadline-rules", headers=company["headers"], json=bad_rule)
    assert response.status_code == 422, response.text
    assert [error["loc"] for error in response.json()["errors"]] == [["body", "source_hash"]]

    bad_calendar = {**_calendar_payload(), "source_hash": "z" * 64}
    response = client.post(
        "/api/ip/working-calendars", headers=company["headers"], json=bad_calendar
    )
    assert response.status_code == 422, response.text
    assert [error["loc"] for error in response.json()["errors"]] == [["body", "source_hash"]]

    bad_fixture = _rule_payload()
    bad_fixture["fixtures"][0]["calculation"]["calendar"]["source_hash"] = "x" * 64
    response = client.post("/api/ip/deadline-rules", headers=company["headers"], json=bad_fixture)
    assert response.status_code == 422, response.text
    assert [error["loc"] for error in response.json()["errors"]] == [
        ["body", "fixtures", 0, "calculation", "calendar", "source_hash"]
    ]

    upper = client.post(
        "/api/ip/working-calendars",
        headers=company["headers"],
        json={**_calendar_payload(), "source_hash": "AB" * 32},
    )
    assert upper.status_code == 201, upper.text
    assert upper.json()["source_hash"] == "ab" * 32


def test_gov_proj_08_legacy_non_hex_calendar_hash_refuses_calculation_explicitly(
    client: TestClient,
) -> None:
    """A calendar stored before the hex rule cannot evidence a calculation."""

    governed = _governed_company(client, "gov-proj-legacy-hash")
    with get_session_factory()() as session:
        session.execute(
            update(LegalWorkingCalendarVersion)
            .where(LegalWorkingCalendarVersion.id == governed["calendar_id"])
            .values(source_hash="legacy-free-text-" + "q" * 47)
        )
        session.commit()
    response = _propose_deadline(
        client, governed, governed["legal"]["headers"], "Respond to examination"
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ip_calendar_source_hash_invalid"
    assert response.json()["field"] == "calendar_version_id"
    # The workspace that lists the legacy calendar still renders.
    workspace = client.get(
        f"/api/ip/dockets/{governed['docket']['id']}/deadline-workspace",
        headers=governed["legal"]["headers"],
    )
    assert workspace.status_code == 200, workspace.text


def test_gov_proj_09_too_few_other_approvers_is_named(client: TestClient) -> None:
    """Ram 2026-10-31 BUG-005/006: a proposer alone in the workspace was told
    another approver must activate, with no way to learn none exists. A
    calendar needs one other owner, admin or partner; a rule needs two."""

    company = _with_docket(client, _company(client, "gov-proj-solo"))
    calendar = client.post(
        "/api/ip/working-calendars", headers=company["headers"], json=_calendar_payload()
    )
    assert calendar.status_code == 201, calendar.text
    calendar_id = calendar.json()["id"]
    assert calendar.json()["activation_blocked_reasons"] == [
        "proposer_cannot_self_approve",
        "no_other_approver",
    ]
    rule_id = _propose(client, company["headers"])["id"]
    alone = _workspace(client, company, company["headers"])
    assert _record(alone, "rules", rule_id)["activation_blocked_reasons"] == [
        "proposer_cannot_self_approve",
        "no_qualified_reviewer",
    ]

    approver = _user(client, company, name="Second Approver")
    owner_view = _workspace(client, company, company["headers"])
    assert _record(owner_view, "calendars", calendar_id)["activation_blocked_reasons"] == [
        "proposer_cannot_self_approve"
    ]
    assert _record(owner_view, "rules", rule_id)["activation_blocked_reasons"] == [
        "proposer_cannot_self_approve",
        "no_other_approver",
    ]
    approver_view = _workspace(client, company, approver["headers"])
    assert _record(approver_view, "calendars", calendar_id)["can_activate"] is True
    assert _record(approver_view, "rules", rule_id)["activation_blocked_reasons"] == [
        "no_qualified_reviewer"
    ]

    reviewer = _user(client, company, name="Third Approver")
    complete = _workspace(client, company, company["headers"])
    assert _record(complete, "rules", rule_id)["activation_blocked_reasons"] == [
        "proposer_cannot_self_approve"
    ]
    approver_view = _workspace(client, company, approver["headers"])
    assert _record(approver_view, "rules", rule_id)["can_activate"] is True
    activated = client.post(
        f"/api/ip/deadline-rules/{rule_id}/activate",
        headers=approver["headers"],
        json={"reviewer_membership_id": reviewer["membership_id"]},
    )
    assert activated.status_code == 200, activated.text


def test_gov_proj_10_only_the_proposer_withdraws_a_candidate_calendar(
    client: TestClient,
) -> None:
    company = _with_docket(client, _company(client, "gov-proj-withdraw"))
    approver = _user(client, company, name="Calendar Approver")
    member = _user(client, company, name="Calendar Member", role="member")
    proposed = client.post(
        "/api/ip/working-calendars", headers=company["headers"], json=_calendar_payload()
    )
    assert proposed.status_code == 201, proposed.text
    calendar_id = proposed.json()["id"]
    assert proposed.json()["can_withdraw"] is True
    approver_view = _workspace(client, company, approver["headers"])
    assert _record(approver_view, "calendars", calendar_id)["can_withdraw"] is False

    url = f"/api/ip/working-calendars/{calendar_id}/withdraw"
    reason = {"reason": "Proposed against the wrong holiday list."}
    assert client.post(url, headers=approver["headers"], json=reason).status_code == 403
    assert client.post(url, headers=member["headers"], json=reason).status_code == 403
    assert client.post(url, headers=company["headers"], json={"reason": "no"}).status_code == 422

    other = _company(client, "gov-proj-withdraw-other")
    assert client.post(url, headers=other["headers"], json=reason).status_code == 404
    unentitled = _company(client, "gov-proj-withdraw-plain", entitled=False)
    refused = client.post(url, headers=unentitled["headers"], json=reason)
    assert refused.status_code == 403, refused.text

    withdrawn = client.post(url, headers=company["headers"], json=reason)
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["status"] == "retired"
    assert withdrawn.json()["can_withdraw"] is False
    assert withdrawn.json()["can_activate"] is False
    assert client.post(url, headers=company["headers"], json=reason).status_code == 409
    late = client.post(
        f"/api/ip/working-calendars/{calendar_id}/activate",
        headers=approver["headers"],
        json={"reason": "Activating a withdrawn calendar version."},
    )
    assert late.status_code == 409, late.text
    with get_session_factory()() as session:
        events = session.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "ip.working_calendar.withdrawn",
                AuditEvent.target_id == calendar_id,
            )
        ).all()
        assert len(events) == 1
        assert events[0].company_id == company["company_id"]
        assert json.loads(events[0].metadata_json or "{}")["reason"] == reason["reason"]
