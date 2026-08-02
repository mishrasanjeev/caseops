from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

CaseTrackingUpdateTypeLiteral = Literal[
    "new_order",
    "new_judgment",
    "hearing_update",
    "status_change",
    "case_metadata_change",
]


class CaseTrackingProviderStatusResponse(BaseModel):
    enabled: bool
    provider: str
    configured: bool
    reason: str | None = None


def _normalized_cnr(value: str | None) -> str | None:
    if not value:
        return None
    normalized = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return normalized or None


class CaseTrackingSearchRequest(BaseModel):
    query: str | None = Field(default=None, max_length=160)
    cnr_number: str | None = Field(default=None, max_length=32)
    case_number: str | None = Field(default=None, max_length=120)
    court_code: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    court_name: str | None = Field(default=None, max_length=255)

    @field_validator("query", "cnr_number", "case_number", "court_code", "state", "court_name")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("cnr_number")
    @classmethod
    def _validate_cnr(cls, value: str | None) -> str | None:
        normalized = _normalized_cnr(value)
        if normalized is not None and len(normalized) < 8:
            raise ValueError("CNR number looks too short.")
        return value

    @model_validator(mode="after")
    def _require_identity(self) -> CaseTrackingSearchRequest:
        if not self.query and not self.cnr_number and not self.case_number:
            raise ValueError("Provide a search query, CNR number, or case number.")
        return self


class CaseTrackingSearchResultRecord(BaseModel):
    provider: str
    cnr_number: str | None
    case_number: str | None
    court_code: str | None
    court_name: str | None
    case_title: str
    party_names: list[str] = Field(default_factory=list)
    current_status: str | None
    current_stage: str | None
    next_hearing_on: date | None
    source_url: str | None = None
    provenance_label: str = "Provider-normalized case status"


class CaseTrackingSearchResponse(BaseModel):
    provider: str
    results: list[CaseTrackingSearchResultRecord]


class CaseTrackingBookmarkCreateRequest(BaseModel):
    provider: str = "ecourtsindia"
    cnr_number: str | None = Field(default=None, max_length=32)
    case_number: str | None = Field(default=None, max_length=120)
    court_code: str | None = Field(default=None, max_length=80)
    court_name: str | None = Field(default=None, max_length=255)
    case_title: str = Field(min_length=1, max_length=500)
    party_names: list[str] = Field(default_factory=list, max_length=20)
    current_status: str | None = Field(default=None, max_length=160)
    current_stage: str | None = Field(default=None, max_length=160)
    next_hearing_on: date | None = None
    matter_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, max_length=160)
    notification_enabled: bool = True
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator(
        "provider",
        "cnr_number",
        "case_number",
        "court_code",
        "court_name",
        "current_status",
        "current_stage",
        "matter_id",
        "name",
    )
    @classmethod
    def _strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("cnr_number")
    @classmethod
    def _validate_cnr(cls, value: str | None) -> str | None:
        normalized = _normalized_cnr(value)
        if normalized is not None and len(normalized) < 8:
            raise ValueError("CNR number looks too short.")
        return value

    @model_validator(mode="after")
    def _require_identity(self) -> CaseTrackingBookmarkCreateRequest:
        if not self.cnr_number and not self.case_number:
            raise ValueError("Bookmark requires a CNR number or case number.")
        return self


class TrackedCaseRecord(BaseModel):
    id: str
    provider: str
    cnr_number: str | None
    case_number: str | None
    court_code: str | None
    court_name: str | None
    case_title: str
    party_names: list[str]
    current_status: str | None
    current_stage: str | None
    next_hearing_on: date | None
    last_provider_checked_at: datetime | None
    last_provider_attempted_at: datetime | None = None
    last_provider_successful_at: datetime | None = None
    next_provider_refresh_at: datetime | None = None
    freshness_status: Literal["fresh", "stale", "never_succeeded", "disabled", "quarantined"] = (
        "never_succeeded"
    )
    response_class: str | None = None
    last_operation_id: str | None = None
    provider_health: Literal[
        "healthy", "degraded", "unhealthy", "disabled", "quarantined"
    ] = "unhealthy"
    manual_refresh_allowed: bool = False
    manual_refresh_disabled_reason: str | None = None
    refresh_cost_minor: int = 0
    refresh_currency: str = "INR"
    last_error: str | None
    metadata: dict[str, object] = Field(default_factory=dict)


class CaseTrackingBookmarkRecord(BaseModel):
    id: str
    company_id: str
    tracked_case_id: str
    created_by_membership_id: str
    matter_id: str | None
    name: str | None
    notification_enabled: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    tracked_case: TrackedCaseRecord
    update_count: int = 0


class CaseTrackingBookmarkListResponse(BaseModel):
    bookmarks: list[CaseTrackingBookmarkRecord]


class CaseTrackingBookmarkUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    notification_enabled: bool | None = None
    is_archived: bool | None = None

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class CaseTrackingUpdateRecord(BaseModel):
    id: str
    company_id: str
    tracked_case_id: str
    update_type: CaseTrackingUpdateTypeLiteral
    source_record_key: str
    title: str
    summary: str | None
    ai_summary: dict[str, object] | None = None
    source_url: str | None
    order_date: date | None
    hearing_date: date | None
    provider_metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class CaseTrackingUpdateListResponse(BaseModel):
    updates: list[CaseTrackingUpdateRecord]


class CaseTrackingRefreshResponse(BaseModel):
    bookmark: CaseTrackingBookmarkRecord
    created_updates: list[CaseTrackingUpdateRecord]
    delivery_status: Literal["in_app_only"] = "in_app_only"


class CaseTrackingPollRunRecord(BaseModel):
    id: str
    company_id: str | None
    status: str
    started_at: datetime
    completed_at: datetime | None
    checked_count: int
    update_count: int
    error_count: int
    skipped_count: int = 0
    blocked_count: int = 0
    provider_call_count: int = 0
    backlog_remaining_count: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
