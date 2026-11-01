from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditActorType,
    IpDocumentTaxonomyAlias,
    IpDocumentTaxonomyEntry,
)
from caseops_api.schemas.ip_documents import (
    IpDocumentFoundationContract,
    IpDocumentNamingPreviewRequest,
    IpDocumentNamingPreviewResponse,
    IpDocumentTaxonomyAliasRecord,
    IpDocumentTaxonomyEntryRecord,
    IpDocumentTaxonomyResponse,
    IpDocumentTaxonomyUpsertRequest,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.session_context import SessionContext

# The one source of truth for the IP document taxonomy version. Workspace
# configuration stores this value unless an API caller sends its own label.
TAXONOMY_VERSION = "ip-document-taxonomy-v1"
DefaultTaxonomyTrigger = Literal[
    "workspace_configuration",
    "workspace_enable",
    "document_upload",
]
NAMING_PATTERN = (
    "[ClientCode]_[AssetType]_[Mark]_[Jurisdiction]_[ApplicationNo]_"
    "[ProceedingType]_[ProceedingNo]_[DocumentType]_[YYYY-MM-DD]_[Version]"
)
LINK_TARGETS = ["docket", "application", "proceeding", "event", "deadline"]

DEFAULT_TAXONOMY: tuple[tuple[str, str], ...] = (
    ("trademark_filing", "Trademark filing"),
    ("examination", "Examination"),
    ("opposition", "Opposition"),
    ("evidence", "Evidence"),
    ("hearing", "Hearing"),
    ("order", "Order"),
    ("appeal", "Appeal"),
    ("renewal", "Renewal"),
    ("assignment", "Assignment"),
    ("licence", "Licence"),
    ("correspondence", "Correspondence"),
    ("search", "Search"),
    ("watch", "Watch"),
    ("invoice", "Invoice"),
)

_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,79}$")
_UNSAFE_FILENAME_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE_OR_SEPARATOR_RE = re.compile(r"[\s_]+")
_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


def _normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split())


def _entry_record(
    entry: IpDocumentTaxonomyEntry,
    aliases: list[IpDocumentTaxonomyAlias],
) -> IpDocumentTaxonomyEntryRecord:
    return IpDocumentTaxonomyEntryRecord(
        id=entry.id,
        key=entry.key,
        label=entry.label,
        description=entry.description,
        sort_order=entry.sort_order,
        is_seeded=entry.is_seeded,
        is_active=entry.is_active,
        version=entry.version,
        aliases=[IpDocumentTaxonomyAliasRecord.model_validate(alias) for alias in aliases],
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _load_taxonomy_rows(
    session: Session,
    *,
    company_id: str,
) -> tuple[list[IpDocumentTaxonomyEntry], list[IpDocumentTaxonomyAlias]]:
    entries = list(
        session.scalars(
            select(IpDocumentTaxonomyEntry)
            .where(IpDocumentTaxonomyEntry.company_id == company_id)
            .order_by(
                IpDocumentTaxonomyEntry.sort_order,
                IpDocumentTaxonomyEntry.label,
                IpDocumentTaxonomyEntry.id,
            )
        ).all()
    )
    aliases = list(
        session.scalars(
            select(IpDocumentTaxonomyAlias)
            .where(IpDocumentTaxonomyAlias.company_id == company_id)
            .order_by(IpDocumentTaxonomyAlias.alias, IpDocumentTaxonomyAlias.id)
        ).all()
    )
    return entries, aliases


def _response(
    entries: list[IpDocumentTaxonomyEntry],
    aliases: list[IpDocumentTaxonomyAlias],
) -> IpDocumentTaxonomyResponse:
    aliases_by_entry: dict[str, list[IpDocumentTaxonomyAlias]] = {}
    for alias in aliases:
        aliases_by_entry.setdefault(alias.taxonomy_entry_id, []).append(alias)
    return IpDocumentTaxonomyResponse(
        taxonomy_version=TAXONOMY_VERSION,
        entries=[_entry_record(entry, aliases_by_entry.get(entry.id, [])) for entry in entries],
    )


def _add_default_entries(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str,
    existing_keys: set[str],
) -> list[str]:
    seeded_keys: list[str] = []
    for sort_order, (key, label) in enumerate(DEFAULT_TAXONOMY, start=10):
        if key in existing_keys:
            continue
        entry = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key=key,
            label=label,
            description=f"CaseOps seeded {label.casefold()} document category.",
            sort_order=sort_order,
            is_seeded=True,
            is_active=True,
            version=1,
            updated_by_membership_id=actor_membership_id,
        )
        session.add(entry)
        session.flush()
        session.add(
            IpDocumentTaxonomyAlias(
                company_id=company_id,
                taxonomy_entry_id=entry.id,
                alias=label,
                normalized_alias=_normalize_alias(label),
                source="seed",
                created_by_membership_id=actor_membership_id,
            )
        )
        seeded_keys.append(key)
    session.flush()
    return seeded_keys


def _company_has_taxonomy_entries(session: Session, *, company_id: str) -> bool:
    return (
        session.scalar(
            select(IpDocumentTaxonomyEntry.id)
            .where(IpDocumentTaxonomyEntry.company_id == company_id)
            .limit(1)
        )
        is not None
    )


def ensure_default_ip_document_taxonomy(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str,
    trigger: DefaultTaxonomyTrigger,
) -> list[str]:
    """Provision the default classifications for a tenant that has none.

    Inserts only when the company owns zero taxonomy entries, so a firm's own,
    renamed or deactivated entries are never changed. The inserts run in a
    savepoint: when a concurrent request provisions the same tenant first, the
    (company_id, key) unique constraint rejects this attempt, the savepoint is
    rolled back and the winner's rows stand. Returns the keys this call
    inserted. The caller owns the outer commit.
    """

    if _company_has_taxonomy_entries(session, company_id=company_id):
        return []
    try:
        with session.begin_nested():
            seeded_keys = _add_default_entries(
                session,
                company_id=company_id,
                actor_membership_id=actor_membership_id,
                existing_keys=set(),
            )
            record_audit(
                session,
                company_id=company_id,
                actor_type=AuditActorType.SYSTEM,
                actor_membership_id=actor_membership_id,
                actor_label="CaseOps default IP document classifications",
                action="ip_document_taxonomy.defaults_provisioned",
                target_type="ip_document_taxonomy",
                target_id=company_id,
                metadata={
                    "taxonomy_version": TAXONOMY_VERSION,
                    "keys": seeded_keys,
                    "trigger": trigger,
                },
            )
    except IntegrityError:
        return []
    return seeded_keys


def ip_document_taxonomy_counts(session: Session, *, company_id: str) -> tuple[int, int]:
    """Return (total, active) taxonomy entry counts for one tenant."""

    total, active = session.execute(
        select(
            func.count(IpDocumentTaxonomyEntry.id),
            func.count(case((IpDocumentTaxonomyEntry.is_active.is_(True), 1))),
        ).where(IpDocumentTaxonomyEntry.company_id == company_id)
    ).one()
    return int(total or 0), int(active or 0)


def seed_ip_document_taxonomy(
    session: Session,
    *,
    context: SessionContext,
) -> IpDocumentTaxonomyResponse:
    existing, aliases = _load_taxonomy_rows(session, company_id=context.company.id)
    existing_keys = {entry.key for entry in existing}
    if {key for key, _label in DEFAULT_TAXONOMY}.issubset(existing_keys):
        return _response(existing, aliases)

    seeded_keys = _add_default_entries(
        session,
        company_id=context.company.id,
        actor_membership_id=context.membership.id,
        existing_keys=existing_keys,
    )
    record_from_context(
        session,
        context,
        action="ip_document_taxonomy.seeded",
        target_type="ip_document_taxonomy",
        target_id=context.company.id,
        metadata={"taxonomy_version": TAXONOMY_VERSION, "keys": seeded_keys},
    )
    session.commit()
    entries, aliases = _load_taxonomy_rows(session, company_id=context.company.id)
    return _response(entries, aliases)


def get_ip_document_taxonomy(
    session: Session,
    *,
    context: SessionContext,
) -> IpDocumentTaxonomyResponse:
    entries, aliases = _load_taxonomy_rows(session, company_id=context.company.id)
    return _response(entries, aliases)


def upsert_ip_document_taxonomy_entry(
    session: Session,
    *,
    context: SessionContext,
    key: str,
    payload: IpDocumentTaxonomyUpsertRequest,
) -> IpDocumentTaxonomyEntryRecord:
    normalized_key = key.strip().casefold()
    if not _KEY_RE.fullmatch(normalized_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "Taxonomy keys must use 2-80 lowercase letters, numbers, "
                "underscores, or hyphens."
            ),
        )
    entry = session.scalar(
        select(IpDocumentTaxonomyEntry)
        .where(
            IpDocumentTaxonomyEntry.company_id == context.company.id,
            IpDocumentTaxonomyEntry.key == normalized_key,
        )
        .with_for_update()
    )
    created = entry is None
    if entry is None:
        if payload.expected_version is not None:
            raise HTTPException(status_code=409, detail="Taxonomy entry does not exist.")
        entry = IpDocumentTaxonomyEntry(
            company_id=context.company.id,
            key=normalized_key,
            label=payload.label,
            description=payload.description,
            sort_order=payload.sort_order,
            is_seeded=False,
            is_active=payload.is_active,
            version=1,
            updated_by_membership_id=context.membership.id,
        )
        session.add(entry)
        session.flush()
    else:
        if payload.expected_version != entry.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_document_taxonomy_version_conflict",
                    "current_version": entry.version,
                },
            )
        entry.label = payload.label
        entry.description = payload.description
        entry.sort_order = payload.sort_order
        entry.is_active = payload.is_active
        entry.version += 1
        entry.updated_by_membership_id = context.membership.id
        session.add(entry)

    requested_aliases = [payload.label, *payload.aliases]
    aliases_by_normalized: dict[str, str] = {}
    for alias in requested_aliases:
        normalized = _normalize_alias(alias)
        if not normalized:
            raise HTTPException(status_code=422, detail="Aliases must contain a letter or number.")
        aliases_by_normalized.setdefault(normalized, alias)
    collision = session.scalar(
        select(IpDocumentTaxonomyAlias).where(
            IpDocumentTaxonomyAlias.company_id == context.company.id,
            IpDocumentTaxonomyAlias.normalized_alias.in_(list(aliases_by_normalized)),
            IpDocumentTaxonomyAlias.taxonomy_entry_id != entry.id,
        )
    )
    if collision is not None:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_document_taxonomy_alias_conflict",
                "alias": collision.alias,
            },
        )
    session.execute(
        delete(IpDocumentTaxonomyAlias).where(
            IpDocumentTaxonomyAlias.company_id == context.company.id,
            IpDocumentTaxonomyAlias.taxonomy_entry_id == entry.id,
        )
    )
    for normalized, alias in aliases_by_normalized.items():
        session.add(
            IpDocumentTaxonomyAlias(
                company_id=context.company.id,
                taxonomy_entry_id=entry.id,
                alias=alias,
                normalized_alias=normalized,
                source="tenant",
                created_by_membership_id=context.membership.id,
            )
        )
    record_from_context(
        session,
        context,
        action="ip_document_taxonomy.created" if created else "ip_document_taxonomy.updated",
        target_type="ip_document_taxonomy_entry",
        target_id=entry.id,
        metadata={
            "key": entry.key,
            "version": entry.version,
            "alias_count": len(aliases_by_normalized),
        },
    )
    session.commit()
    session.refresh(entry)
    aliases = list(
        session.scalars(
            select(IpDocumentTaxonomyAlias)
            .where(IpDocumentTaxonomyAlias.taxonomy_entry_id == entry.id)
            .order_by(IpDocumentTaxonomyAlias.alias)
        ).all()
    )
    return _entry_record(entry, aliases)


def _sanitize_component(value: str) -> tuple[str, bool]:
    original = value
    value = unicodedata.normalize("NFKC", value).strip()
    value = _UNSAFE_FILENAME_RE.sub("_", value)
    value = _SPACE_OR_SEPARATOR_RE.sub("_", value)
    value = value.strip(" ._")
    if value[:1] in {"=", "+", "-", "@"}:
        value = f"_{value}"
    if value.casefold() in _RESERVED_WINDOWS_NAMES:
        value = f"_{value}"
    return value, value != original


def preview_ip_document_name(
    payload: IpDocumentNamingPreviewRequest,
    *,
    name_is_taken: Callable[[str], bool] | None = None,
    conflict_seed: str | None = None,
) -> IpDocumentNamingPreviewResponse:
    ordered_values = (
        ("client_code", payload.client_code),
        ("asset_type", payload.asset_type),
        ("mark", payload.mark),
        ("jurisdiction", payload.jurisdiction),
        ("application_no", payload.application_no),
        ("proceeding_type", payload.proceeding_type),
        ("proceeding_no", payload.proceeding_no),
        ("document_type", payload.document_type),
        ("document_date", payload.document_date.isoformat() if payload.document_date else None),
        ("version", str(payload.version)),
    )
    components: list[str] = []
    omitted: list[str] = []
    warnings: list[str] = []
    for field_name, raw_value in ordered_values:
        if raw_value is None or not raw_value.strip():
            omitted.append(field_name)
            continue
        component, changed = _sanitize_component(raw_value)
        if not component:
            omitted.append(field_name)
            warnings.append(f"{field_name} contained no filename-safe characters and was omitted.")
            continue
        if changed:
            warnings.append(f"{field_name} was sanitized for filesystem and export safety.")
        components.append(component)
    extension = ""
    if payload.extension:
        raw_extension = payload.extension.lstrip(".")
        safe_extension = re.sub(r"[^A-Za-z0-9]+", "", raw_extension)[:16].casefold()
        if safe_extension:
            extension = f".{safe_extension}"
        if safe_extension != raw_extension:
            warnings.append("extension was sanitized.")
    base = "_".join(components) or "document"
    max_base_length = 240 - len(extension)
    if len(base) > max_base_length:
        base = base[:max_base_length].rstrip(" ._")
        warnings.append("name was truncated to the 240-character storage-safe limit.")
    requested = f"{base}{extension}"
    existing = {name.casefold() for name in payload.existing_names}

    def is_taken(candidate: str) -> bool:
        return candidate.casefold() in existing or (
            name_is_taken is not None and name_is_taken(candidate)
        )

    resolved = requested
    suffix: int | None = None
    if name_is_taken is None:
        candidate_numbers = iter(range(2, 2_147_483_647))
    else:
        # Persisted naming must never scan an entire tenant or perform an
        # unbounded suffix loop. Try the familiar small suffixes first, then
        # jump to a stable document-derived range. The caller serializes
        # allocations under the tenant lock, so the selected name cannot race
        # another upload in the same workspace.
        stable_start = 1_000_000_000
        if conflict_seed:
            stable_start += int(hashlib.sha256(conflict_seed.encode()).hexdigest()[:8], 16)
        candidate_numbers = iter([*range(2, 34), *range(stable_start, stable_start + 32)])
    while is_taken(resolved):
        try:
            suffix = next(candidate_numbers)
        except StopIteration as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_document_name_allocation_exhausted",
                    "message": "Could not allocate a unique document name. Retry the upload.",
                },
            ) from exc
        suffix_text = f"_{suffix}"
        candidate_base = base[: 240 - len(extension) - len(suffix_text)].rstrip(" ._")
        resolved = f"{candidate_base}{suffix_text}{extension}"
    if suffix is not None:
        warnings.append(
            "A deterministic numeric suffix was added; no existing name was overwritten."
        )
    export_safe = f"'{resolved}" if resolved[:1] in {"=", "+", "-", "@"} else resolved
    return IpDocumentNamingPreviewResponse(
        pattern=NAMING_PATTERN,
        requested_name=requested,
        resolved_name=resolved,
        conflict_detected=suffix is not None,
        conflict_suffix=suffix,
        sanitized_components=components,
        omitted_components=omitted,
        warnings=warnings,
        export_safe_name=export_safe,
    )


def ip_document_foundation_contract() -> IpDocumentFoundationContract:
    return IpDocumentFoundationContract(
        taxonomy_version=TAXONOMY_VERSION,
        naming_pattern=NAMING_PATTERN,
        supported_link_targets=LINK_TARGETS,
    )
