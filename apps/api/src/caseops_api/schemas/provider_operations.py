from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

ProviderOperationKind = Literal[
    "calendar_sync",
    "notification_delivery",
    "case_tracking_poll",
    "mailbox_message_import",
    "mailbox_webhook",
]
ProviderOperatorState = Literal["open", "ignored", "resolved"]
ProviderOperationAction = Literal["replay", "ignore", "mark_resolved"]
ProviderReadinessState = Literal[
    "blocked_missing_config",
    "blocked_pending_admin_approval",
    "foundation_available",
    "ready",
]


class ProviderOperationRecord(BaseModel):
    id: str
    job_kind: ProviderOperationKind
    provider: str
    company_id: str
    matter_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    provider_item_ref: str | None = None
    status: str
    operator_state: ProviderOperatorState = "open"
    error_redacted: str | None = None
    dead_letter_reason: str | None = None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    next_attempt_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    replay_available: bool
    ignore_available: bool
    mark_resolved_available: bool
    notes: list[str] = Field(default_factory=list)


class ProviderOperationListResponse(BaseModel):
    operations: list[ProviderOperationRecord]
    open_count: int = Field(ge=0)
    ignored_count: int = Field(ge=0)
    resolved_count: int = Field(ge=0)
    replayable_count: int = Field(ge=0)


class ProviderOperationActionRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=500)

    @field_validator("reason", mode="before")
    @classmethod
    def strip_reason(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ProviderOperationActionResponse(BaseModel):
    action: ProviderOperationAction
    changed: bool
    message: str
    operation: ProviderOperationRecord


class ProviderReadinessRecord(BaseModel):
    provider: str
    display_name: str
    adp_slice: str
    state: ProviderReadinessState
    configured: bool
    enabled: bool
    external_calls_enabled: bool = False
    durable_workflow_available: bool = False
    required_config_names: list[str] = Field(default_factory=list)
    missing_config_names: list[str] = Field(default_factory=list)
    required_approval_keys: list[str] = Field(default_factory=list)
    missing_approval_keys: list[str] = Field(default_factory=list)
    endpoint_paths: list[str] = Field(default_factory=list)
    idempotency_fields: list[str] = Field(default_factory=list)
    change_detection_fields: list[str] = Field(default_factory=list)
    review_queue: str | None = None
    retry_dead_letter: str
    limitations: list[str] = Field(default_factory=list)


class ProviderReadinessListResponse(BaseModel):
    providers: list[ProviderReadinessRecord]
