from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

ProceedingSignalTypeLiteral = Literal[
    "next_hearing",
    "filing_defect",
    "compliance_direction",
    "reply_affidavit_deadline",
    "counsel_appearance",
    "interim_observation",
    "order_kind",
    "action_required",
]
ProceedingConfidenceLiteral = Literal["low", "medium", "high"]
ProceedingReviewStatusLiteral = Literal[
    "review_required",
    "reviewed",
    "auto_promoted",
    "insufficient_evidence",
]
ProceedingExtractionStatusLiteral = Literal[
    "supported",
    "insufficient_source_text",
    "insufficient_evidence",
    "not_extracted",
]


class ProceedingSignalRecord(BaseModel):
    id: str
    matter_id: str
    court_order_id: str
    sync_run_id: str | None
    signal_type: ProceedingSignalTypeLiteral
    signal_text: str
    action_required: str | None = None
    due_on: date | None = None
    hearing_on: date | None = None
    order_kind: str | None = None
    confidence_label: ProceedingConfidenceLiteral
    source_snippet: str
    review_status: ProceedingReviewStatusLiteral
    generated_task_id: str | None = None
    generated_deadline_id: str | None = None
    extraction_method: Literal["deterministic", "llm"] = "deterministic"
    parser_version: str
    created_at: datetime
    updated_at: datetime


class ProceedingOrderIntelligenceRecord(BaseModel):
    court_order_id: str
    sync_run_id: str | None = None
    title: str
    order_date: date
    source: str
    source_reference: str | None = None
    order_attachment_id: str | None = None
    extraction_status: ProceedingExtractionStatusLiteral
    missing_data: list[str] = Field(default_factory=list)
    signals: list[ProceedingSignalRecord] = Field(default_factory=list)


class ProceedingIntelligenceResponse(BaseModel):
    matter_id: str
    generated_at: datetime
    disclaimer: str
    orders: list[ProceedingOrderIntelligenceRecord] = Field(default_factory=list)
    pending_compliance_items: list[ProceedingSignalRecord] = Field(default_factory=list)
