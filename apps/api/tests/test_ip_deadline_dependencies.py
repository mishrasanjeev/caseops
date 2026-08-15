"""IPLF-034A deadline dependency graph (CAL-OPS-06).

Stable manifest test ID: ``IPLF-REQ-CAL-OPS-06``.

The graph is a pure read over stored calculation evidence. It must explain the
date that was actually produced, survive later rule changes unchanged, and
report a missing input as unavailable rather than omitting it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _member,
    _responsibilities,
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


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Dep Legal Approver", email="dep-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Dep Reviewer", email="dep-reviewer@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-DEP-034A")
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
    rule = client.post(
        "/api/ip/deadline-rules", headers=owner_headers, json=_rule_payload()
    ).json()
    assert (
        client.post(
            f"/api/ip/deadline-rules/{rule['id']}/activate",
            headers=legal_headers,
            json={"reviewer_membership_id": reviewer_id},
        ).status_code
        == 200
    )
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
    return owner_headers, legal_headers, legal_id, reviewer_id, docket, rule, calendar, deadline


def _dependencies(client, headers, deadline_id: str):
    return client.get(f"/api/ip/deadlines/{deadline_id}/dependencies", headers=headers)


def test_cal_ops_06_graph_names_every_input_that_produced_the_date(
    client: TestClient,
) -> None:
    """IPLF-REQ-CAL-OPS-06 — event, rule, calendar and trace are all explained."""

    owner_headers, _legal, _lid, _rid, docket, rule, calendar, deadline = _setup(client)

    response = _dependencies(client, owner_headers, deadline["id"])
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["deadline_id"] == deadline["id"]
    assert body["docket_id"] == docket["id"]
    assert body["result_on"] == deadline["result_on"]
    assert body["is_critical"] is True
    assert body["unavailable_inputs"] == []

    by_kind = {node["kind"]: node for node in body["nodes"]}
    # The rule and calendar that actually produced the date are named by id.
    assert by_kind["rule_version"]["reference_id"] == rule["id"]
    assert by_kind["rule_version"]["available"] is True
    assert by_kind["calendar_version"]["reference_id"] == calendar["id"]
    assert by_kind["calendar_version"]["available"] is True
    # No registry event drove this one, so the manual base date is the trigger.
    assert by_kind["trigger_event"]["reference_id"] is None
    assert "2026-08-14" in by_kind["trigger_event"]["detail"]

    # The stored trace and engine/source provenance travel with the graph.
    assert body["calculation_trace"]
    assert body["engine_version"] == deadline["engine_version"]
    assert body["source_version"] == deadline["source_version"]
    assert body["rule_citation"] == deadline["rule_citation"]
    assert body["explanation"] == deadline["explanation"]
    assert body["superseded_chain"] == []


def test_cal_ops_06_graph_is_stable_after_the_rule_changes(client: TestClient) -> None:
    """The explanation describes the calculation, not today's rule state."""

    owner_headers, legal_headers, legal_id, reviewer_id, _d, rule, _c, deadline = _setup(
        client
    )
    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    before = _dependencies(client, owner_headers, deadline["id"]).json()

    # Disable the governing rule after the fact.
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

    after = _dependencies(client, owner_headers, deadline["id"]).json()
    # The produced date, trace and citation are unchanged...
    assert after["result_on"] == before["result_on"]
    assert after["calculation_trace"] == before["calculation_trace"]
    assert after["rule_citation"] == before["rule_citation"]
    assert after["unavailable_inputs"] == []
    # ...but the rule node reports its current status honestly.
    rule_node = next(n for n in after["nodes"] if n["kind"] == "rule_version")
    assert "disabled" in rule_node["detail"]


def test_cal_ops_06_override_and_recalculation_chain_are_explained(
    client: TestClient,
) -> None:
    """An override is named, and a superseding recalculation records its parent."""

    owner_headers, legal_headers, legal_id, reviewer_id, _d, _r, _c, deadline = _setup(
        client
    )
    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    ).json()

    impact = client.get(
        f"/api/ip/deadlines/{deadline['id']}/impact", headers=legal_headers
    ).json()
    overridden = client.post(
        f"/api/ip/deadlines/{deadline['id']}/override",
        headers=legal_headers,
        json={
            "expected_version": confirmed["version"],
            "new_result_on": "2026-09-30",
            "reason": "Registry granted a written extension of time.",
            "evidence_reference": "evidence:extension-order-2026-09",
            "impact_token": impact["impact_token"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert overridden.status_code == 200, overridden.text

    # Override supersedes rather than mutating in place, so the current record
    # is a new deadline that links back to the original.
    successor = overridden.json()
    assert successor["id"] != deadline["id"]

    body = _dependencies(client, owner_headers, successor["id"]).json()
    assert body["result_on"] == "2026-09-30"

    override_node = next((n for n in body["nodes"] if n["kind"] == "override"), None)
    assert override_node is not None
    assert override_node["detail"] == "Registry granted a written extension of time."

    # The predecessor chain names the superseded calculation and its old date.
    assert body["superseded_chain"] == [deadline["id"]]
    predecessor = next(n for n in body["nodes"] if n["kind"] == "predecessor_deadline")
    assert predecessor["reference_id"] == deadline["id"]
    assert predecessor["available"] is True
    assert deadline["result_on"] in predecessor["detail"]

    # The original calculation is still readable and keeps its own date.
    original = _dependencies(client, owner_headers, deadline["id"]).json()
    assert original["result_on"] == deadline["result_on"]


def test_dependencies_are_access_scoped_and_tenant_isolated(
    client: TestClient,
) -> None:
    """Another tenant cannot read a deadline's provenance."""

    owner_headers, _legal, _lid, _rid, _d, _r, _c, deadline = _setup(client)
    assert _dependencies(client, owner_headers, deadline["id"]).status_code == 200

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Dep Firm",
            "company_slug": "other-dep-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-dep.example",
            "owner_password": "OtherDep123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))
    assert _dependencies(client, other_headers, deadline["id"]).status_code == 404
    assert _dependencies(client, owner_headers, "missing-deadline").status_code == 404
