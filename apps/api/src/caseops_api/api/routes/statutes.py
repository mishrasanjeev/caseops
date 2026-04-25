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

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from caseops_api.api.dependencies import DbSession, get_current_context
from caseops_api.db.models import Statute, StatuteSection
from caseops_api.services.identity import SessionContext

router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]


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
    section_url: str | None
    parent_section_id: str | None
    ordinal: int


class StatuteSectionsListResponse(BaseModel):
    statute: StatuteRecord
    sections: list[StatuteSectionRecord]


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
        sections=[StatuteSectionRecord.model_validate(s) for s in sections],
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
