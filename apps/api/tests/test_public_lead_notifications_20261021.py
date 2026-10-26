"""J19/M21/US-063: new-only admissions and fail-closed notification delivery."""

from __future__ import annotations

import json
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, text

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingEnrollment
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.saas_billing import DemoRequest
from caseops_api.services import billing_demo as demo
from caseops_api.services.platform_console_leads import leads_page

URL = "/api/billing/enrollments/demo-request"
NOW = datetime(2030, 1, 2, 12, tzinfo=UTC)
CUTOFF = NOW - timedelta(hours=1)


@pytest.fixture(autouse=True)
def offline_mail(monkeypatch, request):
    """Use the real SendGrid adapter, but never let its HTTP POST reach a socket."""
    if hasattr(request, "param"):
        if request.param is None:
            monkeypatch.delenv("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", raising=False)
        else:
            monkeypatch.setenv("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", request.param)
    # This SendGrid contract fixture does not opt into the separate e2e mail adapter.
    monkeypatch.delenv("CASEOPS_PUBLIC_LEAD_TEST_MAIL_URL", raising=False)
    mail = SimpleNamespace(calls=[], status=202, error=None, on_send=None)
    monkeypatch.setenv("CASEOPS_SENDGRID_API_KEY", "offline-mail-fixture")
    monkeypatch.setenv("CASEOPS_SENDGRID_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", "true")
    monkeypatch.setenv("CASEOPS_DEMO_RETENTION_ENABLED", "false")
    get_settings.cache_clear()

    def post(url, **kwargs):
        assert url == "https://api.sendgrid.com/v3/mail/send"
        mail.calls.append(kwargs)
        if mail.on_send:
            mail.on_send()
        if mail.error:
            raise mail.error
        return httpx.Response(
            mail.status, text="private-provider-response-sentinel",
            headers={"X-Message-Id": "offline-message-reference"},
        )

    def deny_transport(*args, **kwargs):
        raise AssertionError("Unmocked HTTP transport in offline public-lead fixture")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny_transport)
    monkeypatch.setattr(httpx, "post", post)
    yield mail
    get_settings.cache_clear()


@pytest.fixture
def clock(monkeypatch):
    value = [NOW]
    monkeypatch.setattr(demo, "_now", lambda: value[0])
    return value


def _payload(**changes):
    return DemoRequest(**{
        "idempotency_key": str(uuid4()), "contact_name": "Private Contact Sentinel",
        "contact_email": "private-contact@example.com", "contact_mobile": "5559876543",
        "company_name": "Private Organisation Sentinel", "segment": "solo",
        "role": "solo_advocate", "intent": "demo", "source": "demo",
        "notes": "Private notes sentinel", "privacy_notice_version": "2026-10-21",
        **changes,
    })


def _admit(payload=None, *, automated=False):
    with get_session_factory()() as session:
        return demo.admit_demo(session, payload or _payload(), automated=automated).id


def _state(identity):
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        assert row is not None
        return json.loads(json.dumps(demo._state(row)))


def _change(identity, **changes):
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        state = demo._state(row)
        state.update(changes)
        demo._save(row, state)
        session.commit()
    return state


@pytest.mark.parametrize("offline_mail", [
    None, "", "http://127.0.0.1:1/ambient-public-lead-mail",
    "https://unowned.example.invalid/public-lead-mail",
], indirect=True, ids=["unset", "empty", "loopback", "nonlocal"])
def test_offline_mail_fixture_isolates_inherited_test_adapter(client, clock, offline_mail):
    assert demo._local_notification_adapter() is None
    identity = _admit()
    demo.deliver_demo_notification(identity)
    state = _state(identity)
    assert state["notification_status"] == "sent" and state["attempts"] == 1
    assert len(offline_mail.calls) == 1


def test_offline_mail_fixture_rejects_unmocked_http_transport(offline_mail):
    with httpx.Client(trust_env=False) as transport:
        with pytest.raises(AssertionError, match="Unmocked HTTP transport"):
            transport.get("https://unowned.example.invalid/public-lead-mail")
    assert offline_mail.calls == []


@pytest.mark.parametrize("value", [None, "", "invalid", "1", "yes"])
def test_pure_invalid_enable_flag_fails_closed(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", value)
    assert demo._notification_enabled() is False


def test_pure_admission_cohort_does_not_depend_on_mutable_cutoff(monkeypatch):
    row = BillingEnrollment(is_public_lead=True, created_at=NOW, status_timestamps_json={
        "demo_admission": {"notification_purpose": demo.NOTIFICATION_PURPOSE,
                           "notification_policy": demo.NOTIFICATION_POLICY,
                           "notification_eligible": True},
    })
    for value in ["invalid", "2000-01-01T00:00:00+00:00", "2040-01-01T00:00:00+00:00"]:
        monkeypatch.setenv("CASEOPS_PUBLIC_LEAD_NOTIFICATION_NOT_BEFORE", value)
        assert demo._notification_eligible(row) is True
    assert not demo._retention_enabled()


@pytest.mark.parametrize("public,purpose,policy,marker,eligible", [
    (True, demo.NOTIFICATION_PURPOSE, demo.NOTIFICATION_POLICY, True, True),
    (False, demo.NOTIFICATION_PURPOSE, demo.NOTIFICATION_POLICY, True, False),
    (True, "legacy-purpose", demo.NOTIFICATION_POLICY, True, False),
    (True, None, demo.NOTIFICATION_POLICY, True, False),
    (True, demo.NOTIFICATION_PURPOSE, "revoked-policy", True, False),
    (True, demo.NOTIFICATION_PURPOSE, None, True, False),
    (True, demo.NOTIFICATION_PURPOSE, demo.NOTIFICATION_POLICY, False, False),
    (True, demo.NOTIFICATION_PURPOSE, demo.NOTIFICATION_POLICY, None, False),
    (True, demo.NOTIFICATION_PURPOSE, demo.NOTIFICATION_POLICY, 1, False),
])
def test_pure_eligibility_requires_exact_persisted_cohort(
    public, purpose, policy, marker, eligible,
):
    row = BillingEnrollment(is_public_lead=public, created_at=NOW, status_timestamps_json={
        "demo_admission": {"notification_purpose": purpose, "notification_policy": policy,
                           "notification_eligible": marker},
    })
    assert demo._notification_eligible(row) is eligible


@pytest.mark.parametrize("intent,source", [("demo", "demo"), ("pricing", "pricing_page"),
                                           ("pilot", "homepage")])
def test_reference_only_mail_uses_real_sendgrid_seam(client, clock, offline_mail, intent, source):
    payload = _payload(intent=intent, source=source)
    response = client.post(URL, json=payload.model_dump(mode="json"))
    assert response.status_code == 200
    identity = response.json()["id"]
    assert identity == str(payload.idempotency_key)
    queued = _state(identity)
    assert queued["notification_status"] == "pending" and queued["attempts"] == 0
    assert "claim" not in queued and "lease_until" not in queued
    assert offline_mail.calls == []
    assert demo.drain_demo_notifications() == {"selected": 1}
    assert _state(identity)["notification_status"] == "sent"
    assert len(offline_mail.calls) == 1
    wire = offline_mail.calls[0]
    assert wire["timeout"] == 20
    assert wire["json"]["personalizations"] == [{
        "to": [{"email": "sanjeev@orchestrum.in"}], "custom_args": {"public_lead_id": identity},
    }]
    assert wire["json"]["content"] == [{"type": "text/plain", "value": (
        f"Public enquiry {identity} is saved.\n"
        "Review its details in the protected administrative dashboard: "
        "https://caseops.ai/platform/leads\n"
    )}]
    rendered = json.dumps(wire["json"])
    for secret in [payload.contact_name, str(payload.contact_email), payload.contact_mobile,
                   payload.company_name, payload.notes]:
        assert secret not in rendered


@pytest.mark.parametrize("cohort", ["legacy", "disabled"])
@pytest.mark.parametrize("new_config", [None, "invalid", "2000-01-01T00:00:00+00:00",
                                         "2040-01-01T00:00:00+00:00"])
def test_obsolete_cutoff_changes_and_replay_never_promote_old_cohort(
    client, clock, offline_mail, monkeypatch, cohort, new_config,
):
    monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", "false")
    payload = _payload()
    identity = _admit(payload)
    if cohort == "legacy":
        with get_session_factory()() as session:
            row = session.get(BillingEnrollment, identity)
            row.created_at = CUTOFF - timedelta(days=1)
            state = demo._state(row)
            for key in ["notification_purpose", "notification_policy", "notification_eligible",
                        "notification_admitted_at", "automated_request"]:
                state.pop(key, None)
            state["notification_status"] = "pending"
            demo._save(row, state)
            session.commit()
    before = _state(identity)
    monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", "true")
    if new_config is None:
        monkeypatch.delenv("CASEOPS_PUBLIC_LEAD_NOTIFICATION_NOT_BEFORE", raising=False)
    else:
        monkeypatch.setenv("CASEOPS_PUBLIC_LEAD_NOTIFICATION_NOT_BEFORE", new_config)
    assert _admit(payload) == identity
    demo.deliver_demo_notification(identity)
    demo.drain_demo_notifications()
    assert _state(identity) == before
    assert offline_mail.calls == []
    with get_session_factory()() as session:
        page = leads_page(session, cursor=None, limit=25)
        record = next(item for item in page.items if item.id == identity)
        assert record.notes == payload.notes and record.contact_email == str(payload.contact_email)


@pytest.mark.parametrize("config", [None, "invalid", "1"])
def test_invalid_enable_flag_retains_visible_lead_without_transport(
    client, clock, offline_mail, monkeypatch, config,
):
    if config is None:
        monkeypatch.delenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", config)
    identity = _admit()
    demo.deliver_demo_notification(identity)
    assert _state(identity)["notification_status"] == "not_requested"
    assert _state(identity)["attempts"] == 0
    assert offline_mail.calls == []
    with get_session_factory()() as session:
        record = next(item for item in leads_page(session, cursor=None, limit=25).items
                      if item.id == identity)
        assert record.notification.status == "not_requested"


def test_idempotent_replay_never_sends_twice(client, clock, offline_mail):
    payload = _payload()
    identity = _admit(payload)
    demo.deliver_demo_notification(identity)
    before = _state(identity)
    assert _admit(payload) == identity
    demo.deliver_demo_notification(identity)
    demo.drain_demo_notifications()
    assert _state(identity) == before
    assert len(offline_mail.calls) == 1


@pytest.mark.parametrize("setting", ["CASEOPS_SENDGRID_API_KEY", "CASEOPS_SENDGRID_SENDER_EMAIL"])
def test_missing_transport_configuration_is_visible_without_losing_lead(
    client, clock, offline_mail, monkeypatch, setting,
):
    monkeypatch.setenv(setting, "")
    get_settings.cache_clear()
    payload = _payload()
    identity = _admit(payload)
    demo.deliver_demo_notification(identity)
    state = _state(identity)
    assert state["notification_status"] == "retry_pending"
    assert state["last_error_code"] == "configuration_unavailable"
    assert state["attempts"] == 1 and offline_mail.calls == []
    with get_session_factory()() as session:
        record = next(item for item in leads_page(session, cursor=None, limit=25).items
                      if item.id == identity)
        assert record.notes == payload.notes
        assert record.notification.last_error_code == "configuration_unavailable"


@pytest.mark.parametrize("existing", [False, True])
def test_no_paid_http_marker_blocks_new_and_replayed_admission(
    client, clock, offline_mail, existing,
):
    payload = _payload()
    if existing:
        _admit(payload)
    response = client.post(URL, json=payload.model_dump(mode="json"), headers={
        "X-CaseOps-Automated-Test": "no-paid-providers",
    })
    assert response.status_code == 200
    assert offline_mail.calls == []
    queued = _state(response.json()["id"])
    assert queued["notification_status"] == "pending" and queued["attempts"] == 0
    assert "claim" not in queued and "lease_until" not in queued
    if not existing:
        identity = response.json()["id"]
        assert _state(identity)["automated_request"] is True
        demo.drain_demo_notifications()
        assert offline_mail.calls == []
        assert _state(identity)["notification_status"] == "exhausted"
        assert _state(identity)["last_error_code"] == "automated_request_blocked"


def test_marked_replay_preserves_human_outbox_then_normal_drain_sends_once(
    client, clock, offline_mail,
):
    payload = _payload()
    identity = _admit(payload)
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        before = json.loads(json.dumps(row.status_timestamps_json))
    admission = before["demo_admission"]
    assert admission["notification_status"] == "pending"
    assert admission["notification_eligible"] is True
    assert admission["automated_request"] is False
    assert admission["attempts"] == 0

    response = client.post(URL, json=payload.model_dump(mode="json"), headers={
        "X-CaseOps-Automated-Test": "no-paid-providers",
    })
    assert response.status_code == 200
    assert response.json()["id"] == identity
    assert offline_mail.calls == []
    with get_session_factory()() as session:
        row = session.get(BillingEnrollment, identity)
        assert row.status_timestamps_json == before

    assert demo.drain_demo_notifications() == {"selected": 1}
    assert len(offline_mail.calls) == 1
    assert offline_mail.calls[0]["json"]["personalizations"][0]["custom_args"] == {
        "public_lead_id": identity,
    }
    delivered = _state(identity)
    assert delivered["notification_status"] == "sent"
    assert delivered["attempts"] == 1
    assert _admit(payload) == identity
    demo.deliver_demo_notification(identity)
    assert demo.drain_demo_notifications() == {"selected": 0}
    assert len(offline_mail.calls) == 1
    assert _state(identity) == delivered


def test_no_paid_context_is_checked_at_last_transport_boundary(client, clock, offline_mail):
    identity = _admit()
    token = set_automated_test_request("no-paid-providers")
    try:
        demo.deliver_demo_notification(identity)
    finally:
        reset_automated_test_request(token)
    assert offline_mail.calls == []
    assert _state(identity)["notification_status"] != "sent"


@pytest.mark.parametrize("result,expected", [
    (202, "sent"), (400, "exhausted"), (429, "retry_pending"),
    (503, "outcome_unknown"), ("timeout", "outcome_unknown"),
])
def test_provider_outcome_is_durable_and_redacted(
    client, clock, offline_mail, caplog, result, expected,
):
    identity = _admit()
    if result == "timeout":
        offline_mail.error = httpx.ReadTimeout("private-provider-response-sentinel")
    else:
        offline_mail.status = result
    demo.deliver_demo_notification(identity)
    state = _state(identity)
    assert state["notification_status"] == expected and state["attempts"] == 1
    assert "claim" not in state and "lease_until" not in state
    assert "private-provider-response-sentinel" not in json.dumps(state) + caplog.text
    clock[0] += timedelta(hours=2)
    offline_mail.error, offline_mail.status = None, 202
    demo.deliver_demo_notification(identity)
    demo.drain_demo_notifications()
    assert len(offline_mail.calls) == (2 if result == 429 else 1)


def test_expired_claim_is_unknown_not_a_resend(client, clock, offline_mail):
    identity = _admit()
    _change(identity, notification_status="sending", claim="interrupted-offline-claim",
            lease_until=(NOW - timedelta(seconds=1)).isoformat(), attempts=1)
    demo.deliver_demo_notification(identity)
    state = _state(identity)
    assert state["notification_status"] == "outcome_unknown"
    assert state["last_error_code"] == "claim_expired"
    demo.deliver_demo_notification(identity)
    demo.drain_demo_notifications()
    assert offline_mail.calls == []


def test_disable_after_claim_prevents_dispatch(client, clock, offline_mail, monkeypatch):
    identity = _admit()
    send = demo._send_notification

    def disable_then_send(key, *, claim):
        monkeypatch.setenv("CASEOPS_DEMO_NOTIFICATION_ENABLED", "false")
        return send(key, claim=claim)

    monkeypatch.setattr(demo, "_send_notification", disable_then_send)
    demo.deliver_demo_notification(identity)
    assert offline_mail.calls == []
    assert _state(identity)["notification_status"] != "sent"


def test_completion_after_lease_expiry_is_not_known_acceptance(client, clock, offline_mail):
    identity = _admit()
    offline_mail.on_send = lambda: clock.__setitem__(0, NOW + timedelta(seconds=61))
    demo.deliver_demo_notification(identity)
    assert len(offline_mail.calls) == 1
    assert _state(identity)["notification_status"] == "sending"
    demo.deliver_demo_notification(identity)
    assert _state(identity)["notification_status"] == "outcome_unknown"
    assert len(offline_mail.calls) == 1


@pytest.mark.postgres
def test_postgres_cas_claim_and_transport_hold_no_transaction(
    isolated_postgres_client, clock, offline_mail, monkeypatch,
):
    identity = _admit()
    factory = get_session_factory()
    opened, entered, release, start = [], Event(), Event(), Event()

    def tracked_factory():
        session = factory()
        opened.append((get_ident(), session))
        return session

    monkeypatch.setattr(demo, "get_session_factory", lambda: tracked_factory)

    def observe_transport():
        owned = [session for thread, session in opened if thread == get_ident()]
        assert owned and all(not session.in_transaction() for session in owned)
        entered.set()
        assert release.wait(5), "Test transport barrier was not released"

    offline_mail.on_send = observe_transport

    def deliver():
        assert start.wait(5), "Concurrent claim start was not released"
        demo.deliver_demo_notification(identity)

    with ThreadPoolExecutor(max_workers=2) as pool:
        workers = [pool.submit(deliver) for _ in range(2)]
        try:
            start.set()
            assert entered.wait(5), "First claim did not reach transport"
            completed, _ = wait(workers, timeout=5, return_when=FIRST_COMPLETED)
            assert len(completed) == 1, "Losing claimant did not finish independently"
            next(iter(completed)).result()
            assert len(offline_mail.calls) == 1
            with factory() as session:
                session.execute(text("SET LOCAL lock_timeout = '250ms'"))
                row = session.scalar(select(BillingEnrollment).where(
                    BillingEnrollment.id == identity,
                ).with_for_update(nowait=True))
                assert demo._state(row)["notification_status"] == "sending"
        finally:
            release.set()
            start.set()
        for worker in workers:
            worker.result(timeout=5)
    assert _state(identity)["notification_status"] == "sent"
    assert _state(identity)["attempts"] == 1


@pytest.mark.postgres
@pytest.mark.parametrize("overlap", ["claim_replaced", "purpose_revoked", "expired_recovered"])
def test_postgres_stale_completion_cannot_overwrite_new_state(
    isolated_postgres_client, clock, offline_mail, overlap,
):
    identity = _admit()
    entered, release = Event(), Event()

    def blocked_transport():
        entered.set()
        assert release.wait(5), "Test transport barrier was not released"

    offline_mail.on_send = blocked_transport
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker = pool.submit(demo.deliver_demo_notification, identity)
        try:
            assert entered.wait(5), "Claim did not reach transport"
            if overlap == "expired_recovered":
                clock[0] += timedelta(seconds=61)
                demo.deliver_demo_notification(identity)
            elif overlap == "claim_replaced":
                _change(identity, claim="replacement-offline-claim",
                        notification_status="outcome_unknown")
            else:
                _change(identity, notification_purpose="revoked-purpose",
                        notification_status="exhausted")
            expected = _state(identity)
        finally:
            release.set()
        worker.result(timeout=5)
    assert _state(identity) == expected
    assert len(offline_mail.calls) == 1
