from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pytest
from sqlalchemy import func, select
from starlette.requests import Request

from caseops_api.core.rate_limit import limiter, proxy_aware_remote_address
from caseops_api.core.settings import get_settings
from caseops_api.db.models import BillingEnrollment
from caseops_api.db.session import get_session_factory
from tests import test_rate_limiting as rate_tests
from tests import test_seo_demo_20261009 as demo_tests
from tests.test_rate_limiting import _bootstrap_once
from tests.test_seo_demo_20261009 import URL, payload

rate_limited_client = rate_tests.rate_limited_client
offline_notifications = demo_tests.offline_notifications


@pytest.fixture
def edge_key(monkeypatch):
    key = secrets.token_hex(32)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_SECRET", key)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_HTTPS", "true")
    get_settings.cache_clear()
    return key


def edge_headers(key, ip="192.0.2.4"):
    return {"x-caseops-edge-client-ip": ip, "x-caseops-edge-attestation": key}


def forward_headers(
    key, ip="2001:db8::1", method="GET", path="/api/health/rate-identity", timestamp=None
):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    message = f"caseops-rate-v1\n{method}\n{path}\n{ip}\n{timestamp}".encode("ascii")
    return {
        "x-caseops-rate-client-ip": ip,
        "x-caseops-rate-timestamp": timestamp,
        "x-caseops-rate-signature": hmac.new(
            key.encode("ascii"), message, hashlib.sha256
        ).hexdigest(),
    }


def fake_request(headers, method="GET", path="/api/health/rate-identity", query=b"", raw_path=None):
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "scheme": "http",
            "raw_path": raw_path or path.encode("ascii"),
            "query_string": query,
            "headers": [(k.encode("ascii"), v.encode("ascii")) for k, v in headers.items()],
            "client": ("192.0.2.1", 4000),
        }
    )


def test_untrusted_forwarding_headers_cannot_choose_rate_key():
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": URL,
            "headers": [
                (b"x-forwarded-for", b"198.51.100.99, 192.0.2.8"),
                (b"x-real-ip", b"198.51.100.98"),
            ],
            "client": ("192.0.2.1", 4000),
        }
    )
    assert proxy_aware_remote_address(request) == "192.0.2.1"


def test_demo_rotating_raw_headers_still_rejects_sixth(client, monkeypatch, offline_notifications):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        statuses = [
            client.post(
                URL,
                json=payload(),
                headers={
                    "x-forwarded-for": f"198.51.100.{n}",
                    "x-real-ip": f"203.0.113.{n}",
                },
            ).status_code
            for n in range(1, 7)
        ]
        assert statuses == [200] * 5 + [429]
        with get_session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 5
        assert len(offline_notifications) == 5
    finally:
        limiter.reset()


def test_login_rotating_raw_headers_still_hits_threshold(rate_limited_client):
    assert _bootstrap_once(rate_limited_client, "edge-rate") == 200
    statuses = [
        rate_limited_client.post(
            "/api/auth/login",
            json={
                "email": "edge-rate@ratefirm.in",
                "password": "wrong-password",
                "company_slug": "edge-rate",
            },
            headers={"x-forwarded-for": f"198.51.100.{n}", "x-real-ip": f"203.0.113.{n}"},
        ).status_code
        for n in range(1, 6)
    ]
    assert statuses == [401] * 3 + [429] * 2


@pytest.mark.parametrize(
    "ip,canonical",
    [
        ("192.0.2.4", "192.0.2.4"),
        ("2001:0DB8:0:0:0:0:0:1", "2001:db8::1"),
        ("::ffff:192.0.2.1", "192.0.2.1"),
    ],
)
def test_attested_ip_is_strict_and_canonical(edge_key, ip, canonical):
    from caseops_api.core.rate_identity import resolve_rate_identity

    identity = resolve_rate_identity(fake_request(edge_headers(edge_key, ip)))
    assert identity.client_ip == canonical and identity.provenance == "edge"
    assert canonical not in repr(identity)


@pytest.mark.parametrize(
    "ip",
    [
        "",
        " 192.0.2.4",
        "192.0.2.4 ",
        "192.0.2.4,192.0.2.5",
        "[2001:db8::1]",
        "fe80::1%eth0",
        "192.000.2.4",
        "256.1.1.1",
        "x" * 4096,
        "2001:db8::1:443:99999",
        "192.0.2.1:443",
    ],
)
def test_bad_edge_ip_is_rejected(edge_key, ip):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity

    with pytest.raises(InvalidRateIdentity, match="^Invalid rate identity claims.$"):
        resolve_rate_identity(fake_request(edge_headers(edge_key, ip)))


@pytest.mark.parametrize(
    "change",
    [
        {"x-caseops-edge-attestation": ""},
        {"x-caseops-edge-attestation": "wrong"},
        {"x-caseops-edge-attestation": "0" * 64},
        {"x-caseops-edge-attestation": "x" * 4096},
    ],
)
def test_forged_attestation_never_authorizes(edge_key, change):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity

    with pytest.raises(InvalidRateIdentity):
        resolve_rate_identity(fake_request(edge_headers(edge_key) | change))


@pytest.mark.parametrize(
    "name",
    [
        "x-caseops-edge-client-ip",
        "x-caseops-edge-attestation",
        "x-caseops-rate-client-ip",
        "x-caseops-rate-timestamp",
        "x-caseops-rate-signature",
    ],
)
def test_duplicate_claims_rejected(edge_key, name):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity

    request = fake_request(edge_headers(edge_key) | forward_headers(edge_key))
    request.scope["headers"].append((name.encode("ascii"), b"duplicate"))
    with pytest.raises(InvalidRateIdentity):
        resolve_rate_identity(request)


@pytest.mark.parametrize(
    "method,path,delta,query",
    [
        ("POST", "/api/health/rate-identity", 0, b""),
        ("GET", "/api/auth/login", 0, b""),
        ("GET", "/api/health/rate-identity", -31, b""),
        ("GET", "/api/health/rate-identity", 6, b""),
        ("GET", "/api/health/rate-identity", 0, b"a=1"),
    ],
)
def test_signature_is_short_lived_and_target_bound(edge_key, method, path, delta, query):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity

    headers = forward_headers(edge_key, timestamp=int(time.time()) + delta)
    with pytest.raises(InvalidRateIdentity):
        resolve_rate_identity(fake_request(headers, method, path, query))


@pytest.mark.parametrize(
    "change",
    [
        {"x-caseops-rate-signature": "0" * 64},
        {"x-caseops-rate-timestamp": "9" * 4096},
        {"x-caseops-rate-client-ip": "192.0.2.9"},
        {"x-caseops-rate-client-ip": "2001:0db8::1"},
    ],
)
def test_signature_tampering_rejected(edge_key, change):
    from caseops_api.core.rate_identity import InvalidRateIdentity, resolve_rate_identity

    with pytest.raises(InvalidRateIdentity):
        resolve_rate_identity(fake_request(forward_headers(edge_key) | change))


def test_signed_web_ip_wins_over_api_edge_egress(edge_key):
    from caseops_api.core.rate_identity import resolve_rate_identity

    identity = resolve_rate_identity(
        fake_request(edge_headers(edge_key) | forward_headers(edge_key))
    )
    assert identity.provenance == "web-forward" and identity.client_ip == "2001:db8::1"


@pytest.mark.parametrize(
    "fixture", ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
@pytest.mark.parametrize("mode", ["edge", "web-forward"])
def test_attested_demo_callers_have_independent_buckets(
    request, fixture, mode, monkeypatch, offline_notifications
):
    client = request.getfixturevalue(fixture)
    key = secrets.token_hex(32)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_SECRET", key)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_HTTPS", "true")
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_REQUIRED", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()

    def claims(ip):
        if mode == "edge":
            return edge_headers(key, ip)
        return edge_headers(key, "192.0.2.200") | forward_headers(key, ip, "POST", URL)

    try:
        statuses = [
            client.post(
                URL,
                json=payload(),
                headers=claims("192.0.2.4")
                | {
                    "x-forwarded-for": f"198.51.100.{n}",
                    "x-real-ip": f"203.0.113.{n}",
                },
            ).status_code
            for n in range(1, 7)
        ]
        assert statuses == [200] * 5 + [429]
        assert client.post(URL, json=payload(), headers=claims("2001:db8::1")).status_code == 200
        assert (
            client.post(URL, json=payload(), headers={"x-forwarded-for": "192.0.2.99"}).status_code
            == 403
        )
        with get_session_factory()() as session:
            assert session.scalar(select(func.count()).select_from(BillingEnrollment)) == 6
        assert len(offline_notifications) == 6
    finally:
        limiter.reset()


@pytest.mark.parametrize(
    "fixture", ["client", pytest.param("isolated_postgres_client", marks=pytest.mark.postgres)]
)
def test_attested_auth_callers_have_independent_buckets(request, fixture, monkeypatch):
    client = request.getfixturevalue(fixture)
    key = secrets.token_hex(32)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_SECRET", key)
    monkeypatch.setenv("CASEOPS_RATE_IDENTITY_EDGE_HTTPS", "true")
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_LOGIN_PER_MINUTE", "3")
    get_settings.cache_clear()
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        statuses = [
            client.post(
                "/api/auth/login",
                json={
                    "email": "absent@example.com",
                    "password": "wrong-password",
                    "company_slug": "absent",
                },
                headers=edge_headers(key)
                | {
                    "x-forwarded-for": f"198.51.100.{n}",
                    "x-real-ip": f"203.0.113.{n}",
                },
            ).status_code
            for n in range(1, 6)
        ]
        assert statuses == [401] * 3 + [429] * 2
        assert (
            client.post(
                "/api/auth/login",
                json={
                    "email": "absent@example.com",
                    "password": "wrong-password",
                    "company_slug": "absent",
                },
                headers=edge_headers(key, "2001:db8::1"),
            ).status_code
            == 401
        )
    finally:
        limiter.reset()


def test_public_readiness_has_no_identifiers_or_tracking(client, edge_key, monkeypatch):
    sha = "9" * 40
    monkeypatch.setenv("CASEOPS_RELEASE_SHA", sha)
    get_settings.cache_clear()
    for headers, provenance, ready in [
        ({}, "socket", False),
        (edge_headers(edge_key), "edge", True),
        (edge_headers(edge_key) | forward_headers(edge_key), "web-forward", True),
    ]:
        response = client.get("/api/health/rate-identity", headers=headers)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert response.json() == {"ready": ready, "provenance": provenance, "release_sha": sha}
        assert (
            edge_key not in response.text
            and "192.0.2." not in response.text
            and "2001:db8" not in response.text
        )


def test_required_settings_fail_before_runtime_and_mask_key(monkeypatch):
    from caseops_api.core.rate_identity import validate_rate_identity_settings
    from caseops_api.core.settings import Settings

    for values in [
        {"rate_identity_required": True},
        {"rate_identity_edge_secret": "invalid"},
        {"rate_identity_required": True, "rate_identity_edge_secret": secrets.token_hex(32)},
    ]:
        with pytest.raises(RuntimeError):
            validate_rate_identity_settings(Settings(_env_file=None, **values))
    key = secrets.token_hex(32)
    config = Settings(_env_file=None, rate_identity_edge_secret=key)
    assert key not in repr(config)
