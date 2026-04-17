"""Embedding provider abstraction for CaseOps.

Design notes:

- One ``EmbeddingProvider`` Protocol. Nothing in the service layer imports a
  specific backend.
- ``MockProvider`` is the default so tests, offline dev, and CI do not need
  network access or a 2 GB model download. Output is a deterministic
  hash-based pseudo-embedding; meaningful only for pipeline tests.
- ``FastEmbedProvider`` (Apache-2.0) is the recommended local backend.
  fastembed bundles ONNX runtime and auto-downloads `BAAI/bge-base-en-v1.5`
  (~250 MB) on first use, producing 768-dim embeddings. We pad to 1024 so
  the vector column accepts either provider without a migration.
- ``VoyageProvider`` targets ``voyage-3-law`` (1024-dim, purpose-built for
  legal text). Best-in-class quality but requires a paid API key.
- ``GeminiProvider`` targets ``text-embedding-005`` (768-dim), padded to
  1024. Sensible pair with the Gemini LLM provider.

All non-mock providers are imported at call time so the base install stays
light — callers opt in via ``CASEOPS_EMBEDDING_PROVIDER``.
"""
from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from caseops_api.core.settings import get_settings

logger = logging.getLogger(__name__)


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding backend cannot produce vectors."""


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    dimensions: int


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dimensions: int

    def embed(self, texts: list[str]) -> EmbeddingResult: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pad(vector: list[float], target: int) -> list[float]:
    """Pad a shorter vector with zeros or truncate to ``target`` length.

    We use this so all providers normalize onto the same column width and
    migrations never have to change when the provider swaps.
    """
    if len(vector) >= target:
        return list(vector[:target])
    padded = list(vector)
    padded.extend(0.0 for _ in range(target - len(vector)))
    return padded


def _l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return vector
    return [v / norm for v in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for i in range(size):
        dot += a[i] * b[i]
        norm_a += a[i] * a[i]
        norm_b += b[i] * b[i]
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------


class MockProvider:
    """Deterministic hash-based provider for tests and offline dev.

    Produces vectors that cluster on shared n-grams, so simple retrieval
    tests ("does a paragraph about patent illegality score higher than one
    about shipping taxation for a query about Section 34?") come out right.
    Not a substitute for a real embedding model.
    """

    name = "mock"

    def __init__(self, *, model: str = "caseops-mock-embed", dimensions: int = 1024) -> None:
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> EmbeddingResult:
        vectors: list[list[float]] = []
        for text in texts:
            vectors.append(_l2_normalize(_mock_vector(text, self.dimensions)))
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


def _mock_vector(text: str, dimensions: int) -> list[float]:
    # Build a stable dimensional vector by hashing token n-grams and
    # accumulating counts into bucketed dimensions. No semantics, but
    # identical/near-identical inputs stay near each other, and long
    # strings on the same topic overlap meaningfully.
    vector = [0.0] * dimensions
    tokens = [t for t in _tokenize(text) if len(t) >= 2]
    if not tokens:
        return vector
    for n in (1, 2):
        for i in range(len(tokens) - n + 1):
            ngram = " ".join(tokens[i : i + n])
            digest = hashlib.blake2b(ngram.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % dimensions
            sign = -1.0 if digest[4] & 1 else 1.0
            vector[idx] += sign
    return vector


def _tokenize(text: str) -> list[str]:
    out: list[str] = []
    current: list[str] = []
    for ch in text.lower():
        if ch.isalnum():
            current.append(ch)
        else:
            if current:
                out.append("".join(current))
                current = []
    if current:
        out.append("".join(current))
    return out


class FastEmbedProvider:
    """Lightweight local provider via `fastembed` (Apache-2.0).

    Imports at construction time so the base install stays small. Falls
    back to a clear error if the package is missing.
    """

    name = "fastembed"

    def __init__(
        self,
        *,
        model: str = "BAAI/bge-base-en-v1.5",
        dimensions: int = 1024,
    ) -> None:
        try:
            from fastembed import TextEmbedding  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EmbeddingProviderError(
                "The 'fastembed' package is not installed. Add the 'embeddings' "
                "extra: `uv sync --extra embeddings` and set "
                "CASEOPS_EMBEDDING_PROVIDER=fastembed.",
            ) from exc
        self._model = TextEmbedding(model_name=model)
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[], provider=self.name, model=self.model, dimensions=self.dimensions
            )
        raw = list(self._model.embed(texts))
        vectors = [_pad([float(x) for x in vec], self.dimensions) for vec in raw]
        vectors = [_l2_normalize(v) for v in vectors]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


class VoyageProvider:
    """Voyage AI provider (paid, ``voyage-3-law`` is our legal default)."""

    name = "voyage"

    def __init__(
        self,
        *,
        model: str = "voyage-3-law",
        api_key: str,
        dimensions: int = 1024,
    ) -> None:
        try:
            import voyageai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EmbeddingProviderError(
                "The 'voyageai' package is not installed. Run "
                "`uv add voyageai` and set CASEOPS_EMBEDDING_PROVIDER=voyage.",
            ) from exc
        self._client = voyageai.Client(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[], provider=self.name, model=self.model, dimensions=self.dimensions
            )
        try:
            result = self._client.embed(texts, model=self.model, input_type="document")
        except Exception as exc:
            raise EmbeddingProviderError(f"Voyage embed failed: {exc}") from exc
        vectors = [_pad([float(x) for x in v], self.dimensions) for v in result.embeddings]
        vectors = [_l2_normalize(v) for v in vectors]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


class GeminiProvider:
    """Google Gemini embedding provider (``text-embedding-005`` by default)."""

    name = "gemini"

    def __init__(
        self,
        *,
        model: str = "text-embedding-005",
        api_key: str,
        dimensions: int = 1024,
    ) -> None:
        try:
            from google import genai  # type: ignore[import-not-found]
        except ImportError as exc:
            raise EmbeddingProviderError(
                "The 'google-genai' package is not installed. Run "
                "`uv add google-genai` and set CASEOPS_EMBEDDING_PROVIDER=gemini.",
            ) from exc
        self._client = genai.Client(api_key=api_key)
        self.model = model
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=[], provider=self.name, model=self.model, dimensions=self.dimensions
            )
        try:
            response = self._client.models.embed_content(
                model=self.model,
                contents=texts,
            )
        except Exception as exc:
            raise EmbeddingProviderError(f"Gemini embed failed: {exc}") from exc
        raw = [list(e.values) for e in response.embeddings]
        vectors = [_pad([float(x) for x in v], self.dimensions) for v in raw]
        vectors = [_l2_normalize(v) for v in vectors]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=self.model,
            dimensions=self.dimensions,
        )


def build_provider() -> EmbeddingProvider:
    settings = get_settings()
    provider_name = settings.embedding_provider.lower()
    if provider_name in {"mock", "noop", "off"}:
        return MockProvider(
            model=settings.embedding_model or "caseops-mock-embed",
            dimensions=settings.embedding_dimensions,
        )
    if provider_name == "fastembed":
        return FastEmbedProvider(
            model=settings.embedding_model or "BAAI/bge-base-en-v1.5",
            dimensions=settings.embedding_dimensions,
        )
    if not settings.embedding_api_key:
        raise EmbeddingProviderError(
            f"CASEOPS_EMBEDDING_API_KEY must be set when "
            f"CASEOPS_EMBEDDING_PROVIDER={provider_name!r}.",
        )
    if provider_name == "voyage":
        return VoyageProvider(
            model=settings.embedding_model or "voyage-3-law",
            api_key=settings.embedding_api_key,
            dimensions=settings.embedding_dimensions,
        )
    if provider_name == "gemini":
        return GeminiProvider(
            model=settings.embedding_model or "text-embedding-005",
            api_key=settings.embedding_api_key,
            dimensions=settings.embedding_dimensions,
        )
    raise EmbeddingProviderError(
        f"Unknown CASEOPS_EMBEDDING_PROVIDER: {provider_name!r}. "
        "Use 'mock', 'fastembed', 'voyage', or 'gemini'.",
    )


def embed_many(provider: EmbeddingProvider, texts: Iterable[str]) -> EmbeddingResult:
    """Convenience wrapper with an explicit list conversion for iterables."""
    return provider.embed(list(texts))


__all__ = [
    "EmbeddingProvider",
    "EmbeddingProviderError",
    "EmbeddingResult",
    "FastEmbedProvider",
    "GeminiProvider",
    "MockProvider",
    "VoyageProvider",
    "build_provider",
    "cosine_similarity",
    "embed_many",
]
