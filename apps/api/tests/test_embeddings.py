from __future__ import annotations

import math

import pytest

from caseops_api.core.settings import get_settings
from caseops_api.services.embeddings import (
    EmbeddingProviderError,
    MockProvider,
    build_provider,
    cosine_similarity,
)


def test_mock_provider_is_deterministic() -> None:
    p = MockProvider(dimensions=256)
    a = p.embed(["patent illegality under Section 34"]).vectors[0]
    b = p.embed(["patent illegality under Section 34"]).vectors[0]
    assert a == b


def test_mock_provider_emits_target_dimensions() -> None:
    p = MockProvider(dimensions=64)
    vec = p.embed(["any short text"]).vectors[0]
    assert len(vec) == 64


def test_mock_provider_is_l2_normalized() -> None:
    p = MockProvider(dimensions=128)
    vec = p.embed(["Section 34 patent illegality arbitration"]).vectors[0]
    magnitude = math.sqrt(sum(x * x for x in vec))
    assert magnitude == pytest.approx(1.0, rel=1e-6) or magnitude == 0.0


def test_cosine_prefers_topic_overlap_over_noise() -> None:
    p = MockProvider(dimensions=512)
    query = p.embed(
        ["patent illegality Section 34 arbitral award public policy"]
    ).vectors[0]
    positive = p.embed(
        [
            "Ssangyong Engg v. NHAI held that patent illegality survives Section 34 "
            "scrutiny where the award is opposed to Indian law."
        ]
    ).vectors[0]
    negative = p.embed(
        [
            "The judgment discusses taxation of non-resident shipping companies "
            "and unrelated commercial matters."
        ]
    ).vectors[0]
    pos_score = cosine_similarity(query, positive)
    neg_score = cosine_similarity(query, negative)
    # Hash-based mock is coarse, but topic overlap should win on average.
    assert pos_score >= neg_score


def test_cosine_similarity_handles_empty() -> None:
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_build_provider_defaults_to_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    get_settings.cache_clear()
    provider = build_provider()
    assert provider.name == "mock"
    assert provider.dimensions == get_settings().embedding_dimensions


def test_build_provider_requires_key_for_voyage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "voyage")
    monkeypatch.delenv("CASEOPS_EMBEDDING_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(EmbeddingProviderError):
        build_provider()


def test_build_provider_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "definitely-not-a-thing")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "irrelevant")
    get_settings.cache_clear()
    with pytest.raises(EmbeddingProviderError):
        build_provider()
