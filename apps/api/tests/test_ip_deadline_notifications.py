"""IPLF-035A deadline notification-intent preview and status (NOTIF, UJ-10).

Stable manifest test IDs:

* ``IPLF-UJ-10-NORMAL``   plan reminders, confirm, and read delivery status
* ``IPLF-UJ-10-EXC-03``   a permission change is visible before dispatch
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_clients import _mk_matter
from tests.test_ip_deadline_workflow import (
    _calendar_payload,
    _docket_for_matter,
    _member,
    _responsibilities,
    _rule_payload,
)


def _setup(client: TestClient):
    bootstrap = bootstrap_company(client)
    owner_token = str(bootstrap["access_token"])
    owner_headers = auth_headers(owner_token)
    legal_id, legal_token = _member(
        client, owner_token, name="Notif Legal", email="notif-legal@asterlegal.in"
    )
    reviewer_id, _r = _member(
        client, owner_token, name="Notif Backup", email="notif-backup@asterlegal.in"
    )
    legal_headers = auth_headers(legal_token)
    matter = _mk_matter(client, owner_token, "IP-NOTIF-035A")
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
    return owner_headers, legal_headers, legal_id, reviewer_id, deadline


def _preview(client, headers, deadline_id, responsibilities, offsets):
    return client.post(
        f"/api/ip/deadlines/{deadline_id}/notification-preview",
        headers=headers,
        json={"responsibilities": responsibilities, "reminder_offsets_days": offsets},
    )


def _status(client, headers, deadline_id):
    return client.get(f"/api/ip/deadlines/{deadline_id}/notifications", headers=headers)


def test_uj10_normal_preview_then_confirm_matches_the_plan(client: TestClient) -> None:
    """IPLF-UJ-10-NORMAL — the preview is the plan confirmation actually enqueues."""

    owner_headers, legal_headers, legal_id, reviewer_id, deadline = _setup(client)
    responsibilities = _responsibilities(legal_id, reviewer_id)

    preview = _preview(client, owner_headers, deadline["id"], responsibilities, [7, 1])
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["deadline_id"] == deadline["id"]
    assert plan["result_on"] == deadline["result_on"]
    assert plan["plan_is_proposal_only"] is True
    assert plan["external_delivery_enabled"] is False
    assert plan["withheld_count"] == 0

    # Two acknowledged owners x two offsets, all in-app and deliverable.
    assert len(plan["planned"]) == 4
    assert {e["recipient_membership_id"] for e in plan["planned"]} == {
        legal_id,
        reviewer_id,
    }
    assert {e["offset_days"] for e in plan["planned"]} == {1, 7}
    assert all(e["channel"] == "in_app" for e in plan["planned"])
    assert all(e["would_deliver"] is True for e in plan["planned"])
    assert all(e["critical"] is True for e in plan["planned"])

    # Previewing writes nothing.
    assert _status(client, owner_headers, deadline["id"]).json()["intents"] == []

    confirmed = client.post(
        f"/api/ip/deadlines/{deadline['id']}/confirm",
        headers=legal_headers,
        json={
            "expected_version": deadline["version"],
            "responsibilities": responsibilities,
            "reminder_offsets_days": [7, 1],
        },
    )
    assert confirmed.status_code == 200, confirmed.text

    status = _status(client, owner_headers, deadline["id"]).json()
    assert len(status["intents"]) == len(plan["planned"])
    # The scheduled times the plan promised are the ones that exist.
    assert {i["scheduled_for"] for i in status["intents"]} == {
        e["scheduled_for"] for e in plan["planned"]
    }
    assert {i["recipient_membership_id"] for i in status["intents"]} == {
        legal_id,
        reviewer_id,
    }
    assert all(i["channel"] == "in_app" for i in status["intents"])
    assert status["delivered_count"] == 0
    assert status["suppressed_count"] == 0


def test_uj10_exc03_unacknowledged_owner_is_withheld_in_the_plan(
    client: TestClient,
) -> None:
    """IPLF-UJ-10-EXC-03 — recipients are revalidated, not assumed."""

    owner_headers, _legal, legal_id, reviewer_id, deadline = _setup(client)

    responsibilities = _responsibilities(legal_id, reviewer_id)
    # The backup has not acknowledged the responsibility.
    responsibilities[1]["accepted"] = False

    plan = _preview(
        client, owner_headers, deadline["id"], responsibilities, [3]
    ).json()
    by_member = {e["recipient_membership_id"]: e for e in plan["planned"]}
    assert by_member[legal_id]["would_deliver"] is True
    assert by_member[reviewer_id]["would_deliver"] is False
    assert by_member[reviewer_id]["withheld_reason"] == "responsibility_not_acknowledged"
    assert plan["withheld_count"] == 1

    # A membership that does not exist is reported, not silently dropped.
    unknown = _preview(
        client,
        owner_headers,
        deadline["id"],
        [
            {
                "membership_id": "00000000-0000-0000-0000-000000000000",
                "role": "primary",
                "accepted": True,
                "escalation_policy": {},
            }
        ],
        [1],
    ).json()
    assert unknown["planned"][0]["would_deliver"] is False
    assert unknown["planned"][0]["withheld_reason"] == "membership_not_found"
    assert unknown["withheld_count"] == 1


def test_preview_offsets_are_normalized_and_scheduled_before_the_date(
    client: TestClient,
) -> None:
    """Offsets are de-duplicated, sorted, and always precede the result date."""

    owner_headers, _legal, legal_id, reviewer_id, deadline = _setup(client)
    responsibilities = _responsibilities(legal_id, reviewer_id)

    plan = _preview(
        client, owner_headers, deadline["id"], responsibilities, [7, 7, 1, -3]
    ).json()
    # Duplicates collapse and the negative offset is discarded.
    assert {e["offset_days"] for e in plan["planned"]} == {1, 7}
    assert len(plan["planned"]) == 4

    # Every reminder is scheduled strictly before the deadline date.
    for entry in plan["planned"]:
        assert entry["scheduled_for"][:10] < deadline["result_on"]

    # No offsets means no plan at all rather than an implicit default.
    empty = _preview(client, owner_headers, deadline["id"], responsibilities, []).json()
    assert empty["planned"] == []
    assert empty["withheld_count"] == 0


def test_notification_preview_is_access_scoped_and_tenant_isolated(
    client: TestClient,
) -> None:
    """Another tenant can neither plan nor read this deadline's notifications."""

    owner_headers, _legal, legal_id, reviewer_id, deadline = _setup(client)
    responsibilities = _responsibilities(legal_id, reviewer_id)
    assert _preview(
        client, owner_headers, deadline["id"], responsibilities, [1]
    ).status_code == 200

    other = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": "Other Notif Firm",
            "company_slug": "other-notif-firm",
            "company_type": "law_firm",
            "owner_full_name": "Other Owner",
            "owner_email": "owner@other-notif.example",
            "owner_password": "OtherNotif123!",
        },
    )
    assert other.status_code == 200, other.text
    other_headers = auth_headers(str(other.json()["access_token"]))

    assert _preview(
        client, other_headers, deadline["id"], responsibilities, [1]
    ).status_code == 404
    assert _status(client, other_headers, deadline["id"]).status_code == 404
    assert _status(client, owner_headers, "missing-deadline").status_code == 404
