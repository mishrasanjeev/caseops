"""Bounded internal record-access review contracts; no new grant authority."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TargetType = Literal["matter", "ip_docket"]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CampaignCreate(Command):
    target_type: TargetType
    target_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=3, max_length=200)
    reason: str = Field(min_length=5, max_length=1000)
    trigger: Literal[
        "periodic",
        "client_team_change",
        "ethical_wall_change",
        "portal_inactivity",
        "employee_change",
        "counsel_completion",
        "incident",
    ]
    expected_access_policy_version: int = Field(ge=0)


class VersionCommand(Command):
    expected_version: int = Field(ge=1)


class ReviewDecision(VersionCommand):
    grant_id: str = Field(min_length=1, max_length=36)
    decision: Literal["keep", "revoke"]
    reason: str = Field(min_length=5, max_length=1000)


class DatedRecord(BaseModel):
    @field_validator(
        "created_at",
        "finalized_at",
        "effective_from",
        "expires_at",
        mode="after",
        check_fields=False,
    )
    @classmethod
    def utc_dates(cls, value):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


class GrantSnapshot(DatedRecord):
    id: str
    record_version: int
    subject_type: Literal["membership", "team"]
    subject_id: str
    subject_label: str
    effective_from: datetime | None
    expires_at: datetime | None
    reason: str | None


class ScopeSnapshot(BaseModel):
    target_type: TargetType
    target_id: str
    target_title: str
    access_policy_version: int
    grants: list[GrantSnapshot]


class DecisionRecord(DatedRecord):
    grant_id: str
    decision: Literal["keep", "revoke"]
    reason: str
    reviewer_user_id: str
    reviewer_membership_id: str
    created_at: datetime


class CampaignRecord(DatedRecord):
    id: str
    title: str
    reason: str
    trigger: str
    status: Literal["open", "finalized"]
    version: int
    creator_user_id: str
    created_at: datetime
    finalized_at: datetime | None
    snapshot: ScopeSnapshot
    decisions: list[DecisionRecord]


class CampaignPage(BaseModel):
    campaigns: list[CampaignRecord]
    next_before_id: str | None


class TargetOption(BaseModel):
    id: str
    title: str


class TargetPage(BaseModel):
    targets: list[TargetOption]
    next_after_id: str | None
