"""Pydantic shapes for teams / departments (Sprint 8c BG-026)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TeamKindLiteral = Literal["team", "department", "practice_area"]


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    description: str | None = Field(default=None, max_length=2000)
    kind: TeamKindLiteral = "team"


class TeamUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    kind: TeamKindLiteral | None = None
    is_active: bool | None = None


class TeamMembershipRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    team_id: str
    membership_id: str
    member_name: str
    member_email: str
    is_lead: bool
    created_at: datetime


class TeamRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    name: str
    slug: str
    description: str | None
    kind: TeamKindLiteral
    is_active: bool
    member_count: int
    members: list[TeamMembershipRecord]
    created_at: datetime
    updated_at: datetime


class TeamListResponse(BaseModel):
    teams: list[TeamRecord]
    team_scoping_enabled: bool


class TeamMembershipCreateRequest(BaseModel):
    membership_id: str = Field(min_length=1)
    is_lead: bool = False


class TeamScopingUpdateRequest(BaseModel):
    enabled: bool


class TeamScopingResponse(BaseModel):
    enabled: bool
