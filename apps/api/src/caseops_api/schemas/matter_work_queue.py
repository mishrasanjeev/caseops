"""Read-only Matter-task work queue; IP work has a separate contract."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Ownership = Literal["mine", "team", "unassigned"]
DateScope = Literal["all", "dated", "undated"]


class WorkQueueMatter(BaseModel):
    id: str
    title: str
    matter_code: str
    status: Literal["intake", "active", "on_hold"]
    is_active: Literal[True]
    lifecycle_version: int


class WorkQueueTask(BaseModel):
    id: str
    title: str
    status: Literal["todo", "in_progress", "blocked"]
    priority: Literal["low", "medium", "high", "urgent"]
    due_on: date | None
    owner_membership_id: str | None
    created_at: datetime
    updated_at: datetime
    matter: WorkQueueMatter


class MatterWorkQueuePage(BaseModel):
    scope: Literal["matter_tasks"] = "matter_tasks"
    ownership: Ownership
    dates: DateScope
    due_from: date | None
    due_to: date | None
    sort: Literal["due_on_created_at_id"] = "due_on_created_at_id"
    limit: int = Field(ge=1, le=25)
    items: list[WorkQueueTask]
    next_cursor: str | None
