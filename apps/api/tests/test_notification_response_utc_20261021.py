from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from caseops_api.api.routes.notifications import (
    EmailSuppressionRecord,
    HearingReminderRecord,
    NotificationIntentRecord,
)
from caseops_api.db.models import NotificationDeliveryIntent
from caseops_api.db.session import get_session_factory
from tests.test_auth_company import auth_headers, bootstrap_company

TIMESTAMP_FIELDS = {
    HearingReminderRecord: ("scheduled_for", "sent_at", "delivered_at", "created_at", "updated_at"),
    NotificationIntentRecord: ("scheduled_for", "created_at", "updated_at"),
    EmailSuppressionRecord: ("first_occurrence", "last_occurrence", "recovered_at"),
}
NULLABLE_FIELDS = {
    HearingReminderRecord: ("sent_at", "delivered_at"),
    NotificationIntentRecord: ("scheduled_for",),
    EmailSuppressionRecord: ("recovered_at",),
}
INSTANT = datetime(2026, 10, 20, 18, 30, tzinfo=UTC)


def _payload(record_type: type[BaseModel], stamp: datetime) -> dict[str, object]:
    if record_type is HearingReminderRecord:
        payload = {
            "id": "reminder-utc", "company_id": "company-utc", "matter_id": None,
            "ip_docket_id": None, "hearing_id": "hearing-utc", "recipient_email": None,
            "channel": "in_app", "status": "delivered", "provider": None,
            "provider_message_id": None, "last_error": None, "attempts": 1,
        }
    elif record_type is NotificationIntentRecord:
        payload = {
            "id": "intent-utc", "channel": "in_app", "status": "queued",
            "event_type": "notification_test", "source_type": "self_service_test",
            "source_id": "source-utc", "attempts": 0, "destination_version": 1,
            "destination": None, "critical": False, "suppression_reason": None,
            "fallback_intent_id": None, "superseded_by_intent_id": None,
            "recovery_of_intent_id": None, "last_error_redacted": None,
        }
    else:
        assert record_type is EmailSuppressionRecord
        payload = {
            "id": "suppression-utc", "provider": "sendgrid", "category": "unsubscribe",
            "affected_address": "recipient@example.test", "recovery_action": None,
            "fallback_sent": False,
        }
    return {**payload, **{name: stamp for name in TIMESTAMP_FIELDS[record_type]}}


def _assert_utc_json(value: str, expected: datetime) -> datetime:
    assert value.endswith("Z"), value
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timedelta(0)
    assert parsed == expected
    return parsed


@pytest.mark.parametrize("record_type", TIMESTAMP_FIELDS, ids=lambda model: model.__name__)
@pytest.mark.parametrize("input_kind", ("naive_utc", "aware_utc", "aware_offset"))
def test_persisted_response_timestamps_emit_utc_without_changing_instant(
    record_type: type[BaseModel], input_kind: str,
) -> None:
    stamp = {
        "naive_utc": INSTANT.replace(tzinfo=None),
        "aware_utc": INSTANT,
        "aware_offset": INSTANT.astimezone(timezone(timedelta(hours=5, minutes=30))),
    }[input_kind]
    payload = _payload(record_type, stamp)
    model = record_type.model_validate(payload)
    encoded = json.loads(model.model_dump_json())
    for name in TIMESTAMP_FIELDS[record_type]:
        _assert_utc_json(encoded[name], INSTANT)
    for name in set(payload) - set(TIMESTAMP_FIELDS[record_type]):
        assert encoded[name] == payload[name]


@pytest.mark.parametrize("record_type", TIMESTAMP_FIELDS, ids=lambda model: model.__name__)
def test_optional_response_timestamps_preserve_null(record_type: type[BaseModel]) -> None:
    payload = _payload(record_type, INSTANT)
    payload.update({name: None for name in NULLABLE_FIELDS[record_type]})
    encoded = json.loads(record_type.model_validate(payload).model_dump_json())
    for name in NULLABLE_FIELDS[record_type]:
        assert encoded[name] is None


@pytest.mark.parametrize(
    ("stamp", "expected_ist_day", "days_remaining"),
    [
        (datetime(2026, 10, 20, 18, 29, 59), date(2026, 10, 20), 1),
        (datetime(2026, 10, 20, 18, 30), date(2026, 10, 21), 0),
        (datetime(2026, 10, 20, 23, 59, 59), date(2026, 10, 21), 0),
        (datetime(2026, 10, 21, 0, 0), date(2026, 10, 21), 0),
    ],
    ids=("before_ist_midnight", "at_ist_midnight", "before_utc_midnight", "at_utc_midnight"),
)
def test_scheduled_day_is_independent_of_client_timezone_assumptions(
    stamp: datetime, expected_ist_day: date, days_remaining: int,
) -> None:
    record = NotificationIntentRecord.model_validate(_payload(NotificationIntentRecord, stamp))
    encoded = json.loads(record.model_dump_json())
    scheduled = _assert_utc_json(encoded["scheduled_for"], stamp.replace(tzinfo=UTC))
    scheduled_day = scheduled.astimezone(ZoneInfo("Asia/Kolkata")).date()
    assert scheduled_day == expected_ist_day
    assert (date(2026, 10, 21) - scheduled_day).days == days_remaining


def test_sqlite_notification_list_serializes_reloaded_utc_timestamps(client: TestClient) -> None:
    boot = bootstrap_company(client)
    headers = {**auth_headers(str(boot["access_token"])),
               "X-CaseOps-Automated-Test": "no-paid-providers"}
    with get_session_factory()() as session:
        assert session.bind is not None and session.bind.dialect.name == "sqlite"
        intent = NotificationDeliveryIntent(
            company_id=str(boot["company"]["id"]),
            recipient_membership_id=str(boot["membership"]["id"]),
            channel="in_app", event_type="notification_test", source_type="self_service_test",
            source_id=uuid4().hex, idempotency_key=uuid4().hex, status="queued",
            scheduled_for=INSTANT, created_at=INSTANT, updated_at=INSTANT,
        )
        session.add(intent)
        session.commit()
        intent_id = intent.id
        session.expire_all()
        reloaded = session.get(NotificationDeliveryIntent, intent_id)
        assert reloaded is not None
        for name in TIMESTAMP_FIELDS[NotificationIntentRecord]:
            assert getattr(reloaded, name).tzinfo is None

    response = client.get("/api/admin/notifications", headers=headers)
    assert response.status_code == 200, response.text
    row = next(item for item in response.json()["intents"] if item["id"] == intent_id)
    for name in TIMESTAMP_FIELDS[NotificationIntentRecord]:
        _assert_utc_json(row[name], INSTANT)
