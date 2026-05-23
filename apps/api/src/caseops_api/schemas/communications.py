"""Phase B / J12 / M11 — communications log request/response shapes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

CommunicationDirection = Literal["outbound", "inbound"]
CommunicationChannel = Literal["email", "sms", "phone", "meeting", "note"]
CommunicationStatus = Literal[
    "logged", "queued", "sent", "delivered", "opened", "bounced", "failed",
]
CommunicationTimelineFilter = Literal[
    "all", "email", "platform", "notes", "attachments", "internal",
]
CommunicationTimelineItemType = Literal[
    "platform_message",
    "imported_email",
    "email_thread",
    "attachment",
    "internal_note",
    "client_visible_note",
    "outside_counsel_visible_update",
]
CommunicationVisibilityLabel = Literal[
    "internal",
    "firm_only",
    "client_visible",
    "outside_counsel_visible",
    "imported_email",
]


class CommunicationRecord(BaseModel):
    """One log row as returned by GET endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    matter_id: str | None
    client_id: str | None
    direction: CommunicationDirection
    channel: CommunicationChannel
    subject: str | None
    body: str
    recipient_name: str | None
    recipient_email: str | None
    recipient_phone: str | None
    status: CommunicationStatus
    occurred_at: datetime
    delivered_at: datetime | None
    opened_at: datetime | None
    external_message_id: str | None
    created_by_membership_id: str | None
    created_at: datetime


class CommunicationCreateRequest(BaseModel):
    """Slice 1 — manual logging only.

    Required: ``channel`` + ``body``. The matter scope comes from the
    URL path (``/matters/{matter_id}/communications``).

    Slice 2 will introduce a separate ``CommunicationSendRequest`` for
    the SendGrid path that requires recipient_email + uses a template.
    """

    direction: CommunicationDirection = "outbound"
    channel: CommunicationChannel
    subject: str | None = Field(default=None, max_length=400)
    body: str = Field(min_length=1, max_length=20000)
    recipient_name: str | None = Field(default=None, max_length=255)
    recipient_email: EmailStr | None = None
    recipient_phone: str | None = Field(default=None, max_length=64)
    occurred_at: datetime | None = Field(
        default=None,
        description=(
            "When the communication actually happened. Defaults to now "
            "if omitted; set to a past datetime when back-logging."
        ),
    )
    client_id: str | None = Field(
        default=None,
        description=(
            "Optional client this communication relates to. The matter "
            "scope already comes from the URL path."
        ),
    )


class CommunicationListResponse(BaseModel):
    matter_id: str
    communications: list[CommunicationRecord]


class CommunicationTimelineAttachmentReference(BaseModel):
    """Bounded attachment card for the unified communications timeline.

    The timeline intentionally exposes existing matter attachment metadata
    only. It never returns storage keys, hashes, extracted text, OCR text, or
    attachment payloads.
    """

    id: str
    filename: str
    content_type: str | None
    size_bytes: int | None
    document_type: str | None
    uploaded_by_membership_id: str | None
    submitted_by_portal_user_id: str | None
    created_at: datetime


class CommunicationTimelineItem(BaseModel):
    id: str
    item_type: CommunicationTimelineItemType
    visibility: CommunicationVisibilityLabel
    occurred_at: datetime
    title: str
    preview: str | None = None
    actor_label: str | None = None
    direction: CommunicationDirection | None = None
    channel: CommunicationChannel | None = None
    status: CommunicationStatus | None = None
    thread_key: str | None = None
    source_type: str
    source_id: str
    communication_id: str | None = None
    note_id: str | None = None
    attachment_id: str | None = None
    attachment: CommunicationTimelineAttachmentReference | None = None
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


class CommunicationTimelineResponse(BaseModel):
    matter_id: str
    filter: CommunicationTimelineFilter
    generated_at: datetime
    items: list[CommunicationTimelineItem]


class InboundEmailAttachmentImport(BaseModel):
    """One attachment from a manually selected inbound email.

    Content is base64 so this foundation can be exercised through a
    JSON-only backend path. The service decodes it and immediately
    routes it through the existing matter attachment storage pipeline.
    """

    filename: str = Field(min_length=1, max_length=255)
    content_type: str | None = Field(default=None, max_length=255)
    content_base64: str = Field(min_length=1)


class InboundEmailImportRequest(BaseModel):
    """Manual inbound-email import into an explicitly selected matter.

    This is deliberately not a mailbox sweep. The matter is selected by
    the URL path and access-checked by the same matter visibility rules
    as the rest of the communications/document surface.
    """

    provider: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    provider_message_id: str = Field(min_length=1, max_length=255)
    sender_email: EmailStr
    sender_name: str | None = Field(default=None, max_length=255)
    to_recipients: list[EmailStr] = Field(default_factory=list, max_length=50)
    cc_recipients: list[EmailStr] = Field(default_factory=list, max_length=50)
    bcc_recipients: list[EmailStr] = Field(default_factory=list, max_length=50)
    subject: str | None = Field(default=None, max_length=400)
    received_at: datetime | None = None
    body_preview: str | None = Field(default=None, max_length=1000)
    body_text: str | None = Field(default=None, max_length=200000)
    attachments: list[InboundEmailAttachmentImport] = Field(
        default_factory=list,
        max_length=20,
    )


class InboundEmailImportResponse(BaseModel):
    matter_id: str
    communication: CommunicationRecord
    duplicate: bool
    body_attachment_id: str | None
    attachment_ids: list[str]
    processing_job_ids: list[str]
    match_basis: Literal["explicit_matter_selection"] = "explicit_matter_selection"
    automation_mode: Literal["manual_only"] = "manual_only"
