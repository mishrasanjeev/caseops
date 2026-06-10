from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

NotificationChannelLiteral = Literal["in_app", "email", "sms", "whatsapp"]
NotificationDigestFrequencyLiteral = Literal["immediate", "daily", "weekly", "disabled"]
NotificationEventCategoryLiteral = Literal[
    "hearing_updates",
    "tracked_case_changes",
    "compliance_deadlines",
    "billing_credit_warnings",
    "connector_failures",
    "document_processing_failures",
    "provider_operation_failures",
]

DEFAULT_EVENT_CATEGORIES: list[NotificationEventCategoryLiteral] = [
    "hearing_updates",
    "tracked_case_changes",
    "compliance_deadlines",
    "billing_credit_warnings",
    "connector_failures",
    "document_processing_failures",
    "provider_operation_failures",
]


class NotificationChannelPreference(BaseModel):
    enabled: bool = True
    provider_configured: bool = False
    external_delivery_enabled: bool = False


class NotificationQuietHours(BaseModel):
    enabled: bool = False
    start: str | None = Field(default=None, max_length=5)
    end: str | None = Field(default=None, max_length=5)
    timezone: str = Field(default="Asia/Kolkata", max_length=80)


class NotificationPreferenceRecord(BaseModel):
    id: str
    company_id: str
    membership_id: str | None = None
    scope: Literal["tenant", "user"]
    channels: dict[NotificationChannelLiteral, NotificationChannelPreference]
    event_categories: dict[NotificationEventCategoryLiteral, bool]
    digest_frequency: NotificationDigestFrequencyLiteral
    quiet_hours: NotificationQuietHours
    escalation_rules: list[dict] = Field(default_factory=list)
    opt_out_categories: list[NotificationEventCategoryLiteral] = Field(default_factory=list)
    external_delivery_policy: str = "disabled_until_configured"
    created_at: datetime
    updated_at: datetime


class NotificationPreferenceUpdateRequest(BaseModel):
    channels: dict[NotificationChannelLiteral, bool] | None = None
    event_categories: dict[NotificationEventCategoryLiteral, bool] | None = None
    digest_frequency: NotificationDigestFrequencyLiteral | None = None
    quiet_hours: NotificationQuietHours | None = None
    escalation_rules: list[dict] | None = None
    opt_out_categories: list[NotificationEventCategoryLiteral] | None = None


class NotificationPreferenceResponse(BaseModel):
    tenant: NotificationPreferenceRecord
    user: NotificationPreferenceRecord
    external_delivery_enabled: bool = False
    provider_configured: dict[NotificationChannelLiteral, bool]
