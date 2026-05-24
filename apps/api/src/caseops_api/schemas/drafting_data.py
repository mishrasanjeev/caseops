from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DraftingDataFieldStatusLiteral = Literal[
    "suggested",
    "needs_review",
    "confirmed",
    "overridden",
    "rejected",
]
DraftingDataConfidenceBandLiteral = Literal["high", "medium", "low"]
DraftingDataReviewActionLiteral = Literal["confirm", "override", "reject"]


class DraftingDataFieldRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    source_attachment_id: str | None
    field_key: str
    label: str
    proposed_value: str
    reviewed_value: str | None
    effective_value: str | None
    confidence_band: DraftingDataConfidenceBandLiteral
    status: DraftingDataFieldStatusLiteral
    source_snippet: str | None
    source_verified: bool
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DraftingDataStatusCounts(BaseModel):
    suggested: int = 0
    needs_review: int = 0
    confirmed: int = 0
    overridden: int = 0
    rejected: int = 0


class DraftingDataExtractionResponse(BaseModel):
    matter_id: str
    fields: list[DraftingDataFieldRecord]
    counts: DraftingDataStatusCounts
    created_count: int = 0
    updated_count: int = 0
    source_attachment_count: int = 0


class DraftingDataReviewRequest(BaseModel):
    action: DraftingDataReviewActionLiteral
    override_value: str | None = Field(default=None, max_length=500)

    @field_validator("override_value")
    @classmethod
    def _trim_override(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None
