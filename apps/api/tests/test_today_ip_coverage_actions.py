"""Today must show the IP coverage waiting on this user.

Today is the page a fee-earner opens in the morning, and it aggregates
hearings, deadlines, tasks, draft reviews and overdue invoices. It did not
aggregate the two IP coverage queues, so:

* a transfer a colleague had offered could sit unseen while it blocked their
  handover — the colleague keeps the deadline until it is answered; and
* a deadline the user held but had not acknowledged could escalate without ever
  appearing on the page that answers "what must I do today".

Both were reachable only by opening the IP workspace and knowing to look.

Stable manifest test IDs:

* ``IPLF-TODAY-IP-01``  an offered transfer reaches Today
* ``IPLF-TODAY-IP-02``  an unacknowledged deadline reaches Today
* ``IPLF-TODAY-IP-03``  the two never describe the same row twice
* ``IPLF-TODAY-IP-04``  a docket the caller cannot open contributes nothing
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars

DUE = date.today() + timedelta(days=5)


@pytest.fixture(autouse=True)
def _enable_rule_governance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_IP_RULE_GOVERNANCE_ENABLED", "true")
    get_settings.cache_clear()


def _setup(client: TestClient, *, restricted: bool = False):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    other_id, other_token = _member(
        client, owner_token, name="Today Colleague", email="today-colleague@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-TODAY-01")

    docket = client.post(
        "/api/ip/dockets",
        headers=owner_headers,
        json={
            "title": "TODAYMARK",
            "matter_id": matter["id"],
            "restricted": restricted,
            "particulars": _particulars("TODAYMARK"),
        },
    )
    assert docket.status_code == 201, docket.text
    deadline = client.post(
        f"/api/matters/{matter['id']}/deadlines",
        headers=owner_headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Renewal fee",
            "due_on": str(DUE),
            "assignee_membership_id": owner_id,
        },
    )
    assert deadline.status_code == 200, deadline.text
    coverage = client.post(
        f"/api/ip/dockets/{docket.json()['id']}/deadline-coverages",
        headers=owner_headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": owner_id,
            "coverage_status": "pending",
        },
    )
    assert coverage.status_code == 200, coverage.text
    return {
        "owner_headers": owner_headers,
        "owner_id": owner_id,
        "other_headers": auth_headers(other_token),
        "other_id": other_id,
        "docket_id": docket.json()["id"],
        "coverage_id": coverage.json()["deadline_coverages"][0]["id"],
    }


def _today(client: TestClient, headers) -> dict:
    response = client.get("/api/me/today", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_today_ip_02_an_unacknowledged_deadline_reaches_today(client: TestClient) -> None:
    """IPLF-TODAY-IP-02 — acknowledging is what stops a critical item escalating."""

    seeded = _setup(client)

    body = _today(client, seeded["owner_headers"])
    actions = body["ip_coverage_actions"]

    assert [a["kind"] for a in actions] == ["acknowledge"]
    action = actions[0]
    assert action["coverage_id"] == seeded["coverage_id"]
    assert action["docket_title"] == "TODAYMARK"
    assert action["deadline_title"] == "Renewal fee"
    assert action["due_on"] == str(DUE)
    assert action["days_until"] == 5
    assert action["responsible_label"] == "You"
    # The stream participates in the same bounding contract as the other five.
    assert body["stream_limits"]["ip_coverage_actions"] >= 1
    assert body["stream_counts"]["ip_coverage_actions"] == 1
    assert body["stream_truncated"]["ip_coverage_actions"] is False


def test_today_ip_01_an_offered_transfer_reaches_today(client: TestClient) -> None:
    """IPLF-TODAY-IP-01 — an unanswered offer blocks the colleague who made it."""

    seeded = _setup(client)
    offered = client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Covering while I am in hearings.",
        },
    )
    assert offered.status_code == 200, offered.text

    # The colleague who was offered the work sees the decision on Today.
    actions = _today(client, seeded["other_headers"])["ip_coverage_actions"]
    assert [a["kind"] for a in actions] == ["decide_transfer"]
    assert actions[0]["coverage_id"] == seeded["coverage_id"]
    assert actions[0]["reason"] == "Covering while I am in hearings."
    # It names who is still accountable until they answer.
    assert actions[0]["responsible_label"] != "You"


def test_today_ip_03_a_row_awaiting_a_decision_is_not_also_an_acknowledgement(
    client: TestClient,
) -> None:
    """IPLF-TODAY-IP-03 — one row must not ask for two different acts.

    While a transfer is outstanding the current holder still owns the deadline
    and it is still unacknowledged, so a naive union would list it twice: once
    as "decide" for the replacement and once as "acknowledge" for the holder.
    Deciding is the act; acknowledging around it would bury the decision.
    """

    seeded = _setup(client)
    client.post(
        f"/api/ip/dockets/{seeded['docket_id']}/deadline-coverages/"
        f"{seeded['coverage_id']}/reassign",
        headers=seeded["owner_headers"],
        json={
            "expected_responsible_membership_id": seeded["owner_id"],
            "responsible_membership_id": seeded["other_id"],
            "reason": "Please take this while I travel.",
        },
    )

    # The holder is not asked to acknowledge a deadline that is being handed over.
    owner_actions = _today(client, seeded["owner_headers"])["ip_coverage_actions"]
    assert owner_actions == []

    # And the replacement is asked exactly once, for the decision.
    other_actions = _today(client, seeded["other_headers"])["ip_coverage_actions"]
    assert len(other_actions) == 1
    assert other_actions[0]["kind"] == "decide_transfer"


def test_today_ip_04_a_restricted_docket_contributes_nothing(client: TestClient) -> None:
    """IPLF-TODAY-IP-04 — Today never widens what a caller may see.

    The module's isolation promise is that nothing surfaces here that the caller
    could not also reach directly. This stream is docket-scoped, so the promise
    rests on can_access_ip_docket rather than visible_matters_filter.
    """

    seeded = _setup(client, restricted=True)

    # The colleague has no grant on a restricted docket.
    assert _today(client, seeded["other_headers"])["ip_coverage_actions"] == []
    # The owner, who can open it, still sees their own work.
    assert len(_today(client, seeded["owner_headers"])["ip_coverage_actions"]) == 1


def test_today_ip_02_an_acknowledged_deadline_stops_asking(client: TestClient) -> None:
    """The list is meant to reach empty; acknowledging must clear it."""

    seeded = _setup(client)
    acknowledged = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=seeded["owner_headers"],
        json={"coverage_ids": [seeded["coverage_id"]]},
    )
    assert acknowledged.status_code == 200, acknowledged.text
    assert acknowledged.json()["acknowledged_count"] == 1

    assert _today(client, seeded["owner_headers"])["ip_coverage_actions"] == []
