from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import distinct, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AIFeedbackItem,
    AIFeedbackStatus,
    AssistantActionPreview,
    AssistantCitation,
    AssistantSession,
    AssistantTurn,
    AssistantTurnRole,
    AuditEvent,
    MatterTask,
)
from caseops_api.schemas.ai_feedback import (
    AIFeedbackReviewRequest,
    AIFeedbackSubmission,
    AIOutcomeAnalyticsResponse,
    AIOutcomeMetric,
    ProductGuideFeedbackCreateRequest,
    WorkspaceAssistantFeedbackCreateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.product_guide import load_product_guide_catalog
from caseops_api.services.session_context import SessionContext

_TERMINAL_STATUSES = {AIFeedbackStatus.RESOLVED, AIFeedbackStatus.DISMISSED}
_HIGH_PRIORITY_CATEGORIES = {"unsafe_citation", "missing_permission_explanation"}
_PRODUCT_GUIDE_TARGET_TYPES = {
    "product_guide_command",
    "product_guide_section",
    "product_guide_permission",
    "product_guide_no_match",
}


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _semantic_values(item: AIFeedbackItem) -> tuple[object, ...]:
    return (
        item.surface,
        item.target_type,
        item.target_id,
        item.parent_target_id,
        item.target_version,
        item.feedback_type,
        item.rating,
        item.category,
        item.comment,
    )


def _requested_semantic_values(
    *,
    surface: str,
    target_type: str,
    target_id: str,
    parent_target_id: str | None,
    target_version: str | None,
    payload: AIFeedbackSubmission,
) -> tuple[object, ...]:
    return (
        surface,
        target_type,
        target_id,
        parent_target_id,
        target_version,
        payload.feedback_type,
        payload.rating,
        payload.category,
        payload.comment,
    )


def _find_replay(
    session: Session,
    *,
    context: SessionContext,
    submission_key: str,
) -> AIFeedbackItem | None:
    return session.scalar(
        select(AIFeedbackItem).where(
            AIFeedbackItem.company_id == context.company.id,
            AIFeedbackItem.submitted_by_membership_id == context.membership.id,
            AIFeedbackItem.submission_key == submission_key,
        )
    )


def _create_or_replay(
    session: Session,
    *,
    context: SessionContext,
    payload: AIFeedbackSubmission,
    surface: str,
    target_type: str,
    target_id: str,
    parent_target_id: str | None,
    target_version: str | None,
    target_href: str | None,
) -> AIFeedbackItem:
    expected = _requested_semantic_values(
        surface=surface,
        target_type=target_type,
        target_id=target_id,
        parent_target_id=parent_target_id,
        target_version=target_version,
        payload=payload,
    )
    replay = _find_replay(
        session,
        context=context,
        submission_key=payload.submission_key,
    )
    if replay is not None:
        if _semantic_values(replay) != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Submission key was already used for different feedback.",
            )
        return replay

    now = datetime.now(UTC)
    item = AIFeedbackItem(
        company_id=context.company.id,
        submitted_by_membership_id=context.membership.id,
        submission_key=payload.submission_key,
        surface=surface,
        target_type=target_type,
        target_id=target_id,
        parent_target_id=parent_target_id,
        target_version=target_version,
        target_href=target_href,
        feedback_type=payload.feedback_type,
        rating=payload.rating,
        category=payload.category,
        priority=("high" if payload.category in _HIGH_PRIORITY_CATEGORIES else "normal"),
        comment=payload.comment,
        status=AIFeedbackStatus.OPEN,
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        replay = _find_replay(
            session,
            context=context,
            submission_key=payload.submission_key,
        )
        if replay is None or _semantic_values(replay) != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Submission key was already used for different feedback.",
            ) from exc
        return replay

    record_from_context(
        session,
        context,
        action="ai.feedback.submitted",
        target_type="ai_feedback_item",
        target_id=item.id,
        metadata={
            "surface": surface,
            "feedback_type": payload.feedback_type,
            "category": payload.category,
            "priority": item.priority,
        },
    )
    session.commit()
    session.refresh(item)
    return item


def submit_product_guide_feedback(
    session: Session,
    *,
    context: SessionContext,
    payload: ProductGuideFeedbackCreateRequest,
) -> AIFeedbackItem:
    catalog = load_product_guide_catalog()
    if payload.catalog_fingerprint != catalog["fingerprint"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Product Guide changed. Refresh it before submitting feedback.",
        )
    if payload.target_type not in _PRODUCT_GUIDE_TARGET_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported Product Guide target.")

    target_href: str | None
    if payload.target_type == "product_guide_command":
        command = next(
            (row for row in catalog["commands"] if row["id"] == payload.target_id),
            None,
        )
        if command is None:
            raise HTTPException(status_code=422, detail="Unknown Product Guide command.")
        target_href = command["href"]
    elif payload.target_type == "product_guide_section":
        section = next(
            (row for row in catalog["sections"] if row["id"] == payload.target_id),
            None,
        )
        if section is None:
            raise HTTPException(status_code=422, detail="Unknown Product Guide section.")
        target_href = f"/guide#{section['id']}"
    elif payload.target_type == "product_guide_permission":
        if payload.target_id != "permission":
            raise HTTPException(status_code=422, detail="Unknown Product Guide permission target.")
        target_href = "/guide"
    else:
        if payload.target_id != "no_match":
            raise HTTPException(status_code=422, detail="Unknown Product Guide no-match target.")
        target_href = "/guide"

    return _create_or_replay(
        session,
        context=context,
        payload=payload,
        surface="product_guide",
        target_type=payload.target_type,
        target_id=payload.target_id,
        parent_target_id=None,
        target_version=catalog["fingerprint"],
        target_href=target_href,
    )


def submit_workspace_assistant_feedback(
    session: Session,
    *,
    context: SessionContext,
    payload: WorkspaceAssistantFeedbackCreateRequest,
) -> AIFeedbackItem:
    turn = session.scalar(
        select(AssistantTurn)
        .join(
            AssistantSession,
            (AssistantSession.id == AssistantTurn.session_id)
            & (AssistantSession.company_id == AssistantTurn.company_id),
        )
        .where(
            AssistantTurn.id == payload.turn_id,
            AssistantTurn.session_id == payload.session_id,
            AssistantTurn.company_id == context.company.id,
            AssistantTurn.role == AssistantTurnRole.ASSISTANT,
            AssistantSession.created_by_membership_id == context.membership.id,
        )
    )
    if turn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant turn not found.",
        )
    return _create_or_replay(
        session,
        context=context,
        payload=payload,
        surface="workspace_assistant",
        target_type="assistant_turn",
        target_id=turn.id,
        parent_target_id=turn.session_id,
        target_version=turn.content_sha256,
        target_href=None,
    )


def list_feedback(
    session: Session,
    *,
    context: SessionContext,
    item_status: str | None,
    surface: str | None,
    category: str | None,
    limit: int,
) -> tuple[list[AIFeedbackItem], bool]:
    bounded = max(1, min(limit, 100))
    statement = select(AIFeedbackItem).where(AIFeedbackItem.company_id == context.company.id)
    if item_status:
        statement = statement.where(AIFeedbackItem.status == item_status)
    if surface:
        statement = statement.where(AIFeedbackItem.surface == surface)
    if category:
        statement = statement.where(AIFeedbackItem.category == category)
    rows = list(
        session.scalars(
            statement.order_by(AIFeedbackItem.created_at.desc(), AIFeedbackItem.id.desc()).limit(
                bounded + 1
            )
        )
    )
    return rows[:bounded], len(rows) > bounded


def _metric(
    key: str,
    *,
    numerator: int,
    denominator: int | None,
    denominator_definition: str | None,
) -> AIOutcomeMetric:
    rate = (
        round(numerator / denominator, 4) if denominator is not None and denominator > 0 else None
    )
    return AIOutcomeMetric(
        key=key,  # type: ignore[arg-type]
        numerator=numerator,
        denominator=denominator,
        rate=rate,
        denominator_definition=denominator_definition,
    )


def get_ai_outcome_analytics(
    session: Session,
    *,
    context: SessionContext,
    window_days: int,
) -> AIOutcomeAnalyticsResponse:
    """Return tenant-only product outcomes with no actor or content dimensions."""

    bounded_days = max(1, min(window_days, 90))
    now = datetime.now(UTC)
    started = now - timedelta(days=bounded_days)
    company_id = context.company.id

    assistant_answer_filter = (
        AssistantTurn.company_id == company_id,
        AssistantTurn.role == AssistantTurnRole.ASSISTANT,
        AssistantTurn.status.in_(("completed", "abstained")),
        AssistantTurn.created_at >= started,
        AssistantTurn.created_at <= now,
    )
    answer_total = int(
        session.scalar(select(func.count(AssistantTurn.id)).where(*assistant_answer_filter)) or 0
    )
    abstained = int(
        session.scalar(
            select(func.count(AssistantTurn.id)).where(
                *assistant_answer_filter,
                AssistantTurn.status == "abstained",
            )
        )
        or 0
    )
    preview_filter = (
        AssistantActionPreview.company_id == company_id,
        AssistantActionPreview.created_at >= started,
        AssistantActionPreview.created_at <= now,
    )
    preview_total = int(
        session.scalar(select(func.count(AssistantActionPreview.id)).where(*preview_filter)) or 0
    )
    confirmed = int(
        session.scalar(
            select(func.count(AssistantActionPreview.id)).where(
                *preview_filter,
                AssistantActionPreview.status == "confirmed",
            )
        )
        or 0
    )
    confirmed_tasks = int(
        session.scalar(
            select(func.count(AssistantActionPreview.id)).where(
                *preview_filter,
                AssistantActionPreview.action_type == "task",
                AssistantActionPreview.status == "confirmed",
            )
        )
        or 0
    )
    completed_tasks = int(
        session.scalar(
            select(func.count(AssistantActionPreview.id))
            .join(
                MatterTask,
                (MatterTask.id == AssistantActionPreview.result_id)
                & (MatterTask.company_id == AssistantActionPreview.company_id),
            )
            .where(
                *preview_filter,
                AssistantActionPreview.action_type == "task",
                AssistantActionPreview.status == "confirmed",
                MatterTask.status == "completed",
            )
        )
        or 0
    )
    citation_total = int(
        session.scalar(
            select(func.count(AssistantCitation.id)).where(
                AssistantCitation.company_id == company_id,
                AssistantCitation.created_at >= started,
                AssistantCitation.created_at <= now,
            )
        )
        or 0
    )
    opened_citations = int(
        session.scalar(
            select(func.count(distinct(AuditEvent.target_id)))
            .join(
                AssistantCitation,
                (AssistantCitation.id == AuditEvent.target_id)
                & (AssistantCitation.company_id == AuditEvent.company_id),
            )
            .where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "workspace_assistant.citation_open_succeeded",
                AuditEvent.created_at >= started,
                AuditEvent.created_at <= now,
                AssistantCitation.created_at >= started,
                AssistantCitation.created_at <= now,
            )
        )
        or 0
    )
    permission_denials = int(
        session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.company_id == company_id,
                AuditEvent.action == "workspace_assistant.scope_access_denied",
                AuditEvent.created_at >= started,
                AuditEvent.created_at <= now,
            )
        )
        or 0
    )
    reported_answers = int(
        session.scalar(
            select(func.count(distinct(AIFeedbackItem.target_id)))
            .join(
                AssistantTurn,
                (AssistantTurn.id == AIFeedbackItem.target_id)
                & (AssistantTurn.company_id == AIFeedbackItem.company_id),
            )
            .where(
                AIFeedbackItem.company_id == company_id,
                AIFeedbackItem.surface == "workspace_assistant",
                AIFeedbackItem.target_type == "assistant_turn",
                AIFeedbackItem.feedback_type == "report",
                AIFeedbackItem.created_at >= started,
                AIFeedbackItem.created_at <= now,
                *assistant_answer_filter,
            )
        )
        or 0
    )
    return AIOutcomeAnalyticsResponse(
        window_days=bounded_days,
        window_started_at=started,
        generated_at=now,
        metrics=[
            _metric(
                "task_completion",
                numerator=completed_tasks,
                denominator=confirmed_tasks,
                denominator_definition="confirmed assistant-created tasks",
            ),
            _metric(
                "abstention",
                numerator=abstained,
                denominator=answer_total,
                denominator_definition="completed or abstained assistant answers",
            ),
            _metric(
                "citation_open_success",
                numerator=opened_citations,
                denominator=citation_total,
                denominator_definition="reauthorizable citations created in the window",
            ),
            _metric(
                "permission_denial",
                numerator=permission_denials,
                denominator=None,
                denominator_definition=None,
            ),
            _metric(
                "proposed_action_confirmation",
                numerator=confirmed,
                denominator=preview_total,
                denominator_definition="stored assistant action previews",
            ),
            _metric(
                "reported_answer",
                numerator=reported_answers,
                denominator=answer_total,
                denominator_definition="completed or abstained assistant answers",
            ),
        ],
    )


def review_feedback(
    session: Session,
    *,
    context: SessionContext,
    feedback_id: str,
    payload: AIFeedbackReviewRequest,
) -> AIFeedbackItem:
    item = session.scalar(
        select(AIFeedbackItem)
        .where(
            AIFeedbackItem.id == feedback_id,
            AIFeedbackItem.company_id == context.company.id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found.")
    if _as_utc(item.updated_at) != _as_utc(payload.expected_updated_at):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feedback changed after it was loaded. Refresh and try again.",
        )
    if item.status in _TERMINAL_STATUSES and payload.status != item.status:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Resolved or dismissed feedback cannot be reopened.",
        )

    now = datetime.now(UTC)
    item.status = payload.status
    item.review_notes = payload.review_notes
    item.reviewed_by_membership_id = context.membership.id
    item.reviewed_at = now
    item.updated_at = now
    session.flush()
    record_from_context(
        session,
        context,
        action="ai.feedback.reviewed",
        target_type="ai_feedback_item",
        target_id=item.id,
        metadata={"surface": item.surface, "status": item.status, "category": item.category},
    )
    session.commit()
    session.refresh(item)
    return item


__all__ = [
    "list_feedback",
    "get_ai_outcome_analytics",
    "review_feedback",
    "submit_product_guide_feedback",
    "submit_workspace_assistant_feedback",
]
