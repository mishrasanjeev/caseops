"""UJ-57-EXC-01/02 — reassignment must not hand work to someone walled off.

Found by the 2026-08-15 inspection audit: `reassign_ip_deadline_coverage` and
`bulk_reassign_ip_deadline_coverages` checked only that the replacement
membership existed. Bulk reassignment sweeps coverage across every docket in
the company, so a restricted record or an ethical wall could be bypassed by
making the walled-off member responsible for its deadline.

Stable manifest test IDs:

* ``IPLF-UJ-57-EXC-01``  replacement lacks access
* ``IPLF-UJ-57-EXC-02``  ethical wall blocks bulk transfer
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import _member
from tests.test_ip_record_workflow import _particulars


def _docket(client, headers, *, matter_id, title, restricted=False):
    r = client.post(
        "/api/ip/dockets",
        headers=headers,
        json={
            "title": title,
            "matter_id": matter_id,
            "restricted": restricted,
            "particulars": _particulars(title.upper()),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _coverage(client, headers, docket_id, *, matter_id, responsible, backup=None):
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Coverage guard deadline",
            "due_on": str(date.today() + timedelta(days=45)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    body = {
        "matter_deadline_id": deadline.json()["id"],
        "responsible_membership_id": responsible,
        "coverage_status": "accepted",
    }
    if backup:
        body["backup_membership_id"] = backup
    r = client.post(f"/api/ip/dockets/{docket_id}/deadline-coverages", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    insider_id, insider_token = _member(
        client, owner_token, name="Coverage Insider", email="cov-insider@asterlegal.in"
    )
    outsider_id, _t2 = _member(
        client, owner_token, name="Coverage Outsider", email="cov-outsider@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-COV-UJ57")
    return owner_headers, owner_id, insider_id, outsider_id, matter, auth_headers(insider_token)


def test_uj57_exc01_single_reassignment_refuses_a_replacement_without_access(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-01 — a replacement who cannot open the record is refused."""

    owner_headers, owner_id, insider_id, outsider_id, matter, _insider_headers = _setup(
        client
    )
    restricted = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Restricted Coverage Mark",
        restricted=True,
    )
    docket = _coverage(
        client, owner_headers, restricted["id"], matter_id=matter["id"], responsible=owner_id
    )
    coverage = docket["deadline_coverages"][0]

    blocked = client.post(
        f"/api/ip/dockets/{restricted['id']}/deadline-coverages/{coverage['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": owner_id,
            "responsible_membership_id": outsider_id,
            "reason": "Attempting to hand a restricted record to a walled-off member.",
        },
    )
    assert blocked.status_code == 409, blocked.text
    problem = blocked.json()
    assert problem["code"] == "ip_coverage_replacement_lacks_access"
    assert problem["blocked_docket_ids"] == [restricted["id"]]
    # The refusal names no record title or other content.
    assert "Restricted Coverage Mark" not in str(problem)

    # Nothing was mutated: the original owner still holds the coverage.
    after = client.get(f"/api/ip/dockets/{restricted['id']}", headers=owner_headers).json()
    unchanged = after["deadline_coverages"][0]
    assert unchanged["responsible_membership_id"] == owner_id
    assert unchanged["reassignment_version"] == coverage["reassignment_version"]
    assert unchanged["coverage_status"] == coverage["coverage_status"]


def test_uj57_exc01_backup_change_requires_handoff_before_access_assignment(
    client: TestClient,
) -> None:
    """A backup cannot be replaced before the dedicated handoff workflow exists."""

    owner_headers, owner_id, insider_id, outsider_id, matter, _insider_headers = _setup(
        client
    )
    restricted = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Backup Guard Mark",
        restricted=True,
    )
    docket = _coverage(
        client, owner_headers, restricted["id"], matter_id=matter["id"], responsible=owner_id
    )
    coverage = docket["deadline_coverages"][0]

    blocked = client.post(
        f"/api/ip/dockets/{restricted['id']}/deadline-coverages/{coverage['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": owner_id,
            "responsible_membership_id": owner_id,
            "backup_membership_id": outsider_id,
            "reason": "Attempting to name a walled-off member as backup.",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ip_coverage_backup_handoff_required"


def test_uj57_exc02_ethical_wall_blocks_bulk_transfer_in_full(
    client: TestClient,
) -> None:
    """IPLF-UJ-57-EXC-02 — a walled record refuses the whole batch, not part."""

    owner_headers, owner_id, insider_id, outsider_id, matter, _insider_headers = _setup(
        client
    )
    open_docket = _docket(client, owner_headers, matter_id=matter["id"], title="Open Coverage Mark")
    restricted = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Walled Coverage Mark",
        restricted=True,
    )
    open_state = _coverage(
        client, owner_headers, open_docket["id"], matter_id=matter["id"], responsible=owner_id
    )
    walled_state = _coverage(
        client, owner_headers, restricted["id"], matter_id=matter["id"], responsible=owner_id
    )
    open_before = open_state["deadline_coverages"][0]
    walled_before = walled_state["deadline_coverages"][0]

    blocked = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=owner_headers,
        json={
            "from_membership_id": owner_id,
            "to_membership_id": outsider_id,
            "reason": "Leave cover for the whole portfolio.",
        },
    )
    assert blocked.status_code == 409, blocked.text
    problem = blocked.json()
    assert problem["code"] == "ip_coverage_replacement_lacks_access"
    assert problem["blocked_docket_ids"] == [restricted["id"]]

    # Fail closed for the batch: the accessible docket was not partially moved.
    open_after = client.get(f"/api/ip/dockets/{open_docket['id']}", headers=owner_headers).json()[
        "deadline_coverages"
    ][0]
    walled_after = client.get(f"/api/ip/dockets/{restricted['id']}", headers=owner_headers).json()[
        "deadline_coverages"
    ][0]
    assert open_after["responsible_membership_id"] == owner_id
    assert open_after["reassignment_version"] == open_before["reassignment_version"]
    assert walled_after["responsible_membership_id"] == owner_id
    assert walled_after["reassignment_version"] == walled_before["reassignment_version"]


def test_uj57_bulk_transfer_succeeds_when_the_replacement_has_access(
    client: TestClient,
) -> None:
    """The guard must not block legitimate leave cover."""

    owner_headers, owner_id, insider_id, _outsider_id, matter, insider_headers = _setup(
        client
    )
    first = _docket(client, owner_headers, matter_id=matter["id"], title="Cover One Mark")
    second = _docket(client, owner_headers, matter_id=matter["id"], title="Cover Two Mark")
    _coverage(client, owner_headers, first["id"], matter_id=matter["id"], responsible=owner_id)
    _coverage(client, owner_headers, second["id"], matter_id=matter["id"], responsible=owner_id)

    moved = client.post(
        "/api/ip/deadline-coverages/bulk-reassign",
        headers=owner_headers,
        json={
            "from_membership_id": owner_id,
            "to_membership_id": insider_id,
            "reason": "Planned leave cover across unrestricted records.",
        },
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["responsible_count"] == 2
    # 2026-08-15 reconciliation: a routine bulk transfer is now a proposal, so
    # the guard is proven by the transfer being *offered*, not by responsibility
    # silently landing on someone who never agreed to it. This assertion
    # previously expected the immediate move.
    assert body["transfer_mode"] == "proposed"
    assert body["pending_count"] == 2

    for docket in (first, second):
        row = client.get(f"/api/ip/dockets/{docket['id']}", headers=owner_headers).json()[
            "deadline_coverages"
        ][0]
        assert row["responsible_membership_id"] == owner_id
        assert row["coverage_status"] == "transfer_pending"

    # The move completes only when the named replacement accepts it.
    for docket in (first, second):
        coverage_id = client.get(f"/api/ip/dockets/{docket['id']}", headers=owner_headers).json()[
            "deadline_coverages"
        ][0]["id"]
        decided = client.post(
            f"/api/ip/deadline-coverages/{coverage_id}/replacement-decision",
            headers=insider_headers,
            json={"decision": "accepted", "reason": "Taking the leave cover."},
        )
        assert decided.status_code == 200, decided.text
        row = client.get(f"/api/ip/dockets/{docket['id']}", headers=owner_headers).json()[
            "deadline_coverages"
        ][0]
        assert row["responsible_membership_id"] == insider_id
        assert row["coverage_status"] == "accepted"
