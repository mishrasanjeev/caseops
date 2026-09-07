from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_guide" / "catalog.generated.json"
MAX_RESULTS = 10
MAX_QUERY_CHARS = 160
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "can",
        "do",
        "find",
        "for",
        "go",
        "how",
        "i",
        "in",
        "is",
        "me",
        "my",
        "need",
        "of",
        "on",
        "open",
        "the",
        "to",
        "use",
        "what",
        "where",
        "with",
    }
)


@lru_cache(maxsize=1)
def load_product_guide_catalog() -> dict[str, Any]:
    payload = CATALOG_PATH.read_bytes()
    document = json.loads(payload)
    if document.get("schema_version") != 1:
        raise RuntimeError("Unsupported Product Guide catalog schema")
    document["fingerprint"] = hashlib.sha256(payload).hexdigest()
    return document


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_value = decomposed.encode("ascii", "ignore").decode("ascii")
    return " ".join(_TOKEN_RE.findall(ascii_value))


@dataclass(frozen=True, slots=True)
class _SearchText:
    title: str
    phrases: frozenset[str]
    indexed_tokens: frozenset[str]
    summary_tokens: frozenset[str]


@lru_cache(maxsize=512)
def _indexed_text(
    title: str, keywords: tuple[str, ...], aliases: tuple[str, ...], summary: str
) -> _SearchText:
    # Cache only public catalog text by content, never a user's results or grants.
    normalized_title = _normalize(title)
    phrases = frozenset(_normalize(value) for value in (*keywords, *aliases))
    normalized_summary = _normalize(summary)
    indexed = " ".join([normalized_title, *phrases])
    return _SearchText(
        title=normalized_title,
        phrases=phrases,
        indexed_tokens=frozenset(indexed.split()),
        summary_tokens=frozenset(normalized_summary.split()),
    )


def _score(
    normalized_query: str,
    tokens: tuple[str, ...],
    *,
    title: str,
    keywords: list[str],
    aliases: list[str],
    summary: str,
) -> int:
    indexed = _indexed_text(title, tuple(keywords), tuple(aliases), summary)
    if normalized_query == indexed.title:
        return 180
    score = 0
    if tokens and f" {normalized_query} " in f" {indexed.title} ":
        score += 120
    if normalized_query in indexed.phrases:
        score += 110
    if not tokens:
        return score
    indexed_matches = sum(token in indexed.indexed_tokens for token in tokens)
    summary_matches = sum(token in indexed.summary_tokens for token in tokens)
    if indexed_matches == len(tokens):
        score += 80 + indexed_matches
    elif indexed_matches:
        score += 25 * indexed_matches
    if summary_matches == len(tokens):
        score += 35
    elif summary_matches:
        score += 8 * summary_matches
    return score


def search_product_guide(
    query: str,
    *,
    capabilities: set[str],
    limit: int = 8,
    client_version: str | None = None,
) -> dict[str, Any]:
    catalog = load_product_guide_catalog()
    bounded_limit = max(1, min(limit, MAX_RESULTS))
    query = query.strip()[:MAX_QUERY_CHARS]
    normalized_query = _normalize(query)
    if not normalized_query:
        return {
            "status": "no_match",
            "version_status": (
                "stale"
                if client_version is not None and client_version != catalog["content_version"]
                else "current"
            ),
            "content_version": catalog["content_version"],
            "catalog_fingerprint": catalog["fingerprint"],
            "query": query,
            "results": [],
            "permission": None,
            "suggested_queries": ["matters", "trademark deadlines", "research", "billing"],
        }
    matches: list[tuple[int, int, dict[str, Any]]] = []
    denied: list[tuple[int, tuple[str, ...]]] = []
    tokens = tuple(
        token
        for token in dict.fromkeys(normalized_query.split())
        if len(token) >= 2 and token not in _SEARCH_STOPWORDS
    )

    for section in catalog["sections"]:
        score = _score(
            normalized_query,
            tokens,
            title=section["title"],
            keywords=section["keywords"],
            aliases=section["aliases"],
            summary=section["summary"],
        )
        if score:
            matches.append(
                (
                    score,
                    1,
                    {
                        "kind": "guide",
                        "id": section["id"],
                        "title": section["title"],
                        "summary": section["summary"],
                        "href": f"/guide#{section['id']}",
                        "required_capabilities": [],
                    },
                )
            )

    for command in catalog["commands"]:
        score = _score(
            normalized_query,
            tokens,
            title=command["label"],
            keywords=command["keywords"],
            aliases=[],
            summary=command["summary"],
        )
        if not score:
            continue
        required = set(command["required_capabilities"])
        missing = tuple(sorted(required - capabilities))
        if missing:
            denied.append((score, missing))
            continue
        matches.append(
            (
                score,
                0,
                {
                    "kind": "command",
                    "id": command["id"],
                    "title": command["label"],
                    "summary": command["summary"],
                    "href": command["href"],
                    "required_capabilities": sorted(required),
                },
            )
        )

    matches.sort(key=lambda item: (-item[0], item[1], item[2]["title"].casefold()))
    results = [item[2] for item in matches[:bounded_limit]]
    permission: dict[str, Any] | None = None
    if denied:
        best_denied_score = max(item[0] for item in denied)
        # Only report capabilities from equally relevant denied commands. This
        # avoids turning a broad keyword into an inventory of unrelated access.
        missing = sorted(
            {
                capability
                for score, capabilities_for_match in denied
                if score == best_denied_score
                for capability in capabilities_for_match
            }
        )
        permission = {
            "required_capabilities": missing,
            "message": "This task needs additional workspace access.",
        }

    status: Literal["matched", "permission_required", "no_match"]
    if results:
        status = "matched"
    elif permission:
        status = "permission_required"
    else:
        status = "no_match"
    return {
        "status": status,
        "version_status": (
            "stale"
            if client_version is not None and client_version != catalog["content_version"]
            else "current"
        ),
        "content_version": catalog["content_version"],
        "catalog_fingerprint": catalog["fingerprint"],
        "query": query,
        "results": results,
        "permission": permission,
        "suggested_queries": (
            []
            if status != "no_match"
            else ["matters", "trademark deadlines", "research", "billing"]
        ),
    }
