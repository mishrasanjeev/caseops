"""Pydantic shapes for the GC intake queue (Sprint 8b BG-025)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

IntakeStatusLiteral = Literal[
    "new", "triaging", "in_progress", "completed", "rejected"
]
IntakePriorityLiteral = Literal["low", "medium", "high", "urgent"]

# Common intake categories for corporate legal teams. Kept as a free
# string on the backend so firms can add their own; the literal here
# is the UI's default picklist.
IntakeCategoryLiteral = Literal[
    "contract_review",
    "policy_question",
    "litigation_support",
    "compliance",
    "employment",
    "ip_trademark",
    "m_and_a",
    "regulatory",
    "other",
]


class IntakeRequestCreateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    category: IntakeCategoryLiteral = "other"
    priority: IntakePriorityLiteral = "medium"
    requester_name: str = Field(min_length=2, max_length=255)
    requester_email: EmailStr | None = None
    business_unit: str | None = Field(default=None, min_length=2, max_length=120)
    description: str = Field(min_length=10, max_length=8000)
    desired_by: date | None = None


class IntakeRequestUpdateRequest(BaseModel):
    status: IntakeStatusLiteral | None = None
    priority: IntakePriorityLiteral | None = None
    assigned_to_membership_id: str | None = Field(default=None, min_length=0)
    triage_notes: str | None = Field(default=None, max_length=8000)


class IntakeRequestPromoteRequest(BaseModel):
    """Promote an intake request into a real Matter. Status flips to
    ``in_progress`` and ``linked_matter_id`` is set.
    """

    matter_code: str = Field(
        min_length=2, max_length=40, pattern=r"^[A-Za-z0-9\-_/]+$"
    )
    matter_title: str | None = Field(default=None, min_length=3, max_length=255)
    practice_area: str | None = Field(default=None, max_length=120)
    forum_level: Literal["lower_court", "high_court", "supreme_court", "tribunal"] = (
        "high_court"
    )


class IntakeRequestRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    submitted_by_membership_id: str | None
    submitted_by_name: str | None
    assigned_to_membership_id: str | None
    assigned_to_name: str | None
    linked_matter_id: str | None
    linked_matter_code: str | None
    title: str
    category: str
    priority: IntakePriorityLiteral
    status: IntakeStatusLiteral
    requester_name: str
    requester_email: str | None
    business_unit: str | None
    description: str
    desired_by: date | None
    triage_notes: str | None
    created_at: datetime
    updated_at: datetime


class IntakeRequestListResponse(BaseModel):
    requests: list[IntakeRequestRecord]
