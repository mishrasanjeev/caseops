from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_deadlines import IpDeadlineRecord
from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_records import IpIdentifierResponse, IpProceedingResponse


class IpOppositionPartyInput(BaseModel):
    role: Literal["applicant", "opponent", "agent", "counsel"]
    party_name: str = Field(min_length=2, max_length=255)
    source: str = Field(min_length=2, max_length=120)


class IpOppositionPartyRecord(IpOppositionPartyInput):
    model_config = ConfigDict(from_attributes=True)

    role: Literal["applicant", "opponent", "agent", "counsel"] = Field(validation_alias="role_kind")
    id: str
    effective_from: date
    effective_until: date | None


class IpOppositionGround(BaseModel):
    category: Literal[
        "earlier_mark",
        "passing_off",
        "well_known_mark",
        "descriptiveness",
        "non_distinctive",
        "prohibited_mark",
        "bad_faith",
        "other",
    ]
    lawyer_detail: str = Field(min_length=5, max_length=4000)
    classification_source: Literal["manual", "ai_assisted"] = "manual"


class IpOppositionScopeSegment(BaseModel):
    class_number: int = Field(ge=1, le=45)
    goods_services_segment: str = Field(min_length=2, max_length=4000)


class IpReliedOnRight(BaseModel):
    mark_or_right: str = Field(min_length=2, max_length=255)
    jurisdiction: str = Field(min_length=2, max_length=40)
    identifier: str | None = Field(default=None, max_length=160)
    status: str = Field(min_length=2, max_length=80)
    owner: str = Field(min_length=2, max_length=255)
    goods_services: str = Field(min_length=2, max_length=4000)
    reputation_claim: str | None = Field(default=None, max_length=4000)
    use_claim: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)


class IpOppositionServiceFact(BaseModel):
    method: str = Field(min_length=2, max_length=80)
    destination: str = Field(min_length=2, max_length=500)
    served_on: date
    acknowledgement: str | None = Field(default=None, max_length=1000)
    defect: str | None = Field(default=None, max_length=2000)
    reservice_on: date | None = None
    starts_response_period: bool = False
    evidence_refs: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_reservice(self) -> IpOppositionServiceFact:
        if self.reservice_on is not None and self.reservice_on < self.served_on:
            raise ValueError("Re-service date cannot precede the original service date.")
        return self


class IpOppositionWorkspaceUpsertRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    expected_profile_event_id: str | None = None
    source: Literal["manual", "registry", "integration", "system"]
    source_reference: str | None = Field(default=None, max_length=255)
    source_notice_reference: str | None = Field(default=None, max_length=500)
    source_notice_document_ref: str | None = Field(default=None, max_length=500)
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    applicable_rule_version: str = Field(min_length=2, max_length=120)
    forum: str = Field(min_length=2, max_length=255)
    client_instruction_state: Literal["pending", "confirmed", "not_required"] = "pending"
    client_instruction_reference: str | None = Field(default=None, max_length=500)
    limitation_date: date | None = None
    parties: list[IpOppositionPartyInput] = Field(min_length=2, max_length=20)
    grounds: list[IpOppositionGround] = Field(min_length=1, max_length=40)
    challenged_scope: list[IpOppositionScopeSegment] = Field(min_length=1, max_length=45)
    relied_on_rights: list[IpReliedOnRight] = Field(default_factory=list, max_length=100)
    service: IpOppositionServiceFact | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_workspace(self) -> IpOppositionWorkspaceUpsertRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Opposition profile time must include a timezone.")
        if self.source == "registry" and not (self.source_reference or "").strip():
            raise ValueError("Registry opposition profiles require a source reference.")
        roles = {party.role for party in self.parties}
        if not {"applicant", "opponent"}.issubset(roles):
            raise ValueError("Opposition profile requires both applicant and opponent parties.")
        keys = [(party.role, party.party_name.strip().casefold()) for party in self.parties]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate opposition party and role entries are not allowed.")
        scope_keys = [
            (row.class_number, row.goods_services_segment.strip().casefold())
            for row in self.challenged_scope
        ]
        if len(scope_keys) != len(set(scope_keys)):
            raise ValueError("Duplicate challenged class segments are not allowed.")
        if (
            self.client_instruction_state == "confirmed"
            and not (self.client_instruction_reference or "").strip()
        ):
            raise ValueError("Confirmed client instruction requires a reference.")
        return self


class IpOppositionProfile(BaseModel):
    applicable_rule_version: str
    forum: str
    client_instruction_state: str
    client_instruction_reference: str | None
    limitation_date: date | None
    source_notice_reference: str | None
    source_notice_document_ref: str | None
    grounds: list[IpOppositionGround]
    challenged_scope: list[IpOppositionScopeSegment]
    relied_on_rights: list[IpReliedOnRight]
    service: IpOppositionServiceFact | None
    lawyer_confirmed_by_membership_id: str


class IpOppositionWorkspaceResponse(BaseModel):
    proceeding: IpProceedingResponse
    profile: IpOppositionProfile | None
    profile_event: IpDocketEventResponse | None
    profile_revision_count: int
    parties: list[IpOppositionPartyRecord]
    application_identifiers: list[IpIdentifierResponse]
    opposition_identifiers: list[IpIdentifierResponse]
    linked_matter_id: str | None
    stage_events: list[IpDocketEventResponse]
    ready_for_stage_progression: bool
    readiness_gaps: list[str]


class IpOppositionPleadingVerification(BaseModel):
    signatory: str = Field(min_length=2, max_length=255)
    authority: str = Field(min_length=2, max_length=500)
    place: str = Field(min_length=2, max_length=255)
    verified_on: date
    verified_paragraph_ranges: list[str] = Field(min_length=1, max_length=100)
    knowledge_basis: str = Field(min_length=5, max_length=2000)
    signed_document_ref: str = Field(min_length=2, max_length=500)


class IpOppositionApplicantActionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    action_kind: Literal[
        "counterstatement_filed",
        "counterstatement_served",
        "applicant_evidence_decision",
    ]
    source: Literal["manual", "registry", "integration", "system"]
    source_reference: str = Field(min_length=2, max_length=255)
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    filing_reference: str | None = Field(default=None, max_length=500)
    filed_on: date | None = None
    evidence_election: Literal["file_evidence", "rely_on_pleaded_facts"] | None = None
    verification: IpOppositionPleadingVerification | None = None
    service: IpOppositionServiceFact | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_applicant_action(self) -> IpOppositionApplicantActionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Applicant action time must include a timezone.")
        if self.action_kind == "counterstatement_filed":
            if not all(
                (
                    (self.filing_reference or "").strip(),
                    self.filed_on,
                    self.verification,
                    self.document_refs,
                    self.evidence_refs,
                )
            ):
                raise ValueError(
                    "A filed counterstatement requires filing facts, signed verification, "
                    "the final document, and filing evidence."
                )
        elif self.action_kind == "counterstatement_served":
            if self.service is None:
                raise ValueError("Counterstatement service requires complete service facts.")
        elif self.evidence_election is None:
            raise ValueError(
                "Applicant evidence requires an explicit filing or pleaded-facts election."
            )
        if self.action_kind != "applicant_evidence_decision" and self.evidence_election:
            raise ValueError("An evidence election is only valid for applicant evidence.")
        if self.evidence_election == "file_evidence" and not (
            self.document_refs and self.evidence_refs
        ):
            raise ValueError("Filed applicant evidence requires document and filing evidence.")
        return self


class IpOppositionApplicantDeadlineProposalRequest(BaseModel):
    workflow_stage: Literal["counterstatement_due", "applicant_evidence_due"]
    trigger_event_id: str
    rule_version_id: str
    calendar_version_id: str
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    date_precision: Literal["unknown", "date", "datetime", "session"] = "date"
    is_critical: bool = True


class IpOppositionApplicantDeadlineRecord(BaseModel):
    workflow_stage: Literal["counterstatement_due", "applicant_evidence_due"]
    deadline: IpDeadlineRecord


class IpOppositionApplicantWorkflowResponse(BaseModel):
    proceeding_id: str
    represented_side: Literal["applicant"]
    opposition_number_status: Literal["confirmed", "pending_allocation"]
    applicant_actions: list[IpDocketEventResponse]
    deadlines: list[IpOppositionApplicantDeadlineRecord]
    next_required_action: Literal[
        "record_opposition_number",
        "propose_counterstatement_deadline",
        "confirm_counterstatement_deadline",
        "advance_to_counterstatement_due",
        "file_counterstatement",
        "record_counterstatement_service",
        "propose_applicant_evidence_deadline",
        "confirm_applicant_evidence_deadline",
        "record_applicant_evidence_decision",
        "await_opponent_or_later_stage",
    ]


class IpOppositionOpponentActionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    action_kind: Literal[
        "watch_hit_closed",
        "client_instruction_escalated",
        "notice_filed",
        "notice_filing_rejected",
        "notice_refiled",
        "notice_served",
        "opponent_evidence_decision",
        "reply_evidence_decision",
    ]
    source: Literal["manual", "registry", "integration", "system"]
    source_reference: str = Field(min_length=2, max_length=255)
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    filing_reference: str | None = Field(default=None, max_length=500)
    filed_on: date | None = None
    evidence_election: (
        Literal[
            "file_evidence",
            "rely_on_pleaded_facts",
            "file_reply_evidence",
            "no_reply_evidence",
        ]
        | None
    ) = None
    verification: IpOppositionPleadingVerification | None = None
    service: IpOppositionServiceFact | None = None
    rejection_reference: str | None = Field(default=None, max_length=500)
    corrective_due_on: date | None = None
    escalation_reference: str | None = Field(default=None, max_length=500)
    escalation_due_on: date | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_opponent_action(self) -> IpOppositionOpponentActionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Opponent action time must include a timezone.")
        if self.action_kind in {"notice_filed", "notice_refiled"}:
            if not all(
                (
                    (self.filing_reference or "").strip(),
                    self.filed_on,
                    self.verification,
                    self.document_refs,
                    self.evidence_refs,
                )
            ):
                raise ValueError(
                    "A filed TM-O notice requires filing facts, signed verification, "
                    "the final document, and filing evidence."
                )
        elif self.action_kind == "notice_filing_rejected":
            if not all(
                (
                    (self.rejection_reference or "").strip(),
                    self.corrective_due_on,
                    self.evidence_refs,
                )
            ):
                raise ValueError(
                    "A rejected TM-O filing requires rejection evidence and a corrective due date."
                )
        elif self.action_kind == "notice_served":
            if self.service is None:
                raise ValueError("TM-O notice service requires complete service facts.")
        elif self.action_kind == "client_instruction_escalated":
            if not all(
                (
                    (self.escalation_reference or "").strip(),
                    self.escalation_due_on,
                    self.evidence_refs,
                )
            ):
                raise ValueError(
                    "Client-instruction escalation requires a reference, due date, and evidence."
                )
        elif self.action_kind == "opponent_evidence_decision":
            if self.evidence_election not in {
                "file_evidence",
                "rely_on_pleaded_facts",
            }:
                raise ValueError("Rule 45 requires an explicit evidence or pleaded-facts election.")
        elif self.action_kind == "reply_evidence_decision" and self.evidence_election not in {
            "file_reply_evidence",
            "no_reply_evidence",
        }:
            raise ValueError("Rule 47 requires an explicit reply-evidence election.")
        if (
            self.action_kind
            not in {
                "opponent_evidence_decision",
                "reply_evidence_decision",
            }
            and self.evidence_election
        ):
            raise ValueError("An evidence election is only valid for an evidence decision.")
        if self.evidence_election in {"file_evidence", "file_reply_evidence"} and not (
            self.document_refs and self.evidence_refs
        ):
            raise ValueError("Filed evidence requires document and filing evidence references.")
        if self.action_kind == "watch_hit_closed" and not self.evidence_refs:
            raise ValueError("Closing a watch hit requires source evidence.")
        return self


class IpOppositionOpponentDeadlineProposalRequest(BaseModel):
    workflow_stage: Literal[
        "notice_filing_due",
        "opponent_evidence_due",
        "reply_evidence_due",
    ]
    trigger_event_id: str
    rule_version_id: str
    calendar_version_id: str
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    date_precision: Literal["unknown", "date", "datetime", "session"] = "date"
    is_critical: bool = True


class IpOppositionOpponentDeadlineRecord(BaseModel):
    workflow_stage: Literal[
        "notice_filing_due",
        "opponent_evidence_due",
        "reply_evidence_due",
    ]
    deadline: IpDeadlineRecord


class IpOppositionOpponentWorkflowResponse(BaseModel):
    proceeding_id: str
    represented_side: Literal["opponent"]
    opposition_number_status: Literal["confirmed", "pending_allocation"]
    client_instruction_status: Literal["pending", "confirmed", "not_required"]
    opponent_actions: list[IpDocketEventResponse]
    deadlines: list[IpOppositionOpponentDeadlineRecord]
    corrective_task_id: str | None
    next_required_action: Literal[
        "watch_hit_closed_no_proceeding",
        "propose_notice_filing_deadline",
        "confirm_notice_filing_deadline",
        "record_client_instruction_escalation",
        "await_client_instruction",
        "file_notice",
        "correct_rejected_notice",
        "advance_to_notice_filed",
        "record_opposition_number",
        "advance_to_service_pending",
        "record_notice_service",
        "await_counterstatement",
        "propose_opponent_evidence_deadline",
        "confirm_opponent_evidence_deadline",
        "record_opponent_evidence_decision",
        "await_applicant_evidence",
        "propose_reply_evidence_deadline",
        "confirm_reply_evidence_deadline",
        "record_reply_evidence_decision",
        "await_hearing_or_later_stage",
    ]
