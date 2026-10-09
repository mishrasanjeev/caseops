from __future__ import annotations

import smtplib
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text

from caseops_api.core.rate_limit import limiter
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingAdminNote, BillingEnrollment, PlatformAdminAuditEvent
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest
from caseops_api.services import billing_demo
from tests.test_auth_company import auth_headers, bootstrap_company

URL = "/api/billing/enrollments/demo-request"
REAL_SEND_NOTIFICATION = billing_demo._send_notification


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def demo_client(request):
    return request.getfixturevalue(request.param)


@pytest.fixture(autouse=True)
def offline_notifications(monkeypatch):
    sent = []
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: True)
    monkeypatch.setattr(billing_demo, "_retention_enabled", lambda: True)
    monkeypatch.setattr(billing_demo, "_send_notification", sent.append)
    return sent


@pytest.mark.parametrize("port", [465, 587])
def test_seo_demo_20261009_smtp_tls_verifies_peer(monkeypatch, port):
    contexts, messages = [], []
    monkeypatch.setenv("CASEOPS_SMTP_USER", "offline@example.com")
    monkeypatch.setenv("CASEOPS_SMTP_PASSWORD", "offline-fake-password")
    monkeypatch.setenv("CASEOPS_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("CASEOPS_SMTP_PORT", str(port))

    class Transport:
        def __init__(self, host, actual_port, *, timeout, context=None):
            assert host == "smtp.example.com" and actual_port == port and timeout == 8
            if context:
                contexts.append(context)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def starttls(self, *, context):
            contexts.append(context)

        def login(self, user, password):
            assert user == "offline@example.com" and password == "offline-fake-password"
            assert contexts

        def send_message(self, message):
            messages.append(message.as_string())

    monkeypatch.setattr(smtplib, "SMTP_SSL", Transport)
    monkeypatch.setattr(smtplib, "SMTP", Transport)
    REAL_SEND_NOTIFICATION(str(uuid4()))
    assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED and contexts[0].check_hostname
    assert "offline-fake-password" not in messages[0]
    assert "demo@example.com" not in messages[0]


def test_seo_demo_20261009_failed_tls_never_sends_credentials(monkeypatch):
    monkeypatch.setenv("CASEOPS_SMTP_USER", "offline@example.com")
    monkeypatch.setenv("CASEOPS_SMTP_PASSWORD", "offline-fake-password")
    monkeypatch.setenv("CASEOPS_SMTP_PORT", "465")

    def reject(*args, **kwargs):
        assert kwargs["context"].verify_mode == ssl.CERT_REQUIRED
        raise ssl.SSLCertVerificationError("offline certificate rejection")

    monkeypatch.setattr(smtplib, "SMTP_SSL", reject)
    with pytest.raises(ssl.SSLCertVerificationError):
        REAL_SEND_NOTIFICATION(str(uuid4()))


def test_seo_demo_20261009_retention_requires_review_and_excludes_legacy(demo_client, monkeypatch):
    identity = demo_client.post(URL, json=payload()).json()["id"]
    with get_session_factory()() as session:
        legacy = BillingEnrollment(
            contact_name="Legacy",
            contact_email="legacy@example.com",
            segment="solo",
            status="demo_requested",
            status_timestamps_json={"demo_admission": {"expires_at": "2000-01-01T00:00:00+00:00"}},
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    monkeypatch.setattr(billing_demo, "_now", lambda: datetime.now(UTC) + timedelta(days=91))
    monkeypatch.setattr(billing_demo, "_retention_enabled", lambda: False)
    assert billing_demo.purge_expired_demo_leads() == {"deleted": 0, "policy_enabled": False}
    assert get_row(identity) is not None
    monkeypatch.setattr(billing_demo, "_retention_enabled", lambda: True)
    assert billing_demo.purge_expired_demo_leads() == {"deleted": 1}
    assert get_row(identity) is None and get_row(legacy_id) is not None


def test_seo_demo_20261009_legacy_public_contract_is_unqualified(demo_client):
    data = {
        "contact_name": "Legacy Demo",
        "contact_email": "legacy@example.com",
        "segment": "firm",
        "contact_mobile": "5550000",
        "company_name": "Example Practice",
        "notes": "x" * 4000,
        "source": "https://x.test/?private=query",
    }
    response = demo_client.post(URL, json=data)
    assert response.status_code == 200, response.text
    row = get_row(response.json()["id"])
    assert row.notes == data["notes"] and row.contact_mobile == data["contact_mobile"]
    assert row.source == "legacy_api"
    assert row.utm_json == {
        "entry_point": "legacy_api",
        "role": "not_specified",
        "intent": "not_specified",
        "privacy_notice_version": None,
        "attribution_qualified": False,
    }
    assert billing_demo._state(row)["contract_version"] == "legacy_public_demo_v1"
    assert billing_demo._state(row)["expires_at"] is None


def test_seo_demo_20261009_retention_preserves_billing_notes(demo_client, monkeypatch):
    identity = demo_client.post(URL, json=payload()).json()["id"]
    with get_session_factory()() as session:
        session.add(BillingAdminNote(enrollment_id=identity, body="Retained commercial context"))
        session.commit()
    monkeypatch.setattr(billing_demo, "_now", lambda: datetime.now(UTC) + timedelta(days=91))
    assert billing_demo.purge_expired_demo_leads() == {"deleted": 0}
    assert get_row(identity) is not None


def test_seo_demo_20261009_sender_approval_stays_closed(
    demo_client, monkeypatch, offline_notifications
):
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: False)
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200
    state = billing_demo._state(get_row(response.json()["id"]))
    assert state["notification_status"] == "pending"
    assert state["last_error_code"] == "sender_approval_pending"
    assert state["attempts"] == 0 and offline_notifications == []


def test_seo_demo_20261009_existing_scheduler_drains_without_visitor(
    demo_client, monkeypatch, offline_notifications, capsys
):
    from caseops_api.scripts import send_hearing_reminders

    monkeypatch.setattr(send_hearing_reminders, "run_reminder_worker", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        send_hearing_reminders, "drain_notification_delivery_intents", lambda *args, **kwargs: {}
    )
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: False)
    identity = demo_client.post(URL, json=payload()).json()["id"]
    state = billing_demo._state(get_row(identity))
    future = datetime.fromisoformat(state["next_attempt_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(billing_demo, "_now", lambda: future)
    assert send_hearing_reminders.run(mode="dry_run") == 0
    assert offline_notifications == []
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: True)
    assert send_hearing_reminders.run(mode="auto") == 0
    assert offline_notifications == [identity]
    assert '"selected": 1' in capsys.readouterr().out


def payload(**changes):
    return {
        "contact_name": "Demo Advocate",
        "contact_email": "demo@example.com",
        "company_name": "Example Practice",
        "segment": "solo",
        "role": "solo_advocate",
        "intent": "pilot",
        "source": "solo_lawyers",
        "privacy_notice_version": "2026-10-09",
        "idempotency_key": str(uuid4()),
        **changes,
    }


def get_row(identity):
    with get_session_factory()() as session:
        return session.get(BillingEnrollment, identity)


def test_seo_demo_20261009_commit_before_notification_and_ack(demo_client, monkeypatch):
    data = payload()
    observed = []

    def transport(identity):
        row = get_row(identity)
        assert row and row.contact_email == data["contact_email"]
        assert row.status_timestamps_json["demo_admission"]["notification_status"] == "sending"
        observed.append(identity)

    monkeypatch.setattr(billing_demo, "_send_notification", transport)
    response = demo_client.post(URL, json=data)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": data["idempotency_key"], "status": "demo_requested"}
    row = get_row(response.json()["id"])
    assert observed == [row.id]
    assert row.company_id is None
    assert row.utm_json == {
        "entry_point": "solo_lawyers",
        "role": "solo_advocate",
        "intent": "pilot",
        "privacy_notice_version": "2026-10-09",
        "attribution_qualified": True,
    }


@pytest.mark.parametrize(
    "error,code",
    [
        (smtplib.SMTPException("redact provider PII"), "smtp_failure"),
        (TimeoutError("redact provider PII"), "timeout"),
    ],
)
def test_seo_demo_20261009_smtp_failure_and_timeout_preserve_lead(
    demo_client, monkeypatch, error, code, caplog
):
    def failing(_):
        raise error

    monkeypatch.setattr(billing_demo, "_send_notification", failing)
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200
    row = get_row(response.json()["id"])
    state = row.status_timestamps_json["demo_admission"]
    assert row.status == "demo_requested" and row.contact_email == "demo@example.com"
    assert state["notification_status"] == "retry_pending" and state["last_error_code"] == code
    assert state["attempts"] == 1
    assert "redact provider PII" not in caplog.text and "demo@example.com" not in caplog.text
    sent = []
    monkeypatch.setattr(billing_demo, "_send_notification", sent.append)
    future = datetime.fromisoformat(state["next_attempt_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(billing_demo, "_now", lambda: future)
    assert billing_demo.drain_demo_notifications() == {"selected": 1}
    assert sent == [row.id]
    assert get_row(row.id).status_timestamps_json["demo_admission"]["notification_status"] == "sent"


def test_seo_demo_20261009_duplicate_same_key_and_conflicting_key(
    demo_client, offline_notifications
):
    data = payload()
    first, second = demo_client.post(URL, json=data), demo_client.post(URL, json=data)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert offline_notifications == [data["idempotency_key"]]
    conflict = demo_client.post(URL, json={**data, "role": "partner"})
    assert conflict.status_code == 409
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"source": "https://example.com/private?email=secret"},
        {"segment": "invented"},
        {"role": "platform_admin"},
        {"contact_name": "  "},
        {"contact_email": "invalid"},
        {"idempotency_key": "not-a-uuid"},
        {"utm_json": {"url": "secret"}},
        {"referrer": "secret"},
        {"privacy_notice_version": "invented"},
        {"idempotency_key": 42},
        {"privacy_notice_version": None},
        {"role": "not_specified"},
        {"notes": "x" * 1001},
    ],
)
def test_seo_demo_20261009_validation_never_admits_or_notifies(
    demo_client, offline_notifications, changes
):
    response = demo_client.post(URL, json=payload(**changes))
    assert response.status_code == 422, response.text
    assert offline_notifications == []
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 0


def test_seo_demo_20261009_rate_limit_rejects_sixth_admission(demo_client, monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    responses = [
        demo_client.post(URL, json=payload(), headers={"x-forwarded-for": "192.0.2.79"})
        for _ in range(6)
    ]
    assert [row.status_code for row in responses] == [200] * 5 + [429]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 5


def test_seo_demo_20261009_crash_attempt_limit_is_bounded(demo_client, offline_notifications):
    identity = demo_client.post(URL, json=payload()).json()["id"]
    offline_notifications.clear()
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        state = billing_demo._state(row)
        state.update(
            notification_status="sending",
            attempts=billing_demo.MAX_ATTEMPTS,
            lease_until="2000-01-01T00:00:00+00:00",
            next_attempt_at="2000-01-01T00:00:00+00:00",
        )
        billing_demo._save(row, state)
        session.commit()
    billing_demo.drain_demo_notifications()
    assert offline_notifications == []
    assert billing_demo._state(get_row(identity))["notification_status"] == "exhausted"


def test_seo_demo_20261009_admin_readback_retry_delete_are_audited(demo_client, monkeypatch):
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    token = str(bootstrap_company(demo_client)["access_token"])

    def failing(_):
        raise TimeoutError()

    monkeypatch.setattr(billing_demo, "_send_notification", failing)
    identity = demo_client.post(URL, json=payload()).json()["id"]
    response = demo_client.get("/api/platform-admin/enrollments", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["enrollments"] if row["id"] == identity)
    assert row["attribution"]["role"] == "solo_advocate"
    assert row["source"] == "solo_lawyers"
    assert row["demo_notification"]["last_error_code"] == "timeout"
    assert "request_sha256" not in response.text and "claim" not in response.text
    sent = []
    monkeypatch.setattr(billing_demo, "_send_notification", sent.append)
    retry = demo_client.post(
        f"/api/platform-admin/enrollments/{identity}/retry-notification",
        headers=auth_headers(token),
        json={"reason": "Retry local fake transport"},
    )
    assert retry.status_code == 200, retry.text
    assert sent == [identity]
    deleted = demo_client.request(
        "DELETE",
        f"/api/platform-admin/enrollments/{identity}",
        headers=auth_headers(token),
        json={"reason": "Contact requested deletion"},
    )
    assert deleted.status_code == 200, deleted.text
    assert get_row(identity) is None
    with get_session_factory()() as session:
        actions = set(session.scalars(select(PlatformAdminAuditEvent.action)))
        assert {
            "platform.enrollments.viewed",
            "platform.demo_notification.retry_requested",
            "platform.demo_enrollment.deleted",
        } <= actions


def test_seo_demo_20261009_anonymous_and_tenant_admin_cannot_read_leads(demo_client):
    identity = demo_client.post(URL, json=payload()).json()["id"]
    assert demo_client.get("/api/platform-admin/enrollments").status_code == 401
    token = str(bootstrap_company(demo_client)["access_token"])
    assert (
        demo_client.get("/api/platform-admin/enrollments", headers=auth_headers(token)).status_code
        == 403
    )
    assert (
        demo_client.request(
            "DELETE",
            f"/api/platform-admin/enrollments/{identity}",
            headers=auth_headers(token),
            json={"reason": "Forbidden deletion"},
        ).status_code
        == 403
    )
    assert get_row(identity) is not None


def test_seo_demo_20261009_expired_claim_recovers_and_retention_preserves_converted(
    demo_client, monkeypatch
):
    identity = demo_client.post(URL, json=payload()).json()["id"]
    now = datetime.now(UTC)
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        state = billing_demo._state(row)
        state.update(
            notification_status="sending",
            lease_until=(now - timedelta(seconds=1)).isoformat(),
            claim="abandoned",
            next_attempt_at=now.isoformat(),
        )
        billing_demo._save(row, state)
        session.commit()
    monkeypatch.setattr(billing_demo, "_now", lambda: now + timedelta(seconds=1))
    assert billing_demo.drain_demo_notifications() == {"selected": 1}
    assert (
        get_row(identity).status_timestamps_json["demo_admission"]["notification_status"] == "sent"
    )
    converted = demo_client.post(URL, json=payload()).json()["id"]
    with get_session_factory()() as session:
        session.get(BillingEnrollment, converted).status = "converted"
        session.commit()
    monkeypatch.setattr(billing_demo, "_now", lambda: now + timedelta(days=91))
    assert billing_demo.purge_expired_demo_leads() == {"deleted": 1}
    assert get_row(identity) is None and get_row(converted) is not None


@pytest.mark.postgres
def test_seo_demo_20261009_postgres_duplicate_race(isolated_postgres_client):
    data = DemoRequest(**payload())

    def admit(_):
        with get_session_factory()() as session:
            return billing_demo.admit_demo(session, data)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(admit, range(2)))
    assert responses[0] == responses[1]
    with get_session_factory()() as session:
        assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 1


@pytest.mark.postgres
def test_seo_demo_20261009_postgres_transport_releases_row_lock(
    isolated_postgres_client, monkeypatch
):
    observed = []

    def transport(identity):
        with get_session_factory()() as session:
            session.execute(text("SET LOCAL lock_timeout = '250ms'"))
            row = session.scalar(
                select(BillingEnrollment)
                .where(BillingEnrollment.id == identity)
                .with_for_update(nowait=True)
            )
            assert (
                row
                and row.status_timestamps_json["demo_admission"]["notification_status"] == "sending"
            )
            observed.append(identity)

    monkeypatch.setattr(billing_demo, "_send_notification", transport)
    response = isolated_postgres_client.post(URL, json=payload())
    assert response.status_code == 200
    assert observed == [response.json()["id"]]
