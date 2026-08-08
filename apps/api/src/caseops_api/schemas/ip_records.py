from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.services.ip_identifier_rules import (
    normalize_ip_identifier,
    validate_identifier_owner,
)


class IpIdentifierCreate(BaseModel):
    identifier_kind: Literal[
        "application", "registration", "opposition", "rectification", "appeal", "court"
    ]
    raw_value: str = Field(min_length=1, max_length=160)
    office: str = Field(min_length=1, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    source: str = Field(min_length=2, max_length=120)
    effective_from: date
    effective_until: date | None = None
    is_primary: bool = False
    application_id: str | None = None
    proceeding_id: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> IpIdentifierCreate:
        validate_identifier_owner(
            identifier_kind=self.identifier_kind,
            application_id=self.application_id,
            proceeding_id=self.proceeding_id,
        )
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("effective_until cannot precede effective_from")
        if not normalize_ip_identifier(self.raw_value):
            raise ValueError("identifier must contain at least one Unicode letter or number")
        return self

    @property
    def normalized_value(self) -> str:
        return normalize_ip_identifier(self.raw_value)


class IpIdentifierCorrectionCreate(IpIdentifierCreate):
    supersedes_identifier_id: str
    correction_reason: str = Field(min_length=5, max_length=500)


class IpAssetCreateRequest(BaseModel):
    asset_kind: Literal["trademark"] = "trademark"
    jurisdiction: str = Field(min_length=2, max_length=40)
    title: str = Field(min_length=2, max_length=255)


class IpApplicationNumberCreate(BaseModel):
    raw_value: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=2, max_length=120)
    effective_from: date
    is_primary: bool = True

    @model_validator(mode="after")
    def validate_value(self) -> IpApplicationNumberCreate:
        if not normalize_ip_identifier(self.raw_value):
            raise ValueError("identifier must contain at least one Unicode letter or number")
        return self


class TrademarkApplicationCreateRequest(BaseModel):
    asset_id: str
    office: str = Field(min_length=2, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    filing_phase: Literal["draft", "pre_filing", "filed"] = "draft"
    source_pending_identifier_allocation: bool = False
    application_number: IpApplicationNumberCreate | None = None


class IpProceedingCreateRequest(BaseModel):
    application_id: str | None = None
    proceeding_kind: Literal["opposition", "rectification", "appeal", "court"]
    side: Literal["applicant", "opponent", "claimant", "respondent", "other"]
    office: str = Field(min_length=2, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    stage: str = Field(default="draft", min_length=2, max_length=40)


class TrademarkApplicationPhaseUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    filing_phase: Literal["draft", "pre_filing", "filed"]
    source_pending_identifier_allocation: bool = False


class IpIdentifierResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    application_id: str | None
    proceeding_id: str | None
    identifier_kind: str
    raw_value: str
    normalized_value: str
    office: str
    jurisdiction: str
    source: str
    effective_from: date
    effective_until: date | None
    is_primary: bool
    reconciliation_status: str
    supersedes_identifier_id: str | None
    correction_reason: str | None
    created_at: datetime


class IpIdentifierMutationResponse(BaseModel):
    identifier: IpIdentifierResponse
    duplicate_candidates: list[IpIdentifierResponse] = Field(default_factory=list)


class IpAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    asset_kind: str
    jurisdiction: str
    title: str
    version: int
    created_at: datetime
    updated_at: datetime


class TrademarkApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    asset_id: str
    office: str
    jurisdiction: str
    filing_phase: str
    source_pending_identifier_allocation: bool
    version: int
    created_at: datetime
    updated_at: datetime


class TrademarkApplicationMutationResponse(BaseModel):
    application: TrademarkApplicationResponse
    identifier: IpIdentifierResponse | None
    duplicate_candidates: list[IpIdentifierResponse] = Field(default_factory=list)


class IpProceedingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    docket_id: str
    application_id: str | None
    proceeding_kind: str
    side: str
    office: str
    jurisdiction: str
    stage: str
    version: int
    created_at: datetime
    updated_at: datetime


class IpCoreRecordResponse(BaseModel):
    assets: list[IpAssetResponse]
    applications: list[TrademarkApplicationResponse]
    proceedings: list[IpProceedingResponse]
    identifiers: list[IpIdentifierResponse]


IpWorkspaceTestKind = Literal[
    "connection",
    "notification",
    "source_open",
    "deadline_calculation",
]
IpAutomationFeature = Literal[
    "registry_sync",
    "deadline_automation",
    "notification_automation",
]


class IpWorkspaceConfigurationUpsertRequest(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)
    enabled_asset_types: list[Literal["trademark"]] = Field(min_length=1, max_length=8)
    jurisdictions: list[str] = Field(min_length=1, max_length=40)
    offices: list[str] = Field(min_length=1, max_length=80)
    timezone: str = Field(min_length=3, max_length=64)
    holiday_calendar_key: str = Field(min_length=2, max_length=120)
    working_day_policy: dict
    document_taxonomy_version: str = Field(min_length=1, max_length=80)
    event_catalog_version: str = Field(min_length=1, max_length=80)
    deadline_rule_versions: dict[str, str]
    notification_channels: list[Literal["in_app", "email"]] = Field(min_length=1)
    critical_event_policy: dict
    escalation_owner_membership_id: str
    provider_keys: list[str] = Field(default_factory=list, max_length=20)
    provider_terms_version: str | None = Field(default=None, max_length=80)
    accept_provider_terms: bool = False

    @model_validator(mode="after")
    def validate_workspace_configuration(self) -> IpWorkspaceConfigurationUpsertRequest:
        for field_name in ("jurisdictions", "offices", "provider_keys"):
            values = getattr(self, field_name)
            if any(not value.strip() for value in values):
                raise ValueError(f"{field_name} cannot contain blank values")
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} cannot contain duplicates")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        weekdays = self.working_day_policy.get("working_weekdays")
        if not isinstance(weekdays, list) or not weekdays:
            raise ValueError("working_day_policy.working_weekdays is required")
        if any(not isinstance(day, int) or day < 0 or day > 6 for day in weekdays):
            raise ValueError("working weekdays must be integers from 0 through 6")
        if not self.critical_event_policy.get("escalation_after_minutes"):
            raise ValueError("critical_event_policy.escalation_after_minutes is required")
        if self.provider_keys and not self.provider_terms_version:
            raise ValueError("provider terms version is required for configured providers")
        return self


class IpWorkspaceConfigurationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    version: int
    enabled_asset_types_json: list[str]
    jurisdictions_json: list[str]
    offices_json: list[str]
    timezone: str
    holiday_calendar_key: str
    working_day_policy_json: dict
    document_taxonomy_version: str
    event_catalog_version: str
    deadline_rule_versions_json: dict[str, str]
    notification_channels_json: list[str]
    critical_event_policy_json: dict
    escalation_owner_membership_id: str
    provider_keys_json: list[str]
    provider_terms_version: str | None
    provider_terms_accepted_by_membership_id: str | None
    provider_terms_accepted_at: datetime | None
    enabled_automations_json: list[str]
    workspace_enabled: bool
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpWorkspaceTestRunRequest(BaseModel):
    expected_config_version: int = Field(ge=1)
    test_kind: IpWorkspaceTestKind
    feature_id: IpAutomationFeature | None = None
    provider_key: str | None = Field(default=None, max_length=80)


class IpWorkspaceTestResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    configuration_id: str
    config_version: int
    test_kind: str
    feature_id: str | None
    provider_key: str | None
    status: str
    failure_code: str | None
    details_json: dict
    performed_by_membership_id: str
    performed_at: datetime


class IpWorkspaceEnableRequest(BaseModel):
    expected_config_version: int = Field(ge=1)
    enabled_automations: list[IpAutomationFeature] = Field(default_factory=list)


class IpWorkspaceConfigurationStatusResponse(BaseModel):
    configuration: IpWorkspaceConfigurationResponse | None
    tests: list[IpWorkspaceTestResultResponse]
    ready_for_manual_docketing: bool
    enablement_blockers: list[str]
