from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from caseops_api.schemas.source_actions import SourceActionRecord

ReviewStateLiteral = Literal[
    "queued",
    "running",
    "ready",
    "abstained",
    "failed",
    "finalized",
    "published",
]
AuthorityDispositionLiteral = Literal["supporting", "contrary"]


class IntelligentReviewFactInput(BaseModel):
    label: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=2000)
    source_ref: str | None = Field(default=None, max_length=500)

    @field_validator("label", "value", "source_ref", mode="before")
    @classmethod
    def _normalize_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None


class IntelligentReviewCreateRequest(BaseModel):
    issue: str = Field(min_length=3, max_length=1200)
    source_research_report_id: str = Field(min_length=1, max_length=36)
    matter_id: str | None = Field(default=None, max_length=36)
    ip_docket_id: str | None = Field(default=None, max_length=36)
    ip_proceeding_id: str | None = Field(default=None, max_length=36)
    facts: list[IntelligentReviewFactInput] = Field(default_factory=list, max_length=50)
    document_refs: list[str] = Field(default_factory=list, max_length=50)
    included_authority_ids: list[str] = Field(default_factory=list, max_length=25)

    @field_validator("issue", mode="before")
    @classmethod
    def _normalize_issue(cls, value: object) -> str:
        return " ".join(str(value).split())

    @field_validator("document_refs", "included_authority_ids", mode="before")
    @classmethod
    def _dedupe_list(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @model_validator(mode="after")
    def _validate_target(self) -> IntelligentReviewCreateRequest:
        if (self.matter_id is None) == (self.ip_docket_id is None):
            raise ValueError("Exactly one of matter_id or ip_docket_id is required.")
        if self.ip_proceeding_id and not self.ip_docket_id:
            raise ValueError("ip_proceeding_id requires ip_docket_id.")
        return self


class IntelligentReviewAssertionRecord(BaseModel):
    text: str
    authority_document_ids: list[str] = Field(default_factory=list)


class IntelligentReviewAuthorityRecord(BaseModel):
    authority_document_id: str
    disposition: AuthorityDispositionLiteral
    title: str
    citation: str
    court: str
    decision_date: str | None
    source_url: str | None
    source_action: SourceActionRecord
    passage: str
    relevance: str
    treatment: str | None
    access_state: str
    content_hash: str | None
    source_version: str | None
    retrieved_at: str | None
    selected: bool


class IntelligentReviewCompletenessRecord(BaseModel):
    selected_authority_count: int
    supporting_authority_count: int
    contrary_authority_count: int
    cited_assertion_count: int
    unsupported_assertion_count: int
    complete: bool
    reasons: list[str] = Field(default_factory=list)


class IntelligentReviewRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str | None
    ip_docket_id: str | None
    ip_proceeding_id: str | None
    source_research_report_id: str
    state: ReviewStateLiteral
    progress: int
    error_code: str | None
    issue: str
    relevant_facts: list[str] = Field(default_factory=list)
    applicable_provisions: list[IntelligentReviewAssertionRecord] = Field(default_factory=list)
    supporting_authorities: list[IntelligentReviewAuthorityRecord] = Field(default_factory=list)
    contrary_authorities: list[IntelligentReviewAuthorityRecord] = Field(default_factory=list)
    factual_analogies: list[IntelligentReviewAssertionRecord] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    lawyer_checks: list[str] = Field(default_factory=list)
    unresolved_contradictions: list[str] = Field(default_factory=list)
    abstention_reason: str | None = None
    stale_warning: str | None = None
    source_freshness_at: str | None = None
    non_exhaustive_disclaimer: str
    lawyer_notes: str | None = None
    completeness: IntelligentReviewCompletenessRecord
    review_template_version: str | None
    prompt_policy_version: str | None
    model_run_id: str | None
    output_hash: str | None
    finalized_by_membership_id: str | None
    finalized_at: datetime | None
    published_draft_id: str | None
    created_at: datetime
    updated_at: datetime


class IntelligentReviewListResponse(BaseModel):
    reviews: list[IntelligentReviewRecord]


class IntelligentReviewSelectionRequest(BaseModel):
    included_authority_ids: list[str] = Field(default_factory=list, max_length=25)
    lawyer_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("included_authority_ids", mode="before")
    @classmethod
    def _dedupe_authorities(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))

    @field_validator("lawyer_notes", mode="before")
    @classmethod
    def _normalize_notes(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class IntelligentReviewFinalizeRequest(BaseModel):
    lawyer_notes: str | None = Field(default=None, max_length=5000)


class IntelligentReviewPublishRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)


class IntelligentReviewPublishResponse(BaseModel):
    review: IntelligentReviewRecord
    draft_id: str
    draft_version_id: str
