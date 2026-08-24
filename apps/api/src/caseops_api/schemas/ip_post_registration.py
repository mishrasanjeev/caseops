from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_records import IpIdentifierResponse, IpProceedingResponse

PostRegistrationKind = Literal["rectification", "cancellation", "non_use_removal"]


class IpPostRegistrationScope(BaseModel):
    class_number: int = Field(ge=1, le=45)
    goods_services_segment: str = Field(min_length=3, max_length=4000)


class IpPostRegistrationRuleMap(BaseModel):
    template_key: str = Field(min_length=5, max_length=120)
    template_version: str = Field(min_length=1, max_length=80)
    authority_reference: str = Field(min_length=3, max_length=500)
    source_reference: str = Field(min_length=3, max_length=500)
    mutatis_mutandis: bool = False
    mapped_from_rule: str | None = Field(default=None, max_length=500)
    mapped_provisions: list[str] = Field(default_factory=list, max_length=100)
    excluded_provisions: list[str] = Field(default_factory=list, max_length=100)
    lawyer_confirmation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_mapping(self) -> IpPostRegistrationRuleMap:
        mapped = bool(
            self.mapped_from_rule
            or self.mapped_provisions
            or self.excluded_provisions
            or self.lawyer_confirmation
        )
        if self.mutatis_mutandis and not all(
            (
                (self.mapped_from_rule or "").strip(),
                self.mapped_provisions,
                self.excluded_provisions,
                (self.lawyer_confirmation or "").strip(),
            )
        ):
            raise ValueError(
                "Mutatis-mutandis use requires the source rule, mapped and excluded "
                "provisions, and lawyer confirmation."
            )
        if not self.mutatis_mutandis and mapped:
            raise ValueError(
                "Rule-mapping details require mutatis_mutandis to be explicitly enabled."
            )
        return self


class IpPostRegistrationProfile(BaseModel):
    proceeding_type: PostRegistrationKind
    legal_basis: str = Field(min_length=5, max_length=2000)
    target_right_reference: str = Field(min_length=2, max_length=500)
    applicant_name: str = Field(min_length=2, max_length=500)
    respondent_name: str = Field(min_length=2, max_length=500)
    challenged_scope: list[IpPostRegistrationScope] = Field(min_length=1, max_length=45)
    grounds: list[str] = Field(min_length=1, max_length=100)
    forum: str = Field(min_length=2, max_length=500)
    form_key: str = Field(min_length=2, max_length=80)
    fee_status: Literal["required", "paid", "not_required", "manual_review"]
    fee_reference: str | None = Field(default=None, max_length=500)
    service_status: Literal["not_started", "prepared", "served", "not_required"]
    service_reference: str | None = Field(default=None, max_length=500)
    rule_map: IpPostRegistrationRuleMap
    lawyer_confirmed_by_membership_id: str = ""

    @model_validator(mode="after")
    def validate_package(self) -> IpPostRegistrationProfile:
        if self.fee_status == "paid" and not (self.fee_reference or "").strip():
            raise ValueError("Paid fee status requires a fee reference.")
        if self.service_status == "served" and not (self.service_reference or "").strip():
            raise ValueError("Served status requires a service reference.")
        if any(not ground.strip() for ground in self.grounds):
            raise ValueError("Grounds cannot contain blank entries.")
        return self


class IpPostRegistrationWorkspaceUpsertRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    expected_profile_event_id: str | None = None
    effective_at: datetime
    responsible_membership_id: str
    source: Literal["manual", "registry", "integration", "system"]
    source_reference: str = Field(min_length=2, max_length=255)
    reason: str = Field(min_length=5, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(min_length=1, max_length=100)
    profile: IpPostRegistrationProfile

    @model_validator(mode="after")
    def validate_time(self) -> IpPostRegistrationWorkspaceUpsertRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Profile effective time must include a timezone.")
        return self


class IpPostRegistrationActionRequest(BaseModel):
    expected_lifecycle_version: int = Field(ge=0)
    expected_proceeding_version: int = Field(ge=1)
    action_kind: Literal[
        "stage_update",
        "parallel_proceeding_link",
        "interim_stay",
        "stay_lifted",
        "order_recorded",
        "closure",
        "disposition_candidate",
        "disposition_review",
    ]
    effective_at: datetime
    responsible_membership_id: str
    source: Literal["manual", "registry", "integration", "system"]
    source_reference: str = Field(min_length=2, max_length=255)
    reason: str = Field(min_length=5, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    stage: str | None = Field(default=None, max_length=64)
    authority_reference: str | None = Field(default=None, max_length=500)
    parallel_proceeding_id: str | None = None
    legal_effect: str | None = Field(default=None, max_length=2000)
    legal_effective_date: date | None = None
    candidate_disposition: (
        Literal["rectify_registration", "cancel_registration", "remove_for_non_use", "no_change"]
        | None
    ) = None
    candidate_event_id: str | None = None
    review_decision: Literal["approved", "rejected"] | None = None
    authorized_confirmation: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_action(self) -> IpPostRegistrationActionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Action effective time must include a timezone.")
        source_evidence = bool(self.evidence_refs or self.document_refs)
        if self.action_kind in {"interim_stay", "stay_lifted", "order_recorded"} and not all(
            ((self.authority_reference or "").strip(), source_evidence)
        ):
            raise ValueError("Court or registry orders require authority and source evidence.")
        if self.action_kind == "stage_update" and not (self.stage or "").strip():
            raise ValueError("Stage updates require a stage.")
        if self.action_kind == "parallel_proceeding_link" and not self.parallel_proceeding_id:
            raise ValueError("Parallel proceeding links require a distinct proceeding id.")
        if self.action_kind == "closure" and not all(
            (
                self.stage in {"withdrawn", "settled", "closed"},
                (self.legal_effect or "").strip(),
                self.legal_effective_date,
                source_evidence,
                (self.authorized_confirmation or "").strip(),
            )
        ):
            raise ValueError(
                "Closure requires its type, legal effect and date, evidence, and "
                "authorized confirmation."
            )
        if self.action_kind == "disposition_candidate" and not all(
            (
                self.candidate_disposition,
                (self.legal_effect or "").strip(),
                source_evidence,
            )
        ):
            raise ValueError(
                "Disposition candidates require a proposed effect and source evidence."
            )
        if self.action_kind == "disposition_review" and not all(
            (
                self.candidate_event_id,
                self.review_decision,
                (self.authorized_confirmation or "").strip(),
            )
        ):
            raise ValueError(
                "Disposition review requires a candidate, decision, and authorized confirmation."
            )
        return self


class IpPostRegistrationWorkspaceResponse(BaseModel):
    proceeding: IpProceedingResponse
    profile: IpPostRegistrationProfile | None
    profile_event: IpDocketEventResponse | None
    profile_revision_count: int
    identifiers: list[IpIdentifierResponse]
    action_events: list[IpDocketEventResponse]
    active_stay: bool
    ready_for_stage_progression: bool
    readiness_gaps: list[str]
    registration_disposition_is_automatic: Literal[False] = False
