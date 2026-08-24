from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_deadlines import IpDeadlineRecord, IpResponsibilityInput
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


class IpOppositionEvidencePackage(BaseModel):
    package_kind: Literal["rule_45", "rule_46", "rule_47", "further_evidence"]
    package_version: int = Field(ge=1)
    affidavit_deponent: str = Field(min_length=2, max_length=255)
    affidavit_document_ref: str = Field(min_length=2, max_length=500)
    exhibit_document_refs: list[str] = Field(min_length=1, max_length=100)
    index_document_ref: str = Field(min_length=2, max_length=500)
    verification: IpOppositionPleadingVerification
    relied_on_document_refs: list[str] = Field(min_length=1, max_length=100)
    filing_reference: str = Field(min_length=2, max_length=500)
    filed_on: date
    service: IpOppositionServiceFact
    leave_or_order_reference: str | None = Field(default=None, max_length=500)
    foreign_language_document_refs: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_further_evidence(self) -> IpOppositionEvidencePackage:
        if self.package_kind == "further_evidence" and not (
            self.leave_or_order_reference or ""
        ).strip():
            raise ValueError("Further evidence requires its leave or order reference.")
        if self.package_kind != "further_evidence" and self.leave_or_order_reference:
            raise ValueError("Leave or order is only recorded for further evidence.")
        return self


class IpOppositionFurtherEvidenceLeave(BaseModel):
    leave_or_order_reference: str = Field(min_length=2, max_length=500)
    permitted_scope: str = Field(min_length=5, max_length=4000)
    granted_on: date


class IpOppositionHearingPreparation(BaseModel):
    shared_hearing_id: str
    checklist_items: list[str] = Field(min_length=1, max_length=100)
    issues: list[str] = Field(min_length=1, max_length=100)
    evidence_document_refs: list[str] = Field(min_length=1, max_length=100)
    authority_refs: list[str] = Field(min_length=1, max_length=100)
    written_submission_document_refs: list[str] = Field(default_factory=list, max_length=100)
    attendance_membership_ids: list[str] = Field(min_length=1, max_length=100)
    cause_list_source: str = Field(min_length=2, max_length=500)
    post_hearing_notes: str | None = Field(default=None, max_length=10000)


class IpOppositionComplianceDirection(BaseModel):
    direction: str = Field(min_length=2, max_length=2000)
    due_on: date


class IpOppositionOrderDetails(BaseModel):
    operative_result: str = Field(min_length=5, max_length=4000)
    affected_application_id: str
    affected_proceeding_id: str
    costs_and_directions: list[str] = Field(default_factory=list, max_length=100)
    compliance_directions: list[IpOppositionComplianceDirection] = Field(
        default_factory=list, max_length=100
    )
    appeal_review: Literal["required", "not_required", "pending"]
    order_document_ref: str = Field(min_length=2, max_length=500)


class IpOppositionAppealLink(BaseModel):
    target_kind: Literal["appeal_proceeding", "matter"]
    target_id: str
    appeal_identifier: str = Field(min_length=2, max_length=255)
    order_event_id: str


class IpOppositionDeadlineExtension(BaseModel):
    deadline_id: str
    expected_deadline_version: int = Field(ge=1)
    new_result_on: date
    responsibilities: list[IpResponsibilityInput] = Field(min_length=1)
    internal_target_on: date | None = None
    reminder_offsets_days: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_reminders(self) -> IpOppositionDeadlineExtension:
        if len(self.reminder_offsets_days) != len(set(self.reminder_offsets_days)):
            raise ValueError("Reminder offsets cannot contain duplicates.")
        if any(offset < 0 or offset > 3650 for offset in self.reminder_offsets_days):
            raise ValueError("Reminder offsets must be between 0 and 3650 days.")
        return self


class IpOppositionApplicationScopeRecord(BaseModel):
    id: str
    class_number: int = Field(ge=1, le=45)
    specification: str
    effective_from: date
    source: str


class IpOppositionScopeDecision(BaseModel):
    application_scope_id: str
    challenged_segment: str = Field(min_length=2, max_length=4000)
    status: Literal["challenged", "continuing", "withdrawn", "decided"]
    outcome: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_outcome(self) -> IpOppositionScopeDecision:
        if self.status == "decided" and not (self.outcome or "").strip():
            raise ValueError("A decided class segment requires its outcome.")
        if self.status != "decided" and self.outcome:
            raise ValueError("An outcome is only valid for a decided class segment.")
        return self


class IpOppositionScopeReview(BaseModel):
    revision: int = Field(ge=1)
    source_scope_certainty: Literal["certain", "partial", "missing"]
    source_confirmation_reference: str | None = Field(default=None, max_length=500)
    decisions: list[IpOppositionScopeDecision] = Field(min_length=1, max_length=45)
    related_application_id: str | None = None
    amendment_or_division_reference: str | None = Field(default=None, max_length=500)
    preserve_unlisted_scopes: Literal[True] = True

    @model_validator(mode="after")
    def validate_scope_review(self) -> IpOppositionScopeReview:
        scope_ids = [row.application_scope_id for row in self.decisions]
        if len(scope_ids) != len(set(scope_ids)):
            raise ValueError("A scope review cannot repeat an application scope.")
        if self.source_scope_certainty != "certain" and not (
            self.source_confirmation_reference or ""
        ).strip():
            raise ValueError(
                "Partial or missing Registry scope requires source confirmation."
            )
        if bool(self.related_application_id) != bool(self.amendment_or_division_reference):
            raise ValueError(
                "Amendment or division relationships require both application and reference."
            )
        return self


class IpOppositionTranslationRecord(BaseModel):
    source_document_ref: str = Field(min_length=2, max_length=500)
    source_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_language: str = Field(min_length=2, max_length=80)
    translated_document_ref: str = Field(min_length=2, max_length=500)
    translated_document_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    translated_language: Literal["Hindi", "English"]
    translator_name: str = Field(min_length=2, max_length=255)
    translator_credential: str = Field(min_length=2, max_length=500)
    attested_on: date
    attestation_reference: str = Field(min_length=2, max_length=500)
    service: IpOppositionServiceFact

    @model_validator(mode="after")
    def validate_language(self) -> IpOppositionTranslationRecord:
        if self.source_language.casefold() in {"hindi", "english"}:
            raise ValueError("Hindi or English material does not require this translation record.")
        return self


class IpOppositionHearingNoticeRecord(BaseModel):
    shared_hearing_id: str
    notice_received_on: date
    notice_document_ref: str = Field(min_length=2, max_length=500)
    minimum_notice_days: int = Field(ge=0, le=365)
    notice_status: Literal["sufficient", "short", "unknown"]
    applicable_rule_version: str = Field(min_length=2, max_length=120)
    confirmation_reference: str = Field(min_length=2, max_length=500)


class IpOppositionAdjournmentRecord(BaseModel):
    shared_hearing_id: str
    requested_on: date
    request_form_ref: str = Field(min_length=2, max_length=500)
    request_reason: str = Field(min_length=5, max_length=2000)
    fee_status: Literal["not_required", "pending", "paid"]
    fee_amount_minor: int | None = Field(default=None, ge=0)
    fee_evidence_ref: str | None = Field(default=None, max_length=500)
    prior_adjournment_count: int = Field(ge=0, le=100)
    allowed_count_candidate: int = Field(ge=0, le=100)
    applicable_rule_version: str = Field(min_length=2, max_length=120)
    policy_confirmation_reference: str = Field(min_length=2, max_length=500)
    outcome: Literal["pending", "granted", "refused"] = "pending"

    @model_validator(mode="after")
    def validate_fee(self) -> IpOppositionAdjournmentRecord:
        if self.fee_status == "paid" and not (
            self.fee_amount_minor is not None and (self.fee_evidence_ref or "").strip()
        ):
            raise ValueError("A paid adjournment fee requires amount and evidence.")
        if self.prior_adjournment_count > self.allowed_count_candidate:
            raise ValueError("Prior adjournments exceed the confirmed allowed-count candidate.")
        return self


class IpOppositionWrittenArgumentsRecord(BaseModel):
    shared_hearing_id: str
    filed_on: date
    filing_reference: str = Field(min_length=2, max_length=500)
    document_refs: list[str] = Field(min_length=1, max_length=100)
    service: IpOppositionServiceFact


class IpOppositionAttendanceRecord(BaseModel):
    shared_hearing_id: str
    appearance_status: Literal["attended", "unrepresented", "nonappearance"]
    attendee_membership_ids: list[str] = Field(default_factory=list, max_length=100)
    attendance_source_ref: str = Field(min_length=2, max_length=500)
    nonappearance_consequence_candidate: str | None = Field(default=None, max_length=2000)
    applicable_rule_version: str = Field(min_length=2, max_length=120)
    consequence_confirmation_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_appearance(self) -> IpOppositionAttendanceRecord:
        if self.appearance_status == "attended" and not self.attendee_membership_ids:
            raise ValueError("Attendance requires at least one attendee.")
        if self.appearance_status == "nonappearance" and not all(
            (
                (self.nonappearance_consequence_candidate or "").strip(),
                (self.consequence_confirmation_reference or "").strip(),
            )
        ):
            raise ValueError(
                "Nonappearance requires a confirmed, rule-versioned consequence candidate."
            )
        return self


class IpOppositionSecurityForCostsRecord(BaseModel):
    direction_reference: str = Field(min_length=2, max_length=500)
    directed_on: date
    amount_minor: int = Field(ge=0)
    enhancement_amount_minor: int = Field(default=0, ge=0)
    due_on: date
    payment_status: Literal["pending", "paid", "overdue", "waived"]
    paid_on: date | None = None
    payment_reference: str | None = Field(default=None, max_length=500)
    consequence_candidate: str = Field(min_length=5, max_length=2000)
    applicable_rule_version: str = Field(min_length=2, max_length=120)
    fee_classification: Literal["security_for_costs"] = "security_for_costs"

    @model_validator(mode="after")
    def validate_payment(self) -> IpOppositionSecurityForCostsRecord:
        if self.due_on < self.directed_on:
            raise ValueError("Security-for-costs due date cannot precede its direction.")
        if self.payment_status == "paid" and not all(
            (self.paid_on, (self.payment_reference or "").strip())
        ):
            raise ValueError("Paid security for costs requires payment date and reference.")
        return self


class IpOppositionDispositionReviewRecord(BaseModel):
    trigger_event_id: str
    outcome_kind: Literal[
        "dismissal", "abandonment", "withdrawal", "settlement", "final_decision"
    ]
    affected_application_scope_ids: list[str] = Field(min_length=1, max_length=45)
    recommended_application_disposition: str = Field(min_length=2, max_length=2000)
    review_status: Literal["pending", "confirmed", "not_applicable"]
    review_reference: str = Field(min_length=2, max_length=500)
    no_automatic_application_update: Literal[True] = True


class IpOppositionMadridDesignationRecord(BaseModel):
    application_id: str
    international_registration_number: str = Field(min_length=2, max_length=160)
    wipo_reference: str = Field(min_length=2, max_length=500)
    india_designation_identifier: str = Field(min_length=2, max_length=160)
    designation_status: str = Field(min_length=2, max_length=120)
    lifecycle_source_reference: str = Field(min_length=2, max_length=500)


class IpOppositionSharedActionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    action_kind: Literal[
        "deadline_extended",
        "further_evidence_leave_recorded",
        "evidence_package_recorded",
        "hearing_preparation_recorded",
        "post_hearing_note_recorded",
        "order_recorded",
        "appeal_linked",
        "scope_review_recorded",
        "translation_recorded",
        "hearing_notice_recorded",
        "adjournment_recorded",
        "written_arguments_recorded",
        "attendance_recorded",
        "security_for_costs_recorded",
        "disposition_review_recorded",
        "madrid_designation_link_recorded",
    ]
    source: Literal["manual", "integration", "system"]
    source_reference: str = Field(min_length=2, max_length=255)
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    authorized_confirmation: str = Field(min_length=2, max_length=500)
    evidence_refs: list[str] = Field(min_length=1, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    acknowledged_exception_codes: list[str] = Field(default_factory=list, max_length=100)
    supersedes_action_event_id: str | None = None
    deadline_extension: IpOppositionDeadlineExtension | None = None
    further_evidence_leave: IpOppositionFurtherEvidenceLeave | None = None
    evidence_package: IpOppositionEvidencePackage | None = None
    hearing_preparation: IpOppositionHearingPreparation | None = None
    order_details: IpOppositionOrderDetails | None = None
    appeal_link: IpOppositionAppealLink | None = None
    scope_review: IpOppositionScopeReview | None = None
    translation: IpOppositionTranslationRecord | None = None
    hearing_notice: IpOppositionHearingNoticeRecord | None = None
    adjournment: IpOppositionAdjournmentRecord | None = None
    written_arguments: IpOppositionWrittenArgumentsRecord | None = None
    attendance: IpOppositionAttendanceRecord | None = None
    security_for_costs: IpOppositionSecurityForCostsRecord | None = None
    disposition_review: IpOppositionDispositionReviewRecord | None = None
    madrid_designation: IpOppositionMadridDesignationRecord | None = None

    @model_validator(mode="after")
    def validate_shared_action(self) -> IpOppositionSharedActionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Shared opposition action time must include a timezone.")
        required_field = {
            "deadline_extended": "deadline_extension",
            "further_evidence_leave_recorded": "further_evidence_leave",
            "evidence_package_recorded": "evidence_package",
            "hearing_preparation_recorded": "hearing_preparation",
            "post_hearing_note_recorded": "hearing_preparation",
            "order_recorded": "order_details",
            "appeal_linked": "appeal_link",
            "scope_review_recorded": "scope_review",
            "translation_recorded": "translation",
            "hearing_notice_recorded": "hearing_notice",
            "adjournment_recorded": "adjournment",
            "written_arguments_recorded": "written_arguments",
            "attendance_recorded": "attendance",
            "security_for_costs_recorded": "security_for_costs",
            "disposition_review_recorded": "disposition_review",
            "madrid_designation_link_recorded": "madrid_designation",
        }[self.action_kind]
        detail_fields = {
            "deadline_extension": self.deadline_extension,
            "further_evidence_leave": self.further_evidence_leave,
            "evidence_package": self.evidence_package,
            "hearing_preparation": self.hearing_preparation,
            "order_details": self.order_details,
            "appeal_link": self.appeal_link,
            "scope_review": self.scope_review,
            "translation": self.translation,
            "hearing_notice": self.hearing_notice,
            "adjournment": self.adjournment,
            "written_arguments": self.written_arguments,
            "attendance": self.attendance,
            "security_for_costs": self.security_for_costs,
            "disposition_review": self.disposition_review,
            "madrid_designation": self.madrid_designation,
        }
        if detail_fields[required_field] is None:
            raise ValueError(f"{self.action_kind.replace('_', ' ')} requires {required_field}.")
        unexpected = [
            field_name
            for field_name, value in detail_fields.items()
            if field_name != required_field and value is not None
        ]
        if unexpected:
            raise ValueError("Shared opposition action contains unrelated detail fields.")
        if self.action_kind == "post_hearing_note_recorded" and not (
            self.hearing_preparation and self.hearing_preparation.post_hearing_notes
        ):
            raise ValueError("A post-hearing action requires post-hearing notes.")
        return self


class IpOppositionSharedHearingRecord(BaseModel):
    id: str
    hearing_on: date
    time_status: str
    forum_name: str
    purpose: str
    status: str


class IpOppositionSharedWorkflowResponse(BaseModel):
    proceeding_id: str
    represented_side: Literal["applicant", "opponent"]
    current_stage: str
    shared_actions: list[IpDocketEventResponse]
    active_deadlines: list[IpDeadlineRecord]
    shared_hearings: list[IpOppositionSharedHearingRecord]
    application_scopes: list[IpOppositionApplicationScopeRecord]
    next_required_action: Literal[
        "complete_role_workflow",
        "record_evidence_package",
        "advance_to_hearing",
        "schedule_hearing",
        "record_hearing_preparation",
        "await_hearing",
        "record_post_hearing_note",
        "advance_to_order",
        "record_order",
        "review_appeal_or_close",
        "link_appeal",
        "complete_appeal_or_close",
        "closed",
    ]
