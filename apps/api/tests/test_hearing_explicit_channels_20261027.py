"""Explicit hearing opt-out survives producers, old queues and uncertain claims.

All wire positives reach the unchanged SendGrid HTTP function through an owned,
fixed-URL offline HTTPTransport. They are not provider/inbox delivery evidence.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from caseops_api.core.automated_test_context import (
    paid_providers_blocked_for_request,
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingReminder,
    InAppNotification,
    Matter,
    MatterHearing,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import notification_delivery as delivery
from caseops_api.services.hearing_channel_policy import (
    explicit_hearing_channel_allowed,
    hearing_channels,
)
from caseops_api.services.hearing_reminders import schedule_reminders_for_hearing
from caseops_api.services.session_context import SessionContext
from tests.test_auth_company import auth_headers, bootstrap_company

MARKER = {"X-CaseOps-Automated-Test": "no-paid-providers"}


@pytest.fixture(autouse=True)
def forbid_unadmitted_network(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("UNADMITTED_HTTP_TRANSPORT")

    async def forbidden_async(*_args, **_kwargs):
        raise AssertionError("UNADMITTED_ASYNC_HTTP_TRANSPORT")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden_async)


@contextmanager
def offline_wire(monkeypatch, *, on_call=None, session=None):
    settings = get_settings()
    assert settings.env == "local"
    url = make_url(settings.database_url)
    assert url.get_backend_name() == "sqlite" or (
        url.get_backend_name() == "postgresql" and url.host in {"127.0.0.1", "localhost"}
    )
    calls = []
    token = set_automated_test_request("no-paid-providers")
    with monkeypatch.context() as patch:
        patch.setattr(settings, "notification_external_delivery_enabled", True)
        patch.setattr(settings, "notification_external_delivery_provider", "sendgrid")
        patch.setattr(settings, "sendgrid_api_key", "synthetic-offline-key")
        patch.setattr(settings, "sendgrid_sender_email", "sender@example.test")
        patch.setattr(settings, "hearing_reminder_offsets_hours", [24, 1])

        def wire(_transport, request):
            assert paid_providers_blocked_for_request() is True
            assert str(request.url) == "https://api.sendgrid.com/v3/mail/send"
            assert request.method == "POST"
            assert request.headers["Authorization"] == "Bearer synthetic-offline-key"
            if session is not None:
                assert not session.in_transaction()
            body = json.loads(request.content)
            assert body["subject"] == "CaseOps notification"
            assert body["content"] == [
                {
                    "type": "text/plain",
                    "value": "Open CaseOps to review this notification securely.",
                }
            ]
            calls.append(body)
            if on_call is not None:
                on_call()
            return httpx.Response(
                202, headers={"X-Message-Id": "offline-accepted"}, request=request
            )

        patch.setattr(httpx.HTTPTransport, "handle_request", wire)
        try:
            yield calls
        finally:
            reset_automated_test_request(token)


def seed_hearing(client):
    boot = bootstrap_company(client)
    headers = {**auth_headers(boot["access_token"]), **MARKER}
    response = client.post(
        "/api/matters/",
        headers=headers,
        json={
            "title": "Synthetic channel boundary",
            "matter_code": "CHANNEL-EMPTY",
            "practice_area": "commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    assert response.status_code == 200, response.text
    matter = response.json()
    response = client.post(
        f"/api/matters/{matter['id']}/hearings",
        headers=headers,
        json={
            "hearing_on": (datetime.now(UTC) + timedelta(days=45)).date().isoformat(),
            "forum_name": "Synthetic forum",
            "purpose": "Synthetic hearing",
            "timezone": "Asia/Kolkata",
            "time_status": "time_not_published",
            "expected_lifecycle_version": matter["lifecycle_version"],
            "reminder_channels": [],
            "notification_critical": False,
            "reminder_offsets_hours": [24, 1],
        },
    )
    assert response.status_code == 200, response.text
    hearing = response.json()
    assert hearing["reminder_policy"]["channels"] == []
    assert hearing["reminder_policy"]["critical"] is False
    return boot, headers, matter, hearing


def context(session, boot):
    return SessionContext(
        company=session.get(Company, boot["company"]["id"]),
        user=session.get(User, boot["user"]["id"]),
        membership=session.get(CompanyMembership, boot["membership"]["id"]),
    )


def snapshot(session, hearing_id):
    reminders = list(
        session.execute(
            select(*HearingReminder.__table__.c)
            .where(HearingReminder.hearing_id == hearing_id)
            .order_by(HearingReminder.id)
        ).mappings()
    )
    intents = list(
        session.execute(
            select(*NotificationDeliveryIntent.__table__.c)
            .where(
                NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
                NotificationDeliveryIntent.schedule_source_id == hearing_id,
            )
            .order_by(NotificationDeliveryIntent.id)
        ).mappings()
    )
    identities = [row["source_id"] for row in intents]
    visible = (
        list(
            session.scalars(
                select(InAppNotification.id).where(
                    InAppNotification.source_type == "hearing_reminder",
                    InAppNotification.source_id.in_(identities),
                )
            )
        )
        if identities
        else []
    )
    return {"reminders": reminders, "intents": intents, "visible": visible}


def set_policy(session, hearing_id, policy):
    observed = session.get(MatterHearing, hearing_id)
    assert observed is not None
    # Follow the same parent -> child order as the current hearing writers.
    session.scalar(select(Matter).where(Matter.id == observed.matter_id).with_for_update())
    hearing = session.scalar(
        select(MatterHearing)
        .where(MatterHearing.id == hearing_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    hearing.reminder_policy_json = policy
    session.commit()


def retained_intent(session, boot, matter, hearing, *, channel="email", status="queued"):
    set_policy(session, hearing["id"], None)
    actor = context(session, boot)
    intent = delivery.enqueue_notification_delivery_intent(
        session,
        context=actor,
        recipient_membership=actor.membership,
        matter=session.get(Matter, matter["id"]),
        channel=channel,
        event_type="hearing_upcoming",
        source_type="hearing_reminder",
        source_id=str(uuid4()),
        title="Synthetic retained notification",
        body="Open CaseOps.",
        critical=False,
        schedule_source_type="matter_hearing",
        schedule_source_id=hearing["id"],
        scheduled_for=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert intent is not None
    intent.status = status
    intent.attempts = 1 if status == "retry_scheduled" else 0
    intent.next_attempt_at = (
        datetime.now(UTC) - timedelta(seconds=1) if status == "retry_scheduled" else None
    )
    session.commit()
    set_policy(session, hearing["id"], {"channels": [], "critical": False})
    return intent.id


@pytest.mark.parametrize(
    "policy,expected",
    [
        (None, ("email",)),
        ({}, ("email",)),
        ({"channels": None}, ("email",)),
        ({"channels": []}, ()),
        ({"channels": ["in_app"]}, ("in_app",)),
    ],
)
def test_channel_parser_distinguishes_absent_legacy_and_explicit_choice(policy, expected):
    assert hearing_channels(policy) == expected
    assert explicit_hearing_channel_allowed(policy, "email") is (expected == ("email",))


@pytest.mark.parametrize(
    "policy",
    [
        [],
        "",
        False,
        0,
        {"channels": False},
        {"channels": "email"},
        {"channels": ["email", "email"]},
        {"channels": ["push"]},
    ],
)
def test_invalid_explicit_policy_is_closed(policy):
    with pytest.raises(ValueError):
        hearing_channels(policy)
    assert explicit_hearing_channel_allowed(policy, "email") is False
    assert explicit_hearing_channel_allowed(policy, "in_app") is False


def empty_http_roundtrip(client, monkeypatch):
    boot, headers, matter, hearing = seed_hearing(client)
    with offline_wire(monkeypatch) as calls:
        with get_session_factory()() as session:
            assert snapshot(session, hearing["id"]) == {
                "reminders": [],
                "intents": [],
                "visible": [],
            }
            repeat = schedule_reminders_for_hearing(
                session, hearing=session.get(MatterHearing, hearing["id"])
            )
            session.commit()
            assert repeat == []
        response = client.patch(
            f"/api/matters/{matter['id']}/hearings/{hearing['id']}",
            headers=headers,
            json={
                "hearing_on": (datetime.now(UTC) + timedelta(days=60)).date().isoformat(),
                "expected_lifecycle_version": matter["lifecycle_version"],
                "expected_record_version": hearing["record_version"],
            },
        )
        assert response.status_code == 200, response.text
        with get_session_factory()() as session:
            assert snapshot(session, hearing["id"]) == {
                "reminders": [],
                "intents": [],
                "visible": [],
            }
        assert calls == []


def test_empty_http_plan_repeat_and_reschedule_create_zero_reminders_and_intents(
    client, monkeypatch
):
    empty_http_roundtrip(client, monkeypatch)


def legacy_positive(client, monkeypatch, policy):
    boot, _headers, _matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            set_policy(session, hearing["id"], policy)
            created = schedule_reminders_for_hearing(
                session, hearing=session.get(MatterHearing, hearing["id"])
            )
            session.commit()
            assert len(created) == 2
            intents = list(
                session.scalars(
                    select(NotificationDeliveryIntent).where(
                        NotificationDeliveryIntent.schedule_source_id == hearing["id"],
                        NotificationDeliveryIntent.channel == "email",
                    )
                )
            )
            assert len(intents) == 2
            intent = intents[0]
            intent.scheduled_for = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
            result = delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, context=context(session, boot)
            )
            session.commit()
            assert result.status == "sent"  # Provider acceptance, not inbox delivery.
            assert len(calls) == 1
            assert calls[0]["personalizations"][0]["custom_args"] == {
                "notification_intent_id": intent.id
            }
            again = delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, context=context(session, boot)
            )
            assert again.status == "sent" and len(calls) == 1


@pytest.mark.parametrize("policy", [None, {}])
def test_legacy_absent_policy_reaches_actual_offline_wire_once(client, monkeypatch, policy):
    legacy_positive(client, monkeypatch, policy)


def retained_queue(client, monkeypatch, channel, status):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            intent_id = retained_intent(
                session, boot, matter, hearing, channel=channel, status=status
            )
            before = session.get(NotificationDeliveryIntent, intent_id).attempts
            result = delivery.process_notification_delivery_intent(
                session, intent_id=intent_id, context=context(session, boot)
            )
            session.commit()
            row = session.get(NotificationDeliveryIntent, intent_id)
            assert (
                result.status == "blocked"
                and row.dead_letter_reason == "hearing_channel_not_requested"
            )
            assert row.attempts == before and row.fallback_intent_id is None and calls == []
            blocked = snapshot(session, hearing["id"])
            assert blocked["visible"] == []
            set_policy(session, hearing["id"], {"channels": ["email", "in_app"], "critical": True})
            again = delivery.process_notification_delivery_intent(
                session, intent_id=intent_id, context=context(session, boot)
            )
            actor = context(session, boot)
            retained = session.get(NotificationDeliveryIntent, intent_id)
            replayed_admission = delivery.enqueue_notification_delivery_intent(
                session,
                context=actor,
                recipient_membership=actor.membership,
                matter=session.get(Matter, matter["id"]),
                channel=channel,
                event_type=retained.event_type,
                source_type=retained.source_type,
                source_id=retained.source_id,
                schedule_source_type="matter_hearing",
                schedule_source_id=hearing["id"],
            )
            session.commit()
            assert again.status == "blocked" and calls == []
            assert replayed_admission.id == intent_id and replayed_admission.status == "blocked"
            assert snapshot(session, hearing["id"]) == blocked


@pytest.mark.parametrize(
    "channel,status", [("email", "queued"), ("email", "retry_scheduled"), ("in_app", "queued")]
)
def test_retained_disabled_channels_block_without_attempt_or_reactivation(
    client, monkeypatch, channel, status
):
    retained_queue(client, monkeypatch, channel, status)


def terminal_and_claim(client, monkeypatch, state):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            intent_id = retained_intent(session, boot, matter, hearing)
            row = session.get(NotificationDeliveryIntent, intent_id)
            row.status = "delivered" if state == "delivered" else "sent"
            row.attempts = 1
            row.provider_event_id = (
                "provider-accepted"
                if state in {"sent", "delivered"}
                else delivery.NOTIFICATION_DISPATCH_CLAIM_PREFIX + "a" * 32
            )
            row.next_attempt_at = (
                (
                    datetime.now(UTC) + timedelta(minutes=1)
                    if state == "live"
                    else datetime.now(UTC) - timedelta(seconds=1)
                )
                if state in {"live", "expired"}
                else None
            )
            session.commit()
            before = snapshot(session, hearing["id"])
            result = delivery.process_notification_delivery_intent(
                session, intent_id=intent_id, context=context(session, boot)
            )
            session.commit()
            after = snapshot(session, hearing["id"])
            if state == "expired":
                assert result.status == "dead_letter"
                assert (
                    after["intents"][0]["dead_letter_reason"]
                    == "dispatch_claim_expired_provider_outcome_unknown"
                )
                assert after["intents"][0]["attempts"] == 1
                assert after["intents"][0]["fallback_intent_id"] is None
                assert len(after["intents"]) == 1 and after["visible"] == []
            else:
                assert after == before
            assert calls == []


@pytest.mark.parametrize("state", ["sent", "delivered", "live", "expired"])
def test_optout_preserves_accepted_or_uncertain_claim_state_without_new_fallback(
    client, monkeypatch, state
):
    terminal_and_claim(client, monkeypatch, state)


def timeout_then_optout(client, monkeypatch):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:

        def provider_boundary():
            # The claim already committed before I/O; a later opt-out does not
            # prove the provider failed to accept that in-flight disclosure.
            with get_session_factory()() as writer:
                set_policy(writer, hearing["id"], {"channels": [], "critical": False})
            raise httpx.ReadTimeout("Read timed out after synthetic provider dispatch")

        with offline_wire(monkeypatch, on_call=provider_boundary, session=session) as calls:
            set_policy(session, hearing["id"], {"channels": ["email"], "critical": False})
            actor = context(session, boot)
            intent = delivery.enqueue_notification_delivery_intent(
                session,
                context=actor,
                recipient_membership=actor.membership,
                matter=session.get(Matter, matter["id"]),
                channel="email",
                event_type="hearing_upcoming",
                source_type="hearing_reminder",
                source_id=str(uuid4()),
                title="Synthetic notice",
                body="Open CaseOps.",
                critical=False,
                schedule_source_type="matter_hearing",
                schedule_source_id=hearing["id"],
            )
            assert intent is not None
            session.commit()
            result = delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, context=actor
            )
            session.commit()
            assert len(calls) == 1 and result.status == "dead_letter"
            row = session.get(NotificationDeliveryIntent, intent.id)
            assert (
                row.dead_letter_reason == "dispatch_provider_outcome_unknown" and row.attempts == 1
            )
            assert row.fallback_intent_id is None
            saved = snapshot(session, hearing["id"])
            assert len(saved["intents"]) == 1 and saved["visible"] == []
            again = delivery.process_notification_delivery_intent(
                session, intent_id=intent.id, context=actor
            )
            session.commit()
            assert again.status == "dead_letter" and len(calls) == 1


def test_optout_after_dispatch_keeps_unknown_provider_state_and_prevents_fallback(
    client, monkeypatch
):
    timeout_then_optout(client, monkeypatch)


@pytest.mark.parametrize("policy", [[], "", False, 0])
def test_falsy_invalid_raw_policy_is_not_rewritten_to_legacy_email(client, policy):
    _boot, _headers, _matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        set_policy(session, hearing["id"], policy)
        with pytest.raises(ValueError):
            schedule_reminders_for_hearing(
                session, hearing=session.get(MatterHearing, hearing["id"])
            )
        assert snapshot(session, hearing["id"]) == {"reminders": [], "intents": [], "visible": []}


def enqueue_fence(client, monkeypatch, *, provider_ready, channels):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            if not provider_ready:
                monkeypatch.setattr(get_settings(), "notification_external_delivery_enabled", False)
            set_policy(session, hearing["id"], {"channels": channels, "critical": False})
            actor = context(session, boot)
            intent = delivery.enqueue_notification_delivery_intent(
                session,
                context=actor,
                recipient_membership=actor.membership,
                matter=session.get(Matter, matter["id"]),
                channel="email",
                event_type="hearing_upcoming",
                source_type="hearing_reminder",
                source_id=str(uuid4()),
                title="Synthetic admission",
                body="Open CaseOps.",
                critical=True,
                schedule_source_type="matter_hearing",
                schedule_source_id=hearing["id"],
            )
            session.commit()
            saved = snapshot(session, hearing["id"])
            if not channels:
                assert intent is None and saved == {"reminders": [], "intents": [], "visible": []}
            else:
                assert intent is not None and intent.fallback_intent_id is None
                assert len(saved["intents"]) == 1 and saved["visible"] == []
                assert saved["intents"][0]["channel"] == "email"
                if provider_ready:
                    result = delivery.process_notification_delivery_intent(
                        session, intent_id=intent.id, context=actor
                    )
                    session.commit()
                    assert result.status == "sent" and len(calls) == 1
                else:
                    assert intent.status == "blocked" and calls == []


@pytest.mark.parametrize(
    "provider_ready,channels", [(True, []), (False, []), (True, ["email"]), (False, ["email"])]
)
def test_current_policy_fences_primary_critical_and_provider_disabled_companions(
    client, monkeypatch, provider_ready, channels
):
    enqueue_fence(client, monkeypatch, provider_ready=provider_ready, channels=channels)


def parent_fence(client, monkeypatch):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            set_policy(session, hearing["id"], None)
            actor = context(session, boot)
            parent = session.get(Matter, matter["id"])
            warmed = session.get(MatterHearing, hearing["id"])
            assert warmed.reminder_policy_json is None
            reached = []

            def before_parent_lock(orm):
                if (
                    reached
                    or orm.bind_mapper is not inspect(Matter)
                    or getattr(orm.statement, "_for_update_arg", None) is None
                ):
                    return
                reached.append(True)
                with Session(session.get_bind()) as writer:
                    set_policy(writer, hearing["id"], {"channels": [], "critical": False})
                assert warmed.reminder_policy_json is None  # Deliberately stale identity map.

            event.listen(session, "do_orm_execute", before_parent_lock)
            try:
                admitted = delivery.enqueue_notification_delivery_intent(
                    session,
                    context=actor,
                    recipient_membership=actor.membership,
                    matter=parent,
                    channel="email",
                    event_type="hearing_upcoming",
                    source_type="hearing_reminder",
                    source_id=str(uuid4()),
                    title="Synthetic fence",
                    body="Open CaseOps.",
                    critical=True,
                    schedule_source_type="matter_hearing",
                    schedule_source_id=hearing["id"],
                )
            finally:
                event.remove(session, "do_orm_execute", before_parent_lock)
            session.commit()
            assert reached == [True]
            assert admitted is None and calls == []
            assert snapshot(session, hearing["id"]) == {
                "reminders": [],
                "intents": [],
                "visible": [],
            }


def test_enqueue_checks_current_policy_after_actual_parent_fence_not_warmed_hearing(
    client, monkeypatch
):
    parent_fence(client, monkeypatch)


def missing_source(client, monkeypatch):
    boot, _headers, matter, hearing = seed_hearing(client)
    with get_session_factory()() as session:
        with offline_wire(monkeypatch, session=session) as calls:
            intent_id = retained_intent(session, boot, matter, hearing)
            intent = session.get(NotificationDeliveryIntent, intent_id)
            intent.schedule_source_id = str(uuid4())
            session.commit()
            result = delivery.process_notification_delivery_intent(
                session, intent_id=intent_id, context=context(session, boot)
            )
            session.commit()
            assert result.status == "blocked" and intent.attempts == 0 and calls == []
            assert intent.fallback_intent_id is None
            actor = context(session, boot)
            admitted = delivery.enqueue_notification_delivery_intent(
                session,
                context=actor,
                recipient_membership=actor.membership,
                matter=session.get(Matter, matter["id"]),
                channel="email",
                event_type="hearing_upcoming",
                source_type="hearing_reminder",
                source_id=str(uuid4()),
                critical=True,
                schedule_source_type="matter_hearing",
                schedule_source_id=str(uuid4()),
            )
            assert admitted is None


def test_missing_matched_hearing_is_not_a_legacy_null_policy(client, monkeypatch):
    missing_source(client, monkeypatch)
