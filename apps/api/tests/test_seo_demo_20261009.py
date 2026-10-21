from __future__ import annotations

import hashlib
import json
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import certifi
import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from sqlalchemy import func, select, text

from caseops_api.core.rate_limit import limiter
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingAdminNote, BillingEnrollment, PlatformAdminAuditEvent
from caseops_api.db.session import get_db_session, get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest
from caseops_api.services import billing_demo
from tests.fixtures_public_lead_transport import (
    drain_offline_lead_notifications,
    install_offline_lead_adapter,
    offline_lead_worker_context,
)
from tests.test_auth_company import auth_headers, bootstrap_company

URL = "/api/billing/enrollments/demo-request"
REAL_SEND_NOTIFICATION = billing_demo._send_notification


@pytest.fixture(
    params=["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def demo_client(request):
    client = request.getfixturevalue(request.param)
    client.headers["X-CaseOps-Automated-Test"] = "no-paid-providers"
    return client


@pytest.fixture
def offline_adapter(request, monkeypatch):
    yield install_offline_lead_adapter(request, monkeypatch)
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def offline_notifications(monkeypatch, offline_adapter):
    sent = []
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: True)
    monkeypatch.setattr(billing_demo, "_retention_enabled", lambda: True)
    monkeypatch.setattr(
        billing_demo, "_send_notification", lambda identity, **_: sent.append(identity)
    )
    return sent


def test_seo_demo_20261009_marked_offline_protocol_keeps_real_delivery_fences(
    demo_client, monkeypatch, offline_adapter
):
    monkeypatch.setattr(billing_demo, "_send_notification", REAL_SEND_NOTIFICATION)
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    assert_pending_notification(identity)
    assert offline_adapter["messages"] == []
    assert drain_offline_lead_notifications() == {"selected": 1}
    state = billing_demo._state(get_row(identity))
    assert state["automated_request"] is True
    assert state["notification_status"] == "sent" and state["attempts"] == 1
    assert len(offline_adapter["messages"]) == 1
    assert offline_adapter["messages"][0]["lead_id"] == identity


def test_seo_demo_20261009_http_admission_only_queues_until_worker(
    demo_client, monkeypatch, offline_adapter
):
    monkeypatch.setattr(billing_demo, "_send_notification", REAL_SEND_NOTIFICATION)
    details = payload()
    response = demo_client.post(URL, json=details)
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    before = billing_demo._state(get_row(identity))
    assert before["notification_status"] == "pending"
    assert before["attempts"] == 0
    assert "claim" not in before and "lease_until" not in before
    assert offline_adapter["messages"] == []
    replay = demo_client.post(URL, json=details)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == identity
    assert billing_demo._state(get_row(identity)) == before
    assert offline_adapter["messages"] == []
    assert before["automated_request"] is True
    assert drain_offline_lead_notifications() == {"selected": 1}
    delivered = billing_demo._state(get_row(identity))
    assert delivered["notification_status"] == "sent" and delivered["attempts"] == 1
    assert "claim" not in delivered and "lease_until" not in delivered
    assert [message["lead_id"] for message in offline_adapter["messages"]] == [identity]
    assert drain_offline_lead_notifications() == {"selected": 0}
    assert billing_demo._state(get_row(identity)) == delivered


@pytest.mark.parametrize(
    "name,value",
    [("K_SERVICE", "offline-refusal"), ("CASEOPS_PUBLIC_APP_URL", "https://example.com")],
)
def test_seo_demo_20261009_offline_protocol_refuses_unadmitted_runtime(
    demo_client, monkeypatch, offline_adapter, name, value
):
    monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    monkeypatch.setattr(billing_demo, "_send_notification", REAL_SEND_NOTIFICATION)
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200, response.text
    assert_pending_notification(response.json()["id"])
    assert offline_adapter["messages"] == []
    assert drain_offline_lead_notifications() == {"selected": 1}
    state = billing_demo._state(get_row(response.json()["id"]))
    assert state["automated_request"] is True
    assert state["notification_status"] == "exhausted"
    assert state["last_error_code"] == "test_transport_not_admitted"
    assert state["attempts"] == 0 and offline_adapter["messages"] == []


@pytest.mark.parametrize("accepted_status", [200, 202])
def test_seo_demo_20261009_sendgrid_tls_verifies_peer(client, monkeypatch, accepted_status):
    contexts, messages, calls, ca_files = [], [], [], []
    create_context = ssl.create_default_context

    def checked_context(*args, **kwargs):
        ca_files.append(kwargs.get("cafile"))
        return create_context(*args, **kwargs)

    def reject_network(*args, **kwargs):
        pytest.fail("SendGrid unit regression attempted an external connection")

    monkeypatch.setattr(ssl, "create_default_context", checked_context)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    monkeypatch.setattr(socket.socket, "connect", reject_network)
    for key in ("SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.com")
    get_settings.cache_clear()

    def transport(self, request):
        assert str(request.url) == "https://api.sendgrid.com/v3/mail/send"
        assert request.method == "POST"
        contexts.append(self._pool._ssl_context)
        messages.append(json.loads(request.read()))
        calls.append("send")
        return httpx.Response(accepted_status, headers={"X-Message-Id": "offline"}, request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", transport)
    identity, claim = claimed_lead()
    REAL_SEND_NOTIFICATION(identity, claim=claim)
    assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED and contexts[0].check_hostname
    expected = {
        certificate.fingerprint(hashes.SHA256()).hex()
        for certificate in x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    }
    actual = {
        hashlib.sha256(certificate).hexdigest()
        for certificate in contexts[0].get_ca_certs(binary_form=True)
    }
    compromised = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b"
    assert expected and compromised not in expected
    assert actual == expected
    assert compromised not in actual
    assert ca_files == [certifi.where()]
    assert calls == ["send"]
    assert len(messages) == 1
    assert messages[0]["from"]["email"] == "sender@example.com"
    assert messages[0]["personalizations"] == [
        {
            "to": [{"email": "sanjeev@orchestrum.in"}],
            "custom_args": {"public_lead_id": identity},
        }
    ]
    assert messages[0]["subject"] == "CaseOps public enquiry saved"
    assert messages[0]["content"] == [
        {
            "type": "text/plain",
            "value": (
                f"Public enquiry {identity} is saved.\n"
                "Review its details in the protected administrative dashboard: "
                "https://caseops.ai/platform/leads\n"
            ),
        }
    ]
    assert "offline-fixture" not in json.dumps(messages[0])
    assert "demo@example.com" not in json.dumps(messages[0])


def test_seo_demo_20261009_failed_tls_never_sends_credentials(client, monkeypatch):
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.com")
    get_settings.cache_clear()

    def reject(self, request):
        assert self._pool._ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert self._pool._ssl_context.check_hostname
        raise httpx.ConnectError("offline certificate rejection", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    identity, claim = claimed_lead()
    with pytest.raises(httpx.ConnectError, match="offline certificate rejection"):
        REAL_SEND_NOTIFICATION(identity, claim=claim)


def claimed_lead():
    with get_session_factory()() as session:
        identity = billing_demo.admit_demo(session, DemoRequest(**payload())).id
        row = session.get(BillingEnrollment, identity)
        state = billing_demo._state(row)
        claim = str(uuid4())
        state.update(
            notification_status="sending",
            claim=claim,
            lease_until=(datetime.now(UTC) + timedelta(seconds=60)).isoformat(),
        )
        billing_demo._save(row, state)
        session.commit()
        return identity, claim


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
    assert state["notification_status"] == "not_requested"
    assert state["notification_eligible"] is False
    assert "last_error_code" not in state
    assert state["attempts"] == 0 and offline_notifications == []


def test_seo_demo_20261009_existing_scheduler_drains_without_visitor(
    demo_client, monkeypatch, offline_notifications, capsys
):
    from caseops_api.scripts import send_hearing_reminders

    events, opened = [], []
    factory = send_hearing_reminders.get_session_factory()
    purge = send_hearing_reminders.purge_expired_demo_leads
    drain = send_hearing_reminders.drain_demo_notifications

    def tracked_factory():
        session = factory()
        opened.append(session)
        return session

    def hearing(_session, *, mode, limit):
        events.append(("hearing", limit))
        return {}

    def durable(_session, *, limit):
        events.append(("durable", limit))
        return {}

    def retention(*, limit):
        assert opened and all(not session.in_transaction() for session in opened)
        events.append(("retention", limit))
        return purge(limit=limit)

    def notifications(*, limit):
        assert opened and all(not session.in_transaction() for session in opened)
        events.append(("leads", limit))
        return drain(limit=limit)

    monkeypatch.setattr(send_hearing_reminders, "get_session_factory", lambda: tracked_factory)
    monkeypatch.setattr(send_hearing_reminders, "run_reminder_worker", hearing)
    monkeypatch.setattr(send_hearing_reminders, "drain_notification_delivery_intents", durable)
    monkeypatch.setattr(send_hearing_reminders, "purge_expired_demo_leads", retention)
    monkeypatch.setattr(send_hearing_reminders, "drain_demo_notifications", notifications)
    # Fresh admission is eligible, independently of temporary delivery pause.
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200, response.text
    identity = response.json()["id"]
    queued = assert_pending_notification(identity)
    assert offline_notifications == []
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: False)
    state = billing_demo._state(get_row(identity))
    future = datetime.fromisoformat(state["next_attempt_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(billing_demo, "_now", lambda: future)
    assert send_hearing_reminders.main(["--mode", "dry_run", "--limit", "137"]) == 0
    assert events == [("hearing", 137)]
    assert billing_demo._state(get_row(identity)) == queued
    assert offline_notifications == []
    events.clear()
    monkeypatch.setattr(billing_demo, "_notification_enabled", lambda: True)
    with offline_lead_worker_context():
        assert send_hearing_reminders.main(["--mode", "auto", "--limit", "137"]) == 0
    assert events == [("hearing", 137), ("durable", 137), ("retention", 100), ("leads", 100)]
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


def assert_pending_notification(identity):
    state = billing_demo._state(get_row(identity))
    assert state["notification_status"] == "pending" and state["attempts"] == 0
    assert state["automated_request"] is True
    assert "claim" not in state and "lease_until" not in state
    return state


def test_seo_demo_20261009_drain_excludes_non_public_cohort_before_limit(
    demo_client, offline_notifications
):
    with get_session_factory()() as session:
        identity = billing_demo.admit_demo(session, DemoRequest(**payload())).id
        public_row = session.get(BillingEnrollment, identity)
        original_state = billing_demo._state(public_row)
        excluded_ids = [str(uuid4()) for _ in range(25)]
        session.add_all(
            BillingEnrollment(
                id=excluded_id,
                contact_name="Non-public enrollment",
                contact_email="excluded@example.com",
                segment="solo",
                status="demo_requested",
                is_public_lead=False,
                created_at=public_row.created_at - timedelta(minutes=1),
                status_timestamps_json={"demo_admission": dict(original_state)},
            )
            for excluded_id in excluded_ids
        )
        session.commit()
        for excluded_id in excluded_ids:
            row = session.get(BillingEnrollment, excluded_id)
            assert row.is_public_lead is False
            assert billing_demo._state(row)["notification_eligible"] is True
            assert billing_demo._notification_eligible(row) is False

    assert billing_demo.drain_demo_notifications(limit=25) == {"selected": 1}
    assert offline_notifications == [identity]
    assert billing_demo.drain_demo_notifications(limit=25) == {"selected": 0}
    for excluded_id in excluded_ids:
        assert billing_demo._state(get_row(excluded_id)) == original_state


def test_seo_demo_20261009_commit_before_notification_and_ack(demo_client, monkeypatch):
    data = payload()
    observed = []

    def transport(identity, *, claim):
        row = get_row(identity)
        assert row and row.contact_email == data["contact_email"]
        assert row.status_timestamps_json["demo_admission"]["notification_status"] == "sending"
        assert row.status_timestamps_json["demo_admission"]["claim"] == claim
        observed.append(identity)

    monkeypatch.setattr(billing_demo, "_send_notification", transport)
    response = demo_client.post(URL, json=data)
    assert response.status_code == 200, response.text
    assert response.json() == {"id": data["idempotency_key"], "status": "demo_requested"}
    assert_pending_notification(response.json()["id"])
    assert observed == []
    assert drain_offline_lead_notifications() == {"selected": 1}
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


def test_seo_demo_20261009_replay_releases_request_session_before_transport(
    demo_client, monkeypatch
):
    data = DemoRequest(**payload())
    with get_session_factory()() as session:
        identity = billing_demo.admit_demo(session, data, automated=True).id
        assert billing_demo._state(session.get(BillingEnrollment, identity))["automated_request"]
    request_sessions, completed, observed = [], [], []

    async def tracked_request_session():
        dependency = get_db_session()
        request_sessions.append(await anext(dependency))
        try:
            yield request_sessions[-1]
        finally:
            await dependency.aclose()
            completed.append(True)

    def transport(enrollment_id, *, claim):
        observed.append(
            {
                "identity": enrollment_id,
                "request_session_count": len(request_sessions),
                "request_in_transaction": request_sessions[0].in_transaction(),
                "dependency_completed": bool(completed),
            }
        )

    monkeypatch.setitem(
        demo_client.app.dependency_overrides, get_db_session, tracked_request_session
    )
    monkeypatch.setattr(billing_demo, "_send_notification", transport)
    response = demo_client.post(URL, json=data.model_dump(mode="json"))
    assert response.status_code == 200, response.text
    assert_pending_notification(identity)
    assert observed == [] and completed == [True]
    assert request_sessions[0].in_transaction() is False
    assert drain_offline_lead_notifications() == {"selected": 1}
    assert observed == [
        {
            "identity": identity,
            "request_session_count": 1,
            "request_in_transaction": False,
            "dependency_completed": True,
        }
    ]
    assert completed == [True]
    assert billing_demo._state(get_row(identity))["notification_status"] == "sent"
    assert billing_demo._state(get_row(identity))["attempts"] == 1


@pytest.mark.parametrize(
    "error,code",
    [
        (httpx.ConnectError("redact provider PII"), "transport_outcome_unknown"),
        (TimeoutError("redact provider PII"), "transport_outcome_unknown"),
    ],
)
def test_seo_demo_20261009_transport_failure_and_timeout_preserve_lead_without_resend(
    demo_client, monkeypatch, error, code, caplog
):
    def failing(_, **_kwargs):
        raise error

    monkeypatch.setattr(billing_demo, "_send_notification", failing)
    response = demo_client.post(URL, json=payload())
    assert response.status_code == 200
    assert_pending_notification(response.json()["id"])
    assert drain_offline_lead_notifications() == {"selected": 1}
    row = get_row(response.json()["id"])
    state = row.status_timestamps_json["demo_admission"]
    assert row.status == "demo_requested" and row.contact_email == "demo@example.com"
    assert state["notification_status"] == "outcome_unknown" and state["last_error_code"] == code
    assert state["attempts"] == 1
    assert "redact provider PII" not in caplog.text and "demo@example.com" not in caplog.text
    sent = []
    monkeypatch.setattr(
        billing_demo, "_send_notification", lambda identity, **_: sent.append(identity)
    )
    future = datetime.fromisoformat(state["next_attempt_at"]) + timedelta(seconds=1)
    monkeypatch.setattr(billing_demo, "_now", lambda: future)
    assert billing_demo.drain_demo_notifications() == {"selected": 0}
    assert sent == []
    assert (
        get_row(row.id).status_timestamps_json["demo_admission"]["notification_status"]
        == "outcome_unknown"
    )


def test_seo_demo_20261009_duplicate_same_key_and_conflicting_key(
    demo_client, offline_notifications
):
    data = payload()
    first, second = demo_client.post(URL, json=data), demo_client.post(URL, json=data)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert_pending_notification(data["idempotency_key"])
    assert offline_notifications == []
    assert drain_offline_lead_notifications() == {"selected": 1}
    assert offline_notifications == [data["idempotency_key"]]
    replay = demo_client.post(URL, json=data)
    assert replay.status_code == 200 and replay.json() == first.json()
    assert drain_offline_lead_notifications() == {"selected": 0}
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
    assert billing_demo._state(get_row(identity))["notification_status"] == "outcome_unknown"
    assert billing_demo._state(get_row(identity))["attempts"] == billing_demo.MAX_ATTEMPTS


def test_seo_demo_20261009_admin_readback_retry_delete_are_audited(demo_client, monkeypatch):
    monkeypatch.setenv("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL", "owner@asterlegal.in")
    get_settings.cache_clear()
    token = str(bootstrap_company(demo_client)["access_token"])

    def failing(_, **_kwargs):
        raise billing_demo.NotificationRejected(retryable=True)

    monkeypatch.setattr(billing_demo, "_send_notification", failing)
    identity = demo_client.post(URL, json=payload()).json()["id"]
    assert_pending_notification(identity)
    assert drain_offline_lead_notifications() == {"selected": 1}
    response = demo_client.get("/api/platform-admin/enrollments", headers=auth_headers(token))
    assert response.status_code == 200, response.text
    row = next(row for row in response.json()["enrollments"] if row["id"] == identity)
    assert row["attribution"]["role"] == "solo_advocate"
    assert row["source"] == "solo_lawyers"
    assert row["demo_notification"]["last_error_code"] == "provider_rate_limited"
    assert "request_sha256" not in response.text and "claim" not in response.text
    synthetic_state = billing_demo._state(get_row(identity))
    assert synthetic_state["automated_request"] is True
    denied = demo_client.post(
        f"/api/platform-admin/enrollments/{identity}/retry-notification",
        headers=auth_headers(token),
        json={"reason": "A marked synthetic admission cannot be manually replayed"},
    )
    assert denied.status_code == 409, denied.text
    assert billing_demo._state(get_row(identity)) == synthetic_state

    # Model a separate human admission through its actual constructor; never
    # clear the persisted automated marker on the HTTP-created synthetic row.
    with get_session_factory()() as session:
        human = billing_demo.admit_demo(session, DemoRequest(**payload())).id
    assert billing_demo._state(get_row(human))["automated_request"] is False
    billing_demo.deliver_demo_notification(human)
    assert billing_demo._state(get_row(human))["last_error_code"] == "provider_rate_limited"
    sent = []
    monkeypatch.setattr(
        billing_demo, "_send_notification", lambda identity, **_: sent.append(identity)
    )
    from caseops_api.api.routes import platform_admin

    worker = Mock(wraps=billing_demo.deliver_demo_notification)
    drain_worker = Mock(wraps=billing_demo.drain_demo_notifications)
    monkeypatch.setattr(billing_demo, "deliver_demo_notification", worker)
    monkeypatch.setattr(billing_demo, "drain_demo_notifications", drain_worker)
    monkeypatch.setattr(platform_admin, "deliver_demo_notification", worker, raising=False)
    monkeypatch.setattr(platform_admin, "drain_demo_notifications", drain_worker, raising=False)
    retry = demo_client.post(
        f"/api/platform-admin/enrollments/{human}/retry-notification",
        headers=auth_headers(token),
        json={"reason": "Retry local fake transport"},
    )
    assert retry.status_code == 200, retry.text
    assert retry.json() == {"status": "queued"}
    worker.assert_not_called()
    drain_worker.assert_not_called()
    retry_state = billing_demo._state(get_row(human))
    assert retry_state["notification_status"] == "pending" and retry_state["attempts"] == 0
    assert "claim" not in retry_state and "lease_until" not in retry_state
    assert sent == []
    assert billing_demo.drain_demo_notifications() == {"selected": 1}
    drain_worker.assert_called_once_with()
    worker.assert_called_once_with(human)
    assert sent == [human]
    deleted = demo_client.request(
        "DELETE",
        f"/api/platform-admin/enrollments/{human}",
        headers=auth_headers(token),
        json={"reason": "Contact requested deletion"},
    )
    assert deleted.status_code == 200, deleted.text
    assert get_row(human) is None
    assert billing_demo._state(get_row(identity)) == synthetic_state
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


def test_seo_demo_20261009_expired_claim_holds_unknown_and_retention_preserves_converted(
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
        get_row(identity).status_timestamps_json["demo_admission"]["notification_status"]
        == "outcome_unknown"
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

    def transport(identity, *, claim):
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
            assert row.status_timestamps_json["demo_admission"]["claim"] == claim
            observed.append(identity)

    monkeypatch.setattr(billing_demo, "_send_notification", transport)
    response = isolated_postgres_client.post(URL, json=payload())
    assert response.status_code == 200
    assert_pending_notification(response.json()["id"])
    assert observed == []
    assert drain_offline_lead_notifications() == {"selected": 1}
    assert observed == [response.json()["id"]]
