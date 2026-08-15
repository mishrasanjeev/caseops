"""IPLF-039C increment 7 — saved queues and bulk acknowledgement (CAL-OPS-09).

CAL-OPS-09 requires the daily docket to support *saved team queues*,
*workload/capacity indicators*, *bulk acknowledgement/assignment with per-record
validation*, and a *print/export manifest*. Increments 1 and 2 delivered the
indicators and the manifest. This closes the other two.

Bulk **assignment** is not a separate mechanism: it is the transfer path
reconciled in increment 5, which fails closed for the whole batch because
handing a restricted record to the wrong person is a security boundary.
Acknowledgement is not a boundary — a caller can only acknowledge their own
work — so it validates per record and applies partially, reporting every id.

Stable manifest test IDs:

* ``IPLF-CAL-OPS-09-QUEUE-01``  a saved queue is reusable and scoped
* ``IPLF-CAL-OPS-09-QUEUE-02``  a team queue needs team membership
* ``IPLF-CAL-OPS-09-QUEUE-03``  another member's personal queue is not visible
* ``IPLF-CAL-OPS-09-ACK-01``    bulk acknowledgement reports every record
* ``IPLF-CAL-OPS-09-ACK-02``    acknowledgement stops the critical escalation
* ``IPLF-CAL-OPS-09-ACK-03``    a pending transfer is not acknowledged around

Bulk acknowledgement writes ``accepted_at``, which increment 5 restricted to the
transfer-decision path. The invariant was widened there rather than duplicated
here: see ``test_ip_coverage_transfer_reconciliation.py::
test_uj57_recon05_only_the_decision_path_may_record_an_acceptance``.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    other_id, other_token = _member(
        client, owner_token, name="Queue Colleague", email="queue-colleague@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-QUEUE-09")
    return owner_headers, owner_id, other_id, auth_headers(other_token), matter


def _coverage(client, headers, *, matter_id, title, responsible, critical=False):
    docket = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={"title": title, "matter_id": matter_id, "particulars": _particulars(title.upper())},
    )
    assert docket.status_code == 201, docket.text
    docket_id = docket.json()["id"]
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Queue deadline",
            "due_on": str(date.today() + timedelta(days=30)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    created = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages",
        headers=headers,
        json={
            "matter_deadline_id": deadline.json()["id"],
            "responsible_membership_id": responsible,
            # Seeded unacknowledged: the point of the feature is taking it on.
            "coverage_status": "pending",
        },
    )
    assert created.status_code == 200, created.text
    return docket_id, created.json()["deadline_coverages"][0]


def test_calops09_queue01_a_saved_queue_is_reusable(client: TestClient) -> None:
    """IPLF-CAL-OPS-09-QUEUE-01 — the filters survive so the view is repeatable."""

    owner_headers, _owner_id, _other_id, _oh, _matter = _setup(client)

    saved = client.post(
        "/api/ip/docket-queues",
        headers=owner_headers,
        json={
            "name": "Critical this week",
            "description": "Opposition deadlines I own.",
            "filters": {"critical_only": True, "window_days": 7},
        },
    )
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["scope"] == "personal"
    assert body["filters"] == {"critical_only": True, "window_days": 7}

    listed = client.get("/api/ip/docket-queues", headers=owner_headers)
    assert listed.status_code == 200, listed.text
    assert [row["name"] for row in listed.json()["queues"]] == ["Critical this week"]

    # A second queue cannot silently shadow the first by reusing its name.
    clash = client.post(
        "/api/ip/docket-queues",
        headers=owner_headers,
        json={"name": "Critical this week", "filters": {}},
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "ip_docket_queue_name_taken"

    removed = client.delete(
        f"/api/ip/docket-queues/{body['id']}", headers=owner_headers
    )
    assert removed.status_code == 204, removed.text
    assert client.get("/api/ip/docket-queues", headers=owner_headers).json()["queues"] == []


def test_calops09_queue02_a_team_queue_requires_team_membership(client: TestClient) -> None:
    """IPLF-CAL-OPS-09-QUEUE-02 — sharing a team's workload view is a disclosure."""

    owner_headers, owner_id, other_id, other_headers, _matter = _setup(client)
    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Trademark Bench", "slug": "tm-bench", "kind": "team"},
    )
    assert team.status_code in {200, 201}, team.text
    team_id = team.json()["id"]

    # Creating a team does not by itself make you a member of it.
    refused = client.post(
        "/api/ip/docket-queues",
        headers=other_headers,
        json={"name": "Bench queue", "filters": {}, "team_id": team_id},
    )
    assert refused.status_code == 403, refused.text

    missing = client.post(
        "/api/ip/docket-queues",
        headers=owner_headers,
        json={"name": "Ghost queue", "filters": {}, "team_id": "does-not-exist"},
    )
    assert missing.status_code == 404, missing.text

    joined = client.post(
        f"/api/teams/{team_id}/members",
        headers=owner_headers,
        json={"membership_id": owner_id, "is_lead": True},
    )
    assert joined.status_code in {200, 201}, joined.text
    saved = client.post(
        "/api/ip/docket-queues",
        headers=owner_headers,
        json={"name": "Bench queue", "filters": {"critical_only": True}, "team_id": team_id},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["scope"] == "team"

    # A shared queue reaches the team, and only once the member is in it.
    assert client.get("/api/ip/docket-queues", headers=other_headers).json()["queues"] == []
    client.post(
        f"/api/teams/{team_id}/members",
        headers=owner_headers,
        json={"membership_id": other_id, "is_lead": False},
    )
    shared = client.get("/api/ip/docket-queues", headers=other_headers).json()["queues"]
    assert [row["name"] for row in shared] == ["Bench queue"]


def test_calops09_queue03_another_members_personal_queue_is_not_visible(
    client: TestClient,
) -> None:
    """IPLF-CAL-OPS-09-QUEUE-03 — personal means personal."""

    owner_headers, _owner_id, _other_id, other_headers, _matter = _setup(client)
    saved = client.post(
        "/api/ip/docket-queues",
        headers=owner_headers,
        json={"name": "My private triage", "filters": {"critical_only": True}},
    )
    assert saved.status_code == 201, saved.text

    assert client.get("/api/ip/docket-queues", headers=other_headers).json()["queues"] == []
    # Deleting it is refused as absent, which does not confirm that it exists.
    blocked = client.delete(
        f"/api/ip/docket-queues/{saved.json()['id']}", headers=other_headers
    )
    assert blocked.status_code == 404, blocked.text
    assert "My private triage" not in blocked.text


def test_calops09_ack01_bulk_acknowledgement_reports_every_record(
    client: TestClient,
) -> None:
    """IPLF-CAL-OPS-09-ACK-01 — per-record validation, nothing silently dropped."""

    owner_headers, owner_id, other_id, _oh, matter = _setup(client)
    _d1, mine_a = _coverage(
        client, owner_headers, matter_id=matter["id"], title="Ack One Mark", responsible=owner_id
    )
    _d2, mine_b = _coverage(
        client, owner_headers, matter_id=matter["id"], title="Ack Two Mark", responsible=owner_id
    )
    _d3, theirs = _coverage(
        client, owner_headers, matter_id=matter["id"], title="Ack Other Mark", responsible=other_id
    )

    result = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=owner_headers,
        json={
            "coverage_ids": [mine_a["id"], mine_b["id"], theirs["id"], "no-such-coverage"],
            "expected_versions": {mine_b["id"]: 999},
        },
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["acknowledged_count"] == 1
    assert body["rejected_count"] == 3

    outcomes = {row["coverage_id"]: row for row in body["outcomes"]}
    # Every requested id is answered for.
    assert set(outcomes) == {mine_a["id"], mine_b["id"], theirs["id"], "no-such-coverage"}
    assert outcomes[mine_a["id"]]["acknowledged"] is True
    assert outcomes[mine_b["id"]]["reason"] == "version_conflict"
    assert outcomes[theirs["id"]]["reason"] == "not_responsible"
    assert outcomes["no-such-coverage"]["reason"] == "not_found"

    # Partial application is real: the valid row was acknowledged, and the
    # rejected ones were left exactly as they were.
    repeat = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=owner_headers,
        json={"coverage_ids": [mine_a["id"]]},
    )
    assert repeat.json()["outcomes"][0]["reason"] == "already_acknowledged"


def test_calops09_ack02_acknowledgement_clears_the_daily_docket_escalation(
    client: TestClient,
) -> None:
    """IPLF-CAL-OPS-09-ACK-02 — the count it feeds is the count that changes.

    Acknowledgement is what stops an unacknowledged item escalating, so the
    proof is the daily docket moving, not just a column being written.
    """

    owner_headers, owner_id, _other_id, _oh, matter = _setup(client)
    _docket_id, coverage = _coverage(
        client, owner_headers, matter_id=matter["id"], title="Ack Docket Mark", responsible=owner_id
    )

    before = client.get("/api/ip/daily-docket", headers=owner_headers)
    assert before.status_code == 200, before.text
    queue_before = next(
        row for row in before.json()["queues"] if row["membership_id"] == owner_id
    )
    assert queue_before["unacknowledged_count"] == 1

    client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=owner_headers,
        json={"coverage_ids": [coverage["id"]]},
    )

    after = client.get("/api/ip/daily-docket", headers=owner_headers)
    queue_after = next(row for row in after.json()["queues"] if row["membership_id"] == owner_id)
    assert queue_after["unacknowledged_count"] == 0
    assert queue_after["assigned_count"] == queue_before["assigned_count"]


def test_calops09_ack03_a_pending_transfer_is_not_acknowledged_around(
    client: TestClient,
) -> None:
    """IPLF-CAL-OPS-09-ACK-03 — a decision must not be buried by a bulk action."""

    owner_headers, owner_id, other_id, _oh, matter = _setup(client)
    docket_id, coverage = _coverage(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Ack Pending Mark",
        responsible=owner_id,
    )
    offered = client.post(
        f"/api/ip/dockets/{docket_id}/deadline-coverages/{coverage['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": owner_id,
            "responsible_membership_id": other_id,
            "reason": "Offered while unacknowledged.",
        },
    )
    assert offered.status_code == 200, offered.text

    result = client.post(
        "/api/ip/deadline-coverages/bulk-acknowledge",
        headers=owner_headers,
        json={"coverage_ids": [coverage["id"]]},
    )
    assert result.status_code == 200, result.text
    assert result.json()["outcomes"][0]["reason"] == "transfer_pending"
    assert result.json()["acknowledged_count"] == 0
