from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from caseops_api.schemas.in_app_notifications import NotificationState


class InboxTarget(BaseModel):
    kind: Literal["matter", "ip_docket"]
    id: str


class InboxRecord(BaseModel):
    id: str
    title: str
    body: str | None
    status: NotificationState
    created_at: AwareDatetime
    read_at: AwareDatetime | None
    target: InboxTarget
    target_label: str | None


class InboxPage(BaseModel):
    items: list[InboxRecord] = Field(default_factory=list, max_length=50)
    next_cursor: str | None = None
    scope: Literal["delivered_hearing_and_ip_renewal"] = "delivered_hearing_and_ip_renewal"
    # A page can contain no current receipts and still have older candidates.
    # Consumers must follow next_cursor, not infer global emptiness.
    history_exhausted: bool
