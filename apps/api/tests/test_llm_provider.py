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
                ("Respond with json. " if structured else "") + "MATTER_TITLE: State v. Rao\n"
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


def test_mock_provider_litigation_strategy_matches_strict_nested_schema() -> None:
    from caseops_api.services.litigation_strategy import _LLMStrategyResponse

    provider = MockProvider()
    completion = provider.generate(
        [
            LLMMessage(role="system", content="You are the litigation strategy engine."),
            LLMMessage(
                role="user",
                content=(
                    "Respond with json. Produce a litigation strategy.\n"
                    "MATTER_TITLE: State v. Rao\n"
                    "FORUM: high_court\n"
                    "RETRIEVED_AUTHORITIES:\n"
                    "[1] CITATION: Ssangyong Engg v. NHAI (2019)\n"
                    "SCHEMA includes recommended_route and forum_sequence."
                ),
            ),
        ]
    )

    validated = _LLMStrategyResponse.model_validate_json(completion.text)

    assert validated.recommended_route.supporting_citations == ["[1] Ssangyong Engg v. NHAI (2019)"]
    assert validated.forum_sequence[0].forum_level == "high_court_single_bench"


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
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "")
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


# ---------------------------------------------------------------
# OpenAI reasoning-model max_completion_tokens floor.
#
# Regression for the 2026-05-03 prod incident: gpt-5-mini bills
# hidden reasoning tokens against ``max_completion_tokens``. With
# the operator-configured cap of 4096, a 4200-token strategy prompt
# exhausted the budget on reasoning and returned status=ok with an
# empty content string. The OpenAIProvider now floors the cap at
# ``_REASONING_MIN_COMPLETION_TOKENS`` for any model whose name
# starts with the reasoning-class prefixes (gpt-5*, o1*, o3*).
# ---------------------------------------------------------------


def _install_fake_openai(monkeypatch: pytest.MonkeyPatch, captured: dict) -> None:
    """Install a fake ``openai`` module so OpenAIProvider can be
    constructed without the real SDK / a live API key. The fake
    captures the kwargs passed to ``chat.completions.create`` so the
    test can assert what landed on the wire."""

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class _Choice:
                class message:
                    content = '{"ok": true}'

            class _Resp:
                choices = [_Choice()]
                usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()

            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self, *_a, **_kw):
            self.chat = _FakeChat()

    fake_module = type(
        "FakeOpenAIModule",
        (),
        {"OpenAI": _FakeClient},
    )
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "openai", fake_module)


def _install_fake_openai_structured(
    monkeypatch: pytest.MonkeyPatch,
    captured: dict,
    *,
    include_parsed: bool = True,
) -> None:
    class _FakeCompletions:
        def create(self, **_kwargs):
            raise AssertionError("structured generation must use the native parse contract")

        def parse(self, **kwargs):
            captured.update(kwargs)
            captured["method"] = "parse"
            response_format = kwargs["response_format"]
            parsed = (
                response_format(
                    title="Native structured response",
                    options=[
                        {
                            "label": "Option A",
                            "confidence": "high",
                            "supporting_citations": ["2024 TEST 1"],
                        }
                    ],
                    confidence="high",
                )
                if include_parsed
                else None
            )

            class _Message:
                content = "provider text is deliberately not trusted here"
                refusal = None

                def __init__(self) -> None:
                    self.parsed = parsed

            class _Choice:
                message = _Message()

            class _Resp:
                choices = [_Choice()]
                usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 5})()

            return _Resp()

    class _FakeChat:
        completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self, *_args, **_kwargs) -> None:
            self.chat = _FakeChat()

    class _FakeLengthFinishReasonError(Exception):
        pass

    class _FakeContentFilterFinishReasonError(Exception):
        pass

    fake_module = type(
        "FakeOpenAIModule",
        (),
        {
            "OpenAI": _FakeClient,
            "LengthFinishReasonError": _FakeLengthFinishReasonError,
            "ContentFilterFinishReasonError": _FakeContentFilterFinishReasonError,
        },
    )
    import sys as _sys

    monkeypatch.setitem(_sys.modules, "openai", fake_module)


def test_openai_generate_structured_uses_native_pydantic_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai_structured(monkeypatch, captured)
    provider = OpenAIProvider(model="gpt-5.1", api_key="k")

    validated, completion = generate_structured(
        provider,
        schema=_Structured,
        messages=_prompt(structured=True),
        context=LLMCallContext(purpose="unit-test"),
    )

    assert captured["method"] == "parse"
    assert captured["response_format"] is _Structured
    assert validated.title == "Native structured response"
    assert json.loads(completion.text)["options"][0]["label"] == "Option A"


def test_openai_generate_structured_rejects_http_200_without_parsed_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai_structured(monkeypatch, captured, include_parsed=False)
    provider = OpenAIProvider(model="gpt-5.1", api_key="k")

    with pytest.raises(LLMResponseFormatError, match="contained no parsed value"):
        generate_structured(
            provider,
            schema=_Structured,
            messages=_prompt(structured=True),
            context=LLMCallContext(purpose="unit-test"),
        )


def test_openai_provider_floors_reasoning_model_max_completion_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gpt-5-mini + max_tokens=2048 -> wire request must carry the
    8192 floor, not the requested 2048. Catches regressions where a
    future cutover to a reasoning model re-triggers the empty-content
    trap (PR #7 / 2026-05-03)."""
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)

    provider = OpenAIProvider(model="gpt-5-mini", api_key="k")
    provider.generate(
        [LLMMessage(role="user", content="x")],
        max_tokens=2048,
    )
    assert captured.get("max_completion_tokens") == 8192, (
        f"reasoning model floor should bump max_completion_tokens to 8192; "
        f"got {captured.get('max_completion_tokens')}"
    )


def test_openai_provider_passes_through_max_tokens_for_non_reasoning_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-reasoning models (e.g. gpt-4*) must pass max_tokens through
    unchanged — only gpt-5*/o1*/o3* get the floor."""
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)

    provider = OpenAIProvider(model="gpt-4o-mini", api_key="k")
    provider.generate(
        [LLMMessage(role="user", content="x")],
        max_tokens=2048,
    )
    assert captured.get("max_completion_tokens") == 2048, (
        "non-reasoning model must pass max_tokens through unchanged"
    )


def test_openai_provider_does_not_lower_when_above_reasoning_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the operator already configures a >=8192 cap, the floor
    is a no-op — the configured value passes through."""
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)

    provider = OpenAIProvider(model="gpt-5-mini", api_key="k")
    provider.generate(
        [LLMMessage(role="user", content="x")],
        max_tokens=16384,
    )
    assert captured.get("max_completion_tokens") == 16384


def test_openai_provider_floor_applies_to_o3_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The floor must cover every reasoning-class prefix (gpt-5*, o1*,
    o3*). o3-mini is the canonical "small reasoning" SKU."""
    from caseops_api.services.llm import OpenAIProvider

    captured: dict = {}
    _install_fake_openai(monkeypatch, captured)

    provider = OpenAIProvider(model="o3-mini", api_key="k")
    provider.generate(
        [LLMMessage(role="user", content="x")],
        max_tokens=1024,
    )
    assert captured.get("max_completion_tokens") == 8192
