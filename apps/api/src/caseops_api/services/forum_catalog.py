"""Shared normalization and reviewed alias access for the forum catalog."""

from __future__ import annotations

import re

from caseops_api.db.models import ForumCatalogEntry

_TRAILING_COURT_SUFFIXES = (
    "courtscomplex",
    "courtcomplex",
    "courts",
    "court",
)


def normalize_forum_catalog_value(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", (value or "").strip().casefold())
    for suffix in _TRAILING_COURT_SUFFIXES:
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return normalized[: -len(suffix)]
    return normalized


def active_verified_aliases(entry: ForumCatalogEntry) -> tuple[str, ...]:
    return tuple(
        alias.alias.strip()
        for alias in entry.aliases
        if alias.is_active and alias.verification_status == "verified" and alias.alias.strip()
    )


def forum_entry_identity_keys(entry: ForumCatalogEntry) -> set[str]:
    return {
        normalize_forum_catalog_value(value)
        for value in (entry.name, *active_verified_aliases(entry))
        if value
    }


__all__ = [
    "active_verified_aliases",
    "forum_entry_identity_keys",
    "normalize_forum_catalog_value",
]
