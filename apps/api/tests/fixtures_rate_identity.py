"""Rate-identity claims without importing application or integration-test modules."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

import pytest

from caseops_api.core.settings import get_settings


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
