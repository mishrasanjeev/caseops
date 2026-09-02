from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ProviderOperationKind = Literal[
    "calendar_sync",
    "notification_delivery",
    "case_tracking_poll",
    "case_tracking_record",
    "mailbox_message_import",
    "mailbox_webhook",
    "drive_file_candidate",
    "calendar_event_candidate",
    "inbound_email_event",
    "connector_health",
    "ip_registry_sync",
    "ip_journal_ingestion",
    "source_link_health",
]
ProviderOperatorState = Literal["open", "ignored", "resolved"]
ProviderOperationAction = Literal["replay", "ignore", "mark_resolved"]
ProviderReadinessState = Literal[
    "blocked_missing_config",
    "blocked_pending_admin_approval",
    "foundation_available",
    "ready",
]
ProviderAdapterDomain = Literal[
    "court_tracking",
    "ip_office_registry",
    "international_trademark_registry",
    "legal_research",
]
ProviderAdapterStatus = Literal[
    "implemented",
    "implemented_default_off",
    "blocked_pending_provider_contract",
]
ProviderCommercialTermsStatus = Literal[
    "support_matrix_governed",
    "runtime_metadata_governed",
    "not_approved",
]
ProviderAdapterCapability = Literal[
    "search",
    "record_fetch",
    "document_fetch",
    "health",
    "attribution",
    "cost",
    "capability",
    "operations",
    "replay",
]


class ProviderAdapterLegalCoverageRecord(BaseModel):
    jurisdiction: str
    office: str
    asset_types: list[str] = Field(default_factory=list)
    identifier_types: list[str] = Field(default_factory=list)
    register_fields: list[str] = Field(default_factory=list)
    document_types: list[str] = Field(default_factory=list)
    coverage_status: Literal["verified", "partial", "unverified"]
    evidence_ref: str | None = None


class ProviderAdapterContractRecord(BaseModel):
    provider: str
    display_name: str
    domain: ProviderAdapterDomain
    adapter_status: ProviderAdapterStatus
    commercial_terms_status: ProviderCommercialTermsStatus
    required_capabilities: list[ProviderAdapterCapability]
    implemented_capabilities: list[ProviderAdapterCapability]
    attribution_label: str
    cost_categories: list[str] = Field(default_factory=list)
    health_path: str | None = None
    support_matrix_path: str | None = None
    operations_path: str
    endpoint_paths: list[str] = Field(default_factory=list)
    legal_coverage: list[ProviderAdapterLegalCoverageRecord] = Field(default_factory=list)
    activation_blockers: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    attribution_url: str | None = None
    terms_url: str | None = None
    pricing_evidence_url: str | None = None
    required_config_names: list[str] = Field(default_factory=list)
    kill_switch_name: str | None = None
    retention_policy: str | None = None


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
    correlation_ref: str | None = None
    response_class: Literal[
        "success",
        "no_change",
        "verified_cached",
        "timeout",
        "authentication",
        "rate_limit",
        "parse_error",
        "provider_outage",
        "url_failure",
        "removed_document",
        "changed_content",
        "unsupported_access",
        "configuration",
        "policy",
        "unknown",
    ] = "unknown"
    last_attempted_at: datetime | None = None
    last_successful_at: datetime | None = None
    last_good_at: datetime | None = None
    next_scheduled_at: datetime | None = None
    freshness_state: Literal[
        "fresh",
        "stale",
        "never_succeeded",
        "disabled",
        "blocked",
        "unknown",
    ] = "unknown"
    records_affected: int | None = Field(default=None, ge=0)
    estimated_cost_minor: int = Field(default=0, ge=0)
    estimated_cost_currency: str = "INR"
    estimated_cost_basis: str = "no_external_call"
    retryable: bool = False
    quarantined: bool = False
    replay_available: bool
    ignore_available: bool
    mark_resolved_available: bool
    manual_reconciliation_required: bool = False
    automatic_replay_block_code: str | None = None
    notes: list[str] = Field(default_factory=list)


class ProviderOperationListResponse(BaseModel):
    operations: list[ProviderOperationRecord]
    returned_count: int = Field(ge=0)
    page_limit: int = Field(ge=1, le=200)
    has_more: bool
    counts_scope: Literal["page"] = "page"
    sort_order: Literal["updated_at_desc_id_desc_source_desc"] = (
        "updated_at_desc_id_desc_source_desc"
    )
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


class ProviderIncidentResolutionRequest(BaseModel):
    root_cause: str = Field(min_length=8, max_length=1000)
    prevention: str = Field(min_length=8, max_length=1000)
    canary_evidence: str = Field(min_length=8, max_length=1000)

    @field_validator("root_cause", "prevention", "canary_evidence", mode="before")
    @classmethod
    def strip_incident_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ProviderOperationReplayPreviewRequest(BaseModel):
    operation_ids: list[str] = Field(min_length=1, max_length=25)

    @field_validator("operation_ids")
    @classmethod
    def unique_operation_ids(cls, value: list[str]) -> list[str]:
        normalized = [item.strip() for item in value]
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("operation_ids must be non-empty and unique")
        return normalized


class ProviderOperationReplayPreviewItem(BaseModel):
    operation: ProviderOperationRecord
    expected_updated_at: datetime
    estimated_cost_minor: int = Field(ge=0)
    currency: str = "INR"
    cost_basis: str


class ProviderOperationReplayPreviewResponse(BaseModel):
    preview_token: str
    expires_at: datetime
    operation_count: int = Field(ge=1, le=25)
    estimated_total_cost_minor: int = Field(ge=0)
    currency: str = "INR"
    items: list[ProviderOperationReplayPreviewItem]
    warnings: list[str] = Field(default_factory=list)


class ProviderOperationReplayConfirmRequest(ProviderOperationActionRequest):
    preview_token: str = Field(min_length=20, max_length=8192)


class ProviderOperationActionResponse(BaseModel):
    action: ProviderOperationAction
    changed: bool
    message: str
    operation: ProviderOperationRecord


class ProviderOperationReplayBatchResponse(BaseModel):
    changed_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    estimated_total_cost_minor: int = Field(ge=0)
    currency: str = "INR"
    operations: list[ProviderOperationActionResponse]


class CalendarUnknownOutcomeReconciliationRequest(BaseModel):
    action: Literal["attach_remote_event", "attest_remote_absence"]
    expected_updated_at: datetime
    expected_status: str = Field(min_length=1, max_length=24)
    expected_dead_letter_reason: str = Field(min_length=1, max_length=120)
    expected_provider: Literal["outlook", "google_calendar"]
    expected_connection_id: str = Field(min_length=1, max_length=36)
    expected_source_type: Literal[
        "matter_hearing", "matter_task", "matter_deadline"
    ]
    expected_source_id: str = Field(min_length=1, max_length=36)
    evidence_reference: str = Field(min_length=8, max_length=1000)
    provider_event_id: str | None = Field(default=None, min_length=1, max_length=255)

    @field_validator(
        "expected_status",
        "expected_dead_letter_reason",
        "expected_connection_id",
        "expected_source_id",
        "evidence_reference",
        "provider_event_id",
        mode="before",
    )
    @classmethod
    def strip_reconciliation_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_remote_event_id(self) -> CalendarUnknownOutcomeReconciliationRequest:
        if self.action == "attach_remote_event" and not self.provider_event_id:
            raise ValueError("provider_event_id is required when attaching a remote event")
        if self.action == "attest_remote_absence" and self.provider_event_id is not None:
            raise ValueError("provider_event_id is forbidden when attesting remote absence")
        return self


class CalendarUnknownOutcomeReconciliationResponse(BaseModel):
    action: Literal["attach_remote_event", "attest_remote_absence"]
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
    adapter_contract: ProviderAdapterContractRecord | None = None


class ProviderReadinessListResponse(BaseModel):
    providers: list[ProviderReadinessRecord]
