"""Transcript-first hearing performance coach.

LI-S13 deliberately derives observable preparation metrics from typed mock
hearing responses only. It does not process recordings or infer personal
condition.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    Matter,
    MockHearingQuestion,
    MockHearingResponse,
    MockHearingSession,
)
from caseops_api.schemas.hearing_coach import (
    HearingCoachFeedbackItem,
    HearingCoachMetricSummary,
    HearingCoachReportResponse,
    HearingCoachRunRequest,
    HearingCoachStatusResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

DISCLAIMER = (
    "Hearing coach is a transcript-first training aid for hearing preparation, "
    "not legal advice. Feedback is limited to observable typed-response content "
    "and source-linked mock hearing material."
)
_LIMITATION_NOTES = [
    "Uses typed mock-hearing responses and source-backed affidavit question banks only.",
    "Does not determine outcomes or infer intent; it only reports observable response markers.",
    "Counsel must review all feedback before relying on it in preparation.",
]
_DOCUMENT_RE = re.compile(
    r"\b(?:annexure|exhibit|invoice|receipt|agreement|ledger|bank|statement|"
    r"document|record|email|letter|notice|cheque|contract|page|paragraph|para)\b",
    re.IGNORECASE,
)
_DIRECT_UNCERTAINTY_RE = re.compile(
    r"\b(?:i\s+do\s+not\s+know|i\s+don't\s+know|not\s+sure|cannot\s+say|"
    r"can't\s+say)\b",
    re.IGNORECASE,
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")
_SOURCE_REFERENCE_CATEGORIES = {
    "document_support",
    "financial_scrutiny",
    "evidence_contradiction",
}


def get_hearing_coach_status(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> HearingCoachStatusResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    mock_session = _latest_mock_session(session, matter)
    responses = _session_responses(mock_session) if mock_session else []
    status_value = (
        "consent_required" if responses else "no_mock_hearing_responses"
    )
    record_from_context(
        session,
        context,
        action="hearing_coach.viewed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={
            "status": status_value,
            "latest_session_id": mock_session.id if mock_session else None,
            "response_count": len(responses),
        },
    )
    session.commit()
    return HearingCoachStatusResponse(
        matter_id=matter.id,
        generated_at=datetime.now(UTC),
        status=status_value,  # type: ignore[arg-type]
        disclaimer=DISCLAIMER,
        consent_required=True,
        latest_session_id=mock_session.id if mock_session else None,
        response_count=len(responses),
        limitation_notes=list(_LIMITATION_NOTES),
    )


def generate_hearing_coach_report(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    session_id: str,
    payload: HearingCoachRunRequest,
) -> HearingCoachReportResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    if not payload.acknowledged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hearing coach requires acknowledgement before analysis.",
        )
    mock_session = _load_mock_session(session, matter=matter, session_id=session_id)
    responses = _session_responses(mock_session)
    if not responses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No typed mock-hearing responses are available for coaching.",
        )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="generate a hearing coach report",
    )

    report = _report_record(matter=matter, mock_session=mock_session, responses=responses)
    record_from_context(
        session,
        context,
        action="hearing_coach.generated",
        target_type="mock_hearing_session",
        target_id=mock_session.id,
        matter_id=matter.id,
        metadata={
            "consent_acknowledged": True,
            "response_count": report.metrics.total_responses,
            "answered_question_count": report.metrics.answered_question_count,
            "source_reference_used_count": report.metrics.source_reference_used_count,
            "unsupported_assertion_count": report.metrics.unsupported_assertion_count,
            "contradiction_count": report.metrics.contradiction_count,
            "missing_exhibit_reference_count": report.metrics.missing_exhibit_reference_count,
            "evasiveness_marker_count": report.metrics.evasiveness_marker_count,
            "overlong_response_count": report.metrics.overlong_response_count,
            "review_required_count": report.metrics.review_required_count,
        },
    )
    session.commit()
    return report


def _load_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _latest_mock_session(session: Session, matter: Matter) -> MockHearingSession | None:
    return session.scalar(
        select(MockHearingSession)
        .options(
            selectinload(MockHearingSession.questions).selectinload(
                MockHearingQuestion.responses
            )
        )
        .where(
            MockHearingSession.company_id == matter.company_id,
            MockHearingSession.matter_id == matter.id,
        )
        .order_by(MockHearingSession.started_at.desc(), MockHearingSession.id.desc())
    )


def _load_mock_session(
    session: Session,
    *,
    matter: Matter,
    session_id: str,
) -> MockHearingSession:
    mock_session = session.scalar(
        select(MockHearingSession)
        .options(
            selectinload(MockHearingSession.questions).selectinload(
                MockHearingQuestion.responses
            )
        )
        .where(
            MockHearingSession.id == session_id,
            MockHearingSession.company_id == matter.company_id,
            MockHearingSession.matter_id == matter.id,
        )
    )
    if mock_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock hearing session not found.",
        )
    return mock_session


def _session_responses(mock_session: MockHearingSession | None) -> list[MockHearingResponse]:
    if mock_session is None:
        return []
    return sorted(
        [response for question in mock_session.questions for response in question.responses],
        key=lambda row: (row.created_at, row.id),
    )


def _report_record(
    *,
    matter: Matter,
    mock_session: MockHearingSession,
    responses: list[MockHearingResponse],
) -> HearingCoachReportResponse:
    items = [_feedback_item(response) for response in responses]
    total = len(items)
    metrics = HearingCoachMetricSummary(
        total_responses=total,
        answered_question_count=sum(1 for item in items if item.answered_question),
        source_reference_used_count=sum(1 for item in items if item.source_reference_used),
        unsupported_assertion_count=sum(
            item.unsupported_assertion_count for item in items
        ),
        contradiction_count=sum(item.contradiction_count for item in items),
        missing_exhibit_reference_count=sum(
            1 for item in items if item.missing_exhibit_reference
        ),
        evasiveness_marker_count=sum(1 for item in items if item.evasiveness_marker),
        overlong_response_count=sum(1 for item in items if item.overlong_response_marker),
        average_clarity_score=round(
            sum(item.clarity_score for item in items) / total
        ),
        average_completeness_score=round(
            sum(item.completeness_score for item in items) / total
        ),
        review_required_count=sum(1 for item in items if item.review_required),
    )
    return HearingCoachReportResponse(
        matter_id=matter.id,
        mock_hearing_session_id=mock_session.id,
        generated_at=datetime.now(UTC),
        status="supported",
        disclaimer=DISCLAIMER,
        consent_acknowledged=True,
        metrics=metrics,
        feedback_items=items,
        limitation_notes=list(_LIMITATION_NOTES),
    )


def _feedback_item(response: MockHearingResponse) -> HearingCoachFeedbackItem:
    question = response.question
    word_count = response.response_word_count
    source_reference_used = bool(_DOCUMENT_RE.search(response.response_text))
    overlong = word_count > 120
    evasiveness_marker = (
        not response.answered_question
        or word_count < 8
        or bool(_DIRECT_UNCERTAINTY_RE.search(response.response_text))
    )
    missing_exhibit_reference = (
        response.missing_document_reference
        or (
            question.category in _SOURCE_REFERENCE_CATEGORIES
            and not source_reference_used
        )
    )
    unsupported_count = 1 if response.unsupported_assertion_added else 0
    contradiction_count = 1 if response.contradiction_with_source else 0
    clarity = _clarity_score(
        answered=response.answered_question,
        word_count=word_count,
        unsupported=unsupported_count,
        contradiction=contradiction_count,
        overlong=overlong,
        evasiveness_marker=evasiveness_marker,
    )
    completeness = _completeness_score(
        completeness_label=response.response_completeness,
        source_reference_used=source_reference_used,
        missing_exhibit_reference=missing_exhibit_reference,
        unsupported=unsupported_count,
        contradiction=contradiction_count,
    )
    feedback: list[str] = []
    checklist: list[str] = []
    if response.answered_question:
        feedback.append("The answer addresses the question in typed form.")
    else:
        feedback.append("The typed answer is too short to assess against the question.")
        checklist.append("Start with a direct answer to the question asked.")
    if source_reference_used:
        feedback.append("The answer refers to a document or record marker.")
    elif missing_exhibit_reference:
        feedback.append("The answer does not identify a supporting exhibit or record.")
        checklist.append("Name the exhibit, annexure, page, or record used for support.")
    if unsupported_count:
        feedback.append("The answer adds a fact not visible in the source quote.")
        checklist.append("Remove new facts unless a linked record supports them.")
    if contradiction_count:
        feedback.append("The answer conflicts with the linked source quote.")
        checklist.append("Reconcile the answer with the source quote before practice.")
    if overlong:
        feedback.append("The answer is longer than the coach threshold for a focused reply.")
        checklist.append("Condense the answer before adding background detail.")
    if not checklist:
        checklist.append("Keep the answer tied to the source quote and cited record.")

    return HearingCoachFeedbackItem(
        response_id=response.id,
        question_id=response.question_id,
        mock_hearing_session_id=response.session_id,
        source_affidavit_question_id=response.source_affidavit_question_id,
        source_affidavit_statement_id=question.source_affidavit_statement_id,
        source_attachment_id=question.source_attachment_id,
        source_chunk_id=question.source_chunk_id,
        source_chunk_index=question.source_chunk_index,
        page_reference=question.page_reference,
        question_text=_snippet(question.question_text, 500),
        transcript_excerpt=_snippet(response.response_text, 500),
        source_quote=_snippet(response.source_quote or question.source_quote, 800),
        answered_question=response.answered_question,
        source_reference_used=source_reference_used,
        unsupported_assertion_count=unsupported_count,
        contradiction_count=contradiction_count,
        clarity_score=clarity,
        completeness_score=completeness,
        evasiveness_marker=evasiveness_marker,
        overlong_response_marker=overlong,
        missing_exhibit_reference=missing_exhibit_reference,
        review_required=response.review_required
        or unsupported_count > 0
        or contradiction_count > 0
        or missing_exhibit_reference
        or evasiveness_marker,
        feedback=feedback,
        improvement_checklist=checklist,
    )


def _clarity_score(
    *,
    answered: bool,
    word_count: int,
    unsupported: int,
    contradiction: int,
    overlong: bool,
    evasiveness_marker: bool,
) -> int:
    score = 60
    if answered:
        score += 15
    if 12 <= word_count <= 80:
        score += 10
    if word_count < 8:
        score -= 15
    if overlong:
        score -= 15
    if evasiveness_marker:
        score -= 10
    score -= unsupported * 15
    score -= contradiction * 20
    return _clamp_score(score)


def _completeness_score(
    *,
    completeness_label: str,
    source_reference_used: bool,
    missing_exhibit_reference: bool,
    unsupported: int,
    contradiction: int,
) -> int:
    score = {"high": 85, "medium": 65, "low": 35}.get(completeness_label, 35)
    if source_reference_used:
        score += 10
    if missing_exhibit_reference:
        score -= 15
    score -= unsupported * 10
    score -= contradiction * 15
    return _clamp_score(score)


def _clamp_score(value: int) -> int:
    return max(0, min(100, value))


def _snippet(value: str | None, limit: int) -> str:
    cleaned = _SPACE_RE.sub(" ", _CONTROL_RE.sub(" ", value or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "..."


__all__ = [
    "DISCLAIMER",
    "generate_hearing_coach_report",
    "get_hearing_coach_status",
]
