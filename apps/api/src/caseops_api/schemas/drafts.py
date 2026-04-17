from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

DraftStatusLiteral = Literal[
    "draft",
    "in_review",
    "changes_requested",
    "approved",
    "finalized",
]
DraftTypeLiteral = Literal["brief", "notice", "reply", "memo", "other"]
DraftReviewActionLiteral = Literal["submit", "request_changes", "approve", "finalize"]


class DraftCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    draft_type: DraftTypeLiteral = "brief"


class DraftGenerateRequest(BaseModel):
    """Body is empty today; kept to give room for future options —
    e.g. template selection, tone steering, focus issues. Having the
    POST body already in place means adding the knob later doesn't
    force a breaking API bump."""

    template_key: str | None = Field(default=None, max_length=120)
    focus_note: str | None = Field(default=None, max_length=4000)


class DraftReviewRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class DraftVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    draft_id: str
    revision: int
    body: str
    citations: list[str]
    verified_citation_count: int
    summary: str | None
    generated_by_membership_id: str | None
    model_run_id: str | None
    created_at: datetime


class DraftReviewRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    draft_id: str
    version_id: str | None
    actor_membership_id: str | None
    action: DraftReviewActionLiteral
    notes: str | None
    created_at: datetime


class DraftRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    created_by_membership_id: str | None
    title: str
    draft_type: DraftTypeLiteral
    status: DraftStatusLiteral
    review_required: bool
    current_version_id: str | None
    versions: list[DraftVersionRecord]
    reviews: list[DraftReviewRecord]
    created_at: datetime
    updated_at: datetime


class DraftListResponse(BaseModel):
    drafts: list[DraftRecord]
    next_cursor: str | None = None
