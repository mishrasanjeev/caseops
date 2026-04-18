"""Generic matter deadlines (BG-041, Sprint 13 partial).

A thin CRUD surface over ``matter_deadlines``. Hearings, drafts,
intake, contracts, and post-hearing follow-ups all write here so the
dashboard + upcoming-deadlines query is one table lookup.

Intentionally narrow for v1: list, create, complete. No reminder
dispatch (that's BG-042 / BG-040 land) and no generic assignment
workflow. Adding the table now unblocks every downstream domain
that wants to emit a deadline.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access

_VALID_SOURCES = {"hearing", "draft", "contract", "intake", "custom", "followup"}


def _load_matter(session: Session, context: SessionContext, matter_id: str) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    assert_access(session, context=context, matter=matter)
    return matter


def list_deadlines(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    include_done: bool = False,
) -> list[MatterDeadline]:
    _load_matter(session, context, matter_id)
    stmt = (
        select(MatterDeadline)
        .where(MatterDeadline.matter_id == matter_id)
        .order_by(MatterDeadline.due_on.asc(), MatterDeadline.created_at.asc())
    )
    if not include_done:
        stmt = stmt.where(
            MatterDeadline.status.in_(
                [MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED]
            )
        )
    return list(session.scalars(stmt))


def create_deadline(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    source: str,
    kind: str,
    title: str,
    due_on: date,
    notes: str | None = None,
    assignee_membership_id: str | None = None,
    source_ref_type: str | None = None,
    source_ref_id: str | None = None,
) -> MatterDeadline:
    _load_matter(session, context, matter_id)
    source_norm = (source or "").strip().lower()
    if source_norm not in _VALID_SOURCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unknown deadline source {source_norm!r}. "
                f"Allowed: {', '.join(sorted(_VALID_SOURCES))}."
            ),
        )
    title = (title or "").strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deadline title is required.",
        )
    deadline = MatterDeadline(
        matter_id=matter_id,
        source=source_norm,
        kind=(kind or "").strip().lower()[:64] or "other",
        title=title[:255],
        notes=(notes.strip() if notes else None),
        due_on=due_on,
        status=MatterDeadlineStatus.OPEN,
        assignee_membership_id=assignee_membership_id,
        source_ref_type=source_ref_type,
        source_ref_id=source_ref_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(deadline)
    session.flush()
    record_from_context(
        session,
        context,
        action="deadline.created",
        target_type="matter_deadline",
        target_id=deadline.id,
        matter_id=matter_id,
        metadata={
            "source": source_norm,
            "kind": deadline.kind,
            "due_on": due_on.isoformat(),
        },
    )
    session.commit()
    session.refresh(deadline)
    return deadline


TransitionAction = Literal["complete", "cancel", "reopen", "miss"]


def transition_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    action: TransitionAction,
) -> MatterDeadline:
    deadline = session.get(MatterDeadline, deadline_id)
    if deadline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found."
        )
    # Tenant scope via matter.
    _load_matter(session, context, deadline.matter_id)
    now = datetime.now(UTC)
    if action == "complete":
        deadline.status = MatterDeadlineStatus.DONE
        deadline.completed_at = now
    elif action == "cancel":
        deadline.status = MatterDeadlineStatus.CANCELLED
        deadline.completed_at = now
    elif action == "miss":
        deadline.status = MatterDeadlineStatus.MISSED
    elif action == "reopen":
        deadline.status = MatterDeadlineStatus.OPEN
        deadline.completed_at = None
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown deadline action {action!r}.",
        )
    session.flush()
    record_from_context(
        session,
        context,
        action=f"deadline.{action}",
        target_type="matter_deadline",
        target_id=deadline.id,
        matter_id=deadline.matter_id,
        metadata={"status": deadline.status},
    )
    session.commit()
    session.refresh(deadline)
    return deadline


__all__ = [
    "create_deadline",
    "list_deadlines",
    "transition_deadline",
]
