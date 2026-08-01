from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from caseops_api.schemas.source_actions import SourceActionRecord

AuthorityForumLevelLiteral = Literal["high_court", "supreme_court"]
AuthorityDocumentTypeLiteral = Literal["judgment", "order", "practice_direction", "notice"]
AuthoritySearchModeLiteral = Literal["keyword", "contextual"]
AuthoritySearchOutcomeLiteral = Literal[
    "results_found",
    "no_results",
    "offset_out_of_range",
    "unreadable_filtered",
]
JudgmentAlertForumLevelLiteral = Literal[
    "lower_court",
    "high_court",
    "supreme_court",
    "tribunal",
]
JudgmentAlertDocumentTypeLiteral = Literal["judgment", "order"]
JudgmentAlertActionLiteral = Literal["read", "dismiss"]


class AuthoritySourceRecord(BaseModel):
    source: str
    label: str
    description: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral


class AuthoritySourceListResponse(BaseModel):
    sources: list[AuthoritySourceRecord]


class AuthorityIngestionRequest(BaseModel):
    source: str = Field(min_length=2, max_length=120)
    max_documents: int = Field(default=8, ge=1, le=20)


class AuthorityIngestionRunRecord(BaseModel):
    id: str
    requested_by_membership_id: str | None
    requested_by_name: str | None
    source: str
    adapter_name: str | None
    status: Literal["completed", "failed"]
    summary: str | None
    imported_document_count: int
    started_at: datetime
    completed_at: datetime


class AuthorityDocumentRecord(BaseModel):
    id: str
    source: str
    adapter_name: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral
    title: str
    case_reference: str | None
    bench_name: str | None
    neutral_citation: str | None
    # Nullable: see AuthorityDocument model for why.
    decision_date: date | None
    source_reference: str | None
    summary: str
    extracted_char_count: int
    ingested_at: datetime
    updated_at: datetime


class AuthorityDocumentListResponse(BaseModel):
    documents: list[AuthorityDocumentRecord]


class AuthoritySearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=600)
    mode: AuthoritySearchModeLiteral = "keyword"
    # PG-110 (2026-05-01): bump ceiling 10→50 so pagination is useful;
    # 50 is still small enough to keep retrieval+rerank under 10s.
    limit: int = Field(default=10, ge=1, le=50)
    # PG-110: pagination cursor — 0-indexed offset into the ranked
    # result set. The service over-fetches enough to honour offset
    # without re-running retrieval per page.
    offset: int = Field(default=0, ge=0, le=500)
    # PG-110: language filter. "en" (default) drops results whose
    # title is non-Latin-script (Garo, Hindi, Tamil, etc. — common
    # after the 2026-04-28 ingest sweep dropped EN-only filtering).
    # "any" returns the unfiltered ranked set.
    language: Literal["en", "any"] = "en"
    forum_level: AuthorityForumLevelLiteral | None = None
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    document_type: AuthorityDocumentTypeLiteral | None = None


class AuthorityContextualQueryPlan(BaseModel):
    key_facts: list[str] = Field(default_factory=list, max_length=6)
    likely_issues: list[str] = Field(default_factory=list, max_length=6)
    statutes_or_sections: list[str] = Field(default_factory=list, max_length=6)
    procedural_posture: list[str] = Field(default_factory=list, max_length=4)
    jurisdiction_hints: list[str] = Field(default_factory=list, max_length=4)
    timing_signals: list[str] = Field(default_factory=list, max_length=4)
    planned_query: str = Field(max_length=360)


AuthorityCitationTreatmentLiteral = Literal[
    "followed",
    "distinguished",
    "overruled",
    "doubted",
    "reversed",
    "dissented",
    "considered",
    "neutral",
]


class AuthoritySearchResult(BaseModel):
    authority_document_id: str
    title: str
    court_name: str
    forum_level: AuthorityForumLevelLiteral
    document_type: AuthorityDocumentTypeLiteral
    decision_date: date | None
    case_reference: str | None
    bench_name: str | None
    summary: str
    source: str
    source_reference: str | None
    source_action: SourceActionRecord | None = None
    snippet: str
    score: int
    matched_terms: list[str]
    relevance_reason: str | None = None
    # PG-006 Phase 1B (2026-05-01) — good-law signal. Lightweight
    # rollup so the search result list can show a single-glance
    # treatment badge without a per-row N+1 fetch. ``worst_treatment``
    # is the strongest adverse signal in the incoming-citation graph
    # (overruled > reversed > doubted) or null when no adverse cite
    # exists. ``adverse_count`` is the total number of adverse incoming
    # citations.
    worst_treatment: AuthorityCitationTreatmentLiteral | None = None
    adverse_count: int = 0


class AuthoritySearchResponse(BaseModel):
    query: str
    mode: AuthoritySearchModeLiteral = "keyword"
    provider: str
    generated_at: datetime
    results: list[AuthoritySearchResult]
    contextual_plan: AuthorityContextualQueryPlan | None = None
    coverage_notice: str | None = None
    # PG-110 (2026-05-01) — pagination metadata. ``total_after_filter``
    # is the size of the ranked+language-filtered result set; ``offset``
    # echoes back the request so the UI can compute Prev/Next visibility.
    total_after_filter: int = 0
    offset: int = 0
    outcome: AuthoritySearchOutcomeLiteral = "no_results"
    diagnostics: dict[str, int | bool] = Field(default_factory=dict)


class JudgmentAlertRuleBase(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    query_terms: list[str] = Field(default_factory=list, max_length=8)
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    forum_level: JudgmentAlertForumLevelLiteral | None = None
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    statute_terms: list[str] = Field(default_factory=list, max_length=8)
    document_types: list[JudgmentAlertDocumentTypeLiteral] = Field(
        default_factory=lambda: ["judgment", "order"],
        max_length=2,
    )
    since_date: date | None = None
    until_date: date | None = None

    @field_validator(
        "court_name",
        "judge_name",
        "practice_area",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("query_terms", "statute_terms", mode="before")
    @classmethod
    def _split_terms(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


class JudgmentAlertRuleCreateRequest(JudgmentAlertRuleBase):
    pass


class JudgmentAlertRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    query_terms: list[str] | None = Field(default=None, max_length=8)
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    forum_level: JudgmentAlertForumLevelLiteral | None = None
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    statute_terms: list[str] | None = Field(default=None, max_length=8)
    document_types: list[JudgmentAlertDocumentTypeLiteral] | None = Field(
        default=None,
        max_length=2,
    )
    since_date: date | None = None
    until_date: date | None = None
    is_archived: bool | None = None

    @field_validator(
        "name",
        "court_name",
        "judge_name",
        "practice_area",
        mode="before",
    )
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @field_validator("query_terms", "statute_terms", mode="before")
    @classmethod
    def _split_terms(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


class JudgmentAlertRuleRecord(BaseModel):
    id: str
    company_id: str
    name: str
    query_terms: list[str]
    court_name: str | None
    forum_level: JudgmentAlertForumLevelLiteral | None
    judge_name: str | None
    practice_area: str | None
    statute_terms: list[str]
    document_types: list[JudgmentAlertDocumentTypeLiteral]
    since_date: date | None
    until_date: date | None
    is_archived: bool
    created_by_membership_id: str | None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class JudgmentAlertRuleListResponse(BaseModel):
    rules: list[JudgmentAlertRuleRecord]


class JudgmentAlertAuthorityRecord(BaseModel):
    authority_document_id: str
    title: str
    court_name: str
    forum_level: str
    document_type: str
    citation_reference: str | None
    decision_date: date | None
    match_reason: str
    source: str
    source_reference: str | None
    snippet: str | None = Field(default=None, max_length=280)


class JudgmentAlertRecord(BaseModel):
    id: str
    company_id: str
    rule_id: str
    is_read: bool
    read_at: datetime | None
    dismissed_at: datetime | None
    created_at: datetime
    authority: JudgmentAlertAuthorityRecord


class JudgmentAlertListResponse(BaseModel):
    alerts: list[JudgmentAlertRecord]


class JudgmentAlertRunRequest(BaseModel):
    preview_only: bool = False
    limit: int = Field(default=20, ge=1, le=50)


class JudgmentAlertRunResponse(BaseModel):
    rule_id: str
    preview_only: bool
    matched_count: int
    created_count: int
    matches: list[JudgmentAlertAuthorityRecord]
    delivery_status: Literal["in_app_only"] = "in_app_only"


class JudgmentAlertUpdateRequest(BaseModel):
    action: JudgmentAlertActionLiteral


class JudgmentAlertDigestPreviewResponse(BaseModel):
    generated_at: datetime
    unread_count: int
    dismissed_count: int
    alerts: list[JudgmentAlertRecord]
    delivery_status: Literal["in_app_only"] = "in_app_only"
    delivery_note: str = (
        "In-app preview only. External delivery is not configured in this foundation."
    )


class AuthorityCorpusStats(BaseModel):
    document_count: int
    chunk_count: int
    embedded_chunk_count: int
    forum_counts: dict[str, int]
    last_ingested_at: datetime | None


AuthorityAnnotationKindLiteral = Literal["note", "flag", "tag"]


class AuthorityAnnotationRecord(BaseModel):
    id: str
    company_id: str
    authority_document_id: str
    created_by_membership_id: str | None
    kind: AuthorityAnnotationKindLiteral
    title: str
    body: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "018f1234-dead-beef-cafe-0123456789ab",
                    "company_id": "018f0000-0000-0000-0000-000000000001",
                    "authority_document_id": "d4ad579f-9b50-49bf-af02-755f14326c55",
                    "created_by_membership_id": "018f1111-2222-3333-4444-555555555555",
                    "kind": "flag",
                    "title": "Parity precedent for bail",
                    "body": "Cite alongside the triple-test paragraph in every bail brief.",
                    "is_archived": False,
                    "created_at": "2026-04-18T13:00:00Z",
                    "updated_at": "2026-04-18T13:00:00Z",
                }
            ]
        }
    }


class AuthorityAnnotationListResponse(BaseModel):
    annotations: list[AuthorityAnnotationRecord]


class AuthorityAnnotationCreateRequest(BaseModel):
    kind: AuthorityAnnotationKindLiteral
    title: str = Field(min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "kind": "note",
                    "title": "Useful for triple-test framing",
                    "body": (
                        "The ratio at paragraphs 17-21 is the cleanest summary "
                        "of BNSS s.483 requirements we have seen."
                    ),
                }
            ]
        }
    }


class AuthorityAnnotationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, max_length=8000)
    is_archived: bool | None = None


class SavedAuthorityAnnotationRecord(BaseModel):
    """An annotation joined with the authority preview the saved-research
    history view needs to render a row without a second fetch (BUG-030)."""

    id: str
    authority_document_id: str
    created_by_membership_id: str | None
    kind: AuthorityAnnotationKindLiteral
    title: str
    body: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    authority_court_name: str
    authority_forum_level: AuthorityForumLevelLiteral
    authority_document_type: AuthorityDocumentTypeLiteral
    authority_title: str
    authority_neutral_citation: str | None
    authority_case_reference: str | None
    authority_decision_date: date | None
    authority_summary: str


class SavedAnnotationListResponse(BaseModel):
    annotations: list[SavedAuthorityAnnotationRecord]


# PG-006 Phase 1B — treatment summary surface ----------------


class AuthorityTreatmentSampleRecord(BaseModel):
    citing_authority_document_id: str
    citing_title: str | None
    citing_neutral_citation: str | None
    citation_text: str
    treatment: AuthorityCitationTreatmentLiteral
    confidence: float | None
    evidence_text: str | None


class AuthorityTreatmentBucketRecord(BaseModel):
    treatment: AuthorityCitationTreatmentLiteral
    count: int
    samples: list[AuthorityTreatmentSampleRecord]


class AuthorityTreatmentSummaryResponse(BaseModel):
    authority_document_id: str
    total_incoming: int
    adverse_count: int
    has_adverse_treatment: bool
    worst_treatment: AuthorityCitationTreatmentLiteral | None
    buckets: list[AuthorityTreatmentBucketRecord]
