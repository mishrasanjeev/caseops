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
    # Must set to empty string, not delete — pydantic-settings falls back
    # to the `.env` file when the OS env is missing the key, so delenv
    # alone will pick up a real key if the dev has one in .env.
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(EmbeddingProviderError):
        build_provider()


def test_build_provider_rejects_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "definitely-not-a-thing")
    monkeypatch.setenv("CASEOPS_EMBEDDING_API_KEY", "irrelevant")
    get_settings.cache_clear()
    with pytest.raises(EmbeddingProviderError):
        build_provider()


def test_voyage_provider_splits_oversized_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """VoyageProvider groups texts so no single request exceeds the
    120K-token server ceiling. We stub the voyageai client to avoid the
    network call but verify the batching decision."""
    from caseops_api.services.embeddings import VoyageProvider

    class _StubVoyageClient:
        def __init__(self) -> None:
            self.batches: list[int] = []

        def tokenize(self, texts, model):  # noqa: ARG002
            # Pretend every 1 char == 1 token so tests control sizes.
            return [list(range(len(t))) for t in texts]

        def embed(self, texts, model, input_type, output_dimension):  # noqa: ARG002
            self.batches.append(sum(len(t) for t in texts))

            class _Result:
                pass

            r = _Result()
            r.embeddings = [[0.1] * output_dimension for _ in texts]
            return r

    stub = _StubVoyageClient()

    # Monkeypatch voyageai.Client so VoyageProvider picks up our stub.
    import voyageai

    monkeypatch.setattr(voyageai, "Client", lambda api_key: stub)

    provider = VoyageProvider(
        model="voyage-4-large",
        api_key="dummy",
        dimensions=1024,
    )
    # Each text is 40K "tokens" (chars == tokens in the stub). Four of
    # them = 160K total — must split into at least two sub-batches.
    texts = ["a" * 40_000 for _ in range(4)]
    result = provider.embed(texts)
    assert len(result.vectors) == 4
    assert len(stub.batches) >= 2, stub.batches
    assert all(b <= provider._MAX_BATCH_TOKENS for b in stub.batches), stub.batches
