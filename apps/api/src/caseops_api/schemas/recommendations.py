from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from caseops_api.schemas.litigation_strategy import LitigationStrategyPayload

# Sprint 9 BG-023: four recommendation kinds land here. Each drives a
# distinct retrieval query + prompt framing in the service layer; the
# output schema is shared so the UI renders all four identically.
#
# MOD-LSE-1 (2026-05-03): the strategy planner adds
# ``litigation_strategy`` as a fifth type. Strategy generation has its
# own service path (``services/litigation_strategy.py``) that hydrates
# a richer ``LitigationStrategyPayload`` alongside the shared
# Recommendation/Option rows.
RecommendationTypeLiteral = Literal[
    "forum",
    "authority",
    "remedy",
    "next_best_action",
    "litigation_strategy",
]
ConfidenceLiteral = Literal["low", "medium", "high"]
DecisionLiteral = Literal["accepted", "rejected", "edited", "deferred"]
StatusLiteral = Literal[
    "proposed", "accepted", "rejected", "edited", "deferred"
]
StrategyEntryTypeLiteral = Literal["plan", "decision", "note"]
StrategyEntryStatusLiteral = Literal["draft", "active", "archived"]


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
    # PG-109 (2026-05-01) — full retrieved-authorities list the LLM
    # was given. UI computes cited-vs-considered by intersecting with
    # options[*].supporting_citations. Empty for legacy rows that
    # pre-date the PG-109 schema column.
    retrieved_authorities: list[str] = Field(default_factory=list)
    # MOD-LSE-1 (2026-05-03) — set only for ``type='litigation_strategy'``.
    # Holds the structured strategy payload (forum sequence, recommended
    # drafts, limitation flags, etc.). Validated against
    # ``LitigationStrategyPayload`` by the strategy service. ``None``
    # on every non-strategy recommendation row.
    strategy_payload: LitigationStrategyPayload | None = None


class RecommendationListResponse(BaseModel):
    matter_id: str
    recommendations: list[RecommendationRecord]


class RecommendationGenerateRequest(BaseModel):
    type: RecommendationTypeLiteral = "authority"


class RecommendationDecisionRequest(BaseModel):
    decision: DecisionLiteral
    selected_option_index: int | None = Field(default=None, ge=0, le=20)
    notes: str | None = Field(default=None, max_length=2000)


class MatterStrategyEntryCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=10000)
    entry_type: StrategyEntryTypeLiteral = "plan"
    status: StrategyEntryStatusLiteral = "active"
    owner_membership_id: str | None = None
    source_recommendation_id: str | None = None


class MatterStrategyEntryUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=10000)
    entry_type: StrategyEntryTypeLiteral | None = None
    status: StrategyEntryStatusLiteral | None = None
    owner_membership_id: str | None = None
    source_recommendation_id: str | None = None


class MatterStrategyEntryRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    title: str
    body: str
    entry_type: StrategyEntryTypeLiteral
    status: StrategyEntryStatusLiteral
    owner_membership_id: str | None
    owner_name: str | None
    created_by_membership_id: str | None
    created_by_name: str | None
    updated_by_membership_id: str | None
    updated_by_name: str | None
    source_recommendation_id: str | None
    created_at: datetime
    updated_at: datetime


class MatterStrategyEntryListResponse(BaseModel):
    matter_id: str
    entries: list[MatterStrategyEntryRecord]
