from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

InboundEmailAliasStatusLiteral = Literal["enabled", "disabled"]
InboundEmailEventStatusLiteral = Literal[
    "new",
    "linked_metadata",
    "content_import_requested",
    "content_imported",
    "ignored",
    "rejected",
    "failed",
]
InboundEmailEventReviewActionLiteral = Literal[
    "link_to_matter",
    "create_note",
    "create_task",
    "request_attachment_import",
    "ignore",
    "reject",
]


class InboundEmailAliasRecord(BaseModel):
    id: str
    company_id: str
    matter_id: str | None = None
    alias_type: Literal["tenant", "matter"]
    alias_address: str
    status: InboundEmailAliasStatusLiteral
    allowed_senders: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    retention_days: int = Field(ge=1)
    spam_security_status: str
    created_at: datetime
    updated_at: datetime


class InboundEmailAliasListResponse(BaseModel):
    aliases: list[InboundEmailAliasRecord]


class InboundEmailAliasCreateRequest(BaseModel):
    matter_id: str | None = Field(default=None, max_length=36)
    status: InboundEmailAliasStatusLiteral = "disabled"
    allowed_senders: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    retention_days: int = Field(default=30, ge=1, le=3650)


class InboundEmailAliasUpdateRequest(BaseModel):
    status: InboundEmailAliasStatusLiteral | None = None
    allowed_senders: list[str] | None = None
    allowed_domains: list[str] | None = None
    retention_days: int | None = Field(default=None, ge=1, le=3650)


class InboundEmailAttachmentMetadata(BaseModel):
    filename: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    scan_status: str = "pending_review"


class InboundEmailEventRecord(BaseModel):
    id: str
    company_id: str
    alias_id: str | None = None
    matched_matter_id: str | None = None
    linked_matter_id: str | None = None
    communication_id: str | None = None
    provider: str
    provider_message_id: str
    from_display: str | None = None
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str | None = None
    received_at: datetime
    snippet: str | None = None
    attachment_metadata: list[InboundEmailAttachmentMetadata] = Field(default_factory=list)
    status: InboundEmailEventStatusLiteral
    redacted_failure_reason: str | None = None
    provenance: dict | None = None
    created_at: datetime
    updated_at: datetime


class InboundEmailEventListResponse(BaseModel):
    events: list[InboundEmailEventRecord]
    pending_count: int = Field(ge=0)


class InboundEmailWebhookRequest(BaseModel):
    provider: str = Field(default="local_safe", max_length=40)
    provider_message_id: str = Field(min_length=1, max_length=255)
    from_email: str | None = Field(default=None, max_length=320)
    from_display: str | None = Field(default=None, max_length=255)
    to_addresses: list[str] = Field(default_factory=list)
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str | None = Field(default=None, max_length=500)
    received_at: datetime | None = None
    snippet: str | None = Field(default=None, max_length=1000)
    attachments: list[InboundEmailAttachmentMetadata] = Field(default_factory=list)


class InboundEmailWebhookResponse(BaseModel):
    accepted: bool
    event_id: str | None = None
    status: InboundEmailEventStatusLiteral | Literal["rejected"]


class InboundEmailEventReviewRequest(BaseModel):
    action: InboundEmailEventReviewActionLiteral
    matter_id: str | None = Field(default=None, min_length=1, max_length=36)
    note_body: str | None = Field(default=None, max_length=4000)
    task_title: str | None = Field(default=None, max_length=255)
    task_description: str | None = Field(default=None, max_length=2000)


class InboundEmailEventReviewResponse(BaseModel):
    event: InboundEmailEventRecord
    note_id: str | None = None
    task_id: str | None = None
