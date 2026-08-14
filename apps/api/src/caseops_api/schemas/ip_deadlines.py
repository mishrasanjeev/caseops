from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

DeadlineKind = Literal[
    "legal_deadline",
    "internal_target",
    "task_date",
    "hearing",
    "renewal",
    "client_instruction",
    "reminder",
]
CalendarMethod = Literal[
    "calendar_days",
    "business_days",
    "month_anniversary",
    "year_anniversary",
]


class LegalCalendarSnapshot(BaseModel):
    calendar_version_id: str
    timezone: str
    weekend_days: list[int] = Field(default_factory=lambda: [5, 6])
    holidays: list[date] = Field(default_factory=list)
    exceptional_working_days: list[date] = Field(default_factory=list)
    source_reference: str = Field(min_length=1, max_length=512)
    source_hash: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_calendar(self) -> LegalCalendarSnapshot:
        if any(day < 0 or day > 6 for day in self.weekend_days):
            raise ValueError("weekend days must be integers from 0 through 6")
        if len(self.weekend_days) != len(set(self.weekend_days)):
            raise ValueError("weekend days cannot contain duplicates")
        if set(self.holidays) & set(self.exceptional_working_days):
            raise ValueError("a date cannot be both a holiday and an exceptional working day")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return self


class IpDeadlineCalculationRequest(BaseModel):
    deadline_kind: DeadlineKind
    trigger_kind: str = Field(min_length=1, max_length=80)
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    duration_value: int = Field(ge=0, le=10000)
    duration_unit: Literal["days", "months", "years"]
    calendar_method: CalendarMethod
    direction: Literal["after", "before"] = "after"
    include_base_date: bool = False
    next_working_day: bool = True
    extension_days: int = Field(default=0, ge=0, le=3650)
    rule_version_id: str
    rule_citation: str = Field(min_length=1, max_length=512)
    source_version: str = Field(min_length=1, max_length=120)
    engine_version: str = Field(min_length=1, max_length=80)
    calendar: LegalCalendarSnapshot

    @model_validator(mode="after")
    def validate_method_unit(self) -> IpDeadlineCalculationRequest:
        expected_unit = {
            "calendar_days": "days",
            "business_days": "days",
            "month_anniversary": "months",
            "year_anniversary": "years",
        }[self.calendar_method]
        if self.duration_unit != expected_unit:
            raise ValueError(f"{self.calendar_method} calculations require {expected_unit}")
        return self


class IpDeadlineCalculationResult(BaseModel):
    state: Literal["provisional", "candidate"]
    result_on: date | None
    certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    explanation: str
    inputs: dict
    trace: list[dict]


class ResponsibilityEvidence(BaseModel):
    membership_id: str
    role: Literal["primary", "backup", "supervisor", "docketing"]
    accepted: bool
    active: bool = True


RuleKind = Literal["deadline", "form", "fee"]
RuleStatus = Literal["candidate", "approved", "active", "retired", "disabled"]
DeadlineState = Literal[
    "provisional",
    "candidate",
    "confirmed",
    "overdue",
    "completed",
    "superseded",
    "cancelled",
]


class IpDeadlineRuleDefinition(BaseModel):
    deadline_kind: DeadlineKind
    trigger_kind: str = Field(min_length=1, max_length=80)
    duration_value: int = Field(ge=0, le=10000)
    duration_unit: Literal["days", "months", "years"]
    calendar_method: CalendarMethod
    direction: Literal["after", "before"] = "after"
    include_base_date: bool = False
    next_working_day: bool = True
    extension_days: int = Field(default=0, ge=0, le=3650)
    rule_citation: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_method_unit(self) -> IpDeadlineRuleDefinition:
        expected_unit = {
            "calendar_days": "days",
            "business_days": "days",
            "month_anniversary": "months",
            "year_anniversary": "years",
        }[self.calendar_method]
        if self.duration_unit != expected_unit:
            raise ValueError(f"{self.calendar_method} rules require {expected_unit}")
        return self


class IpRuleFixture(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    fixture_kind: Literal["positive", "negative", "boundary"]
    calculation: IpDeadlineCalculationRequest | None = None
    expected_state: Literal["provisional", "candidate"] | None = None
    expected_result_on: date | None = None
    expected_outcome: Any | None = None
    observed_outcome: Any | None = None
    evidence_reference: str = Field(min_length=1, max_length=512)


class IpRuleVersionProposalRequest(BaseModel):
    key: str = Field(min_length=1, max_length=160)
    rule_kind: RuleKind
    jurisdiction: str = Field(min_length=1, max_length=40)
    office: str | None = Field(default=None, max_length=120)
    right_kind: str = Field(min_length=1, max_length=40)
    proceeding_kind: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, max_length=40)
    stage: str = Field(min_length=1, max_length=80)
    source_record_id: str = Field(min_length=1, max_length=120)
    source_hash: str = Field(min_length=64, max_length=64)
    source_reference: str = Field(min_length=1, max_length=512)
    effective_from: date
    effective_until: date | None = None
    engine_compatibility: str = Field(min_length=1, max_length=80)
    definition: dict[str, Any]
    fixtures: list[IpRuleFixture] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_definition_and_dates(self) -> IpRuleVersionProposalRequest:
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("effective_until cannot precede effective_from")
        if self.rule_kind == "deadline":
            IpDeadlineRuleDefinition.model_validate(self.definition)
            if any(fixture.calculation is None for fixture in self.fixtures):
                raise ValueError("deadline fixtures require deterministic calculations")
        return self


class IpRuleVersionRecord(BaseModel):
    id: str
    rule_set_id: str
    key: str
    rule_kind: RuleKind
    jurisdiction: str
    office: str | None
    right_kind: str
    proceeding_kind: str | None
    role: str | None
    stage: str
    version: int
    status: RuleStatus
    source_record_id: str
    source_hash: str
    source_reference: str
    effective_from: date
    effective_until: date | None
    engine_compatibility: str
    definition: dict[str, Any]
    fixtures: list[dict[str, Any]]
    proposer_label_snapshot: str
    reviewer_label_snapshot: str | None
    legal_approver_label_snapshot: str | None
    fixtures_passed_at: datetime | None
    activated_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime


class IpRuleActivationRequest(BaseModel):
    reviewer_membership_id: str
    impact_acknowledged: bool = False
    impact_reason: str = Field(default="", max_length=1000)
    impact_token: str | None = None
    supersede_overlapping: bool = False
    select_for_company: bool = True
    auto_confirm_eligible: bool = False
    internal_target_policy: dict[str, Any] = Field(default_factory=dict)


class IpRuleTransitionRequest(BaseModel):
    impact_token: str
    reason: str = Field(min_length=5, max_length=2000)
    emergency_disable: bool = False


class IpRuleImpactResponse(BaseModel):
    rule_version_id: str
    impact_token: str
    company_policy_count: int
    open_deadline_count: int
    candidate_deadline_count: int
    confirmed_deadlines_preserved: bool = True


class IpCompanyRuleSelectionRequest(BaseModel):
    """Tenant selection of an already-approved platform rule version."""

    rule_version_id: str
    auto_confirm_eligible: bool = False
    internal_target_policy: dict[str, Any] = Field(default_factory=dict)
    expected_policy_version: int | None = None


class IpCompanyRulePolicyRecord(BaseModel):
    id: str
    rule_set_id: str
    rule_set_key: str
    rule_kind: RuleKind
    active_rule_version_id: str
    active_rule_version: int
    active_rule_status: RuleStatus
    auto_confirm_eligible: bool
    auto_confirm_suspended_reason: str | None = None
    internal_target_policy: dict[str, Any]
    version: int
    updater_label_snapshot: str
    updated_at: datetime


class LegalCalendarVersionProposalRequest(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=255)
    jurisdiction: str = Field(min_length=1, max_length=40)
    office: str | None = Field(default=None, max_length=120)
    timezone: str
    weekend_days: list[int] = Field(default_factory=lambda: [5, 6])
    holidays: list[date] = Field(default_factory=list)
    exceptional_working_days: list[date] = Field(default_factory=list)
    source_priority: list[str] = Field(min_length=1)
    source_reference: str = Field(min_length=1, max_length=512)
    source_hash: str = Field(min_length=64, max_length=64)
    effective_from: date
    effective_until: date | None = None

    @model_validator(mode="after")
    def validate_calendar(self) -> LegalCalendarVersionProposalRequest:
        LegalCalendarSnapshot(
            calendar_version_id="proposal",
            timezone=self.timezone,
            weekend_days=self.weekend_days,
            holidays=self.holidays,
            exceptional_working_days=self.exceptional_working_days,
            source_reference=self.source_reference,
            source_hash=self.source_hash,
        )
        if self.effective_until and self.effective_until < self.effective_from:
            raise ValueError("effective_until cannot precede effective_from")
        return self


class LegalCalendarActivationRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)
    conflict_reviewed: bool = False


class LegalCalendarVersionRecord(BaseModel):
    id: str
    calendar_id: str
    key: str
    name: str
    jurisdiction: str
    office: str | None
    version: int
    status: RuleStatus
    timezone: str
    weekend_days: list[int]
    holidays: list[date]
    exceptional_working_days: list[date]
    source_priority: list[str]
    source_reference: str
    source_hash: str
    effective_from: date
    effective_until: date | None
    proposer_label_snapshot: str
    approver_label_snapshot: str | None
    approved_at: datetime | None
    created_at: datetime


class IpResponsibilityInput(BaseModel):
    membership_id: str
    role: Literal["primary", "backup", "supervisor", "docketing"]
    accepted: bool = False
    replacement_source: str = Field(default="direct_assignment", min_length=1, max_length=120)
    escalation_policy: dict[str, Any] = Field(default_factory=dict)


class IpDeadlineProposalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    trigger_event_id: str | None = None
    rule_version_id: str
    calendar_version_id: str
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    date_precision: Literal["unknown", "date", "datetime", "session"] = "date"
    is_critical: bool = True


class IpDeadlineConfirmRequest(BaseModel):
    expected_version: int = Field(ge=1)
    responsibilities: list[IpResponsibilityInput] = Field(min_length=1)
    internal_target_on: date | None = None
    reminder_offsets_days: list[int] = Field(default_factory=list)
    corrected_result_on: date | None = None
    correction_reason: str | None = Field(default=None, max_length=2000)
    correction_evidence_reference: str | None = Field(default=None, max_length=512)
    impact_token: str | None = None

    @model_validator(mode="after")
    def validate_correction(self) -> IpDeadlineConfirmRequest:
        if self.corrected_result_on and not (
            self.correction_reason and self.correction_evidence_reference
        ):
            raise ValueError("a corrected confirmation requires reason and evidence")
        if len(self.reminder_offsets_days) != len(set(self.reminder_offsets_days)):
            raise ValueError("reminder offsets cannot contain duplicates")
        if any(offset < 0 or offset > 3650 for offset in self.reminder_offsets_days):
            raise ValueError("reminder offsets must be between 0 and 3650 days")
        return self


class IpDeadlineOverrideRequest(BaseModel):
    expected_version: int = Field(ge=1)
    new_result_on: date
    reason: str = Field(min_length=5, max_length=2000)
    evidence_reference: str = Field(min_length=1, max_length=512)
    impact_token: str
    responsibilities: list[IpResponsibilityInput] = Field(min_length=1)
    internal_target_on: date | None = None
    reminder_offsets_days: list[int] = Field(default_factory=list)


class IpDeadlineRecalculateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    trigger_event_id: str | None = None
    base_date: date | None
    base_date_certainty: Literal["certain", "uncertain", "conflicting", "unknown"]
    reason: str = Field(min_length=5, max_length=2000)
    evidence_reference: str = Field(min_length=1, max_length=512)


class IpDeadlineCompleteRequest(BaseModel):
    expected_version: int = Field(ge=1)
    evidence_reference: str = Field(min_length=1, max_length=512)
    attestation: str = Field(min_length=5, max_length=2000)


class IpDeadlineRecord(BaseModel):
    id: str
    docket_id: str
    trigger_event_id: str | None
    rule_version_id: str
    calendar_version_id: str
    matter_deadline_id: str | None
    supersedes_deadline_id: str | None
    deadline_kind: DeadlineKind
    title: str
    trigger_kind: str
    base_date: date | None
    date_precision: str
    certainty: str
    result_on: date | None
    calculation_inputs: dict[str, Any]
    calculation_trace: list[dict[str, Any]]
    explanation: str
    rule_citation: str
    engine_version: str
    source_version: str
    is_critical: bool
    state: DeadlineState
    version: int
    confirmed_at: datetime | None
    override_reason: str | None
    override_evidence_ref: str | None
    completed_evidence_ref: str | None
    created_at: datetime
    updated_at: datetime
    responsibilities: list[dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class IpDeadlineImpactResponse(BaseModel):
    deadline_id: str
    expected_version: int
    impact_token: str
    operational_deadline_ids: list[str]
    notification_intent_ids: list[str]
    active_responsibility_ids: list[str]
    unrelated_work_preserved: bool = True


class IpDeadlineExceptionRecord(BaseModel):
    deadline_id: str
    docket_id: str
    exception_kinds: list[
        Literal[
            "overdue",
            "unacknowledged",
            "unowned",
            "conflicting",
            "uncertain",
            "source_stale",
            "rule_disabled",
        ]
    ]
    critical: bool
    result_on: date | None
    visible: bool = True


class IpDeadlineWorkspaceResponse(BaseModel):
    docket_id: str
    rules: list[IpRuleVersionRecord]
    calendars: list[LegalCalendarVersionRecord]
    deadlines: list[IpDeadlineRecord]
    exceptions: list[IpDeadlineExceptionRecord]
    automation_state: Literal["explicit_confirmation_only"] = "explicit_confirmation_only"


class IpDeadlineDependencyNode(BaseModel):
    """One input that contributed to a deadline's current date."""

    kind: Literal[
        "trigger_event",
        "rule_version",
        "calendar_version",
        "predecessor_deadline",
        "extension",
        "override",
    ]
    reference_id: str | None = None
    label: str
    detail: str | None = None
    available: bool = True


class IpDeadlineDependencyResponse(BaseModel):
    """CAL-OPS-06 dependency graph for one legal deadline.

    Read-only provenance derived from the stored calculation evidence. It never
    recomputes the date; a missing input is reported as unavailable rather than
    silently dropped, so the chain cannot look complete when it is not.
    """

    deadline_id: str
    docket_id: str
    state: str
    result_on: date | None
    certainty: str
    is_critical: bool
    engine_version: str
    source_version: str
    rule_citation: str
    explanation: str
    nodes: list[IpDeadlineDependencyNode] = Field(default_factory=list)
    calculation_trace: list[dict[str, Any]] = Field(default_factory=list)
    unavailable_inputs: list[str] = Field(default_factory=list)
    superseded_chain: list[str] = Field(default_factory=list)
