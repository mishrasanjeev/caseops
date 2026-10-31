"""Typed journal-watch, review, and canonical handoff contracts."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

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

NICE_CLASS_MIN = 1
NICE_CLASS_MAX = 45
_GOODS_CLASS_KEY = re.compile(r"\d{1,2}")
# Bookkeeping keys that say how evidence was captured, not what it shows.
_EVIDENCE_BOOKKEEPING_KEYS = frozenset({"capture_method"})
MAX_EVIDENCE_TEXT_LENGTH = 20_000


def _http_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def _validate_nice_classes(value: list[int]) -> list[int]:
    if any(number < NICE_CLASS_MIN or number > NICE_CLASS_MAX for number in value):
        raise ValueError("Trademark classes must be between 1 and 45.")
    return value


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

    # Field-level checks keep each 422 anchored to the field that caused it.
    @field_validator("class_numbers")
    @classmethod
    def validate_class_numbers(cls, value: list[int]) -> list[int]:
        return _validate_nice_classes(value)

    @field_validator("recipient_membership_ids")
    @classmethod
    def validate_recipients(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("Watch recipients must be unique.")
        return value

    @field_validator("device_references")
    @classmethod
    def validate_device_references(cls, value: list[str]) -> list[str]:
        if any(not _http_url(ref) for ref in value):
            raise ValueError("Device references must use HTTP or HTTPS.")
        return value

    @model_validator(mode="after")
    def validate_criteria(self) -> IpWatchProfileCreateRequest:
        # Jurisdiction only narrows a match (services.ip_watch._similarity); a
        # profile with nothing else would be saved and never match anything.
        criteria = (
            self.word_terms,
            self.phonetic_terms,
            self.device_references,
            self.class_numbers,
            self.proprietor_terms,
        )
        if not any(criteria):
            raise ValueError(
                "A watch profile requires at least one criterion: a word, phonetic term, "
                "device, Nice class or proprietor."
            )
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
    publication_kind: Literal["advertisement", "correction", "readvertisement"] = "advertisement"
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

    # Field-level checks keep each 422 anchored to the field that caused it.
    # Cross-field checks read earlier fields from ``info.data``; a field that
    # failed its own validation is absent there and reports its own error.
    @field_validator("class_numbers")
    @classmethod
    def validate_class_numbers(cls, value: list[int]) -> list[int]:
        _validate_nice_classes(value)
        if len(value) != len(set(value)):
            raise ValueError("Publication classes must be unique; list each Nice class once.")
        return value

    @field_validator("goods_services")
    @classmethod
    def validate_goods_services(
        cls, value: dict[str, list[str]], info: ValidationInfo
    ) -> dict[str, list[str]]:
        published = info.data.get("class_numbers")
        cleaned: dict[str, list[str]] = {}
        for key, items in value.items():
            text = key.strip()
            number = int(text) if _GOODS_CLASS_KEY.fullmatch(text) else 0
            if not NICE_CLASS_MIN <= number <= NICE_CLASS_MAX:
                raise ValueError("List goods and services under a Nice class number from 1 to 45.")
            if published is not None and number not in published:
                raise ValueError(
                    f"Class {number} is not a published class; goods/services scope must "
                    "belong to a published class."
                )
            if str(number) in cleaned:
                raise ValueError(f"Class {number} goods and services are listed twice.")
            entries = [item.strip() for item in items]
            if not entries or not all(entries):
                raise ValueError(
                    f"Class {number}: enter each published good or service; "
                    "blank entries are not allowed."
                )
            cleaned[str(number)] = entries
        return cleaned

    @field_validator("publication_scope")
    @classmethod
    def validate_publication_scope(
        cls, value: dict[str, Any], info: ValidationInfo
    ) -> dict[str, Any]:
        if not value:
            return value  # Older callers omit the scope; it is then unstated.
        kind = value.get("scope_kind")
        if kind not in {"full", "partial"}:
            raise ValueError("Publication scope must be full or partial.")
        covered = value.get("published_classes")
        if kind == "full" and covered is None:
            return value
        if (
            not isinstance(covered, list)
            or not covered
            or not all(isinstance(item, int) and not isinstance(item, bool) for item in covered)
        ):
            raise ValueError("A partial publication must list the published classes it covers.")
        published = info.data.get("class_numbers")
        if published is not None and not set(covered).issubset(published):
            raise ValueError("A publication can only cover classes it publishes.")
        if published is not None and kind == "full" and set(covered) != set(published):
            raise ValueError("A full publication covers every published class.")
        return value

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        if not _http_url(value):
            raise ValueError("Journal source URL must use HTTP or HTTPS.")
        return value

    @field_validator("device_reference")
    @classmethod
    def validate_device_reference(cls, value: str | None) -> str | None:
        if value and not _http_url(value):
            raise ValueError("Device reference must use HTTP or HTTPS.")
        return value

    @field_validator("source_retrieved_at")
    @classmethod
    def validate_source_retrieved_at(cls, value: datetime | None) -> datetime | None:
        if value and value.utcoffset() is None:
            raise ValueError("Source retrieval time must include a timezone.")
        return value

    @field_validator("raw_evidence")
    @classmethod
    def validate_raw_evidence(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Fail closed: a journal entry is only as good as the evidence captured with it."""

        captured = [
            item
            for key, item in value.items()
            if key not in _EVIDENCE_BOOKKEEPING_KEYS and isinstance(item, str) and item.strip()
        ]
        if not captured:
            raise ValueError(
                "Capture the source evidence: the journal entry as published, or a "
                "reference to the saved journal page."
            )
        if any(
            isinstance(item, str) and len(item) > MAX_EVIDENCE_TEXT_LENGTH
            for item in value.values()
        ):
            raise ValueError(
                "Captured evidence entries must be 20,000 characters or fewer; record "
                "a reference to the saved page instead."
            )
        return value

    @model_validator(mode="after")
    def validate_publication(self) -> IpJournalPublicationCreate:
        if not (self.mark_text or self.device_reference):
            raise ValueError("A journal entry requires a word mark or device reference.")
        corrected = self.publication_kind in {"correction", "readvertisement"}
        if corrected != bool(self.supersedes_publication_id and self.correction_reason):
            raise ValueError("Correction/re-advertisement requires predecessor and reason.")
        return self


class IpJournalIngestRequest(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=120)
    provider_key: str = Field(min_length=2, max_length=80)
    external_call: bool = False
    cost_minor: int = Field(default=0, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    publications: list[IpJournalPublicationCreate] = Field(min_length=1, max_length=50)


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
    # The evidence the operator captured with the entry (IP-WATCH-02).
    raw_evidence_json: dict[str, Any] = Field(default_factory=dict)
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
    # Hit-linked publications plus the most recent visible journal entries, so a
    # capture with no hits is still listed and can be corrected later.
    publications: list[IpJournalPublicationResponse] = Field(default_factory=list)
    ingestion_runs: list[IpJournalIngestionRunResponse] = Field(default_factory=list)
    handoffs: list[IpWatchHandoffResponse] = Field(default_factory=list)
    # Profiles a journal capture is compared with, across every visible docket
    # (the set ingestion uses). Zero means a capture cannot be evaluated.
    intake_profile_count: int = 0
