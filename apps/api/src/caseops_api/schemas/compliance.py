from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ComplianceReviewAction = Literal["confirm", "reject", "waive", "complete"]


class ComplianceExtractionRunRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    court_order_id: str | None
    attachment_id: str | None
    source_type: str
    trigger: str
    status: str
    skip_reason: str | None = None
    model_run_id: str | None = None
    parser_version: str
    started_at: datetime | None
    completed_at: datetime | None
    error_message_redacted: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class ComplianceItemRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str
    court_order_id: str | None
    attachment_id: str | None
    extraction_run_id: str
    description: str
    responsible_party: str | None
    due_on: date | None
    timeline_text: str | None
    filing_requirement: str | None
    court_direction: str | None
    next_action: str | None
    source_snippet: str
    source_page: int | None
    source_paragraph: str | None
    confidence_label: str
    status: str
    review_status: str
    generated_task_id: str | None
    generated_deadline_id: str | None
    dedupe_key: str
    rejection_reason: str | None = None
    waived_reason: str | None = None
    completed_at: datetime | None = None
    reviewed_by_membership_id: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ComplianceListResponse(BaseModel):
    runs: list[ComplianceExtractionRunRecord]
    items: list[ComplianceItemRecord]


class ComplianceItemUpdateRequest(BaseModel):
    action: ComplianceReviewAction
    description: str | None = Field(default=None, min_length=3, max_length=2000)
    responsible_party: str | None = Field(default=None, max_length=255)
    due_on: date | None = None
    timeline_text: str | None = Field(default=None, max_length=500)
    filing_requirement: str | None = Field(default=None, max_length=500)
    court_direction: str | None = Field(default=None, max_length=4000)
    next_action: str | None = Field(default=None, max_length=4000)
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator(
        "description",
        "responsible_party",
        "timeline_text",
        "filing_requirement",
        "court_direction",
        "next_action",
        "reason",
        mode="before",
    )
    @classmethod
    def strip_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value


class ComplianceRetryResponse(BaseModel):
    run: ComplianceExtractionRunRecord
    items: list[ComplianceItemRecord]
