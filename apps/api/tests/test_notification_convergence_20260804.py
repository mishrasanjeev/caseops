"""IPLF-007C deterministic acceptance for NOTIF-01..24 and UJ-11."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EmailSuppression,
    EmailSuppressionReason,
    HearingReminder,
    HearingReminderDeliveryIntent,
    IpDocketRecord,
    MatterAccessGrant,
    MatterHearing,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.email_suppression import record_suppression
from caseops_api.services.hearing_reminders import run_reminder_worker
from caseops_api.services.notification_delivery import (
    NOTIFICATION_DISPATCH_CLAIM_IN_FLIGHT_CODE,
    NOTIFICATION_DISPATCH_CLAIM_PREFIX,
    NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_CODE,
    apply_notification_provider_event,
    drain_notification_delivery_intents,
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


def _blocked_recovery_intent(
    session,
    *,
    company_id: str,
    recipient_membership_id: str,
    matter_id: str | None = None,
    ip_docket_id: str | None = None,
    schedule_source_type: str,
    schedule_source_id: str,
    critical: bool = True,
) -> NotificationDeliveryIntent:
    intent = NotificationDeliveryIntent(
        company_id=company_id,
        recipient_membership_id=recipient_membership_id,
        destination_version=1,
        matter_id=matter_id,
        ip_docket_id=ip_docket_id,
        channel="email",
        event_type="recovery_authority_test",
        source_type="provider_fixture",
        source_id=f"recovery-authority:{uuid4()}",
        idempotency_key=uuid4().hex,
        status="blocked",
        dead_letter_reason="provider_disabled",
        title="Recovery authority fixture",
        body="Open CaseOps to review this notification.",
        critical=critical,
        schedule_source_type=schedule_source_type,
        schedule_source_id=schedule_source_id,
        recipient_snapshot_json={
            "target_type": "membership",
            "target_ref": recipient_membership_id,
            "destination": "original-recipient@example.test",
            "channel": "email",
            "destination_version": 1,
        },
        dispatch_owner="durable_intent",
    )
    session.add(intent)
    session.flush()
    return intent


def _assert_exact_recovery_identity(
    intent: NotificationDeliveryIntent,
    *,
    original_intent_id: str,
) -> None:
    assert intent.source_type == "notification_recovery"
    assert intent.source_id == original_intent_id
    assert intent.source_id != f"{original_intent_id}:v{intent.destination_version}"
    assert len(intent.source_id) <= 36


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


def test_iplf_req_notif_09_suppression_recovery_route_preserves_evidence(
    client: TestClient,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    with get_session_factory()() as session:
        context = _context(session)
        suppression = record_suppression(
            session,
            company_id=context.company.id,
            recipient_email="recovered@example.test",
            reason=EmailSuppressionReason.UNSUBSCRIBE,
            detail="Provider unsubscribe evidence",
            source_message_id="sg-007c-recovery",
        )
        suppression_id = suppression.id
        first_event_at = suppression.first_event_at
        session.commit()

    recovered = client.post(
        f"/api/admin/notifications/suppressions/{suppression_id}/recover",
        headers=headers,
        json={"recovery_action": "Recipient consent was independently reconfirmed"},
    )
    assert recovered.status_code == 200, recovered.text
    payload = recovered.json()
    assert payload["id"] == suppression_id
    assert payload["category"] == "unsubscribe"
    assert payload["affected_address"] == "recovered@example.test"
    assert payload["recovered_at"] is not None
    assert payload["recovery_action"] == "Recipient consent was independently reconfirmed"

    with get_session_factory()() as session:
        persisted = session.get(EmailSuppression, suppression_id)
        assert persisted is not None
        persisted_first = persisted.first_event_at
        if persisted_first.tzinfo is None:
            persisted_first = persisted_first.replace(tzinfo=UTC)
        assert persisted_first == first_event_at
        assert persisted.source_message_id == "sg-007c-recovery"
        assert persisted.recovered_by_membership_id is not None


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
    recovered_id = recovered.json()["intent"]["id"]
    with get_session_factory()() as session:
        original = session.get(NotificationDeliveryIntent, original_id)
        assert original is not None and original.superseded_by_intent_id
        recovered_intent = session.get(NotificationDeliveryIntent, recovered_id)
        assert recovered_intent is not None
        fallback = session.get(
            NotificationDeliveryIntent,
            recovered_intent.fallback_intent_id,
        )
        assert fallback is not None
        for row in (recovered_intent, fallback):
            _assert_exact_recovery_identity(
                row,
                original_intent_id=original_id,
            )


def test_ip_hearing_and_deadline_recovery_preserve_authority_and_deny_unrelated(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_ip_coverage_projection_cutover import (
        _confirmed_deadline_environment,
    )

    env = _confirmed_deadline_environment(client, monkeypatch)
    headers = auth_headers(env["owner_token"])
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", False)
    with get_session_factory()() as session:
        docket = session.get(IpDocketRecord, env["docket_id"])
        assert docket is not None
        docket.restricted = True
        session.add(
            MatterAccessGrant(
                company_id=env["company_id"],
                ip_docket_id=docket.id,
                membership_id=env["reviewer_id"],
                granted_by_membership_id=env["owner_id"],
                reason="Recovery authority fixture",
            )
        )
        hearing = MatterHearing(
            company_id=env["company_id"],
            matter_id=None,
            ip_docket_id=docket.id,
            hearing_on=(datetime.now(UTC) + timedelta(days=3)).date(),
            forum_name="IP Office",
            purpose="Recovery authority hearing",
            status="scheduled",
            responsible_membership_id=env["reviewer_id"],
        )
        session.add(hearing)
        session.flush()
        fixtures = (
            ("matter_hearing", hearing.id, docket.id),
            # Deliberately omit the direct target on the legacy deadline row;
            # recovery must rebind it from the exact schedule source.
            ("ip_deadline", env["ip_deadline_id"], None),
        )
        originals: list[tuple[str, str, str]] = []
        for schedule_type, schedule_id, direct_docket_id in fixtures:
            original = _blocked_recovery_intent(
                session,
                company_id=env["company_id"],
                recipient_membership_id=env["reviewer_id"],
                ip_docket_id=direct_docket_id,
                schedule_source_type=schedule_type,
                schedule_source_id=schedule_id,
            )
            originals.append((original.id, schedule_type, schedule_id))
        session.commit()

    for original_id, schedule_type, schedule_id in originals:
        denied = client.post(
            f"/api/admin/notifications/intents/{original_id}/recover",
            headers=headers,
            json={
                "replacement_membership_id": env["unrelated_id"],
                "recovery_action": "Attempt recovery to an unrelated recipient",
            },
        )
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == "notification_recovery_target_access_denied"
        with get_session_factory()() as session:
            assert list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.recovery_of_intent_id
                        == original_id
                    )
                )
            ) == []

        recovered_response = client.post(
            f"/api/admin/notifications/intents/{original_id}/recover",
            headers=headers,
            json={
                "replacement_membership_id": env["reviewer_id"],
                "recovery_action": "Restore delivery to the authorized docket reviewer",
            },
        )
        assert recovered_response.status_code == 200, recovered_response.text
        recovered_id = recovered_response.json()["intent"]["id"]
        with get_session_factory()() as session:
            recovered = session.get(NotificationDeliveryIntent, recovered_id)
            assert recovered is not None
            fallback = session.get(
                NotificationDeliveryIntent,
                recovered.fallback_intent_id,
            )
            assert fallback is not None
            for row in (recovered, fallback):
                _assert_exact_recovery_identity(
                    row,
                    original_intent_id=original_id,
                )
                assert row.matter_id is None
                assert row.ip_docket_id == env["docket_id"]
                assert row.schedule_source_type == schedule_type
                assert row.schedule_source_id == schedule_id
                assert row.critical is True

    # Exercise the post-provider `_ensure_in_app_fallback` path separately
    # from the provider-disabled enqueue fallback above.
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "recovery-test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        lambda **_kwargs: (False, None, "sendgrid 400 rejected"),
    )
    with get_session_factory()() as session:
        company = session.get(Company, env["company_id"])
        actor = session.get(CompanyMembership, env["owner_id"])
        reviewer = session.get(CompanyMembership, env["reviewer_id"])
        docket = session.get(IpDocketRecord, env["docket_id"])
        assert company is not None and actor is not None
        assert reviewer is not None and docket is not None
        context = SessionContext(company=company, membership=actor, user=actor.user)
        provider_failure = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=reviewer,
            channel="email",
            event_type="recovery_authority_provider_failure",
            source_type="provider_fixture",
            source_id=f"provider-failure:{uuid4()}",
            ip_docket=docket,
            title="Provider failure fallback",
            body="Open CaseOps.",
            critical=False,
            scheduled_for=datetime.now(UTC) - timedelta(hours=1),
            schedule_source_type="ip_deadline",
            schedule_source_id=env["ip_deadline_id"],
        )
        assert provider_failure is not None
        result = process_notification_delivery_intent(
            session,
            intent_id=provider_failure.id,
            context=context,
        )
        assert result.dead_lettered is True
        session.refresh(provider_failure)
        fallback = session.get(
            NotificationDeliveryIntent,
            provider_failure.fallback_intent_id,
        )
        assert fallback is not None
        assert fallback.ip_docket_id == env["docket_id"]
        assert fallback.matter_id is None
        assert fallback.schedule_source_type == "ip_deadline"
        assert fallback.schedule_source_id == env["ip_deadline_id"]
        assert fallback.scheduled_for == provider_failure.scheduled_for


def test_matter_recovery_and_critical_companion_preserve_target_and_schedule(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    headers = auth_headers(token)
    matter = _matter(client, token, "RECOVERY-MATTER-TARGET")
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "recovery-test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    schedule_id = f"matter-schedule:{uuid4()}"
    with get_session_factory()() as session:
        original = _blocked_recovery_intent(
            session,
            company_id=str(boot["company"]["id"]),
            recipient_membership_id=str(boot["membership"]["id"]),
            matter_id=str(matter["id"]),
            schedule_source_type="notification_rule",
            schedule_source_id=schedule_id,
        )
        original_id = original.id
        session.commit()

    response = client.post(
        f"/api/admin/notifications/intents/{original_id}/recover",
        headers=headers,
        json={"recovery_action": "Restore the exact Matter-scoped notification"},
    )
    assert response.status_code == 200, response.text
    with get_session_factory()() as session:
        recovered = session.get(
            NotificationDeliveryIntent,
            response.json()["intent"]["id"],
        )
        assert recovered is not None
        companion = session.get(NotificationDeliveryIntent, recovered.fallback_intent_id)
        assert companion is not None
        assert companion.channel == "in_app"
        for row in (recovered, companion):
            _assert_exact_recovery_identity(
                row,
                original_intent_id=original_id,
            )
            assert row.matter_id == matter["id"]
            assert row.ip_docket_id is None
            assert row.schedule_source_type == "notification_rule"
            assert row.schedule_source_id == schedule_id


def test_recovery_rejects_advisory_tuple_change_without_persisting_any_write(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.api.routes import notifications as notification_routes

    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    matter = _matter(client, token, "RECOVERY-STALE-TUPLE")
    with get_session_factory()() as session:
        original = _blocked_recovery_intent(
            session,
            company_id=str(boot["company"]["id"]),
            recipient_membership_id=str(boot["membership"]["id"]),
            matter_id=str(matter["id"]),
            schedule_source_type="notification_rule",
            schedule_source_id=f"stale-schedule:{uuid4()}",
        )
        original_id = original.id
        session.commit()

    real_fence = notification_routes.lock_company_memberships_for_assignment
    changed = False

    def change_tuple_before_fence(session, **kwargs):
        nonlocal changed
        if not changed:
            row = session.get(NotificationDeliveryIntent, original_id)
            assert row is not None
            row.dead_letter_reason = "changed_after_recovery_preview"
            session.flush()
            changed = True
        return real_fence(session, **kwargs)

    monkeypatch.setattr(
        notification_routes,
        "lock_company_memberships_for_assignment",
        change_tuple_before_fence,
    )
    response = client.post(
        f"/api/admin/notifications/intents/{original_id}/recover",
        headers=auth_headers(token),
        json={"recovery_action": "Attempt recovery from a stale advisory tuple"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "notification_recovery_state_changed"
    with get_session_factory()() as session:
        original = session.get(NotificationDeliveryIntent, original_id)
        assert original is not None
        assert original.dead_letter_reason == "provider_disabled"
        assert original.superseded_by_intent_id is None
        assert list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.recovery_of_intent_id == original_id
                )
            )
        ) == []


def test_sendgrid_accepted_then_timeout_is_not_automatically_resent(
    client: TestClient,
    monkeypatch,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    accepted: list[str] = []

    def accepted_then_timeout(**kwargs) -> tuple[bool, str | None, str | None]:
        accepted.append(str(kwargs["custom_args"]["notification_intent_id"]))
        raise TimeoutError("provider accepted request before response timeout")

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        accepted_then_timeout,
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
            source_id="sendgrid-ambiguous-acceptance",
            title="Sensitive title",
            body="Sensitive body",
            critical=True,
            escalation_membership=context.membership,
        )
        assert intent is not None
        intent_id = intent.id
        first = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            context=context,
        )
        second = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            context=context,
        )
        session.refresh(intent)
        assert first.status == "dead_letter"
        assert second.status == "dead_letter"
        assert intent.status == "dead_letter"
        assert intent.dead_letter_reason == "dispatch_provider_outcome_unknown"
        assert intent.next_attempt_at is None
        assert intent.attempts == 1
        assert accepted == [intent_id]
        unknown_events = list(
            session.scalars(
                select(NotificationDeliveryEvent).where(
                    NotificationDeliveryEvent.intent_id == intent_id,
                    NotificationDeliveryEvent.event_type
                    == "provider_dispatch_outcome_unknown",
                )
            )
        )
        assert len(unknown_events) == 1

    operations = client.get(
        "/api/admin/provider-operations/jobs",
        headers=auth_headers(token),
    )
    assert operations.status_code == 200, operations.text
    record = next(
        row
        for row in operations.json()["operations"]
        if row["id"] == f"notification_delivery:{intent_id}"
    )
    assert record["status"] == "dead_letter"
    assert record["replay_available"] is False


@pytest.mark.parametrize(
    "unknown_reason",
    [
        "dispatch_provider_outcome_unknown",
        "dispatch_claim_expired_provider_outcome_unknown",
    ],
)
def test_unknown_provider_outcome_cannot_use_generic_recovery_or_resend(
    client: TestClient,
    monkeypatch,
    unknown_reason: str,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    provider_calls: list[str] = []

    def unexpected_send(**kwargs) -> tuple[bool, str | None, str | None]:
        provider_calls.append(str(kwargs))
        return True, "unexpected-provider-id", None

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        unexpected_send,
    )
    with get_session_factory()() as session:
        context = _context(session)
        original = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id=f"unknown-recovery-{unknown_reason}",
            title="Sensitive title",
            body="Sensitive body",
            critical=True,
            escalation_membership=context.membership,
        )
        assert original is not None
        original.status = "dead_letter"
        original.dead_letter_reason = unknown_reason
        original.next_attempt_at = None
        original.provider_event_id = None
        session.add(original)
        session.commit()
        original_id = original.id

    preview = client.get(
        f"/api/admin/notifications/intents/{original_id}/recovery-preview",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["recoverable"] is False

    for action in ("ignore", "mark-resolved"):
        closed = client.post(
            "/api/admin/provider-operations/jobs/"
            f"notification_delivery:{original_id}/{action}",
            headers=headers,
            json={"reason": "Do not erase ambiguous provider evidence."},
        )
        assert closed.status_code == 409, closed.text
        assert closed.json()["code"] == (
            "notification_provider_outcome_unknown_reconciliation_required"
        )

    recovered = client.post(
        f"/api/admin/notifications/intents/{original_id}/recover",
        headers=headers,
        json={"recovery_action": "Provider configuration repaired and retry approved"},
    )
    assert recovered.status_code == 409, recovered.text
    assert recovered.json()["code"] == (
        "notification_provider_outcome_unknown_reconciliation_required"
    )

    with get_session_factory()() as session:
        drained = drain_notification_delivery_intents(session, limit=10)
        original = session.get(NotificationDeliveryIntent, original_id)
        recoveries = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.recovery_of_intent_id == original_id
                )
            )
        )
        assert original is not None
        assert original.status == "dead_letter"
        assert original.dead_letter_reason == unknown_reason
        assert recoveries == []
        assert drained["external_calls"] == 0
        assert provider_calls == []


@pytest.mark.parametrize("live", [True, False], ids=["live", "expired"])
def test_raw_sendgrid_claim_cannot_be_closed_recovered_or_resent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    live: bool,
) -> None:
    boot = bootstrap_company(client)
    headers = auth_headers(str(boot["access_token"]))
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    provider_calls: list[str] = []

    def unexpected_send(**kwargs):
        provider_calls.append(str(kwargs))
        return True, "unexpected-provider-id", None

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        unexpected_send,
    )
    factory = get_session_factory()
    with factory() as session:
        context = _context(session)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id=f"raw-sendgrid-claim-{int(live)}",
            title="Sensitive title",
            body="Sensitive body",
        )
        assert intent is not None
        marker = f"{NOTIFICATION_DISPATCH_CLAIM_PREFIX}raw-{int(live)}"
        intent.status = "sent"
        intent.provider_event_id = marker
        intent.dispatch_owner = "provider_claim"
        intent.next_attempt_at = datetime.now(UTC) + (
            timedelta(minutes=5) if live else -timedelta(seconds=1)
        )
        session.add(intent)
        session.commit()
        intent_id = intent.id

    operation_id = f"notification_delivery:{intent_id}"
    expected_code = (
        NOTIFICATION_DISPATCH_CLAIM_IN_FLIGHT_CODE
        if live
        else NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_CODE
    )
    exact = client.get(
        f"/api/admin/provider-operations/jobs/{operation_id}",
        headers=headers,
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["ignore_available"] is False
    assert exact.json()["mark_resolved_available"] is False
    assert exact.json()["replay_available"] is False
    assert exact.json()["manual_reconciliation_required"] is (not live)
    assert exact.json()["automatic_replay_block_code"] == expected_code

    preview = client.post(
        "/api/admin/provider-operations/jobs/replay-preview",
        headers=headers,
        json={"operation_ids": [operation_id]},
    )
    assert preview.status_code == 409, preview.text
    assert preview.json()["code"] == expected_code
    for action in ("ignore", "mark-resolved"):
        denied = client.post(
            f"/api/admin/provider-operations/jobs/{operation_id}/{action}",
            headers=headers,
            json={"reason": "Preserve the ambiguous SendGrid receipt fence."},
        )
        assert denied.status_code == 409, denied.text
        assert denied.json()["code"] == expected_code
    recovered = client.post(
        f"/api/admin/notifications/intents/{intent_id}/recover",
        headers=headers,
        json={"recovery_action": "Provider configuration repaired and retry approved"},
    )
    assert recovered.status_code == 409, recovered.text
    assert recovered.json()["code"] == expected_code

    with factory() as session:
        # A webhook can be retained as evidence but cannot overwrite either
        # the raw in-flight marker or the materialized UNKNOWN state.
        assert apply_notification_provider_event(
            session,
            event={
                "event": "delivered",
                "notification_intent_id": intent_id,
                "sg_event_id": f"raw-stale-{int(live)}",
            },
        )
        session.commit()
        drained = drain_notification_delivery_intents(session, limit=10)
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert intent is not None
        if live:
            assert intent.status == "sent"
            assert intent.provider_event_id == marker
            assert intent.dead_letter_reason is None
        else:
            assert intent.status == "dead_letter"
            assert intent.dead_letter_reason == (
                "dispatch_claim_expired_provider_outcome_unknown"
            )
        assert drained["external_calls"] == 0
        assert provider_calls == []


def test_sendgrid_deferred_is_provider_audit_only_and_never_resubmitted(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_company(client)
    settings = get_settings()
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    provider_calls: list[str] = []

    def accepted(**kwargs):
        provider_calls.append(str(kwargs["custom_args"]["notification_intent_id"]))
        return True, "sg-deferred-accepted", None

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        accepted,
    )
    factory = get_session_factory()
    with factory() as session:
        context = _context(session)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=context.membership,
            channel="email",
            event_type="hearing_upcoming",
            source_type="hearing_reminder",
            source_id="sendgrid-deferred-no-resubmit",
            title="Sensitive title",
            body="Sensitive body",
        )
        assert intent is not None
        first = process_notification_delivery_intent(
            session,
            intent_id=intent.id,
            context=context,
        )
        assert first.status == "sent" and first.external_calls == 1
        assert apply_notification_provider_event(
            session,
            event={
                "event": "deferred",
                "notification_intent_id": intent.id,
                "sg_message_id": "sg-deferred-accepted.filter",
                "sg_event_id": "sg-deferred-event-1",
                "reason": "temporary remote mailbox delay",
            },
        )
        session.commit()
        drained = drain_notification_delivery_intents(session, limit=10)
        session.refresh(intent)
        assert intent.status == "sent"
        assert intent.provider_event_id == "sg-deferred-accepted"
        assert intent.next_attempt_at is None
        assert drained["external_calls"] == 0
        assert provider_calls == [intent.id]
        deferred_event = session.scalar(
            select(NotificationDeliveryEvent).where(
                NotificationDeliveryEvent.intent_id == intent.id,
                NotificationDeliveryEvent.event_type == "provider_deferred",
            )
        )
        assert deferred_event is not None
        assert deferred_event.applied_to_state is False


@pytest.mark.parametrize("order", ["legacy_first", "intent_first"])
def test_linked_hearing_reminder_sends_once_through_canonical_intent_in_either_order(
    client: TestClient,
    monkeypatch,
    order: str,
) -> None:
    boot = bootstrap_company(client)
    token = str(boot["access_token"])
    settings = get_settings()
    monkeypatch.setattr(settings, "hearing_reminders_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_enabled", True)
    monkeypatch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
    monkeypatch.setattr(settings, "sendgrid_api_key", "test-key")
    monkeypatch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
    matter = _matter(client, token, f"REMINDER-{order.replace('_', '-')}")
    hearing = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=auth_headers(token),
        json={
            "hearing_on": (datetime.now(UTC) + timedelta(days=4)).date().isoformat(),
            "forum_name": "Delhi High Court",
            "purpose": "Canonical reminder delivery",
            "reminder_channels": ["email"],
            "reminder_offsets_hours": [24],
            "notification_critical": False,
        },
    )
    assert hearing.status_code == 200, hearing.text
    hearing_id = hearing.json()["id"]
    factory = get_session_factory()
    with factory() as session:
        reminder = session.scalar(
            select(HearingReminder).where(HearingReminder.hearing_id == hearing_id)
        )
        assert reminder is not None
        primary_link = session.scalar(
            select(HearingReminderDeliveryIntent).where(
                HearingReminderDeliveryIntent.hearing_reminder_id == reminder.id,
                HearingReminderDeliveryIntent.is_primary.is_(True),
            )
        )
        assert primary_link is not None
        intent = session.get(NotificationDeliveryIntent, primary_link.intent_id)
        assert intent is not None
        due_at = datetime.now(UTC) - timedelta(minutes=1)
        reminder.scheduled_for = due_at
        intent.scheduled_for = due_at
        session.commit()
        reminder_id = reminder.id
        intent_id = intent.id

    external_calls: list[str] = []
    worker_session_ref: list = []

    def canonical_send(**kwargs):
        assert worker_session_ref
        assert worker_session_ref[0].in_transaction() is False
        external_calls.append(str(kwargs["custom_args"]["notification_intent_id"]))
        return True, "sendgrid-canonical-hearing-1", None

    def legacy_send_forbidden(**_kwargs):  # pragma: no cover - assertion boundary
        raise AssertionError("legacy hearing reminder attempted direct provider I/O")

    monkeypatch.setattr(
        "caseops_api.services.communications._send_via_sendgrid",
        canonical_send,
    )
    monkeypatch.setattr(
        "caseops_api.services.hearing_reminders._send_via_sendgrid",
        legacy_send_forbidden,
    )
    monkeypatch.setattr(
        "caseops_api.services.hearing_reminders._send_via_twilio_sms",
        legacy_send_forbidden,
    )

    with factory() as session:
        worker_session_ref.append(session)
        if order == "legacy_first":
            legacy = run_reminder_worker(session, mode="live", limit=10)
            assert legacy["delegated_to_durable_intent"] == 1
            drained = drain_notification_delivery_intents(session, limit=10)
        else:
            drained = drain_notification_delivery_intents(session, limit=10)
            legacy = run_reminder_worker(session, mode="live", limit=10)
            assert legacy["due_count"] == 0
        assert drained["external_calls"] == 1

    assert external_calls == [intent_id]
    with factory() as session:
        reminder = session.get(HearingReminder, reminder_id)
        intent = session.get(NotificationDeliveryIntent, intent_id)
        assert reminder is not None and intent is not None
        assert reminder.status == "sent"
        assert reminder.provider_message_id == "sendgrid-canonical-hearing-1"
        assert intent.status == "sent"
        assert intent.provider_event_id == "sendgrid-canonical-hearing-1"
