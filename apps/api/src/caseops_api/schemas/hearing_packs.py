from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

HearingPackStatusLiteral = Literal["draft", "reviewed"]
HearingPackItemKindLiteral = Literal[
    "chronology",
    "last_order",
    "pending_compliance",
    "issue",
    "opposition_point",
    "authority_card",
    "oral_point",
]


class HearingPackItemRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_type: HearingPackItemKindLiteral
    title: str
    body: str
    rank: int
    source_ref: str | None
    created_at: datetime


class HearingPackRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    hearing_id: str | None
    generated_by_membership_id: str | None
    reviewed_by_membership_id: str | None
    model_run_id: str | None
    status: HearingPackStatusLiteral
    summary: str
    review_required: bool
    generated_at: datetime
    reviewed_at: datetime | None
    items: list[HearingPackItemRecord]


class HearingPackGenerateRequest(BaseModel):
    """Body is empty for now — kept as a placeholder for future options
    (include_authorities: bool, focus_issues: list[str], etc.)."""

    focus_note: str | None = None
