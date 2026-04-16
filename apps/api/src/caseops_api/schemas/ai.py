from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

BriefTypeLiteral = Literal["matter_summary", "hearing_prep"]


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
