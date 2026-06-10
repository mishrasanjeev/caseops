"""Tenant-safe mailbox connector schemas.

Gmail ingestion is review-first: API responses expose message metadata, snippets,
and attachment candidates only. They never expose OAuth tokens, raw provider
payloads, message bodies, or attachment bytes.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MailboxProviderLiteral = Literal["gmail", "outlook_mail"]
MailboxConnectionStatusLiteral = Literal["connected", "revoked", "error"]
MailboxImportStatusLiteral = Literal[
    "queued",
    "imported",
    "unmatched",
    "duplicate",
    "failed",
    "dead_letter",
    "ignored",
    "resolved",
    "new",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
]
MailboxAttachmentCandidateStatusLiteral = Literal[
    "needs_review",
    "approved_imported",
    "rejected",
    "duplicate_skipped",
]
MailboxWebhookStatusLiteral = Literal["queued", "processed", "failed", "dead_letter"]
MailboxReviewActionLiteral = Literal["approve_import", "reject"]
MailboxMessageReviewActionLiteral = Literal[
    "link_metadata",
    "create_note",
    "create_task",
    "request_content_import",
    "ignore",
]


class MailboxConnectionRecord(BaseModel):
    id: str
    company_id: str
    membership_id: str
    provider: MailboxProviderLiteral
    provider_account_id: str | None
    display_email: str | None
    status: MailboxConnectionStatusLiteral
    scopes: list[str] = Field(default_factory=list)
    last_history_id: str | None = None
    watch_expires_at: datetime | None = None
    last_import_at: datetime | None = None
    connected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MailboxStatusResponse(BaseModel):
    provider: MailboxProviderLiteral = "gmail"
    configured: bool
    webhook_configured: bool
    missing_config_names: list[str] = Field(default_factory=list)
    missing_webhook_config_names: list[str] = Field(default_factory=list)
    connections: list[MailboxConnectionRecord]


class MailboxConnectionStartResponse(BaseModel):
    provider: MailboxProviderLiteral = "gmail"
    provider_available: bool
    auth_url: str | None = None
    unavailable_reason: str | None = None


class MailboxConnectionCallbackResponse(BaseModel):
    provider: MailboxProviderLiteral = "gmail"
    connected: bool
    connection: MailboxConnectionRecord


class MailboxImportRequest(BaseModel):
    limit: int = Field(default=25, ge=1, le=100)


class MailboxImportSummary(BaseModel):
    imported: int = Field(ge=0)
    unmatched: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    failed: int = Field(ge=0)
    attachment_candidates: int = Field(ge=0)


class MailboxMessageImportRecord(BaseModel):
    id: str
    company_id: str
    mailbox_connection_id: str
    provider: MailboxProviderLiteral = "gmail"
    matter_id: str | None
    communication_id: str | None
    provider_message_id: str
    provider_thread_id: str | None
    subject: str | None
    sender_name: str | None
    occurred_at: datetime | None
    snippet: str | None
    labels: list[str] = Field(default_factory=list)
    attachment_count: int = Field(ge=0)
    status: MailboxImportStatusLiteral
    last_error_redacted: str | None
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    next_attempt_at: datetime | None
    dead_letter_reason: str | None
    created_at: datetime
    updated_at: datetime


class MailboxImportResponse(BaseModel):
    summary: MailboxImportSummary
    imports: list[MailboxMessageImportRecord]


class MailboxMessageReviewRequest(BaseModel):
    action: MailboxMessageReviewActionLiteral
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    note_body: str | None = Field(default=None, max_length=4000)
    task_title: str | None = Field(default=None, max_length=255)
    task_description: str | None = Field(default=None, max_length=2000)


class MailboxMessageReviewResponse(BaseModel):
    import_record: MailboxMessageImportRecord
    matter_id: str | None = None
    communication_id: str | None = None
    note_id: str | None = None
    task_id: str | None = None
    content_import_queued: bool = False


class MailboxAttachmentCandidateRecord(BaseModel):
    id: str
    company_id: str
    message_import_id: str
    matter_id: str | None
    filename: str | None
    content_type: str | None
    size_bytes: int | None
    status: MailboxAttachmentCandidateStatusLiteral
    created_at: datetime
    updated_at: datetime


class MailboxAttachmentCandidateListResponse(BaseModel):
    candidates: list[MailboxAttachmentCandidateRecord]
    pending_count: int = Field(ge=0)


class MailboxAttachmentCandidateReviewRequest(BaseModel):
    action: MailboxReviewActionLiteral


class MailboxAttachmentCandidateReviewResponse(BaseModel):
    candidate: MailboxAttachmentCandidateRecord
    imported_attachment_id: str | None = None


class MailboxWatchResponse(BaseModel):
    provider: MailboxProviderLiteral = "gmail"
    watch_started: bool
    webhook_configured: bool
    history_id: str | None = None
    watch_expires_at: datetime | None = None
    missing_config_names: list[str] = Field(default_factory=list)


class MailboxWebhookIngestResponse(BaseModel):
    provider: MailboxProviderLiteral = "gmail"
    accepted: bool
    status: MailboxWebhookStatusLiteral
    event_id: str | None = None


class OutlookMailCandidateCreateRequest(BaseModel):
    provider_message_id: str = Field(min_length=1, max_length=255)
    provider_thread_id: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=500)
    sender_email: str | None = Field(default=None, max_length=320)
    sender_name: str | None = Field(default=None, max_length=255)
    occurred_at: datetime | None = None
    snippet: str | None = Field(default=None, max_length=1000)
    labels: list[str] = Field(default_factory=list)
    attachment_count: int = Field(default=0, ge=0, le=1000)
    suggested_matter_id: str | None = Field(default=None, max_length=36)

