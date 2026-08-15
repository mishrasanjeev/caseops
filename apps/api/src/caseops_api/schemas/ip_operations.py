from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_records import IpWorkspaceConfigurationStatusResponse


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


class IpControlReviewSnapshot(BaseModel):
    """Canonical, hash-bound input and output of one control-report query."""

    schema_version: Literal[1] = 1
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
    version: int
    report: IpDocketControlReport
    snapshot: IpControlReviewSnapshot


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
    # `unknown` is a real outcome: the provider could not be read, so the
    # projection is unverified rather than confirmed correct.
    drift_status: Literal["moved", "missing", "unknown"]
    detail: str


class IpCalendarDriftResponse(BaseModel):
    checked_at: datetime
    findings: list[IpCalendarDriftRecord] = Field(default_factory=list)


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
    affected_roles: dict[str, list[Literal["responsible", "backup"]]] = Field(
        default_factory=dict
    )
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
