from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    AuthorityDocument,
    CompanyMembership,
    Contract,
    ContractLegalReference,
    LegalUpdateAlert,
    LegalUpdateSourceRecord,
    LegalUpdateWatchlist,
    Matter,
    MatterStatuteReference,
    MembershipRole,
    NotificationDeliveryChannel,
    Statute,
    StatuteSection,
    User,
)
from caseops_api.schemas.legal_updates import (
    LegalUpdateActionRequest,
    LegalUpdateDigestPreviewResponse,
    LegalUpdateListResponse,
    LegalUpdateRecord,
    LegalUpdateRunRequest,
    LegalUpdateRunResponse,
    LegalUpdateWatchlistCreateRequest,
    LegalUpdateWatchlistListResponse,
    LegalUpdateWatchlistRecord,
    LegalUpdateWatchlistUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.authority_sources import (
    SOURCE_CATEGORY_STATUTORY_BARE_ACT,
    get_legal_source_readiness,
    get_legal_source_registry_entry,
    list_legal_source_registry_entries,
)
from caseops_api.services.matter_access import assert_access
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext

_ALLOWED_UPDATE_TYPES = {
    "act",
    "amendment",
    "ordinance",
    "notification",
    "repeal",
    "regulation",
    "circular",
    "order",
    "practice_direction",
}
_DEFAULT_UPDATE_TYPES = [
    "act",
    "amendment",
    "ordinance",
    "notification",
    "repeal",
    "regulation",
    "circular",
    "order",
    "practice_direction",
]
_AUTHORITY_UPDATE_TYPES = {
    "notice": "notification",
    "order": "order",
    "practice_direction": "practice_direction",
}
_STATUTE_SOURCE_KEY = "india_code_bare_acts"
_PRS_SOURCE_KEY = "prs_acts_parliament"
_PRS_SOURCE_CATEGORY = "prs_india"
_SOURCE_METADATA_AVAILABLE = "source_metadata_available"
_MAX_TERM_LENGTH = 80
_MAX_TERMS = 8
_MAX_SNIPPET_LENGTH = 280
_CANDIDATE_SCAN_LIMIT = 300


@dataclass(frozen=True)
class _LegalUpdateMatch:
    source_record_key: str
    update_type: str
    title: str
    source_record_id: str | None = None
    statute_id: str | None = None
    statute_section_id: str | None = None
    authority_document_id: str | None = None
    statute_name: str | None = None
    section_number: str | None = None
    jurisdiction: str | None = None
    source_key: str = _STATUTE_SOURCE_KEY
    source_category: str = SOURCE_CATEGORY_STATUTORY_BARE_ACT
    source_url: str | None = None
    provenance_status: str = _SOURCE_METADATA_AVAILABLE
    relevance_explanation: str = "Matched bounded watchlist filters against existing records."
    snippet: str | None = None
    summary_json: dict | None = None
    effective_date: date | None = None
    published_date: date | None = None
    decision_date: date | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _hash_value(value: object) -> str:
    blob = json.dumps(value, default=str, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _compact_text(value: str | None, *, max_length: int) -> str | None:
    if value is None:
        return None
    compacted = re.sub(r"\s+", " ", value).strip()
    if not compacted:
        return None
    return compacted[:max_length]


def _normalize_terms(value: Iterable[str] | None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for raw in value or []:
        term = _compact_text(str(raw), max_length=_MAX_TERM_LENGTH)
        if term is None:
            continue
        folded = term.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        terms.append(term)
        if len(terms) >= _MAX_TERMS:
            break
    return terms


def _normalize_update_types(value: Iterable[str] | None) -> list[str]:
    cleaned: list[str] = []
    for raw in value or _DEFAULT_UPDATE_TYPES:
        update_type = str(raw).strip()
        if update_type not in _ALLOWED_UPDATE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported legal update type.",
        )
        if update_type not in cleaned:
            cleaned.append(update_type)
    return cleaned or list(_DEFAULT_UPDATE_TYPES)


def _require_valid_dates(
    rule: LegalUpdateWatchlist | LegalUpdateWatchlistCreateRequest,
) -> None:
    if rule.since_date and rule.until_date and rule.since_date > rule.until_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="since_date must be on or before until_date.",
        )


def _require_bounded_filters(rule: LegalUpdateWatchlist) -> None:
    if any(
        (
            rule.practice_area,
            rule.statute_id,
            rule.jurisdiction,
            rule.statute_terms_json,
            rule.source_key,
            rule.source_category,
            rule.since_date,
            rule.until_date,
            rule.matter_id,
            rule.contract_id,
        )
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Legal update watchlists require at least one bounded filter.",
    )


def _known_source_categories() -> set[str]:
    return {
        *{entry.source_category for entry in list_legal_source_registry_entries()},
        _PRS_SOURCE_CATEGORY,
    }


def _validate_source_filters(source_key: str | None, source_category: str | None) -> None:
    if (
        source_key
        and source_key != _PRS_SOURCE_KEY
        and get_legal_source_registry_entry(source_key) is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown legal source registry key.",
        )
    if source_category and source_category not in _known_source_categories():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown legal source category.",
        )


def _load_statute_or_404(
    session: Session,
    statute_id: str | None,
) -> Statute | None:
    if statute_id is None:
        return None
    statute = session.scalar(
        select(Statute).where(Statute.id == statute_id, Statute.is_active.is_(True))
    )
    if statute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Statute not found.",
        )
    return statute


def _load_matter_with_access(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter | None:
    if matter_id is None:
        return None
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _load_contract_or_404(
    session: Session,
    *,
    context: SessionContext,
    contract_id: str | None,
) -> Contract | None:
    if contract_id is None:
        return None
    contract = session.scalar(
        select(Contract).where(
            Contract.id == contract_id,
            Contract.company_id == context.company.id,
        )
    )
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contract not found.",
        )
    return contract


def _watchlist_record(rule: LegalUpdateWatchlist) -> LegalUpdateWatchlistRecord:
    return LegalUpdateWatchlistRecord(
        id=rule.id,
        company_id=rule.company_id,
        name=rule.name,
        practice_area=rule.practice_area,
        statute_id=rule.statute_id,
        jurisdiction=rule.jurisdiction,
        statute_terms=list(rule.statute_terms_json or []),
        source_key=rule.source_key,
        source_category=rule.source_category,
        update_types=_normalize_update_types(rule.update_types_json),  # type: ignore[arg-type]
        since_date=rule.since_date,
        until_date=rule.until_date,
        matter_id=rule.matter_id,
        contract_id=rule.contract_id,
        is_archived=rule.is_archived,
        created_by_membership_id=rule.created_by_membership_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        archived_at=rule.archived_at,
    )


def _watchlist_filter_keys(rule: LegalUpdateWatchlist) -> list[str]:
    keys: list[str] = []
    if rule.practice_area:
        keys.append("practice_area")
    if rule.statute_id:
        keys.append("statute_id")
    if rule.jurisdiction:
        keys.append("jurisdiction")
    if rule.statute_terms_json:
        keys.append("statute_terms")
    if rule.source_key:
        keys.append("source_key")
    if rule.source_category:
        keys.append("source_category")
    if rule.update_types_json:
        keys.append("update_types")
    if rule.since_date or rule.until_date:
        keys.append("date_range")
    if rule.matter_id:
        keys.append("matter_id")
    if rule.contract_id:
        keys.append("contract_id")
    return keys


def _watchlist_audit_metadata(
    rule: LegalUpdateWatchlist,
    *,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "filter_keys": _watchlist_filter_keys(rule),
        "statute_term_count": len(rule.statute_terms_json or []),
        "statute_terms_sha256": _hash_value(rule.statute_terms_json or []),
        "update_type_count": len(rule.update_types_json or []),
        "has_practice_area_filter": bool(rule.practice_area),
        "has_statute_filter": bool(rule.statute_id),
        "has_jurisdiction_filter": bool(rule.jurisdiction),
        "has_source_filter": bool(rule.source_key or rule.source_category),
        "has_date_filter": bool(rule.since_date or rule.until_date),
        "has_matter_scope": bool(rule.matter_id),
        "has_contract_scope": bool(rule.contract_id),
        "is_archived": bool(rule.is_archived),
    }
    if extra:
        metadata.update(extra)
    return metadata


def list_legal_update_watchlists(
    session: Session,
    *,
    context: SessionContext,
) -> LegalUpdateWatchlistListResponse:
    rows = list(
        session.scalars(
            select(LegalUpdateWatchlist)
            .where(LegalUpdateWatchlist.company_id == context.company.id)
            .order_by(LegalUpdateWatchlist.created_at.desc())
        )
    )
    return LegalUpdateWatchlistListResponse(
        watchlists=[_watchlist_record(row) for row in rows]
    )


def create_legal_update_watchlist(
    session: Session,
    *,
    context: SessionContext,
    payload: LegalUpdateWatchlistCreateRequest,
) -> LegalUpdateWatchlistRecord:
    _require_valid_dates(payload)
    _validate_source_filters(payload.source_key, payload.source_category)
    _load_statute_or_404(session, payload.statute_id)
    _load_matter_with_access(session, context=context, matter_id=payload.matter_id)
    _load_contract_or_404(session, context=context, contract_id=payload.contract_id)
    watchlist = LegalUpdateWatchlist(
        company_id=context.company.id,
        created_by_membership_id=context.membership.id,
        name=payload.name,
        practice_area=payload.practice_area,
        statute_id=payload.statute_id,
        jurisdiction=payload.jurisdiction,
        statute_terms_json=_normalize_terms(payload.statute_terms),
        source_key=payload.source_key,
        source_category=payload.source_category,
        update_types_json=_normalize_update_types(payload.update_types),
        since_date=payload.since_date,
        until_date=payload.until_date,
        matter_id=payload.matter_id,
        contract_id=payload.contract_id,
    )
    _require_bounded_filters(watchlist)
    session.add(watchlist)
    session.flush()
    record_from_context(
        session,
        context,
        action="legal_update.watchlist_created",
        target_type="legal_update_watchlist",
        target_id=watchlist.id,
        matter_id=watchlist.matter_id,
        metadata=_watchlist_audit_metadata(watchlist),
    )
    session.commit()
    return _watchlist_record(watchlist)


def _get_watchlist(
    session: Session,
    *,
    context: SessionContext,
    watchlist_id: str,
) -> LegalUpdateWatchlist:
    watchlist = session.scalar(
        select(LegalUpdateWatchlist).where(
            LegalUpdateWatchlist.id == watchlist_id,
            LegalUpdateWatchlist.company_id == context.company.id,
        )
    )
    if watchlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal update watchlist not found.",
        )
    if watchlist.matter_id:
        _load_matter_with_access(session, context=context, matter_id=watchlist.matter_id)
    return watchlist


def update_legal_update_watchlist(
    session: Session,
    *,
    context: SessionContext,
    watchlist_id: str,
    payload: LegalUpdateWatchlistUpdateRequest,
) -> LegalUpdateWatchlistRecord:
    watchlist = _get_watchlist(session, context=context, watchlist_id=watchlist_id)
    fields = payload.model_fields_set
    if "name" in fields and payload.name:
        watchlist.name = payload.name
    if "practice_area" in fields:
        watchlist.practice_area = payload.practice_area
    if "statute_id" in fields:
        _load_statute_or_404(session, payload.statute_id)
        watchlist.statute_id = payload.statute_id
    if "jurisdiction" in fields:
        watchlist.jurisdiction = payload.jurisdiction
    if "statute_terms" in fields:
        watchlist.statute_terms_json = _normalize_terms(payload.statute_terms)
    if "source_key" in fields:
        _validate_source_filters(payload.source_key, watchlist.source_category)
        watchlist.source_key = payload.source_key
    if "source_category" in fields:
        _validate_source_filters(watchlist.source_key, payload.source_category)
        watchlist.source_category = payload.source_category
    if "update_types" in fields:
        watchlist.update_types_json = _normalize_update_types(payload.update_types)
    if "since_date" in fields:
        watchlist.since_date = payload.since_date
    if "until_date" in fields:
        watchlist.until_date = payload.until_date
    if "matter_id" in fields:
        _load_matter_with_access(session, context=context, matter_id=payload.matter_id)
        watchlist.matter_id = payload.matter_id
    if "contract_id" in fields:
        _load_contract_or_404(session, context=context, contract_id=payload.contract_id)
        watchlist.contract_id = payload.contract_id
    if "is_archived" in fields and payload.is_archived is not None:
        watchlist.is_archived = payload.is_archived
        watchlist.archived_at = _now() if payload.is_archived else None
    _require_valid_dates(watchlist)
    _require_bounded_filters(watchlist)
    session.add(watchlist)
    record_from_context(
        session,
        context,
        action="legal_update.watchlist_updated",
        target_type="legal_update_watchlist",
        target_id=watchlist.id,
        matter_id=watchlist.matter_id,
        metadata=_watchlist_audit_metadata(
            watchlist,
            extra={"updated_field_count": len(fields)},
        ),
    )
    session.commit()
    return _watchlist_record(watchlist)


def _terms_match(search_text: str, terms: Iterable[str] | None) -> bool:
    cleaned = _normalize_terms(terms)
    if not cleaned:
        return True
    return all(term.casefold() in search_text for term in cleaned)


def _date_in_range(
    value: date | None,
    *,
    since_date: date | None,
    until_date: date | None,
) -> bool:
    if value is None:
        return since_date is None and until_date is None
    if since_date and value < since_date:
        return False
    if until_date and value > until_date:
        return False
    return True


def _source_readiness(source_key: str) -> str:
    readiness = get_legal_source_readiness(source_key)
    if readiness is None:
        return _SOURCE_METADATA_AVAILABLE
    return readiness.readiness_status


def _statute_source_matches(rule: LegalUpdateWatchlist) -> bool:
    if rule.source_key and rule.source_key != _STATUTE_SOURCE_KEY:
        return False
    if rule.source_category and rule.source_category != SOURCE_CATEGORY_STATUTORY_BARE_ACT:
        return False
    return True


def _authority_source_category(document: AuthorityDocument) -> str:
    entry = get_legal_source_registry_entry(document.source)
    return entry.source_category if entry else "authority_document"


def _authority_source_matches(rule: LegalUpdateWatchlist, document: AuthorityDocument) -> bool:
    if rule.source_key and document.source != rule.source_key:
        return False
    if rule.source_category and _authority_source_category(document) != rule.source_category:
        return False
    return True


def _statute_search_text(section: StatuteSection, statute: Statute) -> str:
    parts = [
        statute.short_name,
        statute.long_name,
        statute.jurisdiction,
        section.section_number,
        section.section_label,
        section.section_text,
        section.section_text_source,
    ]
    return " ".join(part for part in parts if part).casefold()


def _authority_search_text(document: AuthorityDocument) -> str:
    sections = document.sections_cited_json
    if isinstance(sections, list):
        section_text = " ".join(str(item) for item in sections[:20])
    else:
        section_text = str(sections or "")
    chunk_text = " ".join(
        _compact_text(chunk.content, max_length=800) or ""
        for chunk in list(document.chunks or [])[:4]
    )
    parts = [
        document.title,
        document.summary,
        document.court_name,
        document.forum_level,
        document.document_type,
        document.case_reference,
        document.neutral_citation,
        document.source,
        document.source_reference,
        section_text,
        chunk_text,
    ]
    return " ".join(part for part in parts if part).casefold()


def _snippet(*values: str | None) -> str | None:
    for value in values:
        compacted = _compact_text(value, max_length=_MAX_SNIPPET_LENGTH)
        if compacted:
            return compacted
    return None


def _summary_payload(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    required = {
        "plain_english_summary",
        "practical_legal_impact",
        "source_url",
        "provenance_status",
    }
    if not required <= set(value):
        return None
    return dict(value)


def _source_record_search_text(record: LegalUpdateSourceRecord) -> str:
    raw_metadata = record.raw_metadata_json
    if isinstance(raw_metadata, dict):
        metadata_text = json.dumps(raw_metadata, default=str, sort_keys=True)
    else:
        metadata_text = str(raw_metadata or "")
    summary = _summary_payload(record.summary_json)
    summary_text = json.dumps(summary, default=str, sort_keys=True) if summary else ""
    statute_text = ""
    if record.statute:
        statute_text = " ".join(
            part
            for part in (
                record.statute.short_name,
                record.statute.long_name,
                record.statute.jurisdiction,
            )
            if part
        )
    parts = [
        record.title,
        record.normalized_title,
        record.update_type,
        record.source_key,
        record.source_category,
        record.provenance_status,
        str(record.act_year or ""),
        metadata_text,
        summary_text,
        statute_text,
        " ".join(str(item) for item in (record.sections_changed_json or [])),
    ]
    return " ".join(part for part in parts if part).casefold()


def _source_record_date(record: LegalUpdateSourceRecord) -> date | None:
    return record.published_date or record.effective_date


def _source_record_candidate_query(rule: LegalUpdateWatchlist):
    statement = select(LegalUpdateSourceRecord).options(
        selectinload(LegalUpdateSourceRecord.statute)
    )
    if rule.source_key:
        statement = statement.where(LegalUpdateSourceRecord.source_key == rule.source_key)
    if rule.source_category:
        statement = statement.where(
            LegalUpdateSourceRecord.source_category == rule.source_category
        )
    if rule.statute_id:
        statement = statement.where(
            (LegalUpdateSourceRecord.statute_id == rule.statute_id)
            | (LegalUpdateSourceRecord.statute_id.is_(None))
        )
    if rule.since_date:
        statement = statement.where(
            (LegalUpdateSourceRecord.published_date >= rule.since_date)
            | (LegalUpdateSourceRecord.published_date.is_(None))
        )
    if rule.until_date:
        statement = statement.where(
            (LegalUpdateSourceRecord.published_date <= rule.until_date)
            | (LegalUpdateSourceRecord.published_date.is_(None))
        )
    return statement.order_by(
        LegalUpdateSourceRecord.published_date.desc().nullslast(),
        LegalUpdateSourceRecord.last_seen_at.desc(),
    ).limit(_CANDIDATE_SCAN_LIMIT)


def _statute_candidate_query(rule: LegalUpdateWatchlist):
    statement = (
        select(StatuteSection, Statute)
        .join(Statute, Statute.id == StatuteSection.statute_id)
        .where(StatuteSection.is_active.is_(True), Statute.is_active.is_(True))
    )
    if rule.statute_id:
        statement = statement.where(Statute.id == rule.statute_id)
    if rule.jurisdiction:
        statement = statement.where(Statute.jurisdiction.ilike(f"%{rule.jurisdiction}%"))
    return statement.order_by(Statute.short_name, StatuteSection.ordinal).limit(
        _CANDIDATE_SCAN_LIMIT
    )


def _authority_candidate_query(rule: LegalUpdateWatchlist):
    statement = (
        select(AuthorityDocument)
        .options(selectinload(AuthorityDocument.chunks))
        .where(AuthorityDocument.document_type.in_(tuple(_AUTHORITY_UPDATE_TYPES)))
    )
    if rule.source_key:
        statement = statement.where(AuthorityDocument.source == rule.source_key)
    if rule.since_date:
        statement = statement.where(AuthorityDocument.decision_date >= rule.since_date)
    if rule.until_date:
        statement = statement.where(AuthorityDocument.decision_date <= rule.until_date)
    return statement.order_by(
        AuthorityDocument.decision_date.desc().nullslast(),
        AuthorityDocument.updated_at.desc(),
    ).limit(_CANDIDATE_SCAN_LIMIT)


def _matter_relevance_notes(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
    statute_id: str | None,
    section_id: str | None,
) -> list[str]:
    if rule.matter_id is None:
        return []
    notes: list[str] = []
    matter = session.get(Matter, rule.matter_id)
    if matter is None:
        return notes
    if rule.practice_area and matter.practice_area:
        if rule.practice_area.casefold() in matter.practice_area.casefold():
            notes.append("matter practice area matched watchlist practice area")
    if rule.jurisdiction:
        matter_forum = " ".join(
            part
            for part in (
                matter.forum_state,
                matter.forum_district,
                matter.forum_city,
                matter.court_name,
                matter.forum_level,
            )
            if part
        ).casefold()
        if rule.jurisdiction.casefold() in matter_forum:
            notes.append("jurisdiction matched matter forum metadata")
    if statute_id or section_id:
        ref_stmt = select(MatterStatuteReference).where(
            MatterStatuteReference.matter_id == matter.id
        )
        refs = list(session.scalars(ref_stmt))
        if any(ref.section_id == section_id for ref in refs):
            notes.append("matter statute references matched watched section")
        elif statute_id:
            section_ids = set(
                session.scalars(
                    select(StatuteSection.id).where(StatuteSection.statute_id == statute_id)
                )
            )
            if any(ref.section_id in section_ids for ref in refs):
                notes.append("matter statute references matched watched Act")
    return notes


def _contract_relevance_notes(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
    statute_id: str | None,
    search_text: str,
) -> list[str]:
    if rule.contract_id is None:
        return []
    contract = session.get(Contract, rule.contract_id)
    if contract is None:
        return []
    notes: list[str] = []
    if rule.jurisdiction and contract.jurisdiction:
        if rule.jurisdiction.casefold() in contract.jurisdiction.casefold():
            notes.append("jurisdiction matched contract metadata")
    refs = list(
        session.scalars(
            select(ContractLegalReference).where(
                ContractLegalReference.company_id == rule.company_id,
                ContractLegalReference.contract_id == contract.id,
            )
        )
    )
    for ref in refs:
        if statute_id and ref.statute_id == statute_id:
            notes.append("contract legal references matched watched statute/Act")
            break
        needle = " ".join(part for part in (ref.act_name, ref.section_label) if part).casefold()
        if needle and needle in search_text:
            notes.append("contract legal references matched watched statute/Act")
            break
    return notes


def _relevance_explanation(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
    source_kind: str,
    statute_id: str | None,
    section_id: str | None,
    search_text: str,
) -> str:
    reasons: list[str] = []
    if rule.statute_id:
        reasons.append("watched Act")
    if rule.statute_terms_json:
        reasons.append("statute/section terms")
    if rule.practice_area:
        reasons.append("practice-area filter")
    if rule.jurisdiction:
        reasons.append("jurisdiction filter")
    if rule.source_key or rule.source_category:
        reasons.append("source registry filter")
    if rule.update_types_json:
        reasons.append("update type filter")
    if rule.since_date or rule.until_date:
        reasons.append("date filter")
    reasons.extend(
        _matter_relevance_notes(
            session,
            rule=rule,
            statute_id=statute_id,
            section_id=section_id,
        )
    )
    reasons.extend(
        _contract_relevance_notes(
            session,
            rule=rule,
            statute_id=statute_id,
            search_text=search_text,
        )
    )
    joined = "; ".join(dict.fromkeys(reasons)) or "bounded watchlist filters"
    return f"Matched {joined} against existing {source_kind} metadata."[:500]


def _source_record_matches(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
) -> list[_LegalUpdateMatch]:
    allowed_types = set(_normalize_update_types(rule.update_types_json))
    matches: list[_LegalUpdateMatch] = []
    for record in session.scalars(_source_record_candidate_query(rule)):
        if record.update_type not in allowed_types:
            continue
        row_date = _source_record_date(record)
        if not _date_in_range(
            row_date,
            since_date=rule.since_date,
            until_date=rule.until_date,
        ):
            continue
        search_text = _source_record_search_text(record)
        if rule.practice_area and rule.practice_area.casefold() not in search_text:
            continue
        if rule.jurisdiction:
            jurisdiction = "india"
            if record.statute and record.statute.jurisdiction:
                jurisdiction = record.statute.jurisdiction
            if rule.jurisdiction.casefold() not in jurisdiction.casefold():
                continue
        if rule.statute_id:
            statute = session.get(Statute, rule.statute_id)
            statute_terms = [
                part
                for part in (
                    statute.short_name if statute else None,
                    statute.long_name if statute else None,
                )
                if part
            ]
            if record.statute_id != rule.statute_id and not any(
                term.casefold() in search_text for term in statute_terms
            ):
                continue
        if not _terms_match(search_text, rule.statute_terms_json):
            continue

        summary = _summary_payload(record.summary_json)
        statute_name = record.statute.short_name if record.statute else None
        match = _LegalUpdateMatch(
            source_record_key=record.source_record_key,
            source_record_id=record.id,
            update_type=record.update_type,
            title=_compact_text(record.title, max_length=255) or "Legal update",
            statute_id=record.statute_id,
            statute_section_id=None,
            statute_name=statute_name,
            section_number=None,
            jurisdiction=record.statute.jurisdiction if record.statute else "india",
            source_key=record.source_key,
            source_category=record.source_category or _PRS_SOURCE_CATEGORY,
            source_url=record.source_url,
            provenance_status=record.provenance_status,
            relevance_explanation=_relevance_explanation(
                session,
                rule=rule,
                source_kind="source record",
                statute_id=record.statute_id,
                section_id=None,
                search_text=search_text,
            ),
            snippet=_snippet(
                summary.get("plain_english_summary") if summary else None,
                record.title,
            ),
            summary_json=summary,
            effective_date=record.effective_date,
            published_date=record.published_date,
        )
        matches.append(match)
    return matches


def _section_matches(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
) -> list[_LegalUpdateMatch]:
    if "amendment" not in _normalize_update_types(rule.update_types_json):
        return []
    if not _statute_source_matches(rule):
        return []
    matches: list[_LegalUpdateMatch] = []
    for section, statute in session.execute(_statute_candidate_query(rule)).all():
        row_date = section.updated_at.date() if section.updated_at else None
        if not _date_in_range(
            row_date,
            since_date=rule.since_date,
            until_date=rule.until_date,
        ):
            continue
        search_text = _statute_search_text(section, statute)
        if rule.practice_area and rule.practice_area.casefold() not in search_text:
            continue
        if not _terms_match(search_text, rule.statute_terms_json):
            continue
        title_parts = [statute.short_name, section.section_number]
        if section.section_label:
            title_parts.append(section.section_label)
        title = ": ".join((" ".join(title_parts[:2]), " ".join(title_parts[2:])))
        source_url = section.section_url or statute.source_url
        matches.append(
            _LegalUpdateMatch(
                source_record_key=f"statute_section:{section.id}",
                update_type="amendment",
                title=_compact_text(title, max_length=255) or statute.short_name,
                statute_id=statute.id,
                statute_section_id=section.id,
                statute_name=statute.short_name,
                section_number=section.section_number,
                jurisdiction=statute.jurisdiction,
                source_key=_STATUTE_SOURCE_KEY,
                source_category=SOURCE_CATEGORY_STATUTORY_BARE_ACT,
                source_url=source_url,
                provenance_status=_source_readiness(_STATUTE_SOURCE_KEY),
                relevance_explanation=_relevance_explanation(
                    session,
                    rule=rule,
                    source_kind="statute",
                    statute_id=statute.id,
                    section_id=section.id,
                    search_text=search_text,
                ),
                snippet=_snippet(section.section_label, section.section_text),
                published_date=row_date,
            )
        )
    return matches


def _authority_matches(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
) -> list[_LegalUpdateMatch]:
    allowed_types = set(_normalize_update_types(rule.update_types_json))
    matches: list[_LegalUpdateMatch] = []
    for document in session.scalars(_authority_candidate_query(rule)):
        update_type = _AUTHORITY_UPDATE_TYPES.get(str(document.document_type))
        if update_type is None or update_type not in allowed_types:
            continue
        if not _authority_source_matches(rule, document):
            continue
        if rule.jurisdiction:
            jurisdiction_text = " ".join(
                part
                for part in (
                    document.court_name,
                    document.forum_level,
                    get_legal_source_registry_entry(document.source).jurisdiction
                    if get_legal_source_registry_entry(document.source)
                    else None,
                )
                if part
            ).casefold()
            if rule.jurisdiction.casefold() not in jurisdiction_text:
                continue
        search_text = _authority_search_text(document)
        if rule.practice_area and rule.practice_area.casefold() not in search_text:
            continue
        if not _terms_match(search_text, rule.statute_terms_json):
            continue
        source_category = _authority_source_category(document)
        matches.append(
            _LegalUpdateMatch(
                source_record_key=f"authority_document:{document.id}",
                update_type=update_type,
                title=_compact_text(document.title, max_length=255) or "Legal update",
                authority_document_id=document.id,
                jurisdiction=document.court_name or document.forum_level,
                source_key=document.source,
                source_category=source_category,
                source_url=document.source_reference,
                provenance_status=_source_readiness(document.source),
                relevance_explanation=_relevance_explanation(
                    session,
                    rule=rule,
                    source_kind="authority/source",
                    statute_id=None,
                    section_id=None,
                    search_text=search_text,
                ),
                snippet=_snippet(document.summary, *[c.content for c in document.chunks[:4]]),
                decision_date=document.decision_date,
            )
        )
    return matches


def _match_record(
    match: _LegalUpdateMatch,
    *,
    company_id: str,
    watchlist_id: str,
) -> LegalUpdateRecord:
    return LegalUpdateRecord(
        id=f"preview:{_hash_value([watchlist_id, match.source_record_key])[:24]}",
        company_id=company_id,
        watchlist_id=watchlist_id,
        source_record_id=match.source_record_id,
        update_type=match.update_type,  # type: ignore[arg-type]
        title=match.title,
        statute_id=match.statute_id,
        statute_section_id=match.statute_section_id,
        authority_document_id=match.authority_document_id,
        matter_id=None,
        contract_id=None,
        statute_name=match.statute_name,
        section_number=match.section_number,
        jurisdiction=match.jurisdiction,
        source_key=match.source_key,
        source_category=match.source_category,
        source_url=match.source_url,
        provenance_status=match.provenance_status,
        relevance_explanation=match.relevance_explanation,
        effective_date=match.effective_date,
        published_date=match.published_date,
        decision_date=match.decision_date,
        snippet=_compact_text(match.snippet, max_length=_MAX_SNIPPET_LENGTH),
        summary=match.summary_json,  # type: ignore[arg-type]
        is_read=False,
        read_at=None,
        dismissed_at=None,
        created_at=_now(),
    )


def _alert_record(alert: LegalUpdateAlert) -> LegalUpdateRecord:
    return LegalUpdateRecord(
        id=alert.id,
        company_id=alert.company_id,
        watchlist_id=alert.watchlist_id,
        source_record_id=alert.source_record_id,
        update_type=alert.update_type,  # type: ignore[arg-type]
        title=alert.title,
        statute_id=alert.statute_id,
        statute_section_id=alert.statute_section_id,
        authority_document_id=alert.authority_document_id,
        matter_id=alert.matter_id,
        contract_id=alert.contract_id,
        statute_name=alert.statute_name,
        section_number=alert.section_number,
        jurisdiction=alert.jurisdiction,
        source_key=alert.source_key,
        source_category=alert.source_category,
        source_url=alert.source_url,
        provenance_status=alert.provenance_status,
        relevance_explanation=alert.relevance_explanation,
        effective_date=alert.effective_date,
        published_date=alert.published_date,
        decision_date=alert.decision_date,
        snippet=_compact_text(alert.snippet, max_length=_MAX_SNIPPET_LENGTH),
        summary=_summary_payload(alert.summary_json),  # type: ignore[arg-type]
        is_read=alert.is_read,
        read_at=alert.read_at,
        dismissed_at=alert.dismissed_at,
        created_at=alert.created_at,
    )


def _matches_for_watchlist(
    session: Session,
    *,
    rule: LegalUpdateWatchlist,
) -> list[_LegalUpdateMatch]:
    matches = [
        *_source_record_matches(session, rule=rule),
        *_section_matches(session, rule=rule),
        *_authority_matches(session, rule=rule),
    ]
    deduped: dict[str, _LegalUpdateMatch] = {}
    for match in matches:
        deduped.setdefault(match.source_record_key, match)
    return list(deduped.values())


def _active_internal_memberships(
    session: Session,
    *,
    company_id: str,
) -> list[CompanyMembership]:
    internal_roles = tuple(role.value for role in MembershipRole)
    return list(
        session.scalars(
            select(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
                CompanyMembership.role.in_(internal_roles),
                User.is_active.is_(True),
            )
            .order_by(CompanyMembership.created_at.asc())
        )
    )


def _notification_body(match: _LegalUpdateMatch) -> str:
    summary = _summary_payload(match.summary_json)
    if summary:
        text = str(summary.get("plain_english_summary") or "")
    else:
        text = match.snippet or match.relevance_explanation
    parts = [
        text,
        f"Source: {match.source_key}",
        f"Provenance: {match.provenance_status}",
    ]
    return " ".join(part for part in parts if part)


def _enqueue_legal_update_notifications(
    session: Session,
    *,
    context: SessionContext,
    watchlist: LegalUpdateWatchlist,
    alert: LegalUpdateAlert,
    match: _LegalUpdateMatch,
) -> int:
    matter = session.get(Matter, watchlist.matter_id) if watchlist.matter_id else None
    created_or_existing = 0
    for membership in _active_internal_memberships(session, company_id=context.company.id):
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=membership,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type="legal_update.watchlist_matched",
            source_type="legal_update_alert",
            source_id=alert.id,
            matter=matter,
            title=f"Legal update matched: {match.title}"[:255],
            body=_notification_body(match),
        )
        if intent is not None:
            created_or_existing += 1
            record_from_context(
                session,
                context,
                action="legal_update.notification_enqueued",
                target_type="notification_delivery_intent",
                target_id=intent.id,
                matter_id=watchlist.matter_id,
                metadata={
                    "watchlist_id_sha256": _hash_value(watchlist.id),
                    "alert_id_sha256": _hash_value(alert.id),
                    "recipient_membership_id_sha256": _hash_value(membership.id),
                    "channel": NotificationDeliveryChannel.IN_APP,
                    "event_type": "legal_update.watchlist_matched",
                },
            )
    return created_or_existing


def run_legal_update_watchlist(
    session: Session,
    *,
    context: SessionContext,
    watchlist_id: str,
    payload: LegalUpdateRunRequest,
) -> LegalUpdateRunResponse:
    watchlist = _get_watchlist(session, context=context, watchlist_id=watchlist_id)
    if watchlist.is_archived:
        record_from_context(
            session,
            context,
            action="legal_update.watchlist_run",
            target_type="legal_update_watchlist",
            target_id=watchlist.id,
            matter_id=watchlist.matter_id,
            metadata=_watchlist_audit_metadata(
                watchlist,
                extra={
                    "preview_only": payload.preview_only,
                    "matched_count": 0,
                    "created_count": 0,
                    "archived_watchlist": True,
                },
            ),
        )
        session.commit()
        return LegalUpdateRunResponse(
            watchlist_id=watchlist.id,
            preview_only=payload.preview_only,
            matched_count=0,
            created_count=0,
            matches=[],
        )

    matches = _matches_for_watchlist(session, rule=watchlist)[: payload.limit]
    created_count = 0
    notification_intent_count = 0
    if not payload.preview_only:
        for match in matches:
            existing = session.scalar(
                select(LegalUpdateAlert).where(
                    LegalUpdateAlert.company_id == context.company.id,
                    LegalUpdateAlert.watchlist_id == watchlist.id,
                    LegalUpdateAlert.source_record_key == match.source_record_key,
                )
            )
            if existing is not None:
                continue
            alert = LegalUpdateAlert(
                company_id=context.company.id,
                watchlist_id=watchlist.id,
                source_record_key=match.source_record_key,
                source_record_id=match.source_record_id,
                update_type=match.update_type,
                title=match.title,
                statute_id=match.statute_id,
                statute_section_id=match.statute_section_id,
                authority_document_id=match.authority_document_id,
                matter_id=watchlist.matter_id,
                contract_id=watchlist.contract_id,
                statute_name=match.statute_name,
                section_number=match.section_number,
                jurisdiction=match.jurisdiction,
                source_key=match.source_key,
                source_category=match.source_category,
                source_url=match.source_url,
                provenance_status=match.provenance_status,
                relevance_explanation=match.relevance_explanation,
                snippet=match.snippet,
                summary_json=match.summary_json,
                effective_date=match.effective_date,
                published_date=match.published_date,
                decision_date=match.decision_date,
            )
            session.add(alert)
            session.flush()
            record_from_context(
                session,
                context,
                action="legal_update.watchlist_matched",
                target_type="legal_update_alert",
                target_id=alert.id,
                matter_id=watchlist.matter_id,
                metadata={
                    "watchlist_id_sha256": _hash_value(watchlist.id),
                    "source_record_key_sha256": _hash_value(match.source_record_key),
                    "source_record_id_sha256": _hash_value(match.source_record_id),
                    "update_type": match.update_type,
                    "source_key": match.source_key,
                    "has_summary": bool(match.summary_json),
                },
            )
            notification_intent_count += _enqueue_legal_update_notifications(
                session,
                context=context,
                watchlist=watchlist,
                alert=alert,
                match=match,
            )
            created_count += 1
        session.flush()
    records = [
        _match_record(match, company_id=context.company.id, watchlist_id=watchlist.id)
        for match in matches
    ]
    record_from_context(
        session,
        context,
        action="legal_update.watchlist_run",
        target_type="legal_update_watchlist",
        target_id=watchlist.id,
        matter_id=watchlist.matter_id,
        metadata=_watchlist_audit_metadata(
            watchlist,
            extra={
                "preview_only": payload.preview_only,
                "matched_count": len(matches),
                "created_count": created_count,
                "source_record_keys_sha256": _hash_value(
                    [match.source_record_key for match in matches]
                ),
                "notification_intent_count": notification_intent_count,
            },
        ),
    )
    session.commit()
    return LegalUpdateRunResponse(
        watchlist_id=watchlist.id,
        preview_only=payload.preview_only,
        matched_count=len(matches),
        created_count=created_count,
        matches=records,
    )


def list_legal_updates(
    session: Session,
    *,
    context: SessionContext,
    include_dismissed: bool = False,
    limit: int = 50,
) -> LegalUpdateListResponse:
    statement = (
        select(LegalUpdateAlert)
        .where(LegalUpdateAlert.company_id == context.company.id)
        .order_by(LegalUpdateAlert.created_at.desc())
        .limit(limit)
    )
    if not include_dismissed:
        statement = statement.where(LegalUpdateAlert.dismissed_at.is_(None))
    rows = list(session.scalars(statement))
    return LegalUpdateListResponse(updates=[_alert_record(row) for row in rows])


def update_legal_update(
    session: Session,
    *,
    context: SessionContext,
    update_id: str,
    payload: LegalUpdateActionRequest,
) -> LegalUpdateRecord:
    alert = session.scalar(
        select(LegalUpdateAlert).where(
            LegalUpdateAlert.id == update_id,
            LegalUpdateAlert.company_id == context.company.id,
        )
    )
    if alert is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal update not found.",
        )
    if alert.matter_id:
        _load_matter_with_access(session, context=context, matter_id=alert.matter_id)
    if payload.action == "read":
        alert.is_read = True
        alert.read_at = alert.read_at or _now()
    elif payload.action == "dismiss":
        alert.dismissed_at = alert.dismissed_at or _now()
        alert.is_read = True
        alert.read_at = alert.read_at or alert.dismissed_at
    else:  # pragma: no cover - schema validates actions.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported legal update action.",
        )
    session.add(alert)
    record_from_context(
        session,
        context,
        action=f"legal_update.alert_{payload.action}",
        target_type="legal_update_alert",
        target_id=alert.id,
        matter_id=alert.matter_id,
        metadata={
            "action": payload.action,
            "watchlist_id_sha256": _hash_value(alert.watchlist_id),
            "source_record_key_sha256": _hash_value(alert.source_record_key),
            "is_read": alert.is_read,
            "dismissed": alert.dismissed_at is not None,
        },
    )
    session.commit()
    return _alert_record(alert)


def preview_legal_update_digest(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 10,
) -> LegalUpdateDigestPreviewResponse:
    visible = list_legal_updates(
        session,
        context=context,
        include_dismissed=False,
        limit=limit,
    ).updates
    unread_count = session.scalar(
        select(func.count()).where(
            LegalUpdateAlert.company_id == context.company.id,
            LegalUpdateAlert.is_read.is_(False),
            LegalUpdateAlert.dismissed_at.is_(None),
        )
    )
    dismissed_count = session.scalar(
        select(func.count()).where(
            LegalUpdateAlert.company_id == context.company.id,
            LegalUpdateAlert.dismissed_at.is_not(None),
        )
    )
    return LegalUpdateDigestPreviewResponse(
        generated_at=_now(),
        unread_count=int(unread_count or 0),
        dismissed_count=int(dismissed_count or 0),
        updates=visible,
    )
