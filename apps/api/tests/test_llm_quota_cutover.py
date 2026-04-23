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
        Exception("insufficient_quota: please add credits"),
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


def test_openai_provider_wraps_insufficient_quota_as_quota_exhausted(
    monkeypatch: pytest.MonkeyPatch,
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
                raise Exception(
                    "Error code: 429 - "
                    "{'error': {'code': 'insufficient_quota', "
                    "'message': 'You exceeded your current quota'}}",
                )

    monkeypatch.setattr(provider._client, "chat", _FakeChat())

    with pytest.raises(LLMQuotaExhaustedError):
        provider.generate([LLMMessage(role="user", content="hi")])


def test_drafting_quota_error_routes_to_openai_not_haiku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The drafting service's error handler must:

    - On ``LLMQuotaExhaustedError`` from the primary provider, skip
      the (futile) Haiku retry and call OpenAI directly.
    - When OpenAI succeeds, return the OpenAI completion as the
      successful draft.

    Verified by spying on which fallback helpers are called."""
    from caseops_api.services import drafting as drafting_mod

    haiku_calls: list[bool] = []
    openai_calls: list[bool] = []

    def _fake_haiku() -> None:
        haiku_calls.append(True)
        return None

    class _FakeOpenAI:
        name = "openai"
        model = "gpt-5.1"

        def generate(self, messages, **_kwargs):
            openai_calls.append(True)
            raise AssertionError(
                "drafting helper should call generate_structured, not generate"
            )

    def _fake_openai_provider():
        return _FakeOpenAI()

    monkeypatch.setattr(
        drafting_mod, "_haiku_fallback_provider", _fake_haiku
    )
    monkeypatch.setattr(
        drafting_mod, "_openai_fallback_provider", _fake_openai_provider
    )

    # Spy on the inner invoke shape: drafting's
    # ``_generate_draft_via_openai(invoke, root_exc)`` calls
    # ``invoke(openai_provider)``. We simulate a successful OpenAI
    # response so the helper returns rather than raising.
    sentinel_ok = ("RESPONSE_OK", "COMPLETION_OK")

    def _fake_invoke(p):
        # The helper passes the OpenAI provider here. If we got the
        # _FakeOpenAI we expected, return the success sentinel.
        assert isinstance(p, _FakeOpenAI), (
            "drafting must invoke OpenAI fallback, not Haiku"
        )
        return sentinel_ok

    quota_exc = LLMQuotaExhaustedError("Anthropic credit balance is too low")
    result = drafting_mod._generate_draft_via_openai(_fake_invoke, quota_exc)
    assert result == sentinel_ok
    # Helper does NOT consult Haiku — that's the whole point of the
    # quota cutover branch.
    assert haiku_calls == []
    # OpenAI provider must have been built.
    assert openai_calls == []  # _FakeOpenAI.generate was not called directly


def test_drafting_openai_unconfigured_raises_actionable_422() -> None:
    """When OpenAI isn't configured (no ``CASEOPS_OPENAI_API_KEY``),
    the cutover helper must surface a 422 with a detail string the
    user can act on — not a 500."""
    from fastapi import HTTPException

    from caseops_api.services import drafting as drafting_mod

    quota_exc = LLMQuotaExhaustedError("Anthropic credit balance is too low")
    # _openai_fallback_provider returns None when no key is configured.
    # In test env we have no CASEOPS_OPENAI_API_KEY, so this is the
    # natural state.

    with pytest.raises(HTTPException) as info:
        drafting_mod._generate_draft_via_openai(
            lambda _p: ("R", "C"), quota_exc,
        )
    assert info.value.status_code == 422
    detail = info.value.detail
    assert "OpenAI" in detail
    assert "LLMQuotaExhaustedError" in detail
    # Actionability: must mention either a retry path or a support
    # contact so the lawyer knows what to do next.
    lowered = detail.lower()
    assert "retry" in lowered or "support" in lowered
