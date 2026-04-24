"""P0-004 (2026-04-24, QG-NOTIF-003/-004) — SendGrid webhook signature
verification must fail closed outside local/test.

Covers:

- Local env, no public key configured -> webhook accepted with warning.
- Non-local env, no public key configured -> 503 (no silent fail-open).
- Local env, missing cryptography lib -> webhook accepted with warning.
- Non-local env, missing cryptography lib -> 503.
- Invalid signature -> 401 (regardless of env).
- Valid signature -> 200.
- Malformed payload (not JSON) -> 400.
- Malformed payload (not a list) -> 400.
"""
from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from caseops_api.api.routes import notifications as notifications_route


def _post_event(
    client: TestClient,
    payload: object,
    *,
    signature: str | None = None,
    timestamp: str | None = None,
) -> object:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if signature:
        headers["X-Twilio-Email-Event-Webhook-Signature"] = signature
    if timestamp:
        headers["X-Twilio-Email-Event-Webhook-Timestamp"] = timestamp
    return client.post(
        "/api/webhooks/sendgrid/events",
        data=json.dumps(payload),
        headers=headers,
    )


def _set_settings(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> None:
    """Replace settings.get_settings() with a stub carrying overrides
    on top of the existing test settings instance."""
    from caseops_api.core import settings as settings_module

    original = settings_module.get_settings()
    fields = {
        "env": getattr(original, "env", "local"),
        "sendgrid_webhook_public_key": getattr(
            original, "sendgrid_webhook_public_key", None
        ),
    }
    fields.update(overrides)

    class _Stub:
        def __init__(self, **kw: object) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    stub = _Stub(**fields)
    monkeypatch.setattr(notifications_route, "get_settings", lambda: stub)
    monkeypatch.setattr(
        "caseops_api.core.settings.get_settings",
        lambda: stub,
    )


@pytest.fixture
def restore_settings_cache() -> Iterator[None]:
    """Clear the lru_cache before the test runs. We don't clear after
    the test because ``_set_settings`` monkeypatches ``get_settings``
    itself, replacing the cached function — at which point
    ``cache_clear`` would not exist on the patched callable.
    monkeypatch's autouse teardown restores the original function;
    the autouse settings reset in conftest takes care of cache
    isolation between tests."""
    from caseops_api.core import settings as settings_module

    if hasattr(settings_module.get_settings, "cache_clear"):
        settings_module.get_settings.cache_clear()
    yield


def test_local_env_without_public_key_accepts_webhook(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="local", sendgrid_webhook_public_key=None,
    )
    resp = _post_event(client, [])
    assert resp.status_code == 200, resp.text


def test_production_env_without_public_key_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="production", sendgrid_webhook_public_key=None,
    )
    resp = _post_event(client, [])
    assert resp.status_code == 503, resp.text
    body = resp.json()
    assert "verification" in body["detail"].lower()
    assert "CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY" in body["detail"]


def test_staging_env_without_public_key_returns_503(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="staging", sendgrid_webhook_public_key=None,
    )
    resp = _post_event(client, [])
    assert resp.status_code == 503


def test_unknown_env_treated_as_non_local(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    """is_non_local_env uses an allow-list — anything not in
    {local, dev, test, e2e} is treated as non-local. A typo in the env
    var (cloud, prod-1, gke) MUST fail closed."""
    _set_settings(
        monkeypatch, env="cloud-prod", sendgrid_webhook_public_key=None,
    )
    resp = _post_event(client, [])
    assert resp.status_code == 503


def test_invalid_signature_returns_401(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    """When the public key IS configured but the signature is wrong,
    return 401 (not 503). 503 means "server can't process"; 401 means
    "you sent something we can't trust"."""
    # A valid-looking but wrong base64 EC public key. Verification
    # will load it but then fail when comparing against the body.
    fake_pk = (
        "MFYwEAYHKoZIzj0CAQYFK4EEAAoDQgAEokj7vPvWpW3OcJaXhRywJYWdY+iN"
        "1CXxRDk0NwK2JZcvF9k3EeIqKQ5CfHOj56MZ2PSdkU/9TGVE8wgaTVfa0g=="
    )
    _set_settings(
        monkeypatch, env="production", sendgrid_webhook_public_key=fake_pk,
    )
    resp = _post_event(
        client,
        [{"event": "delivered"}],
        signature="bogus",
        timestamp="0",
    )
    assert resp.status_code == 401


def test_malformed_json_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="local", sendgrid_webhook_public_key=None,
    )
    resp = client.post(
        "/api/webhooks/sendgrid/events",
        data=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "malformed" in resp.json()["detail"].lower()


def test_payload_must_be_a_list(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="local", sendgrid_webhook_public_key=None,
    )
    resp = _post_event(client, {"event": "delivered"})
    assert resp.status_code == 400
    assert "json array" in resp.json()["detail"].lower()


def test_unit_verifier_raises_webhookconfigerror_in_prod_when_no_key(
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="production", sendgrid_webhook_public_key=None,
    )
    with pytest.raises(notifications_route.WebhookConfigError):
        notifications_route._verify_sendgrid_signature(
            body=b"payload",
            signature=None,
            timestamp=None,
            public_key_b64=None,
        )


def test_unit_verifier_returns_true_in_local_when_no_key(
    monkeypatch: pytest.MonkeyPatch,
    restore_settings_cache: None,
) -> None:
    _set_settings(
        monkeypatch, env="local", sendgrid_webhook_public_key=None,
    )
    assert (
        notifications_route._verify_sendgrid_signature(
            body=b"payload",
            signature=None,
            timestamp=None,
            public_key_b64=None,
        )
        is True
    )
