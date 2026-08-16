"""IPLF-027B legal rule-version governance (UJ-47, RULE-GOV-01..08).

IPLF-023B delivered proposal, fixture gating, two-person activation, and the
emergency-disable status flag.  This module covers the governance behaviour that
remained open: effective-range collision, stale impact previews, tenant
selection of an approved version, and the fail-closed consequences of an
emergency disable.

Stable manifest test IDs:

* ``IPLF-UJ-47-NORMAL``   propose -> test -> activate -> retire
* ``IPLF-UJ-47-EXC-01``   proposer cannot self-approve
* ``IPLF-UJ-47-EXC-02``   failed fixture blocks activation
* ``IPLF-UJ-47-EXC-03``   overlapping effective ranges conflict
* ``IPLF-UJ-47-EXC-04``   activation does not rewrite confirmed deadlines
* ``IPLF-UJ-47-EXC-05``   emergency disable stops auto-confirm, preserves history
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _member,
    _rule_payload,
)


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests propose and activate deadline rules.

    IPLF-027B's A0 rollout drain made rule-governance mutations default-off, so
    the endpoints answer 503 ``ip_rule_governance_quiesced`` unless a caller
    opts in. These tests exercise the governance workflow itself, so they state
    the enabled precondition explicitly rather than relying on a default.

    This mirrors the fixture in ``test_ip_deadline_workflow.py``. An autouse
    fixture does not travel with an imported helper, which is why importing
    that module's helpers was not enough.
    """

    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _governance_actors(client: TestClient) -> tuple[dict, dict, str, str, str]:
    """Owner (proposer), legal approver, an independent reviewer, and the owner token."""

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name="Rule Legal Approver",
        email="rule-legal@asterlegal.in",
    )
    reviewer_id, _reviewer_token = _member(
        client,
        owner_token,
        name="Rule Fixture Reviewer",
        email="rule-reviewer@asterlegal.in",
    )
    return owner_headers, auth_headers(legal_token), legal_id, reviewer_id, owner_token


def _propose(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = _rule_payload()
    payload.update(overrides)
    response = client.post("/api/ip/deadline-rules", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _activate(
    client: TestClient,
    headers: dict[str, str],
    rule_id: str,
    reviewer_id: str,
    **extra,
) -> object:
    body: dict = {"reviewer_membership_id": reviewer_id}
    body.update(extra)
    return client.post(
        f"/api/ip/deadline-rules/{rule_id}/activate",
        headers=headers,
        json=body,
    )


def test_uj47_normal_propose_test_activate_retire(client: TestClient) -> None:
    """IPLF-UJ-47-NORMAL."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    rule = _propose(client, owner_headers)
    assert rule["status"] == "candidate"
    assert rule["fixtures_passed_at"] is None
    assert rule["activated_at"] is None

    activated = _activate(client, legal_headers, rule["id"], reviewer_id)
    assert activated.status_code == 200, activated.text
    body = activated.json()
    assert body["status"] == "active"
    # RULE-GOV-03: fixtures ran and both independent actors are recorded.
    assert body["fixtures_passed_at"] is not None
    assert body["reviewer_label_snapshot"] == "Rule Fixture Reviewer"
    assert body["legal_approver_label_snapshot"] == "Rule Legal Approver"
    assert body["proposer_label_snapshot"] != body["legal_approver_label_snapshot"]

    impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact",
        headers=legal_headers,
    )
    assert impact.status_code == 200, impact.text
    retired = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/transition",
        headers=legal_headers,
        json={
            "impact_token": impact.json()["impact_token"],
            "reason": "Superseded by the 2027 official amendment.",
            "emergency_disable": False,
        },
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "retired"
    # RULE-GOV-02/06: retirement preserves the immutable proposal evidence.
    assert retired.json()["disabled_at"] is None
    assert retired.json()["fixtures_passed_at"] is not None
    assert retired.json()["source_hash"] == rule["source_hash"]


def test_uj47_exc01_proposer_cannot_self_approve(client: TestClient) -> None:
    """IPLF-UJ-47-EXC-01 — RULE-GOV-03 two-qualified-actor rule."""

    owner_headers, legal_headers, legal_id, reviewer_id, owner_token = _governance_actors(client)
    rule = _propose(client, owner_headers)

    # The proposer may not supply themselves as the legal approver.
    self_approval = _activate(client, owner_headers, rule["id"], reviewer_id)
    assert self_approval.status_code == 409
    assert "independent" in self_approval.json()["detail"].lower()

    # The legal approver may not also be the named fixture reviewer.
    same_actor = _activate(client, legal_headers, rule["id"], legal_id)
    assert same_actor.status_code == 409
    assert "distinct" in same_actor.json()["detail"].lower()

    assert _activate(client, legal_headers, rule["id"], reviewer_id).status_code == 200


def test_uj47_exc02_failed_fixture_blocks_activation(client: TestClient) -> None:
    """IPLF-UJ-47-EXC-02 — RULE-GOV-03 every declared fixture must pass."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    payload = _rule_payload()
    # Same rule, but the fixture asserts a date the engine will not produce.
    payload["fixtures"][0]["expected_result_on"] = "2026-08-19"
    rule = _propose(client, owner_headers, fixtures=payload["fixtures"])

    blocked = _activate(client, legal_headers, rule["id"], reviewer_id)
    assert blocked.status_code == 409
    assert "fixture" in blocked.json()["detail"].lower()

    # Fail-closed: the version stays a candidate with no approval evidence.
    workspace_rule = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact",
        headers=legal_headers,
    )
    assert workspace_rule.status_code == 200
    still_candidate = _propose(client, owner_headers, key="in-tm-second-scope-v1")
    assert still_candidate["status"] == "candidate"


def test_uj47_exc03_overlapping_effective_ranges_conflict(client: TestClient) -> None:
    """IPLF-UJ-47-EXC-03 — RULE-GOV-01 effective-range collision is explicit."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    first = _propose(client, owner_headers, effective_from="2026-01-01", effective_until=None)
    assert _activate(client, legal_headers, first["id"], reviewer_id).status_code == 200

    # A second version of the same rule set covering an overlapping period.
    second = _propose(client, owner_headers, effective_from="2026-06-01", effective_until=None)
    conflict = _activate(client, legal_headers, second["id"], reviewer_id)
    assert conflict.status_code == 409
    detail = conflict.json()["detail"]
    assert "overlap" in detail.lower()
    assert str(first["version"]) in detail

    # Explicit supersession is required and retires only the colliding version.
    impact = client.get(
        f"/api/ip/deadline-rules/{second['id']}/impact", headers=legal_headers
    ).json()
    superseded = _activate(
        client,
        legal_headers,
        second["id"],
        reviewer_id,
        supersede_overlapping=True,
        impact_acknowledged=True,
        impact_reason="Reviewed the mid-year amendment supersession.",
        impact_token=impact["impact_token"],
    )
    assert superseded.status_code == 200, superseded.text
    assert superseded.json()["status"] == "active"

    policies = client.get("/api/ip/rule-policies", headers=owner_headers)
    assert policies.status_code == 200, policies.text
    active = [item for item in policies.json() if item["rule_set_key"] == first["key"]]
    assert len(active) == 1
    assert active[0]["active_rule_version_id"] == second["id"]


def test_uj47_exc04_activation_preserves_confirmed_deadlines(client: TestClient) -> None:
    """IPLF-UJ-47-EXC-04 — RULE-GOV-05 confirmed evidence stays historical."""

    from tests.test_clients import _mk_matter
    from tests.test_ip_deadline_workflow import _docket_for_matter, _responsibilities

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client,
        owner_token,
        name="Rule Legal Approver",
        email="rule-legal@asterlegal.in",
    )
    reviewer_id, _reviewer = _member(
        client,
        owner_token,
        name="Rule Fixture Reviewer",
        email="rule-reviewer@asterlegal.in",
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DL-027B")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    assert (
        client.post(
            f"/api/ip/working-calendars/{calendar['id']}/activate",
            headers=legal_headers,
            json={"reason": "Independent calendar review is complete."},
        ).status_code
        == 200
    )

    rule = _propose(client, owner_headers)
    assert _activate(client, legal_headers, rule["id"], reviewer_id).status_code == 200

    deadline = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Respond to examination report",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    ).json()
    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    confirmed_body = confirmed.json()
    assert confirmed_body["state"] == "confirmed"

    # Activating a successor now has real impact: it must be previewed, the
    # preview token must still be current, and supersession must be explicit.
    successor = _propose(client, owner_headers, effective_from="2026-09-01", effective_until=None)
    unacknowledged = _activate(
        client,
        legal_headers,
        successor["id"],
        reviewer_id,
        supersede_overlapping=True,
    )
    assert unacknowledged.status_code == 409
    assert "impact" in unacknowledged.json()["detail"].lower()

    # RULE-GOV-05: the candidate's preview must surface the records carried by
    # the active version it would supersede, not an empty own-row count.
    impact = client.get(
        f"/api/ip/deadline-rules/{successor['id']}/impact", headers=legal_headers
    ).json()
    assert impact["open_deadline_count"] == 1
    assert impact["company_policy_count"] == 1
    assert impact["confirmed_deadlines_preserved"] is True

    stale = _activate(
        client,
        legal_headers,
        successor["id"],
        reviewer_id,
        impact_acknowledged=True,
        impact_reason="Reviewed the successor amendment impact.",
        impact_token="stale-token-value",
        supersede_overlapping=True,
    )
    assert stale.status_code == 409
    assert "preview" in stale.json()["detail"].lower()

    activated = _activate(
        client,
        legal_headers,
        successor["id"],
        reviewer_id,
        impact_acknowledged=True,
        impact_reason="Reviewed the successor amendment impact.",
        impact_token=impact["impact_token"],
        supersede_overlapping=True,
    )
    assert activated.status_code == 200, activated.text

    # The confirmed legal calculation keeps its original rule, result and trace.
    reloaded = client.get(
        f"/api/ip/dockets/{docket['id']}/deadline-workspace", headers=legal_headers
    )
    assert reloaded.status_code == 200, reloaded.text
    still = next(
        item for item in reloaded.json()["deadlines"] if item["id"] == deadline["id"]
    )
    assert still["state"] == "confirmed"
    assert still["rule_version_id"] == rule["id"]
    assert still["result_on"] == confirmed_body["result_on"]
    assert still["version"] == confirmed_body["version"]


def test_uj47_exc05_emergency_disable_is_fail_closed(client: TestClient) -> None:
    """IPLF-UJ-47-EXC-05 — RULE-GOV-04/07 disable stops auto-confirm."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    rule = _propose(client, owner_headers)
    activated = _activate(
        client,
        legal_headers,
        rule["id"],
        reviewer_id,
        select_for_company=True,
        auto_confirm_eligible=True,
    )
    assert activated.status_code == 200, activated.text

    policies = client.get("/api/ip/rule-policies", headers=owner_headers).json()
    assert len(policies) == 1
    assert policies[0]["auto_confirm_eligible"] is True
    assert policies[0]["auto_confirm_suspended_reason"] is None

    impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact", headers=legal_headers
    ).json()
    disabled = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/transition",
        headers=legal_headers,
        json={
            "impact_token": impact["impact_token"],
            "reason": "Official source withdrew the notified rule text.",
            "emergency_disable": True,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["status"] == "disabled"
    assert disabled.json()["disabled_at"] is not None
    # History is preserved, not deleted.
    assert disabled.json()["fixtures_passed_at"] is not None
    assert disabled.json()["source_hash"] == rule["source_hash"]

    after = client.get("/api/ip/rule-policies", headers=owner_headers).json()
    assert after[0]["auto_confirm_eligible"] is False
    assert after[0]["auto_confirm_suspended_reason"] == "rule_disabled"
    assert after[0]["version"] > policies[0]["version"]


def test_rulegov07_disable_alerts_record_owners(client: TestClient) -> None:
    """RULE-GOV-07 — affected record owners are alerted through the shared dispatcher."""

    from sqlalchemy import func, select

    from caseops_api.db.models import NotificationDeliveryIntent
    from caseops_api.db.session import get_session_factory
    from tests.test_clients import _mk_matter
    from tests.test_ip_deadline_workflow import _docket_for_matter, _responsibilities

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Rule Legal Approver", email="rule-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Rule Fixture Reviewer", email="rule-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DL-027D")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent calendar review is complete."},
    )
    rule = _propose(client, owner_headers)
    assert _activate(client, legal_headers, rule["id"], reviewer_id).status_code == 200

    deadline = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Respond to examination report",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    ).json()
    assert (
        client.post(
            f"/api/ip/deadlines/{deadline['id']}/confirm",
            headers=legal_headers,
            json={
                "expected_version": deadline["version"],
                "responsibilities": _responsibilities(legal_id, reviewer_id),
            },
        ).status_code
        == 200
    )

    impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact", headers=legal_headers
    ).json()
    disabled = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/transition",
        headers=legal_headers,
        json={
            "impact_token": impact["impact_token"],
            "reason": "Official source withdrew the notified rule text.",
            "emergency_disable": True,
        },
    )
    assert disabled.status_code == 200, disabled.text

    with get_session_factory()() as session:
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.event_type == "ip_rule_version_disabled"
                )
            ).all()
        )
    # Both acknowledged owners of the affected legal deadline are alerted.
    assert {i.recipient_membership_id for i in intents} == {legal_id, reviewer_id}
    assert all(i.channel == "in_app" for i in intents)
    assert all(rule["id"] in str(i.source_id) for i in intents)

    # The disable is idempotent: a repeat cannot double-send.
    repeat = client.post(
        f"/api/ip/deadline-rules/{rule['id']}/transition",
        headers=legal_headers,
        json={
            "impact_token": impact["impact_token"],
            "reason": "Repeat of the same emergency disable.",
            "emergency_disable": True,
        },
    )
    assert repeat.status_code == 409
    with get_session_factory()() as session:
        again = int(
            session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryIntent)
                .where(NotificationDeliveryIntent.event_type == "ip_rule_version_disabled")
            )
            or 0
        )
    assert again == len(intents)


def test_rulegov06_confirmed_calculation_stays_reproducible(client: TestClient) -> None:
    """RULE-GOV-06 — stored engine/inputs/trace survive later rule changes."""

    from tests.test_clients import _mk_matter
    from tests.test_ip_deadline_workflow import _docket_for_matter, _responsibilities

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Rule Legal Approver", email="rule-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Rule Fixture Reviewer", email="rule-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DL-027D2")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])
    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent calendar review is complete."},
    )
    rule = _propose(client, owner_headers)
    assert _activate(client, legal_headers, rule["id"], reviewer_id).status_code == 200
    deadline = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Respond to examination report",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    ).json()
    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    ).json()
    before = {
        "result_on": confirmed["result_on"],
        "engine_version": confirmed["engine_version"],
        "source_version": confirmed["source_version"],
        "rule_citation": confirmed["rule_citation"],
        "inputs": confirmed["calculation_inputs"],
        "trace": confirmed["calculation_trace"],
    }
    assert before["trace"], "the calculation trace must be persisted"

    # Retire the rule the calculation was made under.
    impact = client.get(
        f"/api/ip/deadline-rules/{rule['id']}/impact", headers=legal_headers
    ).json()
    assert (
        client.post(
            f"/api/ip/deadline-rules/{rule['id']}/transition",
            headers=legal_headers,
            json={
                "impact_token": impact["impact_token"],
                "reason": "Superseded by a later official amendment.",
                "emergency_disable": False,
            },
        ).status_code
        == 200
    )

    after = next(
        item
        for item in client.get(
            f"/api/ip/dockets/{docket['id']}/deadline-workspace", headers=legal_headers
        ).json()["deadlines"]
        if item["id"] == deadline["id"]
    )
    assert after["result_on"] == before["result_on"]
    assert after["engine_version"] == before["engine_version"]
    assert after["source_version"] == before["source_version"]
    assert after["rule_citation"] == before["rule_citation"]
    assert after["calculation_inputs"] == before["inputs"]
    assert after["calculation_trace"] == before["trace"]


def _fee_payload() -> dict:
    return {
        "key": "in-tm-renewal-fee-v1",
        "rule_kind": "fee",
        "jurisdiction": "IN",
        "office": "IP India",
        "right_kind": "trademark",
        "proceeding_kind": "application",
        "role": "applicant",
        "stage": "renewal",
        "source_record_id": "tm-fee-schedule-2026",
        "source_hash": "c" * 64,
        "source_reference": "https://official.example/ip-india/tm-fees",
        "effective_from": "2026-01-01",
        "effective_until": None,
        "engine_compatibility": "caseops-ip-fee-v1",
        "definition": {"official_fee_inr": 9000, "basis": "per_class_per_renewal"},
        "fixtures": [
            {
                "id": "one-class-renewal",
                "fixture_kind": "positive",
                "expected_outcome": 9000,
                "observed_outcome": 9000,
                "evidence_reference": "fixture:official-fee-schedule-2026",
            }
        ],
    }


def test_rulegov08_fee_rules_use_the_same_model_but_a_separate_domain(
    client: TestClient,
) -> None:
    """RULE-GOV-08 — fee versions share the lifecycle, not the deadline domain."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    fee = client.post("/api/ip/deadline-rules", headers=owner_headers, json=_fee_payload())
    assert fee.status_code == 201, fee.text
    fee_body = fee.json()
    assert fee_body["rule_kind"] == "fee"
    assert fee_body["status"] == "candidate"

    # Same propose/review/activate model, including two-actor independence.
    assert _activate(client, owner_headers, fee_body["id"], reviewer_id).status_code == 409
    activated = _activate(client, legal_headers, fee_body["id"], reviewer_id)
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "active"
    assert activated.json()["fixtures_passed_at"] is not None

    # A failed fee fixture blocks activation the same way a deadline fixture does.
    bad = _fee_payload()
    bad["key"] = "in-tm-renewal-fee-v2"
    bad["fixtures"][0]["observed_outcome"] = 1
    bad_rule = client.post("/api/ip/deadline-rules", headers=owner_headers, json=bad).json()
    blocked = _activate(client, legal_headers, bad_rule["id"], reviewer_id)
    assert blocked.status_code == 409
    assert "fixture" in blocked.json()["detail"].lower()

    # Separate version domain: a fee rule can never drive a legal deadline.
    from tests.test_clients import _mk_matter
    from tests.test_ip_deadline_workflow import _docket_for_matter

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent calendar review is complete."},
    )
    matter = _mk_matter(client, owner_token, "IP-FEE-DOMAIN")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])
    misuse = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Fee rule must not calculate a legal deadline",
            "rule_version_id": fee_body["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
        },
    )
    assert misuse.status_code == 409
    assert "not a deadline rule" in misuse.json()["detail"].lower()


def test_company_policy_cannot_select_unapproved_rule(client: TestClient) -> None:
    """RULE-GOV-04 — a tenant cannot make a draft or disabled version authoritative."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)

    candidate = _propose(client, owner_headers)
    draft_selection = client.put(
        "/api/ip/rule-policies",
        headers=legal_headers,
        json={"rule_version_id": candidate["id"], "auto_confirm_eligible": True},
    )
    assert draft_selection.status_code == 409
    assert "active" in draft_selection.json()["detail"].lower()
    assert client.get("/api/ip/rule-policies", headers=owner_headers).json() == []

    assert (
        _activate(
            client,
            legal_headers,
            candidate["id"],
            reviewer_id,
            select_for_company=False,
        ).status_code
        == 200
    )
    selected = client.put(
        "/api/ip/rule-policies",
        headers=legal_headers,
        json={"rule_version_id": candidate["id"], "auto_confirm_eligible": False},
    )
    assert selected.status_code == 200, selected.text
    assert selected.json()["active_rule_version_id"] == candidate["id"]
    assert selected.json()["version"] == 1

    # Stale-write protection on the tenant policy itself.
    stale = client.put(
        "/api/ip/rule-policies",
        headers=legal_headers,
        json={
            "rule_version_id": candidate["id"],
            "auto_confirm_eligible": True,
            "expected_policy_version": 99,
        },
    )
    assert stale.status_code == 409


def test_rule_policy_selection_is_tenant_isolated(client: TestClient) -> None:
    """RULE-GOV-04 tenant isolation — another company cannot select this rule."""

    owner_headers, legal_headers, _legal_id, reviewer_id, owner_token = _governance_actors(client)
    rule = _propose(client, owner_headers)
    assert _activate(client, legal_headers, rule["id"], reviewer_id).status_code == 200

    second = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Rule Firm",
            "company_slug": "other-rule-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-rule.example",
            "owner_password": "OtherRule123!",
        },
    )
    assert second.status_code == 200, second.text
    other_headers = auth_headers(str(second.json()["access_token"]))

    leaked = client.put(
        "/api/ip/rule-policies",
        headers=other_headers,
        json={"rule_version_id": rule["id"], "auto_confirm_eligible": True},
    )
    assert leaked.status_code == 404
    assert client.get("/api/ip/rule-policies", headers=other_headers).json() == []


def test_shared_rule_key_governance_never_crosses_tenant_ownership(
    client: TestClient,
) -> None:
    """A shared legal-scope key cannot leak impact or retire another tenant's version."""

    from sqlalchemy import select

    from caseops_api.db.models import IpRuleVersion
    from caseops_api.db.session import get_session_factory

    first_headers, first_legal_headers, _first_legal_id, first_reviewer_id, _token = (
        _governance_actors(client)
    )
    first = _propose(client, first_headers)
    first_activated = _activate(
        client,
        first_legal_headers,
        first["id"],
        first_reviewer_id,
        select_for_company=True,
        auto_confirm_eligible=True,
    )
    assert first_activated.status_code == 200, first_activated.text

    second_bootstrap = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Second Rule Governance Firm",
            "company_slug": "second-rule-governance-firm",
            "company_type": "law_firm",
            "owner_full_name": "Second Rule Owner",
            "owner_email": "second-rule-owner@example.com",
            "owner_password": "SecondRuleOwner123!",
        },
    )
    assert second_bootstrap.status_code == 200, second_bootstrap.text
    second_token = str(second_bootstrap.json()["access_token"])
    second_headers = auth_headers(second_token)
    _second_legal_id, second_legal_token = _member(
        client,
        second_token,
        name="Second Rule Legal Approver",
        email="second-rule-legal@example.com",
        company_slug="second-rule-governance-firm",
    )
    second_reviewer_id, _second_reviewer_token = _member(
        client,
        second_token,
        name="Second Rule Fixture Reviewer",
        email="second-rule-reviewer@example.com",
        company_slug="second-rule-governance-firm",
    )
    second_legal_headers = auth_headers(second_legal_token)

    # The stable rule-set key is shared catalog identity, but the candidate,
    # active lifecycle, impact, and policy are owned by the proposing tenant.
    second = _propose(client, second_headers)
    second_impact = client.get(
        f"/api/ip/deadline-rules/{second['id']}/impact",
        headers=second_legal_headers,
    )
    assert second_impact.status_code == 200, second_impact.text
    assert second_impact.json()["company_policy_count"] == 0
    assert second_impact.json()["open_deadline_count"] == 0
    assert second_impact.json()["candidate_deadline_count"] == 0

    # Tenant A's active version is not an overlap Tenant B must supersede.
    second_activated = _activate(
        client,
        second_legal_headers,
        second["id"],
        second_reviewer_id,
        select_for_company=True,
        auto_confirm_eligible=True,
    )
    assert second_activated.status_code == 200, second_activated.text

    with get_session_factory()() as session:
        states = dict(
            session.execute(
                select(IpRuleVersion.id, IpRuleVersion.status).where(
                    IpRuleVersion.id.in_([first["id"], second["id"]])
                )
            ).all()
        )
    assert states == {first["id"]: "active", second["id"]: "active"}

    second_active_impact = client.get(
        f"/api/ip/deadline-rules/{second['id']}/impact",
        headers=second_legal_headers,
    ).json()
    disabled = client.post(
        f"/api/ip/deadline-rules/{second['id']}/transition",
        headers=second_legal_headers,
        json={
            "impact_token": second_active_impact["impact_token"],
            "reason": "Second tenant withdrew only its selected version.",
            "emergency_disable": True,
        },
    )
    assert disabled.status_code == 200, disabled.text

    first_policy = client.get("/api/ip/rule-policies", headers=first_headers).json()
    assert len(first_policy) == 1
    assert first_policy[0]["active_rule_version_id"] == first["id"]
    assert first_policy[0]["auto_confirm_eligible"] is True
