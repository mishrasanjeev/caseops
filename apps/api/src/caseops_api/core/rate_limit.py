from __future__ import annotations

import hashlib

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request

from caseops_api.core.rate_identity import request_rate_identity
from caseops_api.core.settings import get_settings


def proxy_aware_remote_address(request: Request) -> str:
    """Use purpose-verified identity or the unmodified socket peer, never XFF."""
    return request_rate_identity(request).client_ip


limiter = Limiter(
    key_func=proxy_aware_remote_address,
    default_limits=[],
    strategy="fixed-window",
)


def configure_limiter() -> Limiter:
    settings = get_settings()
    limiter.enabled = settings.auth_rate_limit_enabled
    return limiter


def login_rate_limit() -> str:
    return f"{get_settings().auth_rate_limit_login_per_minute}/minute"


def bootstrap_rate_limit() -> str:
    return f"{get_settings().auth_rate_limit_bootstrap_per_hour}/hour"


def tenant_aware_key(request: Request) -> str:
    """EG-004 (2026-04-23): rate-limit AI routes per session, not per
    proxy-IP. The peer IP is the Cloud Run front-end so every tenant
    would otherwise share one bucket.

    Strategy: hash the bearer token (session-stable + opaque) and
    return the prefix as the key. Different tenants → different
    tokens → different buckets. The fallback to peer IP keeps
    pre-auth probes (smoke checks, anonymous health) bucketed too.

    We hash so the limiter's storage never holds the raw token —
    the in-memory store is process-local on Cloud Run today, but a
    Redis-backed store is on the WTBD list and we want this safe
    when that ships.
    """
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[len("Bearer "):]
        return "tk:" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return "ip:" + proxy_aware_remote_address(request)


def portal_request_link_rate_limit() -> str:
    """Phase C-1 hardening (2026-04-24). Defends the magic-link
    request endpoint against email-enumeration timing attacks AND
    against simple flood: ten requests per minute per peer-IP is
    plenty for a real portal user fat-fingering their email a few
    times, but stops a script harvesting addresses."""
    return f"{get_settings().auth_rate_limit_login_per_minute}/minute"


def ai_route_rate_limit() -> str:
    """Per-session limit on expensive AI generation routes (drafting
    generate, hearing-pack assemble, recommendations, matter
    summary regenerate, drafting preview). Tunable via
    CASEOPS_AI_ROUTE_RATE_LIMIT_PER_MINUTE; default 30/minute is
    generous for a partner reviewing a matter and far below what
    runaway abuse would attempt.
    """
    return f"{get_settings().ai_route_rate_limit_per_minute}/minute"


__all__ = [
    "RateLimitExceeded",
    "ai_route_rate_limit",
    "bootstrap_rate_limit",
    "configure_limiter",
    "limiter",
    "login_rate_limit",
    "tenant_aware_key",
]
