"""Shared normalization and reviewed alias access for the forum catalog."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload, selectinload

from caseops_api.db.models import (
    ForumCatalogAlias,
    ForumCatalogEntry,
    Matter,
    PlatformAdminMembership,
)
from caseops_api.schemas.forum_catalog import ForumCatalogAliasRecord

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


def active_entries_matching_name(
    session: Session,
    court_name: str | None,
) -> list[ForumCatalogEntry]:
    """Active catalogue rows whose canonical name or reviewed alias is ``court_name``.

    The one predicate both the matter write path (resolving typed text to a
    catalogue row) and the court-website read path use, so a badge never links
    a court the write path would not have resolved.
    """

    normalized = normalize_forum_catalog_value(court_name)
    if not normalized:
        return []
    return [
        candidate
        for candidate in session.scalars(
            select(ForumCatalogEntry)
            .options(selectinload(ForumCatalogEntry.aliases))
            .where(
                ForumCatalogEntry.is_active.is_(True),
                or_(
                    ForumCatalogEntry.normalized_name == normalized,
                    ForumCatalogEntry.id.in_(
                        select(ForumCatalogAlias.forum_catalog_entry_id).where(
                            ForumCatalogAlias.normalized_alias == normalized,
                            ForumCatalogAlias.is_active.is_(True),
                            ForumCatalogAlias.verification_status == "verified",
                        )
                    ),
                ),
            )
            .order_by(ForumCatalogEntry.display_order, ForumCatalogEntry.id)
        )
        if normalized in forum_entry_identity_keys(candidate)
    ]


# Court badges link only to government-run sites. A catalogue value outside
# these domains (or not https) is treated as absent: plain text, no link.
OFFICIAL_WEBSITE_DOMAIN_SUFFIXES = (".gov.in", ".nic.in")


def official_website_or_none(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parts = urlsplit(value.strip())
        host = (parts.hostname or "").lower()
    except ValueError:
        return None
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or not host.endswith(OFFICIAL_WEBSITE_DOMAIN_SUFFIXES)
    ):
        return None
    return value.strip()


def matter_court_website_urls(
    session: Session | None, matters: Iterable[Matter]
) -> dict[str, str | None]:
    """Official court websites for many matters, keyed by matter id.

    Resolution follows each matter's canonical identity, never its display
    text: the selected catalogue row first; else the master Court row's
    catalogue entry (exactly one active row); else, for a legacy free-text
    court, the same canonical name/reviewed-alias predicate the write path
    applies (``active_entries_matching_name``), at the matter's forum level,
    and only when exactly one row matches. A selected catalogue row without a
    website is final: it never falls back to another row.

    At most two queries for any number of matters: the catalogue rows, plus
    their aliases only when a legacy free-text name must be confirmed; none
    when no matter carries a court identity. Only read paths that render the
    court badge call this.
    """

    rows = list(matters)
    urls: dict[str, str | None] = {row.id: None for row in rows}
    if session is None or not rows:
        return urls
    entry_ids: set[str] = set()
    court_ids: set[str] = set()
    names: set[str] = set()
    for row in rows:
        if row.forum_catalog_entry_id:
            entry_ids.add(row.forum_catalog_entry_id)
        elif row.court_id:
            court_ids.add(row.court_id)
        else:
            normalized = normalize_forum_catalog_value(row.court_name)
            if normalized:
                names.add(normalized)
    clauses = []
    if entry_ids:
        clauses.append(ForumCatalogEntry.id.in_(entry_ids))
    if court_ids:
        clauses.append(ForumCatalogEntry.court_id.in_(court_ids))
    if names:
        clauses.append(ForumCatalogEntry.normalized_name.in_(names))
        clauses.append(
            ForumCatalogEntry.id.in_(
                select(ForumCatalogAlias.forum_catalog_entry_id).where(
                    ForumCatalogAlias.normalized_alias.in_(names),
                    ForumCatalogAlias.is_active.is_(True),
                    ForumCatalogAlias.verification_status == "verified",
                )
            )
        )
    if not clauses:
        return urls
    stmt = select(ForumCatalogEntry).where(ForumCatalogEntry.is_active.is_(True), or_(*clauses))
    if names:
        # Aliases are read only to confirm a legacy free-text name match.
        stmt = stmt.options(selectinload(ForumCatalogEntry.aliases))
    entries = list(session.scalars(stmt))
    by_id = {entry.id: entry for entry in entries}
    by_court: dict[str, list[ForumCatalogEntry]] = {}
    by_name: dict[str, list[ForumCatalogEntry]] = {}
    for entry in entries:
        if entry.court_id in court_ids:
            by_court.setdefault(entry.court_id, []).append(entry)
        if not names:
            continue
        # The same two-step predicate as active_entries_matching_name: the
        # stored key matched in SQL, and the entry's own identity keys agree.
        matched = {entry.normalized_name} | {
            alias.normalized_alias
            for alias in entry.aliases
            if alias.is_active and alias.verification_status == "verified"
        }
        for name in (matched & names) & forum_entry_identity_keys(entry):
            by_name.setdefault(name, []).append(entry)
    for row in rows:
        if row.forum_catalog_entry_id:
            entry = by_id.get(row.forum_catalog_entry_id)
            url = entry.official_website_url if entry is not None else None
        elif row.court_id:
            linked = by_court.get(row.court_id, [])
            url = linked[0].official_website_url if len(linked) == 1 else None
        else:
            forum_level = row.forum_level or ""
            candidates = [
                candidate
                for candidate in by_name.get(
                    normalize_forum_catalog_value(row.court_name), []
                )
                if not forum_level or candidate.forum_level == forum_level
            ]
            url = candidates[0].official_website_url if len(candidates) == 1 else None
        urls[row.id] = official_website_or_none(url)
    return urls


def matter_court_website_url(session: Session | None, matter: Matter) -> str | None:
    """One matter's official court website; see ``matter_court_website_urls``."""

    return matter_court_website_urls(session, [matter])[matter.id]


class ForumCatalogAliasError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _escaped_contains(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _alias_record(alias: ForumCatalogAlias) -> ForumCatalogAliasRecord:
    entry = alias.entry
    return ForumCatalogAliasRecord(
        id=alias.id,
        forum_catalog_entry_id=entry.id,
        canonical_name=entry.name,
        forum_type=entry.forum_type,
        forum_level=entry.forum_level,
        state=entry.state,
        district=entry.district,
        city=entry.city,
        lineage=entry.lineage,
        alias=alias.alias,
        normalized_alias=alias.normalized_alias,
        alias_type=alias.alias_type,
        source_name=alias.source_name,
        source_url=alias.source_url,
        verification_status=alias.verification_status,
        is_active=alias.is_active,
        reviewed_at=alias.reviewed_at,
        record_version=alias.record_version,
        created_by_platform_admin_id=alias.created_by_platform_admin_id,
        reviewed_by_platform_admin_id=alias.reviewed_by_platform_admin_id,
        updated_by_platform_admin_id=alias.updated_by_platform_admin_id,
        created_at=alias.created_at,
        updated_at=alias.updated_at,
    )


def list_forum_catalog_aliases(
    session: Session,
    *,
    q: str | None = None,
    verification_status: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
) -> tuple[list[ForumCatalogAliasRecord], bool]:
    stmt = (
        select(ForumCatalogAlias)
        .join(ForumCatalogEntry)
        .options(joinedload(ForumCatalogAlias.entry))
    )
    if q and q.strip():
        pattern = _escaped_contains(q.strip())
        stmt = stmt.where(
            or_(
                ForumCatalogAlias.alias.ilike(pattern, escape="\\"),
                ForumCatalogAlias.normalized_alias.ilike(pattern, escape="\\"),
                ForumCatalogEntry.name.ilike(pattern, escape="\\"),
                ForumCatalogEntry.state.ilike(pattern, escape="\\"),
                ForumCatalogEntry.district.ilike(pattern, escape="\\"),
            )
        )
    if verification_status is not None:
        stmt = stmt.where(ForumCatalogAlias.verification_status == verification_status)
    if is_active is not None:
        stmt = stmt.where(ForumCatalogAlias.is_active.is_(is_active))
    rows = list(
        session.scalars(
            stmt.order_by(
                ForumCatalogAlias.updated_at.desc(),
                ForumCatalogAlias.id,
            ).limit(limit + 1)
        ).unique()
    )
    return [_alias_record(row) for row in rows[:limit]], len(rows) > limit


def _locked_active_entry(session: Session, entry_id: str) -> ForumCatalogEntry:
    entry = session.scalar(
        select(ForumCatalogEntry)
        .where(
            ForumCatalogEntry.id == entry_id,
            ForumCatalogEntry.is_active.is_(True),
        )
        .with_for_update()
    )
    if entry is None:
        raise ForumCatalogAliasError(
            "forum_catalog_entry_unavailable",
            "Select an active canonical forum catalog entry.",
            status_code=404,
        )
    return entry


def _assert_alias_identity_available(
    session: Session,
    *,
    entry: ForumCatalogEntry,
    normalized_alias: str,
    exclude_alias_id: str | None = None,
) -> None:
    if not normalized_alias:
        raise ForumCatalogAliasError(
            "forum_alias_empty",
            "The alias must contain at least one letter or number.",
        )
    if normalized_alias == entry.normalized_name:
        raise ForumCatalogAliasError(
            "forum_alias_matches_canonical_name",
            "The alias duplicates the canonical forum name and is not needed.",
            status_code=409,
        )
    duplicate_stmt = select(ForumCatalogAlias.id).where(
        ForumCatalogAlias.forum_catalog_entry_id == entry.id,
        ForumCatalogAlias.normalized_alias == normalized_alias,
    )
    if exclude_alias_id is not None:
        duplicate_stmt = duplicate_stmt.where(ForumCatalogAlias.id != exclude_alias_id)
    if session.scalar(duplicate_stmt.limit(1)) is not None:
        raise ForumCatalogAliasError(
            "forum_alias_duplicate",
            "This canonical forum already has the same normalized alias. Update the existing row.",
            status_code=409,
        )

    conflicting_canonical = session.scalar(
        select(ForumCatalogEntry.id)
        .where(
            ForumCatalogEntry.id != entry.id,
            ForumCatalogEntry.is_active.is_(True),
            ForumCatalogEntry.normalized_name == normalized_alias,
            ForumCatalogEntry.forum_type == entry.forum_type,
            func.coalesce(func.lower(ForumCatalogEntry.state), "")
            == (entry.state or "").casefold(),
            func.coalesce(func.lower(ForumCatalogEntry.district), "")
            == (entry.district or "").casefold(),
        )
        .limit(1)
    )
    if conflicting_canonical is not None:
        raise ForumCatalogAliasError(
            "forum_alias_conflicts_with_canonical_name",
            "The alias conflicts with another active canonical forum in the same context.",
            status_code=409,
        )


def _assert_verification_evidence(
    *,
    verification_status: str,
    source_name: str,
    source_url: str | None,
) -> None:
    if not source_name.strip():
        raise ForumCatalogAliasError(
            "forum_alias_source_required",
            "A source name is required for every alias record.",
        )
    if verification_status == "verified" and not source_url:
        raise ForumCatalogAliasError(
            "forum_alias_verified_source_required",
            "A verified alias requires a source URL.",
        )
    if source_url and not source_url.casefold().startswith("https://"):
        raise ForumCatalogAliasError(
            "forum_alias_https_source_required",
            "Alias source URLs must use HTTPS.",
        )


def create_forum_catalog_alias(
    session: Session,
    *,
    platform_admin: PlatformAdminMembership,
    forum_catalog_entry_id: str,
    alias: str,
    alias_type: str,
    source_name: str,
    source_url: str | None,
    verification_status: str,
    is_active: bool,
) -> ForumCatalogAliasRecord:
    entry = _locked_active_entry(session, forum_catalog_entry_id)
    normalized_alias = normalize_forum_catalog_value(alias)
    _assert_alias_identity_available(
        session,
        entry=entry,
        normalized_alias=normalized_alias,
    )
    _assert_verification_evidence(
        verification_status=verification_status,
        source_name=source_name,
        source_url=source_url,
    )
    if verification_status == "rejected":
        is_active = False
    now = datetime.now(UTC)
    reviewed = verification_status in {"verified", "rejected"}
    row = ForumCatalogAlias(
        forum_catalog_entry_id=entry.id,
        alias=alias.strip(),
        normalized_alias=normalized_alias,
        alias_type=alias_type,
        source_name=source_name.strip(),
        source_url=source_url,
        verification_status=verification_status,
        is_active=is_active,
        reviewed_at=now if reviewed else None,
        record_version=0,
        created_by_platform_admin_id=platform_admin.id,
        reviewed_by_platform_admin_id=platform_admin.id if reviewed else None,
        updated_by_platform_admin_id=platform_admin.id,
        created_at=now,
        updated_at=now,
        entry=entry,
    )
    session.add(row)
    session.flush()
    return _alias_record(row)


def update_forum_catalog_alias(
    session: Session,
    *,
    alias_id: str,
    platform_admin: PlatformAdminMembership,
    expected_record_version: int,
    updates: dict[str, object],
) -> ForumCatalogAliasRecord:
    entry_id = session.scalar(
        select(ForumCatalogAlias.forum_catalog_entry_id).where(
            ForumCatalogAlias.id == alias_id
        )
    )
    if entry_id is None:
        raise ForumCatalogAliasError(
            "forum_alias_not_found",
            "The forum alias record was not found.",
            status_code=404,
        )
    entry = _locked_active_entry(session, entry_id)
    row = session.scalar(
        select(ForumCatalogAlias)
        .where(ForumCatalogAlias.id == alias_id)
        .with_for_update()
    )
    if row is None:
        raise ForumCatalogAliasError(
            "forum_alias_not_found",
            "The forum alias record was not found.",
            status_code=404,
        )
    if row.record_version != expected_record_version:
        raise ForumCatalogAliasError(
            "forum_alias_stale_write",
            "This alias changed after it was loaded. Refresh and retry.",
            status_code=409,
        )

    alias = str(updates.get("alias", row.alias)).strip()
    alias_type = str(updates.get("alias_type", row.alias_type))
    source_name = str(updates.get("source_name", row.source_name)).strip()
    source_url_value = updates.get("source_url", row.source_url)
    source_url = str(source_url_value) if source_url_value is not None else None
    verification_status = str(updates.get("verification_status", row.verification_status))
    is_active = bool(updates.get("is_active", row.is_active))
    if verification_status == "rejected":
        is_active = False
    normalized_alias = normalize_forum_catalog_value(alias)
    _assert_alias_identity_available(
        session,
        entry=entry,
        normalized_alias=normalized_alias,
        exclude_alias_id=row.id,
    )
    _assert_verification_evidence(
        verification_status=verification_status,
        source_name=source_name,
        source_url=source_url,
    )

    reviewed = verification_status in {"verified", "rejected"}
    now = datetime.now(UTC)
    row.alias = alias
    row.normalized_alias = normalized_alias
    row.alias_type = alias_type
    row.source_name = source_name
    row.source_url = source_url
    row.verification_status = verification_status
    row.is_active = is_active
    row.reviewed_at = now if reviewed else None
    row.reviewed_by_platform_admin_id = platform_admin.id if reviewed else None
    row.updated_by_platform_admin_id = platform_admin.id
    row.updated_at = now
    row.record_version += 1
    row.entry = entry
    session.flush()
    return _alias_record(row)


__all__ = [
    "active_verified_aliases",
    "create_forum_catalog_alias",
    "forum_entry_identity_keys",
    "ForumCatalogAliasError",
    "list_forum_catalog_aliases",
    "normalize_forum_catalog_value",
    "update_forum_catalog_alias",
]
