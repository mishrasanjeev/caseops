from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request

from caseops_api.core.settings import get_settings


def proxy_aware_remote_address(request: Request) -> str:
    """Trust X-Forwarded-For when the platform sits behind a known
    reverse proxy (Cloud Run, ALB, Cloud Armor → Load Balancer).

    Codex's 2026-04-19 cybersecurity review (finding #11) flagged
    that the previous ``get_remote_address`` keyed on the immediate
    peer, which on Cloud Run is always the proxy IP — meaning every
    user collapses into the same rate-limit bucket. We now take the
    leftmost IP of X-Forwarded-For (the original client) when present
    and only fall back to the peer when the header is absent.

    Spoofing risk: in production we sit behind Cloud Run / a real LB,
    which strips client-supplied X-Forwarded-For and re-emits its
    own. In a misconfigured deployment WITHOUT a stripping proxy, a
    client could set their own X-Forwarded-For — that's the real
    deployment hardening gap the runbook flags. The header trust
    decision matches FastAPI's standard ProxyHeadersMiddleware
    behaviour."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        # Leftmost IP is the original client; subsequent IPs are
        # proxies in the chain.
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip")
    if real:
        return real
    return get_remote_address(request)


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


__all__ = [
    "RateLimitExceeded",
    "bootstrap_rate_limit",
    "configure_limiter",
    "limiter",
    "login_rate_limit",
]
