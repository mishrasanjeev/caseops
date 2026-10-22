"""Explicit public-contact projection; never serialize account/auth/billing JSON."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ConsoleLeadNotification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "not_requested",
        "pending",
        "sending",
        "accepted",
        "retry_pending",
        "exhausted",
        "outcome_unknown",
    ]
    attempts: int = Field(ge=0)
    last_error_code: str | None
    eligible: bool


class ConsoleLead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    submitted_at: datetime
    contact_name: str | None
    contact_email: str | None
    contact_mobile: str | None
    company_name: str | None
    segment: str
    selected_plan: str | None
    source: str
    role: str | None
    intent: str | None
    notes: str | None
    privacy_notice_version: str | None
    notification: ConsoleLeadNotification


class ConsoleLeadsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[ConsoleLead] = Field(max_length=100)
    next_cursor: str | None
    has_more: bool
