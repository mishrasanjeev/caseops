"""Typed journal-watch, review, and canonical handoff contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

WatchDisposition = Literal[
    "new",
    "reviewing",
    "relevant",
    "not_relevant",
    "monitor",
    "client_instruction",
    "enforcement_opened",
    "closed",
]


class IpWatchProfileCreateRequest(BaseModel):
    docket_id: str
    name: str = Field(min_length=2, max_length=255)
    provider_key: str = Field(default="manual-journal", min_length=2, max_length=80)
    word_terms: list[str] = Field(default_factory=list, max_length=100)
    phonetic_terms: list[str] = Field(default_factory=list, max_length=100)
    device_references: list[str] = Field(default_factory=list, max_length=50)
    class_numbers: list[int] = Field(default_factory=list, max_length=45)
    proprietor_terms: list[str] = Field(default_factory=list, max_length=100)
    jurisdictions: list[str] = Field(default_factory=list, max_length=50)
    frequency: Literal["publication", "daily", "weekly", "monthly"]
    recipient_membership_ids: list[str] = Field(min_length=1, max_length=100)
    max_cost_minor_per_period: int = Field(default=0, ge=0)
    cost_currency: str = Field(default="INR", min_length=3, max_length=3)

    @model_validator(mode="after")
    def validate_criteria(self) -> IpWatchProfileCreateRequest:
        criteria = (
            self.word_terms,
            self.phonetic_terms,
            self.device_references,
            self.class_numbers,
            self.proprietor_terms,
            self.jurisdictions,
        )
        if not any(criteria):
            raise ValueError("A watch profile requires at least one criterion.")
        if any(number < 1 or number > 45 for number in self.class_numbers):
            raise ValueError("Trademark classes must be between 1 and 45.")
        if len(self.recipient_membership_ids) != len(set(self.recipient_membership_ids)):
            raise ValueError("Watch recipients must be unique.")
        if any(not ref.startswith(("https://", "http://")) for ref in self.device_references):
            raise ValueError("Device references must use HTTP or HTTPS.")
        return self


class IpWatchProfileUpdateRequest(BaseModel):
    expected_version: int = Field(ge=1)
    poll_status: Literal["active", "paused", "disabled"]
    reason: str = Field(min_length=5, max_length=500)


class IpWatchProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    docket_id: str
    name: str
    provider_key: str
    word_terms_json: list[str]
    phonetic_terms_json: list[str]
    device_references_json: list[str]
    class_numbers_json: list[int]
    proprietor_terms_json: list[str]
    jurisdictions_json: list[str]
    frequency: str
    recipient_membership_ids_json: list[str]
    max_cost_minor_per_period: int
    spent_cost_minor_in_period: int
    cost_currency: str
    poll_status: str
    pause_reason: str | None
    last_polled_at: datetime | None
    next_poll_at: datetime | None
    criteria_version: str
    version: int
    created_by_membership_id: str
    created_at: datetime
    updated_at: datetime


class IpJournalPublicationCreate(BaseModel):
    application_id: str | None = None
    journal_number: str = Field(min_length=1, max_length=80)
    journal_date: date
    publication_kind: Literal["advertisement", "correction", "readvertisement"] = (
        "advertisement"
    )
    application_number: str = Field(min_length=1, max_length=160)
    mark_text: str | None = Field(default=None, max_length=500)
    device_reference: str | None = Field(default=None, max_length=800)
    proprietor_name: str | None = Field(default=None, max_length=500)
    office: str = Field(min_length=2, max_length=80)
    jurisdiction: str = Field(min_length=2, max_length=40)
    class_numbers: list[int] = Field(min_length=1, max_length=45)
    goods_services: dict[str, list[str]] = Field(default_factory=dict)
    publication_scope: dict[str, Any] = Field(default_factory=dict)
    source_url: str = Field(min_length=8, max_length=800)
    source_page: str | None = Field(default=None, max_length=80)
    source_status: Literal["available", "unavailable", "stale"]
    source_retrieved_at: datetime | None = None
    parser_version: str = Field(min_length=2, max_length=80)
    attribution: dict[str, Any] = Field(default_factory=dict)
    raw_evidence: dict[str, Any] = Field(default_factory=dict)
    supersedes_publication_id: str | None = None
    correction_reason: str | None = Field(default=None, min_length=5, max_length=1000)

    @model_validator(mode="after")
    def validate_publication(self) -> IpJournalPublicationCreate:
        if not (self.mark_text or self.device_reference):
            raise ValueError("A journal entry requires a word mark or device reference.")
        if not self.source_url.startswith(("https://", "http://")):
            raise ValueError("Journal source URL must use HTTP or HTTPS.")
        if self.device_reference and not self.device_reference.startswith(("https://", "http://")):
            raise ValueError("Device reference must use HTTP or HTTPS.")
        if any(number < 1 or number > 45 for number in self.class_numbers):
            raise ValueError("Trademark classes must be between 1 and 45.")
        if len(self.class_numbers) != len(set(self.class_numbers)):
            raise ValueError("Publication classes must be unique.")
        goods_classes = {int(key) for key in self.goods_services}
        if not goods_classes.issubset(set(self.class_numbers)):
            raise ValueError("Goods/services scope must belong to a published class.")
        corrected = self.publication_kind in {"correction", "readvertisement"}
        if corrected != bool(self.supersedes_publication_id and self.correction_reason):
            raise ValueError("Correction/re-advertisement requires predecessor and reason.")
        if self.source_retrieved_at and self.source_retrieved_at.utcoffset() is None:
            raise ValueError("Source retrieval time must include a timezone.")
        return self


class IpJournalIngestRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    provider_key: str = Field(min_length=2, max_length=80)
    external_call: bool = False
    cost_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    publications: list[IpJournalPublicationCreate] = Field(min_length=1, max_length=500)


class IpJournalPublicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    application_id: str | None
    provider_key: str
    journal_number: str
    journal_date: date
    publication_kind: str
    application_number: str
    mark_text: str | None
    device_reference: str | None
    proprietor_name: str | None
    office: str
    jurisdiction: str
    class_numbers_json: list[int]
    goods_services_json: dict[str, list[str]]
    publication_scope_json: dict[str, Any]
    source_url: str
    source_page: str | None
    source_status: str
    source_retrieved_at: datetime | None
    parser_version: str
    attribution_json: dict[str, Any]
    source_fingerprint: str
    supersedes_publication_id: str | None
    correction_reason: str | None
    ingestion_delay_hours: int
    created_at: datetime


class IpJournalIngestionRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    provider_key: str
    idempotency_key: str
    request_sha256: str
    status: str
    external_call: bool
    cost_minor: int
    currency: str
    publications_seen: int
    publications_created: int
    hits_created: int
    duplicate_hits: int
    publication_ids_json: list[str]
    hit_ids_json: list[str]
    stale_source_alert: bool
    error_redacted: str | None
    requested_by_membership_id: str
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime


class IpJournalIngestResponse(BaseModel):
    run: IpJournalIngestionRunResponse
    publications: list[IpJournalPublicationResponse] = Field(default_factory=list)
    hits: list[IpWatchHitResponse] = Field(default_factory=list)
    idempotent_replay: bool = False


class IpWatchHitResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    profile_id: str
    publication_id: str
    duplicate_of_hit_id: str | None
    compared_mark_json: dict[str, Any]
    candidate_mark_json: dict[str, Any]
    classes_goods_json: dict[str, Any]
    similarity_evidence_json: dict[str, Any]
    ai_advisory: bool
    advisory_notice: str
    source_url: str
    source_status: str
    source_snapshot_json: dict[str, Any]
    hit_date: date
    stale_source_alert: bool
    deadline_confirmation_state: str
    disposition: WatchDisposition
    disposition_reason: str | None
    reviewed_by_membership_id: str | None
    reviewed_at: datetime | None
    reviewer_decision_json: dict[str, Any]
    version: int
    created_at: datetime
    updated_at: datetime


class IpWatchHitDispositionRequest(BaseModel):
    expected_version: int = Field(ge=1)
    disposition: WatchDisposition
    reason: str = Field(min_length=5, max_length=2000)
    source_confirmed: bool = False


class IpWatchHandoffRequest(BaseModel):
    handoff_kind: Literal[
        "opposition", "enforcement_matter", "task", "deadline", "client_report_item"
    ]
    application_id: str | None = None
    represented_side: Literal["applicant", "opponent"] = "opponent"
    title: str | None = Field(default=None, min_length=2, max_length=255)
    matter_code: str | None = Field(default=None, min_length=2, max_length=80)
    due_on: date | None = None
    assignee_membership_id: str | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_handoff(self) -> IpWatchHandoffRequest:
        if self.handoff_kind in {"task", "deadline", "enforcement_matter"} and not self.title:
            raise ValueError("The selected handoff requires a title.")
        if self.handoff_kind == "deadline" and self.due_on is None:
            raise ValueError("Deadline handoff requires a due date.")
        if self.handoff_kind == "enforcement_matter" and not self.matter_code:
            raise ValueError("Enforcement Matter handoff requires a matter code.")
        return self


class IpWatchHandoffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    hit_id: str
    handoff_kind: str
    status: str
    target_type: str | None
    target_id: str | None
    source_snapshot_json: dict[str, Any]
    reviewer_decision_json: dict[str, Any]
    request_json: dict[str, Any]
    error_redacted: str | None
    created_by_membership_id: str
    completed_at: datetime | None
    created_at: datetime


class IpWatchWorkspaceResponse(BaseModel):
    profiles: list[IpWatchProfileResponse] = Field(default_factory=list)
    hits: list[IpWatchHitResponse] = Field(default_factory=list)
    publications: list[IpJournalPublicationResponse] = Field(default_factory=list)
    ingestion_runs: list[IpJournalIngestionRunResponse] = Field(default_factory=list)
    handoffs: list[IpWatchHandoffResponse] = Field(default_factory=list)
