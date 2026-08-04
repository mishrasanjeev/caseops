"""IPLF-007C deterministic acceptance for NOTIF-01..24 and UJ-11."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EmailSuppression,
    HearingReminder,
    HearingReminderDeliveryIntent,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.notification_delivery import (
    apply_notification_provider_event,
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company


def _matter(client: TestClient, token: str, code: str) -> dict:
    response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": f"Notification convergence {code}",
            "matter_code": code,
            "practice_area": "intellectual_property",
            "forum_level": "high_court",
            "status": "intake",
            "court_name": "Delhi High Court",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _context(session) -> SessionContext:
    membership = session.scalar(select(CompanyMembership))
    assert membership is not None
    company = session.get(Company, membership.company_id)
    user = session.get(User, membership.user_id)
    assert company is not None and user is not None
    return SessionContext(company=company, membership=membership, user=user)


def test_iplf_uj_11_normal_self_service_test_and_admin_metrics(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))

    tested = client.post("/api/notification-preferences/test", headers=headers)
    assert tested.status_code == 200, tested.text
    assert tested.json()["intent"]["status"] == "delivered"
    assert tested.json()["intent"]["channel"] == "in_app"
    assert "without contacting an external provider" in tested.json()["message"]

    dashboard = client.get("/api/admin/notifications", headers=headers)
    assert dashboard.status_code == 200, dashboard.text
    payload = dashboard.json()
    assert payload["metrics"]["delivered"] == 1
    assert payload["metrics"]["attempted"] == 1
    assert payload["metrics"]["critical_alerts"] == 0
    assert payload["intents"][0]["event_type"] == "notification_test"


def test_iplf_req_notif_01_02_17_21_hearing_policy_lineage_and_cancellation(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    headers = auth_headers(token)
    matter = _matter(client, token, "IPLF-007C-HEARING")
    hearing_on = (datetime.now(UTC) + timedelta(days=4)).date()
    created = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=headers,
        json={
            "hearing_on": hearing_on.isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Time not published listing",
            "time_status": "time_not_published",
            "timezone": "Asia/Kolkata",
            "reminder_channels": ["in_app", "email"],
            "reminder_offsets_hours": [24, 1],
            "notification_critical": True,
        },
    )
    assert created.status_code == 200, created.text
    hearing = created.json()
    assert hearing["hearing_time"] is None
    assert hearing["time_status"] == "time_not_published"
    assert hearing["reminder_policy"]["schedule_basis"] == "date_boundary"
    assert hearing["reminder_policy"]["date_reminder_local_time"] == "18:00"

    with get_session_factory()() as session:
        reminders = list(
            session.scalars(
                select(HearingReminder).where(HearingReminder.hearing_id == hearing["id"])
            )
        )
        links = list(session.scalars(select(HearingReminderDeliveryIntent)))
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
                    NotificationDeliveryIntent.schedule_source_id == hearing["id"],
                )
            )
        )
        assert len(reminders) == 2
        assert len([link for link in links if link.is_primary]) == 2
        assert len(intents) == 4
        assert {intent.channel for intent in intents} == {"email", "in_app"}
        assert all(intent.scheduled_for is not None for intent in intents)
        assert all(intent.critical for intent in intents)
        assert all(
            intent.confidentiality_mode == "minimal"
            for intent in intents
            if intent.channel == "email"
        )

    closed = client.patch(
        f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
        headers=headers,
        json={"status": "completed"},
    )
    assert closed.status_code == 200, closed.text
    with get_session_factory()() as session:
        pending = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.schedule_source_id == hearing["id"],
                    NotificationDeliveryIntent.status.in_(("queued", "retry_scheduled")),
                )
            )
        )
        assert pending == []


def test_iplf_uj_11_exc_01_out_of_order_bounce_is_audited_and_not_overwritten(
    client: TestClient,
    monkeypatch,
) -> None:
    bootstrap_company(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        lambda **_kwargs: (True, "sg-007c-message", None),
    )

    with get_session_factory()() as session:
        context = _context(session)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id="iplf-007c-out-of-order",
            title="Sensitive Matter v Opponent",
            body="Privileged merits and client facts",
            critical=True,
            escalation_membership=context.membership,
        )
        assert intent is not None
        process_notification_delivery_intent(session, intent_id=intent.id, context=context)
        assert intent.title == "CaseOps notification"
        assert "Sensitive" not in (intent.title or "")
        bounce = apply_notification_provider_event(
            session,
            event={
                "event": "bounce",
                "notification_intent_id": intent.id,
                "sg_message_id": "sg-007c-message.filter",
                "sg_event_id": "event-007c-bounce",
                "timestamp": 200,
                "email": context.user.email,
                "reason": "550 permanent",
            },
        )
        late_delivery = apply_notification_provider_event(
            session,
            event={
                "event": "delivered",
                "notification_intent_id": intent.id,
                "sg_message_id": "sg-007c-message.filter",
                "sg_event_id": "event-007c-late-delivery",
                "timestamp": 100,
            },
        )
        duplicate = apply_notification_provider_event(
            session,
            event={
                "event": "bounce",
                "notification_intent_id": intent.id,
                "sg_message_id": "sg-007c-message.filter",
                "sg_event_id": "event-007c-bounce",
                "timestamp": 200,
                "email": context.user.email,
            },
        )
        assert bounce and late_delivery and duplicate
        session.commit()
        session.refresh(intent)
        assert intent.status == "bounced"
        events = list(
            session.scalars(
                select(NotificationDeliveryEvent).where(
                    NotificationDeliveryEvent.intent_id == intent.id,
                    NotificationDeliveryEvent.provider == "sendgrid",
                )
            )
        )
        provider_events = [event for event in events if event.event_type.startswith("provider_")]
        assert len(provider_events) == 3  # accepted, bounce, late delivered; duplicate is ignored
        late = next(event for event in provider_events if event.event_type == "provider_delivered")
        assert late.applied_to_state is False
        suppression = session.scalar(select(EmailSuppression))
        assert suppression is not None
        assert suppression.first_event_at <= suppression.last_event_at
        assert suppression.fallback_sent is True


def test_iplf_uj_11_exc_02_provider_disabled_recovery_is_versioned(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    with get_session_factory()() as session:
        context = _context(session)
        original = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id="iplf-007c-provider-outage",
            title="Hearing reminder",
            body="Open CaseOps.",
            critical=True,
            escalation_membership=context.membership,
        )
        assert original is not None and original.status == "blocked"
        original_id = original.id
        session.commit()

    preview = client.get(
        f"/api/admin/notifications/intents/{original_id}/recovery-preview",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["recoverable"] is True
    assert preview.json()["next_destination_version"] == 2

    recovered = client.post(
        f"/api/admin/notifications/intents/{original_id}/recover",
        headers=headers,
        json={"recovery_action": "Provider configuration repaired and retry approved"},
    )
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["intent"]["destination_version"] == 2
    assert recovered.json()["intent"]["recovery_of_intent_id"] == original_id
    with get_session_factory()() as session:
        original = session.get(NotificationDeliveryIntent, original_id)
        assert original is not None and original.superseded_by_intent_id
