from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditResult,
    Matter,
    MatterNextHearingHistory,
    MatterNextHearingSource,
    MatterNextHearingSuggestion,
    MatterNextHearingSuggestionStatus,
    MatterStatus,
)
from caseops_api.schemas.matters import (
    MatterNextHearingHistoryRecord,
    MatterNextHearingSuggestionRecord,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.session_context import SessionContext


@dataclass(frozen=True, slots=True)
class NextHearingApplyResult:
    applied: bool
    suggestion_id: str | None = None
    reason: str | None = None


def _history_record(row: MatterNextHearingHistory) -> MatterNextHearingHistoryRecord:
    return MatterNextHearingHistoryRecord(
        id=row.id,
        company_id=row.company_id,
        matter_id=row.matter_id,
        old_date=row.old_date,
        new_date=row.new_date,
        source=row.source,
        source_ref_type=row.source_ref_type,
        source_ref_id=row.source_ref_id,
        changed_by_membership_id=row.changed_by_membership_id,
        change_reason=row.change_reason,
        manual_lock=row.manual_lock,
        created_at=row.created_at,
    )


def _suggestion_record(row: MatterNextHearingSuggestion) -> MatterNextHearingSuggestionRecord:
    return MatterNextHearingSuggestionRecord(
        id=row.id,
        company_id=row.company_id,
        matter_id=row.matter_id,
        suggested_date=row.suggested_date,
        existing_date=row.existing_date,
        source=row.source,
        source_ref_type=row.source_ref_type,
        source_ref_id=row.source_ref_id,
        confidence_label=row.confidence_label,
        reason=row.reason,
        status=row.status,
        decided_by_membership_id=row.decided_by_membership_id,
        decided_at=row.decided_at,
        created_at=row.created_at,
    )


def list_next_hearing_history(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> tuple[list[MatterNextHearingHistoryRecord], list[MatterNextHearingSuggestionRecord]]:
    matter = _load_accessible_matter(session, context=context, matter_id=matter_id)
    history = list(
        session.scalars(
            select(MatterNextHearingHistory)
            .where(MatterNextHearingHistory.matter_id == matter.id)
            .order_by(MatterNextHearingHistory.created_at.desc())
            .limit(100)
        )
    )
    suggestions = list(
        session.scalars(
            select(MatterNextHearingSuggestion)
            .where(MatterNextHearingSuggestion.matter_id == matter.id)
            .order_by(
                MatterNextHearingSuggestion.status.asc(),
                MatterNextHearingSuggestion.created_at.desc(),
            )
            .limit(100)
        )
    )
    return [_history_record(row) for row in history], [
        _suggestion_record(row) for row in suggestions
    ]


def _load_accessible_matter(
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def _today() -> date:
    return datetime.now(UTC).date()


def _audit_next_hearing(
    session: Session,
    *,
    context: SessionContext | None,
    company_id: str,
    actor_membership_id: str | None,
    action: str,
    matter_id: str,
    target_type: str,
    target_id: str,
    result: str = AuditResult.SUCCESS,
    metadata: dict[str, object | None],
) -> None:
    if context is not None:
        record_from_context(
            session,
            context,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            matter_id=matter_id,
            metadata=metadata,
        )
        return
    record_audit(
        session,
        company_id=company_id,
        actor_membership_id=actor_membership_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        matter_id=matter_id,
        metadata=metadata,
    )


def _existing_pending_suggestion(
    session: Session,
    *,
    matter: Matter,
    suggested_date: date,
    source: str,
    source_ref_type: str | None,
    source_ref_id: str | None,
) -> MatterNextHearingSuggestion | None:
    return session.scalar(
        select(MatterNextHearingSuggestion).where(
            MatterNextHearingSuggestion.matter_id == matter.id,
            MatterNextHearingSuggestion.suggested_date == suggested_date,
            MatterNextHearingSuggestion.source == source,
            MatterNextHearingSuggestion.source_ref_type == source_ref_type,
            MatterNextHearingSuggestion.source_ref_id == source_ref_id,
            MatterNextHearingSuggestion.status == MatterNextHearingSuggestionStatus.PENDING,
        )
    )


def _create_suggestion(
    session: Session,
    *,
    matter: Matter,
    suggested_date: date,
    source: str,
    source_ref_type: str | None,
    source_ref_id: str | None,
    confidence_label: str,
    reason: str,
    context: SessionContext | None,
    actor_membership_id: str | None,
) -> MatterNextHearingSuggestion:
    suggestion = _existing_pending_suggestion(
        session,
        matter=matter,
        suggested_date=suggested_date,
        source=source,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
    )
    if suggestion is None:
        suggestion = MatterNextHearingSuggestion(
            company_id=matter.company_id,
            matter_id=matter.id,
            suggested_date=suggested_date,
            existing_date=matter.next_hearing_on,
            source=source,
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
            confidence_label=confidence_label,
            reason=reason,
            status=MatterNextHearingSuggestionStatus.PENDING,
        )
        session.add(suggestion)
        session.flush()
    _audit_next_hearing(
        session,
        context=context,
        company_id=matter.company_id,
        actor_membership_id=actor_membership_id,
        action="matter.next_hearing.suggestion.created",
        target_type="matter_next_hearing_suggestion",
        target_id=suggestion.id,
        matter_id=matter.id,
        metadata={
            "suggested_date": suggested_date.isoformat(),
            "existing_date": matter.next_hearing_on.isoformat()
            if matter.next_hearing_on
            else None,
            "source": source,
            "source_ref_type": source_ref_type,
            "source_ref_id": source_ref_id,
            "reason": reason,
        },
    )
    return suggestion


def apply_next_hearing_update(
    session: Session,
    *,
    matter: Matter,
    new_date: date,
    source: str | MatterNextHearingSource,
    actor_membership_id: str | None = None,
    context: SessionContext | None = None,
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    reason: str | None = None,
    confidence_label: str = "high",
    manual_lock: bool = False,
    force: bool = False,
) -> NextHearingApplyResult:
    source_value = str(source.value if isinstance(source, MatterNextHearingSource) else source)
    is_manual = source_value == MatterNextHearingSource.MANUAL
    if matter.next_hearing_on == new_date and matter.next_hearing_manual_lock == manual_lock:
        return NextHearingApplyResult(applied=False, reason="unchanged")

    today = _today()
    cautious_reason: str | None = None
    if not is_manual and not force:
        if matter.next_hearing_manual_lock:
            cautious_reason = "manual_lock_conflict"
        elif (
            matter.next_hearing_on is not None
            and new_date < today
            and matter.status != MatterStatus.DISPOSED
        ):
            cautious_reason = "past_date_requires_review"
        elif (
            matter.next_hearing_on is not None
            and matter.next_hearing_on >= today
            and matter.next_hearing_on != new_date
        ):
            cautious_reason = "future_date_conflict"

    if cautious_reason is not None:
        suggestion = _create_suggestion(
            session,
            matter=matter,
            suggested_date=new_date,
            source=source_value,
            source_ref_type=source_ref_type,
            source_ref_id=source_ref_id,
            confidence_label=confidence_label,
            reason=cautious_reason,
            context=context,
            actor_membership_id=actor_membership_id,
        )
        return NextHearingApplyResult(
            applied=False,
            suggestion_id=suggestion.id,
            reason=cautious_reason,
        )

    old_date = matter.next_hearing_on
    matter.next_hearing_on = new_date
    matter.next_hearing_source = source_value
    matter.next_hearing_source_ref_type = source_ref_type
    matter.next_hearing_source_ref_id = source_ref_id
    matter.next_hearing_updated_by_membership_id = actor_membership_id
    matter.next_hearing_updated_at = datetime.now(UTC)
    matter.next_hearing_manual_lock = (
        manual_lock if is_manual or force else matter.next_hearing_manual_lock
    )
    session.add(matter)
    history = MatterNextHearingHistory(
        company_id=matter.company_id,
        matter_id=matter.id,
        old_date=old_date,
        new_date=new_date,
        source=source_value,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        changed_by_membership_id=actor_membership_id,
        change_reason=reason,
        manual_lock=matter.next_hearing_manual_lock,
    )
    session.add(history)
    session.flush()
    _audit_next_hearing(
        session,
        context=context,
        company_id=matter.company_id,
        actor_membership_id=actor_membership_id,
        action="matter.next_hearing.updated",
        target_type="matter_next_hearing_history",
        target_id=history.id,
        matter_id=matter.id,
        metadata={
            "before": old_date.isoformat() if old_date else None,
            "after": new_date.isoformat(),
            "source": source_value,
            "source_ref_type": source_ref_type,
            "source_ref_id": source_ref_id,
            "manual_lock": matter.next_hearing_manual_lock,
        },
    )
    return NextHearingApplyResult(applied=True, reason="updated")


def clear_next_hearing(
    session: Session,
    *,
    matter: Matter,
    source: str | MatterNextHearingSource,
    actor_membership_id: str | None = None,
    context: SessionContext | None = None,
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
    reason: str | None = None,
    manual_lock: bool = False,
) -> NextHearingApplyResult:
    source_value = str(source.value if isinstance(source, MatterNextHearingSource) else source)
    if matter.next_hearing_on is None:
        return NextHearingApplyResult(applied=False, reason="unchanged")

    old_date = matter.next_hearing_on
    matter.next_hearing_on = None
    matter.next_hearing_source = source_value
    matter.next_hearing_source_ref_type = source_ref_type
    matter.next_hearing_source_ref_id = source_ref_id
    matter.next_hearing_updated_by_membership_id = actor_membership_id
    matter.next_hearing_updated_at = datetime.now(UTC)
    matter.next_hearing_manual_lock = manual_lock
    session.add(matter)
    history = MatterNextHearingHistory(
        company_id=matter.company_id,
        matter_id=matter.id,
        old_date=old_date,
        new_date=None,
        source=source_value,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        changed_by_membership_id=actor_membership_id,
        change_reason=reason,
        manual_lock=matter.next_hearing_manual_lock,
    )
    session.add(history)
    session.flush()
    _audit_next_hearing(
        session,
        context=context,
        company_id=matter.company_id,
        actor_membership_id=actor_membership_id,
        action="matter.next_hearing.cleared",
        target_type="matter_next_hearing_history",
        target_id=history.id,
        matter_id=matter.id,
        metadata={
            "before": old_date.isoformat() if old_date else None,
            "after": None,
            "source": source_value,
            "source_ref_type": source_ref_type,
            "source_ref_id": source_ref_id,
            "manual_lock": matter.next_hearing_manual_lock,
        },
    )
    return NextHearingApplyResult(applied=True, reason="cleared")


def accept_next_hearing_suggestion(
    session: Session,
    *,
    matter: Matter,
    suggestion: MatterNextHearingSuggestion,
    context: SessionContext,
) -> NextHearingApplyResult:
    suggestion.status = MatterNextHearingSuggestionStatus.ACCEPTED
    suggestion.decided_by_membership_id = context.membership.id
    suggestion.decided_at = datetime.now(UTC)
    session.add(suggestion)
    return apply_next_hearing_update(
        session,
        matter=matter,
        new_date=suggestion.suggested_date,
        source=suggestion.source,
        actor_membership_id=context.membership.id,
        context=context,
        source_ref_type=suggestion.source_ref_type,
        source_ref_id=suggestion.source_ref_id,
        reason="accepted_suggestion",
        confidence_label=suggestion.confidence_label,
        force=True,
    )


def reject_next_hearing_suggestion(
    session: Session,
    *,
    matter: Matter,
    suggestion: MatterNextHearingSuggestion,
    context: SessionContext,
) -> None:
    suggestion.status = MatterNextHearingSuggestionStatus.REJECTED
    suggestion.decided_by_membership_id = context.membership.id
    suggestion.decided_at = datetime.now(UTC)
    session.add(suggestion)
    _audit_next_hearing(
        session,
        context=context,
        company_id=matter.company_id,
        actor_membership_id=context.membership.id,
        action="matter.next_hearing.suggestion.rejected",
        target_type="matter_next_hearing_suggestion",
        target_id=suggestion.id,
        matter_id=matter.id,
        metadata={
            "suggested_date": suggestion.suggested_date.isoformat(),
            "source": suggestion.source,
            "source_ref_type": suggestion.source_ref_type,
            "source_ref_id": suggestion.source_ref_id,
        },
    )


def decide_next_hearing_suggestion(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    suggestion_id: str,
    action: str,
) -> None:
    matter = _load_accessible_matter(session, context=context, matter_id=matter_id)
    suggestion = session.scalar(
        select(MatterNextHearingSuggestion).where(
            MatterNextHearingSuggestion.id == suggestion_id,
            MatterNextHearingSuggestion.matter_id == matter.id,
            MatterNextHearingSuggestion.company_id == context.company.id,
        )
    )
    if suggestion is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Next hearing suggestion not found.",
        )
    if suggestion.status != MatterNextHearingSuggestionStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Next hearing suggestion is already decided.",
        )
    if action == "accept":
        accept_next_hearing_suggestion(
            session,
            matter=matter,
            suggestion=suggestion,
            context=context,
        )
    elif action == "reject":
        reject_next_hearing_suggestion(
            session,
            matter=matter,
            suggestion=suggestion,
            context=context,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported next hearing suggestion action.",
        )
    session.commit()
