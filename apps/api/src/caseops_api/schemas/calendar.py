"""Phase B / J08 / M08 — unified calendar response shape.

The cockpit's ``/app/calendar`` page asks for one merged view of:

- ``MatterHearing`` (next hearing date)
- ``MatterTask`` with a ``due_on``
- ``MatterDeadline`` (drafts, contracts, intake follow-ups all funnel
  here per the docstring on the model)

Returning a flat ``CalendarEventRecord[]`` instead of a per-source
nested response keeps the UI a simple grid render and lets the date
filter / kind filter / search box be pure-client.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CalendarEventKind = Literal["hearing", "task", "deadline"]
CalendarProviderLiteral = Literal["outlook"]
CalendarConnectionStatusLiteral = Literal["connected", "revoked", "error"]
CalendarSyncSourceTypeLiteral = Literal["matter_hearing", "matter_deadline", "matter_task"]
CalendarEventSyncStatusLiteral = Literal["pending", "synced", "failed", "deleted"]
CalendarSyncModeLiteral = Literal["manual_bounded"]
CalendarNotificationDeliveryLiteral = Literal["pending_wtd_5_3"]
CalendarEmailInvitationCandidateLiteral = Literal["deferred_pending_review_queue"]
CalendarConflictTypeLiteral = Literal["duplicate_provider_event_id"]
CalendarConflictSeverityLiteral = Literal["review"]
NotificationRuleScopeTypeLiteral = Literal["company", "matter", "user"]
NotificationRuleEventTypeLiteral = Literal[
    "hearing_upcoming",
    "new_order_uploaded",
    "stay_status_changed",
]
NotificationChannelLiteral = Literal["in_app", "email", "sms", "whatsapp"]


class CalendarEventRecord(BaseModel):
    """One row on the calendar — same shape regardless of source."""

    id: str = Field(description="Source row's primary key prefixed by kind.")
    kind: CalendarEventKind
    occurs_on: date = Field(description="ISO yyyy-mm-dd. All events are date-granular.")
    title: str = Field(min_length=1, max_length=400)
    matter_id: str
    matter_title: str
    matter_code: str
    # ``status`` is the source row's status string verbatim (hearing
    # status, task status, deadline status). Useful for grey-ing
    # completed items in the grid without another round-trip.
    status: str | None = None
    # Free-text disambiguation for multiple events on the same matter
    # in the same day. e.g. "Bombay HC, Justice Patel" for a hearing,
    # "High" for a task priority.
    detail: str | None = None


class CalendarEventListResponse(BaseModel):
    range_from: date
    range_to: date
    events: list[CalendarEventRecord]


class CalendarConnectionRecord(BaseModel):
    id: str
    company_id: str
    membership_id: str
    provider: CalendarProviderLiteral
    provider_account_id: str | None
    display_email: str | None
    status: CalendarConnectionStatusLiteral
    scopes: list[str] = Field(default_factory=list)
    connected_at: datetime | None
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CalendarConnectionListResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    provider_available: bool
    unavailable_reason: str | None = None
    durable_automation: Literal["blocked_pending_temporal"] = "blocked_pending_temporal"
    connections: list[CalendarConnectionRecord]


class CalendarConnectionStartResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    provider_available: bool
    auth_url: str | None = None
    unavailable_reason: str | None = None


class CalendarConnectionCallbackResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    connected: bool
    connection: CalendarConnectionRecord


class CalendarEventSyncRecord(BaseModel):
    id: str
    company_id: str
    calendar_connection_id: str
    source_type: CalendarSyncSourceTypeLiteral
    source_id: str
    provider_event_id: str | None
    sync_status: CalendarEventSyncStatusLiteral
    last_error: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CalendarEventSyncResponse(BaseModel):
    sync: CalendarEventSyncRecord


class CalendarProviderConfigStatus(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    configured: bool
    missing_config_names: list[str] = Field(default_factory=list)


class CalendarSyncCapabilityStatus(BaseModel):
    sync_mode: CalendarSyncModeLiteral = "manual_bounded"
    manual_sync_available: bool
    durable_automation: Literal["blocked_pending_temporal"] = "blocked_pending_temporal"
    notification_delivery: CalendarNotificationDeliveryLiteral = "pending_wtd_5_3"
    email_invitation_candidates: CalendarEmailInvitationCandidateLiteral = (
        "deferred_pending_review_queue"
    )


class CalendarSyncConflictCandidate(BaseModel):
    id: str
    conflict_type: CalendarConflictTypeLiteral
    severity: CalendarConflictSeverityLiteral = "review"
    provider: CalendarProviderLiteral = "outlook"
    calendar_connection_id: str
    provider_event_id: str
    duplicate_count: int = Field(ge=2)
    source_ids: list[str]
    source_types: list[CalendarSyncSourceTypeLiteral]
    sync_ids: list[str]
    message: str


class CalendarSyncConflictSummary(BaseModel):
    has_conflicts: bool
    candidate_count: int = Field(ge=0)
    duplicate_provider_event_count: int = Field(ge=0)
    changed_event_candidate_count: int = Field(default=0, ge=0)
    changed_event_detection: Literal["unsupported_no_provider_snapshot"] = (
        "unsupported_no_provider_snapshot"
    )


class CalendarSyncStatusResponse(BaseModel):
    provider_available: bool
    durable_automation: Literal["blocked_pending_temporal"] = "blocked_pending_temporal"
    notification_delivery: CalendarNotificationDeliveryLiteral = "pending_wtd_5_3"
    capabilities: CalendarSyncCapabilityStatus
    provider_config: list[CalendarProviderConfigStatus]
    conflict_summary: CalendarSyncConflictSummary
    conflict_candidates: list[CalendarSyncConflictCandidate]
    connections: list[CalendarConnectionRecord]
    syncs: list[CalendarEventSyncRecord]


# BUG-039 (Hari 2026-05-09) — bounded manual bulk sync of the
# caller's visible hearings to their connected Outlook calendar. No
# durable background automation is implied; the caller pulls a
# date range, the backend loops over visible hearings, returns a
# structured summary. Tasks/deadlines are accepted in the request
# but the v1 adapter does not yet upsert them — they surface as
# `skipped` with `skip_reason="source_type_unsupported"`.
class OutlookBulkSyncRequest(BaseModel):
    range_from: date = Field(alias="from")
    range_to: date = Field(alias="to")
    matter_id: str | None = Field(
        default=None, min_length=36, max_length=36
    )
    source_types: list[CalendarSyncSourceTypeLiteral] | None = Field(
        default=None,
        description=(
            "Optional list of source types to include. v1 only "
            "actually syncs `matter_hearing`; other entries are "
            "echoed back as `skipped` with `skip_reason=\"source_"
            "type_unsupported\"`. Default behaviour is "
            "[\"matter_hearing\"]."
        ),
    )
    limit: int = Field(default=50, ge=1, le=200)

    model_config = ConfigDict(populate_by_name=True)


class OutlookBulkSyncItem(BaseModel):
    """One row of the bulk-sync summary. ``sync_status="synced"``
    rows are split between ``created`` and ``updated`` counters in
    the parent response based on whether a CalendarEventSync row
    existed before the batch ran.
    """

    source_type: CalendarSyncSourceTypeLiteral
    source_id: str
    sync_status: CalendarEventSyncStatusLiteral | Literal["skipped"]
    matter_id: str | None
    matter_title: str | None
    provider_event_id: str | None = None
    last_error: str | None = None
    skip_reason: str | None = None


class OutlookBulkSyncResponse(BaseModel):
    """Structured summary for the manual bulk sync. ``examined`` is
    the count of source rows the backend actually loaded (after
    tenant + visibility + matter filters); ``skipped`` includes
    both unsupported source types and cases where the row was
    out-of-range or otherwise not eligible. ``durable_automation``
    explicitly notes that this endpoint is the only sync path —
    Temporal-backed background sync remains blocked.
    """

    examined: int
    created: int
    updated: int
    failed: int
    skipped: int
    items: list[OutlookBulkSyncItem]
    durable_automation: Literal["blocked_pending_temporal"] = (
        "blocked_pending_temporal"
    )


class NotificationRuleBase(BaseModel):
    scope_type: NotificationRuleScopeTypeLiteral
    scope_id: str | None = None
    event_type: NotificationRuleEventTypeLiteral
    channels: list[NotificationChannelLiteral] = Field(default_factory=lambda: ["in_app"])
    offset_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    enabled: bool = True

    @field_validator("scope_id", mode="before")
    @classmethod
    def blank_scope_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value

    @model_validator(mode="after")
    def validate_scope(self) -> NotificationRuleBase:
        if self.scope_type in {"matter", "user"} and not self.scope_id:
            raise ValueError("matter and user scoped rules require scope_id.")
        if self.scope_type == "company" and self.scope_id:
            raise ValueError("company scoped rules must not set scope_id.")
        if not self.channels:
            raise ValueError("notification rules require at least one channel.")
        return self


class NotificationRuleCreateRequest(NotificationRuleBase):
    pass


class NotificationRuleUpdateRequest(BaseModel):
    scope_type: NotificationRuleScopeTypeLiteral | None = None
    scope_id: str | None = None
    event_type: NotificationRuleEventTypeLiteral | None = None
    channels: list[NotificationChannelLiteral] | None = None
    offset_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 30)
    enabled: bool | None = None

    @field_validator("scope_id", mode="before")
    @classmethod
    def blank_scope_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class NotificationRuleRecord(BaseModel):
    id: str
    company_id: str
    scope_type: NotificationRuleScopeTypeLiteral
    scope_id: str | None
    event_type: NotificationRuleEventTypeLiteral
    channels: list[NotificationChannelLiteral]
    offset_minutes: int | None
    enabled: bool
    created_by_membership_id: str | None
    durable_delivery: Literal["blocked_pending_temporal"] = "blocked_pending_temporal"
    created_at: datetime
    updated_at: datetime


class NotificationRuleListResponse(BaseModel):
    durable_delivery: Literal["blocked_pending_temporal"] = "blocked_pending_temporal"
    rules: list[NotificationRuleRecord]
