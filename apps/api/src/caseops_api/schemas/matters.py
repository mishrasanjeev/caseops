from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from caseops_api.schemas.billing import InvoiceRecord, TimeEntryRecord

MatterStatusLiteral = Literal["intake", "active", "on_hold", "closed"]
MatterForumLevelLiteral = Literal[
    "lower_court",
    "high_court",
    "supreme_court",
    "tribunal",
    "arbitration",
    "advisory",
]


class MatterCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    matter_code: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9-_/]+$")
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    opposing_party: str | None = Field(default=None, min_length=2, max_length=255)
    status: MatterStatusLiteral = "intake"
    practice_area: str = Field(min_length=2, max_length=120)
    forum_level: MatterForumLevelLiteral
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None


class MatterUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    assignee_membership_id: str | None = None
    client_name: str | None = Field(default=None, min_length=2, max_length=255)
    opposing_party: str | None = Field(default=None, min_length=2, max_length=255)
    status: MatterStatusLiteral | None = None
    practice_area: str | None = Field(default=None, min_length=2, max_length=120)
    forum_level: MatterForumLevelLiteral | None = None
    court_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    next_hearing_on: date | None = None
    is_active: bool | None = None


class MatterRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    assignee_membership_id: str | None
    title: str
    matter_code: str
    client_name: str | None
    opposing_party: str | None
    status: MatterStatusLiteral
    practice_area: str
    forum_level: MatterForumLevelLiteral
    court_name: str | None
    judge_name: str | None
    description: str | None
    next_hearing_on: date | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class MatterListResponse(BaseModel):
    company_id: str
    matters: list[MatterRecord]


class MatterWorkspaceMembership(BaseModel):
    membership_id: str
    user_id: str
    full_name: str
    email: str
    role: str
    is_active: bool


class MatterNoteCreateRequest(BaseModel):
    body: str = Field(min_length=2, max_length=4000)


class MatterNoteRecord(BaseModel):
    id: str
    matter_id: str
    author_membership_id: str
    author_name: str
    author_role: str
    body: str
    created_at: datetime


class MatterHearingCreateRequest(BaseModel):
    hearing_on: date
    forum_name: str = Field(min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    purpose: str = Field(min_length=2, max_length=255)
    status: Literal["scheduled", "completed", "adjourned"] = "scheduled"
    outcome_note: str | None = Field(default=None, max_length=4000)


class MatterHearingRecord(BaseModel):
    id: str
    matter_id: str
    hearing_on: date
    forum_name: str
    judge_name: str | None
    purpose: str
    status: Literal["scheduled", "completed", "adjourned"]
    outcome_note: str | None
    created_at: datetime


class MatterActivityRecord(BaseModel):
    id: str
    matter_id: str
    actor_membership_id: str | None
    actor_name: str | None
    event_type: str
    title: str
    detail: str | None
    created_at: datetime


class MatterAttachmentRecord(BaseModel):
    id: str
    matter_id: str
    uploaded_by_membership_id: str | None
    uploaded_by_name: str | None
    original_filename: str
    content_type: str | None
    size_bytes: int
    sha256_hex: str
    created_at: datetime


class MatterWorkspaceResponse(BaseModel):
    matter: MatterRecord
    assignee: MatterWorkspaceMembership | None
    available_assignees: list[MatterWorkspaceMembership]
    attachments: list[MatterAttachmentRecord]
    time_entries: list[TimeEntryRecord]
    invoices: list[InvoiceRecord]
    notes: list[MatterNoteRecord]
    hearings: list[MatterHearingRecord]
    activity: list[MatterActivityRecord]
