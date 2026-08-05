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
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
)
from caseops_api.schemas.matters import MatterDeadlineRecord, MatterDeadlineUpdateRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access, can_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

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


def _get_company_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> CompanyMembership:
    membership = session.scalar(
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if membership is None or not membership.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee does not belong to this company.",
        )
    return membership


def _assert_membership_can_access_matter(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    membership: CompanyMembership,
) -> None:
    candidate_context = SessionContext(
        company=context.company,
        user=membership.user,
        membership=membership,
    )
    if can_access(session, context=candidate_context, matter=matter):
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Assignee cannot access this matter.",
    )


def deadline_record(deadline: MatterDeadline) -> MatterDeadlineRecord:
    return MatterDeadlineRecord(
        id=deadline.id,
        matter_id=deadline.matter_id,
        source=deadline.source,
        kind=deadline.kind,
        title=deadline.title,
        notes=deadline.notes,
        due_on=deadline.due_on,
        status=deadline.status,
        assignee_membership_id=deadline.assignee_membership_id,
        source_ref_type=deadline.source_ref_type,
        source_ref_id=deadline.source_ref_id,
        created_by_membership_id=deadline.created_by_membership_id,
        completed_at=deadline.completed_at,
        created_at=deadline.created_at,
        updated_at=deadline.updated_at,
    )


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


def list_deadline_records(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    include_done: bool = False,
) -> list[MatterDeadlineRecord]:
    return [
        deadline_record(deadline)
        for deadline in list_deadlines(
            session,
            context=context,
            matter_id=matter_id,
            include_done=include_done,
        )
    ]


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
    matter = require_operational_matter(
        session,
        matter=_load_matter(session, context, matter_id),
        operation="create a deadline",
    )
    if assignee_membership_id:
        assignee = _get_company_membership(
            session,
            company_id=context.company.id,
            membership_id=assignee_membership_id,
        )
        _assert_membership_can_access_matter(
            session,
            context=context,
            matter=matter,
            membership=assignee,
        )
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


def update_deadline(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    deadline_id: str,
    payload: MatterDeadlineUpdateRequest,
) -> MatterDeadline:
    matter = require_operational_matter(
        session,
        matter=_load_matter(session, context, matter_id),
        operation="update a deadline",
    )
    deadline = session.scalar(
        select(MatterDeadline).where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.matter_id == matter_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    if deadline is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found."
        )

    updates = payload.model_dump(exclude_unset=True)
    if (
        deadline.cancelled_by_matter_disposal
        and "status" in updates
        and updates["status"] != MatterDeadlineStatus.CANCELLED.value
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This deadline was cancelled by matter disposal and cannot be "
                "resurrected after reopening. Create a new deadline instead."
            ),
        )
    assignee_membership_id = updates.pop("assignee_membership_id", None)
    assignee_changed = "assignee_membership_id" in payload.model_dump(exclude_unset=True)
    if assignee_changed:
        if assignee_membership_id is None:
            deadline.assignee_membership_id = None
        else:
            assignee = _get_company_membership(
                session,
                company_id=context.company.id,
                membership_id=assignee_membership_id,
            )
            _assert_membership_can_access_matter(
                session,
                context=context,
                matter=matter,
                membership=assignee,
            )
            deadline.assignee_membership_id = assignee.id

    previous_status = deadline.status
    changed_fields: set[str] = set()
    for field_name, value in updates.items():
        if field_name == "title":
            value = value.strip()
        elif field_name == "notes" and isinstance(value, str):
            value = value.strip() or None
        if getattr(deadline, field_name) != value:
            changed_fields.add(field_name)
            setattr(deadline, field_name, value)
    if assignee_changed:
        changed_fields.add("assignee_membership_id")

    if previous_status != deadline.status:
        changed_fields.add("status")
        now = datetime.now(UTC)
        if deadline.status in {
            MatterDeadlineStatus.DONE,
            MatterDeadlineStatus.CANCELLED,
        }:
            deadline.completed_at = deadline.completed_at or now
        elif deadline.status == MatterDeadlineStatus.OPEN:
            deadline.completed_at = None
        if deadline.status in {
            MatterDeadlineStatus.DONE,
            MatterDeadlineStatus.CANCELLED,
        }:
            from caseops_api.services.notification_delivery import (
                cancel_pending_notification_intents,
            )

            cancel_pending_notification_intents(
                session,
                company_id=context.company.id,
                schedule_source_type="matter_deadline",
                schedule_source_id=deadline.id,
            )

    action = "deadline.updated"
    if previous_status != deadline.status:
        if deadline.status == MatterDeadlineStatus.DONE:
            action = "deadline.complete"
        elif previous_status == MatterDeadlineStatus.DONE and (
            deadline.status == MatterDeadlineStatus.OPEN
        ):
            action = "deadline.reopen"
        elif deadline.status == MatterDeadlineStatus.CANCELLED:
            action = "deadline.cancel"
        elif deadline.status == MatterDeadlineStatus.MISSED:
            action = "deadline.miss"

    session.add(deadline)
    session.flush()
    record_from_context(
        session,
        context,
        action=action,
        target_type="matter_deadline",
        target_id=deadline.id,
        matter_id=deadline.matter_id,
        metadata={
            "status": deadline.status,
            "changed_fields": sorted(changed_fields),
            "source": deadline.source,
            "kind": deadline.kind,
            "has_notes": bool(deadline.notes),
            "has_source_ref": bool(deadline.source_ref_id),
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
    require_operational_matter(
        session,
        matter=_load_matter(session, context, deadline.matter_id),
        operation="transition a deadline",
    )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(MatterDeadline.id == deadline_id)
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    assert deadline is not None
    if deadline.cancelled_by_matter_disposal and action != "cancel":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This deadline was cancelled by matter disposal and cannot be "
                "resurrected after reopening. Create a new deadline instead."
            ),
        )
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
    if action in {"complete", "cancel"}:
        from caseops_api.services.notification_delivery import (
            cancel_pending_notification_intents,
        )

        cancel_pending_notification_intents(
            session,
            company_id=context.company.id,
            schedule_source_type="matter_deadline",
            schedule_source_id=deadline.id,
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
    "deadline_record",
    "list_deadline_records",
    "list_deadlines",
    "transition_deadline",
    "update_deadline",
]
