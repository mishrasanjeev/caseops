"""Layer-2 corpus extraction — provider switch + $/day cap (2026-05-01).

Anchors:
- build_tier_provider returns an OpenAIProvider for both haiku and
  sonnet tiers (cutover from Anthropic per user directive 2026-05-01).
- completion_cost_usd applies the new gpt-5.1 rates and stays
  backward-compatible for legacy Anthropic ModelRun rows.
- ensure_daily_cap_not_exceeded sums today's metadata_extract spend
  via on-the-fly pricing and raises LLMProviderError once the cap
  is crossed. Default cap is $20; CASEOPS_LAYER2_DAILY_CAP_USD
  overrides it.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from caseops_api.core.settings import get_settings
from caseops_api.db.session import get_session_factory
from caseops_api.services.corpus_structured import (
    DEFAULT_LAYER2_DAILY_CAP_USD,
    build_tier_provider,
    completion_cost_usd,
    ensure_daily_cap_not_exceeded,
)
from caseops_api.services.llm import LLMProviderError, OpenAIProvider

# ---------- build_tier_provider ----------


def test_build_tier_provider_returns_openai_for_haiku(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live-mode haiku tier returns OpenAIProvider on gpt-5.1 when no
    CASEOPS_LLM_MODEL_METADATA_EXTRACT override is set."""
    _ = client
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-test-key")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "")
    get_settings.cache_clear()
    provider = build_tier_provider("haiku")
    assert isinstance(provider, OpenAIProvider)
    # OpenAIProvider exposes the model on the instance.
    assert provider.model == "gpt-5.1"


def test_build_tier_provider_sonnet_also_gpt_5_1(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sonnet tier also resolves to gpt-5.1 — single-model cutover."""
    _ = client
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-test-key")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "")
    get_settings.cache_clear()
    provider = build_tier_provider("sonnet")
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-5.1"


def test_build_tier_provider_honors_env_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CASEOPS_LLM_MODEL_METADATA_EXTRACT overrides the tier default —
    this is what enables Layer-2 model A/Bs without a code change."""
    _ = client
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "sk-test-key")
    monkeypatch.setenv("CASEOPS_LLM_MODEL_METADATA_EXTRACT", "gpt-5-nano")
    get_settings.cache_clear()
    provider = build_tier_provider("haiku")
    assert isinstance(provider, OpenAIProvider)
    assert provider.model == "gpt-5-nano"


def test_build_tier_provider_unknown_tier_raises(client: TestClient) -> None:
    _ = client
    with pytest.raises(ValueError):
        build_tier_provider("opus-extreme")


def test_build_tier_provider_mock_falls_back(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock provider mode bypasses the cutover (tests don't need an
    OpenAI key)."""
    _ = client
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    provider = build_tier_provider("haiku")
    # The build_provider mock fallback returns MockProvider; we just
    # assert it's NOT OpenAIProvider so the no-key path doesn't hit
    # the OpenAI SDK.
    assert not isinstance(provider, OpenAIProvider)


def test_build_tier_provider_missing_key_raises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = client
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("CASEOPS_LLM_API_KEY", "")
    monkeypatch.delenv("CASEOPS_OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(LLMProviderError):
        build_tier_provider("haiku")


# ---------- completion_cost_usd ----------


def test_cost_gpt_5_1_typical_doc() -> None:
    """gpt-5.1 at 5K input + 1K output ≈ $0.02."""
    cost = completion_cost_usd(
        "openai", "gpt-5.1",
        prompt_tokens=5_000,
        completion_tokens=1_000,
    )
    # 5000*2/1M + 1000*10/1M = 0.01 + 0.01 = 0.02
    assert cost == pytest.approx(0.02, abs=0.0001)


def test_cost_legacy_anthropic_still_resolves() -> None:
    """Historical ModelRun rows from the Anthropic era keep their
    cost so the cap query reads them correctly."""
    cost = completion_cost_usd(
        "anthropic", "claude-haiku-4-5-20251001",
        prompt_tokens=10_000,
        completion_tokens=2_000,
    )
    # 10000*1/1M + 2000*5/1M = 0.01 + 0.01 = 0.02
    assert cost == pytest.approx(0.02, abs=0.0001)


def test_cost_unknown_provider_returns_zero() -> None:
    assert (
        completion_cost_usd("xyz", "abc", prompt_tokens=1000, completion_tokens=1000)
        == 0.0
    )


# ---------- ensure_daily_cap_not_exceeded ----------


def _seed_model_run(
    *,
    purpose: str,
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    created_at: datetime | None = None,
) -> None:
    factory = get_session_factory()
    s = factory()
    try:
        s.execute(
            text(
                "INSERT INTO model_runs "
                "(id, purpose, provider, model, prompt_tokens, "
                " completion_tokens, latency_ms, status, created_at) "
                "VALUES (:id, :purpose, :provider, :model, :pt, "
                " :ct, 0, 'ok', :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "purpose": purpose,
                "provider": provider,
                "model": model,
                "pt": prompt_tokens,
                "ct": completion_tokens,
                "created_at": created_at or datetime.now(UTC),
            },
        )
        s.commit()
    finally:
        s.close()


def test_cap_passes_when_under_budget(client: TestClient) -> None:
    _ = client
    factory = get_session_factory()
    s = factory()
    try:
        # No model_runs at all — should pass.
        ensure_daily_cap_not_exceeded(s)
    finally:
        s.close()


def test_cap_fires_when_over_budget(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = client
    # Use a tiny cap so a small synthetic spend trips it.
    monkeypatch.setenv("CASEOPS_LAYER2_DAILY_CAP_USD", "0.01")
    get_settings.cache_clear()
    # 5000 prompt + 1000 completion @ gpt-5.1 = $0.02 (above 0.01).
    _seed_model_run(
        purpose="metadata_extract",
        provider="openai", model="gpt-5.1",
        prompt_tokens=5_000, completion_tokens=1_000,
    )
    factory = get_session_factory()
    s = factory()
    try:
        with pytest.raises(LLMProviderError) as exc:
            ensure_daily_cap_not_exceeded(s)
        assert "daily cap reached" in str(exc.value).lower()
    finally:
        s.close()


def test_cap_ignores_other_purposes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only metadata_extract spend counts toward the Layer 2 cap.
    A drafting call with the same model/tokens MUST NOT trip it."""
    _ = client
    monkeypatch.setenv("CASEOPS_LAYER2_DAILY_CAP_USD", "0.01")
    get_settings.cache_clear()
    _seed_model_run(
        purpose="drafting",  # NOT metadata_extract
        provider="openai", model="gpt-5.1",
        prompt_tokens=5_000, completion_tokens=1_000,
    )
    factory = get_session_factory()
    s = factory()
    try:
        # No metadata_extract spend → pass even with tiny cap.
        ensure_daily_cap_not_exceeded(s)
    finally:
        s.close()


def test_cap_default_is_20(client: TestClient) -> None:
    """Sanity: when the env var is unset the default is $20."""
    _ = client
    assert DEFAULT_LAYER2_DAILY_CAP_USD == 20.0
