from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SourceActionState = Literal[
    "available",
    "missing",
    "unverified",
    "blocked",
    "quarantined",
]
SourceTargetType = Literal[
    "authority_document",
    "statute_section",
    "judge_appointment",
    "matter_attachment",
]
SourceOriginSurface = Literal[
    "research",
    "saved_research",
    "judge_profile",
    "uploaded_case_analysis",
    "intelligent_review",
    "statute",
    "other",
]
SourceIssueType = Literal[
    "broken",
    "wrong_document",
    "access_denied",
    "stale",
    "other",
]


class SourceActionRecord(BaseModel):
    """Typed, fail-closed contract for every user-visible source action."""

    state: SourceActionState
    label: str = "Open source"
    open_url: str | None = None
    source_reference: str | None = None
    reason: str | None = None
    opens_new_tab: bool = True
    target_type: SourceTargetType | None = None
    target_id: str | None = None


class SourceActionInspectRequest(BaseModel):
    source_reference: str | None = Field(default=None, max_length=1000)
    verified: bool = False
    quarantined: bool = False


class SourceLinkReportCreateRequest(BaseModel):
    target_type: SourceTargetType
    target_id: str = Field(min_length=1, max_length=120)
    origin_surface: SourceOriginSurface
    issue_type: SourceIssueType
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("target_id", "description", mode="before")
    @classmethod
    def strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class SourceLinkReportRecord(BaseModel):
    id: str
    target_type: SourceTargetType
    target_id: str
    origin_surface: SourceOriginSurface
    issue_type: SourceIssueType
    status: Literal["queued", "investigating", "resolved", "dismissed"]
    source_state: SourceActionState
    destination_class: str
    created_at: datetime


__all__ = [
    "SourceActionInspectRequest",
    "SourceActionRecord",
    "SourceActionState",
    "SourceIssueType",
    "SourceLinkReportCreateRequest",
    "SourceLinkReportRecord",
    "SourceOriginSurface",
    "SourceTargetType",
]
