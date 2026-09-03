"""Request-local marker that prevents automated tests from spending real money."""

from __future__ import annotations

from contextvars import ContextVar, Token

NO_PAID_PROVIDERS_HEADER = "X-CaseOps-Automated-Test"
NO_PAID_PROVIDERS_VALUE = "no-paid-providers"

_paid_provider_calls_blocked: ContextVar[bool] = ContextVar(
    "caseops_paid_provider_calls_blocked",
    default=False,
)


def set_automated_test_request(value: str | None) -> Token[bool]:
    blocked = (value or "").strip().lower() == NO_PAID_PROVIDERS_VALUE
    return _paid_provider_calls_blocked.set(blocked)


def reset_automated_test_request(token: Token[bool]) -> None:
    _paid_provider_calls_blocked.reset(token)


def paid_providers_blocked_for_request() -> bool:
    return _paid_provider_calls_blocked.get()


__all__ = [
    "NO_PAID_PROVIDERS_HEADER",
    "NO_PAID_PROVIDERS_VALUE",
    "paid_providers_blocked_for_request",
    "reset_automated_test_request",
    "set_automated_test_request",
]
