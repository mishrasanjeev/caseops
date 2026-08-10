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


class IpHearingReminderPolicyRequest(BaseModel):
    offsets_hours: list[int] = Field(default_factory=list, max_length=12)
    channels: list[Literal["in_app", "email", "sms", "whatsapp"]] = Field(
        default_factory=lambda: ["email"], min_length=1, max_length=4
    )
    recipient_membership_ids: list[str] = Field(default_factory=list, max_length=50)
    escalation_membership_id: str | None = None
    date_reminder_local_time: time = time(18, 0)
    critical: bool = True

    @model_validator(mode="after")
    def validate_offsets_and_channels(self) -> IpHearingReminderPolicyRequest:
        if any(offset < 0 or offset > 24 * 365 for offset in self.offsets_hours):
            raise ValueError("reminder offsets must be between 0 and 8760 hours")
        if len(set(self.offsets_hours)) != len(self.offsets_hours):
            raise ValueError("reminder offsets must be unique")
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("reminder channels must be unique")
        if len(set(self.recipient_membership_ids)) != len(
            self.recipient_membership_ids
        ):
            raise ValueError("reminder recipients must be unique")
        return self


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
    location_text: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=2048, pattern=r"^https?://")
    attendee_membership_ids: list[str] = Field(default_factory=list, max_length=50)
    source: str = Field(default="manual", min_length=2, max_length=40)
    source_ref_type: str | None = Field(default=None, max_length=40)
    source_ref_id: str | None = Field(default=None, max_length=120)
    responsible_membership_id: str | None = None
    reminder_policy: IpHearingReminderPolicyRequest | None = None

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
        if len(set(self.attendee_membership_ids)) != len(self.attendee_membership_ids):
            raise ValueError("hearing attendees must be unique")
        return self


class IpSharedHearingUpdateRequest(BaseModel):
    docket_id: str
    hearing_on: date | None = None
    time_status: Literal["exact", "session", "time_not_published"] | None = None
    hearing_time: time | None = None
    session_label: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, min_length=3, max_length=64)
    forum_name: str | None = Field(default=None, min_length=2, max_length=255)
    judge_name: str | None = Field(default=None, min_length=2, max_length=255)
    purpose: str | None = Field(default=None, min_length=2, max_length=255)
    hearing_mode: Literal["physical", "virtual", "hybrid", "unknown"] | None = None
    location_text: str | None = Field(default=None, max_length=500)
    meeting_url: str | None = Field(default=None, max_length=2048, pattern=r"^https?://")
    attendee_membership_ids: list[str] | None = Field(default=None, max_length=50)
    status: Literal["scheduled", "completed", "adjourned", "cancelled"] | None = None
    outcome_note: str | None = Field(default=None, max_length=4000)
    responsible_membership_id: str | None = None
    reminder_policy: IpHearingReminderPolicyRequest | None = None

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> IpSharedHearingUpdateRequest:
        for field in (
            "hearing_on",
            "time_status",
            "timezone",
            "forum_name",
            "purpose",
            "hearing_mode",
            "status",
        ):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} may not be null")
        resulting_time_status = self.time_status
        if resulting_time_status == "exact" and "hearing_time" in self.model_fields_set:
            if self.hearing_time is None:
                raise ValueError("hearing_time is required when time_status is exact")
        if resulting_time_status in {"session", "time_not_published"} and self.hearing_time:
            raise ValueError("hearing_time is only allowed when time_status is exact")
        if resulting_time_status == "session" and not (self.session_label or "").strip():
            raise ValueError("session_label is required when time_status is session")
        if self.attendee_membership_ids is not None and len(
            set(self.attendee_membership_ids)
        ) != len(self.attendee_membership_ids):
            raise ValueError("hearing attendees must be unique")
        return self


class IpHearingReminderRecord(BaseModel):
    id: str
    recipient_membership_id: str | None
    channel: str
    scheduled_for: datetime
    schedule_generation: int
    status: str
    provider: str | None
    provider_message_id: str | None
    last_error: str | None
    attempts: int
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime


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
    location_text: str | None
    meeting_url: str | None
    attendee_membership_ids: list[str]
    source: str
    source_ref_type: str | None
    source_ref_id: str | None
    responsible_membership_id: str | None
    forum_name: str
    judge_name: str | None
    purpose: str
    status: str
    outcome_note: str | None
    reminder_policy: dict | None
    reminders: list[IpHearingReminderRecord] = Field(default_factory=list)
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
