from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

IpEventKind = Literal[
    "filing",
    "formalities",
    "examination_report",
    "response",
    "show_cause_hearing",
    "acceptance",
    "publication",
    "registration",
    "renewal",
    "refusal",
    "abandonment",
    "restoration",
    "lifecycle_transition",
]
IpEventSource = Literal["manual", "registry", "integration", "system"]
IpCandidateStatus = Literal["candidate", "confirmed", "reconciled", "rejected"]


class IpDocketEventCreateRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    application_id: str | None = None
    proceeding_id: str | None = None
    event_kind: IpEventKind
    source: IpEventSource
    source_reference: str | None = Field(default=None, max_length=255)
    effective_at: datetime
    responsible_membership_id: str
    reason: str | None = Field(default=None, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    resulting_stage: str | None = Field(default=None, max_length=64)
    resulting_deadline_refs: list[str] = Field(default_factory=list, max_length=100)
    before_phase: str | None = Field(default=None, max_length=64)
    after_phase: str | None = Field(default=None, max_length=64)
    candidate_status: IpCandidateStatus = "confirmed"
    supersedes_event_id: str | None = None
    correction_reason: str | None = Field(default=None, max_length=2000)
    reconciles_event_id: str | None = None
    reconciliation_decision: Literal["same_fact", "keep_separate", "reject_candidate"] | None = None
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_contract(self) -> IpDocketEventCreateRequest:
        if self.application_id and self.proceeding_id:
            raise ValueError("An event can target an application or proceeding, not both.")
        if self.source == "manual" and not (self.reason or "").strip():
            raise ValueError("Manual events require a reason.")
        if self.supersedes_event_id and not (self.correction_reason or "").strip():
            raise ValueError("Corrected events require a correction reason.")
        if self.reconciles_event_id and self.reconciliation_decision is None:
            raise ValueError("Reconciled events require an explicit decision.")
        if self.reconciliation_decision and not self.reconciles_event_id:
            raise ValueError("A reconciliation decision requires a candidate event.")
        return self


class IpDocketEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    sequence: int
    application_id: str | None
    proceeding_id: str | None
    event_kind: str
    source: str
    source_reference: str | None
    effective_at: datetime
    entered_at: datetime
    responsible_membership_id: str
    entered_by_membership_id: str
    reason: str | None
    evidence_refs_json: list[str]
    document_refs_json: list[str]
    resulting_stage: str | None
    resulting_deadline_refs_json: list[str]
    before_phase: str | None
    after_phase: str | None
    candidate_status: str
    supersedes_event_id: str | None
    correction_reason: str | None
    reconciles_event_id: str | None
    reconciliation_decision: str | None
    payload_json: dict[str, object]
    created_at: datetime


class IpLifecycleTransitionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    to_status: Literal["ready", "abandoned", "transferred", "retired", "closed"]
    effective_at: datetime
    reason: str = Field(min_length=5, max_length=2000)
    outcome: str = Field(min_length=2, max_length=120)
    source: str = Field(min_length=2, max_length=80)
    evidence_ref: str = Field(min_length=2, max_length=512)
    successor_docket_id: str | None = None

    @model_validator(mode="after")
    def validate_transition_contract(self) -> IpLifecycleTransitionRequest:
        if self.to_status == "transferred" and self.successor_docket_id is None:
            raise ValueError("A transferred docket requires a successor docket.")
        if self.to_status != "transferred" and self.successor_docket_id is not None:
            raise ValueError("A successor docket is only valid for transfer.")
        return self
