"""Typed contracts for foreign-associate filing coordination."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_documents import IpDocumentRecord
from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_operations import IpDocketRecordResponse

IpForeignAssociateStatus = Literal[
    "draft",
    "approved",
    "dispatched",
    "acknowledged",
    "in_progress",
    "filing_reported",
    "evidence_verified",
    "invoiced",
    "completed",
    "refused",
    "superseded",
    "cancelled",
]
IpForeignAssociateTransactionKind = Literal[
    "approve",
    "dispatch",
    "acknowledge",
    "record_query",
    "approve_substantive_response",
    "approve_fee_change",
    "report_filing",
    "verify_filing_evidence",
    "link_invoice",
    "complete",
    "refuse",
    "cancel",
    "reassign",
]


class IpForeignAssociateScope(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    source_kind: Literal["application", "search"]
    source_reference: str = Field(min_length=1, max_length=255)
    filing_kind: str = Field(min_length=2, max_length=120)
    scoped_fields: dict[str, object] = Field(default_factory=dict)


class IpForeignAssociateEstimateTerms(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    tax_type: str | None = Field(default=None, max_length=80)
    tax_rate_percent: float | None = Field(default=None, ge=0, le=100)
    tax_inclusive: bool = False
    tax_evidence_reference: str | None = Field(default=None, max_length=500)
    assumptions: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_tax_terms(self) -> IpForeignAssociateEstimateTerms:
        has_tax = self.tax_type is not None or self.tax_rate_percent is not None
        if has_tax and not (self.tax_evidence_reference or "").strip():
            raise ValueError("Tax terms require an evidence reference.")
        return self


class IpForeignAssociateCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    docket_id: str
    expected_lifecycle_version: int = Field(ge=0)
    instruction_thread_key: str = Field(min_length=3, max_length=120)
    source_client_instruction_id: str | None = None
    client_authority_reference: str | None = Field(default=None, max_length=500)
    target_jurisdiction: str = Field(min_length=2, max_length=80)
    outside_counsel_id: str
    assignment_id: str | None = None
    responsible_membership_id: str
    scope: IpForeignAssociateScope
    selected_document_refs: list[str] = Field(min_length=1, max_length=100)
    include_privileged_documents: bool = False
    estimate_cost_item_id: str
    estimate_terms: IpForeignAssociateEstimateTerms
    budget_policy_reference: str = Field(min_length=3, max_length=500)
    response_due_at: datetime | None = None
    reason: str = Field(min_length=5, max_length=2000)

    @model_validator(mode="after")
    def validate_create_contract(self) -> IpForeignAssociateCreateRequest:
        if not self.source_client_instruction_id and not (
            self.client_authority_reference or ""
        ).strip():
            raise ValueError(
                "Link an accepted client instruction or provide its external authority evidence."
            )
        if self.response_due_at and self.response_due_at.utcoffset() is None:
            raise ValueError("Associate response deadline must include a timezone.")
        if len(set(self.selected_document_refs)) != len(self.selected_document_refs):
            raise ValueError("Selected document references must be unique.")
        return self


class IpForeignAssociateTransactionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    transaction_kind: IpForeignAssociateTransactionKind
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    deadline_refs: list[str] = Field(default_factory=list, max_length=100)
    dispatch_communication_id: str | None = None
    external_dispatch_reference: str | None = Field(default=None, max_length=500)
    external_delivery_reference: str | None = Field(default=None, max_length=500)
    external_delivered_at: datetime | None = None
    acknowledgement_reference: str | None = Field(default=None, max_length=500)
    replacement_estimate_cost_item_id: str | None = None
    replacement_estimate_terms: IpForeignAssociateEstimateTerms | None = None
    filing_identifier: str | None = Field(default=None, max_length=255)
    actual_cost_item_id: str | None = None
    spend_record_id: str | None = None
    replacement_outside_counsel_id: str | None = None
    replacement_assignment_id: str | None = None
    replacement_response_due_at: datetime | None = None
    details: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transaction_contract(self) -> IpForeignAssociateTransactionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Associate transaction time must include a timezone.")
        if self.external_delivered_at and self.external_delivered_at.utcoffset() is None:
            raise ValueError("External delivery time must include a timezone.")
        if (
            self.replacement_response_due_at
            and self.replacement_response_due_at.utcoffset() is None
        ):
            raise ValueError("Replacement response deadline must include a timezone.")
        if self.dispatch_communication_id and self.external_dispatch_reference:
            raise ValueError("Use a Communication or an external dispatch reference, not both.")
        if self.transaction_kind == "dispatch" and not (
            self.dispatch_communication_id or self.external_dispatch_reference
        ):
            raise ValueError("Dispatch requires a Communication or external dispatch evidence.")
        if self.external_delivery_reference and not self.external_dispatch_reference:
            raise ValueError("External delivery evidence requires external dispatch evidence.")
        if self.external_delivered_at and not self.external_delivery_reference:
            raise ValueError("External delivery time requires its evidence reference.")
        if self.transaction_kind == "acknowledge" and not (
            self.acknowledgement_reference or ""
        ).strip():
            raise ValueError("Associate acknowledgement requires independent evidence.")
        if self.transaction_kind == "approve_fee_change" and not (
            self.replacement_estimate_cost_item_id and self.replacement_estimate_terms
        ):
            raise ValueError("Fee-change approval requires replacement estimate and tax terms.")
        if self.transaction_kind == "report_filing":
            if not (self.filing_identifier or "").strip():
                raise ValueError("Filing report requires the foreign filing identifier.")
            if not self.evidence_refs or not self.document_refs:
                raise ValueError("Filing report requires source and docket-document evidence.")
        if self.transaction_kind == "verify_filing_evidence" and not self.evidence_refs:
            raise ValueError("Filing evidence verification requires independent evidence.")
        if self.transaction_kind == "link_invoice" and not (
            self.actual_cost_item_id and self.spend_record_id
        ):
            raise ValueError("Invoice linkage requires canonical cost and spend records.")
        if self.transaction_kind in {
            "record_query",
            "approve_substantive_response",
            "approve_fee_change",
            "refuse",
            "reassign",
        } and not self.evidence_refs:
            raise ValueError(f"{self.transaction_kind} requires correspondence evidence.")
        if self.transaction_kind == "reassign" and not (
            self.replacement_outside_counsel_id
            and self.replacement_estimate_cost_item_id
            and self.replacement_estimate_terms
        ):
            raise ValueError(
                "Reassignment requires an approved associate and replacement estimate terms."
            )
        for label, values in (
            ("evidence", self.evidence_refs),
            ("document", self.document_refs),
            ("deadline", self.deadline_refs),
        ):
            if any(not value for value in values) or len(values) != len(set(values)):
                raise ValueError(f"{label.title()} references must be non-blank and unique.")
        return self


class IpForeignAssociateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    instruction_thread_key: str
    instruction_version: int
    row_version: int
    supersedes_instruction_id: str | None
    source_client_instruction_id: str | None
    client_authority_reference: str | None
    target_jurisdiction: str
    outside_counsel_id: str
    assignment_id: str | None
    responsible_membership_id: str
    scope_json: dict[str, object]
    selected_document_refs_json: list[str]
    privileged_document_refs_json: list[str]
    estimate_cost_item_id: str
    estimate_terms_json: dict[str, object]
    budget_policy_reference: str
    approved_by_membership_id: str | None
    approved_at: datetime | None
    privileged_approved_by_membership_id: str | None
    privileged_approved_at: datetime | None
    dispatch_communication_id: str | None
    external_dispatch_reference: str | None
    external_delivery_reference: str | None
    external_delivered_at: datetime | None
    dispatched_at: datetime | None
    acknowledged_at: datetime | None
    acknowledgement_reference: str | None
    response_due_at: datetime | None
    filing_identifier: str | None
    filing_reported_at: datetime | None
    filing_evidence_refs_json: list[str]
    filing_verified_at: datetime | None
    actual_cost_item_id: str | None
    spend_record_id: str | None
    status: str
    created_by_membership_id: str
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpForeignAssociatePageResponse(BaseModel):
    items: list[IpForeignAssociateResponse]
    total: int
    limit: int
    offset: int


class IpForeignAssociateTransactionResponse(BaseModel):
    instruction: IpForeignAssociateResponse
    event: IpDocketEventResponse
    successor: IpForeignAssociateResponse | None = None


class IpForeignAssociateReminderRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    reminder_offsets_hours: list[int] = Field(
        default_factory=lambda: [72, 24, 0], min_length=1, max_length=10
    )
    channels: list[Literal["in_app", "email"]] = Field(
        default_factory=lambda: ["in_app"], min_length=1, max_length=2
    )
    escalation_after_hours: int = Field(default=24, ge=1, le=168)
    escalation_membership_id: str | None = None

    @model_validator(mode="after")
    def validate_reminder_policy(self) -> IpForeignAssociateReminderRequest:
        if len(self.reminder_offsets_hours) != len(set(self.reminder_offsets_hours)):
            raise ValueError("Reminder offsets must be unique.")
        if any(value < 0 or value > 720 for value in self.reminder_offsets_hours):
            raise ValueError("Reminder offsets must be between 0 and 720 hours.")
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("Reminder channels must be unique.")
        return self


class IpForeignAssociateReminderRecord(BaseModel):
    id: str
    recipient_membership_id: str | None
    event_type: str
    channel: str
    status: str
    scheduled_for: datetime | None
    delivered_at: datetime | None
    critical: bool


class IpForeignAssociateReminderScheduleResponse(BaseModel):
    instruction_id: str
    created_count: int
    existing_count: int
    reminders: list[IpForeignAssociateReminderRecord]


class IpForeignAssociateWorkspaceResponse(BaseModel):
    instruction: IpForeignAssociateResponse
    docket: IpDocketRecordResponse
    documents: list[IpDocumentRecord]
    transactions: list[IpDocketEventResponse]
    associate_name: str
    delivery_status: str
    delivered_at: datetime | None
    acknowledgement_status: Literal["outstanding", "received"]
    filing_evidence_status: Literal["not_reported", "reported_unverified", "verified"]
    invoice_status: str | None
    response_overdue: bool
    reminders: list[IpForeignAssociateReminderRecord] = Field(default_factory=list)
