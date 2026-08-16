"""IPLF-039C rebuild increment 2: the daily docket (UJ-50).

UJ-50's acceptance is that a manager can identify every critical item *without
combining side spreadsheets, provider portals, and hidden notification logs*.
That is what these tests hold the implementation to.

Stable manifest test IDs:

* ``IPLF-UJ-50-NORMAL``   triage daily docket and workload
* ``IPLF-UJ-50-EXC-02``   absent or disabled user triggers backup policy
* ``IPLF-UJ-50-EXC-03``   stale provider data is not shown as no work
* ``IPLF-UJ-50-EXC-04``   unacknowledged critical item re-escalates
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


def _coverage(
    client, headers, docket_id, *, matter_id, responsible, backup=None, status="accepted"
):
    deadline = client.post(
        f"/api/matters/{matter_id}/deadlines",
        headers=headers,
        json={
            "source": "custom",
            "kind": "licence_royalty",
            "title": "Daily docket deadline",
            "due_on": str(date.today() + timedelta(days=10)),
            "assignee_membership_id": responsible,
        },
    )
    assert deadline.status_code == 200, deadline.text
    body = {
        "matter_deadline_id": deadline.json()["id"],
        "responsible_membership_id": responsible,
        "coverage_status": status,
    }
    if backup:
        body["backup_membership_id"] = backup
    r = client.post(f"/api/ip/dockets/{docket_id}/deadline-coverages", headers=headers, json=body)
    assert r.status_code == 200, r.text
    return r.json()["deadline_coverages"]


def _docket_view(client, headers, **params):
    return client.get("/api/ip/daily-docket", headers=headers, params=params)


def _deactivate(client, owner_headers, membership_id):
    r = client.patch(
        f"/api/companies/current/users/{membership_id}",
        headers=owner_headers,
        json={"is_active": False},
    )
    assert r.status_code in {200, 204}, r.text


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    owner_id = str(bootstrap["membership"]["id"])
    primary_id, _t1 = _member(
        client, owner_token, name="Docket Primary", email="docket-primary@asterlegal.in"
    )
    backup_id, _t2 = _member(
        client, owner_token, name="Docket Backup", email="docket-backup@asterlegal.in"
    )
    matter = _mk_matter(client, owner_token, "IP-039C-UJ50")
    team = client.post(
        "/api/teams/",
        headers=owner_headers,
        json={"name": "Trademarks", "slug": "trademarks", "kind": "team"},
    )
    assert team.status_code == 201, team.text
    assigned = client.patch(
        f"/api/matters/{matter['id']}",
        headers=owner_headers,
        json={
            "team_id": team.json()["id"],
            "expected_updated_at": matter["updated_at"],
        },
    )
    assert assigned.status_code == 200, assigned.text
    matter = assigned.json()
    return owner_headers, owner_id, primary_id, backup_id, matter


def test_uj50_normal_triage_daily_docket_and_workload(client: TestClient) -> None:
    """IPLF-UJ-50-NORMAL — workload and capacity are visible per owner."""

    owner_headers, owner_id, primary_id, backup_id, matter = _setup(client)
    first = _docket(client, owner_headers, matter_id=matter["id"], title="Queue One Mark")
    second = _docket(client, owner_headers, matter_id=matter["id"], title="Queue Two Mark")
    _coverage(client, owner_headers, first["id"], matter_id=matter["id"], responsible=primary_id)
    _coverage(client, owner_headers, second["id"], matter_id=matter["id"], responsible=primary_id)
    third = _docket(client, owner_headers, matter_id=matter["id"], title="Queue Three Mark")
    _coverage(client, owner_headers, third["id"], matter_id=matter["id"], responsible=backup_id)

    response = _docket_view(client, owner_headers, team="trademarks")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["generated_at"]
    assert body["filters"] == {"team": "trademarks"}
    assert body["counts_are_complete"] is True
    assert body["stale_sources"] == []

    queues = {q["membership_id"]: q for q in body["queues"]}
    assert set(queues) == {primary_id, backup_id}
    assert queues[primary_id]["assigned_count"] == 2
    assert queues[backup_id]["assigned_count"] == 1
    assert queues[primary_id]["label"] == "Docket Primary"
    assert queues[primary_id]["active"] is True
    assert queues[primary_id]["capacity_state"] == "available"
    # Nothing is critical or unacknowledged in this fixture.
    assert queues[primary_id]["critical_count"] == 0
    assert queues[primary_id]["unacknowledged_count"] == 0
    assert body["escalations"] == []


@pytest.mark.parametrize("terminal_status", ["done", "cancelled"])
def test_daily_docket_excludes_coverage_for_terminal_operational_deadline(
    client: TestClient,
    terminal_status: str,
) -> None:
    """DONE/CANCELLED deadlines are history, never assignable daily work."""

    owner_headers, _owner_id, primary_id, _backup_id, matter = _setup(client)
    docket = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title=f"Terminal {terminal_status} deadline",
    )
    coverages = _coverage(
        client,
        owner_headers,
        docket["id"],
        matter_id=matter["id"],
        responsible=primary_id,
        status="pending",
    )
    coverage = coverages[-1]

    before = _docket_view(client, owner_headers).json()
    assert next(
        queue for queue in before["queues"] if queue["membership_id"] == primary_id
    )["assigned_count"] == 1

    transitioned = client.patch(
        f"/api/matters/{matter['id']}/deadlines/{coverage['matter_deadline_id']}",
        headers=owner_headers,
        json={"status": terminal_status},
    )
    assert transitioned.status_code == 200, transitioned.text

    after = _docket_view(client, owner_headers)
    assert after.status_code == 200, after.text
    body = after.json()
    assert body["queues"] == []
    assert body["escalations"] == []
    assert coverage["id"] not in after.text


def test_uj50_exc02_absent_or_disabled_owner_triggers_backup_policy(
    client: TestClient,
) -> None:
    """IPLF-UJ-50-EXC-02 — a deactivated owner escalates to the named backup."""

    owner_headers, owner_id, primary_id, backup_id, matter = _setup(client)
    with_backup = _docket(client, owner_headers, matter_id=matter["id"], title="Backup Policy Mark")
    covered = _coverage(
        client,
        owner_headers,
        with_backup["id"],
        matter_id=matter["id"],
        responsible=primary_id,
        backup=backup_id,
    )
    orphan_docket = _docket(client, owner_headers, matter_id=matter["id"], title="No Backup Mark")
    orphan = _coverage(
        client,
        owner_headers,
        orphan_docket["id"],
        matter_id=matter["id"],
        responsible=primary_id,
    )

    before = _docket_view(client, owner_headers).json()
    assert before["escalations"] == []

    _deactivate(client, owner_headers, primary_id)

    after = _docket_view(client, owner_headers).json()
    queues = {q["membership_id"]: q for q in after["queues"]}
    assert queues[primary_id]["active"] is False
    assert queues[primary_id]["capacity_state"] == "unavailable"

    by_coverage = {e["coverage_id"]: e for e in after["escalations"]}
    covered_id = covered[0]["id"]
    orphan_id = next(c["id"] for c in orphan if c["id"] != covered_id)

    # With a live backup the work escalates to them by name.
    assert by_coverage[covered_id]["reason"] == "owner_inactive"
    assert by_coverage[covered_id]["escalate_to_membership_id"] == backup_id
    # With no backup the item is explicitly unowned, not quietly dropped.
    assert by_coverage[orphan_id]["reason"] == "unowned"
    assert by_coverage[orphan_id]["escalate_to_membership_id"] is None


def test_uj50_exc03_stale_provider_data_is_not_shown_as_no_work(
    client: TestClient,
) -> None:
    """IPLF-UJ-50-EXC-03 — unknown work reports null counts, never zero."""

    owner_headers, owner_id, primary_id, backup_id, matter = _setup(client)
    docket = _docket(client, owner_headers, matter_id=matter["id"], title="Stale Docket Mark")
    _coverage(client, owner_headers, docket["id"], matter_id=matter["id"], responsible=primary_id)

    fresh = _docket_view(client, owner_headers).json()
    assert fresh["counts_are_complete"] is True
    assert fresh["queues"][0]["assigned_count"] == 1

    stale = _docket_view(client, owner_headers, stale_source="registry_status_feed").json()
    assert stale["counts_are_complete"] is False
    assert stale["stale_sources"] == ["registry_status_feed"]

    queue = next(q for q in stale["queues"] if q["membership_id"] == primary_id)
    # The critical distinction: unknown is null, not 0.
    assert queue["assigned_count"] is None
    assert queue["critical_count"] is None
    assert queue["unacknowledged_count"] is None
    assert queue["assigned_count"] != 0
    # The owner is still listed, so the work does not vanish from the view.
    assert queue["membership_id"] == primary_id
    assert queue["capacity_state"] == "available"


def test_uj50_exc04_unacknowledged_critical_item_re_escalates(
    client: TestClient,
) -> None:
    """IPLF-UJ-50-EXC-04 — an unacknowledged critical item does not sit quietly."""

    from tests.test_ip_deadline_workflow import (
        _calendar_payload,
        _docket_for_matter,
        _responsibilities,
        _rule_payload,
    )

    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Crit Legal", email="crit-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Crit Backup", email="crit-backup@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-039C-UJ50E4")
    docket = _docket_for_matter(client, owner_headers, matter_id=matter["id"])

    calendar = client.post(
        "/api/ip/working-calendars", headers=owner_headers, json=_calendar_payload()
    ).json()
    client.post(
        f"/api/ip/working-calendars/{calendar['id']}/activate",
        headers=legal_headers,
        json={"reason": "Independent calendar review is complete."},
    )
    rule = client.post("/api/ip/deadline-rules", headers=owner_headers, json=_rule_payload()).json()
    client.post(
        f"/api/ip/deadline-rules/{rule['id']}/activate",
        headers=legal_headers,
        json={"reviewer_membership_id": reviewer_id},
    )
    proposed = client.post(
        f"/api/ip/dockets/{docket['id']}/deadlines",
        headers=legal_headers,
        json={
            "title": "Critical examination response",
            "rule_version_id": rule["id"],
            "calendar_version_id": calendar["id"],
            "base_date": "2026-08-14",
            "base_date_certainty": "certain",
            "is_critical": True,
        },
    ).json()
    confirmed = client.post(
        f"/api/ip/deadlines/{proposed['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": proposed["version"],
            "responsibilities": _responsibilities(legal_id, reviewer_id),
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    # Confirmation creates an accepted coverage. Reassigning it leaves the new
    # owner un-acknowledged, which is how a critical item becomes unacknowledged
    # in practice.
    docket_state = client.get(f"/api/ip/dockets/{docket['id']}", headers=owner_headers).json()
    coverage_row = docket_state["deadline_coverages"][0]
    reassigned = client.post(
        f"/api/ip/dockets/{docket['id']}/deadline-coverages/{coverage_row['id']}/reassign",
        headers=owner_headers,
        json={
            "expected_responsible_membership_id": coverage_row["responsible_membership_id"],
            "responsible_membership_id": legal_id,
            "backup_membership_id": reviewer_id,
            "reason": "Reassigned to the responding attorney pending acknowledgement.",
        },
    )
    assert reassigned.status_code == 200, reassigned.text

    body = _docket_view(client, owner_headers).json()
    escalated = [e for e in body["escalations"] if e["reason"] == "unacknowledged_critical"]
    assert escalated, "an unacknowledged critical item must escalate"
    assert escalated[0]["critical"] is True
    assert escalated[0]["escalate_to_membership_id"] == reviewer_id
    assert escalated[0]["docket_id"] == docket["id"]

    queue = next(q for q in body["queues"] if q["membership_id"] == legal_id)
    assert queue["critical_count"] >= 1
    assert queue["unacknowledged_count"] >= 1


def test_uj50_exc01_restricted_work_contributes_no_leaked_counts(
    client: TestClient,
) -> None:
    """IPLF-UJ-50-EXC-01 — a restricted record adds no queue entry or count."""

    owner_headers, owner_id, primary_id, backup_id, matter = _setup(client)
    open_docket = _docket(client, owner_headers, matter_id=matter["id"], title="Open Docket Mark")
    secret = _docket(
        client,
        owner_headers,
        matter_id=matter["id"],
        title="Secret Docket Mark",
        restricted=True,
    )
    _coverage(
        client, owner_headers, open_docket["id"], matter_id=matter["id"], responsible=primary_id
    )
    _coverage(client, owner_headers, secret["id"], matter_id=matter["id"], responsible=primary_id)

    owner_view = _docket_view(client, owner_headers).json()
    assert (
        next(q for q in owner_view["queues"] if q["membership_id"] == primary_id)["assigned_count"]
        == 2
    )

    # A member without access to the restricted docket sees only the open one.
    login = client.post(
        "/api/auth/login",
        json={
            "email": "docket-backup@asterlegal.in",
            "password": "DeadlineAdmin123!",
            "company_slug": "aster-legal",
        },
    )
    assert login.status_code == 200, login.text
    client.cookies.clear()
    scoped_headers = auth_headers(str(login.json()["access_token"]))
    scoped = _docket_view(client, scoped_headers).json()
    serialized = str(scoped)
    assert secret["id"] not in serialized
    assert "Secret Docket Mark" not in serialized
    scoped_queue = [q for q in scoped["queues"] if q["membership_id"] == primary_id]
    assert scoped_queue and scoped_queue[0]["assigned_count"] == 1
