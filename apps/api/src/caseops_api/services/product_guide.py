from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

CATALOG_PATH = (
    Path(__file__).resolve().parents[1]
    / "product_guide"
    / "catalog.generated.json"
)
MAX_RESULTS = 10
MAX_QUERY_CHARS = 160
_TOKEN_RE = re.compile(r"[a-z0-9]+")


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


def _score(query: str, *, title: str, keywords: list[str], aliases: list[str], summary: str) -> int:
    normalized_query = _normalize(query)
    tokens = tuple(dict.fromkeys(_TOKEN_RE.findall(normalized_query)))
    normalized_title = _normalize(title)
    normalized_keywords = [_normalize(value) for value in keywords]
    normalized_aliases = [_normalize(value) for value in aliases]
    normalized_summary = _normalize(summary)
    indexed = " ".join([normalized_title, *normalized_keywords, *normalized_aliases])

    if normalized_query == normalized_title:
        return 180
    score = 0
    if normalized_query in normalized_title:
        score += 120
    if normalized_query in normalized_keywords or normalized_query in normalized_aliases:
        score += 110
    indexed_matches = sum(token in indexed for token in tokens)
    summary_matches = sum(token in normalized_summary for token in tokens)
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
    if not _normalize(query):
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

    for section in catalog["sections"]:
        score = _score(
            query,
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
            query,
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
