"""GC intake queue service (Sprint 8b BG-025).

Tenant-scoped CRUD + promote-to-matter. Every mutation writes an
``audit_events`` row so the IAM audit trail captures who filed, who
triaged, and what the intake became.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MatterForumLevel,
    MatterIntakeRequest,
    MatterIntakeStatus,
    MatterStatus,
    User,
)
from caseops_api.schemas.intake import (
    IntakeRequestCreateRequest,
    IntakeRequestListResponse,
    IntakeRequestPromoteRequest,
    IntakeRequestRecord,
    IntakeRequestUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

logger = logging.getLogger(__name__)


def _load_request(
    session: Session, *, context: SessionContext, request_id: str
) -> MatterIntakeRequest:
    row = session.scalar(
        select(MatterIntakeRequest)
        .where(MatterIntakeRequest.id == request_id)
        .where(MatterIntakeRequest.company_id == context.company.id)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Intake request not found.",
        )
    return row


def _membership_name(
    session: Session, membership_id: str | None
) -> str | None:
    if not membership_id:
        return None
    row = session.scalar(
        select(User.full_name)
        .join(CompanyMembership, CompanyMembership.user_id == User.id)
        .where(CompanyMembership.id == membership_id)
    )
    return row


def _matter_code(session: Session, matter_id: str | None) -> str | None:
    if not matter_id:
        return None
    return session.scalar(select(Matter.matter_code).where(Matter.id == matter_id))


def _record(
    session: Session, row: MatterIntakeRequest
) -> IntakeRequestRecord:
    return IntakeRequestRecord(
        id=row.id,
        company_id=row.company_id,
        submitted_by_membership_id=row.submitted_by_membership_id,
        submitted_by_name=_membership_name(session, row.submitted_by_membership_id),
        assigned_to_membership_id=row.assigned_to_membership_id,
        assigned_to_name=_membership_name(session, row.assigned_to_membership_id),
        linked_matter_id=row.linked_matter_id,
        linked_matter_code=_matter_code(session, row.linked_matter_id),
        title=row.title,
        category=row.category,
        priority=row.priority,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        requester_name=row.requester_name,
        requester_email=row.requester_email,
        business_unit=row.business_unit,
        description=row.description,
        desired_by=row.desired_by,
        triage_notes=row.triage_notes,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_intake_request(
    session: Session,
    *,
    context: SessionContext,
    payload: IntakeRequestCreateRequest,
) -> IntakeRequestRecord:
    row = MatterIntakeRequest(
        company_id=context.company.id,
        submitted_by_membership_id=context.membership.id if context.membership else None,
        title=payload.title.strip(),
        category=payload.category,
        priority=payload.priority,
        status=MatterIntakeStatus.NEW,
        requester_name=payload.requester_name.strip(),
        requester_email=payload.requester_email,
        business_unit=(payload.business_unit or "").strip() or None,
        description=payload.description.strip(),
        desired_by=payload.desired_by,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="intake.created",
        target_type="matter_intake_request",
        target_id=row.id,
        metadata={
            "title": row.title,
            "category": row.category,
            "priority": row.priority,
        },
    )
    session.flush()
    return _record(session, row)


def list_intake_requests(
    session: Session,
    *,
    context: SessionContext,
    status_filter: str | None = None,
    assigned_to_me: bool = False,
) -> IntakeRequestListResponse:
    stmt = (
        select(MatterIntakeRequest)
        .where(MatterIntakeRequest.company_id == context.company.id)
        .order_by(MatterIntakeRequest.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(MatterIntakeRequest.status == status_filter)
    if assigned_to_me and context.membership is not None:
        stmt = stmt.where(
            MatterIntakeRequest.assigned_to_membership_id == context.membership.id
        )
    rows = list(session.scalars(stmt))
    return IntakeRequestListResponse(
        requests=[_record(session, r) for r in rows]
    )


def update_intake_request(
    session: Session,
    *,
    context: SessionContext,
    request_id: str,
    payload: IntakeRequestUpdateRequest,
) -> IntakeRequestRecord:
    row = _load_request(session, context=context, request_id=request_id)
    changes: dict[str, Any] = {}
    if payload.status is not None and payload.status != row.status:
        row.status = payload.status
        changes["status"] = payload.status
    if payload.priority is not None and payload.priority != row.priority:
        row.priority = payload.priority
        changes["priority"] = payload.priority
    if payload.assigned_to_membership_id is not None:
        new_assignee = payload.assigned_to_membership_id or None
        if new_assignee != row.assigned_to_membership_id:
            if new_assignee is not None:
                # Validate the membership belongs to this company.
                ok = session.scalar(
                    select(CompanyMembership.id)
                    .where(CompanyMembership.id == new_assignee)
                    .where(CompanyMembership.company_id == context.company.id)
                )
                if ok is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Assignee is not a member of this company.",
                    )
            row.assigned_to_membership_id = new_assignee
            changes["assigned_to"] = new_assignee
    if payload.triage_notes is not None:
        row.triage_notes = payload.triage_notes.strip() or None
        changes["triage_notes_updated"] = True
    if changes:
        session.flush()
        record_from_context(
            session,
            context,
            action="intake.updated",
            target_type="matter_intake_request",
            target_id=row.id,
            metadata=changes,
        )
        session.flush()
    return _record(session, row)


def promote_intake_request(
    session: Session,
    *,
    context: SessionContext,
    request_id: str,
    payload: IntakeRequestPromoteRequest,
) -> IntakeRequestRecord:
    row = _load_request(session, context=context, request_id=request_id)
    if row.linked_matter_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Intake request is already linked to a matter.",
        )
    # Reject promotion from terminal states.
    if row.status in (MatterIntakeStatus.COMPLETED, MatterIntakeStatus.REJECTED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot promote a {row.status} intake request.",
        )

    # Build the new matter. Keep it lean — the promoter can enrich from
    # the matter detail page afterwards. Matter description borrows
    # the intake description so the origin is preserved.
    matter_title = (payload.matter_title or row.title)[:255]
    client_name = row.business_unit or row.requester_name
    normalised_code = payload.matter_code.upper().strip()

    # Pre-flight uniqueness check — the (company_id, matter_code) unique
    # constraint would otherwise raise an IntegrityError on flush and
    # bubble up as a generic 500 / "Could not promote request" for the
    # frontend. Checking here lets us return a specific, actionable 400.
    # BUG-008 (2026-04-20): end users saw only the generic error with no
    # hint about why. Repro path: two intake requests promoted with the
    # same matter_code.
    existing_code = session.scalar(
        select(Matter.id).where(
            Matter.company_id == context.company.id,
            Matter.matter_code == normalised_code,
        )
    )
    if existing_code is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Matter code {normalised_code!r} is already in use for "
                "another matter in this workspace. Choose a different "
                "code and try again."
            ),
        )

    matter = Matter(
        company_id=context.company.id,
        matter_code=normalised_code,
        title=matter_title,
        client_name=client_name,
        practice_area=payload.practice_area,
        forum_level=MatterForumLevel(payload.forum_level),
        status=MatterStatus.INTAKE,
        description=f"Promoted from intake request {row.id}. {row.description}"[
            :4000
        ],
    )
    session.add(matter)
    session.flush()

    row.linked_matter_id = matter.id
    row.status = MatterIntakeStatus.IN_PROGRESS
    session.flush()

    record_from_context(
        session,
        context,
        action="intake.promoted",
        target_type="matter_intake_request",
        target_id=row.id,
        matter_id=matter.id,
        metadata={
            "matter_id": matter.id,
            "matter_code": matter.matter_code,
        },
    )
    record_from_context(
        session,
        context,
        action="matter.created",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={
            "matter_code": matter.matter_code,
            "origin": "intake",
            "intake_request_id": row.id,
        },
    )
    session.flush()
    return _record(session, row)


__all__ = [
    "create_intake_request",
    "list_intake_requests",
    "promote_intake_request",
    "update_intake_request",
]
