"""Shared normalization and reviewed alias access for the forum catalog."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    ForumCatalogAlias,
    ForumCatalogEntry,
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
