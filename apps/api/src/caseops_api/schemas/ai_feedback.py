from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AIFeedbackSurface = Literal["product_guide", "workspace_assistant"]
AIFeedbackType = Literal["rating", "report"]
AIFeedbackRating = Literal["helpful", "not_helpful"]
AIFeedbackCategory = Literal[
    "answer_quality",
    "wrong_navigation",
    "missing_permission_explanation",
    "unsafe_citation",
    "outdated_guidance",
    "missing_guidance",
    "other",
]
AIFeedbackStatus = Literal["open", "in_review", "resolved", "dismissed"]
ProductGuideTargetType = Literal[
    "product_guide_command",
    "product_guide_section",
    "product_guide_permission",
    "product_guide_no_match",
]


class AIFeedbackSubmission(BaseModel):
    submission_key: str = Field(min_length=8, max_length=80)
    feedback_type: AIFeedbackType
    rating: AIFeedbackRating | None = None
    category: AIFeedbackCategory | None = None
    comment: str | None = Field(default=None, max_length=1000)

    @field_validator("submission_key", "comment", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def validate_feedback_shape(self) -> Self:
        if self.feedback_type == "rating":
            if self.rating is None or self.category is not None:
                raise ValueError("Rating feedback requires rating and must not include category.")
        elif self.rating is not None or self.category is None:
            raise ValueError("Report feedback requires category and must not include rating.")
        return self


class ProductGuideFeedbackCreateRequest(AIFeedbackSubmission):
    target_type: ProductGuideTargetType
    target_id: str = Field(min_length=1, max_length=160)
    catalog_fingerprint: str = Field(min_length=64, max_length=64)


class WorkspaceAssistantFeedbackCreateRequest(AIFeedbackSubmission):
    session_id: str = Field(min_length=1, max_length=36)
    turn_id: str = Field(min_length=1, max_length=36)


class AIFeedbackRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    submitted_by_membership_id: str
    reviewed_by_membership_id: str | None
    surface: AIFeedbackSurface
    target_type: str
    target_id: str
    parent_target_id: str | None
    target_version: str | None
    target_href: str | None
    feedback_type: AIFeedbackType
    rating: AIFeedbackRating | None
    category: AIFeedbackCategory | None
    priority: Literal["normal", "high"]
    comment: str | None
    status: AIFeedbackStatus
    review_notes: str | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AIFeedbackListResponse(BaseModel):
    items: list[AIFeedbackRecord]
    limit: int
    has_more: bool


class AIFeedbackReviewRequest(BaseModel):
    expected_updated_at: datetime
    status: Literal["in_review", "resolved", "dismissed"]
    review_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("review_notes", mode="before")
    @classmethod
    def strip_review_notes(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None
