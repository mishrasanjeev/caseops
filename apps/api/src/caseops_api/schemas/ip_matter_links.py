from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

IpMatterRelationRole = Literal[
    "operational",
    "litigation",
    "advisory",
    "appeal",
    "enforcement",
    "billing",
    "other",
]


class IpMatterLinkCreateRequest(BaseModel):
    matter_id: str = Field(min_length=36, max_length=36)
    relation_role: IpMatterRelationRole
    effective_from: datetime | None = None
    source_reference: str | None = Field(default=None, max_length=512)
    reason: str = Field(min_length=8, max_length=2000)
    expected_docket_updated_at: datetime


class IpMatterLinkRetireRequest(BaseModel):
    retired_at: datetime | None = None
    reason: str = Field(min_length=8, max_length=2000)
    expected_link_updated_at: datetime
    expected_docket_updated_at: datetime


class IpMatterLifecycleRecord(BaseModel):
    matter_id: str
    matter_code: str
    matter_title: str
    matter_status: str
    matter_is_active: bool
    docket_id: str
    docket_title: str
    docket_status: str
    docket_is_active: bool


class IpMatterLinkRecord(BaseModel):
    id: str
    company_id: str
    docket_id: str
    matter_id: str
    relation_role: IpMatterRelationRole
    effective_from: datetime
    retired_at: datetime | None
    source: Literal["manual", "system", "migration"]
    source_reference: str | None
    reason: str
    retirement_reason: str | None
    created_by_membership_id: str | None
    retired_by_membership_id: str | None
    access_mismatch_warning: bool
    lifecycle: IpMatterLifecycleRecord
    created_at: datetime
    updated_at: datetime


class IpMatterLinkListResponse(BaseModel):
    links: list[IpMatterLinkRecord]
    count: int
    active_count: int


class IpMatterLinkRetireResponse(BaseModel):
    link: IpMatterLinkRecord
    operational_pointer_cleared: bool


class MatterIpLinkListResponse(IpMatterLinkListResponse):
    matter_id: str


class IpDocketMatterLinkListResponse(IpMatterLinkListResponse):
    docket_id: str
