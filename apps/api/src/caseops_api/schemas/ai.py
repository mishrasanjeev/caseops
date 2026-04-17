from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BriefTypeLiteral = Literal["matter_summary", "hearing_prep"]
MatterDocumentReviewTypeLiteral = Literal["workspace_review"]
ContractReviewTypeLiteral = Literal["intake_review"]


class MatterBriefGenerateRequest(BaseModel):
    brief_type: BriefTypeLiteral = "matter_summary"
    focus: str | None = Field(default=None, max_length=500)


class MatterBriefResponse(BaseModel):
    matter_id: str
    brief_type: BriefTypeLiteral
    provider: str
    generated_at: datetime
    headline: str
    summary: str
    authority_highlights: list[str]
    authority_relationships: list[str]
    court_posture: list[str]
    key_points: list[str]
    risks: list[str]
    recommended_actions: list[str]
    upcoming_items: list[str]
    source_provenance: list[str]
    billing_snapshot: str


class MatterDocumentReviewGenerateRequest(BaseModel):
    review_type: MatterDocumentReviewTypeLiteral = "workspace_review"
    focus: str | None = Field(default=None, max_length=500)


class MatterDocumentReviewResponse(BaseModel):
    matter_id: str
    review_type: MatterDocumentReviewTypeLiteral
    provider: str
    generated_at: datetime
    headline: str
    summary: str
    source_attachments: list[str]
    extracted_facts: list[str]
    chronology: list[str]
    risks: list[str]
    recommended_actions: list[str]


class MatterDocumentSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    limit: int = Field(default=5, ge=1, le=10)


class MatterDocumentSearchResult(BaseModel):
    attachment_id: str
    attachment_name: str
    snippet: str
    score: int
    matched_terms: list[str]


class MatterDocumentSearchResponse(BaseModel):
    matter_id: str
    query: str
    provider: str
    generated_at: datetime
    results: list[MatterDocumentSearchResult]


class ContractReviewGenerateRequest(BaseModel):
    review_type: ContractReviewTypeLiteral = "intake_review"
    focus: str | None = Field(default=None, max_length=500)


class ContractReviewResponse(BaseModel):
    contract_id: str
    review_type: ContractReviewTypeLiteral
    provider: str
    generated_at: datetime
    headline: str
    summary: str
    key_clauses: list[str]
    extracted_obligations: list[str]
    risks: list[str]
    recommended_actions: list[str]
    source_attachments: list[str]
