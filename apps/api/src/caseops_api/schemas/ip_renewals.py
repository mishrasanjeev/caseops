"""Typed API contracts for the IPLF-037A renewal foundation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

RenewalState = Literal[
    "due",
    "instructed",
    "filing_in_progress",
    "filed",
    "accepted",
    "grace",
    "overdue",
    "completed",
    "cancelled",
]
InstructionDecision = Literal[
    "renew", "do_not_renew", "defer", "clarification_required"
]
InstructionStatus = Literal[
    "pending", "accepted", "rejected", "clarification_required", "superseded"
]


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class IpRenewalFoundationContract(BaseModel):
    renewal_owner: str = "ip_renewal_terms"
    instruction_owner: str = "ip_client_instructions"
    legal_deadline_owner: str = "ip_deadlines"
    operational_deadline_owner: str = "matter_deadlines"
    legal_event_owner: str = "ip_docket_events"
    cost_owner: str = "ip_cost_items"
    document_owner: str = "ip_documents"
    communication_owner: str = "communications"
    notification_owner: str = "notification_delivery_intents"
    completion_rule: str = (
        "Payment or filing initiation never completes a renewal; registry acceptance, "
        "certificate evidence, and a confirmed next-term deadline are required."
    )


class IpRenewalTermCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_event_id: str
    renewal_deadline_id: str
    grace_deadline_id: str | None = None
    fee_cost_item_id: str | None = None


class IpRenewalTermTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_state: RenewalState
    expected_version: int = Field(gt=0)
    expected_updated_at: datetime
    target_state: RenewalState
    reason: str = Field(min_length=5, max_length=2000)
    fee_cost_item_id: str | None = None
    filing_initiated_reference: str | None = Field(default=None, min_length=3, max_length=500)
    filing_event_id: str | None = None
    acceptance_event_id: str | None = None
    certificate_document_id: str | None = None
    next_term_deadline_id: str | None = None

    @field_validator("expected_updated_at")
    @classmethod
    def normalize_expected_updated_at(cls, value: datetime) -> datetime:
        return _as_aware(value)

    @model_validator(mode="after")
    def require_transition_evidence(self) -> Self:
        if self.target_state == "filing_in_progress" and not self.filing_initiated_reference:
            raise ValueError("filing_initiated_reference is required for filing initiation")
        if self.target_state in {"filed", "accepted", "completed"} and not self.filing_event_id:
            raise ValueError("filing_event_id is required once a renewal is filed")
        if self.target_state in {"accepted", "completed"} and not self.acceptance_event_id:
            raise ValueError("acceptance_event_id is required for registry acceptance")
        if self.target_state == "completed" and (
            not self.certificate_document_id or not self.next_term_deadline_id
        ):
            raise ValueError(
                "certificate_document_id and next_term_deadline_id are required for completion"
            )
        return self


class IpClientInstructionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: InstructionDecision
    scope: dict[str, object] = Field(min_length=1)
    options: list[dict[str, object]] = Field(default_factory=list, max_length=100)
    instruction_deadline_at: datetime | None = None
    source_channel: str = Field(min_length=2, max_length=40)
    source_communication_id: str | None = None
    authority_name: str = Field(min_length=2, max_length=255)
    authority_reference: str | None = Field(default=None, max_length=255)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    received_at: datetime
    expected_current_instruction_id: str | None = None
    expected_current_row_version: int | None = Field(default=None, gt=0)

    @field_validator("received_at", "instruction_deadline_at")
    @classmethod
    def normalize_datetimes(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _as_aware(value)

    @model_validator(mode="after")
    def require_complete_revision_token(self) -> Self:
        has_id = self.expected_current_instruction_id is not None
        has_version = self.expected_current_row_version is not None
        if has_id != has_version:
            raise ValueError(
                "expected_current_instruction_id and expected_current_row_version "
                "must be supplied together"
            )
        return self


class IpClientInstructionAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: Literal["pending"]
    expected_row_version: int = Field(gt=0)
    expected_updated_at: datetime
    status: Literal["accepted", "rejected", "clarification_required"]
    reason: str = Field(min_length=5, max_length=2000)
    resulting_event_id: str | None = None

    @field_validator("expected_updated_at")
    @classmethod
    def normalize_expected_updated_at(cls, value: datetime) -> datetime:
        return _as_aware(value)

    @model_validator(mode="after")
    def validate_resulting_event(self) -> Self:
        if self.resulting_event_id is not None and self.status != "accepted":
            raise ValueError("Only an accepted instruction can link a resulting event")
        return self


class IpClientInstructionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    renewal_term_id: str
    instruction_version: int
    row_version: int
    decision: InstructionDecision
    status: InstructionStatus
    scope_json: dict[str, object]
    options_json: list[dict[str, object]]
    instruction_deadline_at: datetime | None
    source_channel: str
    source_communication_id: str | None
    authority_name: str
    authority_reference: str | None
    evidence_refs_json: list[str]
    received_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_membership_id: str | None
    acknowledgement_reason: str | None
    supersedes_instruction_id: str | None
    resulting_event_id: str | None
    created_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpRenewalTermRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    term_sequence: int
    registration_event_id: str
    renewal_deadline_id: str
    grace_deadline_id: str | None
    fee_cost_item_id: str | None
    filing_initiated_reference: str | None
    filing_event_id: str | None
    acceptance_event_id: str | None
    certificate_document_id: str | None
    next_term_deadline_id: str | None
    state: RenewalState
    version: int
    completed_at: datetime | None
    created_by_membership_id: str
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime
    instructions: list[IpClientInstructionRecord] = Field(default_factory=list)


class IpRenewalTermListResponse(BaseModel):
    items: list[IpRenewalTermRecord]
    total: int
