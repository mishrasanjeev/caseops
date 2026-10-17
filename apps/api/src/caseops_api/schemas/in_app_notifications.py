from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NotificationState = Literal["unread", "read", "dismissed"]


class InAppNotificationUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_status: NotificationState
    status: NotificationState


class RecipientNotificationRecord(BaseModel):
    id: str
    docket_id: str
    title: str
    body: str | None
    status: NotificationState
    created_at: datetime
    read_at: datetime | None


class RecipientNotificationPage(BaseModel):
    items: list[RecipientNotificationRecord] = Field(default_factory=list)
    next_cursor: str | None = None
