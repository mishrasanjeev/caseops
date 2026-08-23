from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_records import IpIdentifierResponse, IpProceedingResponse


class IpOppositionPartyInput(BaseModel):
    role: Literal["applicant", "opponent", "agent", "counsel"]
    party_name: str = Field(min_length=2, max_length=255)
    source: str = Field(min_length=2, max_length=120)


class IpOppositionPartyRecord(IpOppositionPartyInput):
    model_config = ConfigDict(from_attributes=True)

    role: Literal["applicant", "opponent", "agent", "counsel"] = Field(
        validation_alias="role_kind"
    )
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
        if self.client_instruction_state == "confirmed" and not (
            self.client_instruction_reference or ""
        ).strip():
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
