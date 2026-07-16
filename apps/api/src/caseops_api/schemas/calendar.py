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
CalendarProviderLiteral = Literal["outlook", "google_calendar"]
CalendarConnectionStatusLiteral = Literal["connected", "revoked", "error"]
CalendarSyncSourceTypeLiteral = Literal["matter_hearing", "matter_deadline", "matter_task"]
CalendarEventSyncStatusLiteral = Literal[
    "pending",
    "synced",
    "failed",
    "retry_scheduled",
    "dead_letter",
    "deleted",
    "delete_pending",
]
CalendarSyncModeLiteral = Literal["manual_bounded"]
CalendarDurableAutomationLiteral = Literal[
    "blocked_pending_provider_approval",
    "caseops_to_outlook_hearings_ready",
]
CalendarNotificationDeliveryLiteral = Literal["wtd_5_3_foundation_available"]
OutlookConfigurationSourceLiteral = Literal["tenant_admin", "environment", "missing"]
OutlookReadinessItemStatusLiteral = Literal["passed", "failed", "blocked", "not_run"]
OutlookADP20ReadinessLiteral = Literal[
    "blocked_pending_admin_configuration",
    "ready_for_adp20_implementation",
]
CalendarEmailInvitationCandidateLiteral = Literal[
    "deferred_pending_review_queue",
    "review_queue_available",
]
CalendarConflictTypeLiteral = Literal["duplicate_provider_event_id"]
CalendarConflictSeverityLiteral = Literal["review"]
CalendarProviderEventCandidateStatusLiteral = Literal[
    "new",
    "conflict",
    "accepted",
    "rejected",
    "ignored",
    "failed",
]
CalendarProviderEventCandidateReviewActionLiteral = Literal[
    "accept",
    "reject",
    "ignore",
]
EmailInvitationCandidateStatusLiteral = Literal[
    "needs_review",
    "approved_created",
    "rejected",
    "duplicate_skipped",
]
EmailInvitationCandidateReviewActionLiteral = Literal["approve", "reject"]
EmailInvitationCandidateConfidenceLiteral = Literal["high", "medium", "low"]
NotificationRuleScopeTypeLiteral = Literal["company", "matter", "user"]
NotificationRuleEventTypeLiteral = Literal[
    "hearing_upcoming",
    "new_order_uploaded",
    "stay_status_changed",
]
NotificationChannelLiteral = Literal["in_app", "email", "sms", "whatsapp"]
NotificationRuleDurableDeliveryLiteral = Literal["wtd_5_3_foundation_available"]


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
    durable_automation: CalendarDurableAutomationLiteral = (
        "blocked_pending_provider_approval"
    )
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
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    next_attempt_at: datetime | None = None
    dead_letter_reason: str | None = None
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
    durable_automation: CalendarDurableAutomationLiteral = (
        "blocked_pending_provider_approval"
    )
    notification_delivery: CalendarNotificationDeliveryLiteral = (
        "wtd_5_3_foundation_available"
    )
    email_invitation_candidates: CalendarEmailInvitationCandidateLiteral = (
        "review_queue_available"
    )


class EmailInvitationCandidateRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    matter_title: str
    matter_code: str
    communication_id: str
    thread_key: str | None
    status: EmailInvitationCandidateStatusLiteral
    detected_title: str = Field(min_length=1, max_length=255)
    detected_start_at: datetime
    detected_end_at: datetime | None
    detected_location: str | None = Field(default=None, max_length=255)
    source_preview: str | None = Field(default=None, max_length=280)
    confidence_band: EmailInvitationCandidateConfidenceLiteral
    duplicate_of_candidate_id: str | None
    created_deadline_id: str | None
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class EmailInvitationCandidateListResponse(BaseModel):
    candidates: list[EmailInvitationCandidateRecord]
    pending_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)


class EmailInvitationCandidateExtractRequest(BaseModel):
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    limit: int = Field(default=50, ge=1, le=200)


class EmailInvitationCandidateExtractResponse(BaseModel):
    examined_count: int = Field(ge=0)
    created_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    candidates: list[EmailInvitationCandidateRecord]


class EmailInvitationCandidateReviewRequest(BaseModel):
    action: EmailInvitationCandidateReviewActionLiteral


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
    durable_automation: CalendarDurableAutomationLiteral = (
        "blocked_pending_provider_approval"
    )
    notification_delivery: CalendarNotificationDeliveryLiteral = (
        "wtd_5_3_foundation_available"
    )
    capabilities: CalendarSyncCapabilityStatus
    provider_config: list[CalendarProviderConfigStatus]
    conflict_summary: CalendarSyncConflictSummary
    conflict_candidates: list[CalendarSyncConflictCandidate]
    connections: list[CalendarConnectionRecord]
    syncs: list[CalendarEventSyncRecord]


class CalendarProviderEventCandidateRecord(BaseModel):
    id: str
    company_id: str
    provider: CalendarProviderLiteral
    provider_event_id: str
    i_cal_uid: str | None = None
    title: str
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = None
    organizer_display: str | None = None
    provider_status: str | None = None
    suggested_matter_id: str | None = None
    linked_matter_id: str | None = None
    linked_hearing_id: str | None = None
    confidence: float | None = None
    status: CalendarProviderEventCandidateStatusLiteral
    conflict_reason: str | None = None
    provenance: dict | None = None
    sync_history: list[dict] = Field(default_factory=list)
    reviewed_by_membership_id: str | None = None
    reviewed_at: datetime | None = None
    last_error_redacted: str | None = None
    created_at: datetime
    updated_at: datetime


class CalendarProviderEventCandidateListResponse(BaseModel):
    candidates: list[CalendarProviderEventCandidateRecord]
    pending_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)


class CalendarProviderEventCandidateCreateRequest(BaseModel):
    provider: CalendarProviderLiteral
    provider_event_id: str = Field(min_length=1, max_length=255)
    i_cal_uid: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    starts_at: datetime
    ends_at: datetime | None = None
    location: str | None = Field(default=None, max_length=500)
    organizer_display: str | None = Field(default=None, max_length=255)
    provider_status: str | None = Field(default=None, max_length=40)
    suggested_matter_id: str | None = Field(default=None, max_length=36)


class CalendarProviderEventCandidateReviewRequest(BaseModel):
    action: CalendarProviderEventCandidateReviewActionLiteral
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    force_overwrite_locked: bool = False


class CalendarProviderEventCandidateReviewResponse(BaseModel):
    candidate: CalendarProviderEventCandidateRecord
    hearing_id: str | None = None


class OutlookConfigurationItemStatus(BaseModel):
    name: str
    configured: bool


class OutlookApprovalItemStatus(BaseModel):
    key: str
    label: str
    approved: bool


class OutlookTenantConfigurationResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    configured: bool
    config_source: OutlookConfigurationSourceLiteral
    enabled: bool
    required_config: list[OutlookConfigurationItemStatus]
    required_approvals: list[OutlookApprovalItemStatus]
    approved_scopes: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    connection_count: int = Field(ge=0)
    connected_account_count: int = Field(ge=0)
    last_test_status: OutlookReadinessItemStatusLiteral = "not_run"
    last_tested_at: datetime | None = None
    last_error_redacted: str | None = None
    adp20_readiness: OutlookADP20ReadinessLiteral


class OutlookTenantConfigurationUpdateRequest(BaseModel):
    client_id: str | None = Field(default=None, max_length=255)
    client_secret: str | None = Field(default=None, max_length=4096)
    tenant_id: str | None = Field(default=None, max_length=255)
    redirect_uri: str | None = Field(default=None, max_length=500)
    scopes: list[str] | None = None
    oauth_consent_model_approved: bool = False
    scopes_approved: bool = False
    durable_runbook_approved: bool = False
    rollback_approved: bool = False
    redaction_rules_approved: bool = False
    enabled: bool = True

    @field_validator(
        "client_id",
        "client_secret",
        "tenant_id",
        "redirect_uri",
        mode="before",
    )
    @classmethod
    def blank_string_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        return value


class OutlookReadinessCheckResult(BaseModel):
    key: str
    label: str
    status: OutlookReadinessItemStatusLiteral
    detail: str | None = None


class OutlookReadinessTestResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    status: OutlookReadinessItemStatusLiteral
    checks: list[OutlookReadinessCheckResult]
    adp20_readiness: OutlookADP20ReadinessLiteral
    tested_at: datetime


class OutlookDurableSyncReplayRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)


class OutlookDurableSyncReplayResponse(BaseModel):
    provider: CalendarProviderLiteral = "outlook"
    status: Literal["processed", "blocked"]
    adp20_readiness: OutlookADP20ReadinessLiteral
    missing_config_names: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    examined: int = Field(ge=0)
    synced: int = Field(ge=0)
    failed: int = Field(ge=0)
    retry_scheduled: int = Field(ge=0)
    dead_lettered: int = Field(ge=0)
    skipped: int = Field(ge=0)
    replayed: int = Field(ge=0)


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
    durable_automation: CalendarDurableAutomationLiteral = (
        "blocked_pending_provider_approval"
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
    durable_delivery: NotificationRuleDurableDeliveryLiteral = (
        "wtd_5_3_foundation_available"
    )
    created_at: datetime
    updated_at: datetime


class NotificationRuleListResponse(BaseModel):
    durable_delivery: NotificationRuleDurableDeliveryLiteral = (
        "wtd_5_3_foundation_available"
    )
    rules: list[NotificationRuleRecord]
