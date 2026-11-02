"""Bounded retained decision-support reads. These DTOs grant no workflow action."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.litigation_strategy import LitigationStrategyPayload
from caseops_api.schemas.recommendations import RecommendationAnalysisRecord

ReadState = Literal["available", "unsupported_size", "unsupported_legacy"]


class MatterReadScope(BaseModel):
    company_id: str
    matter_id: str
    matter_status: str
    matter_is_active: bool
    matter_lifecycle_version: int


class RetainedRead[T](BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    read_state: ReadState
    record: T | None


class RecommendationMetadata(BaseModel):
    type: str
    title: str
    confidence: str
    review_required: bool
    status: str


class RecommendationContent(RecommendationMetadata):
    rationale: str
    primary_option_index: int
    assumptions: list[str]
    missing_facts: list[str]
    next_action: str | None
    retrieved_authorities: list[str]
    strategy_payload: LitigationStrategyPayload | None
    analysis: RecommendationAnalysisRecord | None


class RecommendationSummary(RetainedRead[RecommendationMetadata]):
    created_at: datetime
    updated_at: datetime


class RecommendationDetail(RetainedRead[RecommendationContent]):
    scope: MatterReadScope
    created_at: datetime
    updated_at: datetime


class RecommendationOptionContent(BaseModel):
    label: str
    rationale: str
    confidence: str
    supporting_citations: list[str]
    risk_notes: str | None


class RecommendationOptionRead(RetainedRead[RecommendationOptionContent]):
    rank: int


class RecommendationDecisionContent(BaseModel):
    actor_membership_id: str | None
    decision: str
    selected_option_index: int | None
    notes: str | None


class RecommendationDecisionRead(RetainedRead[RecommendationDecisionContent]):
    created_at: datetime


class HearingPackContent(BaseModel):
    generated_by_membership_id: str | None
    reviewed_by_membership_id: str | None
    model_run_id: str | None
    status: str
    summary: str
    review_required: bool


class HearingPackRead(RetainedRead[HearingPackContent]):
    scope: MatterReadScope
    hearing_id: str | None
    generated_at: datetime
    reviewed_at: datetime | None


class HearingPackItemContent(BaseModel):
    item_type: str
    title: str
    body: str
    # Stored opaque reference only: never resolved or treated as authority to open a URL.
    source_ref: str | None


class HearingPackItemRead(RetainedRead[HearingPackItemContent]):
    rank: int
    created_at: datetime


class ReadPage[T](BaseModel):
    scope: MatterReadScope
    parent_id: str | None
    limit: int = Field(ge=1, le=25)
    order: str
    items: list[T]
    next_cursor: str | None


class RecommendationPage(ReadPage[RecommendationSummary]):
    order: Literal["created_at_desc_id_desc"] = "created_at_desc_id_desc"
    kind: Literal["recommendations"] = "recommendations"


class RecommendationOptionPage(ReadPage[RecommendationOptionRead]):
    order: Literal["rank_asc_id_asc"] = "rank_asc_id_asc"
    kind: Literal["recommendation_options"] = "recommendation_options"


class RecommendationDecisionPage(ReadPage[RecommendationDecisionRead]):
    order: Literal["created_at_desc_id_desc"] = "created_at_desc_id_desc"
    kind: Literal["recommendation_decisions"] = "recommendation_decisions"


class HearingPackItemPage(ReadPage[HearingPackItemRead]):
    order: Literal["rank_asc_id_asc"] = "rank_asc_id_asc"
    kind: Literal["hearing_pack_items"] = "hearing_pack_items"
