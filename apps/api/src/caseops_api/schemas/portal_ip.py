from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from caseops_api.schemas.ip_renewals import RenewalState
from caseops_api.schemas.ip_reports import (
    IpReportKind,
    IpReportPortfolioFilters,
)

PortalIpInstructionDecision = Literal[
    "renew",
    "do_not_renew",
    "proceed",
    "do_not_proceed",
    "defer",
    "clarification_required",
]


class PortalIpScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Shared grants may also target Matters. These legacy Matter capabilities
    # are accepted here but are never used to authorize IP portal data.
    can_reply: bool = True
    can_upload: bool = False
    can_invoice: bool = False
    show_status: bool = True
    show_identifiers: bool = True
    event_kinds: list[str] = Field(default_factory=list, max_length=40)
    deadline_kinds: list[str] = Field(default_factory=list, max_length=40)
    document_categories: list[str] = Field(default_factory=list, max_length=40)
    can_submit_instructions: bool = True

    @field_validator("event_kinds", "deadline_kinds", "document_categories")
    @classmethod
    def clean_values(cls, values: list[str]) -> list[str]:
        cleaned = [str(value).strip().lower() for value in values if str(value).strip()]
        if any(len(value) > 80 for value in cleaned):
            raise ValueError("Scope values must not exceed 80 characters.")
        return list(dict.fromkeys(cleaned))


class PortalIpGrantRecord(BaseModel):
    id: str
    portal_user_id: str
    portal_user_name: str
    portal_user_email: str
    ip_docket_record_id: str
    docket_title: str
    scope: PortalIpScope
    granted_at: datetime
    expires_at: datetime | None
    revoked_at: datetime | None
    row_version: int
    active: bool


class PortalIpGrantListResponse(BaseModel):
    grants: list[PortalIpGrantRecord] = Field(default_factory=list)


class PortalGrantRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_row_version: int = Field(gt=0)
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class PortalIpEventRecord(BaseModel):
    id: str
    event_kind: str
    effective_at: datetime
    resulting_stage: str | None
    source: str


class PortalIpDeadlineRecord(BaseModel):
    id: str
    deadline_kind: str
    title: str
    due_on: str | None
    due_at: datetime | None
    certainty: str
    state: str


class PortalIpRecord(BaseModel):
    id: str
    title: str
    record_type: str
    status: str | None
    primary_identifier: str | None
    identifiers: list[str] = Field(default_factory=list)
    events: list[PortalIpEventRecord] = Field(default_factory=list)
    upcoming_dates: list[PortalIpDeadlineRecord] = Field(default_factory=list)
    grant_expires_at: datetime | None


class PortalIpRecordListResponse(BaseModel):
    records: list[PortalIpRecord] = Field(default_factory=list)


class PortalReportPublicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal_user_id: str = Field(min_length=10, max_length=64)
    grant_ids: list[str] = Field(min_length=1, max_length=50)
    title: str = Field(min_length=2, max_length=255)
    report_kind: IpReportKind
    filters: IpReportPortfolioFilters = Field(default_factory=IpReportPortfolioFilters)
    renewal_states: list[RenewalState] = Field(default_factory=list, max_length=10)
    row_limit: int = Field(default=200, ge=1, le=200)
    expected_snapshot_sha256: str = Field(min_length=64, max_length=64)
    scheduled_for: datetime | None = None

    @field_validator("grant_ids")
    @classmethod
    def unique_grants(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))


class PortalDocumentPublicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portal_user_id: str = Field(min_length=10, max_length=64)
    grant_id: str = Field(min_length=10, max_length=64)
    document_id: str = Field(min_length=10, max_length=64)
    version_number: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=255)
    scheduled_for: datetime | None = None


class PortalPublicationTargetRecord(BaseModel):
    ip_docket_record_id: str
    docket_title: str
    current: bool


class PortalPublicationRecord(BaseModel):
    id: str
    publication_kind: Literal["report", "document"]
    title: str
    status: Literal["scheduled", "published", "revoked"]
    access_state: Literal["available", "scheduled", "review_required", "revoked"]
    scheduled_for: datetime | None
    published_at: datetime | None
    delivery_status: str | None
    delivery_error: str | None
    report_kind: str | None
    schema_version: str | None
    generated_at: datetime | None
    freshness: dict[str, Any] | None
    summary: dict[str, Any] | None
    rows: list[dict[str, Any]] | None
    document_id: str | None
    document_version: int | None
    document_filename: str | None
    targets: list[PortalPublicationTargetRecord] = Field(default_factory=list)
    accessed_at: datetime | None = None


class PortalPublicationListResponse(BaseModel):
    publications: list[PortalPublicationRecord] = Field(default_factory=list)


class PortalInstructionSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: PortalIpInstructionDecision
    instruction_kind: Literal["renewal", "proceeding", "filing", "watch", "general"]
    docket_id: str | None = Field(default=None, min_length=10, max_length=64)
    note: str = Field(min_length=2, max_length=4000)
    expected_current_instruction_id: str | None = Field(default=None, min_length=10, max_length=64)
    expected_current_row_version: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_expected_pair(self) -> PortalInstructionSubmitRequest:
        if (self.expected_current_instruction_id is None) != (
            self.expected_current_row_version is None
        ):
            raise ValueError("Expected instruction id and row version must be supplied together.")
        renewal_decisions = {"renew", "do_not_renew"}
        if self.instruction_kind == "renewal" and self.decision in {
            "proceed",
            "do_not_proceed",
        }:
            raise ValueError("Renewal instructions must use a renewal decision.")
        if self.instruction_kind != "renewal" and self.decision in renewal_decisions:
            raise ValueError("Renewal decisions require a renewal instruction.")
        return self

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str) -> str:
        return value.strip()


class PortalInstructionRecord(BaseModel):
    id: str
    docket_id: str
    docket_title: str
    publication_id: str
    instruction_version: int
    row_version: int
    instruction_kind: str
    decision: str
    status: str
    note: str
    submitted_by: str
    received_at: datetime
    acknowledged_at: datetime | None
    acknowledgement_reason: str | None
    resulting_event_id: str | None
    updated_at: datetime


class PortalInstructionListResponse(BaseModel):
    instructions: list[PortalInstructionRecord] = Field(default_factory=list)


class PortalInstructionAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: Literal["pending"] = "pending"
    expected_row_version: int = Field(gt=0)
    status: Literal["accepted", "rejected", "clarification_required"]
    reason: str = Field(min_length=5, max_length=2000)
    resulting_event_id: str | None = Field(default=None, min_length=10, max_length=64)

    @model_validator(mode="after")
    def validate_result(self) -> PortalInstructionAcknowledgeRequest:
        if self.resulting_event_id is not None and self.status != "accepted":
            raise ValueError("Only an accepted instruction can link a resulting event.")
        return self


__all__ = [name for name in globals() if name.startswith("Portal")]
