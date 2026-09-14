"""EH-SGR-06: the inbound email webhook never accepts an unsigned post.

Before 2026-09-14 ``_verify_signature`` returned early in ``mock`` provider
mode, so selecting mock mode anywhere but a test turned a signed webhook into
an anonymous one. These tests pin the property that matters - no provider
mode is a signature waiver - rather than the shape of any one branch.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings

WEBHOOK = "/api/mailbox/inbound/webhook"
SECRET = "inbound-secret-for-tests-at-least-32-bytes-long"
PAYLOAD = {
    "provider_message_id": "msg-eh-sgr-06",
    "to_addresses": ["nobody@inbound.disabled.caseops.local"],
}


@pytest.fixture()
def provider_mode(monkeypatch):
    def configure(mode: str, *, secret: str | None) -> None:
        monkeypatch.setenv("CASEOPS_INBOUND_EMAIL_PROVIDER_MODE", mode)
        if secret is None:
            monkeypatch.delenv("CASEOPS_INBOUND_EMAIL_WEBHOOK_SECRET", raising=False)
        else:
            monkeypatch.setenv("CASEOPS_INBOUND_EMAIL_WEBHOOK_SECRET", secret)
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def _post(client: TestClient, body: bytes, signature: str | None):
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-CaseOps-Inbound-Signature"] = signature
    return client.post(WEBHOOK, content=body, headers=headers)


def _sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.parametrize("mode", ["mock", "production"])
def test_no_provider_mode_accepts_an_unsigned_post(
    client: TestClient, provider_mode, mode: str
) -> None:
    provider_mode(mode, secret=SECRET)
    body = json.dumps(PAYLOAD).encode()

    unsigned = _post(client, body, None)
    assert unsigned.status_code == 401, unsigned.text

    forged = _post(client, body, "sha256=" + "0" * 64)
    assert forged.status_code == 401, forged.text


@pytest.mark.parametrize("mode", ["mock", "production"])
def test_a_mode_without_a_secret_is_unavailable_not_open(
    client: TestClient, provider_mode, mode: str
) -> None:
    """Missing configuration must read as an outage, never as no auth."""

    provider_mode(mode, secret=None)
    body = json.dumps(PAYLOAD).encode()

    response = _post(client, body, None)
    assert response.status_code == 503, response.text


def test_a_correctly_signed_post_passes_the_signature_gate(
    client: TestClient, provider_mode
) -> None:
    """The gate is a gate, not a wall: a valid HMAC reaches the alias lookup.

    404 here is the alias lookup failing on a fixture with no alias, which is
    the first thing after the signature check - so it proves the check passed.
    """

    provider_mode("mock", secret=SECRET)
    body = json.dumps(PAYLOAD).encode()

    response = _post(client, body, _sign(body))
    assert response.status_code == 404, response.text
    assert "alias" in response.text.lower()
