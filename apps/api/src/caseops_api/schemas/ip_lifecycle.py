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
    "opposition_profile",
    "opposition_applicant_action",
    "opposition_opponent_action",
    "opposition_shared_action",
]
IpEventSource = Literal["manual", "registry", "integration", "system"]
IpCandidateStatus = Literal["candidate", "confirmed", "reconciled", "rejected"]


class IpCorrespondenceMilestones(BaseModel):
    direction: Literal["inward", "outward"]
    received_at: datetime | None = None
    due_at: datetime | None = None
    prepared_at: datetime | None = None
    approved_at: datetime | None = None
    filed_at: datetime | None = None
    accepted_at: datetime | None = None

    @model_validator(mode="after")
    def validate_milestones(self) -> IpCorrespondenceMilestones:
        milestones = [
            self.received_at,
            self.due_at,
            self.prepared_at,
            self.approved_at,
            self.filed_at,
            self.accepted_at,
        ]
        if not any(milestones):
            raise ValueError("Correspondence requires at least one milestone timestamp.")
        if any(value is not None and value.utcoffset() is None for value in milestones):
            raise ValueError("Correspondence milestone timestamps must include a timezone.")
        if self.received_at and self.due_at and self.due_at < self.received_at:
            raise ValueError("Correspondence due time cannot precede receipt.")
        outward = [
            value
            for value in (self.prepared_at, self.approved_at, self.filed_at, self.accepted_at)
            if value is not None
        ]
        if any(later < earlier for earlier, later in zip(outward, outward[1:], strict=False)):
            raise ValueError("Outward correspondence milestones must remain chronological.")
        return self


class IpDocketEventCreateRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_application_version: int | None = Field(default=None, ge=1)
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
    acknowledged_exception_codes: list[str] = Field(default_factory=list, max_length=100)
    correspondence: IpCorrespondenceMilestones | None = None
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_event_contract(self) -> IpDocketEventCreateRequest:
        if self.application_id and self.proceeding_id:
            raise ValueError("An event can target an application or proceeding, not both.")
        if self.source == "manual" and not (self.reason or "").strip():
            raise ValueError("Manual events require a reason.")
        if self.source == "registry" and not (self.source_reference or "").strip():
            raise ValueError("Registry events require a source reference.")
        if self.supersedes_event_id and not (self.correction_reason or "").strip():
            raise ValueError("Corrected events require a correction reason.")
        if self.reconciles_event_id and self.reconciliation_decision is None:
            raise ValueError("Reconciled events require an explicit decision.")
        if self.reconciliation_decision and not self.reconciles_event_id:
            raise ValueError("A reconciliation decision requires a candidate event.")
        if self.application_id and self.expected_application_version is None:
            raise ValueError("Application events require the expected application version.")
        if not self.application_id and self.expected_application_version is not None:
            raise ValueError("Application version is only valid for an application event.")
        return self


class IpChecklistItem(BaseModel):
    category: Literal["fact", "form", "fee", "document", "approval", "exception"]
    key: str
    label: str
    required: bool
    satisfied: bool
    evidence_refs: list[str] = Field(default_factory=list)


class IpDocketEventPreviewResponse(BaseModel):
    docket_id: str
    lifecycle_version: int
    current_phase: str
    proposed_phase: str | None
    backdated: bool
    recalculation_required: bool
    duplicate_candidate_ids: list[str]
    checklist: list[IpChecklistItem]
    unresolved_exception_codes: list[str]
    operational_effects_are_proposals: Literal[True] = True
    filing_claimed: Literal[False] = False


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
    acknowledged_exception_codes: list[str] = Field(default_factory=list, max_length=100)
    second_approver_membership_id: str | None = None
    client_report_handling: Literal["retain", "exclude", "successor"] = "retain"
    linked_matter_handling: Literal["retain", "reviewed", "not_linked"] = "retain"

    @model_validator(mode="after")
    def validate_transition_contract(self) -> IpLifecycleTransitionRequest:
        if self.to_status == "transferred" and self.successor_docket_id is None:
            raise ValueError("A transferred docket requires a successor docket.")
        if self.to_status != "transferred" and self.successor_docket_id is not None:
            raise ValueError("A successor docket is only valid for transfer.")
        return self


class IpLifecycleImpactRow(BaseModel):
    impact_kind: Literal[
        "coverage",
        "obligation",
        "deadline",
        "incident",
        "proceeding",
        "recordal",
        "matter",
        "successor",
    ]
    record_id: str
    current_state: str
    proposed_outcome: str
    blocking: bool = False
    blocker_code: str | None = None


class IpLifecyclePreviewResponse(BaseModel):
    docket_id: str
    from_status: str
    to_status: str
    expected_lifecycle_version: int
    impacts: list[IpLifecycleImpactRow]
    blocker_codes: list[str]
    requires_exception_acknowledgement: bool
    reopen_without_child_resurrection: bool


class IpLifecycleTransitionResponse(BaseModel):
    docket_id: str
    status: str
    is_active: bool
    lifecycle_version: int
    successor_docket_id: str | None
    event: IpDocketEventResponse


class IpProsecutionWorkspaceResponse(BaseModel):
    docket_id: str
    lifecycle_status: str
    lifecycle_version: int
    current_phase: str
    registry_freshness: Literal["not_configured", "candidate_pending", "current"]
    data_quality_gaps: list[str]
    unconfirmed_deadline_refs: list[str]
    conflicting_event_ids: list[str]
    events: list[IpDocketEventResponse]
    operational_completion_count: int
    filing_evidence_count: int
    registry_acceptance_count: int
    final_disposition_count: int
