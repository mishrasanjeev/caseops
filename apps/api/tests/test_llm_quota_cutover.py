"""Hard 402 cutover from Anthropic to OpenAI (gpt-5.1).

Anthropic's "credit balance is too low" error means *every* model on
that key (Opus, Sonnet, Haiku) will fail. Retrying on Haiku is wasted
work. The drafting / recommendations / hearing-pack / matter-summary /
contract-intelligence services should detect the typed
``LLMQuotaExhaustedError`` and immediately retry on OpenAI.

These tests cover:

1. ``AnthropicProvider`` raises ``LLMQuotaExhaustedError`` (subclass
   of ``LLMProviderError``) when the wire returns "credit balance is
   too low" — by HTTP status 402 OR by message substring.
2. ``OpenAIProvider`` raises ``LLMQuotaExhaustedError`` on
   ``insufficient_quota`` for symmetry.
3. ``_is_quota_exhausted`` distinguishes quota errors from generic
   503 / timeout / overload errors so the existing Haiku fallback
   path stays untouched for transient upstream blips.
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
        Exception("Your credit balance is too low to access the Anthropic API."),
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
        _StatusErr(503, "Anthropic 503 overloaded — please retry"),
        _StatusErr(429, "rate_limit_exceeded: too many requests"),
        Exception("connection timeout after 60s"),
        Exception("invalid model name"),
    ],
)
def test_is_quota_exhausted_does_not_misfire_on_transient_errors(
    exc: Exception,
) -> None:
    """Transient or retryable errors must NOT be treated as quota-
    exhausted — they belong on the existing Haiku fallback path."""
    assert _is_quota_exhausted(exc) is False


def test_anthropic_provider_wraps_402_as_quota_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the Anthropic SDK raises a 402 (credit balance too low),
    ``AnthropicProvider.generate`` must raise
    ``LLMQuotaExhaustedError`` so the service-layer cutover catches
    it before the (futile) Haiku retry."""
    from caseops_api.services.llm import AnthropicProvider, LLMMessage

    provider = AnthropicProvider(model="claude-opus-4-7", api_key="sk-fake")

    class _FakeMessages:
        def create(self, **_kwargs):
            raise _StatusErr(
                402,
                "Your credit balance is too low to access the Anthropic API.",
            )

    monkeypatch.setattr(provider._client, "messages", _FakeMessages())

    with pytest.raises(LLMQuotaExhaustedError):
        provider.generate([LLMMessage(role="user", content="hi")])


def test_anthropic_provider_keeps_other_errors_as_generic_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 503 / overload must continue to surface as plain
    ``LLMProviderError`` so the existing Haiku fallback path is
    unchanged."""
    from caseops_api.services.llm import AnthropicProvider, LLMMessage

    provider = AnthropicProvider(model="claude-opus-4-7", api_key="sk-fake")

    class _FakeMessages:
        def create(self, **_kwargs):
            raise _StatusErr(503, "Anthropic 503 overloaded")

    monkeypatch.setattr(provider._client, "messages", _FakeMessages())

    with pytest.raises(LLMProviderError) as info:
        provider.generate([LLMMessage(role="user", content="hi")])
    # Specifically NOT the quota-exhausted child.
    assert not isinstance(info.value, LLMQuotaExhaustedError)


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
    """OpenAI's ``insufficient_quota`` must also be wrapped so a
    cross-provider OpenAI fallback that *also* runs out of credits
    produces a typed error rather than a generic provider failure."""
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


# Tests test_drafting_quota_error_routes_to_openai_not_haiku and
# test_drafting_openai_unconfigured_raises_actionable_422 were removed
# 2026-04-30 / 2026-05-01 with the gpt-5.1-only cutover (commit 39cd459)
# — the Anthropic→Haiku→OpenAI fallback ladder + its helper functions
# (_haiku_fallback_provider, _generate_draft_via_openai) no longer
# exist. The single-call shape is exercised by
# tests/test_drafting_studio.py::test_generate_draft_provider_error_returns_actionable_422.
