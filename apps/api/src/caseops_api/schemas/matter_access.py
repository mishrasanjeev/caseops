from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

MatterAccessLevelLiteral = Literal["member"]


class MatterAccessGrantCreateRequest(BaseModel):
    membership_id: str = Field(min_length=1, max_length=36)
    access_level: MatterAccessLevelLiteral = "member"
    reason: str | None = Field(default=None, max_length=2000)


class EthicalWallCreateRequest(BaseModel):
    excluded_membership_id: str = Field(min_length=1, max_length=36)
    reason: str | None = Field(default=None, max_length=2000)


class MatterRestrictedAccessRequest(BaseModel):
    restricted: bool


class MatterAccessGrantRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    membership_id: str
    access_level: MatterAccessLevelLiteral
    reason: str | None
    granted_by_membership_id: str | None
    created_at: datetime


class EthicalWallRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str
    excluded_membership_id: str
    reason: str | None
    created_by_membership_id: str | None
    created_at: datetime


class MatterAccessPanelResponse(BaseModel):
    matter_id: str
    restricted_access: bool
    grants: list[MatterAccessGrantRecord]
    walls: list[EthicalWallRecord]
