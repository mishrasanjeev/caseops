from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_records import (
    IpApplicationNumberCreate,
    IpAssetResponse,
    IpIdentifierResponse,
    IpWorkspaceConfigurationStatusResponse,
    TrademarkApplicationResponse,
)


class IpFeatureReadinessRecord(BaseModel):
    feature_id: str
    available: bool
    reason: Literal[
        "available",
        "unknown_feature",
        "missing_capability",
        "missing_entitlement",
        "rollout_disabled",
        "rollout_expired",
        "workspace_not_configured",
        "tenant_disabled",
        "readiness_test_failed",
        "incident_kill_switch",
    ]
    owner: str
    required_capabilities: list[str]
    missing_capabilities: list[str]
    entitlement_key: str | None
    entitled: bool
    rollout_flag: str | None
    rollout_enabled: bool
    rollout_expires_at: datetime | None
    manual_fallback_feature_id: str | None
    blocked_by_incident_id: str | None = None


class IpWorkspaceReadinessResponse(BaseModel):
    timezone: str
    workspace_available: bool
    manual_docketing_available: bool
    configuration_status: IpWorkspaceConfigurationStatusResponse
    features: list[IpFeatureReadinessRecord]


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
    mark_kind: Literal[
        "word",
        "device",
        "composite",
        "label",
        "colour",
        "shape",
        "sound",
        "other",
    ]
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


class ManualTrademarkApplicationCreateRequest(BaseModel):
    """One manual command for the canonical docket, asset, application and number."""

    title: str = Field(min_length=2, max_length=255)
    matter_id: str | None = None
    restricted: bool = False
    asset_title: str = Field(min_length=2, max_length=255)
    jurisdiction: str = Field(min_length=2, max_length=40)
    office: str = Field(min_length=2, max_length=80)
    filing_phase: Literal["draft", "pre_filing", "filed"] = "draft"
    source_pending_identifier_allocation: bool = False
    application_number: IpApplicationNumberCreate | None = None
    particulars: TrademarkParticularPayload

    @model_validator(mode="after")
    def validate_identifier_allocation(self) -> ManualTrademarkApplicationCreateRequest:
        if self.application_number is not None and self.source_pending_identifier_allocation:
            raise ValueError(
                "application_number and source_pending_identifier_allocation are mutually exclusive"
            )
        return self


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
    # Same reconciliation as the bulk path: responsibility for a filing date is
    # taken, not assigned. Backup naming stays immediate — a backup is not the
    # accountable party until responsibility actually moves to them.
    transfer_mode: Literal["proposed", "immediate"] = "proposed"
    escalation_membership_id: str | None = None


class IpDeadlineCoverageRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_deadline_id: str
    responsible_membership_id: str
    backup_membership_id: str | None
    coverage_status: str
    pending_replacement_membership_id: str | None = None
    replacement_decision: str = "none"
    replacement_decided_at: datetime | None = None
    replacement_decision_reason: str | None = None
    emergency_until: datetime | None = None
    emergency_escalation_membership_id: str | None = None
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
    # CAL-OPS-08 requires an *accepted* replacement, so a routine transfer is a
    # proposal. `immediate` exists only for departure and emergency, where the
    # outgoing person cannot be waited on; it still requires acknowledgement and
    # an escalation owner, and it never records an acceptance nobody gave.
    transfer_mode: Literal["proposed", "immediate"] = "proposed"
    escalation_membership_id: str | None = None


class IpCoverageBulkReassignResponse(BaseModel):
    reassigned_count: int
    responsible_count: int
    backup_count: int
    coverage_ids: list[str]
    transfer_mode: Literal["proposed", "immediate"] = "proposed"
    # Rows awaiting the replacement's decision. In `proposed` mode responsibility
    # has not moved for these; in `immediate` mode it has, pending acknowledgement.
    pending_count: int = 0


class IpIncidentEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calculation_version_refs: list[str] = Field(default_factory=list, max_length=100)
    rule_version_refs: list[str] = Field(default_factory=list, max_length=100)
    calendar_version_refs: list[str] = Field(default_factory=list, max_length=100)
    source_refs: list[str] = Field(default_factory=list, max_length=200)
    message_refs: list[str] = Field(default_factory=list, max_length=200)
    provider_event_refs: list[str] = Field(default_factory=list, max_length=200)
    audit_refs: list[str] = Field(default_factory=list, max_length=200)


class IpDeadlineIncidentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matter_deadline_id: str | None = None
    severity: Literal["low", "medium", "high", "critical"]
    summary: str = Field(min_length=5, max_length=500)
    impact: dict = Field(default_factory=dict)
    containment: str | None = Field(default=None, max_length=4000)
    correction_deadline_id: str | None = None
    defect_scope: Literal[
        "record_specific", "shared_rule", "shared_source", "platform_wide"
    ] = "record_specific"
    defect_fingerprint: str | None = Field(default=None, min_length=3, max_length=500)
    evidence_snapshot: IpIncidentEvidenceSnapshot = Field(
        default_factory=IpIncidentEvidenceSnapshot
    )
    kill_switch_features: list[str] = Field(default_factory=list, max_length=20)
    kill_switch_evidence_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_platform_containment(self) -> IpDeadlineIncidentCreateRequest:
        if len(self.kill_switch_features) != len(set(self.kill_switch_features)):
            raise ValueError("kill_switch_features must not contain duplicates.")
        if self.defect_scope == "platform_wide":
            if not self.kill_switch_features:
                raise ValueError("Platform-wide incidents require at least one kill switch.")
            if not self.kill_switch_evidence_reference:
                raise ValueError("Platform-wide incidents require kill-switch evidence.")
        elif self.kill_switch_features:
            raise ValueError("Kill switches are restricted to platform-wide incidents.")
        return self


class IpDeadlineIncidentImpactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_type: str = Field(min_length=2, max_length=40)
    record_reference: str = Field(min_length=1, max_length=500)
    relationship: str = Field(min_length=2, max_length=120)
    assessment: Literal["affected", "not_affected", "pending"]
    scan_method: str = Field(min_length=2, max_length=80)
    evidence_reference: str = Field(min_length=3, max_length=500)


class IpDeadlineIncidentImpactScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[IpDeadlineIncidentImpactItem] = Field(min_length=1, max_length=500)
    complete: bool = False


class IpDeadlineIncidentActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_type: Literal[
        "containment", "corrective_task", "filing", "external_advice", "prevention"
    ]
    action_status: Literal["planned", "completed", "not_available"]
    action_reference: str = Field(min_length=3, max_length=500)
    details: str = Field(min_length=5, max_length=4000)
    evidence_reference: str = Field(min_length=3, max_length=500)


class IpDeadlineIncidentNotificationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_type: Literal["client", "insurer", "regulator", "court", "external_counsel"]
    recipient_reference: str = Field(min_length=1, max_length=500)
    decision: Literal["pending", "notify", "do_not_notify", "not_applicable"]
    rationale: str = Field(min_length=5, max_length=4000)
    approval_evidence_reference: str = Field(min_length=3, max_length=500)
    communication_reference: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_communication_reference(
        self,
    ) -> IpDeadlineIncidentNotificationDecisionRequest:
        if self.decision == "notify" and not self.communication_reference:
            raise ValueError("Notify decisions require a communication reference.")
        return self


class IpDeadlineIncidentVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: Literal["verified", "disproved"] = "verified"
    corrective_action: str = Field(min_length=5, max_length=4000)
    root_cause: str = Field(min_length=5, max_length=4000)
    preventive_action: str = Field(min_length=5, max_length=4000)
    resolution_evidence_reference: str = Field(min_length=3, max_length=500)


class IpIncidentKillSwitchReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    release_reason: str = Field(min_length=5, max_length=4000)
    release_evidence_reference: str = Field(min_length=3, max_length=500)


class IpDeadlineIncidentImpactRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    record_type: str
    record_reference_sha256: str
    relationship: str
    assessment: str
    scan_method: str
    evidence_reference: str
    assessed_by_membership_id: str
    assessed_at: datetime


class IpDeadlineIncidentActionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    action_type: str
    action_status: str
    action_reference: str
    details: str
    evidence_reference: str
    recorded_by_membership_id: str
    recorded_at: datetime


class IpDeadlineIncidentNotificationDecisionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    recipient_type: str
    recipient_reference_sha256: str
    decision: str
    decision_version: int
    rationale: str
    approval_evidence_reference: str
    communication_reference: str | None
    decided_by_membership_id: str
    decided_at: datetime


class IpIncidentKillSwitchRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    feature_id: str
    status: str
    reason: str
    activation_evidence_reference: str
    activated_by_membership_id: str
    activated_at: datetime
    release_reason: str | None
    release_evidence_reference: str | None
    released_by_membership_id: str | None
    released_at: datetime | None
    version: int


class IpDeadlineIncidentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_deadline_id: str | None
    severity: str
    summary: str
    impact_json: dict
    evidence_snapshot_json: dict
    preservation_manifest_sha256: str
    defect_scope: str
    defect_fingerprint_sha256: str | None
    containment: str | None
    correction_deadline_id: str | None
    status: str
    impact_scan_completed_at: datetime | None
    corrective_action: str | None
    root_cause: str | None
    preventive_action: str | None
    prevention_verified_at: datetime | None
    resolution_evidence_reference: str | None
    resolved_at: datetime | None
    verified_at: datetime | None
    version: int
    impacts: list[IpDeadlineIncidentImpactRecord] = Field(default_factory=list)
    actions: list[IpDeadlineIncidentActionRecord] = Field(default_factory=list)
    notification_decisions: list[IpDeadlineIncidentNotificationDecisionRecord] = Field(
        default_factory=list
    )
    kill_switches: list[IpIncidentKillSwitchRecord] = Field(default_factory=list)
    created_at: datetime


class IpTitleInterestCreateRequest(BaseModel):
    interest_type: Literal["ownership", "assignment", "licence", "encumbrance", "security"]
    party_name: str = Field(min_length=2, max_length=255)
    party_role: str | None = Field(default=None, min_length=2, max_length=40)
    executed_on: date | None = None
    effective_from: date
    effective_until: date | None = None
    related_docket_id: str | None = None
    scope: dict[str, object] = Field(default_factory=dict)
    evidence_reference: str = Field(min_length=3, max_length=500)
    recordal_status: Literal[
        "not_required", "pending", "filed", "recorded", "rejected", "withdrawn"
    ] = "not_required"

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
    party_role: str | None
    executed_on: date | None
    effective_from: date
    effective_until: date | None
    related_docket_id: str | None
    source_recordal_id: str | None
    scope_json: dict[str, object]
    evidence_reference: str
    recordal_status: str
    registry_recorded_on: date | None
    conflict_flags_json: list
    version: int
    created_at: datetime
    updated_at: datetime


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
    #: The amount exactly as incurred. When the ``fx_*`` block is supplied this
    #: remains the ORIGINAL amount and currency (UJ-52-EXC-02).
    amount_minor: int = Field(ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    evidence_reference: str = Field(min_length=3, max_length=500)
    billing_link_type: Literal["invoice", "invoice_line_item", "time_entry"] | None = None
    billing_link_id: str | None = Field(default=None, max_length=64)
    #: UJ-52-EXC-01. A cost on a docket with no billing Matter must be declared
    #: nonbillable; the caller states the billing decision, it is never guessed.
    billable: bool = True
    #: UJ-52-EXC-04. A provider's quote is not an expense.
    cost_nature: Literal["actual", "estimate"] = "actual"
    #: UJ-52-EXC-05. Withhold the amount from readers without ``ip:fees_manage``.
    rate_confidential: bool = False
    #: UJ-52-EXC-02. Supplied together or not at all.
    fx_rate: Decimal | None = Field(default=None, gt=0)
    fx_rate_source: str | None = Field(default=None, min_length=2, max_length=120)
    fx_converted_at: datetime | None = None
    base_amount_minor: int | None = Field(default=None, ge=0)
    base_currency: str | None = Field(default=None, min_length=3, max_length=3)

    @model_validator(mode="after")
    def complete_billing_link(self) -> IpCostItemCreateRequest:
        if bool(self.billing_link_type) != bool(self.billing_link_id):
            raise ValueError("billing_link_type and billing_link_id must be supplied together.")
        return self

    @model_validator(mode="after")
    def complete_conversion(self) -> IpCostItemCreateRequest:
        """A partial conversion preserves nothing, so refuse it outright."""

        supplied = {
            "fx_rate": self.fx_rate is not None,
            "fx_rate_source": self.fx_rate_source is not None,
            "fx_converted_at": self.fx_converted_at is not None,
            "base_amount_minor": self.base_amount_minor is not None,
            "base_currency": self.base_currency is not None,
        }
        if any(supplied.values()) and not all(supplied.values()):
            missing = sorted(name for name, present in supplied.items() if not present)
            raise ValueError(
                "An exchange conversion must preserve the original amount, rate, "
                f"source and time together; missing: {', '.join(missing)}."
            )
        if self.base_currency is not None and self.base_currency.upper() == self.currency.upper():
            raise ValueError("A conversion must target a different currency than the original.")
        return self

    @model_validator(mode="after")
    def estimate_is_not_an_expense(self) -> IpCostItemCreateRequest:
        if self.cost_nature == "estimate" and self.billing_link_type is not None:
            raise ValueError(
                "A provider estimate is not an actual expense and cannot be linked "
                "to a Matter billing record."
            )
        if not self.billable and self.billing_link_type is not None:
            raise ValueError("A nonbillable cost cannot be linked to a Matter billing record.")
        return self


class IpCostItemRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    matter_id: str | None
    category: str
    description: str
    #: ``None`` when the row is rate-confidential and the reader does not hold
    #: ``ip:fees_manage``. ``amount_withheld`` says which of the two it is, so a
    #: withheld rate can never be misread as a zero or absent cost.
    amount_minor: int | None
    currency: str
    billable: bool
    cost_nature: str
    rate_confidential: bool
    amount_withheld: bool = False
    fx_rate: Decimal | None = None
    fx_rate_source: str | None = None
    fx_converted_at: datetime | None = None
    base_amount_minor: int | None = None
    base_currency: str | None = None
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
    #: ``comparison_amount_minor``/``comparison_currency`` are what was actually
    #: compared against the ledger. They equal the evidence amount unless the
    #: cost preserves a conversion, in which case the converted amount is the
    #: only one the ledger could match (UJ-52-EXC-02).
    comparison_amount_minor: int
    comparison_currency: str
    #: ``estimate`` and ``nonbillable`` are terminal, not stages: neither can
    #: become ``matched``, because neither belongs in the client ledger.
    status: Literal["matched", "mismatch", "missing", "unlinked", "estimate", "nonbillable"]


class IpCostReconciliationReport(BaseModel):
    generated_at: datetime
    docket_id: str
    accounting_owner: Literal["matter_billing"] = "matter_billing"
    rows: list[IpCostReconciliationRow]
    matched_count: int
    mismatch_count: int
    missing_count: int
    unlinked_count: int
    estimate_count: int = 0
    nonbillable_count: int = 0
    checksum_sha256: str


class IpDocketRecordResponse(BaseModel):
    id: str
    company_id: str
    matter_id: str | None
    record_type: str
    title: str
    primary_identifier: str | None
    status: str
    is_active: bool
    lifecycle_version: int
    lifecycle_effective_at: datetime | None
    lifecycle_reason: str | None
    lifecycle_outcome: str | None
    lifecycle_source: str | None
    lifecycle_evidence_ref: str | None
    successor_docket_id: str | None
    restricted: bool
    access_policy_version: int
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


class ManualTrademarkApplicationCreateResponse(BaseModel):
    docket: IpDocketRecordResponse
    asset: IpAssetResponse
    application: TrademarkApplicationResponse
    identifier: IpIdentifierResponse | None
    duplicate_candidates: list[IpIdentifierResponse] = Field(default_factory=list)


class IpDocketListResponse(BaseModel):
    dockets: list[IpDocketRecordResponse]
    count: int
    has_more: bool = False


class IpDocketControlRow(BaseModel):
    """One visible docket's deadline-control posture."""

    docket_id: str
    docket_title: str
    primary_identifier: str | None
    docket_status: str
    deadline_coverage_count: int
    uncovered_deadline: bool
    open_incident_count: int
    unprojected_calendar_count: int
    inactive_coverage_count: int


class IpDocketControlReport(BaseModel):
    generated_at: datetime
    source_cutoff: datetime | None = None
    docket_count: int
    ready_count: int
    uncovered_deadline_count: int
    open_incident_count: int
    unprojected_calendar_count: int
    inactive_coverage_count: int
    #: Covers only the costs this reader may see. A confidential rate is
    #: excluded rather than added as a zero, so the total is honest for the
    #: reader but not necessarily complete.
    total_cost_minor_by_currency: dict[str, int]
    #: How many cost amounts the total could not include, so an incomplete
    #: total can never be mistaken for a complete one (UJ-52-EXC-05, and the
    #: UJ-59 rule that a control report cannot claim all clear while something
    #: is hidden).
    withheld_cost_item_count: int = 0
    counts_are_complete: bool = True
    rows: list[IpDocketControlRow] = Field(default_factory=list)


__all__ = [
    name
    for name in globals()
    if name.startswith("Ip") or name.startswith("Trademark") or name == "FilingManifestItem"
]


class IpControlExceptionRecord(BaseModel):
    """A critical exception that a filter or dismissal cannot hide (CAL-OPS-13)."""

    docket_id: str
    kind: Literal["uncovered", "inactive_owner", "unprojected_calendar", "open_incident"]
    critical: bool = True


class IpControlReviewIncludedRecord(BaseModel):
    """One access-filtered docket row frozen into a control-review manifest."""

    docket_id: str
    current_version: int = Field(ge=1)
    sha256: str = Field(min_length=64, max_length=64)


class IpControlReviewPolicy(BaseModel):
    policy_version: str
    required_signature_count: Literal[1, 2]
    required_sample_size: int = Field(ge=0, le=20)
    distinct_preparer_and_reviewer: bool


class IpControlReviewDelta(BaseModel):
    predecessor_review_id: str | None = None
    predecessor_manifest_sha256: str | None = None
    added_docket_ids: list[str] = Field(default_factory=list)
    removed_docket_ids: list[str] = Field(default_factory=list)
    changed_docket_ids: list[str] = Field(default_factory=list)
    added_exception_keys: list[str] = Field(default_factory=list)
    removed_exception_keys: list[str] = Field(default_factory=list)


class IpControlReviewSnapshot(BaseModel):
    """Canonical, hash-bound input and output of one control-report query."""

    schema_version: Literal[1, 2] = 1
    query_version: str
    generated_at: datetime
    timezone: str
    filters: dict[str, Any]
    freshness: dict[str, Any]
    hidden_restricted_count_policy: Literal["omit_without_count"]
    included_records: list[IpControlReviewIncludedRecord] = Field(default_factory=list)
    report: IpDocketControlReport
    mandatory_exceptions: list[IpControlExceptionRecord] = Field(default_factory=list)
    incompleteness_reasons: list[str] = Field(default_factory=list)
    review_policy: IpControlReviewPolicy | None = None
    delta: IpControlReviewDelta | None = None


class IpControlReviewFilters(BaseModel):
    """The complete, versioned filter vocabulary for a control review."""

    model_config = ConfigDict(extra="forbid")

    # Team is an exact company-scoped team ID or slug, never a fuzzy label.
    team: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    exclude_docket_ids: list[UUID] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def reject_duplicate_exclusions(self) -> IpControlReviewFilters:
        if len(self.exclude_docket_ids) != len(set(self.exclude_docket_ids)):
            raise ValueError("exclude_docket_ids must not contain duplicates")
        return self


class IpControlReviewCreateRequest(BaseModel):
    """Filters and observed source freshness for one control review."""

    model_config = ConfigDict(extra="forbid")

    filters: IpControlReviewFilters = Field(default_factory=IpControlReviewFilters)
    stale_sources: list[str] = Field(default_factory=list, max_length=40)
    failed_queries: list[str] = Field(default_factory=list, max_length=40)


class IpControlReviewExportRequest(BaseModel):
    outcome: Literal["generated", "failed"]
    error_redacted: str | None = Field(default=None, max_length=500)


class IpControlReviewSignOffRequest(BaseModel):
    expected_version: int = Field(ge=1)
    attestation: str = Field(min_length=5, max_length=2000)


class IpControlReviewExceptionDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    disposition: Literal["resolved", "annotated"]
    annotation: str = Field(min_length=5, max_length=4000)
    evidence_reference: str = Field(min_length=3, max_length=500)


class IpControlReviewSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    docket_id: str = Field(min_length=1, max_length=36)
    source_evidence_reference: str = Field(min_length=3, max_length=500)
    calculation_evidence_reference: str = Field(min_length=3, max_length=500)
    coverage_evidence_reference: str = Field(min_length=3, max_length=500)
    notes: str | None = Field(default=None, max_length=4000)


class IpControlReviewExceptionDecisionRecord(BaseModel):
    docket_id: str
    exception_kind: str
    disposition: Literal["resolved", "annotated"]
    annotation: str
    evidence_reference: str
    decided_by_membership_id: str
    decided_at: datetime


class IpControlReviewSampleRecord(BaseModel):
    docket_id: str
    reviewer_membership_id: str
    source_evidence_reference: str
    calculation_evidence_reference: str
    coverage_evidence_reference: str
    notes: str | None = None
    sampled_at: datetime


class IpControlReviewSignatureRecord(BaseModel):
    signer_membership_id: str
    signer_role: Literal["preparer", "reviewer"]
    signer_label_snapshot: str
    attestation: str
    manifest_sha256: str
    sequence: Literal[1, 2]
    signed_at: datetime


class IpControlReviewRecord(BaseModel):
    id: str
    generated_at: datetime
    filters: dict[str, Any]
    freshness: dict[str, Any]
    completeness_status: str
    incompleteness_reasons: list[str] = Field(default_factory=list)
    mandatory_exceptions: list[IpControlExceptionRecord] = Field(default_factory=list)
    query_version: str
    manifest_sha256: str
    export_status: str
    export_error_redacted: str | None = None
    signer_label_snapshot: str | None = None
    signed_off_at: datetime | None = None
    review_policy: IpControlReviewPolicy
    predecessor_review_id: str | None = None
    delta: IpControlReviewDelta
    exception_decisions: list[IpControlReviewExceptionDecisionRecord] = Field(default_factory=list)
    reviewer_samples: list[IpControlReviewSampleRecord] = Field(default_factory=list)
    signatures: list[IpControlReviewSignatureRecord] = Field(default_factory=list)
    pending_exception_count: int = Field(ge=0)
    annotated_exception_count: int = Field(ge=0)
    signoff_status: Literal["draft", "awaiting_second_signature", "signed"]
    version: int
    report: IpDocketControlReport
    snapshot: IpControlReviewSnapshot


class IpControlReviewListResponse(BaseModel):
    reviews: list[IpControlReviewRecord] = Field(default_factory=list)


class IpDailyDocketQueue(BaseModel):
    """Workload and capacity for one responsible member (CAL-OPS-09)."""

    membership_id: str
    label: str
    active: bool
    capacity_state: Literal["available", "unavailable"]
    assigned_count: int | None = None
    critical_count: int | None = None
    unacknowledged_count: int | None = None


class IpDailyDocketEscalation(BaseModel):
    """A critical item that must not be lost (CAL-OPS-13)."""

    coverage_id: str
    docket_id: str
    reason: Literal["owner_inactive", "unacknowledged_critical", "unowned"]
    critical: bool
    escalate_to_membership_id: str | None = None


class IpDailyDocketResponse(BaseModel):
    """The daily docket a manager triages.

    When a source is stale the affected counts are ``null`` rather than ``0``:
    unknown work must never render as no work (UJ-50-EXC-03).
    """

    generated_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    stale_sources: list[str] = Field(default_factory=list)
    counts_are_complete: bool = True
    queues: list[IpDailyDocketQueue] = Field(default_factory=list)
    escalations: list[IpDailyDocketEscalation] = Field(default_factory=list)


class IpDocketQueueSaveRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    filters: dict[str, Any] = Field(default_factory=dict)
    # A queue is either shared with a team or personal to the caller. There is
    # no company-wide tier: a queue everyone can edit is a queue nobody owns.
    team_id: str | None = None


class IpDocketQueueRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    team_id: str | None = None
    owner_membership_id: str | None = None
    scope: Literal["team", "personal"]
    created_at: datetime
    updated_at: datetime


class IpDocketQueueListResponse(BaseModel):
    queues: list[IpDocketQueueRecord] = Field(default_factory=list)


class IpCoverageBulkAcknowledgeRequest(BaseModel):
    coverage_ids: list[str] = Field(min_length=1, max_length=500)
    # Optional per-record fencing: a row that moved since the queue was read is
    # reported rather than silently acknowledged at its new state.
    expected_versions: dict[str, int] = Field(default_factory=dict)


class IpCoverageAcknowledgeOutcome(BaseModel):
    """Per-record validation result (CAL-OPS-09).

    Every requested id gets a row, so a caller can never mistake "silently
    dropped" for "acknowledged".
    """

    coverage_id: str
    acknowledged: bool
    reason: (
        Literal[
            "acknowledged",
            "already_acknowledged",
            "not_found",
            "not_responsible",
            "version_conflict",
            "transfer_pending",
            "inactive_lifecycle",
        ]
        | None
    ) = None
    reassignment_version: int | None = None


class IpCoverageBulkAcknowledgeResponse(BaseModel):
    acknowledged_count: int
    rejected_count: int
    outcomes: list[IpCoverageAcknowledgeOutcome] = Field(default_factory=list)


class IpCalendarDriftRecord(BaseModel):
    """A projected calendar event that no longer matches CaseOps (UJ-62-EXC-03)."""

    sync_id: str
    connection_id: str
    membership_id: str | None = None
    source_type: str
    source_id: str
    ip_docket_id: str | None = None
    reconciliation_candidate_id: str | None = None
    # `unknown` is a real outcome: the provider could not be read, so the
    # projection is unverified rather than confirmed correct.
    drift_status: Literal["moved", "missing", "unknown"]
    detail: str


class IpCalendarDriftResponse(BaseModel):
    checked_at: datetime
    findings: list[IpCalendarDriftRecord] = Field(default_factory=list)


class IpCalendarReconciliationCandidateRecord(BaseModel):
    id: str
    calendar_event_sync_id: str
    calendar_connection_id: str
    source_type: str
    source_id: str
    ip_docket_id: str | None
    drift_status: Literal["moved", "missing", "unknown"]
    snapshot_schema_version: int
    expected_snapshot: dict
    observed_snapshot: dict
    snapshot_sha256: str
    status: Literal["pending", "accepted", "rejected", "superseded"]
    detected_by_membership_id: str | None
    decided_by_membership_id: str | None
    decision_evidence_reference: str | None
    decided_at: datetime | None
    created_at: datetime


class IpCalendarReconciliationCandidateListResponse(BaseModel):
    candidates: list[IpCalendarReconciliationCandidateRecord] = Field(default_factory=list)


class IpCalendarReconciliationDecisionRequest(BaseModel):
    action: Literal["accept", "reject"]
    evidence_reference: str = Field(min_length=8, max_length=500)
    expected_snapshot_sha256: str = Field(min_length=64, max_length=64)


class IpAssignedCoverageRecord(BaseModel):
    """One deadline the calling member is responsible for (CAL-OPS-09).

    The daily docket reports how much work each member holds; this is the work
    itself, so a member can acknowledge it rather than only be counted.
    """

    coverage_id: str
    docket_id: str
    docket_title: str
    docket_identifier: str | None = None
    deadline_title: str | None = None
    due_on: date | None = None
    days_until_due: int | None = None
    critical: bool = False
    acknowledged: bool
    coverage_status: str
    transfer_pending: bool = False
    reassignment_version: int


class IpAssignedCoverageListResponse(BaseModel):
    coverages: list[IpAssignedCoverageRecord] = Field(default_factory=list)


class IpCoverageTransferAwaiting(BaseModel):
    """One coverage transfer awaiting the calling member's decision.

    Carries what a lawyer needs in order to answer "can I hold this date?" —
    which record, which deadline, when it falls, who asked and why — so the
    decision does not require opening each docket in turn.
    """

    coverage_id: str
    docket_id: str
    docket_title: str
    docket_identifier: str | None = None
    deadline_title: str | None = None
    due_on: date | None = None
    days_until_due: int | None = None
    critical: bool = False
    # `proposed`: responsibility has not moved and stays with `responsible_...`
    # until this is accepted. `immediate`: it already moved because the outgoing
    # person could not be waited on, and declining escalates rather than
    # returning it.
    transfer_kind: Literal["proposed", "immediate"]
    responsible_membership_id: str
    responsible_label: str
    escalation_membership_id: str | None = None
    escalation_label: str | None = None
    reason: str | None = None
    reassignment_version: int


class IpCoverageTransfersAwaitingResponse(BaseModel):
    transfers: list[IpCoverageTransferAwaiting] = Field(default_factory=list)


class IpCoverageReassignPreviewRequest(BaseModel):
    from_membership_id: str
    to_membership_id: str


class IpCoverageReassignPreviewResponse(BaseModel):
    """Atomic snapshot of a proposed transfer (CAL-OPS-08)."""

    from_membership_id: str
    to_membership_id: str
    preview_token: str
    affected_coverage_ids: list[str] = Field(default_factory=list)
    affected_roles: dict[str, list[Literal["responsible", "backup"]]] = Field(default_factory=dict)
    affected_docket_ids: list[str] = Field(default_factory=list)
    blocked_docket_ids: list[str] = Field(default_factory=list)
    transfer_allowed: bool


class IpCoverageReassignProposeRequest(BaseModel):
    from_membership_id: str
    to_membership_id: str
    preview_token: str
    reason: str = Field(min_length=5, max_length=2000)
    emergency_until: datetime | None = None
    emergency_escalation_membership_id: str | None = None


class IpCoverageReplacementDecisionRequest(BaseModel):
    decision: Literal["accepted", "rejected"]
    # Accepting needs no justification — the act itself is the record, and
    # forcing prose to click accept produces "ok" in an audit trail. Declining
    # sends work back or escalates it, so it must be explained.
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_reason_when_declining(self) -> IpCoverageReplacementDecisionRequest:
        if self.decision == "rejected" and len((self.reason or "").strip()) < 5:
            raise ValueError("Declining a transfer requires a reason.")
        return self
