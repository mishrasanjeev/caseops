"""Text-first mock hearing simulator.

LI-S3 deliberately uses deterministic, source-bound feedback. It snapshots
LI-S2 affidavit questions into a matter-private session and evaluates typed
responses against the source quote and question rationale only.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    AffidavitIntelligenceRun,
    AffidavitIntelligenceRunStatus,
    AffidavitQuestion,
    Matter,
    MockHearingQuestion,
    MockHearingQuestionStatus,
    MockHearingResponse,
    MockHearingReviewStatus,
    MockHearingSession,
    MockHearingSessionStatus,
)
from caseops_api.schemas.mock_hearing import (
    MockHearingListResponse,
    MockHearingQuestionRecord,
    MockHearingResponseCreateRequest,
    MockHearingResponseRecord,
    MockHearingScorecard,
    MockHearingSessionRecord,
    MockHearingStartRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

DISCLAIMER = (
    "Mock hearings are source-backed hearing-preparation decision support, "
    "not legal advice. Feedback is limited to observable response content and "
    "must be reviewed by counsel."
)
MAX_SOURCE_QUESTIONS = 20

_DATE_RE = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{4})\b",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(
    r"\b(?:Rs\.?|INR)\s*[\d,]+(?:\.\d+)?\b|"
    r"\b\d{1,3}(?:,\d{2,3})+(?:\.\d+)?\b|"
    r"\b[\d,]+(?:\.\d+)?\s*(?:lakh|lakhs|crore|crores)\b",
    re.IGNORECASE,
)
_NEGATED_PAYMENT_RE = re.compile(
    r"\b(?:not|never|no|did\s+not)\b.{0,24}\b(?:paid|payment|received|receipt)\b",
    re.IGNORECASE,
)
_PAYMENT_RE = re.compile(r"\b(?:paid|payment|received|receipt)\b", re.IGNORECASE)
_DOCUMENT_RE = re.compile(
    r"\b(?:annexure|exhibit|invoice|receipt|agreement|ledger|bank|statement|"
    r"document|record|email|letter|notice|cheque|contract)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]{2,}")
_STOPWORDS = {
    "about",
    "against",
    "also",
    "and",
    "answer",
    "because",
    "been",
    "before",
    "being",
    "between",
    "case",
    "court",
    "document",
    "from",
    "have",
    "into",
    "that",
    "their",
    "there",
    "this",
    "under",
    "which",
    "with",
    "would",
}
_DOCUMENT_CATEGORIES = {
    "document_support",
    "financial_scrutiny",
    "evidence_contradiction",
}


@dataclass(frozen=True)
class _Evaluation:
    answered_question: bool
    consistency_with_affidavit: bool
    unsupported_assertion_added: bool
    missing_document_reference: bool
    contradiction_with_source: bool
    response_completeness: str
    confidence_label: str
    review_required: bool
    feedback_text: str
    evaluation: dict[str, object]


def list_mock_hearings(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> MockHearingListResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    sessions = _load_sessions(session, matter.id)
    record_from_context(
        session,
        context,
        action="mock_hearing.viewed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"session_count": len(sessions)},
    )
    session.commit()
    return _list_response(matter_id=matter.id, sessions=sessions)


def get_mock_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    session_id: str,
) -> MockHearingSessionRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    mock_session = _load_session(session, matter=matter, session_id=session_id)
    record_from_context(
        session,
        context,
        action="mock_hearing.viewed",
        target_type="mock_hearing_session",
        target_id=mock_session.id,
        matter_id=matter.id,
    )
    session.commit()
    return _session_record(mock_session)


def start_mock_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MockHearingStartRequest,
) -> MockHearingSessionRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="start a mock hearing",
    )
    affidavit_run = _latest_affidavit_run(session, matter)
    source_questions = _select_source_questions(affidavit_run, payload)
    if not source_questions:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No source-backed affidavit question bank is available for this matter.",
        )

    mock_session = MockHearingSession(
        company_id=matter.company_id,
        matter_id=matter.id,
        source_affidavit_run_id=affidavit_run.id,
        created_by_membership_id=context.membership.id,
        mode=payload.mode,
        participant_label=_clean_label(payload.participant_label),
        status=MockHearingSessionStatus.ACTIVE,
        review_status=MockHearingReviewStatus.REVIEW_REQUIRED,
        disclaimer=DISCLAIMER,
        total_questions=len(source_questions),
        scorecard_json="{}",
    )
    session.add(mock_session)
    session.flush()

    for idx, question in enumerate(source_questions):
        row = MockHearingQuestion(
            company_id=matter.company_id,
            matter_id=matter.id,
            session_id=mock_session.id,
            source_affidavit_run_id=affidavit_run.id,
            source_affidavit_question_id=question.id,
            source_affidavit_statement_id=question.statement_id,
            source_attachment_id=question.attachment_id,
            source_chunk_id=question.source_chunk_id,
            source_chunk_index=question.source_chunk_index,
            page_reference=question.page_reference,
            turn_index=idx,
            category=question.category,
            question_text=question.question_text,
            reason=question.reason,
            source_quote=question.source_quote,
            difficulty_label=question.confidence_label,
            status=MockHearingQuestionStatus.PENDING,
        )
        session.add(row)
    session.flush()
    _refresh_scorecard(mock_session)
    record_from_context(
        session,
        context,
        action="mock_hearing.created",
        target_type="mock_hearing_session",
        target_id=mock_session.id,
        matter_id=matter.id,
        metadata={
            "source_affidavit_run_id": affidavit_run.id,
            "question_count": len(source_questions),
            "mode": mock_session.mode,
        },
    )
    session.commit()
    return get_mock_hearing(
        session,
        context=context,
        matter_id=matter.id,
        session_id=mock_session.id,
    )


def record_mock_hearing_response(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    session_id: str,
    payload: MockHearingResponseCreateRequest,
) -> MockHearingSessionRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="record a mock hearing response",
    )
    mock_session = _load_session(
        session,
        matter=matter,
        session_id=session_id,
        lock_for_write=True,
    )
    if mock_session.status != MockHearingSessionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Mock hearing session is not active.",
        )
    question = _resolve_question(mock_session, payload.question_id)
    if not question:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending mock hearing question is available.",
        )
    if question.responses:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This mock hearing question already has a response.",
        )

    response_text = _normalize_space(payload.response_text)
    evaluation = _evaluate_response(question=question, response_text=response_text)
    response = MockHearingResponse(
        company_id=matter.company_id,
        matter_id=matter.id,
        session=mock_session,
        question=question,
        source_affidavit_question_id=question.source_affidavit_question_id,
        response_text=response_text,
        response_word_count=len(_words(response_text)),
        elapsed_seconds=payload.elapsed_seconds,
        answered_question=evaluation.answered_question,
        consistency_with_affidavit=evaluation.consistency_with_affidavit,
        unsupported_assertion_added=evaluation.unsupported_assertion_added,
        missing_document_reference=evaluation.missing_document_reference,
        contradiction_with_source=evaluation.contradiction_with_source,
        response_completeness=evaluation.response_completeness,
        confidence_label=evaluation.confidence_label,
        feedback_text=evaluation.feedback_text,
        evaluation_json=json.dumps(evaluation.evaluation, sort_keys=True),
        source_quote=question.source_quote,
        review_required=evaluation.review_required,
        review_status=MockHearingReviewStatus.REVIEW_REQUIRED,
    )
    question.status = MockHearingQuestionStatus.ANSWERED
    session.add_all([question, response])
    session.flush()
    _refresh_scorecard(mock_session)
    record_from_context(
        session,
        context,
        action="mock_hearing.response_recorded",
        target_type="mock_hearing_response",
        target_id=response.id,
        matter_id=matter.id,
        metadata={
            "session_id": mock_session.id,
            "question_id": question.id,
            "source_affidavit_question_id": question.source_affidavit_question_id,
            "review_required": response.review_required,
            "confidence_label": response.confidence_label,
        },
    )
    session.commit()
    return get_mock_hearing(
        session,
        context=context,
        matter_id=matter.id,
        session_id=mock_session.id,
    )


def complete_mock_hearing(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    session_id: str,
) -> MockHearingSessionRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="complete a mock hearing",
    )
    mock_session = _load_session(
        session,
        matter=matter,
        session_id=session_id,
        lock_for_write=True,
    )
    if mock_session.status != MockHearingSessionStatus.COMPLETED:
        mock_session.status = MockHearingSessionStatus.COMPLETED
        mock_session.completed_at = datetime.now(UTC)
        _refresh_scorecard(mock_session)
        session.add(mock_session)
        record_from_context(
            session,
            context,
            action="mock_hearing.completed",
            target_type="mock_hearing_session",
            target_id=mock_session.id,
            matter_id=matter.id,
            metadata=json.loads(mock_session.scorecard_json),
        )
        session.commit()
    return get_mock_hearing(
        session,
        context=context,
        matter_id=matter.id,
        session_id=mock_session.id,
    )


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


def _load_sessions(session: Session, matter_id: str) -> list[MockHearingSession]:
    return list(
        session.scalars(
            select(MockHearingSession)
            .options(
                selectinload(MockHearingSession.questions).selectinload(
                    MockHearingQuestion.responses
                )
            )
            .where(MockHearingSession.matter_id == matter_id)
            .order_by(
                MockHearingSession.started_at.desc(),
                MockHearingSession.id.desc(),
            )
        )
    )


def _load_session(
    session: Session,
    *,
    matter: Matter,
    session_id: str,
    lock_for_write: bool = False,
) -> MockHearingSession:
    statement = (
        select(MockHearingSession)
        .options(
            selectinload(MockHearingSession.questions).selectinload(
                MockHearingQuestion.responses
            )
        )
        .where(
            MockHearingSession.id == session_id,
            MockHearingSession.matter_id == matter.id,
            MockHearingSession.company_id == matter.company_id,
        )
    )
    if lock_for_write:
        statement = statement.with_for_update(of=MockHearingSession)
    mock_session = session.scalar(
        statement.execution_options(populate_existing=lock_for_write)
    )
    if mock_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mock hearing session not found.",
        )
    return mock_session


def _latest_affidavit_run(session: Session, matter: Matter) -> AffidavitIntelligenceRun:
    run = session.scalar(
        select(AffidavitIntelligenceRun)
        .options(selectinload(AffidavitIntelligenceRun.questions))
        .where(
            AffidavitIntelligenceRun.company_id == matter.company_id,
            AffidavitIntelligenceRun.matter_id == matter.id,
            AffidavitIntelligenceRun.status == AffidavitIntelligenceRunStatus.COMPLETED,
        )
        .order_by(
            AffidavitIntelligenceRun.created_at.desc(),
            AffidavitIntelligenceRun.id.desc(),
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No completed affidavit intelligence run is available for this matter.",
        )
    return run


def _select_source_questions(
    run: AffidavitIntelligenceRun,
    payload: MockHearingStartRequest,
) -> list[AffidavitQuestion]:
    categories = set(payload.categories or [])
    questions = [
        question
        for question in sorted(run.questions, key=lambda row: (row.created_at, row.id))
        if question.source_quote.strip()
        and question.question_text.strip()
        and (not categories or question.category in categories)
    ]
    return questions[: min(payload.max_questions, MAX_SOURCE_QUESTIONS)]


def _resolve_question(
    mock_session: MockHearingSession,
    question_id: str | None,
) -> MockHearingQuestion | None:
    ordered = sorted(mock_session.questions, key=lambda row: (row.turn_index, row.id))
    if question_id:
        return next((question for question in ordered if question.id == question_id), None)
    return next(
        (
            question
            for question in ordered
            if question.status == MockHearingQuestionStatus.PENDING
        ),
        None,
    )


def _evaluate_response(
    *,
    question: MockHearingQuestion,
    response_text: str,
) -> _Evaluation:
    words = _words(response_text)
    source_context = " ".join([question.question_text, question.reason, question.source_quote])
    answered_question = len(words) >= 4
    contradiction = _contradicts_source(source_context, response_text)
    unsupported = _has_unsupported_assertion(source_context, response_text)
    missing_document_reference = (
        question.category in _DOCUMENT_CATEGORIES and not _DOCUMENT_RE.search(response_text)
    )
    consistency = not contradiction
    flag_count = sum([unsupported, missing_document_reference, contradiction])

    if not answered_question or flag_count >= 2:
        completeness = "low"
    elif flag_count == 1 or len(words) < 16:
        completeness = "medium"
    else:
        completeness = "high"

    confidence = completeness
    review_required = confidence != "high" or flag_count > 0
    feedback_parts: list[str] = []
    if answered_question:
        feedback_parts.append("Response addresses the prompt at a basic level.")
    else:
        feedback_parts.append("Response is too short to assess against the prompt.")
    if missing_document_reference:
        feedback_parts.append("Response should identify the supporting document or record.")
    if unsupported:
        feedback_parts.append("Response adds facts not visible in the source quote.")
    if contradiction:
        feedback_parts.append("Response may conflict with the source affidavit statement.")
    if not feedback_parts:
        feedback_parts.append("Response stays within the available source context.")

    evaluation = {
        "answered_question": answered_question,
        "consistency_with_affidavit": consistency,
        "unsupported_assertion_added": unsupported,
        "missing_document_reference": missing_document_reference,
        "contradiction_with_source": contradiction,
        "response_completeness": completeness,
        "source_affidavit_question_id": question.source_affidavit_question_id,
        "source_quote": question.source_quote,
    }
    return _Evaluation(
        answered_question=answered_question,
        consistency_with_affidavit=consistency,
        unsupported_assertion_added=unsupported,
        missing_document_reference=missing_document_reference,
        contradiction_with_source=contradiction,
        response_completeness=completeness,
        confidence_label=confidence,
        review_required=review_required,
        feedback_text=" ".join(feedback_parts),
        evaluation=evaluation,
    )


def _contradicts_source(source_context: str, response_text: str) -> bool:
    source = source_context.lower()
    response = response_text.lower()
    source_negates = bool(_NEGATED_PAYMENT_RE.search(source))
    response_negates = bool(_NEGATED_PAYMENT_RE.search(response))
    source_payment = bool(_PAYMENT_RE.search(source))
    response_payment = bool(_PAYMENT_RE.search(response))
    if source_payment and not source_negates and response_negates:
        return True
    if source_negates and response_payment and not response_negates:
        return True
    return False


def _has_unsupported_assertion(source_context: str, response_text: str) -> bool:
    source_tokens = _token_set(source_context)
    response_tokens = _token_set(response_text)
    unsupported_tokens = [
        token for token in response_tokens if token not in source_tokens and token not in _STOPWORDS
    ]
    date_or_money = [
        marker.lower()
        for marker in [*_DATE_RE.findall(response_text), *_MONEY_RE.findall(response_text)]
        if marker and marker.lower() not in source_context.lower()
    ]
    return len(unsupported_tokens) >= 2 or bool(date_or_money)


def _refresh_scorecard(mock_session: MockHearingSession) -> MockHearingScorecard:
    questions = list(mock_session.questions)
    responses = [response for question in questions for response in question.responses]
    elapsed = [
        response.elapsed_seconds
        for response in responses
        if response.elapsed_seconds is not None
    ]
    scorecard = MockHearingScorecard(
        total_questions=len(questions),
        answered_questions=sum(
            1 for question in questions if question.status == MockHearingQuestionStatus.ANSWERED
        ),
        responses_recorded=len(responses),
        answered_question_count=sum(1 for response in responses if response.answered_question),
        unsupported_assertion_count=sum(
            1 for response in responses if response.unsupported_assertion_added
        ),
        missing_document_reference_count=sum(
            1 for response in responses if response.missing_document_reference
        ),
        contradiction_count=sum(1 for response in responses if response.contradiction_with_source),
        review_required_count=sum(1 for response in responses if response.review_required),
        average_response_seconds=round(sum(elapsed) / len(elapsed), 2) if elapsed else None,
    )
    mock_session.total_questions = scorecard.total_questions
    mock_session.answered_questions = scorecard.answered_questions
    mock_session.unsupported_assertion_count = scorecard.unsupported_assertion_count
    mock_session.missing_document_reference_count = scorecard.missing_document_reference_count
    mock_session.contradiction_count = scorecard.contradiction_count
    mock_session.review_required_count = scorecard.review_required_count
    mock_session.average_response_seconds = scorecard.average_response_seconds
    mock_session.scorecard_json = scorecard.model_dump_json()
    return scorecard


def _scorecard(mock_session: MockHearingSession) -> MockHearingScorecard:
    try:
        parsed = json.loads(mock_session.scorecard_json or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if not isinstance(parsed, dict) or not parsed:
        return _refresh_scorecard(mock_session)
    return MockHearingScorecard(**parsed)


def _list_response(
    *,
    matter_id: str,
    sessions: list[MockHearingSession],
) -> MockHearingListResponse:
    records = [_session_record(mock_session) for mock_session in sessions]
    return MockHearingListResponse(
        matter_id=matter_id,
        generated_at=datetime.now(UTC),
        disclaimer=DISCLAIMER,
        sessions=records,
        latest_session=records[0] if records else None,
    )


def _session_record(mock_session: MockHearingSession) -> MockHearingSessionRecord:
    questions = sorted(mock_session.questions, key=lambda row: (row.turn_index, row.id))
    current = next(
        (
            question
            for question in questions
            if question.status == MockHearingQuestionStatus.PENDING
            and mock_session.status == MockHearingSessionStatus.ACTIVE
        ),
        None,
    )
    return MockHearingSessionRecord(
        id=mock_session.id,
        matter_id=mock_session.matter_id,
        source_affidavit_run_id=mock_session.source_affidavit_run_id,
        mode=mock_session.mode,  # type: ignore[arg-type]
        participant_label=mock_session.participant_label,
        status=mock_session.status,  # type: ignore[arg-type]
        review_status=mock_session.review_status,  # type: ignore[arg-type]
        current_question_id=current.id if current else None,
        disclaimer=mock_session.disclaimer,
        scorecard=_scorecard(mock_session),
        created_by_membership_id=mock_session.created_by_membership_id,
        started_at=mock_session.started_at,
        completed_at=mock_session.completed_at,
        updated_at=mock_session.updated_at,
        questions=[_question_record(question) for question in questions],
    )


def _question_record(question: MockHearingQuestion) -> MockHearingQuestionRecord:
    responses = sorted(question.responses, key=lambda row: (row.created_at, row.id))
    return MockHearingQuestionRecord(
        id=question.id,
        session_id=question.session_id,
        matter_id=question.matter_id,
        source_affidavit_run_id=question.source_affidavit_run_id,
        source_affidavit_question_id=question.source_affidavit_question_id,
        source_affidavit_statement_id=question.source_affidavit_statement_id,
        source_attachment_id=question.source_attachment_id,
        turn_index=question.turn_index,
        category=question.category,  # type: ignore[arg-type]
        question_text=question.question_text,
        reason=question.reason,
        source_quote=question.source_quote,
        source_chunk_id=question.source_chunk_id,
        source_chunk_index=question.source_chunk_index,
        page_reference=question.page_reference,
        difficulty_label=question.difficulty_label,  # type: ignore[arg-type]
        status=question.status,  # type: ignore[arg-type]
        responses=[_response_record(response, question=question) for response in responses],
        created_at=question.created_at,
        updated_at=question.updated_at,
    )


def _response_record(
    response: MockHearingResponse,
    *,
    question: MockHearingQuestion,
) -> MockHearingResponseRecord:
    return MockHearingResponseRecord(
        id=response.id,
        session_id=response.session_id,
        question_id=response.question_id,
        matter_id=response.matter_id,
        source_affidavit_question_id=response.source_affidavit_question_id,
        source_affidavit_statement_id=question.source_affidavit_statement_id,
        source_attachment_id=question.source_attachment_id,
        source_chunk_id=question.source_chunk_id,
        source_chunk_index=question.source_chunk_index,
        page_reference=question.page_reference,
        response_text=response.response_text,
        response_word_count=response.response_word_count,
        elapsed_seconds=response.elapsed_seconds,
        answered_question=response.answered_question,
        consistency_with_affidavit=response.consistency_with_affidavit,
        unsupported_assertion_added=response.unsupported_assertion_added,
        missing_document_reference=response.missing_document_reference,
        contradiction_with_source=response.contradiction_with_source,
        response_completeness=response.response_completeness,  # type: ignore[arg-type]
        confidence_label=response.confidence_label,  # type: ignore[arg-type]
        feedback_text=response.feedback_text,
        source_quote=response.source_quote,
        review_required=response.review_required,
        review_status=response.review_status,  # type: ignore[arg-type]
        created_at=response.created_at,
        updated_at=response.updated_at,
    )


def _token_set(value: str) -> set[str]:
    return {
        token.lower()
        for token in _WORD_RE.findall(value)
        if len(token) >= 5 and token.lower() not in _STOPWORDS
    }


def _words(value: str) -> list[str]:
    return _WORD_RE.findall(value)


def _normalize_space(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_label(value: str | None) -> str | None:
    cleaned = _normalize_space(value)
    return cleaned[:120] if cleaned else None


__all__ = [
    "DISCLAIMER",
    "complete_mock_hearing",
    "get_mock_hearing",
    "list_mock_hearings",
    "record_mock_hearing_response",
    "start_mock_hearing",
]
