from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

LegalUpdateTypeLiteral = Literal[
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
LegalUpdateActionLiteral = Literal["read", "dismiss"]
LegalUpdateSummaryStatusLiteral = Literal["pending", "completed", "failed", "not_required"]
LegalUpdateSourceRunStatusLiteral = Literal["completed", "failed", "partial"]
StatuteChangeTypeLiteral = Literal["new_act", "amendment", "repeal", "notification", "unknown"]

DEFAULT_LEGAL_UPDATE_TYPES: tuple[LegalUpdateTypeLiteral, ...] = (
    "act",
    "amendment",
    "ordinance",
    "notification",
    "repeal",
    "regulation",
    "circular",
    "order",
    "practice_direction",
)


class LegalUpdateSummaryRecord(BaseModel):
    plain_english_summary: str
    affected_acts: list[str] = Field(default_factory=list)
    affected_sections: list[str] = Field(default_factory=list)
    change_kind: str = "unknown"
    practical_legal_impact: str
    suggested_lawyer_review_actions: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    source_url: str
    provenance_status: str
    review_framing: str = "Source-backed summary for lawyer review."


class LegalUpdateWatchlistBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    statute_id: str | None = Field(default=None, min_length=1, max_length=64)
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=120)
    statute_terms: list[str] = Field(default_factory=list, max_length=8)
    source_key: str | None = Field(default=None, min_length=2, max_length=120)
    source_category: str | None = Field(default=None, min_length=2, max_length=80)
    update_types: list[LegalUpdateTypeLiteral] = Field(
        default_factory=lambda: list(DEFAULT_LEGAL_UPDATE_TYPES),
        max_length=len(DEFAULT_LEGAL_UPDATE_TYPES),
    )
    since_date: date | None = None
    until_date: date | None = None
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    contract_id: str | None = Field(default=None, min_length=1, max_length=36)

    @field_validator(
        "name",
        "practice_area",
        "statute_id",
        "jurisdiction",
        "source_key",
        "source_category",
        "matter_id",
        "contract_id",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("statute_terms", mode="before")
    @classmethod
    def _split_terms(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


class LegalUpdateWatchlistCreateRequest(LegalUpdateWatchlistBase):
    pass


class LegalUpdateWatchlistUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    statute_id: str | None = Field(default=None, min_length=1, max_length=64)
    jurisdiction: str | None = Field(default=None, min_length=2, max_length=120)
    statute_terms: list[str] | None = Field(default=None, max_length=8)
    source_key: str | None = Field(default=None, min_length=2, max_length=120)
    source_category: str | None = Field(default=None, min_length=2, max_length=80)
    update_types: list[LegalUpdateTypeLiteral] | None = Field(
        default=None,
        max_length=len(DEFAULT_LEGAL_UPDATE_TYPES),
    )
    since_date: date | None = None
    until_date: date | None = None
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    contract_id: str | None = Field(default=None, min_length=1, max_length=36)
    is_archived: bool | None = None

    @field_validator(
        "name",
        "practice_area",
        "statute_id",
        "jurisdiction",
        "source_key",
        "source_category",
        "matter_id",
        "contract_id",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("statute_terms", mode="before")
    @classmethod
    def _split_terms(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


class LegalUpdateWatchlistRecord(BaseModel):
    id: str
    company_id: str
    name: str
    practice_area: str | None
    statute_id: str | None
    jurisdiction: str | None
    statute_terms: list[str]
    source_key: str | None
    source_category: str | None
    update_types: list[LegalUpdateTypeLiteral]
    since_date: date | None
    until_date: date | None
    matter_id: str | None
    contract_id: str | None
    is_archived: bool
    created_by_membership_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class LegalUpdateWatchlistListResponse(BaseModel):
    watchlists: list[LegalUpdateWatchlistRecord]


class LegalUpdateRecord(BaseModel):
    id: str
    company_id: str
    watchlist_id: str
    source_record_id: str | None = None
    update_type: LegalUpdateTypeLiteral
    title: str
    statute_id: str | None
    statute_section_id: str | None
    authority_document_id: str | None
    matter_id: str | None
    contract_id: str | None
    statute_name: str | None
    section_number: str | None
    jurisdiction: str | None
    source_key: str
    source_category: str
    source_url: str | None
    provenance_status: str
    relevance_explanation: str
    effective_date: date | None
    published_date: date | None
    decision_date: date | None
    snippet: str | None = Field(default=None, max_length=280)
    summary: LegalUpdateSummaryRecord | None = None
    is_read: bool
    read_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime


class LegalUpdateListResponse(BaseModel):
    updates: list[LegalUpdateRecord]


class LegalUpdateRunRequest(BaseModel):
    preview_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class LegalUpdateRunResponse(BaseModel):
    watchlist_id: str
    preview_only: bool
    matched_count: int
    created_count: int
    matches: list[LegalUpdateRecord]
    delivery_status: Literal["in_app_only"] = "in_app_only"


class LegalUpdateActionRequest(BaseModel):
    action: LegalUpdateActionLiteral


class LegalUpdateDigestPreviewResponse(BaseModel):
    generated_at: datetime
    unread_count: int
    dismissed_count: int
    updates: list[LegalUpdateRecord]
    delivery_status: Literal["in_app_only"] = "in_app_only"
    delivery_note: str = (
        "In-app preview only. External legal update delivery requires "
        "provider-specific approval."
    )


class LegalUpdateSourceRunRecord(BaseModel):
    id: str
    source_key: str
    status: LegalUpdateSourceRunStatusLiteral
    started_at: datetime
    completed_at: datetime | None
    fetched_count: int
    created_count: int
    changed_count: int
    error_message: str | None
    metadata: dict[str, object] = Field(default_factory=dict)


class LegalUpdateSourceRecordRecord(BaseModel):
    id: str
    source_key: str
    source_record_key: str
    update_type: LegalUpdateTypeLiteral
    title: str
    normalized_title: str
    source_url: str
    source_document_url: str | None
    published_date: date | None
    effective_date: date | None
    act_year: int | None
    statute_id: str | None
    statute_section_ids: list[str] = Field(default_factory=list)
    sections_changed: list[str] = Field(default_factory=list)
    source_category: str | None
    provenance_status: str
    content_hash: str
    summary: LegalUpdateSummaryRecord | None
    summary_status: LegalUpdateSummaryStatusLiteral
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class LegalUpdateSourceRecordListResponse(BaseModel):
    records: list[LegalUpdateSourceRecordRecord]


class StatuteChangeEventRecord(BaseModel):
    id: str
    statute_id: str
    source_record_id: str
    change_type: StatuteChangeTypeLiteral
    title: str
    sections_changed: list[str] = Field(default_factory=list)
    summary: str | None
    comparison: dict[str, object] = Field(default_factory=dict)
    published_date: date | None
    effective_date: date | None
    source_url: str
    created_at: datetime


class StatuteAmendmentHistoryResponse(BaseModel):
    statute_id: str
    events: list[StatuteChangeEventRecord]
