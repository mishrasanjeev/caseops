from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.db.models import (
    InAppNotification,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    NotificationRule,
)
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company
from tests.test_ip_059a_foreign_associate_foundation import (
    _create_payload,
    _foundation_records,
    _lifecycle_version,
    _matter_and_docket,
    _transaction,
)


def _dispatched_instruction(client: TestClient) -> tuple[dict, dict[str, str], str, str]:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    created = client.post(
        "/api/ip/foreign-associate-instructions",
        headers=headers,
        json=_create_payload(
            docket_id=docket["id"],
            membership_id=membership_id,
            records=records,
            thread="ASTER-US-REMINDERS-2026",
        ),
    )
    assert created.status_code == 201, created.text
    instruction = created.json()
    approved = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=instruction["row_version"],
        membership_id=membership_id,
        kind="approve",
    )
    assert approved.status_code == 201, approved.text
    dispatched = _transaction(
        client,
        headers=headers,
        docket_id=docket["id"],
        instruction_id=instruction["id"],
        version=approved.json()["instruction"]["row_version"],
        membership_id=membership_id,
        kind="dispatch",
        extra={"dispatch_communication_id": records["communication_id"]},
    )
    assert dispatched.status_code == 201, dispatched.text
    return dispatched.json()["instruction"], headers, membership_id, company_id


def test_foreign_associate_event_names_fit_every_notification_owner() -> None:
    longest = len("foreign_associate_acknowledgement_overdue")
    for model in (
        NotificationRule,
        InAppNotification,
        NotificationDeliveryIntent,
        NotificationDeliveryEvent,
    ):
        assert model.__table__.c.event_type.type.length >= longest


def test_uj37_normal_reminders_are_idempotent_and_stop_on_acknowledgement(
    client: TestClient,
) -> None:
    instruction, headers, membership_id, company_id = _dispatched_instruction(client)
    payload = {
        "expected_version": instruction["row_version"],
        "expected_lifecycle_version": _lifecycle_version(
            client, headers, instruction["docket_id"]
        ),
        "reminder_offsets_hours": [48, 24, 0],
        "channels": ["in_app", "email"],
        "escalation_after_hours": 12,
        "escalation_membership_id": membership_id,
    }
    first = client.post(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/reminders",
        headers=headers,
        json=payload,
    )
    assert first.status_code == 200, first.text
    assert first.json()["created_count"] == 8
    assert first.json()["existing_count"] == 0
    assert {row["event_type"] for row in first.json()["reminders"]} == {
        "foreign_associate_acknowledgement_due",
        "foreign_associate_acknowledgement_overdue",
    }
    assert sum(row["critical"] for row in first.json()["reminders"]) == 2

    replay = client.post(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/reminders",
        headers=headers,
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["created_count"] == 0
    assert replay.json()["existing_count"] == 8

    workspace = client.get(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/workspace",
        headers=headers,
    )
    assert workspace.status_code == 200, workspace.text
    assert len(workspace.json()["reminders"]) == 8
    assert workspace.json()["acknowledgement_status"] == "outstanding"

    acknowledged = _transaction(
        client,
        headers=headers,
        docket_id=instruction["docket_id"],
        instruction_id=instruction["id"],
        version=instruction["row_version"],
        membership_id=membership_id,
        kind="acknowledge",
        extra={"acknowledgement_reference": "Associate acknowledgement ACK-US-101"},
    )
    assert acknowledged.status_code == 201, acknowledged.text
    assert acknowledged.json()["event"]["payload_json"]["cancelled_reminder_count"] == 4
    with get_session_factory()() as session:
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.company_id == company_id,
                    NotificationDeliveryIntent.schedule_source_type
                    == "ip_foreign_associate_instruction",
                    NotificationDeliveryIntent.schedule_source_id == instruction["id"],
                )
            )
        )
        assert sum(str(intent.status) == "cancelled" for intent in intents) == 4
        assert sum(str(intent.status) == "blocked" for intent in intents) == 4

    after = client.get(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/workspace",
        headers=headers,
    )
    assert after.status_code == 200, after.text
    assert after.json()["acknowledgement_status"] == "received"
    assert after.json()["response_overdue"] is False


def test_uj37_reminder_policy_fails_closed_for_wrong_state_and_stale_versions(
    client: TestClient,
) -> None:
    bootstrap = bootstrap_company(client)
    headers = auth_headers(str(bootstrap["access_token"]))
    company_id = str(bootstrap["company"]["id"])
    membership_id = str(bootstrap["membership"]["id"])
    matter, docket = _matter_and_docket(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
    )
    records = _foundation_records(
        client,
        headers=headers,
        company_id=company_id,
        membership_id=membership_id,
        matter=matter,
        docket_id=docket["id"],
    )
    create_payload = _create_payload(
        docket_id=docket["id"],
        membership_id=membership_id,
        records=records,
        thread=f"ASTER-US-REMINDER-NEGATIVE-{datetime.now(UTC).timestamp()}",
    )
    created = client.post(
        "/api/ip/foreign-associate-instructions", headers=headers, json=create_payload
    )
    assert created.status_code == 201, created.text
    instruction = created.json()
    reminder_payload = {
        "expected_version": instruction["row_version"],
        "expected_lifecycle_version": 0,
        "reminder_offsets_hours": [24],
        "channels": ["in_app"],
        "escalation_after_hours": 24,
    }
    wrong_state = client.post(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/reminders",
        headers=headers,
        json=reminder_payload,
    )
    assert wrong_state.status_code == 409
    assert "dispatched" in wrong_state.text

    reminder_payload["reminder_offsets_hours"] = [24, 24]
    duplicate_policy = client.post(
        f"/api/ip/foreign-associate-instructions/{instruction['id']}/reminders",
        headers=headers,
        json=reminder_payload,
    )
    assert duplicate_policy.status_code == 422
    assert "unique" in duplicate_policy.text
