"""Typed contracts for the public Trade Marks Journal feed."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class IpJournalFeedSettingUpdateRequest(BaseModel):
    enabled: bool
    # Omit when no setting exists yet; otherwise the version you loaded.
    expected_version: int | None = Field(default=None, ge=1)


class IpJournalFeedSettingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    version: int
    run_as_membership_id: str
    updated_by_membership_id: str
    updated_at: datetime


class IpPublicJournalCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    reason_code: str | None
    http_status: int | None
    issues_listed: int
    documents_discovered: int
    checked_at: datetime


class IpPublicJournalDocumentResponse(BaseModel):
    """Public source lineage for one listed journal PDF."""

    id: str
    journal_number: str
    journal_date: date
    available_on: date | None
    file_name: str
    source_url: str
    status: str
    attempts: int
    content_sha256: str | None
    byte_size: int | None
    page_count: int | None
    entry_count: int
    review_count: int
    parser_version: str | None
    error_code: str | None
    retrieved_at: datetime | None
    # This workspace's comparison of the document, if one ran.
    workspace_status: str | None = None
    workspace_entries_compared: int | None = None


class IpPublicJournalReviewItemResponse(BaseModel):
    """A span of a public journal PDF the parser could not read with confidence."""

    id: str
    document_id: str
    journal_number: str
    journal_date: date
    page_start: int
    page_end: int
    journal_page: str | None
    review_reason: str | None
    application_number: str | None
    source_url: str


class IpJournalFeedStatusResponse(BaseModel):
    source_key: str
    listing_url: str
    attribution: str
    # Platform kill switch; when false no IP India request is made at all.
    global_enabled: bool
    setting: IpJournalFeedSettingResponse | None = None
    last_check: IpPublicJournalCheckResponse | None = None
    documents: list[IpPublicJournalDocumentResponse] = Field(default_factory=list)
    review_items: list[IpPublicJournalReviewItemResponse] = Field(default_factory=list)
    review_total: int = 0
