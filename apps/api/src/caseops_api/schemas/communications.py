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
