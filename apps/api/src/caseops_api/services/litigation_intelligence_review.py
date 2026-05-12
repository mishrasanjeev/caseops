"""LI-S6 matter-level review queue for source-backed litigation intelligence."""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AffidavitQuestion,
    AffidavitStatement,
    AuditResult,
    Matter,
    MatterAttachment,
    MatterCourtOrder,
    MatterProceedingSignal,
    MockHearingResponse,
    MockHearingSession,
    PredictiveSignalEvidence,
    PredictiveSignalItem,
    PredictiveSignalRun,
)
from caseops_api.schemas.litigation_intelligence import (
    LitigationIntelligenceReviewItem,
    LitigationIntelligenceReviewResponse,
    LitigationIntelligenceReviewSource,
    LitigationIntelligenceReviewSummary,
    LitigationReviewPriorityLiteral,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access

DISCLAIMER = (
    "Litigation intelligence review is source-backed decision support, not legal "
    "advice. Verify source documents and use lawyer review before relying on any "
    "extracted signal, question, feedback, or predictive limitation."
)

REVIEW_REQUIRED_STATUSES = {"review_required", "auto_promoted", "insufficient_evidence"}


def build_litigation_intelligence_review(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> LitigationIntelligenceReviewResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    items: list[LitigationIntelligenceReviewItem] = []
    items.extend(_proceeding_items(session, matter))
    items.extend(_affidavit_statement_items(session, matter))
    items.extend(_affidavit_question_items(session, matter))
    items.extend(_mock_hearing_items(session, matter))
    items.extend(_predictive_items(session, matter))
    items.sort(key=_sort_key)

    record_from_context(
        session,
        context,
        action="litigation_intelligence_review.viewed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        result=AuditResult.SUCCESS,
        metadata={
            "total_items": len(items),
            "review_required_count": sum(
                1 for item in items if item.status in REVIEW_REQUIRED_STATUSES
            ),
            "item_types": sorted({item.item_type for item in items}),
        },
    )
    session.commit()

    return LitigationIntelligenceReviewResponse(
        matter_id=matter.id,
        generated_at=datetime.now(UTC),
        disclaimer=DISCLAIMER,
        summary=_summary(items),
        items=items,
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


def _proceeding_items(
    session: Session,
    matter: Matter,
) -> list[LitigationIntelligenceReviewItem]:
    signals = list(
        session.scalars(
            select(MatterProceedingSignal)
            .where(
                MatterProceedingSignal.company_id == matter.company_id,
                MatterProceedingSignal.matter_id == matter.id,
                MatterProceedingSignal.review_status.in_(REVIEW_REQUIRED_STATUSES),
            )
            .order_by(MatterProceedingSignal.created_at.desc())
            .limit(50)
        )
    )
    order_ids = {signal.court_order_id for signal in signals}
    orders = _orders_by_id(session, order_ids)
    out: list[LitigationIntelligenceReviewItem] = []
    for signal in signals:
        order = orders.get(signal.court_order_id)
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"proceeding:{signal.id}",
                item_type="proceeding_signal",
                title=_title_from_key(signal.signal_type),
                description=signal.action_required or signal.signal_text,
                status=signal.review_status,
                priority=_priority(signal.confidence_label, high_when_review=True),
                confidence_label=signal.confidence_label,
                limitation_note=(
                    "Proceeding signal was extracted from raw order text and remains "
                    "pending lawyer review."
                ),
                review_reason=_proceeding_review_reason(signal),
                source=LitigationIntelligenceReviewSource(
                    source_type="matter_court_order",
                    source_id=signal.court_order_id,
                    label=order.title if order else "Court order",
                    reference=order.source_reference if order else None,
                    snippet=signal.source_snippet,
                ),
                due_on=signal.due_on or signal.hearing_on,
                created_at=signal.created_at,
                updated_at=signal.updated_at,
            )
        )
    return out


def _affidavit_statement_items(
    session: Session,
    matter: Matter,
) -> list[LitigationIntelligenceReviewItem]:
    statements = list(
        session.scalars(
            select(AffidavitStatement)
            .where(
                AffidavitStatement.company_id == matter.company_id,
                AffidavitStatement.matter_id == matter.id,
                AffidavitStatement.review_status.in_(REVIEW_REQUIRED_STATUSES),
            )
            .order_by(AffidavitStatement.created_at.desc())
            .limit(50)
        )
    )
    attachments = _attachments_by_id(session, {row.attachment_id for row in statements})
    out: list[LitigationIntelligenceReviewItem] = []
    for statement in statements:
        attachment = attachments.get(statement.attachment_id)
        priority: LitigationReviewPriorityLiteral = (
            "high"
            if statement.statement_type in {"evidence_gap", "contradiction"}
            else _priority(statement.confidence_label)
        )
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"affidavit-statement:{statement.id}",
                item_type="affidavit_statement",
                title=_title_from_key(statement.statement_type),
                description=statement.statement_text,
                status=statement.review_status,
                priority=priority,
                confidence_label=statement.confidence_label,
                limitation_note=(
                    "Affidavit statement is extracted from attachment text or chunks "
                    "and must be checked against the source quote."
                ),
                review_reason=_affidavit_statement_reason(statement),
                source=LitigationIntelligenceReviewSource(
                    source_type="matter_document",
                    source_id=statement.attachment_id,
                    label=attachment.original_filename if attachment else "Matter document",
                    reference=f"chunk {statement.source_chunk_index}"
                    if statement.source_chunk_index is not None
                    else None,
                    snippet=statement.source_quote,
                    page_reference=statement.page_reference,
                ),
                created_at=statement.created_at,
                updated_at=statement.updated_at,
            )
        )
    return out


def _affidavit_question_items(
    session: Session,
    matter: Matter,
) -> list[LitigationIntelligenceReviewItem]:
    questions = list(
        session.scalars(
            select(AffidavitQuestion)
            .where(
                AffidavitQuestion.company_id == matter.company_id,
                AffidavitQuestion.matter_id == matter.id,
                AffidavitQuestion.review_required.is_(True),
                AffidavitQuestion.review_status.in_(REVIEW_REQUIRED_STATUSES),
            )
            .order_by(AffidavitQuestion.created_at.desc())
            .limit(50)
        )
    )
    attachments = _attachments_by_id(session, {row.attachment_id for row in questions})
    out: list[LitigationIntelligenceReviewItem] = []
    for question in questions:
        attachment = attachments.get(question.attachment_id)
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"affidavit-question:{question.id}",
                item_type="affidavit_question",
                title=_title_from_key(question.category),
                description=question.question_text,
                status=question.review_status,
                priority=_priority(question.confidence_label, high_when_review=True),
                confidence_label=question.confidence_label,
                limitation_note=(
                    "Cross-examination question is source-bound and remains review "
                    "required until a lawyer reviews it."
                ),
                review_reason=question.reason,
                source=LitigationIntelligenceReviewSource(
                    source_type="matter_document",
                    source_id=question.attachment_id,
                    label=attachment.original_filename if attachment else "Matter document",
                    reference=f"chunk {question.source_chunk_index}"
                    if question.source_chunk_index is not None
                    else None,
                    snippet=question.source_quote,
                    page_reference=question.page_reference,
                ),
                created_at=question.created_at,
                updated_at=question.updated_at,
            )
        )
    return out


def _mock_hearing_items(
    session: Session,
    matter: Matter,
) -> list[LitigationIntelligenceReviewItem]:
    sessions = list(
        session.scalars(
            select(MockHearingSession)
            .where(
                MockHearingSession.company_id == matter.company_id,
                MockHearingSession.matter_id == matter.id,
                MockHearingSession.review_status.in_(REVIEW_REQUIRED_STATUSES),
            )
            .order_by(MockHearingSession.started_at.desc())
            .limit(25)
        )
    )
    responses = list(
        session.scalars(
            select(MockHearingResponse)
            .where(
                MockHearingResponse.company_id == matter.company_id,
                MockHearingResponse.matter_id == matter.id,
                MockHearingResponse.review_required.is_(True),
                MockHearingResponse.review_status.in_(REVIEW_REQUIRED_STATUSES),
            )
            .order_by(MockHearingResponse.created_at.desc())
            .limit(50)
        )
    )
    out: list[LitigationIntelligenceReviewItem] = []
    for row in sessions:
        if row.review_required_count <= 0 and row.status == "completed":
            continue
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"mock-hearing-session:{row.id}",
                item_type="mock_hearing_session",
                title="Mock hearing review",
                description=(
                    f"{row.answered_questions}/{row.total_questions} typed responses "
                    f"recorded; {row.review_required_count} feedback item"
                    f"{'' if row.review_required_count == 1 else 's'} need review."
                ),
                status=row.review_status,
                priority="medium" if row.review_required_count else "low",
                evidence_quality="source_backed_affidavit_questions",
                sample_size=row.total_questions,
                limitation_note=(
                    "Mock-hearing feedback is deterministic and source-bound; it is "
                    "not legal advice or credibility scoring."
                ),
                review_reason="Review source-linked preparation feedback before use.",
                source=LitigationIntelligenceReviewSource(
                    source_type="mock_hearing_session",
                    source_id=row.id,
                    label="Mock hearing session",
                    reference=row.mode,
                    snippet=row.disclaimer,
                ),
                created_at=row.started_at,
                updated_at=row.updated_at,
            )
        )
    for row in responses:
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"mock-hearing-response:{row.id}",
                item_type="mock_hearing_response",
                title="Mock hearing response feedback",
                description=row.feedback_text,
                status=row.review_status,
                priority=_mock_response_priority(row),
                confidence_label=row.confidence_label,
                evidence_quality="source_backed_affidavit_question",
                limitation_note=(
                    "Feedback checks observable typed-response markers against the "
                    "source quote only."
                ),
                review_reason=_mock_response_reason(row),
                source=LitigationIntelligenceReviewSource(
                    source_type="mock_hearing_session",
                    source_id=row.session_id,
                    label="Mock hearing session",
                    reference=row.source_affidavit_question_id,
                    snippet=row.source_quote,
                ),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return out


def _predictive_items(
    session: Session,
    matter: Matter,
) -> list[LitigationIntelligenceReviewItem]:
    run = session.scalar(
        select(PredictiveSignalRun)
        .where(
            PredictiveSignalRun.company_id == matter.company_id,
            PredictiveSignalRun.matter_id == matter.id,
        )
        .order_by(PredictiveSignalRun.created_at.desc())
        .limit(1)
    )
    if run is None:
        return []

    evidence_by_item = _predictive_evidence_by_item(session, run)
    items = list(
        session.scalars(
            select(PredictiveSignalItem)
            .where(
                PredictiveSignalItem.run_id == run.id,
                PredictiveSignalItem.company_id == matter.company_id,
                PredictiveSignalItem.matter_id == matter.id,
            )
            .order_by(PredictiveSignalItem.created_at.asc())
        )
    )
    out = [
        LitigationIntelligenceReviewItem(
            id=f"bench-context:{run.id}",
            item_type="bench_context",
            title="Bench context limitations",
            description=(
                "Latest predictive run evidence quality is "
                f"{_title_from_key(run.evidence_quality)}."
            ),
            status=_bench_context_status(run),
            priority="medium" if run.evidence_quality != "strong" else "low",
            evidence_quality=run.evidence_quality,
            sample_size=run.sample_size,
            limitation_note=run.limitation_note
            or "Bench context remains limited to indexed source samples.",
            review_reason=(
                "Review sample size, confidence band, and cited source coverage before use."
            ),
            source=_predictive_run_source(run),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )
    ]
    for item in items:
        if item.status == "supported" and item.confidence_label not in {"low", "insufficient"}:
            continue
        out.append(
            LitigationIntelligenceReviewItem(
                id=f"predictive-signal:{item.id}",
                item_type="predictive_signal",
                title=item.label,
                description=item.estimate_label or item.status,
                status=item.status if item.status != "supported" else "limited_context",
                priority=_predictive_priority(item),
                confidence_label=item.confidence_label,
                evidence_quality=run.evidence_quality,
                sample_size=item.sample_size,
                limitation_note=item.limitation_note,
                review_reason=(
                    "Predictive item needs lawyer review because the sample is weak, "
                    "low-confidence, or insufficient."
                ),
                source=_predictive_item_source(item, run, evidence_by_item.get(item.id, [])),
                created_at=item.created_at,
                updated_at=None,
            )
        )
    return out


def _orders_by_id(
    session: Session,
    order_ids: Iterable[str],
) -> dict[str, MatterCourtOrder]:
    ids = list(order_ids)
    if not ids:
        return {}
    return {
        row.id: row
        for row in session.scalars(
            select(MatterCourtOrder).where(MatterCourtOrder.id.in_(ids))
        )
    }


def _attachments_by_id(
    session: Session,
    attachment_ids: Iterable[str],
) -> dict[str, MatterAttachment]:
    ids = list(attachment_ids)
    if not ids:
        return {}
    return {
        row.id: row
        for row in session.scalars(select(MatterAttachment).where(MatterAttachment.id.in_(ids)))
    }


def _predictive_evidence_by_item(
    session: Session,
    run: PredictiveSignalRun,
) -> dict[str, list[PredictiveSignalEvidence]]:
    evidence: dict[str, list[PredictiveSignalEvidence]] = {}
    rows = session.scalars(
        select(PredictiveSignalEvidence)
        .where(
            PredictiveSignalEvidence.run_id == run.id,
            PredictiveSignalEvidence.company_id == run.company_id,
            PredictiveSignalEvidence.matter_id == run.matter_id,
        )
        .order_by(PredictiveSignalEvidence.weight.desc(), PredictiveSignalEvidence.created_at.asc())
    )
    for row in rows:
        evidence.setdefault(row.item_id, []).append(row)
    return evidence


def _predictive_item_source(
    item: PredictiveSignalItem,
    run: PredictiveSignalRun,
    evidence: list[PredictiveSignalEvidence],
) -> LitigationIntelligenceReviewSource:
    for row in evidence:
        if row.source_type == "unavailable":
            continue
        return LitigationIntelligenceReviewSource(
            source_type=row.source_type,  # type: ignore[arg-type]
            source_id=row.source_id,
            label=row.title or row.source_reference or row.source_id,
            reference=row.source_reference,
            snippet=row.excerpt,
        )
    return _predictive_run_source(run, snippet=item.limitation_note)


def _predictive_run_source(
    run: PredictiveSignalRun,
    *,
    snippet: str | None = None,
) -> LitigationIntelligenceReviewSource:
    return LitigationIntelligenceReviewSource(
        source_type="predictive_signal_run",
        source_id=run.id,
        label="Predictive intelligence run",
        reference=run.evidence_quality,
        snippet=snippet or run.limitation_note,
    )


def _summary(
    items: list[LitigationIntelligenceReviewItem],
) -> LitigationIntelligenceReviewSummary:
    by_type = Counter(item.item_type for item in items)
    by_status = Counter(item.status for item in items)
    return LitigationIntelligenceReviewSummary(
        total_items=len(items),
        review_required_count=sum(1 for item in items if item.status in REVIEW_REQUIRED_STATUSES),
        source_linked_count=sum(1 for item in items if item.source.source_id),
        by_type=dict(by_type),
        by_status=dict(by_status),
    )


def _sort_key(item: LitigationIntelligenceReviewItem) -> tuple[int, float]:
    priority_rank = {"high": 0, "medium": 1, "low": 2}
    created = item.updated_at or item.created_at
    return priority_rank[item.priority], -created.timestamp()


def _priority(
    confidence_label: str | None,
    *,
    high_when_review: bool = False,
) -> LitigationReviewPriorityLiteral:
    if confidence_label == "high" and high_when_review:
        return "high"
    if confidence_label in {"low", "insufficient"}:
        return "high"
    if confidence_label == "medium":
        return "medium"
    return "low"


def _mock_response_priority(row: MockHearingResponse) -> LitigationReviewPriorityLiteral:
    if row.contradiction_with_source or row.unsupported_assertion_added:
        return "high"
    if row.missing_document_reference or row.confidence_label != "high":
        return "medium"
    return "low"


def _predictive_priority(item: PredictiveSignalItem) -> LitigationReviewPriorityLiteral:
    if item.status == "insufficient_evidence" or item.confidence_label == "insufficient":
        return "high"
    if item.confidence_label == "low":
        return "medium"
    return "low"


def _bench_context_status(run: PredictiveSignalRun) -> str:
    if run.sample_size <= 0 or run.evidence_quality == "insufficient":
        return "insufficient_evidence"
    if run.evidence_quality in {"thin", "limited", "partial"}:
        return "limited_context"
    return "supported"


def _proceeding_review_reason(signal: MatterProceedingSignal) -> str:
    if signal.generated_task_id or signal.generated_deadline_id:
        return "Generated work exists and should be confirmed against the source order."
    if signal.due_on or signal.hearing_on:
        return "Date-bearing proceeding signal needs source confirmation."
    return "Review extracted proceeding signal before relying on it."


def _affidavit_statement_reason(statement: AffidavitStatement) -> str:
    if statement.statement_type == "evidence_gap":
        return "Confirm whether the asserted fact has supporting matter evidence."
    if statement.statement_type == "contradiction":
        return "Confirm the possible inconsistency against the linked source material."
    return "Review extracted affidavit statement against the source quote."


def _mock_response_reason(row: MockHearingResponse) -> str:
    reasons: list[str] = []
    if row.unsupported_assertion_added:
        reasons.append("unsupported assertion added")
    if row.missing_document_reference:
        reasons.append("missing document reference")
    if row.contradiction_with_source:
        reasons.append("possible source contradiction")
    if not row.answered_question:
        reasons.append("question not directly answered")
    return f"Review typed response feedback: {', '.join(reasons)}." if reasons else (
        "Review low-confidence typed response feedback."
    )


def _title_from_key(value: str) -> str:
    return value.replace("_", " ").strip().title()


__all__ = ["build_litigation_intelligence_review"]
