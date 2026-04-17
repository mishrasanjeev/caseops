from __future__ import annotations

import json

import pytest
from pydantic import BaseModel

from caseops_api.core.settings import get_settings
from caseops_api.services.llm import (
    LLMCallContext,
    LLMCompletion,
    LLMMessage,
    LLMProviderError,
    LLMResponseFormatError,
    MockProvider,
    build_provider,
    generate_structured,
)


class _Option(BaseModel):
    label: str
    confidence: str
    supporting_citations: list[str] = []


class _Structured(BaseModel):
    title: str
    options: list[_Option]
    confidence: str


def _prompt(structured: bool) -> list[LLMMessage]:
    return [
        LLMMessage(role="system", content="You are a CaseOps legal reasoner."),
        LLMMessage(
            role="user",
            content=(
                ("Respond with json. " if structured else "")
                + "MATTER_TITLE: State v. Rao\n"
                "FORUM: high_court\n"
                "- CITATION: Ssangyong Engg v. NHAI (2019)\n"
                "- CITATION: Patel Engg v. Union of India (2008)\n"
            ),
        ),
    ]


def test_mock_provider_plain_is_deterministic() -> None:
    provider = MockProvider()
    result_a = provider.generate(_prompt(structured=False))
    result_b = provider.generate(_prompt(structured=False))
    assert result_a.text == result_b.text
    assert result_a.provider == "mock"
    assert result_a.prompt_tokens > 0
    assert result_a.completion_tokens > 0
    assert result_a.latency_ms >= 1


def test_mock_provider_structured_returns_valid_json() -> None:
    provider = MockProvider()
    completion = provider.generate(_prompt(structured=True))
    payload = json.loads(completion.text)
    assert "options" in payload
    assert payload["options"][0]["supporting_citations"]
    assert "Ssangyong" in payload["options"][0]["supporting_citations"][0]


def test_generate_structured_validates_schema() -> None:
    provider = MockProvider()
    validated, completion = generate_structured(
        provider,
        schema=_Structured,
        messages=_prompt(structured=True),
        context=LLMCallContext(purpose="unit-test"),
    )
    assert isinstance(validated, _Structured)
    assert validated.options
    assert isinstance(completion, LLMCompletion)


def test_generate_structured_raises_on_invalid_json() -> None:
    class _BrokenProvider:
        name = "broken"
        model = "broken-1"

        def generate(self, messages, **kwargs):  # type: ignore[override]
            return LLMCompletion(
                text="not json at all",
                provider="broken",
                model="broken-1",
                prompt_tokens=1,
                completion_tokens=1,
                latency_ms=1,
            )

    with pytest.raises(LLMResponseFormatError):
        generate_structured(
            _BrokenProvider(),
            schema=_Structured,
            messages=_prompt(structured=True),
            context=LLMCallContext(purpose="unit-test"),
        )


def test_generate_structured_raises_on_schema_mismatch() -> None:
    class _UnexpectedProvider:
        name = "unexpected"
        model = "unexpected-1"

        def generate(self, messages, **kwargs):  # type: ignore[override]
            return LLMCompletion(
                text=json.dumps({"title": "ok", "options": "not-a-list"}),
                provider="unexpected",
                model="unexpected-1",
                prompt_tokens=1,
                completion_tokens=1,
                latency_ms=1,
            )

    with pytest.raises(LLMResponseFormatError):
        generate_structured(
            _UnexpectedProvider(),
            schema=_Structured,
            messages=_prompt(structured=True),
            context=LLMCallContext(purpose="unit-test"),
        )


def test_on_model_run_hook_receives_completion_and_context() -> None:
    provider = MockProvider()
    captured: list[tuple[LLMCompletion, LLMCallContext, list[LLMMessage]]] = []

    def writer(completion, context, messages):  # type: ignore[override]
        captured.append((completion, context, messages))

    ctx = LLMCallContext(
        tenant_id="tenant-123",
        matter_id="matter-abc",
        purpose="forum_recommendation",
    )
    generate_structured(
        provider,
        schema=_Structured,
        messages=_prompt(structured=True),
        context=ctx,
        on_model_run=writer,
    )
    assert len(captured) == 1
    completion, context, _ = captured[0]
    assert context.tenant_id == "tenant-123"
    assert context.matter_id == "matter-abc"
    assert completion.provider == "mock"


def test_build_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    provider = build_provider()
    assert provider.name == "mock"


def test_build_provider_requires_api_key_for_real_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("CASEOPS_LLM_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(LLMProviderError):
        build_provider()


def test_build_provider_rejects_unknown_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "totally-made-up")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "k")
    get_settings.cache_clear()
    with pytest.raises(LLMProviderError):
        build_provider()
