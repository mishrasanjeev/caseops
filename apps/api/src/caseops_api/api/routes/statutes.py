"""Statute + Bare Acts read API — Slice S2 (MOD-TS-017).

Per docs/PRD_STATUTE_MODEL_2026-04-25.md §3 Slice S2. v1 surface is
read-only; matter reference + drafting prompt extension lands in
Slice S4. v1 endpoints:

- GET /api/statutes — list every Act in the catalog
- GET /api/statutes/{statute_id} — Act detail + section count
- GET /api/statutes/{statute_id}/sections — sections under an Act
- GET /api/statutes/{statute_id}/sections/{section_number} — one
  section detail (text + url + parent + cross-refs)

All endpoints are auth-gated (catalog is global; no per-tenant
scoping). 404 on unknown id / section_number.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.db.models import (
    Matter,
    MatterStatuteReference,
    Statute,
    StatuteSection,
)
from caseops_api.schemas.legal_updates import (
    LegalUpdateActionRequest,
    LegalUpdateDigestPreviewResponse,
    LegalUpdateListResponse,
    LegalUpdateRecord,
    LegalUpdateRunRequest,
    LegalUpdateRunResponse,
    LegalUpdateSourceRecordListResponse,
    LegalUpdateSourceRunRecord,
    LegalUpdateWatchlistCreateRequest,
    LegalUpdateWatchlistListResponse,
    LegalUpdateWatchlistRecord,
    LegalUpdateWatchlistUpdateRequest,
    StatuteAmendmentHistoryResponse,
)
from caseops_api.services.legal_update_sources import (
    list_source_records,
    list_statute_amendment_history,
    source_run_record,
    sync_source,
)
from caseops_api.services.legal_updates import (
    create_legal_update_watchlist,
    list_legal_update_watchlists,
    list_legal_updates,
    preview_legal_update_digest,
    run_legal_update_watchlist,
    update_legal_update,
    update_legal_update_watchlist,
)
from caseops_api.services.session_context import SessionContext

router = APIRouter()
matter_scoped_router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
# MOD-TS-017 Slice S4 — write actions on matter statute references
# require the matters:edit capability (same gate as other matter-
# scoped writes). Tenant scoping inside `_scoped_matter_or_404`
# further restricts which matter the user can touch.
MatterEditor = Annotated[
    SessionContext, Depends(require_capability("matters:edit"))
]
LegalUpdateUser = Annotated[
    SessionContext, Depends(require_capability("authorities:search"))
]
LegalUpdateAdmin = Annotated[
    SessionContext, Depends(require_capability("notifications:manage"))
]


class StatuteRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    short_name: str
    long_name: str
    enacted_year: int | None
    jurisdiction: str
    source_url: str | None
    is_active: bool


class StatuteListItem(BaseModel):
    """Statute with a section_count denormalised for the list view."""

    id: str
    short_name: str
    long_name: str
    enacted_year: int | None
    jurisdiction: str
    source_url: str | None
    section_count: int


class StatuteListResponse(BaseModel):
    statutes: list[StatuteListItem]
    total_section_count: int


class StatuteSectionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    statute_id: str
    section_number: str
    section_label: str | None
    section_text: str | None
    section_text_source: str | None = None
    is_provisional: bool = False
    section_url: str | None
    parent_section_id: str | None
    ordinal: int


class StatuteSectionListItem(BaseModel):
    """Lighter section row for the list endpoint.

    Drops `section_text` (the full body) to keep the list response
    fast — IPC with 511 sections × ~500 chars/section was a 250KB+
    JSON payload that took 30-90s on a cold cache and timed out
    prod-Playwright tests. Callers who need the body fetch the
    section-detail endpoint, which keeps the full StatuteSectionRecord.
    """
    model_config = ConfigDict(from_attributes=True)

    id: str
    statute_id: str
    section_number: str
    section_label: str | None
    section_text_source: str | None = None
    is_provisional: bool = False
    section_url: str | None
    parent_section_id: str | None
    ordinal: int


class StatuteSectionsListResponse(BaseModel):
    statute: StatuteRecord
    sections: list[StatuteSectionListItem]


class StatuteSectionDetailResponse(BaseModel):
    statute: StatuteRecord
    section: StatuteSectionRecord
    parent_section: StatuteSectionRecord | None = None
    child_sections: list[StatuteSectionRecord] = Field(default_factory=list)


@router.get(
    "/",
    response_model=StatuteListResponse,
    summary=(
        "List every Act in the catalog with a denormalised "
        "section_count. Powers /app/statutes index."
    ),
)
def list_statutes(
    context: CurrentContext,
    session: DbSession,
) -> StatuteListResponse:
    _ = context  # auth-gated, no per-tenant scoping (catalog is global)
    rows = session.execute(
        select(
            Statute,
            func.count(StatuteSection.id).label("section_count"),
        )
        .outerjoin(
            StatuteSection,
            (StatuteSection.statute_id == Statute.id)
            & (StatuteSection.is_active.is_(True)),
        )
        .where(Statute.is_active.is_(True))
        .group_by(Statute.id)
        .order_by(Statute.short_name)
    ).all()
    items: list[StatuteListItem] = []
    total = 0
    for row in rows:
        statute: Statute = row[0]
        count: int = int(row[1] or 0)
        total += count
        items.append(
            StatuteListItem(
                id=statute.id,
                short_name=statute.short_name,
                long_name=statute.long_name,
                enacted_year=statute.enacted_year,
                jurisdiction=statute.jurisdiction,
                source_url=statute.source_url,
                section_count=count,
            )
        )
    return StatuteListResponse(statutes=items, total_section_count=total)


@router.get(
    "/legal-updates/watchlists",
    response_model=LegalUpdateWatchlistListResponse,
    summary="List this tenant's legal update watchlists.",
)
def get_legal_update_watchlists(
    context: LegalUpdateUser,
    session: DbSession,
) -> LegalUpdateWatchlistListResponse:
    return list_legal_update_watchlists(session, context=context)


@router.post(
    "/legal-updates/watchlists",
    response_model=LegalUpdateWatchlistRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a bounded in-app legal update watchlist.",
)
def post_legal_update_watchlist(
    payload: LegalUpdateWatchlistCreateRequest,
    context: LegalUpdateUser,
    session: DbSession,
) -> LegalUpdateWatchlistRecord:
    return create_legal_update_watchlist(session, context=context, payload=payload)


@router.patch(
    "/legal-updates/watchlists/{watchlist_id}",
    response_model=LegalUpdateWatchlistRecord,
    summary="Update or archive a legal update watchlist.",
)
def patch_legal_update_watchlist(
    watchlist_id: str,
    payload: LegalUpdateWatchlistUpdateRequest,
    context: LegalUpdateUser,
    session: DbSession,
) -> LegalUpdateWatchlistRecord:
    return update_legal_update_watchlist(
        session,
        context=context,
        watchlist_id=watchlist_id,
        payload=payload,
    )


@router.post(
    "/legal-updates/watchlists/{watchlist_id}/run",
    response_model=LegalUpdateRunResponse,
    summary=(
        "Run or preview deterministic in-app legal update matches "
        "against existing records only."
    ),
)
def post_legal_update_watchlist_run(
    watchlist_id: str,
    payload: LegalUpdateRunRequest,
    context: LegalUpdateUser,
    session: DbSession,
) -> LegalUpdateRunResponse:
    return run_legal_update_watchlist(
        session,
        context=context,
        watchlist_id=watchlist_id,
        payload=payload,
    )


@router.get(
    "/legal-updates",
    response_model=LegalUpdateListResponse,
    summary="List this tenant's in-app legal update alerts.",
)
def get_legal_updates(
    context: LegalUpdateUser,
    session: DbSession,
    include_dismissed: bool = False,
    limit: int = 50,
) -> LegalUpdateListResponse:
    safe_limit = max(1, min(limit, 100))
    return list_legal_updates(
        session,
        context=context,
        include_dismissed=include_dismissed,
        limit=safe_limit,
    )


@router.get(
    "/legal-updates/digest-preview",
    response_model=LegalUpdateDigestPreviewResponse,
    summary="Preview an in-app-only legal update digest.",
)
def get_legal_update_digest_preview(
    context: LegalUpdateUser,
    session: DbSession,
    limit: int = 10,
) -> LegalUpdateDigestPreviewResponse:
    safe_limit = max(1, min(limit, 50))
    return preview_legal_update_digest(session, context=context, limit=safe_limit)


@router.patch(
    "/legal-updates/{update_id}",
    response_model=LegalUpdateRecord,
    summary="Mark an in-app legal update alert read or dismissed.",
)
def patch_legal_update(
    update_id: str,
    payload: LegalUpdateActionRequest,
    context: LegalUpdateUser,
    session: DbSession,
) -> LegalUpdateRecord:
    return update_legal_update(
        session,
        context=context,
        update_id=update_id,
        payload=payload,
    )


@router.post(
    "/legal-updates/sources/{source_key}/sync",
    response_model=LegalUpdateSourceRunRecord,
    summary="Manually sync a configured legal update source.",
)
def post_legal_update_source_sync(
    source_key: str,
    context: LegalUpdateAdmin,
    session: DbSession,
    limit: int = 100,
) -> LegalUpdateSourceRunRecord:
    run = sync_source(
        session,
        source_key=source_key,
        limit=max(1, min(limit, 500)),
        context=context,
        run_watchlists=True,
    )
    session.commit()
    return source_run_record(run)


@router.get(
    "/legal-updates/source-records",
    response_model=LegalUpdateSourceRecordListResponse,
    summary="List normalized source-backed legal update records.",
)
def get_legal_update_source_records(
    context: LegalUpdateUser,
    session: DbSession,
    source_key: str | None = None,
    update_type: str | None = None,
    statute_id: str | None = None,
    summary_status: str | None = None,
    since_date: date | None = None,
    until_date: date | None = None,
    limit: int = 50,
) -> LegalUpdateSourceRecordListResponse:
    _ = context
    return list_source_records(
        session,
        source_key=source_key,
        update_type=update_type,
        statute_id=statute_id,
        summary_status=summary_status,
        since_date=since_date,
        until_date=until_date,
        limit=limit,
    )


@router.get(
    "/{statute_id}/amendment-history",
    response_model=StatuteAmendmentHistoryResponse,
    summary="List source-backed amendment and change events for an Act.",
)
def get_statute_amendment_history(
    statute_id: str,
    context: CurrentContext,
    session: DbSession,
    limit: int = 50,
) -> StatuteAmendmentHistoryResponse:
    _ = context
    statute = session.scalar(select(Statute).where(Statute.id == statute_id))
    if statute is None or not statute.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statute {statute_id!r} not found.",
        )
    return list_statute_amendment_history(
        session,
        statute_id=statute_id,
        limit=limit,
    )


@router.get(
    "/{statute_id}",
    response_model=StatuteRecord,
    summary="One Act's metadata (without the full section list).",
)
def get_statute(
    statute_id: str,
    context: CurrentContext,
    session: DbSession,
) -> StatuteRecord:
    _ = context
    statute = session.scalar(select(Statute).where(Statute.id == statute_id))
    if statute is None or not statute.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statute {statute_id!r} not found.",
        )
    return StatuteRecord.model_validate(statute)


@router.get(
    "/{statute_id}/sections",
    response_model=StatuteSectionsListResponse,
    summary="Sections under an Act, ordered by ordinal.",
)
def list_statute_sections(
    statute_id: str,
    context: CurrentContext,
    session: DbSession,
) -> StatuteSectionsListResponse:
    _ = context
    statute = session.scalar(select(Statute).where(Statute.id == statute_id))
    if statute is None or not statute.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statute {statute_id!r} not found.",
        )
    sections = list(
        session.scalars(
            select(StatuteSection)
            .where(
                StatuteSection.statute_id == statute_id,
                StatuteSection.is_active.is_(True),
            )
            .order_by(StatuteSection.ordinal, StatuteSection.section_number)
        ).all()
    )
    return StatuteSectionsListResponse(
        statute=StatuteRecord.model_validate(statute),
        sections=[StatuteSectionListItem.model_validate(s) for s in sections],
    )


@router.get(
    "/{statute_id}/sections/{section_number:path}",
    response_model=StatuteSectionDetailResponse,
    summary=(
        "One section detail. Includes parent + child rows when "
        "section is hierarchical (e.g. Section 173(8))."
    ),
)
def get_statute_section(
    statute_id: str,
    section_number: str,
    context: CurrentContext,
    session: DbSession,
) -> StatuteSectionDetailResponse:
    _ = context
    statute = session.scalar(select(Statute).where(Statute.id == statute_id))
    if statute is None or not statute.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statute {statute_id!r} not found.",
        )
    section = session.scalar(
        select(StatuteSection).where(
            StatuteSection.statute_id == statute_id,
            StatuteSection.section_number == section_number,
            StatuteSection.is_active.is_(True),
        )
    )
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Section {section_number!r} not found in {statute.short_name}."
            ),
        )
    parent = None
    if section.parent_section_id:
        parent = session.scalar(
            select(StatuteSection).where(
                StatuteSection.id == section.parent_section_id
            )
        )
    children = list(
        session.scalars(
            select(StatuteSection)
            .where(
                StatuteSection.parent_section_id == section.id,
                StatuteSection.is_active.is_(True),
            )
            .order_by(StatuteSection.ordinal, StatuteSection.section_number)
        ).all()
    )
    return StatuteSectionDetailResponse(
        statute=StatuteRecord.model_validate(statute),
        section=StatuteSectionRecord.model_validate(section),
        parent_section=(
            StatuteSectionRecord.model_validate(parent) if parent else None
        ),
        child_sections=[
            StatuteSectionRecord.model_validate(c) for c in children
        ],
    )


# ---------------------------------------------------------------------
# Slice S4 (MOD-TS-017, 2026-04-25): matter statute references.
#
# Mounted under /api/matters/{matter_id}/... so the URL shape stays
# consistent with the rest of the matter cockpit. Tenancy enforced
# via Matter.company_id == context.company.id (foreign matter → 404).
# ---------------------------------------------------------------------


class MatterStatuteReferenceRecord(BaseModel):
    id: str
    matter_id: str
    section_id: str
    statute_id: str
    statute_short_name: str
    section_number: str
    section_label: str | None
    section_url: str | None
    relevance: str  # 'cited' | 'opposing' | 'context'
    notes: str | None
    created_at: str


class MatterStatuteReferenceListResponse(BaseModel):
    matter_id: str
    references: list[MatterStatuteReferenceRecord]


class MatterStatuteReferenceCreateRequest(BaseModel):
    section_id: str
    relevance: str = "cited"
    notes: str | None = None


def _serialise_matter_ref(
    ref: MatterStatuteReference,
    section: StatuteSection,
    statute: Statute,
) -> MatterStatuteReferenceRecord:
    return MatterStatuteReferenceRecord(
        id=ref.id,
        matter_id=ref.matter_id,
        section_id=ref.section_id,
        statute_id=statute.id,
        statute_short_name=statute.short_name,
        section_number=section.section_number,
        section_label=section.section_label,
        section_url=section.section_url,
        relevance=ref.relevance,
        notes=ref.notes,
        created_at=ref.created_at.isoformat(),
    )


def _scoped_matter_or_404(
    session, *, matter_id: str, company_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter)
        .where(Matter.id == matter_id)
        .where(Matter.company_id == company_id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    return matter


@matter_scoped_router.get(
    "/{matter_id}/statute-references",
    response_model=MatterStatuteReferenceListResponse,
    summary=(
        "List statute references attached to a matter. Joins to "
        "StatuteSection + Statute so the UI can render section "
        "metadata without extra round-trips."
    ),
)
def list_matter_statute_references(
    matter_id: str,
    context: CurrentContext,
    session: DbSession,
) -> MatterStatuteReferenceListResponse:
    matter = _scoped_matter_or_404(
        session, matter_id=matter_id, company_id=context.company.id,
    )
    rows = list(
        session.execute(
            select(MatterStatuteReference, StatuteSection, Statute)
            .join(
                StatuteSection,
                StatuteSection.id == MatterStatuteReference.section_id,
            )
            .join(Statute, Statute.id == StatuteSection.statute_id)
            .where(MatterStatuteReference.matter_id == matter.id)
            .order_by(
                Statute.short_name,
                StatuteSection.ordinal,
                StatuteSection.section_number,
            )
        ).all()
    )
    return MatterStatuteReferenceListResponse(
        matter_id=matter.id,
        references=[
            _serialise_matter_ref(ref, section, statute)
            for ref, section, statute in rows
        ],
    )


@matter_scoped_router.post(
    "/{matter_id}/statute-references",
    response_model=MatterStatuteReferenceRecord,
    status_code=status.HTTP_201_CREATED,
    summary=(
        "Attach a statute section to a matter. Idempotent on the "
        "uq_matter_statute_references_unique constraint — re-posting "
        "the same (section_id, relevance) tuple returns the existing "
        "row instead of erroring."
    ),
)
def add_matter_statute_reference(
    matter_id: str,
    payload: MatterStatuteReferenceCreateRequest,
    context: MatterEditor,
    session: DbSession,
) -> MatterStatuteReferenceRecord:
    matter = _scoped_matter_or_404(
        session, matter_id=matter_id, company_id=context.company.id,
    )
    section = session.scalar(
        select(StatuteSection).where(
            StatuteSection.id == payload.section_id,
            StatuteSection.is_active.is_(True),
        )
    )
    if section is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Statute section {payload.section_id!r} not found.",
        )
    statute = session.scalar(
        select(Statute).where(Statute.id == section.statute_id)
    )
    if statute is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent statute for this section is missing.",
        )

    relevance = (payload.relevance or "cited").strip().lower()
    if relevance not in {"cited", "opposing", "context"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "relevance must be one of 'cited' | 'opposing' | 'context'."
            ),
        )
    existing = session.scalar(
        select(MatterStatuteReference).where(
            MatterStatuteReference.matter_id == matter.id,
            MatterStatuteReference.section_id == section.id,
            MatterStatuteReference.relevance == relevance,
        )
    )
    if existing is not None:
        return _serialise_matter_ref(existing, section, statute)

    ref = MatterStatuteReference(
        matter_id=matter.id,
        section_id=section.id,
        relevance=relevance,
        added_by_membership_id=context.membership.id,
        notes=payload.notes,
    )
    session.add(ref)
    session.commit()
    session.refresh(ref)
    return _serialise_matter_ref(ref, section, statute)


@matter_scoped_router.delete(
    "/{matter_id}/statute-references/{reference_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a statute reference from a matter.",
)
def delete_matter_statute_reference(
    matter_id: str,
    reference_id: str,
    context: MatterEditor,
    session: DbSession,
):
    matter = _scoped_matter_or_404(
        session, matter_id=matter_id, company_id=context.company.id,
    )
    ref = session.scalar(
        select(MatterStatuteReference).where(
            MatterStatuteReference.id == reference_id,
            MatterStatuteReference.matter_id == matter.id,
        )
    )
    if ref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Statute reference not found on this matter.",
        )
    session.delete(ref)
    session.commit()
    from fastapi import Response
    return Response(status_code=status.HTTP_204_NO_CONTENT)
