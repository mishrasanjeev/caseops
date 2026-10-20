from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ActivityReportDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActivityMetrics(ActivityReportDTO):
    users_added: int
    matters_created: int
    tasks_created: int
    tasks_completed: int
    hearings_created: int
    documents_uploaded: int
    notices_received: int
    notices_sent: int
    time_entries: int
    billable_hours: float
    invoices_issued: int
    invoiced_amount_minor: int
    payments_received: int
    collections_minor: int
    audit_events: int
    failed_or_denied_events: int


class ActivitySnapshot(ActivityReportDTO):
    active_users: int
    active_matters: int
    open_tasks: int
    overdue_tasks: int
    upcoming_hearings_30d: int
    documents_total: int
    storage_bytes: int
    open_notices: int
    overdue_notice_replies: int
    open_invoices: int
    outstanding_amount_minor: int


class ActivityPeriods(ActivityReportDTO):
    day: ActivityMetrics
    week: ActivityMetrics
    month: ActivityMetrics
    till_date: ActivityMetrics


class ActivityAccount(ActivityReportDTO):
    company_id: str = Field(min_length=1, max_length=36)
    name: str
    company_type: str
    is_active: bool
    last_meaningful_activity_at: AwareDatetime | None
    usage_status: Literal["recent", "inactive", "unknown"]
    current: ActivitySnapshot
    periods: ActivityPeriods

    @model_validator(mode="after")
    def known_usage_has_evidence(self) -> ActivityAccount:
        if self.usage_status != "unknown" and self.last_meaningful_activity_at is None:
            raise ValueError("Known engagement requires a recorded human-activity timestamp.")
        return self


class ActivitySegment(ActivityReportDTO):
    company_count: int = Field(ge=0)
    company_names: list[str]
    periods: ActivityPeriods
    accounts: list[ActivityAccount]


class ActivitySegments(ActivityReportDTO):
    law_firms: ActivitySegment
    general_counsels: ActivitySegment
    solo_lawyers: ActivitySegment
    other: ActivitySegment


class ActivityPeriodBounds(ActivityReportDTO):
    start_date: date | None
    end_date: date


class ActivityReportingPeriods(ActivityReportDTO):
    day: ActivityPeriodBounds
    week: ActivityPeriodBounds
    month: ActivityPeriodBounds
    till_date: ActivityPeriodBounds


class ActivityWindow(ActivityReportDTO):
    days: Literal[30]
    cutoff: AwareDatetime
    as_of: AwareDatetime
    time_zone: Literal["Asia/Kolkata"]
    basis: Literal["successful_human_audit_events"]
    limitations: str

    @model_validator(mode="after")
    def window_is_rolling_thirty_days(self) -> ActivityWindow:
        if self.as_of - self.cutoff != timedelta(days=30):
            raise ValueError("The engagement window must cover thirty elapsed days.")
        return self


class ActivityReportResponse(ActivityReportDTO):
    generated_at: AwareDatetime
    account_scope: Literal["all_registered_accounts", "operational_email"]
    excluded_account_count: int = Field(ge=0)
    activity_window: ActivityWindow
    reporting_periods: ActivityReportingPeriods
    segments: ActivitySegments

    @model_validator(mode="after")
    def usage_agrees_with_report_window(self) -> ActivityReportResponse:
        if self.generated_at != self.activity_window.as_of:
            raise ValueError("The engagement window must end at report generation.")
        if self.account_scope == "all_registered_accounts" and self.excluded_account_count:
            raise ValueError("All-account scope cannot silently exclude registered accounts.")
        for name in ActivitySegments.model_fields:
            segment = getattr(self.segments, name)
            for account in segment.accounts:
                last = account.last_meaningful_activity_at
                if last is None:
                    continue
                if last > self.activity_window.as_of:
                    raise ValueError("Future activity cannot establish engagement.")
                if account.usage_status == "recent" and last < self.activity_window.cutoff:
                    raise ValueError("Recent engagement must fall inside the rolling window.")
                if account.usage_status == "inactive" and last >= self.activity_window.cutoff:
                    raise ValueError("Recorded recent activity cannot be classified inactive.")
        return self
