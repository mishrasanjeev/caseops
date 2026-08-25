"""Typed contracts for Madrid international registrations and designations."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from caseops_api.schemas.ip_deadlines import IpDeadlineRecord
from caseops_api.schemas.ip_documents import IpDocumentRecord
from caseops_api.schemas.ip_lifecycle import IpDocketEventResponse
from caseops_api.schemas.ip_operations import IpCostItemRecord, IpDocketRecordResponse

MadridActionKind = Literal[
    "form_prepared",
    "fee_recorded",
    "office_of_origin_certified",
    "wipo_irregularity",
    "international_registration_recorded",
    "wipo_notification_recorded",
    "national_examination_recorded",
    "provisional_refusal_recorded",
    "response_filed",
    "publication_recorded",
    "opposition_recorded",
    "grant_statement_recorded",
    "refusal_statement_recorded",
    "dependency_impact_review",
    "central_attack_impact_review",
    "source_snapshot",
    "source_reconciliation",
    "local_agent_instruction",
    "subsequent_designation_recorded",
    "change_recorded",
    "renewal_transaction",
]
MadridAuthority = Literal[
    "wipo",
    "office_of_origin",
    "national_office",
    "local_agent",
    "client",
    "internal",
]


class TrademarkInternationalRecordCreateRequest(BaseModel):
    docket_id: str | None = None
    docket_title: str | None = Field(default=None, min_length=2, max_length=255)
    restricted: bool = False
    record_kind: Literal["international_registration", "international_designation"]
    direction: Literal["outbound", "inbound"]
    parent_registration_id: str | None = None
    basic_application_id: str | None = None
    international_application_number: str | None = Field(default=None, max_length=120)
    ir_number: str | None = Field(default=None, max_length=120)
    wipo_reference: str = Field(min_length=2, max_length=255)
    holder_name: str = Field(min_length=1, max_length=500)
    mark_name: str = Field(min_length=1, max_length=500)
    office_of_origin: str | None = Field(default=None, max_length=120)
    designated_member_code: str | None = Field(default=None, max_length=20)
    designated_office: str | None = Field(default=None, max_length=120)
    jurisdiction: str | None = Field(default=None, max_length=40)
    designation_kind: Literal["original", "subsequent"] | None = None
    classes: list[int] = Field(default_factory=list, max_length=45)
    goods_services: dict[str, str] = Field(default_factory=dict)
    priority_claims: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    form_kind: str | None = Field(default=None, max_length=40)
    wipo_status: str | None = Field(default=None, max_length=120)
    national_status: str | None = Field(default=None, max_length=120)
    local_agent_name: str | None = Field(default=None, max_length=500)
    source_url: str = Field(min_length=8, max_length=800)
    source_reference: str = Field(min_length=2, max_length=500)
    source_retrieved_at: datetime
    application_date: date | None = None
    international_registration_date: date | None = None
    designation_effective_date: date | None = None
    notification_date: date | None = None
    publication_date: date | None = None
    statement_date: date | None = None
    dependency_end_date: date | None = None
    renewal_due_date: date | None = None

    @model_validator(mode="after")
    def validate_record_boundary(self) -> TrademarkInternationalRecordCreateRequest:
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Madrid source URL must use HTTP or HTTPS.")
        if self.source_retrieved_at.utcoffset() is None:
            raise ValueError("Madrid source retrieval time must include a timezone.")
        if self.docket_id is not None and self.docket_title is not None:
            raise ValueError("Docket title is only valid when creating a new Madrid docket.")
        if len(set(self.classes)) != len(self.classes) or any(
            value < 1 or value > 45 for value in self.classes
        ):
            raise ValueError("Madrid classes must be unique Nice class numbers from 1 to 45.")
        if set(self.goods_services) != {str(value) for value in self.classes}:
            raise ValueError("Goods/services must provide exactly one entry for every class.")
        if any(not value.strip() for value in self.goods_services.values()):
            raise ValueError("Goods/services entries cannot be blank.")

        designation_fields = (
            self.parent_registration_id,
            self.designated_member_code,
            self.jurisdiction,
            self.designation_kind,
            self.designation_effective_date,
        )
        if self.record_kind == "international_registration":
            if any(value is not None for value in designation_fields):
                raise ValueError("An international registration cannot contain designation fields.")
            if self.direction == "outbound" and self.basic_application_id is None:
                raise ValueError(
                    "An outbound Madrid registration requires a basic Indian application."
                )
        else:
            if any(value is None for value in designation_fields):
                raise ValueError(
                    "A Madrid designation requires its parent, member, jurisdiction, kind and date."
                )
            if self.basic_application_id is not None:
                raise ValueError(
                    "Only the international registration may own the basic application link."
                )
            if self.ir_number is not None:
                raise ValueError("IR number belongs to the parent international registration.")
        return self


class TrademarkInternationalRecordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    record_kind: Literal["international_registration", "international_designation"]
    direction: Literal["outbound", "inbound"]
    parent_registration_id: str | None
    basic_application_id: str | None
    international_application_number: str | None
    ir_number: str | None
    wipo_reference: str
    holder_name: str
    mark_name: str
    office_of_origin: str | None
    designated_member_code: str | None
    designated_office: str | None
    jurisdiction: str | None
    designation_kind: Literal["original", "subsequent"] | None
    classes_json: list[int]
    goods_services_json: dict[str, str]
    priority_claims_json: list[dict[str, Any]]
    form_kind: str | None
    wipo_status: str | None
    national_status: str | None
    local_agent_name: str | None
    source_url: str
    source_reference: str
    source_retrieved_at: datetime
    application_date: date | None
    international_registration_date: date | None
    designation_effective_date: date | None
    notification_date: date | None
    publication_date: date | None
    statement_date: date | None
    dependency_end_date: date | None
    renewal_due_date: date | None
    version: int
    created_by_membership_id: str
    updated_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class TrademarkInternationalRecordPageResponse(BaseModel):
    items: list[TrademarkInternationalRecordResponse]
    total: int
    limit: int
    offset: int


class TrademarkInternationalActionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    expected_lifecycle_version: int = Field(ge=0)
    action_kind: MadridActionKind
    authority: MadridAuthority
    effective_at: datetime
    responsible_membership_id: str
    reason: str = Field(min_length=5, max_length=2000)
    source_url: str | None = Field(default=None, max_length=800)
    source_reference: str = Field(min_length=2, max_length=500)
    source_retrieved_at: datetime
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    document_refs: list[str] = Field(default_factory=list, max_length=100)
    deadline_refs: list[str] = Field(default_factory=list, max_length=100)
    cost_item_refs: list[str] = Field(default_factory=list, max_length=100)
    wipo_status: str | None = Field(default=None, max_length=120)
    national_status: str | None = Field(default=None, max_length=120)
    local_agent_name: str | None = Field(default=None, max_length=500)
    ir_number: str | None = Field(default=None, max_length=120)
    international_registration_date: date | None = None
    notification_date: date | None = None
    publication_date: date | None = None
    statement_date: date | None = None
    renewal_due_date: date | None = None
    reconciles_event_id: str | None = None
    reconciliation_decision: Literal["same_fact", "keep_separate", "reject_candidate"] | None = None
    acknowledged_exception_codes: list[str] = Field(default_factory=list, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_action_boundary(self) -> TrademarkInternationalActionRequest:
        for value, label in (
            (self.effective_at, "Effective time"),
            (self.source_retrieved_at, "Source retrieval time"),
        ):
            if value.utcoffset() is None:
                raise ValueError(f"{label} must include a timezone.")
        if self.source_url and not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Madrid source URL must use HTTP or HTTPS.")
        if self.authority in {"wipo", "office_of_origin", "national_office"}:
            if self.source_url is None:
                raise ValueError("External-office actions require a source URL.")
        if self.wipo_status is not None and self.authority != "wipo":
            raise ValueError("Only a WIPO-attributed action may propose WIPO status.")
        if self.national_status is not None and self.authority != "national_office":
            raise ValueError(
                "Only a national-office-attributed action may propose national status."
            )
        if self.local_agent_name is not None and self.action_kind != "local_agent_instruction":
            raise ValueError("Local agent may change only through local-agent instruction.")
        if self.action_kind == "local_agent_instruction" and self.authority != "local_agent":
            raise ValueError("Local-agent instruction must remain attributed to the local agent.")
        if self.action_kind == "source_snapshot":
            if self.authority not in {"wipo", "national_office"}:
                raise ValueError(
                    "A source snapshot must be attributed to WIPO or a national office."
                )
            if not self.wipo_status and not self.national_status:
                raise ValueError("A source snapshot must propose its authority-owned status.")
            if self.reconciles_event_id or self.reconciliation_decision:
                raise ValueError("A source snapshot cannot reconcile another source event.")
        elif self.action_kind == "source_reconciliation":
            if self.authority != "internal":
                raise ValueError("Source reconciliation must be an internal legal decision.")
            if not self.reconciles_event_id or self.reconciliation_decision is None:
                raise ValueError(
                    "Source reconciliation requires a candidate event and explicit decision."
                )
            if self.wipo_status or self.national_status:
                raise ValueError(
                    "Reconciliation accepts or rejects the candidate snapshot as stored."
                )
        elif self.reconciles_event_id or self.reconciliation_decision:
            raise ValueError("Only source reconciliation may reference a candidate event.")
        elif self.wipo_status or self.national_status:
            raise ValueError("Legal status changes must enter through a sourced snapshot.")
        if self.action_kind in {"dependency_impact_review", "central_attack_impact_review"}:
            if "impact_scope" not in self.details or "recommended_action" not in self.details:
                raise ValueError(
                    "Dependency impact review requires impact_scope and recommended_action."
                )
        if self.action_kind == "fee_recorded" and not self.cost_item_refs:
            raise ValueError("Fee action requires at least one canonical cost item.")
        return self


class TrademarkInternationalActionResponse(BaseModel):
    record: TrademarkInternationalRecordResponse
    event: IpDocketEventResponse
    status_applied: bool
    impact_review_only: bool


class TrademarkInternationalWorkspaceResponse(BaseModel):
    record: TrademarkInternationalRecordResponse
    docket: IpDocketRecordResponse
    parent: TrademarkInternationalRecordResponse | None
    designations: list[TrademarkInternationalRecordResponse]
    events: list[IpDocketEventResponse]
    deadlines: list[IpDeadlineRecord]
    documents: list[IpDocumentRecord]
    costs: list[IpCostItemRecord]
    unresolved_source_candidates: list[IpDocketEventResponse]
    data_quality_gaps: list[str]
    next_required_actions: list[str]
    provider_mode: Literal["manual_sourced_only", "contracted_sync"]
    provider_activation_blockers: list[str]
