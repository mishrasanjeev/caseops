"""Actor-derived preservation commands; no client-supplied approval identity."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HoldDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idempotency_key: str = Field(min_length=8, max_length=100)
    title: str = Field(min_length=3, max_length=255)
    authority_reference: str = Field(min_length=3, max_length=512)
    scope: Literal["company", "data_classes"]
    data_class_ids: list[str] = Field(default_factory=list, max_length=100)


class HoldVersionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    expected_updated_at: datetime


class HoldReleaseRequest(HoldVersionCommand):
    idempotency_key: str = Field(min_length=8, max_length=100)
    dry_run_id: str = Field(min_length=1, max_length=36)
    reason_reference: str = Field(min_length=3, max_length=512)


class HoldRecord(BaseModel):
    id: str
    title: str
    authority_reference: str
    status: Literal["draft", "active", "released", "cancelled"]
    scope: Literal["company", "data_classes"]
    data_class_ids: list[str]
    created_by_membership_id: str | None
    approved_by_membership_id: str | None
    updated_at: datetime
    activated_at: datetime | None
    released_at: datetime | None


class HoldListResponse(BaseModel):
    holds: list[HoldRecord]
    has_more: bool
    next_before_id: str | None = None


class HoldReleaseProposal(BaseModel):
    id: str
    hold_id: str
    request_hash: str
    expires_at: datetime
    requester_membership_id: str
    reason_reference: str
    dry_run_id: str


class HoldReleaseListResponse(BaseModel):
    proposals: list[HoldReleaseProposal]
    has_more: bool
    next_before_id: str | None = None
