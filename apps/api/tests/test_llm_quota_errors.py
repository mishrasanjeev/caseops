"""OpenAI quota-exhaustion handling.

These tests cover:

1. ``LLMQuotaExhaustedError`` remains a provider-error subtype.
2. ``OpenAIProvider`` raises it on
   ``insufficient_quota`` for symmetry.
3. ``_is_quota_exhausted`` distinguishes quota errors from generic
   503 / timeout / overload errors.
"""
from __future__ import annotations

import pytest

from caseops_api.services.llm import (
    LLMProviderError,
    LLMQuotaExhaustedError,
    _is_quota_exhausted,
)


class _StatusErr(Exception):
    """Mimic an SDK exception that exposes ``status_code``."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_quota_error_is_subclass_of_provider_error() -> None:
    """The cutover branches catch ``LLMQuotaExhaustedError`` *before*
    the broader ``LLMProviderError`` block. The subclass relationship
    keeps the existing fallback paths working when callers only care
    about the parent."""
    assert issubclass(LLMQuotaExhaustedError, LLMProviderError)


@pytest.mark.parametrize(
    "exc",
    [
        _StatusErr(402, "Payment Required"),
        Exception("credit_balance_exhausted"),
        Exception("insufficient_quota: please add credits"),
        Exception("No credits remaining for this organization"),
        Exception("You exceeded your current quota, please check your plan."),
        Exception("billing_hard_limit_reached"),
    ],
)
def test_is_quota_exhausted_detects_provider_billing_errors(exc: Exception) -> None:
    """Sniffer picks up the marker phrases each provider uses for
    "you ran out of paid credits"."""
    assert _is_quota_exhausted(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        _StatusErr(503, "provider overloaded — please retry"),
        _StatusErr(429, "rate_limit_exceeded: too many requests"),
        Exception("connection timeout after 60s"),
        Exception("invalid model name"),
    ],
)
def test_is_quota_exhausted_does_not_misfire_on_transient_errors(
    exc: Exception,
) -> None:
    """Transient or retryable errors must not be treated as quota exhausted."""
    assert _is_quota_exhausted(exc) is False


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 - {'error': {'code': 'insufficient_quota'}}",
        "Error code: 429 - {'error': {'code': 'credit_balance_exhausted'}}",
        "Error code: 429 - No credits remaining for this organization",
    ],
)
def test_openai_provider_wraps_exhausted_credit_as_quota_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    """OpenAI's ``insufficient_quota`` is surfaced as a typed error."""
    from caseops_api.services.llm import LLMMessage, OpenAIProvider

    provider = OpenAIProvider(model="gpt-5.1", api_key="sk-fake")

    class _FakeChat:
        class completions:
            @staticmethod
            def create(**_kwargs):
                raise Exception(message)

    monkeypatch.setattr(provider._client, "chat", _FakeChat())

    with pytest.raises(LLMQuotaExhaustedError):
        provider.generate([LLMMessage(role="user", content="hi")])
