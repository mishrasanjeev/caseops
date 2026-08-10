from __future__ import annotations

from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class SharedWorkOwnerContract(BaseModel):
    owner: str
    table_name: str
    classification: Literal["EXTEND", "LINK"]
    canonical_writer: str
    ip_target_column: str | None
    compatibility_path: str


class SharedWorkFoundationContract(BaseModel):
    contract_version: str
    migration_heads: list[str]
    target_rule: str
    mixed_revision_policy: str
    one_writer_policy: str
    forbidden_duplicates: list[str]
    owners: list[SharedWorkOwnerContract]


class SharedWorkOwnerReconciliation(BaseModel):
    owner: str
    table_name: str
    row_count: int
    ip_target_rows: int
    legacy_tail_rows: int
    invalid_target_rows: int
    tenant_mismatch_rows: int
    ready: bool


class SharedWorkReconciliationReport(BaseModel):
    contract_version: str
    company_id: str
    release_blocking: bool
    ready: bool
    owners: list[SharedWorkOwnerReconciliation]
    calendar_source_types: list[str]
    notification_ip_target_rows: int
    notification_tenant_mismatch_rows: int


class IpSharedTaskCreateRequest(BaseModel):
    docket_id: str
    title: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_membership_id: str | None = None
    due_on: date | None = None
    status: Literal["todo", "in_progress", "completed", "cancelled"] = "todo"
    priority: Literal["low", "medium", "high", "urgent"] = "medium"


class IpSharedTaskUpdateRequest(BaseModel):
    docket_id: str
    title: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    owner_membership_id: str | None = None
    due_on: date | None = None
    status: Literal["todo", "in_progress", "completed", "cancelled"] | None = None
    priority: Literal["low", "medium", "high", "urgent"] | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> IpSharedTaskUpdateRequest:
        for field in ("title", "status", "priority"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class IpSharedTaskRecord(BaseModel):
    id: str
    company_id: str
    target_type: Literal["ip_docket"] = "ip_docket"
    target_id: str
    ip_docket_id: str
    created_by_membership_id: str | None
    owner_membership_id: str | None
    title: str
    description: str | None
    due_on: date | None
    status: str
    priority: str
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IpSharedTaskListResponse(BaseModel):
    docket_id: str
    tasks: list[IpSharedTaskRecord]


class IpSharedHearingCreateRequest(BaseModel):
    docket_id: str
    hearing_on: date
    forum_name: str = Field(min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    purpose: str = Field(min_length=2, max_length=255)
    status: Literal["scheduled", "completed", "adjourned", "cancelled"] = "scheduled"
    outcome_note: str | None = Field(default=None, max_length=4000)
    time_status: Literal["exact", "session", "time_not_published"] = "time_not_published"
    hearing_time: time | None = None
    session_label: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="Asia/Kolkata", min_length=3, max_length=64)
    hearing_mode: Literal["physical", "virtual", "hybrid", "unknown"] = "unknown"
    source: str = Field(default="manual", min_length=2, max_length=40)
    source_ref_type: str | None = Field(default=None, max_length=40)
    source_ref_id: str | None = Field(default=None, max_length=120)
    responsible_membership_id: str | None = None

    @model_validator(mode="after")
    def validate_precision(self) -> IpSharedHearingCreateRequest:
        if self.time_status == "exact" and self.hearing_time is None:
            raise ValueError("hearing_time is required when time_status is exact")
        if self.time_status != "exact" and self.hearing_time is not None:
            raise ValueError("hearing_time is only allowed when time_status is exact")
        if self.time_status == "session" and not (self.session_label or "").strip():
            raise ValueError("session_label is required when time_status is session")
        if self.time_status != "session" and self.session_label is not None:
            raise ValueError("session_label is only allowed when time_status is session")
        return self


class IpSharedHearingUpdateRequest(BaseModel):
    docket_id: str
    hearing_on: date | None = None
    status: Literal["scheduled", "completed", "adjourned", "cancelled"] | None = None
    outcome_note: str | None = Field(default=None, max_length=4000)
    responsible_membership_id: str | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> IpSharedHearingUpdateRequest:
        for field in ("hearing_on", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class IpSharedHearingRecord(BaseModel):
    id: str
    company_id: str
    target_type: Literal["ip_docket"] = "ip_docket"
    target_id: str
    ip_docket_id: str
    hearing_on: date
    time_status: str
    hearing_time: time | None
    session_label: str | None
    timezone: str
    hearing_mode: str | None
    source: str
    source_ref_type: str | None
    source_ref_id: str | None
    responsible_membership_id: str | None
    forum_name: str
    judge_name: str | None
    purpose: str
    status: str
    outcome_note: str | None
    created_at: datetime


class IpSharedHearingListResponse(BaseModel):
    docket_id: str
    hearings: list[IpSharedHearingRecord]


class IpOperationalDeadlineCreateRequest(BaseModel):
    docket_id: str
    source: Literal["custom", "hearing", "followup", "intake"] = "custom"
    kind: str = Field(default="manual", min_length=1, max_length=64)
    title: str = Field(min_length=2, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    due_on: date
    assignee_membership_id: str | None = None


class IpOperationalDeadlineUpdateRequest(BaseModel):
    docket_id: str
    title: str | None = Field(default=None, min_length=2, max_length=255)
    notes: str | None = Field(default=None, max_length=4000)
    due_on: date | None = None
    status: Literal["open", "done", "cancelled", "missed"] | None = None
    assignee_membership_id: str | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> IpOperationalDeadlineUpdateRequest:
        for field in ("title", "due_on", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        return self


class IpOperationalDeadlineRecord(BaseModel):
    id: str
    company_id: str
    target_type: Literal["ip_docket"] = "ip_docket"
    target_id: str
    ip_docket_id: str
    source: str
    kind: str
    title: str
    notes: str | None
    due_on: date
    status: str
    assignee_membership_id: str | None
    source_ref_type: str | None
    source_ref_id: str | None
    created_by_membership_id: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IpOperationalDeadlineListResponse(BaseModel):
    docket_id: str
    deadlines: list[IpOperationalDeadlineRecord]
