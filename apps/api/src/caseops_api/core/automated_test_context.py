"""Request-local marker that prevents automated tests from spending real money."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

NO_PAID_PROVIDERS_HEADER = "X-CaseOps-Automated-Test"
NO_PAID_PROVIDERS_VALUE = "no-paid-providers"
# Automated verification may additionally ask for a paid lookup to be answered
# from stored, integrity-verified, fresh provider evidence instead of being
# rejected. It never enables a provider call and has no effect on human traffic.
PROVIDER_REPLAY_HEADER = "X-CaseOps-Provider-Replay"
PROVIDER_REPLAY_VALUE = "verified-fresh"

_paid_provider_calls_blocked: ContextVar[bool] = ContextVar(
    "caseops_paid_provider_calls_blocked",
    default=False,
)
_provider_replay_requested: ContextVar[bool] = ContextVar(
    "caseops_provider_replay_requested",
    default=False,
)


def set_automated_test_request(value: str | None) -> Token[bool]:
    blocked = (value or "").strip().lower() == NO_PAID_PROVIDERS_VALUE
    return _paid_provider_calls_blocked.set(blocked)


def reset_automated_test_request(token: Token[bool]) -> None:
    _paid_provider_calls_blocked.reset(token)


def paid_providers_blocked_for_request() -> bool:
    return _paid_provider_calls_blocked.get()


def set_provider_replay_request(value: str | None) -> Token[bool]:
    requested = (value or "").strip().lower() == PROVIDER_REPLAY_VALUE
    return _provider_replay_requested.set(requested)


def reset_provider_replay_request(token: Token[bool]) -> None:
    _provider_replay_requested.reset(token)


def provider_replay_requested() -> bool:
    """True only for an automated no-paid request that explicitly opted in."""

    return _provider_replay_requested.get() and paid_providers_blocked_for_request()


@contextmanager
def restored_no_paid_marker(persisted: bool) -> Iterator[None]:
    """Re-enter a queued job's persisted no-paid marker outside its request.

    A worker has no request headers. The marker captured when the row was
    queued is restored before any embedding or model call; an already-blocked
    context stays blocked. Replay permission is request-local and never
    queued, so it is cleared.
    """

    marker = set_automated_test_request(
        NO_PAID_PROVIDERS_VALUE if persisted or paid_providers_blocked_for_request() else None
    )
    replay = set_provider_replay_request(None)
    try:
        yield
    finally:
        reset_provider_replay_request(replay)
        reset_automated_test_request(marker)


__all__ = [
    "NO_PAID_PROVIDERS_HEADER",
    "NO_PAID_PROVIDERS_VALUE",
    "PROVIDER_REPLAY_HEADER",
    "PROVIDER_REPLAY_VALUE",
    "paid_providers_blocked_for_request",
    "provider_replay_requested",
    "reset_automated_test_request",
    "reset_provider_replay_request",
    "restored_no_paid_marker",
    "set_automated_test_request",
    "set_provider_replay_request",
]
