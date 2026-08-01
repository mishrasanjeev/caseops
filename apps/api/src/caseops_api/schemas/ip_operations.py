from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrademarkClassScope(BaseModel):
    class_number: int = Field(ge=1, le=45)
    specification: str = Field(min_length=3, max_length=4000)


class TrademarkParty(BaseModel):
    role: Literal["applicant", "owner", "priority_claimant", "agent"]
    name: str = Field(min_length=2, max_length=255)
    address: str | None = Field(default=None, max_length=1000)
    country: str | None = Field(default=None, max_length=120)


class FilingManifestItem(BaseModel):
    key: str = Field(min_length=2, max_length=80)
    label: str = Field(min_length=2, max_length=160)
    required: bool = True
    evidence_reference: str | None = Field(default=None, max_length=500)


class TrademarkParticularPayload(BaseModel):
    form_key: str = Field(default="TM-A", min_length=2, max_length=80)
    form_version: str = Field(default="2026.1", min_length=1, max_length=40)
    mark_kind: Literal["word", "device", "composite", "shape", "sound", "other"]
    representation: dict = Field(default_factory=dict)
    classes: list[TrademarkClassScope] = Field(min_length=1, max_length=45)
    use_priority: dict | None = None
    parties: list[TrademarkParty] = Field(min_length=1, max_length=30)
    agent: dict | None = None
    filing_manifest: list[FilingManifestItem] = Field(default_factory=list, max_length=80)

    @model_validator(mode="after")
    def unique_classes(self) -> TrademarkParticularPayload:
        values = [row.class_number for row in self.classes]
        if len(values) != len(set(values)):
            raise ValueError("Trademark class numbers must be unique.")
        return self


class IpDocketCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    matter_id: str | None = None
    primary_identifier: str | None = Field(default=None, max_length=120)
    restricted: bool = False
    particulars: TrademarkParticularPayload


class IpDocketVersionCreateRequest(TrademarkParticularPayload):
    expected_current_version: int = Field(ge=1)
    finalize: bool = False


class TrademarkParticularVersionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    version: int
    form_key: str
    form_version: str
    mark_kind: str
    representation_json: dict
    classes_json: list
    use_priority_json: dict | None
    parties_json: list
    agent_json: dict | None
    filing_manifest_json: list
    readiness_status: str
    readiness_errors_json: list
    finalized_at: datetime | None
    created_at: datetime


class IpNoticeLinkCreateRequest(BaseModel):
    notice_id: str
    link_kind: Literal["correspondence", "service", "instruction", "official_notice"]
    accepted_effect: str | None = Field(default=None, max_length=80)


class IpNoticeLinkRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    notice_id: str
    link_kind: str
    accepted_effect: str | None
    created_at: datetime


class IpEvidenceCandidateRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    source_type: str
    source_id: str
    source_fingerprint: str
    evidence_kind: str
    suggested_link_kind: str
    status: str
    accepted_effect: str | None
    duplicate_of_candidate_id: str | None
    metadata_json: dict | None
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    created_at: datetime


class IpEvidenceDiscoveryResponse(BaseModel):
    candidates: list[IpEvidenceCandidateRecord]
    discovered_count: int
    duplicate_count: int


class IpEvidenceCandidateReviewRequest(BaseModel):
    expected_status: Literal["needs_review", "duplicate"]
    action: Literal["accept", "reject"]
    link_kind: Literal["correspondence", "service", "instruction", "official_notice"] | None = None
    accepted_effect: str | None = Field(default=None, max_length=80)


class IpDeadlineCoverageCreateRequest(BaseModel):
    matter_deadline_id: str
    responsible_membership_id: str
    backup_membership_id: str | None = None
    coverage_status: Literal["accepted", "pending", "reassigned"] = "accepted"


class IpDeadlineCoverageReassignRequest(BaseModel):
    expected_responsible_membership_id: str
    responsible_membership_id: str
    backup_membership_id: str | None = None
    reason: str = Field(min_length=5, max_length=500)


class IpDeadlineCoverageRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_deadline_id: str
    responsible_membership_id: str
    backup_membership_id: str | None
    coverage_status: str
    calendar_projection_status: str
    accepted_at: datetime | None
    reassignment_version: int
    created_at: datetime
    updated_at: datetime


class IpCoverageBulkReassignRequest(BaseModel):
    from_membership_id: str
    to_membership_id: str
    reason: str = Field(min_length=5, max_length=500)
    expected_versions: dict[str, int] = Field(default_factory=dict)


class IpCoverageBulkReassignResponse(BaseModel):
    reassigned_count: int
    responsible_count: int
    backup_count: int
    coverage_ids: list[str]


class IpDeadlineIncidentCreateRequest(BaseModel):
    matter_deadline_id: str | None = None
    severity: Literal["low", "medium", "high", "critical"]
    summary: str = Field(min_length=5, max_length=500)
    impact: dict = Field(default_factory=dict)
    containment: str | None = Field(default=None, max_length=4000)
    correction_deadline_id: str | None = None


class IpDeadlineIncidentVerifyRequest(BaseModel):
    corrective_action: str = Field(min_length=5, max_length=4000)


class IpDeadlineIncidentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_deadline_id: str | None
    severity: str
    summary: str
    impact_json: dict
    containment: str | None
    correction_deadline_id: str | None
    status: str
    corrective_action: str | None
    verified_at: datetime | None
    created_at: datetime


class IpTitleInterestCreateRequest(BaseModel):
    interest_type: Literal["ownership", "assignment", "licence", "encumbrance", "security"]
    party_name: str = Field(min_length=2, max_length=255)
    effective_from: date
    effective_until: date | None = None
    related_docket_id: str | None = None
    evidence_reference: str = Field(min_length=3, max_length=500)
    recordal_status: Literal["not_required", "pending", "filed", "recorded", "rejected"] = (
        "not_required"
    )

    @model_validator(mode="after")
    def valid_dates(self) -> IpTitleInterestCreateRequest:
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("effective_until cannot precede effective_from.")
        return self


class IpTitleInterestRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    interest_type: str
    party_name: str
    effective_from: date
    effective_until: date | None
    related_docket_id: str | None
    evidence_reference: str
    recordal_status: str
    conflict_flags_json: list
    created_at: datetime


class IpRelatedRightObligationCreateRequest(BaseModel):
    title_interest_id: str | None = None
    obligation_type: Literal[
        "renewal",
        "royalty",
        "recordal",
        "consent",
        "quality_control",
        "termination",
        "other",
    ]
    title: str = Field(min_length=3, max_length=255)
    due_on: date | None = None
    owner_membership_id: str
    matter_deadline_id: str | None = None
    evidence_reference: str = Field(min_length=3, max_length=500)


class IpRelatedRightObligationCompleteRequest(BaseModel):
    expected_status: Literal["open"] = "open"
    completion_evidence_reference: str = Field(min_length=3, max_length=500)


class IpRelatedRightObligationRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    title_interest_id: str | None
    obligation_type: str
    title: str
    due_on: date | None
    owner_membership_id: str
    matter_deadline_id: str | None
    status: str
    evidence_reference: str
    completion_evidence_reference: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class IpCostItemCreateRequest(BaseModel):
    category: Literal["official_fee", "professional_fee", "associate_fee", "disbursement", "other"]
    description: str = Field(min_length=3, max_length=500)
    amount_minor: int = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    evidence_reference: str = Field(min_length=3, max_length=500)
    billing_link_type: Literal["invoice", "invoice_line_item", "time_entry"] | None = None
    billing_link_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def complete_billing_link(self) -> IpCostItemCreateRequest:
        if bool(self.billing_link_type) != bool(self.billing_link_id):
            raise ValueError("billing_link_type and billing_link_id must be supplied together.")
        return self


class IpCostItemRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category: str
    description: str
    amount_minor: int
    currency: str
    evidence_reference: str
    billing_link_type: str | None
    billing_link_id: str | None
    reconciliation_status: str
    canonical_amount_minor: int | None
    reconciliation_difference_minor: int | None
    reconciled_at: datetime | None
    created_at: datetime


class IpCostReconciliationRow(BaseModel):
    cost_item_id: str
    billing_link_type: str | None
    billing_link_id: str | None
    evidence_amount_minor: int
    canonical_amount_minor: int | None
    difference_minor: int | None
    currency: str
    status: Literal["matched", "mismatch", "missing", "unlinked"]


class IpCostReconciliationReport(BaseModel):
    generated_at: datetime
    docket_id: str
    accounting_owner: Literal["matter_billing"] = "matter_billing"
    rows: list[IpCostReconciliationRow]
    matched_count: int
    mismatch_count: int
    missing_count: int
    unlinked_count: int
    checksum_sha256: str


class IpDocketRecordResponse(BaseModel):
    id: str
    company_id: str
    matter_id: str | None
    record_type: str
    title: str
    primary_identifier: str | None
    status: str
    restricted: bool
    current_version: int
    current_particulars: TrademarkParticularVersionRecord
    notice_links: list[IpNoticeLinkRecord] = Field(default_factory=list)
    evidence_candidates: list[IpEvidenceCandidateRecord] = Field(default_factory=list)
    deadline_coverages: list[IpDeadlineCoverageRecord] = Field(default_factory=list)
    deadline_incidents: list[IpDeadlineIncidentRecord] = Field(default_factory=list)
    title_interests: list[IpTitleInterestRecord] = Field(default_factory=list)
    related_right_obligations: list[IpRelatedRightObligationRecord] = Field(default_factory=list)
    cost_items: list[IpCostItemRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class IpDocketListResponse(BaseModel):
    dockets: list[IpDocketRecordResponse]
    count: int


class IpDocketControlReport(BaseModel):
    generated_at: datetime
    docket_count: int
    ready_count: int
    uncovered_deadline_count: int
    open_incident_count: int
    unprojected_calendar_count: int
    inactive_coverage_count: int
    total_cost_minor_by_currency: dict[str, int]


__all__ = [
    name
    for name in globals()
    if name.startswith("Ip") or name.startswith("Trademark") or name == "FilingManifestItem"
]
