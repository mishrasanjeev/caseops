"""Cross-encoder-style reranker over retrieved authorities (§4.2).

The first-stage retriever is fast but lossy: pgvector + lexical hybrid
returns plausible candidates, but its ordering is often wrong for
legal nuance — a paragraph that mentions "bail" wins against one that
actually sets out the triple-test if the former has more keyword hits.

This module implements a small, pluggable reranker Protocol so callers
can over-fetch (say top 25 candidates) and surface only the top K that
genuinely help the generation.

Providers shipped in v1:

- ``MockReranker`` — no-op, preserves input order. Default for tests
  and offline dev.
- ``LLMReranker`` — uses the existing ``LLMProvider`` (Haiku or
  equivalent) as a judge. Sends the query + a numbered list of
  candidates (title + summary, ≤ 250 chars each) in ONE call and asks
  the model to return a JSON array of candidate indices in
  relevance-descending order. One LLM round-trip per retrieval,
  regardless of candidate count.

We deliberately do NOT ship a local cross-encoder (BGE-reranker,
Jina-reranker) in v1 — they add ~500 MB of model weights to the
container image. If a deployment later wants native inference it can
add a new provider here without changing call sites.
"""
from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from caseops_api.services.llm import (
    LLMMessage,
    LLMProvider,
    LLMResponseFormatError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RerankerCandidate:
    """One item to rerank. ``identifier`` is opaque — the caller uses
    it to map back to the underlying row after reranking."""

    identifier: str
    title: str
    text: str


class RerankerProvider(Protocol):
    name: str

    def rerank(
        self,
        query: str,
        candidates: list[RerankerCandidate],
        *,
        top_k: int,
    ) -> list[RerankerCandidate]: ...


class MockReranker:
    """Preserves input order; clamps to ``top_k``. Used when reranking
    is disabled or in tests."""

    name = "mock"

    def rerank(
        self,
        query: str,
        candidates: list[RerankerCandidate],
        *,
        top_k: int,
    ) -> list[RerankerCandidate]:
        del query  # no-op
        return candidates[: max(0, top_k)]


class FastembedReranker:
    """Native cross-encoder reranker via ``fastembed``.

    Defaults to ``jinaai/jina-reranker-v1-tiny-en`` — a 130 MB ONNX
    model that scores query/document pairs directly and runs on CPU.
    The first call downloads the model; subsequent calls are warm.

    Fastembed exposes ``TextCrossEncoder`` which yields a float score
    per (query, doc) pair. We sort descending and clamp to ``top_k``.
    """

    name = "fastembed"

    def __init__(
        self,
        *,
        model: str = "jinaai/jina-reranker-v1-tiny-en",
        cache_dir: str | None = None,
    ) -> None:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as exc:  # pragma: no cover — dep is always present
            raise RuntimeError(
                "The 'fastembed' package is required for FastembedReranker."
            ) from exc
        self._encoder = TextCrossEncoder(
            model_name=model,
            cache_dir=cache_dir,
        )
        self.model = model

    def rerank(
        self,
        query: str,
        candidates: list[RerankerCandidate],
        *,
        top_k: int,
    ) -> list[RerankerCandidate]:
        if not candidates:
            return []
        if top_k <= 0:
            return []
        if len(candidates) <= 1:
            return candidates[:top_k]
        documents = [
            (c.title + "\n" + c.text)[:1500] for c in candidates
        ]
        try:
            scores = list(self._encoder.rerank(query, documents))
        except Exception as exc:  # noqa: BLE001
            logger.warning("fastembed reranker failed, falling back: %s", exc)
            return candidates[:top_k]
        scored = list(zip(candidates, scores, strict=False))
        scored.sort(key=lambda pair: float(pair[1]), reverse=True)
        return [cand for cand, _ in scored[:top_k]]


class LLMReranker:
    """Uses an ``LLMProvider`` to score candidates in one batch call."""

    name = "llm-judge"

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def rerank(
        self,
        query: str,
        candidates: list[RerankerCandidate],
        *,
        top_k: int,
    ) -> list[RerankerCandidate]:
        if not candidates:
            return []
        if top_k <= 0:
            return []
        if len(candidates) <= 1:
            # Nothing to rank against. Preserve order, clamp to top_k.
            return candidates[:top_k]

        numbered = []
        for idx, cand in enumerate(candidates):
            excerpt = cand.text[:280].replace("\n", " ").strip()
            title = (cand.title or "(untitled)").strip()[:140]
            numbered.append(f"[{idx}] {title}\n    {excerpt}")

        system = (
            "You are a legal research assistant. Rank retrieved court "
            "judgments by how directly they support the user's query. "
            "Relevance means: the judgment's ratio or operative reasoning "
            "addresses the legal proposition in the query. A mere "
            "keyword hit is NOT relevance."
        )
        user = (
            f"Query: {query.strip()}\n\n"
            f"Candidates (indexed {0}..{len(candidates) - 1}):\n"
            + "\n\n".join(numbered)
            + "\n\nReturn a JSON object of the form "
            '{"order": [i1, i2, ...]} listing candidate indices '
            "in relevance-descending order. Include every index exactly "
            "once. Do not return prose."
        )

        try:
            completion = self._provider.generate(
                messages=[
                    LLMMessage(role="system", content=system),
                    LLMMessage(role="user", content=user),
                ],
                temperature=0.0,
                max_tokens=512,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reranker provider failed, falling back: %s", exc)
            return candidates[:top_k]

        try:
            order = _parse_order(completion.text, expected=len(candidates))
        except LLMResponseFormatError as exc:
            logger.warning("reranker output unparseable: %s", exc)
            return candidates[:top_k]

        ranked: list[RerankerCandidate] = []
        seen: set[int] = set()
        for idx in order:
            if idx in seen:
                continue
            if 0 <= idx < len(candidates):
                ranked.append(candidates[idx])
                seen.add(idx)
            if len(ranked) >= top_k:
                break
        # If the model under-ranked, backfill from the original order.
        if len(ranked) < top_k:
            for idx, cand in enumerate(candidates):
                if idx in seen:
                    continue
                ranked.append(cand)
                if len(ranked) >= top_k:
                    break
        return ranked


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _parse_order(text: str, *, expected: int) -> list[int]:
    cleaned = text.strip()
    fence = _FENCE_RE.search(cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMResponseFormatError("reranker response was not JSON") from exc
    if isinstance(payload, dict) and "order" in payload:
        raw = payload["order"]
    elif isinstance(payload, list):
        raw = payload
    else:
        raise LLMResponseFormatError(
            "reranker response lacked an 'order' array"
        )
    if not isinstance(raw, list):
        raise LLMResponseFormatError("reranker 'order' was not a list")
    out: list[int] = []
    for item in raw:
        if isinstance(item, int):
            out.append(item)
        elif isinstance(item, str) and item.isdigit():
            out.append(int(item))
    if not out:
        raise LLMResponseFormatError("reranker returned an empty order")
    del expected  # we tolerate short/long outputs — caller backfills.
    return out


def build_reranker(provider: LLMProvider | None = None) -> RerankerProvider:
    """Pick the reranker that matches the environment.

    ``CASEOPS_RERANK_ENABLED=true`` (default false) turns reranking on.
    ``CASEOPS_RERANK_BACKEND`` picks the implementation:

    - ``mock`` (default when disabled) — no-op, preserves input order.
    - ``fastembed`` (default when enabled) — native cross-encoder via
      fastembed; CPU-only, ~130 MB model, one-call-per-rerank.
    - ``llm`` — LLM-as-judge; sends all candidates in one prompt to
      the configured ``LLMProvider``. Useful when you already pay for
      the LLM and want to avoid shipping another model in the image.

    ``CASEOPS_RERANK_MODEL`` overrides the fastembed model name.

    Any construction failure falls back silently to ``MockReranker``
    so retrieval never breaks on reranker misconfiguration.
    """
    enabled = os.environ.get("CASEOPS_RERANK_ENABLED", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return MockReranker()

    backend = os.environ.get("CASEOPS_RERANK_BACKEND", "fastembed").strip().lower()

    if backend in {"llm", "llm-judge"}:
        if provider is None:
            try:
                from caseops_api.services.llm import build_provider
                provider = build_provider()
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "LLM reranker unavailable; falling back to mock: %s", exc
                )
                return MockReranker()
        return LLMReranker(provider)

    if backend in {"fastembed", "native", "cross-encoder"}:
        model = os.environ.get(
            "CASEOPS_RERANK_MODEL", "jinaai/jina-reranker-v1-tiny-en"
        )
        try:
            return FastembedReranker(model=model)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "fastembed reranker unavailable; falling back to mock: %s", exc
            )
            return MockReranker()

    logger.warning("unknown CASEOPS_RERANK_BACKEND=%s; using mock", backend)
    return MockReranker()


def candidates_from_iterable(
    items: Iterable, *, id_attr: str = "id", title_attr: str = "title", text_attr: str = "summary",
) -> list[RerankerCandidate]:
    """Adapter: build RerankerCandidate rows from a list of ORM objects."""
    out: list[RerankerCandidate] = []
    for item in items:
        identifier = getattr(item, id_attr, None) or ""
        if not identifier:
            continue
        out.append(
            RerankerCandidate(
                identifier=str(identifier),
                title=str(getattr(item, title_attr, "") or ""),
                text=str(getattr(item, text_attr, "") or ""),
            )
        )
    return out


__all__ = [
    "FastembedReranker",
    "LLMReranker",
    "MockReranker",
    "RerankerCandidate",
    "RerankerProvider",
    "build_reranker",
    "candidates_from_iterable",
]
