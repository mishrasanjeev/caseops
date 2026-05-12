from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LitigationReviewItemTypeLiteral = Literal[
    "proceeding_signal",
    "affidavit_statement",
    "affidavit_question",
    "mock_hearing_session",
    "mock_hearing_response",
    "predictive_signal",
    "bench_context",
]
LitigationReviewStatusLiteral = Literal[
    "review_required",
    "reviewed",
    "auto_promoted",
    "insufficient_evidence",
    "supported",
    "limited_context",
    "active",
    "completed",
]
LitigationReviewPriorityLiteral = Literal["high", "medium", "low"]
LitigationReviewSourceTypeLiteral = Literal[
    "matter_court_order",
    "matter_cause_list_entry",
    "matter_document",
    "matter_attachment_chunk",
    "affidavit_statement",
    "affidavit_question",
    "mock_hearing_session",
    "predictive_signal_run",
    "authority_document",
    "aggregate_snapshot",
]


class LitigationIntelligenceReviewSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: LitigationReviewSourceTypeLiteral
    source_id: str
    label: str
    reference: str | None = None
    snippet: str | None = None
    page_reference: str | None = None


class LitigationIntelligenceReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    item_type: LitigationReviewItemTypeLiteral
    title: str
    description: str
    status: LitigationReviewStatusLiteral
    priority: LitigationReviewPriorityLiteral
    confidence_label: str | None = None
    evidence_quality: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    limitation_note: str
    review_reason: str
    source: LitigationIntelligenceReviewSource
    due_on: date | None = None
    created_at: datetime
    updated_at: datetime | None = None


class LitigationIntelligenceReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_items: int = Field(ge=0)
    review_required_count: int = Field(ge=0)
    source_linked_count: int = Field(ge=0)
    by_type: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)


class LitigationIntelligenceReviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter_id: str
    generated_at: datetime
    disclaimer: str
    summary: LitigationIntelligenceReviewSummary
    items: list[LitigationIntelligenceReviewItem] = Field(default_factory=list)
