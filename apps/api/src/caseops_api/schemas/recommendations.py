from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Sprint 9 BG-023: four recommendation kinds land here. Each drives a
# distinct retrieval query + prompt framing in the service layer; the
# output schema is shared so the UI renders all four identically.
RecommendationTypeLiteral = Literal[
    "forum", "authority", "remedy", "next_best_action"
]
ConfidenceLiteral = Literal["low", "medium", "high"]
DecisionLiteral = Literal["accepted", "rejected", "edited", "deferred"]
StatusLiteral = Literal[
    "proposed", "accepted", "rejected", "edited", "deferred"
]


class RecommendationOptionRecord(BaseModel):
    id: str
    rank: int
    label: str
    rationale: str
    confidence: ConfidenceLiteral
    supporting_citations: list[str]
    risk_notes: str | None


class RecommendationDecisionRecord(BaseModel):
    id: str
    actor_membership_id: str | None
    decision: DecisionLiteral
    selected_option_index: int | None
    notes: str | None
    created_at: datetime


class RecommendationRecord(BaseModel):
    id: str
    matter_id: str
    type: RecommendationTypeLiteral
    title: str
    rationale: str
    primary_option_index: int
    assumptions: list[str]
    missing_facts: list[str]
    confidence: ConfidenceLiteral
    review_required: bool
    status: StatusLiteral
    next_action: str | None
    created_at: datetime
    options: list[RecommendationOptionRecord]
    decisions: list[RecommendationDecisionRecord]


class RecommendationListResponse(BaseModel):
    matter_id: str
    recommendations: list[RecommendationRecord]


class RecommendationGenerateRequest(BaseModel):
    type: RecommendationTypeLiteral = "authority"


class RecommendationDecisionRequest(BaseModel):
    decision: DecisionLiteral
    selected_option_index: int | None = Field(default=None, ge=0, le=20)
    notes: str | None = Field(default=None, max_length=2000)
