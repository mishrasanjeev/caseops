"""SMS (MSG91) and WhatsApp (Meta Cloud API) reminder delivery.

Every provider call in this file goes to an in-process ``httpx.MockTransport``.
No test reaches a real network endpoint, and every credential is a fake.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.automated_test_context import NO_PAID_PROVIDERS_HEADER
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    BillingUsageEvent,
    CompanyProviderSpendPolicy,
    HearingReminder,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    NotificationPhoneContact,
    ProviderCostProfile,
    ProviderSpendReservation,
)
from caseops_api.db.session import get_session_factory
from caseops_api.schemas.phone_channels import PhoneTemplateMessage
from caseops_api.services import phone_providers
from caseops_api.services.notification_delivery import drain_notification_delivery_intents
from caseops_api.services.phone_providers import (
    classify_msg91_response,
    classify_whatsapp_response,
    msg91_request,
    phone_channel_readiness,
    send_phone_template,
    use_phone_transport,
    whatsapp_request,
)
from tests.test_hearing_reminders import _force_due, _mk_hearing_via_api, _mk_matter

PHONE = "+919812345678"
APP_SECRET = "fake-whatsapp-app-secret"
FULL_ENV = {
    "CASEOPS_PHONE_NOTIFICATION_TRANSPORT": "live",
    "CASEOPS_PHONE_NOTIFICATIONS_KILL_SWITCH": "false",
    "CASEOPS_MSG91_ENABLED": "true",
    "CASEOPS_MSG91_AUTH_KEY": "fake-msg91-auth-key",
    "CASEOPS_MSG91_SENDER_ID": "CSEOPS",
    "CASEOPS_MSG91_HEARING_TEMPLATE_ID": "msg91-hearing-tpl",
    "CASEOPS_MSG91_HEARING_DLT_TEMPLATE_ID": "1107160000000000001",
    "CASEOPS_MSG91_ALERT_TEMPLATE_ID": "msg91-alert-tpl",
    "CASEOPS_MSG91_ALERT_DLT_TEMPLATE_ID": "1107160000000000002",
    "CASEOPS_MSG91_OTP_TEMPLATE_ID": "msg91-otp-tpl",
    "CASEOPS_MSG91_OTP_DLT_TEMPLATE_ID": "1107160000000000003",
    "CASEOPS_WHATSAPP_ENABLED": "true",
    "CASEOPS_WHATSAPP_ACCESS_TOKEN": "fake-meta-token",
    "CASEOPS_WHATSAPP_PHONE_NUMBER_ID": "123456789012345",
    "CASEOPS_WHATSAPP_HEARING_TEMPLATE_NAME": "hearing_reminder_v1",
    "CASEOPS_WHATSAPP_ALERT_TEMPLATE_NAME": "workspace_alert_v1",
    "CASEOPS_WHATSAPP_OTP_TEMPLATE_NAME": "verification_code_v1",
    "CASEOPS_WHATSAPP_APP_SECRET": APP_SECRET,
    "CASEOPS_WHATSAPP_WEBHOOK_VERIFY_TOKEN": "fake-verify-token",
}


class FakeProvider:
    """Records every request; answers with a scripted response per call."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responders: list[Callable[[httpx.Request], httpx.Response]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responders:
            return self.responders.pop(0)(request)
        if request.url.host == "control.msg91.com":
            return httpx.Response(
                200, json={"type": "success", "message": f"req-{len(self.requests)}"}
            )
        return httpx.Response(
            200,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": PHONE, "wa_id": PHONE[1:]}],
                "messages": [{"id": f"wamid.fake{len(self.requests)}"}],
            },
        )

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]

    @contextmanager
    def installed(self) -> Iterator[FakeProvider]:
        with use_phone_transport(httpx.MockTransport(self.handler)):
            yield self


@pytest.fixture
def phone_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    def apply(**overrides: str | None) -> None:
        for key, value in {**FULL_ENV, **overrides}.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield apply
    get_settings.cache_clear()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _bootstrap(client: TestClient, slug: str = "aster-legal") -> dict:
    response = client.post(
        "/api/bootstrap/company",
        json={
            "company_name": f"{slug.title()} LLP",
            "company_slug": slug,
            "company_type": "law_firm",
            "owner_full_name": "Asha Rao",
            "owner_email": f"owner@{slug}.in",
            "owner_password": "FoundersPass123!",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _enable_channels(client: TestClient, token: str, **channels: bool) -> None:
    response = client.patch(
        "/api/admin/notification-preferences",
        headers=_auth(token),
        json={"channels": channels},
    )
    assert response.status_code == 200, response.text


def _verified_cost(channel: str, provider: str, amount: int = 25) -> None:
    with get_session_factory()() as session:
        session.add(
            ProviderCostProfile(
                category=channel,
                provider=provider,
                currency="INR",
                unit_amount_minor=amount,
                unit_label="message",
                effective_from=datetime.now(UTC) - timedelta(days=1),
                status="active",
                source="Provider rate card (test fixture)",
                cost_basis="actual",
                confidence_level="high",
                evidence_ref="test-fixture-rate-card",
            )
        )
        session.commit()


def _verify_and_consent(
    client: TestClient,
    token: str,
    fake: FakeProvider,
    *,
    channel: str = "sms",
    consent: tuple[str, ...] = ("sms",),
) -> None:
    started = client.post(
        "/api/notification-preferences/phone/verification",
        headers=_auth(token),
        json={"phone_number": "98123 45678", "channel": channel},
    )
    assert started.status_code == 200, started.text
    body = fake.bodies()[-1]
    if channel == "sms":
        code = body["recipients"][0]["VAR1"]
    else:
        code = body["template"]["components"][0]["parameters"][0]["text"]
    confirmed = client.post(
        "/api/notification-preferences/phone/verification/confirm",
        headers=_auth(token),
        json={"code": code},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["verified"] is True
    for item in consent:
        granted = client.post(
            "/api/notification-preferences/phone/consent",
            headers=_auth(token),
            json={"channel": item, "opted_in": True, "consent_text_version": "2026-11-22"},
        )
        assert granted.status_code == 200, granted.text
        assert granted.json()["channels"][item]["opted_in"] is True


def _phone_intents(company_id: str, channel: str = "sms") -> list[NotificationDeliveryIntent]:
    with get_session_factory()() as session:
        return list(
            session.scalars(
                select(NotificationDeliveryIntent)
                .where(
                    NotificationDeliveryIntent.company_id == company_id,
                    NotificationDeliveryIntent.channel == channel,
                )
                .order_by(NotificationDeliveryIntent.scheduled_for)
            )
        )


def _due_hearing(
    client: TestClient, token: str, code: str, channels: list[str]
) -> dict:
    matter = _mk_matter(client, token, code=code)
    hearing = _mk_hearing_via_api(client, token, matter["id"], days_ahead=3, channels=channels)
    with get_session_factory()() as session:
        _force_due(session, hearing["id"])
        session.commit()
    return hearing


def _drain() -> dict[str, int]:
    with get_session_factory()() as session:
        return drain_notification_delivery_intents(session, limit=50)


def _setup_opted_in_sms(
    client: TestClient, phone_env, fake: FakeProvider, slug: str = "aster-legal"
) -> tuple[str, str]:
    phone_env()
    boot = _bootstrap(client, slug)
    token = str(boot["access_token"])
    _enable_channels(client, token, sms=True, whatsapp=True)
    _verified_cost("sms", "msg91")
    _verify_and_consent(client, token, fake)
    return token, str(boot["company"]["id"])


# ------------------------------------------------------------------ adapters


def _message(channel: str, template: str = "hearing_reminder", variables=None):
    return PhoneTemplateMessage(
        channel=channel,
        to=PHONE,
        template=template,
        variables=variables or ("CIV-12", "24 Nov 2026", "10:30", "Delhi High Court"),
        idempotency_key="a" * 64,
    )


def test_msg91_payload_uses_flow_api_template_and_auth_header(phone_env) -> None:
    phone_env()
    url, headers, body = msg91_request(_message("sms"))
    assert url == "https://control.msg91.com/api/v5/flow"
    assert headers == {
        "authkey": "fake-msg91-auth-key",
        "accept": "application/json",
        "content-type": "application/json",
    }
    assert body == {
        "template_id": "msg91-hearing-tpl",
        "short_url": "0",
        "realTimeResponse": "1",
        "recipients": [
            {
                "mobiles": "919812345678",
                "VAR1": "CIV-12",
                "VAR2": "24 Nov 2026",
                "VAR3": "10:30",
                "VAR4": "Delhi High Court",
            }
        ],
    }
    reference = phone_providers.template_reference("sms", "hearing_reminder")
    assert reference == {
        "provider_template_id": "msg91-hearing-tpl",
        "dlt_template_id": "1107160000000000001",
        "sender_id": "CSEOPS",
    }


def test_whatsapp_payload_uses_approved_template_and_bearer_token(phone_env) -> None:
    phone_env()
    url, headers, body = whatsapp_request(_message("whatsapp"))
    assert url == "https://graph.facebook.com/v21.0/123456789012345/messages"
    assert headers == {
        "Authorization": "Bearer fake-meta-token",
        "Content-Type": "application/json",
    }
    assert body == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": PHONE,
        "type": "template",
        "template": {
            "name": "hearing_reminder_v1",
            "language": {"code": "en"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": "CIV-12"},
                        {"type": "text", "text": "24 Nov 2026"},
                        {"type": "text", "text": "10:30"},
                        {"type": "text", "text": "Delhi High Court"},
                    ],
                }
            ],
        },
    }
    _, _, otp = whatsapp_request(_message("whatsapp", "otp", ("123456",)))
    assert otp["template"]["name"] == "verification_code_v1"
    assert otp["template"]["components"] == [
        {"type": "body", "parameters": [{"type": "text", "text": "123456"}]},
        {
            "type": "button",
            "sub_type": "url",
            "index": "0",
            "parameters": [{"type": "text", "text": "123456"}],
        },
    ]


@pytest.mark.parametrize(
    ("status_code", "payload", "outcome", "error_code"),
    [
        (200, {"type": "success", "message": "abc123"}, "accepted", None),
        (200, {"type": "error", "message": "Bad template"}, "permanent_rejection",
         "provider_rejected"),
        (401, {"type": "error", "message": "Bad authkey"}, "permanent_rejection",
         "provider_authentication"),
        (429, {"type": "error", "message": "Too many"}, "retryable_rejection",
         "provider_rate_limited"),
        (503, {}, "outcome_unknown", "provider_server_error"),
    ],
)
def test_msg91_error_mapping(status_code, payload, outcome, error_code) -> None:
    result = classify_msg91_response(httpx.Response(status_code, json=payload))
    assert result.outcome == outcome
    assert result.error_code == error_code
    if outcome == "accepted":
        assert result.provider_message_id == "abc123"


@pytest.mark.parametrize(
    ("status_code", "code", "outcome"),
    [
        (400, 130429, "retryable_rejection"),
        (400, 131056, "retryable_rejection"),
        (400, 80007, "retryable_rejection"),
        (400, 4, "retryable_rejection"),
        (401, 190, "permanent_rejection"),
        (400, 132001, "permanent_rejection"),
        (400, 131026, "permanent_rejection"),
        (500, 1, "outcome_unknown"),
    ],
)
def test_whatsapp_error_mapping(status_code, code, outcome) -> None:
    result = classify_whatsapp_response(
        httpx.Response(
            status_code,
            json={"error": {"message": "(#x) failure", "type": "OAuthException", "code": code}},
        )
    )
    assert result.outcome == outcome
    assert result.error_code == f"meta_{code}"


def test_transport_failures_distinguish_never_sent_from_unknown(phone_env) -> None:
    phone_env()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    def hang(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with use_phone_transport(httpx.MockTransport(refuse)):
        assert send_phone_template(_message("sms")).outcome == "retryable_rejection"
    with use_phone_transport(httpx.MockTransport(hang)):
        result = send_phone_template(_message("whatsapp"))
    assert result.outcome == "outcome_unknown"
    assert result.error_code == "transport_outcome_unknown"


# ------------------------------------------------------------ configuration


def test_kill_switch_and_incomplete_configuration_refuse(phone_env, monkeypatch) -> None:
    phone_env()
    assert phone_channel_readiness("sms").ready is True
    phone_env(CASEOPS_PHONE_NOTIFICATIONS_KILL_SWITCH="true")
    assert phone_channel_readiness("sms").reason == "kill_switch_active"
    assert phone_channel_readiness("whatsapp").reason == "kill_switch_active"
    phone_env(CASEOPS_MSG91_OTP_DLT_TEMPLATE_ID=None)
    readiness = phone_channel_readiness("sms")
    assert readiness.reason == "provider_incomplete"
    assert readiness.missing == ("CASEOPS_MSG91_OTP_DLT_TEMPLATE_ID",)
    phone_env(CASEOPS_WHATSAPP_ENABLED="false")
    assert phone_channel_readiness("whatsapp").reason == "provider_disabled"
    with pytest.raises(ValueError, match="not ready"):
        send_phone_template(_message("whatsapp"))
    # Mock transport never leaves the process, so it must never count as
    # ready outside a local environment.
    phone_env(CASEOPS_PHONE_NOTIFICATION_TRANSPORT="mock")
    real = get_settings()
    monkeypatch.setattr(
        phone_providers, "get_settings", lambda: real.model_copy(update={"env": "production"})
    )
    assert phone_channel_readiness("sms").reason == "mock_transport_outside_local"


def test_default_deployment_has_no_ready_phone_channel(client: TestClient) -> None:
    get_settings.cache_clear()
    assert phone_channel_readiness("sms").reason == "provider_disabled"
    assert phone_channel_readiness("whatsapp").reason == "provider_disabled"
    token = str(_bootstrap(client)["access_token"])
    status_body = client.get("/api/admin/notification-phone-channels", headers=_auth(token)).json()
    assert status_body["channels"]["sms"]["provider_ready"] is False
    assert "CASEOPS_MSG91_AUTH_KEY" in status_body["channels"]["sms"]["missing_configuration"]


# ------------------------------------------------------- end-to-end delivery


def test_opted_in_hearing_reminder_sends_once_with_minimal_template(
    client: TestClient, phone_env
) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        otp_calls = len(fake.requests)
        _due_hearing(client, token, "CIV-12", ["in_app", "sms"])
        first = _drain()
        second = _drain()
    sends = fake.requests[otp_calls:]
    intents = _phone_intents(company_id)
    assert len(intents) == 2  # one per reminder offset, never per retry
    assert len(sends) == 2
    assert first["external_calls"] == 2
    assert second["external_calls"] == 0
    for request in sends:
        assert str(request.url) == "https://control.msg91.com/api/v5/flow"
        assert request.headers["authkey"] == "fake-msg91-auth-key"
        body = json.loads(request.content)
        assert body["template_id"] == "msg91-hearing-tpl"
        recipient = body["recipients"][0]
        assert recipient["mobiles"] == "919812345678"
        assert recipient["VAR1"] == "CIV-12"
        assert recipient["VAR3"] == "time not fixed"
        assert recipient["VAR4"].startswith("Delhi HC")
        assert all(len(value) <= 30 for value in recipient.values())
        # Matter title, purpose and other privileged fields never leave.
        assert "Reminder test" not in request.content.decode()
        assert "bail" not in request.content.decode()
    assert {intent.status for intent in intents} == {"sent"}
    assert {intent.provider_event_id for intent in intents} == {"req-2", "req-3"}
    with get_session_factory()() as session:
        attempts = session.scalars(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "notification_delivery.phone.attempted",
            )
        ).all()
        assert len(attempts) == 2
        metadata = json.loads(attempts[0].metadata_json)
        assert metadata["outcome"] == "accepted"
        assert metadata["dlt_template_id"] == "1107160000000000001"
        assert PHONE not in attempts[0].metadata_json
        assert "9812345678" not in attempts[0].metadata_json
        usage = session.scalars(
            select(BillingUsageEvent).where(
                BillingUsageEvent.company_id == company_id,
                BillingUsageEvent.provider_key == "msg91",
            )
        ).all()
        # One verification code plus two reminders.
        assert sorted(row.estimated_cost_minor for row in usage) == [25, 25, 25]
        holds = session.scalars(
            select(ProviderSpendReservation).where(
                ProviderSpendReservation.company_id == company_id
            )
        ).all()
        assert {row.status for row in holds} == {"settled"}
        events = session.scalars(
            select(NotificationDeliveryEvent).where(
                NotificationDeliveryEvent.intent_id == intents[0].id
            )
        ).all()
        assert [row.event_type for row in events].count("provider_accepted") == 1
        assert "delivery_claimed" in [row.event_type for row in events]


def test_whatsapp_hearing_reminder_uses_meta_template(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
        _enable_channels(client, token, whatsapp=True)
        _verified_cost("whatsapp", "meta-whatsapp")
        _verify_and_consent(client, token, fake, channel="whatsapp", consent=("whatsapp",))
        assert fake.bodies()[0]["template"]["name"] == "verification_code_v1"
        _due_hearing(client, token, "WA-7", ["in_app", "whatsapp"])
        _drain()
    sends = fake.requests[1:]
    assert len(sends) == 2
    assert sends[0].headers["Authorization"] == "Bearer fake-meta-token"
    body = json.loads(sends[0].content)
    assert body["template"]["name"] == "hearing_reminder_v1"
    assert body["template"]["components"][0]["parameters"][0] == {"type": "text", "text": "WA-7"}
    assert {i.status for i in _phone_intents(company_id, "whatsapp")} == {"sent"}


def test_unknown_outcome_is_never_resent(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)

        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("lost response", request=request)

        fake.responders = [timeout, timeout]
        _due_hearing(client, token, "UNK-1", ["in_app", "sms"])
        _drain()
        calls = len(fake.requests)
        _drain()
        _drain()
    assert len(fake.requests) == calls
    intents = _phone_intents(company_id)
    assert {i.status for i in intents} == {"dead_letter"}
    assert {i.dead_letter_reason for i in intents} == {"dispatch_provider_outcome_unknown"}
    with get_session_factory()() as session:
        holds = session.scalars(
            select(ProviderSpendReservation).where(
                ProviderSpendReservation.company_id == company_id,
                ProviderSpendReservation.status == "reserved",
            )
        ).all()
        # The possible charge stays held against the monthly cap.
        assert len(holds) == 2
        assert all(row.dispatched_at is not None for row in holds)


def test_rate_limited_send_retries_once_and_records_each_attempt(
    client: TestClient, phone_env
) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        fake.responders = [
            lambda request: httpx.Response(429, json={"type": "error", "message": "slow down"}),
        ]
        hearing = _due_hearing(client, token, "RTY-1", ["in_app", "sms"])
        _drain()
        retrying = [i for i in _phone_intents(company_id) if i.status == "retry_scheduled"]
        assert len(retrying) == 1
        with get_session_factory()() as session:
            row = session.get(NotificationDeliveryIntent, retrying[0].id)
            row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        _drain()
        _drain()
    assert hearing["id"]
    intents = _phone_intents(company_id)
    assert {i.status for i in intents} == {"sent"}
    retried = next(i for i in intents if i.id == retrying[0].id)
    assert retried.attempts == 2
    with get_session_factory()() as session:
        events = [
            row.event_type
            for row in session.scalars(
                select(NotificationDeliveryEvent)
                .where(NotificationDeliveryEvent.intent_id == retried.id)
                .order_by(NotificationDeliveryEvent.occurred_at)
            )
        ]
        released = session.scalars(
            select(ProviderSpendReservation).where(
                ProviderSpendReservation.company_id == company_id,
                ProviderSpendReservation.status == "released",
            )
        ).all()
    assert events.count("delivery_claimed") == 2
    assert events.count("provider_attempt_failed") == 1
    assert events.count("provider_accepted") == 1
    assert len(released) == 1  # the refused attempt costs nothing


def test_live_claim_blocks_a_concurrent_second_dispatch(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        _due_hearing(client, token, "CLM-1", ["in_app", "sms"])
        intents = _phone_intents(company_id)
        with get_session_factory()() as session:
            for intent in intents:
                row = session.get(NotificationDeliveryIntent, intent.id)
                row.status = "sent"
                row.provider_event_id = "dispatch_claim:other-worker"
                row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=4)
            session.commit()
        calls = len(fake.requests)
        _drain()
    assert len(fake.requests) == calls


# ------------------------------------------------------------- refusals


def _assert_blocked_without_calls(company_id: str, fake: FakeProvider, calls: int, reason: str):
    assert len(fake.requests) == calls
    intents = _phone_intents(company_id)
    assert intents, "expected SMS intents"
    assert {i.status for i in intents} == {"blocked"}
    assert {i.dead_letter_reason for i in intents} == {reason}


def test_unverified_number_refuses(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
        _enable_channels(client, token, sms=True)
        _verified_cost("sms", "msg91")
        refused = client.post(
            "/api/notification-preferences/phone/consent",
            headers=_auth(token),
            json={"channel": "sms", "opted_in": True, "consent_text_version": "2026-11-22"},
        )
        assert refused.status_code == 409
        assert refused.json()["code"] == "phone_not_verified"
        with get_session_factory()() as session:
            # Even a row that claims consent cannot send without verification.
            session.add(
                NotificationPhoneContact(
                    company_id=company_id,
                    membership_id=boot["membership"]["id"],
                    phone_number=PHONE,
                    sms_consent_at=datetime.now(UTC),
                    verification_attempts=0,
                )
            )
            session.commit()
        _due_hearing(client, token, "UNV-1", ["in_app", "sms"])
        _drain()
    _assert_blocked_without_calls(company_id, fake, 0, "phone_not_verified")


def test_verified_number_without_consent_refuses(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
        _enable_channels(client, token, sms=True)
        _verified_cost("sms", "msg91")
        _verify_and_consent(client, token, fake, consent=())
        missing_version = client.post(
            "/api/notification-preferences/phone/consent",
            headers=_auth(token),
            json={"channel": "sms", "opted_in": True},
        )
        assert missing_version.status_code == 422
        _due_hearing(client, token, "NOC-1", ["in_app", "sms"])
        _drain()
    _assert_blocked_without_calls(company_id, fake, 1, "phone_consent_missing")


def test_opt_out_after_queueing_is_honoured_at_dispatch(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        _due_hearing(client, token, "OPT-1", ["in_app", "sms"])
        assert {i.status for i in _phone_intents(company_id)} == {"queued"}
        withdrawn = client.post(
            "/api/notification-preferences/phone/consent",
            headers=_auth(token),
            json={"channel": "sms", "opted_in": False},
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["channels"]["sms"]["opted_in"] is False
        _drain()
    _assert_blocked_without_calls(company_id, fake, 1, "phone_opted_out")
    with get_session_factory()() as session:
        actions = set(
            session.scalars(
                select(AuditEvent.action).where(AuditEvent.company_id == company_id)
            )
        )
    assert {
        "notification_phone.verification_sent",
        "notification_phone.verified",
        "notification_phone.consent_granted",
        "notification_phone.consent_withdrawn",
        "notification_delivery.phone.blocked",
    } <= actions


def test_generic_preference_patch_can_opt_out_but_never_opt_in(
    client: TestClient, phone_env
) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, _ = _setup_opted_in_sms(client, phone_env, fake)
    off = client.patch(
        "/api/notification-preferences", headers=_auth(token), json={"channels": {"sms": False}}
    )
    assert off.status_code == 200
    assert off.json()["user"]["channels"]["sms"]["enabled"] is False
    on = client.patch(
        "/api/notification-preferences", headers=_auth(token), json={"channels": {"sms": True}}
    )
    assert on.status_code == 422


def test_budget_cap_refuses_without_calling_provider(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        with get_session_factory()() as session:
            session.add(
                CompanyProviderSpendPolicy(
                    company_id=company_id,
                    provider_key="msg91",
                    monthly_limit_minor=30,
                    currency="INR",
                    policy_source="test_cap",
                )
            )
            session.commit()
        _due_hearing(client, token, "CAP-1", ["in_app", "sms"])
        _drain()
    # 25 already spent on the verification code; the next 25 would pass 30.
    _assert_blocked_without_calls(company_id, fake, 1, "provider_budget_exhausted")


def test_unverified_cost_refuses(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token = str(boot["access_token"])
        _enable_channels(client, token, sms=True)
        response = client.post(
            "/api/notification-preferences/phone/verification",
            headers=_auth(token),
            json={"phone_number": PHONE, "channel": "sms"},
        )
    assert response.status_code == 503
    assert response.json()["code"] == "provider_cost_policy"
    assert fake.requests == []


def test_kill_switch_and_unconfigured_provider_refuse_queued_work(
    client: TestClient, phone_env
) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        _due_hearing(client, token, "KIL-1", ["in_app", "sms"])
        phone_env(CASEOPS_PHONE_NOTIFICATIONS_KILL_SWITCH="true")
        refused = client.post(
            "/api/notification-preferences/phone/verification",
            headers=_auth(token),
            json={"phone_number": PHONE, "channel": "sms"},
        )
        assert refused.status_code == 409
        assert refused.json()["reason"] == "kill_switch_active"
        _drain()
    _assert_blocked_without_calls(company_id, fake, 1, "kill_switch_active")


def test_unconfigured_provider_blocks_at_enqueue(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        phone_env(CASEOPS_MSG91_HEARING_TEMPLATE_ID=None)
        _due_hearing(client, token, "CFG-1", ["in_app", "sms"])
        _drain()
    _assert_blocked_without_calls(company_id, fake, 1, "provider_incomplete")


def test_live_config_inside_pytest_without_fake_never_sends(
    client: TestClient, phone_env
) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        _due_hearing(client, token, "NPD-1", ["in_app", "sms"])
    # Outside the fake, a leaked live configuration in a test process is
    # refused before any network I/O.
    _drain()
    _assert_blocked_without_calls(company_id, fake, 1, "paid_provider_automated_test_process")


def test_no_paid_marker_refuses_verification_send(client: TestClient, phone_env) -> None:
    phone_env()
    boot = _bootstrap(client)
    token = str(boot["access_token"])
    _enable_channels(client, token, sms=True)
    _verified_cost("sms", "msg91")
    response = client.post(
        "/api/notification-preferences/phone/verification",
        headers={**_auth(token), NO_PAID_PROVIDERS_HEADER: "no-paid-providers"},
        json={"phone_number": PHONE, "channel": "sms"},
    )
    assert response.status_code == 409
    assert response.json()["code"] == "paid_provider_blocked_for_test"


def test_verification_code_rules(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token = str(boot["access_token"])
        _enable_channels(client, token, sms=True)
        _verified_cost("sms", "msg91")
        intl = client.post(
            "/api/notification-preferences/phone/verification",
            headers=_auth(token),
            json={"phone_number": "+14155550100", "channel": "sms"},
        )
        assert intl.status_code == 422
        started = client.post(
            "/api/notification-preferences/phone/verification",
            headers=_auth(token),
            json={"phone_number": PHONE, "channel": "sms"},
        )
        assert started.status_code == 200
        assert started.json()["phone_masked"] == "+91 ••••• 5678"
        assert PHONE not in started.text
        again = client.post(
            "/api/notification-preferences/phone/verification",
            headers=_auth(token),
            json={"phone_number": PHONE, "channel": "sms"},
        )
        assert again.status_code == 429
        code = fake.bodies()[0]["recipients"][0]["VAR1"]
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            bad = client.post(
                "/api/notification-preferences/phone/verification/confirm",
                headers=_auth(token),
                json={"code": wrong},
            )
            assert bad.status_code == 422
        locked = client.post(
            "/api/notification-preferences/phone/verification/confirm",
            headers=_auth(token),
            json={"code": code},
        )
        assert locked.status_code == 429
    with get_session_factory()() as session:
        contact = session.scalar(select(NotificationPhoneContact))
        assert contact.verified_at is None
        assert code not in (contact.verification_code_hash or "")


# --------------------------------------------------------- tenant isolation


def test_one_tenants_settings_never_send_for_another(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token_a, company_a = _setup_opted_in_sms(client, phone_env, fake, slug="aster-legal")
        boot_b = _bootstrap(client, "birch-chambers")
        token_b, company_b = str(boot_b["access_token"]), str(boot_b["company"]["id"])
        calls = len(fake.requests)
        _due_hearing(client, token_b, "B-1", ["in_app", "sms"])
        _drain()
        assert len(fake.requests) == calls
        assert {i.dead_letter_reason for i in _phone_intents(company_b)} == {
            "workspace_channel_disabled"
        }
        # Enabling the channel in B still needs B's own verified consent.
        _enable_channels(client, token_b, sms=True)
        _due_hearing(client, token_b, "B-2", ["in_app", "sms"])
        _drain()
        assert len(fake.requests) == calls
        admin_b = client.get(
            "/api/admin/notification-phone-channels", headers=_auth(token_b)
        ).json()
        admin_a = client.get(
            "/api/admin/notification-phone-channels", headers=_auth(token_a)
        ).json()
    assert admin_b["channels"]["sms"]["opted_in_members"] == 0
    assert admin_a["channels"]["sms"]["opted_in_members"] == 1
    reasons = {i.dead_letter_reason for i in _phone_intents(company_b)}
    assert reasons == {"workspace_channel_disabled", "phone_not_registered"}
    assert _phone_intents(company_a) == []


# ---------------------------------------------------------- WhatsApp webhook


def _signed(body: bytes) -> dict[str, str]:
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


def test_whatsapp_stop_reply_opts_out(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        consent = client.post(
            "/api/notification-preferences/phone/consent",
            headers=_auth(token),
            json={"channel": "whatsapp", "opted_in": True, "consent_text_version": "2026-11-22"},
        )
        assert consent.json()["channels"]["whatsapp"]["opted_in"] is True
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "waba",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "from": "919812345678",
                                    "id": "wamid.in1",
                                    "timestamp": "1763700000",
                                    "type": "text",
                                    "text": {"body": " Stop "},
                                }
                            ]
                        },
                    }
                ],
            }
        ],
    }
    body = json.dumps(payload).encode()
    forged = client.post(
        "/api/webhooks/whatsapp",
        content=body,
        headers={"X-Hub-Signature-256": "sha256=" + "0" * 64, "Content-Type": "application/json"},
    )
    assert forged.status_code == 401
    accepted = client.post("/api/webhooks/whatsapp", content=body, headers=_signed(body))
    assert accepted.status_code == 200, accepted.text
    state = client.get("/api/notification-preferences/phone", headers=_auth(token)).json()
    assert state["channels"]["whatsapp"]["opted_in"] is False
    assert state["channels"]["whatsapp"]["opt_out_source"] == "whatsapp_stop_reply"
    # SMS consent is a separate choice and stays as it was.
    assert state["channels"]["sms"]["opted_in"] is True
    with get_session_factory()() as session:
        audit = session.scalar(
            select(AuditEvent).where(
                AuditEvent.company_id == company_id,
                AuditEvent.actor_label == "whatsapp-webhook",
            )
        )
    assert audit is not None and audit.action == "notification_phone.consent_withdrawn"


def test_whatsapp_webhook_handshake_and_missing_secret(
    client: TestClient, phone_env, monkeypatch
) -> None:
    phone_env()
    ok = client.get(
        "/api/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "fake-verify-token",
            "hub.challenge": "1158201444",
        },
    )
    assert ok.status_code == 200 and ok.text == "1158201444"
    bad = client.get(
        "/api/webhooks/whatsapp",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "1"},
    )
    assert bad.status_code == 403
    from caseops_api.api.routes import notifications as routes

    phone_env(CASEOPS_WHATSAPP_APP_SECRET=None)
    monkeypatch.setattr(routes, "_is_local_env", lambda: False)
    refused = client.post("/api/webhooks/whatsapp", content=b"{}")
    assert refused.status_code == 503


def test_whatsapp_delivery_status_advances_intent(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        phone_env()
        boot = _bootstrap(client)
        token, company_id = str(boot["access_token"]), str(boot["company"]["id"])
        _enable_channels(client, token, whatsapp=True)
        _verified_cost("whatsapp", "meta-whatsapp")
        _verify_and_consent(client, token, fake, channel="whatsapp", consent=("whatsapp",))
        _due_hearing(client, token, "WAS-1", ["in_app", "whatsapp"])
        _drain()
    intent = _phone_intents(company_id, "whatsapp")[0]
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "statuses": [
                                {
                                    "id": intent.provider_event_id,
                                    "status": "delivered",
                                    "timestamp": "1763700000",
                                    "recipient_id": "919812345678",
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode()
    for _ in range(2):  # a redelivered webhook is applied once
        response = client.post("/api/webhooks/whatsapp", content=body, headers=_signed(body))
        assert response.status_code == 200
    with get_session_factory()() as session:
        row = session.get(NotificationDeliveryIntent, intent.id)
        statuses = session.scalars(
            select(NotificationDeliveryEvent.event_type).where(
                NotificationDeliveryEvent.intent_id == intent.id,
                NotificationDeliveryEvent.event_type == "provider_status_delivered",
            )
        ).all()
    assert row.status == "delivered"
    assert len(statuses) == 1


def test_legacy_reminder_rows_carry_no_phone_number(client: TestClient, phone_env) -> None:
    fake = FakeProvider()
    with fake.installed():
        token, company_id = _setup_opted_in_sms(client, phone_env, fake)
        _due_hearing(client, token, "LEG-1", ["in_app", "sms"])
    with get_session_factory()() as session:
        rows = session.scalars(
            select(HearingReminder).where(
                HearingReminder.company_id == company_id, HearingReminder.channel == "sms"
            )
        ).all()
        snapshots = [i.recipient_snapshot_json for i in _phone_intents(company_id)]
    assert rows and all(row.recipient_phone is None for row in rows)
    assert all(PHONE not in json.dumps(snapshot) for snapshot in snapshots)
