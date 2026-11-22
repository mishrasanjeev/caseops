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


MembershipRoleLiteral = Literal["owner", "admin", "partner", "member", "paralegal", "viewer"]


class MatterEthicalWallDirectoryRecord(BaseModel):
    """One active Matter wall and the people it names, for the admin screen."""

    id: str
    matter_id: str
    matter_code: str
    matter_title: str
    excluded_membership_id: str
    excluded_full_name: str
    excluded_email: str
    excluded_role: MembershipRoleLiteral
    excluded_membership_active: bool
    # Owners bypass every wall (record_access_policy._is_owner), so a wall
    # naming an owner is stored but has no effect.
    enforced: bool
    reason: str | None
    created_by_membership_id: str | None
    created_by_full_name: str | None
    created_at: datetime


class MatterEthicalWallDirectoryResponse(BaseModel):
    walls: list[MatterEthicalWallDirectoryRecord]
    # More active walls exist than this bounded read returns.
    truncated: bool
