"""Typed contracts for post-registration recordals and their legal projections."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_operations import IpTitleInterestRecord

IpRecordalType = Literal[
    "renewal",
    "restoration",
    "assignment",
    "transmission",
    "name_change",
    "address_change",
    "address_for_service_change",
    "registered_user",
    "licence",
    "association",
    "division",
    "limitation",
    "disclaimer",
    "certified_copy",
    "well_known_mark",
]
IpRecordalStatus = Literal[
    "draft",
    "ready",
    "filed",
    "defective",
    "accepted",
    "rejected",
    "withdrawn",
]
IpRecordalPartyRole = Literal[
    "registered_proprietor",
    "assignor",
    "assignee",
    "transmitter",
    "transmittee",
    "licensor",
    "licensee",
    "registered_user",
    "applicant",
    "subject",
    "authorized_signatory",
]
IpRecordalTransactionKind = Literal[
    "review_approved",
    "filed",
    "acknowledgement_received",
    "defect_noted",
    "corrected",
    "accepted",
    "rejected",
    "withdrawn",
]


class IpRecordalParty(BaseModel):
    role: IpRecordalPartyRole
    name: str = Field(min_length=2, max_length=500)
    identifier: str | None = Field(default=None, max_length=160)
    address: str | None = Field(default=None, max_length=1000)
    evidence_reference: str = Field(min_length=3, max_length=500)


class IpRecordalCreateRequest(BaseModel):
    docket_id: str
    expected_lifecycle_version: int = Field(ge=0)
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    recordal_type: IpRecordalType
    legal_basis: str = Field(min_length=3, max_length=2000)
    form_code: str = Field(min_length=1, max_length=80)
    parties: list[IpRecordalParty] = Field(min_length=1, max_length=50)
    executed_on: date | None = None
    effective_on: date | None = None
    affected_registration_refs: list[str] = Field(min_length=1, max_length=100)
    affected_classes: list[int] = Field(default_factory=list, max_length=45)
    scope_kind: Literal["whole_right", "partial"] = "whole_right"
    scope_details: dict[str, object] = Field(default_factory=dict)
    supporting_instrument_refs: list[str] = Field(min_length=1, max_length=100)
    fee_cost_item_refs: list[str] = Field(default_factory=list, max_length=100)
    deadline_rule_key: str | None = Field(default=None, min_length=3, max_length=160)

    @model_validator(mode="after")
    def validate_recordal_contract(self) -> IpRecordalCreateRequest:
        if self.executed_on and self.effective_on and self.effective_on < self.executed_on:
            raise ValueError("Recordal effective date cannot precede execution date.")
        if len(set(self.affected_classes)) != len(self.affected_classes) or any(
            value < 1 or value > 45 for value in self.affected_classes
        ):
            raise ValueError("Affected classes must be unique Nice class numbers from 1 to 45.")
        if self.scope_kind == "partial" and not self.affected_classes:
            raise ValueError("A partial recordal must identify its affected classes.")
        if self.deadline_rule_key and "opposition" in self.deadline_rule_key.casefold():
            raise ValueError("Post-registration recordals cannot use an opposition deadline rule.")
        supporting_refs = set(self.supporting_instrument_refs)
        if any(party.evidence_reference not in supporting_refs for party in self.parties):
            raise ValueError(
                "Every recordal party must cite one of the supporting instrument references."
            )

        title_bearing_types = {"assignment", "transmission", "licence", "registered_user"}
        if self.recordal_type in title_bearing_types and self.effective_on is None:
            raise ValueError("Ownership and licence recordals require an effective date.")
        if self.recordal_type in title_bearing_types and self.executed_on is None:
            raise ValueError("Ownership and licence recordals require an execution date.")

        roles = {party.role for party in self.parties}
        if self.recordal_type == "assignment" and not {"assignor", "assignee"}.issubset(roles):
            raise ValueError("An assignment requires assignor and assignee parties.")
        if self.recordal_type == "transmission" and not {
            "transmitter",
            "transmittee",
        }.issubset(roles):
            raise ValueError("A transmission requires transmitter and transmittee parties.")
        if self.recordal_type == "licence" and not {"licensor", "licensee"}.issubset(roles):
            raise ValueError("A licence requires licensor and licensee parties.")
        if self.recordal_type == "registered_user" and "registered_user" not in roles:
            raise ValueError("A registered-user recordal requires a registered-user party.")
        return self


class IpRecordalTransactionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    transaction_kind: IpRecordalTransactionKind
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    source_url: HttpUrl | None = None
    source_reference: str | None = Field(default=None, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    deadline_refs: list[str] = Field(default_factory=list, max_length=100)
    cost_item_refs: list[str] = Field(default_factory=list, max_length=100)
    registry_snapshot_id: str | None = None
    registry_recorded_on: date | None = None
    details: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transaction_contract(self) -> IpRecordalTransactionRequest:
        if self.effective_at.utcoffset() is None:
            raise ValueError("Recordal transaction time must include a timezone.")
        if (
            self.transaction_kind in {"filed", "defect_noted", "corrected", "rejected"}
            and not self.evidence_refs
        ):
            raise ValueError(f"{self.transaction_kind} requires evidence.")
        if self.transaction_kind == "corrected" and not self.document_refs:
            raise ValueError("Corrected recordal requires a docket-linked corrected instrument.")
        if self.transaction_kind == "accepted":
            if not self.evidence_refs:
                raise ValueError("Accepted recordal requires acceptance evidence.")
            if not self.source_url or not (self.source_reference or "").strip():
                raise ValueError("Accepted recordal requires registry source URL and reference.")
            if not self.registry_snapshot_id:
                raise ValueError("Accepted recordal requires a registry snapshot.")
            if not self.registry_recorded_on:
                raise ValueError("Accepted recordal requires its registry-recorded date.")
        if self.registry_snapshot_id and self.transaction_kind != "accepted":
            raise ValueError("Registry snapshot can only be applied by an accepted transaction.")
        if self.registry_recorded_on and self.transaction_kind != "accepted":
            raise ValueError("Registry-recorded date can only be set by an accepted transaction.")
        if self.source_url and not (self.source_reference or "").strip():
            raise ValueError("A recordal source URL requires its source reference.")
        return self


class IpRecordalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    recordal_type: str
    legal_basis: str
    form_code: str
    parties_json: list[dict[str, object]]
    executed_on: date | None
    effective_on: date | None
    affected_registration_refs_json: list[str]
    affected_classes_json: list[int]
    scope_json: dict[str, object]
    supporting_instrument_refs_json: list[str]
    fee_cost_item_refs_json: list[str]
    filing_evidence_refs_json: list[str]
    acceptance_evidence_refs_json: list[str]
    deadline_rule_key: str | None
    registry_snapshot_id: str | None
    status: str
    version: int
    created_by_membership_id: str
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpRecordalPageResponse(BaseModel):
    items: list[IpRecordalResponse]
    total: int
    limit: int
    offset: int


class IpRecordalTransactionResponse(BaseModel):
    recordal: IpRecordalResponse
    event: IpDocketEventResponse
    projected_title_interests: list[IpTitleInterestRecord] = Field(default_factory=list)
    registry_projection_applied: bool = False


class IpRecordalWorkspaceResponse(BaseModel):
    recordal: IpRecordalResponse
    transactions: list[IpDocketEventResponse]
    title_interests: list[IpTitleInterestRecord]
    current_registered_interests: list[IpTitleInterestRecord]
    pending_interests: list[IpTitleInterestRecord]
