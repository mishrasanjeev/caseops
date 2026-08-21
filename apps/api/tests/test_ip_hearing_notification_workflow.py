"""IPLF-035B hearing precision and reminder replacement-chain proof."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from caseops_api.db.models import IpDocketRecord
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company


def test_uj10_unknown_time_confirmation_supersedes_reminders(
    client: TestClient,
) -> None:
    """IPLF-UJ-10-EXC-01/02: preserve uncertainty, then expose its replacement."""
    bootstrap = bootstrap_company(client)
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    headers = auth_headers(str(bootstrap["access_token"]))
    with get_session_factory()() as session:
        docket = IpDocketRecord(
            company_id=company_id,
            record_type="trademark",
            title="Unknown-time hearing",
            status="draft",
            restricted=False,
            created_by_membership_id=membership_id,
        )
        session.add(docket)
        session.commit()
        docket_id = docket.id

    hearing_on = date.today() + timedelta(days=60)
    created = client.post(
        "/api/ip/hearings",
        headers=headers,
        json={
            "docket_id": docket_id,
            "hearing_on": hearing_on.isoformat(),
            "forum_name": "Trade Marks Registry, Delhi",
            "purpose": "Opposition hearing",
            "time_status": "time_not_published",
            "timezone": "Asia/Kolkata",
            "responsible_membership_id": membership_id,
            "reminder_policy": {
                "offsets_hours": [48, 24],
                "channels": ["email", "in_app"],
                "recipient_membership_ids": [membership_id],
                "date_reminder_local_time": "18:00:00",
                "critical": True,
            },
        },
    )
    assert created.status_code == 201, created.text
    first = created.json()
    hearing_id = str(first["id"])
    assert first["time_confirmation_required"] is True
    assert first["current_schedule_generation"] == 1
    assert len(first["reminders"]) == 4
    assert all(row["is_superseded"] is False for row in first["reminders"])
    assert all(row["replacement_generation"] is None for row in first["reminders"])

    confirmed = client.patch(
        f"/api/ip/hearings/{hearing_id}",
        headers=headers,
        json={
            "docket_id": docket_id,
            "time_status": "exact",
            "hearing_time": "14:30:00",
            "session_label": None,
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    current = confirmed.json()
    assert current["time_confirmation_required"] is False
    assert current["hearing_time"] == "14:30:00"
    assert current["current_schedule_generation"] == 2

    first_generation = [
        row for row in current["reminders"] if row["schedule_generation"] == 1
    ]
    replacement_generation = [
        row for row in current["reminders"] if row["schedule_generation"] == 2
    ]
    assert len(first_generation) == 4
    assert {row["status"] for row in first_generation} == {"cancelled"}
    assert all(row["is_superseded"] is True for row in first_generation)
    assert {row["replacement_generation"] for row in first_generation} == {2}
    assert len(replacement_generation) == 4
    assert {row["status"] for row in replacement_generation} == {"queued"}
    assert all(row["is_superseded"] is False for row in replacement_generation)

    cancelled = client.patch(
        f"/api/ip/hearings/{hearing_id}",
        headers=headers,
        json={"docket_id": docket_id, "status": "cancelled"},
    )
    assert cancelled.status_code == 200, cancelled.text
    cancelled_body = cancelled.json()
    assert cancelled_body["current_schedule_generation"] is None
    final_generation = [
        row
        for row in cancelled_body["reminders"]
        if row["schedule_generation"] == 2
    ]
    assert {row["status"] for row in final_generation} == {"cancelled"}
    assert all(row["is_superseded"] is False for row in final_generation)
    assert all(row["replacement_generation"] is None for row in final_generation)
