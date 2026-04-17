from __future__ import annotations

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from caseops_api.core.settings import get_settings

limiter = Limiter(
    key_func=get_remote_address,
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
