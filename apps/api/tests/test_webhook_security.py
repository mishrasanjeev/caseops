from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from caseops_api.services.pine_labs import (
    PineLabsCreatePaymentLinkResult,
    PineLabsPaymentStatusResult,
)
from tests.test_auth_company import auth_headers, bootstrap_company

WEBHOOK_SECRET = b"pine-webhook-secret"


class FakeGateway:
    def __init__(self, provider_order_id: str = "pl-order-1") -> None:
        self.provider_order_id = provider_order_id

    def create_payment_link(self, **_kwargs):
        return PineLabsCreatePaymentLinkResult(
            provider_order_id=self.provider_order_id,
            payment_url=f"https://pay.pinelabs.test/{self.provider_order_id}",
            provider_reference="plink-ref",
            status="created",
            raw_payload={
                "order_id": self.provider_order_id,
                "payment_url": f"https://pay.pinelabs.test/{self.provider_order_id}",
                "status": "created",
                "customer_email": "leak@example.com",
                "customer_phone": "+91-9000000000",
                "cvv": "123",
            },
        )

    def parse_webhook_payload(self, payload):
        return PineLabsPaymentStatusResult(
            provider_order_id=str(payload.get("order_id")),
            provider_reference="plink-ref",
            status=str(payload.get("status", "paid")),
            amount_received_minor=int(payload.get("amount_received_minor", 0)),
            raw_payload=dict(payload),
        )


def _sign(body: bytes, secret: bytes = WEBHOOK_SECRET) -> str:
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def _setup_invoice_with_attempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str, str]:
    monkeypatch.setattr(
        "caseops_api.services.payments._get_gateway_client",
        lambda: FakeGateway(),
    )

    bootstrap_payload = bootstrap_company(client)
    token = str(bootstrap_payload["access_token"])

    matter_response = client.post(
        "/api/matters/",
        headers=auth_headers(token),
        json={
            "title": "Webhook Security Suite",
            "matter_code": "WHS-2026-001",
            "practice_area": "Commercial",
            "forum_level": "high_court",
            "status": "active",
        },
    )
    matter_id = matter_response.json()["id"]

    invoice_response = client.post(
        f"/api/matters/{matter_id}/invoices",
        headers=auth_headers(token),
        json={
            "invoice_number": "INV-WHS-001",
            "issued_on": "2026-04-16",
            "include_uninvoiced_time_entries": False,
            "manual_items": [{"description": "Retainer", "amount_minor": 120000}],
        },
    )
    invoice_id = invoice_response.json()["id"]

    client.post(
        f"/api/payments/matters/{matter_id}/invoices/{invoice_id}/pine-labs/link",
        headers=auth_headers(token),
        json={"customer_name": "Ops Desk"},
    )
    return token, matter_id, invoice_id


def test_webhook_without_configured_secret_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CASEOPS_PINE_LABS_WEBHOOK_SECRET", "")
    from caseops_api.core.settings import get_settings

    get_settings.cache_clear()

    body = json.dumps({"order_id": "x", "status": "paid"}).encode()
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": "anything",
        },
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_webhook_with_tampered_signature_returns_401(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_invoice_with_attempt(client, monkeypatch)
    body = json.dumps({"order_id": "pl-order-1", "status": "paid"}).encode()
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": "deadbeef" * 8,
        },
    )
    assert response.status_code == 401


def test_webhook_with_unknown_order_is_ignored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_invoice_with_attempt(client, monkeypatch)
    payload = {"order_id": "unknown-order", "status": "paid", "amount_received_minor": 0}
    body = json.dumps(payload).encode()
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": _sign(body),
        },
    )
    assert response.status_code == 200
    assert response.json()["accepted"] is True


def test_webhook_is_idempotent_on_repeat_event_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_invoice_with_attempt(client, monkeypatch)
    payload = {
        "order_id": "pl-order-1",
        "status": "paid",
        "amount_received_minor": 120000,
        "event_id": "evt-abc-1",
    }
    body = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "X-PineLabs-Signature": _sign(body),
    }

    first = client.post("/api/payments/pine-labs/webhook", content=body, headers=headers)
    second = client.post("/api/payments/pine-labs/webhook", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["already_processed"] is False
    assert second.json()["already_processed"] is True


def test_webhook_rejects_cross_tenant_attempt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_invoice_with_attempt(client, monkeypatch)

    from sqlalchemy import select, update

    from caseops_api.db.models import MatterInvoicePaymentAttempt
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        session.execute(
            update(MatterInvoicePaymentAttempt).values(
                merchant_order_id="other-tenant-INV-1",
            )
        )
        session.commit()

    payload = {
        "order_id": "pl-order-1",
        "status": "paid",
        "amount_received_minor": 120000,
        "event_id": "evt-cross-1",
    }
    body = json.dumps(payload).encode()
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": _sign(body),
        },
    )
    assert response.status_code == 409

    with factory() as session:
        attempt = session.scalar(select(MatterInvoicePaymentAttempt))
        assert attempt is not None
        assert attempt.status != "paid"


def test_webhook_redacts_sensitive_fields_before_persistence(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _setup_invoice_with_attempt(client, monkeypatch)

    payload = {
        "order_id": "pl-order-1",
        "status": "paid",
        "amount_received_minor": 120000,
        "event_id": "evt-redact-1",
        "customer_email": "leak@example.com",
        "customer_phone": "+91-9000000000",
        "card_number": "4111111111111111",
        "cvv": "321",
    }
    body = json.dumps(payload).encode()
    response = client.post(
        "/api/payments/pine-labs/webhook",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-PineLabs-Signature": _sign(body),
        },
    )
    assert response.status_code == 200

    from sqlalchemy import select

    from caseops_api.db.models import (
        MatterInvoicePaymentAttempt,
        PaymentWebhookEvent,
    )
    from caseops_api.db.session import get_session_factory

    factory = get_session_factory()
    with factory() as session:
        events = list(session.scalars(select(PaymentWebhookEvent)))
        attempts = list(session.scalars(select(MatterInvoicePaymentAttempt)))

    for event in events:
        assert "leak@example.com" not in event.payload_json
        assert "9000000000" not in event.payload_json
        assert "4111111111111111" not in event.payload_json
        assert "321" not in event.payload_json or "[redacted]" in event.payload_json

    for attempt in attempts:
        if attempt.provider_payload_json:
            assert "leak@example.com" not in attempt.provider_payload_json
            assert "9000000000" not in attempt.provider_payload_json
