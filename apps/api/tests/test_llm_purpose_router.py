"""Per-purpose LLM router (Pass 0).

The drafting pipeline warrants high-reliability reasoning; structured
recommendations run fine on the recommendations model; metadata extraction scales on
the extraction model. `build_provider(purpose=...)` picks the configured model for
each; the global `llm_model` is the fallback.
"""

from __future__ import annotations

import pytest

from caseops_api.core.automated_test_context import (
    reset_automated_test_request,
    set_automated_test_request,
)
from caseops_api.core.settings import get_settings
from caseops_api.services.llm import (
    PURPOSE_ASSISTANT,
    PURPOSE_DRAFTING,
    PURPOSE_EVAL,
    PURPOSE_HEARING_PACK,
    PURPOSE_METADATA_EXTRACT,
    PURPOSE_RECOMMENDATIONS,
    build_provider,
    max_tokens_for_purpose,
)


def _clear_cache() -> None:
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    _clear_cache()
    yield
    _clear_cache()


def test_drafting_uses_dedicated_model_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "generic-fallback")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_DRAFTING", "gpt-5.1")
    _clear_cache()

    drafter = build_provider(purpose=PURPOSE_DRAFTING)
    default = build_provider()
    assert drafter.model == "gpt-5.1"
    assert default.model == "generic-fallback"


def test_recommendations_and_hearing_pack_resolve_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "fallback")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_RECOMMENDATIONS", "gpt-5-mini")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_HEARING_PACK", "gpt-5-mini")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "gpt-5-nano")
    _clear_cache()

    assert build_provider(purpose=PURPOSE_RECOMMENDATIONS).model == "gpt-5-mini"
    assert build_provider(purpose=PURPOSE_HEARING_PACK).model == "gpt-5-mini"
    assert build_provider(purpose=PURPOSE_METADATA_EXTRACT).model == "gpt-5-nano"


def test_unset_purpose_falls_back_to_global_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "default-only")
    # delenv is not enough — pydantic-settings will still pick up the
    # value from .env. Force empty strings so the "None or empty"
    # fallback in _resolve_model_for_purpose kicks in.
    monkeypatch.setenv("CASEOPS_LLM_MODEL_DRAFTING", "")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_EVAL", "")
    _clear_cache()

    assert build_provider(purpose=PURPOSE_DRAFTING).model == "default-only"
    assert build_provider(purpose=PURPOSE_EVAL).model == "default-only"


def test_each_structured_purpose_gets_its_configured_max_tokens_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Production recommendations need visible-output headroom after hidden
    # reasoning tokens; the purpose-specific setting must not fall through to
    # the much smaller global default.
    monkeypatch.setenv("CASEOPS_LLM_MAX_OUTPUT_TOKENS", "2048")
    monkeypatch.setenv("CASEOPS_LLM_MAX_OUTPUT_TOKENS_RECOMMENDATIONS", "16384")
    _clear_cache()

    assert max_tokens_for_purpose(PURPOSE_DRAFTING) == 8192
    assert max_tokens_for_purpose(PURPOSE_HEARING_PACK) == 4096
    assert max_tokens_for_purpose(PURPOSE_RECOMMENDATIONS) == 16384
    assert max_tokens_for_purpose(None) == 2048


def test_openai_background_and_interactive_calls_use_bounded_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retry multiplication must not cross the surrounding job/request budget."""
    captured_budgets: list[tuple[str, float, int]] = []

    class _FakeOpenAIProvider:
        name = "openai"

        def __init__(
            self,
            *,
            model: str,
            api_key: str,
            timeout_seconds: float,
            max_retries: int,
        ) -> None:
            assert api_key == "sk-test"
            assert timeout_seconds > 0
            self.model = model
            captured_budgets.append((model, timeout_seconds, max_retries))

    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "gpt-5-mini")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_RECOMMENDATIONS", "gpt-5.1")
    monkeypatch.setattr(
        "caseops_api.services.llm.OpenAIProvider",
        _FakeOpenAIProvider,
    )
    _clear_cache()

    build_provider(purpose=PURPOSE_METADATA_EXTRACT)
    build_provider(purpose=PURPOSE_RECOMMENDATIONS)

    assert captured_budgets == [
        ("gpt-5-mini", 60.0, 0),
        ("gpt-5.1", 100.0, 0),
    ]


def test_automated_request_uses_offline_llm_before_paid_sdk_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_ASSISTANT", "approved-test-model")
    _clear_cache()
    marker = set_automated_test_request("no-paid-providers")
    try:
        provider = build_provider(purpose=PURPOSE_ASSISTANT)
    finally:
        reset_automated_test_request(marker)
    assert provider.name == "mock"
    assert provider.model == "approved-test-model"
