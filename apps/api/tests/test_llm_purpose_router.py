"""Per-purpose LLM router (Pass 0).

The drafting pipeline warrants Opus-class reasoning; structured
recommendations run fine on Sonnet; metadata extraction scales on
Haiku. `build_provider(purpose=...)` picks the configured model for
each; the global `llm_model` is the fallback.
"""
from __future__ import annotations

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.services.llm import (
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
    monkeypatch.setenv("CASEOPS_LLM_MODEL_DRAFTING", "claude-opus-4-7")
    _clear_cache()

    drafter = build_provider(purpose=PURPOSE_DRAFTING)
    default = build_provider()
    assert drafter.model == "claude-opus-4-7"
    assert default.model == "generic-fallback"


def test_recommendations_and_hearing_pack_resolve_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_MODEL", "fallback")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_RECOMMENDATIONS", "claude-sonnet-4-6")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_HEARING_PACK", "claude-sonnet-4-6")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "claude-haiku-4-5-20251001")
    _clear_cache()

    assert build_provider(purpose=PURPOSE_RECOMMENDATIONS).model == "claude-sonnet-4-6"
    assert build_provider(purpose=PURPOSE_HEARING_PACK).model == "claude-sonnet-4-6"
    assert (
        build_provider(purpose=PURPOSE_METADATA_EXTRACT).model
        == "claude-haiku-4-5-20251001"
    )


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


def test_drafting_gets_its_larger_max_tokens_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Defaults: drafting 8192, hearing-pack 4096, global 2048.
    monkeypatch.setenv("CASEOPS_LLM_MAX_OUTPUT_TOKENS", "2048")
    _clear_cache()

    assert max_tokens_for_purpose(PURPOSE_DRAFTING) == 8192
    assert max_tokens_for_purpose(PURPOSE_HEARING_PACK) == 4096
    assert max_tokens_for_purpose(PURPOSE_RECOMMENDATIONS) == 2048
    assert max_tokens_for_purpose(None) == 2048
