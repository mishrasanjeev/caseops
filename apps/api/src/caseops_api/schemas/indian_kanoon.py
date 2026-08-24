from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from caseops_api.schemas.source_actions import SourceActionRecord

IndianKanoonReadinessState = Literal[
    "blocked_disabled",
    "blocked_missing_config",
    "blocked_terms",
    "blocked_costs",
    "blocked_budget",
    "ready",
]
IndianKanoonFailureCode = Literal[
    "provider_disabled",
    "provider_configuration",
    "provider_terms",
    "provider_cost_policy",
    "provider_budget_exhausted",
    "provider_authentication",
    "provider_quota",
    "source_removed",
    "provider_contract_changed",
    "provider_outage",
    "unsupported_operation",
]


class IndianKanoonAttribution(BaseModel):
    label: Literal["Powered by Indian Kanoon"] = "Powered by Indian Kanoon"
    provider_url: str = "https://indiankanoon.org/"
    terms_url: str = "https://indiankanoon.org/terms.html"
    logo_required: bool = True


class IndianKanoonReadinessResponse(BaseModel):
    provider: Literal["indian-kanoon"] = "indian-kanoon"
    state: IndianKanoonReadinessState
    configured: bool
    enabled: bool
    external_calls_enabled: bool
    missing_config_names: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    missing_cost_categories: list[str] = Field(default_factory=list)
    permitted_uses: list[str] = Field(default_factory=list)
    daily_budget_minor: int = Field(ge=0)
    monthly_budget_minor: int = Field(ge=0)
    retention_days: int = Field(ge=0)
    terms_owner: str | None = None
    terms_approved_at: datetime | None = None
    terms_expires_at: datetime | None = None
    kill_switch_name: Literal["INDIAN_KANOON_ENABLED"] = "INDIAN_KANOON_ENABLED"
    attribution: IndianKanoonAttribution = Field(default_factory=IndianKanoonAttribution)
    limitations: list[str] = Field(default_factory=list)


class IndianKanoonSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=600)
    page_number: int = Field(default=0, ge=0, le=100)
    max_results: int = Field(default=20, ge=1, le=100)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class IndianKanoonFragmentRequest(BaseModel):
    query: str = Field(min_length=2, max_length=600)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class IndianKanoonSourceRecord(BaseModel):
    document_id: str
    title: str
    publisher: str
    jurisdiction: str = "India"
    issuing_body: str | None = None
    source_category: str
    document_type: str
    decision_or_publication_date: date | None = None
    canonical_citation: str | None = None
    authority_status: str = "provider_record_unreviewed"
    binding_status: str = "verify_jurisdiction_and_precedential_status"
    canonical_url: str
    source_action: SourceActionRecord
    attribution: IndianKanoonAttribution = Field(default_factory=IndianKanoonAttribution)


class IndianKanoonSearchResult(IndianKanoonSourceRecord):
    rank: int = Field(ge=1)
    headline: str | None = None


class IndianKanoonCallMetadata(BaseModel):
    cached: bool
    stale: bool
    freshness_warning: str | None = None
    retrieved_at: datetime
    estimated_cost_minor: int = Field(ge=0)
    currency: Literal["INR"] = "INR"
    cost_category: str
    cost_basis: Literal["approved_actual", "fresh_cache", "stale_cache"]


class IndianKanoonSearchResponse(BaseModel):
    query: str
    page_number: int
    returned_count: int = Field(ge=0)
    results: list[IndianKanoonSearchResult]
    call: IndianKanoonCallMetadata
    attribution: IndianKanoonAttribution = Field(default_factory=IndianKanoonAttribution)
    disclaimer: str = (
        "Provider results are research aids. Verify the exact passage, court, "
        "precedential status, subsequent treatment, and official source before reliance."
    )


class IndianKanoonDocumentResponse(IndianKanoonSourceRecord):
    content: str
    content_hash: str
    source_version: str
    exact_passage_query: str | None = None
    call: IndianKanoonCallMetadata
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class IndianKanoonMetadataResponse(IndianKanoonSourceRecord):
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    content_hash: str | None = None
    source_version: str | None = None
    call: IndianKanoonCallMetadata


class IndianKanoonHealthResponse(BaseModel):
    readiness: IndianKanoonReadinessResponse
    health: Literal["ready", "blocked"]
    checked_at: datetime
    performs_external_probe: Literal[False] = False


class IndianKanoonImportRequest(BaseModel):
    expected_content_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class IndianKanoonImportResponse(BaseModel):
    authority_document_id: str
    document_id: str
    created: bool
    changed: bool
    invalidated_report_count: int = Field(ge=0)
    content_hash: str
    source_version: str
    legal_review_status: str
    source_action: SourceActionRecord
    attribution: IndianKanoonAttribution = Field(default_factory=IndianKanoonAttribution)


class AuthorityLegalSourceReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    expected_content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    note: str = Field(min_length=8, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def strip_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AuthorityLegalSourceReviewResponse(BaseModel):
    authority_document_id: str
    legal_review_status: Literal["first_reviewed", "verified", "rejected"]
    first_reviewed_by_membership_id: str | None
    first_reviewed_at: datetime | None
    second_reviewed_by_membership_id: str | None
    second_reviewed_at: datetime | None
    content_hash: str
    note: str
