from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

MockHearingModeLiteral = Literal[
    "client_preparation",
    "counsel_practice",
    "witness_preparation",
]
MockHearingSessionStatusLiteral = Literal["active", "completed", "cancelled"]
MockHearingQuestionStatusLiteral = Literal["pending", "answered"]
MockHearingReviewStatusLiteral = Literal["review_required", "reviewed"]
MockHearingConfidenceLiteral = Literal["low", "medium", "high"]
MockHearingQuestionCategoryLiteral = Literal[
    "fact_based",
    "timeline_inconsistency",
    "financial_scrutiny",
    "evidence_contradiction",
    "document_support",
    "intent_motive",
]
MockHearingCompletenessLiteral = Literal["low", "medium", "high"]


class MockHearingStartRequest(BaseModel):
    mode: MockHearingModeLiteral = "client_preparation"
    participant_label: str | None = Field(default=None, max_length=120)
    categories: list[MockHearingQuestionCategoryLiteral] | None = None
    max_questions: int = Field(default=8, ge=1, le=20)


class MockHearingResponseCreateRequest(BaseModel):
    question_id: str | None = Field(default=None, max_length=36)
    response_text: str = Field(min_length=1, max_length=5000)
    elapsed_seconds: int | None = Field(default=None, ge=0, le=86400)


class MockHearingScorecard(BaseModel):
    total_questions: int
    answered_questions: int
    responses_recorded: int
    answered_question_count: int
    unsupported_assertion_count: int
    missing_document_reference_count: int
    contradiction_count: int
    review_required_count: int
    average_response_seconds: float | None = None


class MockHearingResponseRecord(BaseModel):
    id: str
    session_id: str
    question_id: str
    matter_id: str
    source_affidavit_question_id: str | None = None
    source_affidavit_statement_id: str | None = None
    source_attachment_id: str | None = None
    source_chunk_id: str | None = None
    source_chunk_index: int | None = None
    page_reference: str | None = None
    response_text: str
    response_word_count: int
    elapsed_seconds: int | None = None
    answered_question: bool
    consistency_with_affidavit: bool
    unsupported_assertion_added: bool
    missing_document_reference: bool
    contradiction_with_source: bool
    response_completeness: MockHearingCompletenessLiteral
    confidence_label: MockHearingConfidenceLiteral
    feedback_text: str
    source_quote: str
    review_required: bool
    review_status: MockHearingReviewStatusLiteral
    created_at: datetime
    updated_at: datetime


class MockHearingQuestionRecord(BaseModel):
    id: str
    session_id: str
    matter_id: str
    source_affidavit_run_id: str | None = None
    source_affidavit_question_id: str | None = None
    source_affidavit_statement_id: str | None = None
    source_attachment_id: str | None = None
    turn_index: int
    category: MockHearingQuestionCategoryLiteral
    question_text: str
    reason: str
    source_quote: str
    source_chunk_id: str | None = None
    source_chunk_index: int | None = None
    page_reference: str | None = None
    difficulty_label: MockHearingConfidenceLiteral
    status: MockHearingQuestionStatusLiteral
    responses: list[MockHearingResponseRecord] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MockHearingSessionRecord(BaseModel):
    id: str
    matter_id: str
    source_affidavit_run_id: str | None = None
    mode: MockHearingModeLiteral
    participant_label: str | None = None
    status: MockHearingSessionStatusLiteral
    review_status: MockHearingReviewStatusLiteral
    current_question_id: str | None = None
    disclaimer: str
    scorecard: MockHearingScorecard
    created_by_membership_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    updated_at: datetime
    questions: list[MockHearingQuestionRecord] = Field(default_factory=list)


class MockHearingListResponse(BaseModel):
    matter_id: str
    generated_at: datetime
    disclaimer: str
    sessions: list[MockHearingSessionRecord] = Field(default_factory=list)
    latest_session: MockHearingSessionRecord | None = None
