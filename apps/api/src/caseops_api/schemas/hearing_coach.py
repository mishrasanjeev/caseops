from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

HearingCoachStatusLiteral = Literal[
    "consent_required",
    "no_mock_hearing_responses",
]


class HearingCoachStatusResponse(BaseModel):
    matter_id: str
    generated_at: datetime
    status: HearingCoachStatusLiteral
    disclaimer: str
    consent_required: bool
    latest_session_id: str | None = None
    response_count: int = 0
    limitation_notes: list[str] = Field(default_factory=list)


class HearingCoachRunRequest(BaseModel):
    acknowledged: bool = False
    acknowledgement_text: str | None = Field(default=None, max_length=500)


class HearingCoachMetricSummary(BaseModel):
    total_responses: int
    answered_question_count: int
    source_reference_used_count: int
    unsupported_assertion_count: int
    contradiction_count: int
    missing_exhibit_reference_count: int
    evasiveness_marker_count: int
    overlong_response_count: int
    average_clarity_score: int
    average_completeness_score: int
    review_required_count: int


class HearingCoachFeedbackItem(BaseModel):
    response_id: str
    question_id: str
    mock_hearing_session_id: str
    source_affidavit_question_id: str | None = None
    source_affidavit_statement_id: str | None = None
    source_attachment_id: str | None = None
    source_chunk_id: str | None = None
    source_chunk_index: int | None = None
    page_reference: str | None = None
    question_text: str
    transcript_excerpt: str
    source_quote: str
    answered_question: bool
    source_reference_used: bool
    unsupported_assertion_count: int
    contradiction_count: int
    clarity_score: int
    completeness_score: int
    evasiveness_marker: bool
    overlong_response_marker: bool
    missing_exhibit_reference: bool
    review_required: bool
    feedback: list[str] = Field(default_factory=list)
    improvement_checklist: list[str] = Field(default_factory=list)


class HearingCoachReportResponse(BaseModel):
    matter_id: str
    mock_hearing_session_id: str
    generated_at: datetime
    status: Literal["supported"]
    disclaimer: str
    consent_acknowledged: bool
    metrics: HearingCoachMetricSummary
    feedback_items: list[HearingCoachFeedbackItem] = Field(default_factory=list)
    limitation_notes: list[str] = Field(default_factory=list)
