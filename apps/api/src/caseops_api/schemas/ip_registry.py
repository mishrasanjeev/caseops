"""Typed contracts for IP-office registry evidence and court references."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IpRegistryLinkCreateRequest(BaseModel):
    application_id: str | None = None
    proceeding_id: str | None = None
    provider_key: str = Field(min_length=2, max_length=80)
    office: str = Field(min_length=2, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    identifier_kind: str = Field(min_length=2, max_length=40)
    raw_identifier: str = Field(min_length=1, max_length=160)
    source_url: str = Field(min_length=8, max_length=800)
    match_confidence: Decimal = Field(ge=0, le=1)
    match_evidence: dict[str, Any] = Field(default_factory=dict)
    terms_version: str | None = Field(default=None, max_length=80)
    capability_version: str = Field(min_length=2, max_length=80)

    @model_validator(mode="after")
    def validate_single_target(self) -> IpRegistryLinkCreateRequest:
        if bool(self.application_id) == bool(self.proceeding_id):
            raise ValueError("Choose exactly one application or proceeding target.")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Registry source URL must use HTTP or HTTPS.")
        return self


class IpRegistryLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    application_id: str | None
    proceeding_id: str | None
    provider_key: str
    office: str
    jurisdiction: str
    identifier_kind: str
    raw_identifier: str
    normalized_identifier: str
    source_url: str
    match_status: Literal["candidate", "confirmed", "mismatch", "retired"]
    match_confidence: Decimal
    match_evidence_json: dict[str, Any]
    accepted_state_json: dict[str, Any]
    terms_version: str | None
    capability_version: str
    freshness_status: Literal["never_succeeded", "current", "stale", "failed", "blocked"]
    last_attempted_at: datetime | None
    last_successful_at: datetime | None
    last_snapshot_id: str | None
    last_normalized_hash: str | None
    last_error_redacted: str | None
    version: int
    created_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpRegistryLinkMatchDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["confirm", "mismatch", "retire"]
    reason: str = Field(min_length=5, max_length=800)


class IpRegistryManualSnapshotRequest(BaseModel):
    expected_link_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)
    source_url: str = Field(min_length=8, max_length=800)
    source_retrieved_at: datetime
    parser_version: str = Field(min_length=2, max_length=80)
    schema_version: int = Field(default=1, ge=1)
    attribution: dict[str, Any] = Field(default_factory=dict)
    raw_snapshot: dict[str, Any]
    normalized_snapshot: dict[str, Any]
    supersedes_snapshot_id: str | None = None
    correction_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_snapshot(self) -> IpRegistryManualSnapshotRequest:
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Registry source URL must use HTTP or HTTPS.")
        if self.source_retrieved_at.utcoffset() is None:
            raise ValueError("Source retrieval time must include a timezone.")
        if not self.raw_snapshot or not self.normalized_snapshot:
            raise ValueError("Raw and normalized snapshots must both contain evidence.")
        if bool(self.supersedes_snapshot_id) != bool((self.correction_reason or "").strip()):
            raise ValueError("A corrected snapshot requires both predecessor and reason.")
        return self


class IpRegistryFailureRequest(BaseModel):
    expected_link_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=120)
    response_class: Literal[
        "authentication",
        "rate_limit",
        "parse_error",
        "provider_outage",
        "configuration",
        "policy",
        "unknown",
    ]
    error: str = Field(min_length=2, max_length=2000)
    external_call: bool = False
    source_retrieved_at: datetime | None = None


class IpRegistrySyncAttemptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    link_id: str
    provider_key: str
    operation_kind: str
    idempotency_key: str
    correlation_id: str
    status: Literal["pending", "succeeded", "no_change", "failed", "blocked"]
    response_class: str
    external_call: bool
    attempts: int
    replay_of_attempt_id: str | None
    cost_minor: int
    currency: str
    error_redacted: str | None
    metadata_json: dict[str, Any]
    requested_by_membership_id: str
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class IpRegistrySnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    link_id: str
    attempt_id: str
    source_url: str
    source_retrieved_at: datetime
    parser_version: str
    schema_version: int
    attribution_json: dict[str, Any]
    terms_version: str | None
    raw_sha256: str
    normalized_sha256: str
    raw_json: dict[str, Any]
    normalized_json: dict[str, Any]
    supersedes_snapshot_id: str | None
    correction_reason: str | None
    created_at: datetime


class IpRegistrySnapshotSummaryResponse(BaseModel):
    """Bounded registry history without the immutable evidence bodies."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    link_id: str
    attempt_id: str
    source_url: str
    source_retrieved_at: datetime
    parser_version: str
    schema_version: int
    attribution_json: dict[str, Any]
    terms_version: str | None
    raw_sha256: str
    normalized_sha256: str
    supersedes_snapshot_id: str | None
    correction_reason: str | None
    created_at: datetime


class IpRegistryDiffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    snapshot_id: str
    field_path: str
    change_kind: Literal["added", "changed", "removed"]
    before_value_json: Any | None
    after_value_json: Any | None
    risk_level: Literal["low", "high"]
    risk_reasons_json: list[str]
    policy_version: str
    resolution_status: Literal["pending", "accepted", "rejected", "mapped", "deferred"]
    resolution_reason: str | None
    mapped_field_path: str | None
    resolved_by_membership_id: str | None
    resolved_at: datetime | None
    emitted_event_id: str | None
    deadline_recalculation_state: Literal["not_applicable", "required", "proposed", "blocked"]
    version: int
    created_at: datetime
    updated_at: datetime


class IpRegistrySnapshotResult(BaseModel):
    link: IpRegistryLinkResponse
    attempt: IpRegistrySyncAttemptResponse
    snapshot: IpRegistrySnapshotResponse | None
    diffs: list[IpRegistryDiffResponse] = Field(default_factory=list)
    no_change: bool
    idempotent_replay: bool = False


class IpRegistryDiffResolveRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["accept", "reject", "map", "defer"]
    reason: str = Field(min_length=5, max_length=1000)
    mapped_field_path: str | None = Field(default=None, max_length=500)
    effective_at: datetime | None = None
    responsible_membership_id: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> IpRegistryDiffResolveRequest:
        if self.decision == "map" and not (self.mapped_field_path or "").strip():
            raise ValueError("Mapping requires a canonical field path.")
        if self.mapped_field_path is not None and (
            not self.mapped_field_path.startswith("/") or self.mapped_field_path == "/"
        ):
            raise ValueError("Canonical mapping must be a non-root JSON pointer.")
        if self.decision == "accept":
            if self.effective_at is None or self.responsible_membership_id is None:
                raise ValueError("Acceptance requires effective time and responsible member.")
            if self.effective_at.utcoffset() is None:
                raise ValueError("Accepted effective time must include a timezone.")
        return self


class IpRegistryWorkspaceResponse(BaseModel):
    link: IpRegistryLinkResponse
    attempts: list[IpRegistrySyncAttemptResponse] = Field(default_factory=list)
    snapshots: list[IpRegistrySnapshotSummaryResponse] = Field(default_factory=list)


class IpRegistryWorkspacePageResponse(BaseModel):
    items: list[IpRegistryWorkspaceResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class IpRegistryDiffPageResponse(BaseModel):
    items: list[IpRegistryDiffResponse] = Field(default_factory=list)
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class IpTrackedCaseLinkCreateRequest(BaseModel):
    proceeding_id: str
    tracked_case_id: str
    purpose: str = Field(min_length=3, max_length=120)
    evidence_reference: str = Field(min_length=3, max_length=800)


class IpTrackedCaseLinkDecisionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision: Literal["confirm", "mismatch", "retire"]
    reason: str = Field(min_length=5, max_length=800)


class IpTrackedCaseReferenceResponse(BaseModel):
    id: str
    company_id: str
    docket_id: str
    proceeding_id: str
    tracked_case_id: str
    link_status: Literal["active", "mismatch", "retired"]
    purpose: str
    evidence_reference: str
    created_by_membership_id: str
    version: int
    created_at: datetime
    updated_at: datetime
    provider: str
    case_title: str
    cnr_number: str | None
    case_number: str | None
    court_name: str | None
    current_status: str | None
    last_provider_successful_at: datetime | None
    provider_freshness_status: str
    update_count: int
