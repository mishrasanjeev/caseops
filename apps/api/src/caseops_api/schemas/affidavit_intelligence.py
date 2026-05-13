from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AffidavitRunStatusLiteral = Literal[
    "completed",
    "insufficient_source_text",
    "no_findings",
]
AffidavitStatementTypeLiteral = Literal[
    "key_statement",
    "fact_assertion",
    "timeline_point",
    "monetary_figure",
    "named_entity",
    "exhibit_reference",
    "evidence_gap",
    "contradiction",
]
AffidavitQuestionCategoryLiteral = Literal[
    "fact_based",
    "timeline_inconsistency",
    "financial_scrutiny",
    "evidence_contradiction",
    "document_support",
    "intent_motive",
]
AffidavitConfidenceLiteral = Literal["low", "medium", "high"]
AffidavitReviewStatusLiteral = Literal[
    "review_required",
    "reviewed",
    "insufficient_evidence",
]


class AffidavitStatementRecord(BaseModel):
    id: str
    run_id: str
    matter_id: str
    attachment_id: str
    source_chunk_id: str | None = None
    source_chunk_index: int | None = None
    page_reference: str | None = None
    statement_type: AffidavitStatementTypeLiteral
    statement_text: str
    source_quote: str
    confidence_label: AffidavitConfidenceLiteral
    review_status: AffidavitReviewStatusLiteral
    created_at: datetime
    updated_at: datetime


class AffidavitQuestionRecord(BaseModel):
    id: str
    run_id: str
    matter_id: str
    attachment_id: str
    statement_id: str | None = None
    source_chunk_id: str | None = None
    source_chunk_index: int | None = None
    page_reference: str | None = None
    category: AffidavitQuestionCategoryLiteral
    question_text: str
    reason: str
    source_quote: str
    confidence_label: AffidavitConfidenceLiteral
    review_required: bool
    review_status: AffidavitReviewStatusLiteral
    created_at: datetime
    updated_at: datetime


class AffidavitIntelligenceRunRecord(BaseModel):
    id: str
    matter_id: str
    attachment_id: str
    status: AffidavitRunStatusLiteral
    extraction_method: Literal["deterministic", "llm"] = "deterministic"
    parser_version: str
    source_hash: str
    source_char_count: int
    missing_data: list[str] = Field(default_factory=list)
    model_run_id: str | None = None
    created_by_membership_id: str | None = None
    created_at: datetime
    updated_at: datetime
    statements: list[AffidavitStatementRecord] = Field(default_factory=list)
    questions: list[AffidavitQuestionRecord] = Field(default_factory=list)


class AffidavitIntelligenceResponse(BaseModel):
    matter_id: str
    generated_at: datetime
    disclaimer: str
    runs: list[AffidavitIntelligenceRunRecord] = Field(default_factory=list)
    latest_run: AffidavitIntelligenceRunRecord | None = None
