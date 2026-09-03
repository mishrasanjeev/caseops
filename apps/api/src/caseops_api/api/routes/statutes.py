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

from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import and_, func, select

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
    StatuteSourceVersion,
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
from caseops_api.schemas.source_actions import SourceActionRecord
from caseops_api.services.audit import record_from_context
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
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext
from caseops_api.services.source_actions import (
    inspect_source_target_action,
)
from caseops_api.services.statute_source_governance import (
    check_statute_section_link,
    create_statute_source_conflict,
    decide_statute_source_conflict,
    decide_statute_source_version,
    propose_statute_source_version,
)

router = APIRouter()
matter_scoped_router = APIRouter()
CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
# MOD-TS-017 Slice S4 — write actions on matter statute references
# require the matters:edit capability (same gate as other matter-
# scoped writes). Tenant scoping inside `_scoped_matter_or_404`
# further restricts which matter the user can touch.
MatterEditor = Annotated[SessionContext, Depends(require_capability("matters:edit"))]
LegalUpdateUser = Annotated[SessionContext, Depends(require_capability("authorities:search"))]
LegalUpdateAdmin = Annotated[SessionContext, Depends(require_capability("notifications:manage"))]


def _selectable_statute_section_sql():
    """One server-owned definition of an attachable statutory provision."""
    return and_(
        StatuteSection.is_active.is_(True),
        StatuteSection.section_text.is_not(None),
        StatuteSection.verification_status.in_(
            {"verified_official", "verified_licensed"}
        ),
        StatuteSection.source_sha256.is_not(None),
        StatuteSection.source_publisher.is_not(None),
        StatuteSection.issuing_body.is_not(None),
        StatuteSection.section_text_fetched_at.is_not(None),
        StatuteSection.exact_source_version.is_not(None),
        StatuteSection.source_locator_type == "section_deep_link",
        StatuteSection.link_health_status == "available",
    )


def _is_selectable_statute_section(section: StatuteSection) -> bool:
    return bool(
        section.is_active
        and section.section_text
        and section.verification_status in {"verified_official", "verified_licensed"}
        and section.source_sha256
        and section.source_publisher
        and section.issuing_body
        and section.section_text_fetched_at
        and section.exact_source_version
        and section.source_locator_type == "section_deep_link"
        and section.link_health_status == "available"
    )


class StatuteRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    short_name: str
    long_name: str
    enacted_year: int | None
    jurisdiction: str
    source_url: str | None
    issuing_body: str | None = None
    source_category: str = "consolidated_statute"
    source_status: str = "unverified"
    legal_status: str = "enacted"
    verification_status: str = "unverified"
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    source_retrieved_at: datetime | None = None
    source_sha256: str | None = None
    exact_source_version: str | None = None
    history_status: str = "current_text_only"
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
    catalog_section_count: int
    coverage_label: str


class StatuteListResponse(BaseModel):
    statutes: list[StatuteListItem]
    total_section_count: int
    total_catalog_section_count: int
    coverage_label: str = "Verified statutory text only"


class StatuteSectionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    statute_id: str
    section_number: str
    section_label: str | None
    section_text: str | None
    section_text_source: str | None = None
    editorial_notes: str | None = None
    case_annotations: str | None = None
    ai_explanation: str | None = None
    is_provisional: bool = False
    verification_status: str = "unverified"
    source_sha256: str | None = None
    source_publisher: str | None = None
    issuing_body: str | None = None
    source_category: str = "consolidated_statute"
    source_status: str = "unverified"
    legal_status: str = "enacted"
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    amendment_metadata_json: dict = Field(default_factory=dict)
    history_status: str = "current_text_only"
    exact_source_version: str | None = None
    source_locator_type: str = "unavailable"
    source_policy_json: dict = Field(default_factory=dict, exclude=True)
    link_health_status: str = "not_checked"
    link_last_checked_at: datetime | None = None
    link_last_error: str | None = None
    source_retrieved_at: datetime | None = None
    section_text_fetched_at: datetime | None = Field(default=None, exclude=True)
    source_version: int = 1
    verified_at: datetime | None = None
    quarantine_reason: str | None = None
    source_action: SourceActionRecord | None = None
    section_url: str | None
    parent_section_id: str | None
    ordinal: int

    @model_validator(mode="after")
    def fail_closed_source(self) -> StatuteSectionRecord:
        self.source_retrieved_at = self.source_retrieved_at or getattr(
            self, "section_text_fetched_at", None
        )
        complete_provenance = bool(
            self.source_sha256
            and self.source_publisher
            and self.issuing_body
            and self.source_retrieved_at
            and self.exact_source_version
            and self.source_locator_type == "section_deep_link"
            and self.link_health_status == "available"
        )
        authoritative = complete_provenance and self.verification_status in {
            "verified_official",
            "verified_licensed",
        }
        quarantined = self.verification_status in {"quarantined", "retired"}
        if not authoritative:
            self.section_text = None
        self.source_action = inspect_source_target_action(
            self.section_url if self.source_locator_type == "section_deep_link" else None,
            target_type="statute_section",
            target_id=self.id,
            verified=authoritative,
            quarantined=quarantined,
        )
        return self


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
    verification_status: str = "unverified"
    source_version: int = 1
    quarantine_reason: str | None = None
    source_locator_type: str = "unavailable"
    link_health_status: str = "not_checked"
    link_last_checked_at: datetime | None = None
    source_action: SourceActionRecord | None = None
    section_url: str | None
    parent_section_id: str | None
    ordinal: int

    @model_validator(mode="after")
    def source_contract(self) -> StatuteSectionListItem:
        self.source_action = inspect_source_target_action(
            self.section_url if self.source_locator_type == "section_deep_link" else None,
            target_type="statute_section",
            target_id=self.id,
            verified=(
                self.verification_status in {"verified_official", "verified_licensed"}
                and self.link_health_status == "available"
            ),
            quarantined=self.verification_status in {"quarantined", "retired"},
        )
        return self


class StatuteSectionCatalogListItem(BaseModel):
    """Safe catalog metadata, including rows that are not yet attachable."""

    id: str
    statute_id: str
    section_number: str
    section_label: str | None
    ordinal: int
    selection_state: Literal[
        "verified_selectable", "verification_pending", "quarantined", "retired"
    ]


class StatuteSectionsListResponse(BaseModel):
    statute: StatuteRecord
    sections: list[StatuteSectionListItem]
    catalog_sections: list[StatuteSectionCatalogListItem] = Field(default_factory=list)
    verified_section_count: int = 0
    catalog_section_count: int = 0
    coverage_label: str = "Verified statutory text only"


class StatuteSectionDetailResponse(BaseModel):
    statute: StatuteRecord
    section: StatuteSectionRecord
    parent_section: StatuteSectionRecord | None = None
    child_sections: list[StatuteSectionRecord] = Field(default_factory=list)


class StatuteVerificationAuditResponse(BaseModel):
    total: int
    verified: int
    unverified: int
    quarantined: int
    provisional: int
    ai_generated: int
    suspect_records: int


class StatuteVerificationRequest(BaseModel):
    status: Literal[
        "verified_official",
        "verified_licensed",
        "unverified",
        "quarantined",
        "retired",
    ]
    expected_source_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=500)


class StatuteSourceVersionProposalRequest(BaseModel):
    expected_source_version: int = Field(ge=1)
    candidate_text: str = Field(min_length=20)
    source_url: str = Field(min_length=8, max_length=500)
    source_publisher: str = Field(min_length=2, max_length=160)
    issuing_body: str = Field(min_length=2, max_length=160)
    source_category: str = "consolidated_statute"
    source_status: Literal["official", "licensed"]
    legal_status: Literal["enacted", "advisory", "draft", "repealed"] = "enacted"
    source_locator_type: Literal["section_deep_link"]
    exact_source_version: str = Field(min_length=1, max_length=160)
    retrieved_at: datetime
    publication_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    amendment_metadata: dict = Field(default_factory=dict)
    source_policy: dict = Field(default_factory=dict)


class StatuteSourceVersionDecisionRequest(BaseModel):
    expected_source_version: int = Field(ge=1)
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=5, max_length=500)


class StatuteSourceVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    section_id: str
    proposed_source_version: int
    candidate_text: str
    candidate_sha256: str
    source_url: str
    source_publisher: str
    issuing_body: str
    source_category: str
    source_status: str
    legal_status: str
    source_locator_type: str
    exact_source_version: str
    retrieved_at: datetime
    publication_date: date | None
    effective_from: date | None
    effective_to: date | None
    amendment_metadata_json: dict
    diff_unified: str
    status: str
    proposed_by_membership_id: str | None
    proposed_at: datetime
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    review_reason: str | None


class StatuteSourceVersionListResponse(BaseModel):
    versions: list[StatuteSourceVersionRecord]


class StatuteSourceConflictCreateRequest(BaseModel):
    expected_source_version: int = Field(ge=1)
    disputed_facts: dict
    source_versions: list[dict] = Field(min_length=2)
    authority_rank: dict
    affected_records: list[dict] = Field(default_factory=list)
    impact_scan: dict = Field(default_factory=dict)


class StatuteSourceConflictDecisionRequest(BaseModel):
    decision: str = Field(min_length=10, max_length=2_000)


class StatuteSourceConflictRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    section_id: str
    disputed_facts_json: dict
    source_versions_json: list
    authority_rank_json: dict
    affected_records_json: list
    impact_scan_json: dict
    status: str
    decision: str | None
    decision_by_membership_id: str | None
    decided_at: datetime | None
    created_by_membership_id: str | None
    created_at: datetime


class StatuteLinkHealthRecord(BaseModel):
    section_id: str
    source_version: int
    status: str
    checked_at: datetime
    error_class: str | None


class StatuteVerificationSectionListResponse(BaseModel):
    sections: list[StatuteSectionRecord]


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
            func.count(StatuteSection.id).label("catalog_section_count"),
            func.count(StatuteSection.id)
            .filter(_selectable_statute_section_sql())
            .label("verified_section_count"),
        )
        .outerjoin(
            StatuteSection,
            (StatuteSection.statute_id == Statute.id) & (StatuteSection.is_active.is_(True)),
        )
        .where(Statute.is_active.is_(True))
        .group_by(Statute.id)
        .order_by(Statute.short_name)
    ).all()
    items: list[StatuteListItem] = []
    total = 0
    for row in rows:
        statute: Statute = row[0]
        catalog_count = int(row[1] or 0)
        count = int(row[2] or 0)
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
                catalog_section_count=catalog_count,
                coverage_label=f"{count} verified of {catalog_count} catalogued sections",
            )
        )
    return StatuteListResponse(
        statutes=items,
        total_section_count=total,
        total_catalog_section_count=sum(item.catalog_section_count for item in items),
    )


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
        "Run or preview deterministic in-app legal update matches against existing records only."
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
    "/verification/audit",
    response_model=StatuteVerificationAuditResponse,
    summary="Audit statute source provenance without publishing replacement text.",
)
def audit_statute_verification(
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteVerificationAuditResponse:
    _ = context
    sections = list(session.scalars(select(StatuteSection)).all())
    suspect = 0
    for section in sections:
        body = section.section_text or ""
        if (
            section.section_text_source == "haiku_generated"
            or "\ufffd" in body
            or (body and len(body.strip()) < 20)
        ):
            suspect += 1
    return StatuteVerificationAuditResponse(
        total=len(sections),
        verified=sum(
            s.verification_status in {"verified_official", "verified_licensed"} for s in sections
        ),
        unverified=sum(s.verification_status == "unverified" for s in sections),
        quarantined=sum(s.verification_status == "quarantined" for s in sections),
        provisional=sum(bool(s.is_provisional) for s in sections),
        ai_generated=sum(s.section_text_source == "haiku_generated" for s in sections),
        suspect_records=suspect,
    )


@router.post(
    "/verification/sections/{section_id}",
    response_model=StatuteSectionRecord,
    summary="Apply an optimistic, audited curator decision to statute text.",
)
def verify_statute_section(
    section_id: str,
    payload: StatuteVerificationRequest,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSectionRecord:
    section = session.scalar(
        select(StatuteSection).where(StatuteSection.id == section_id).with_for_update()
    )
    if section is None:
        raise HTTPException(status_code=404, detail="Statute section not found.")
    if section.source_version != payload.expected_source_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Statute source version changed; reload before reviewing.",
        )
    if payload.status in {"verified_official", "verified_licensed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Direct verification is disabled. Propose an immutable source version "
                "and obtain approval from a different legal reviewer."
            ),
        )
    elif payload.status in {"quarantined", "retired"}:
        if not (payload.reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A quarantine reason is required.",
            )
        section.verified_at = None
        section.verified_by_membership_id = None
        section.quarantined_at = datetime.now(UTC)
        section.quarantine_reason = payload.reason.strip()
        section.is_provisional = True
    else:
        section.verified_at = None
        section.verified_by_membership_id = None
        section.quarantined_at = None
        section.quarantine_reason = payload.reason.strip() if payload.reason else None
        section.is_provisional = True
    previous_status = section.verification_status
    section.verification_status = payload.status
    section.source_version += 1
    record_from_context(
        session,
        context,
        action="statute_section.verification_changed",
        target_type="statute_section",
        target_id=section.id,
        metadata={
            "previous_verification_status": previous_status,
            "verification_status": payload.status,
            "source_version": section.source_version,
            "has_source_hash": bool(section.source_sha256),
            "reason_sha256": (
                sha256((payload.reason or "").encode("utf-8")).hexdigest()
                if payload.reason
                else None
            ),
        },
    )
    session.commit()
    session.refresh(section)
    return StatuteSectionRecord.model_validate(section)


@router.post(
    "/verification/sections/{section_id}/source-versions",
    response_model=StatuteSourceVersionRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Propose an immutable statute-text source version for independent review.",
)
def post_statute_source_version(
    section_id: str,
    payload: StatuteSourceVersionProposalRequest,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSourceVersionRecord:
    row = propose_statute_source_version(
        session,
        context=context,
        section_id=section_id,
        **payload.model_dump(),
    )
    return StatuteSourceVersionRecord.model_validate(row)


@router.get(
    "/verification/sections",
    response_model=StatuteVerificationSectionListResponse,
    summary="Search the complete curator corpus, including quarantined records.",
)
def list_statute_verification_sections(
    context: LegalUpdateAdmin,
    session: DbSession,
    statute_id: str | None = None,
    verification_status: Literal[
        "unverified",
        "verified_official",
        "verified_licensed",
        "quarantined",
        "retired",
    ]
    | None = None,
    limit: int = 100,
) -> StatuteVerificationSectionListResponse:
    _ = context
    stmt = select(StatuteSection).order_by(
        StatuteSection.statute_id,
        StatuteSection.ordinal,
        StatuteSection.section_number,
    )
    if statute_id:
        stmt = stmt.where(StatuteSection.statute_id == statute_id)
    if verification_status:
        stmt = stmt.where(StatuteSection.verification_status == verification_status)
    rows = list(session.scalars(stmt.limit(max(1, min(limit, 500)))).all())
    return StatuteVerificationSectionListResponse(
        sections=[StatuteSectionRecord.model_validate(row) for row in rows]
    )
@router.get(
    "/verification/sections/{section_id}/source-versions",
    response_model=StatuteSourceVersionListResponse,
    summary="List immutable source proposals and their independent-review decisions.",
)
def get_statute_source_versions(
    section_id: str,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSourceVersionListResponse:
    _ = context
    if session.get(StatuteSection, section_id) is None:
        raise HTTPException(status_code=404, detail="Statute section not found.")
    rows = list(
        session.scalars(
            select(StatuteSourceVersion)
            .where(StatuteSourceVersion.section_id == section_id)
            .order_by(StatuteSourceVersion.proposed_at.desc())
        ).all()
    )
    return StatuteSourceVersionListResponse(
        versions=[StatuteSourceVersionRecord.model_validate(row) for row in rows]
    )


@router.post(
    "/verification/source-versions/{proposal_id}/decision",
    response_model=StatuteSourceVersionRecord,
    summary="Approve or reject a proposal as a distinct legal reviewer.",
)
def post_statute_source_version_decision(
    proposal_id: str,
    payload: StatuteSourceVersionDecisionRequest,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSourceVersionRecord:
    row = decide_statute_source_version(
        session,
        context=context,
        proposal_id=proposal_id,
        **payload.model_dump(),
    )
    return StatuteSourceVersionRecord.model_validate(row)


@router.post(
    "/verification/sections/{section_id}/link-check",
    response_model=StatuteLinkHealthRecord,
    summary="Check and persist typed health for an approved section-level source link.",
)
def post_statute_section_link_check(
    section_id: str,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteLinkHealthRecord:
    section = check_statute_section_link(
        session, context=context, section_id=section_id
    )
    return StatuteLinkHealthRecord(
        section_id=section.id,
        source_version=section.source_version,
        status=section.link_health_status,
        checked_at=section.link_last_checked_at,
        error_class=section.link_last_error,
    )


@router.post(
    "/verification/sections/{section_id}/conflicts",
    response_model=StatuteSourceConflictRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Open a source conflict and immediately quarantine affected statutory text.",
)
def post_statute_source_conflict(
    section_id: str,
    payload: StatuteSourceConflictCreateRequest,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSourceConflictRecord:
    row = create_statute_source_conflict(
        session,
        context=context,
        section_id=section_id,
        **payload.model_dump(),
    )
    return StatuteSourceConflictRecord.model_validate(row)


@router.post(
    "/verification/conflicts/{conflict_id}/decision",
    response_model=StatuteSourceConflictRecord,
    summary="Record an independent legal decision while keeping text quarantined.",
)
def post_statute_source_conflict_decision(
    conflict_id: str,
    payload: StatuteSourceConflictDecisionRequest,
    context: LegalUpdateAdmin,
    session: DbSession,
) -> StatuteSourceConflictRecord:
    row = decide_statute_source_conflict(
        session,
        context=context,
        conflict_id=conflict_id,
        decision=payload.decision,
    )
    return StatuteSourceConflictRecord.model_validate(row)


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
    catalog_sections = list(
        session.scalars(
            select(StatuteSection)
            .where(
                StatuteSection.statute_id == statute_id,
                StatuteSection.is_active.is_(True),
            )
            .order_by(StatuteSection.ordinal, StatuteSection.section_number)
        ).all()
    )
    sections = [row for row in catalog_sections if _is_selectable_statute_section(row)]

    def catalog_item(row: StatuteSection) -> StatuteSectionCatalogListItem:
        if _is_selectable_statute_section(row):
            selection_state = "verified_selectable"
        elif row.verification_status == "quarantined":
            selection_state = "quarantined"
        elif row.verification_status == "retired":
            selection_state = "retired"
        else:
            selection_state = "verification_pending"
        return StatuteSectionCatalogListItem(
            id=row.id,
            statute_id=row.statute_id,
            section_number=row.section_number,
            section_label=row.section_label,
            ordinal=row.ordinal,
            selection_state=selection_state,
        )

    return StatuteSectionsListResponse(
        statute=StatuteRecord.model_validate(statute),
        sections=[StatuteSectionListItem.model_validate(s) for s in sections],
        catalog_sections=[catalog_item(s) for s in catalog_sections],
        verified_section_count=len(sections),
        catalog_section_count=len(catalog_sections),
        coverage_label=(
            f"{len(sections)} verified of {len(catalog_sections)} catalogued sections"
        ),
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
            detail=(f"Section {section_number!r} not found in {statute.short_name}."),
        )
    parent = None
    if section.parent_section_id:
        parent = session.scalar(
            select(StatuteSection).where(StatuteSection.id == section.parent_section_id)
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
        parent_section=(StatuteSectionRecord.model_validate(parent) if parent else None),
        child_sections=[StatuteSectionRecord.model_validate(c) for c in children],
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
    session,
    *,
    matter_id: str,
    context: SessionContext,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(Matter.id == matter_id).where(Matter.company_id == context.company.id)
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
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
        session,
        matter_id=matter_id,
        context=context,
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
        references=[_serialise_matter_ref(ref, section, statute) for ref, section, statute in rows],
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
        session,
        matter_id=matter_id,
        context=context,
    )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="add a statute reference to this matter",
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
    statute = session.scalar(select(Statute).where(Statute.id == section.statute_id))
    if statute is None or not statute.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parent statute for this section is missing.",
        )
    if not _is_selectable_statute_section(section):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "statute_section_not_verified",
                "message": (
                    "This provision is catalogued but does not yet have complete "
                    "source-verified text, lineage, and an available section-level link. "
                    "It cannot be attached to a Matter."
                ),
            },
        )

    relevance = (payload.relevance or "cited").strip().lower()
    if relevance not in {"cited", "opposing", "context"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("relevance must be one of 'cited' | 'opposing' | 'context'."),
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
        session,
        matter_id=matter_id,
        context=context,
    )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="remove a statute reference from this matter",
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
