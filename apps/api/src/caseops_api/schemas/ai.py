from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BriefTypeLiteral = Literal["matter_summary", "hearing_prep"]
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
    key_points: list[str]
    risks: list[str]
    recommended_actions: list[str]
    upcoming_items: list[str]
    billing_snapshot: str


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
