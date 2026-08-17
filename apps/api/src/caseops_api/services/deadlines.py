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
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
)
from caseops_api.schemas.matters import MatterDeadlineRecord, MatterDeadlineUpdateRequest
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import (
    assert_access,
    can_access,
    can_access_ip_docket,
    can_stably_access_ip_docket,
)
from caseops_api.services.matter_operational_guard import (
    matter_is_operational,
    require_operational_matter,
)
from caseops_api.services.session_context import SessionContext

_VALID_SOURCES = {
    "hearing",
    "draft",
    "contract",
    "intake",
    "custom",
    "followup",
    "ip_deadline",
}

_IP_COVERAGE_OPERATIONAL_STATUSES = frozenset(
    {
        "accepted",
        "emergency",
        "escalated",
        "pending",
        "reassigned",
        "transfer_pending",
    }
)
_IP_DOCKET_TERMINAL_STATUSES = frozenset(
    {"archived", "abandoned", "transferred", "retired", "closed"}
)

LinkedIpDocketFamilySnapshot = tuple[tuple[str, str, bool, bool, int, bool], ...]


def _deadline_is_lifecycle_neutralized(deadline: object) -> bool:
    return bool(
        getattr(deadline, "cancelled_by_matter_disposal", False)
        or getattr(deadline, "neutralized_by_ip_lifecycle_event_id", None)
        or getattr(deadline, "neutralized_by_ip_lifecycle_version", None)
        or getattr(deadline, "neutralized_at", None)
    )


def _raise_immutable_deadline_history() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "deadline_lifecycle_history_immutable",
            "message": (
                "This deadline is lifecycle-neutralized history and cannot be "
                "changed after reopening. Create a new deadline instead."
            ),
        },
    )


def _linked_ip_docket_family_snapshot(
    dockets: list[IpDocketRecord],
) -> LinkedIpDocketFamilySnapshot:
    return tuple(
        sorted(
            (
                docket.id,
                str(docket.status),
                bool(docket.is_active),
                bool(docket.archived_by_matter_disposal),
                int(docket.access_policy_version),
                bool(docket.restricted),
            )
            for docket in dockets
        )
    )


def _operational_linked_ip_dockets(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    for_update: bool = False,
) -> list[IpDocketRecord]:
    statement = (
        select(IpDocketRecord)
        .where(
            IpDocketRecord.company_id == company_id,
            IpDocketRecord.matter_id == matter_id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            IpDocketRecord.status.notin_(_IP_DOCKET_TERMINAL_STATUSES),
        )
        .order_by(IpDocketRecord.id)
    )
    if for_update:
        statement = statement.with_for_update(of=IpDocketRecord).execution_options(
            populate_existing=True
        )
    return list(session.scalars(statement).all())


def _lock_and_revalidate_linked_ip_docket_family(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    expected: LinkedIpDocketFamilySnapshot,
) -> list[IpDocketRecord]:
    dockets = _operational_linked_ip_dockets(
        session,
        company_id=company_id,
        matter_id=matter_id,
        for_update=True,
    )
    if _linked_ip_docket_family_snapshot(dockets) != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_linked_docket_family_changed",
                "message": (
                    "Linked IP records or their access policy changed; reload before "
                    "changing this deadline."
                ),
            },
        )
    return dockets


def _load_matter(
    session: Session,
    context: SessionContext,
    matter_id: str,
    *,
    for_update: bool = False,
) -> Matter:
    statement = select(Matter).where(
        Matter.id == matter_id,
        Matter.company_id == context.company.id,
    )
    if for_update:
        statement = statement.with_for_update(of=Matter).execution_options(
            populate_existing=True
        )
    matter = session.scalar(statement)
    if matter is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
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
    linked_dockets: list[IpDocketRecord] | None = None,
) -> None:
    candidate_context = SessionContext(
        company=context.company,
        user=membership.user,
        membership=membership,
    )
    if linked_dockets is None:
        linked_dockets = _operational_linked_ip_dockets(
            session,
            company_id=matter.company_id,
            matter_id=matter.id,
        )
    has_operational_ip_docket = bool(linked_dockets)
    access_allowed = all(
        can_stably_access_ip_docket(
            session,
            context=candidate_context,
            docket=docket,
        )
        for docket in linked_dockets
    ) if has_operational_ip_docket else can_access(
        session,
        context=candidate_context,
        matter=matter,
    )
    if access_allowed:
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Assignee needs durable access to this Matter while linked IP work "
            "is operational."
            if has_operational_ip_docket
            else "Assignee cannot access this matter."
        ),
    )


def _assert_generic_mutation_does_not_bypass_ip_workflow(
    session: Session,
    *,
    deadline_id: str,
    changed_fields: set[str],
) -> None:
    if not changed_fields:
        return
    linked_ip_deadline = session.scalar(
        select(IpDeadline.id).where(IpDeadline.matter_deadline_id == deadline_id).limit(1)
    )
    linked_ip_coverage = session.scalar(
        select(IpDeadlineCoverage.id)
        .where(IpDeadlineCoverage.matter_deadline_id == deadline_id)
        .limit(1)
    )
    if linked_ip_deadline is None and linked_ip_coverage is None:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ip_deadline_workflow_required",
            "message": (
                "IP-owned deadline responsibility and lifecycle must be changed "
                "through the IP legal-deadline workflow."
            ),
        },
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
            MatterDeadline.status.in_([MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED])
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
    commit: bool = True,
    required_capability: str = "matters:write",
) -> MatterDeadline:
    linked_docket_candidates = _operational_linked_ip_dockets(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
    )
    linked_docket_snapshot = _linked_ip_docket_family_snapshot(
        linked_docket_candidates
    )
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id, assignee_membership_id},
    )
    actor = memberships.get(context.membership.id)
    if actor is None or not actor.is_active or not actor.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required to create a deadline.",
        )
    require_locked_membership_capability(session, actor, required_capability)
    assignee = memberships.get(assignee_membership_id) if assignee_membership_id else None
    if assignee_membership_id and (
        assignee is None or not assignee.is_active or not assignee.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee does not belong to this company.",
        )
    matter = require_operational_matter(
        session,
        matter=_load_matter(session, context, matter_id, for_update=True),
        operation="create a deadline",
    )
    linked_dockets = _lock_and_revalidate_linked_ip_docket_family(
        session,
        company_id=context.company.id,
        matter_id=matter.id,
        expected=linked_docket_snapshot,
    )
    if assignee is not None:
        _assert_membership_can_access_matter(
            session,
            context=context,
            matter=matter,
            membership=assignee,
            linked_dockets=linked_dockets,
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
        company_id=matter.company_id,
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
    if commit:
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
    commit: bool = True,
    allow_ip_workflow_mutation: bool = False,
    required_capability: str = "matters:write",
) -> MatterDeadline:
    requested_updates = payload.model_dump(exclude_unset=True)
    candidate = session.execute(
        select(
            MatterDeadline.assignee_membership_id,
            MatterDeadline.status,
            MatterDeadline.cancelled_by_matter_disposal,
            MatterDeadline.neutralized_by_ip_lifecycle_event_id,
            MatterDeadline.neutralized_by_ip_lifecycle_version,
            MatterDeadline.neutralized_at,
            MatterDeadline.updated_at,
        ).where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.matter_id == matter_id,
            MatterDeadline.company_id == context.company.id,
        )
    ).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found.")
    resulting_assignee_id = requested_updates.get(
        "assignee_membership_id", candidate.assignee_membership_id
    )
    resulting_status = requested_updates.get("status", candidate.status)
    linked_docket_candidates = _operational_linked_ip_dockets(
        session,
        company_id=context.company.id,
        matter_id=matter_id,
    )
    linked_docket_snapshot = _linked_ip_docket_family_snapshot(
        linked_docket_candidates
    )
    resulting_assignee: CompanyMembership | None = None
    if allow_ip_workflow_mutation:
        require_locked_membership_capability(
            session,
            context.membership,
            required_capability,
        )
        if "assignee_membership_id" in requested_updates:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_deadline_workflow_required",
                    "message": "The IP workflow may not bypass responsibility transfer.",
                },
            )
    else:
        memberships = lock_company_memberships_for_assignment(
            session,
            company_id=context.company.id,
            membership_ids={
                context.membership.id,
                candidate.assignee_membership_id,
                resulting_assignee_id,
            },
        )
        actor = memberships.get(context.membership.id)
        if actor is None or not actor.is_active or not actor.user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="An active company membership is required to update a deadline.",
            )
        require_locked_membership_capability(session, actor, required_capability)
        resulting_assignee = (
            memberships.get(resulting_assignee_id) if resulting_assignee_id else None
        )
        if resulting_assignee_id and (
            resulting_assignee is None
            or not resulting_assignee.is_active
            or not resulting_assignee.user.is_active
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Assignee does not belong to this company.",
            )
    matter = require_operational_matter(
        session,
        matter=_load_matter(session, context, matter_id, for_update=True),
        operation="update a deadline",
    )
    linked_dockets = _lock_and_revalidate_linked_ip_docket_family(
        session,
        company_id=context.company.id,
        matter_id=matter.id,
        expected=linked_docket_snapshot,
    )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.matter_id == matter_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    if deadline is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found.")
    if (
        deadline.assignee_membership_id,
        deadline.status,
        deadline.cancelled_by_matter_disposal,
        deadline.neutralized_by_ip_lifecycle_event_id,
        deadline.neutralized_by_ip_lifecycle_version,
        deadline.neutralized_at,
        deadline.updated_at,
    ) != (
        candidate.assignee_membership_id,
        candidate.status,
        candidate.cancelled_by_matter_disposal,
        candidate.neutralized_by_ip_lifecycle_event_id,
        candidate.neutralized_by_ip_lifecycle_version,
        candidate.neutralized_at,
        candidate.updated_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deadline assignment or lifecycle changed; reload before updating.",
        )
    if _deadline_is_lifecycle_neutralized(deadline):
        _raise_immutable_deadline_history()

    if (
        not allow_ip_workflow_mutation
        and resulting_assignee is not None
        and resulting_status in {MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED}
    ):
        _assert_membership_can_access_matter(
            session,
            context=context,
            matter=matter,
            membership=resulting_assignee,
            linked_dockets=linked_dockets,
        )

    updates = requested_updates
    if not allow_ip_workflow_mutation:
        _assert_generic_mutation_does_not_bypass_ip_workflow(
            session,
            deadline_id=deadline.id,
            changed_fields=set(updates),
        )
    assignee_membership_id = updates.pop("assignee_membership_id", None)
    assignee_changed = "assignee_membership_id" in payload.model_dump(exclude_unset=True)
    if assignee_changed:
        if assignee_membership_id is None:
            deadline.assignee_membership_id = None
        else:
            assert resulting_assignee is not None
            deadline.assignee_membership_id = resulting_assignee.id

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
    if commit:
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
    expected_ip_docket_id: str | None = None,
    require_ip_coverage: bool = False,
    required_capability: str = "matters:write",
) -> MatterDeadline:
    if action not in {"complete", "cancel", "reopen", "miss"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown deadline action {action!r}.",
        )
    candidate = session.execute(
        select(
            MatterDeadline.matter_id,
            MatterDeadline.ip_docket_id,
            MatterDeadline.assignee_membership_id,
            MatterDeadline.status,
            MatterDeadline.cancelled_by_matter_disposal,
            MatterDeadline.neutralized_by_ip_lifecycle_event_id,
            MatterDeadline.neutralized_by_ip_lifecycle_version,
            MatterDeadline.neutralized_at,
            MatterDeadline.updated_at,
        ).where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.company_id == context.company.id,
        )
    ).one_or_none()
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deadline not found.")
    locked_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={
            context.membership.id,
            candidate.assignee_membership_id,
        },
    )
    locked_actor = locked_memberships.get(context.membership.id)
    if (
        locked_actor is None
        or not locked_actor.is_active
        or not locked_actor.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required to change a deadline.",
        )
    require_locked_membership_capability(
        session,
        locked_actor,
        required_capability,
    )
    locked_context = SessionContext(
        company=context.company,
        membership=locked_actor,
        user=locked_actor.user,
    )
    linked_ip_deadline_refs = list(
        session.execute(
            select(IpDeadline.id, IpDeadline.docket_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.matter_deadline_id == deadline_id,
            )
        ).all()
    )
    coverage_refs = list(
        session.execute(
            select(IpDeadlineCoverage.id, IpDeadlineCoverage.docket_id).where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.matter_deadline_id == deadline_id,
            )
        ).all()
    )
    if require_ip_coverage and not coverage_refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_coverage_required",
                "message": "This action is only available for an IP-covered deadline.",
            },
        )
    coverage_docket_ids = {row.docket_id for row in coverage_refs}
    if (
        expected_ip_docket_id is not None
        and expected_ip_docket_id not in coverage_docket_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Operational deadline not found.",
        )
    ip_docket_ids = coverage_docket_ids | {
        row.docket_id for row in linked_ip_deadline_refs
    }
    if candidate.ip_docket_id is not None:
        ip_docket_ids.add(candidate.ip_docket_id)
    advisory_dockets = (
        list(
            session.execute(
                select(IpDocketRecord.id, IpDocketRecord.matter_id)
                .where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(sorted(ip_docket_ids)),
                )
                .order_by(IpDocketRecord.id)
            ).all()
        )
        if ip_docket_ids
        else []
    )
    if {row.id for row in advisory_dockets} != ip_docket_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_projection_changed",
                "message": "The linked IP docket family changed; reload before updating.",
            },
        )
    matter_ids = {
        matter_id
        for matter_id in (
            candidate.matter_id,
            *(row.matter_id for row in advisory_dockets),
        )
        if matter_id is not None
    }
    locked_matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(sorted(matter_ids)),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
        if matter_ids
        else []
    )
    if {matter.id for matter in locked_matters} != matter_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    for matter in locked_matters:
        if (
            not matter_is_operational(matter)
            or not can_access(session, context=locked_context, matter=matter)
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Matter not found.",
            )
    locked_dockets = (
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(sorted(ip_docket_ids)),
                )
                .order_by(IpDocketRecord.id)
                .with_for_update(of=IpDocketRecord)
                .execution_options(populate_existing=True)
            )
        )
        if ip_docket_ids
        else []
    )
    if {row.id for row in locked_dockets} != ip_docket_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_projection_changed",
                "message": "The linked IP docket family changed; reload before updating.",
            },
        )
    advisory_docket_matter = {row.id: row.matter_id for row in advisory_dockets}
    if any(
        docket.matter_id != advisory_docket_matter.get(docket.id)
        or (
            candidate.matter_id is not None
            and docket.id in coverage_docket_ids
            and docket.matter_id != candidate.matter_id
        )
        or not docket.is_active
        or docket.archived_by_matter_disposal
        or str(docket.status) in _IP_DOCKET_TERMINAL_STATUSES
        or not can_access_ip_docket(
            session,
            context=locked_context,
            docket=docket,
        )
        for docket in locked_dockets
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP docket record not found.",
        )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == deadline_id,
            MatterDeadline.company_id == context.company.id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    assert deadline is not None
    if (
        deadline.matter_id != candidate.matter_id
        or deadline.ip_docket_id != candidate.ip_docket_id
        or deadline.assignee_membership_id != candidate.assignee_membership_id
        or deadline.status != candidate.status
        or deadline.cancelled_by_matter_disposal
        != candidate.cancelled_by_matter_disposal
        or deadline.neutralized_by_ip_lifecycle_event_id
        != candidate.neutralized_by_ip_lifecycle_event_id
        or deadline.neutralized_by_ip_lifecycle_version
        != candidate.neutralized_by_ip_lifecycle_version
        or deadline.neutralized_at != candidate.neutralized_at
        or deadline.updated_at != candidate.updated_at
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Deadline responsibility or lifecycle changed; reload before updating.",
        )
    if _deadline_is_lifecycle_neutralized(deadline):
        _raise_immutable_deadline_history()
    current_ip_deadline_refs = {
        (row.id, row.docket_id)
        for row in session.execute(
            select(IpDeadline.id, IpDeadline.docket_id).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.matter_deadline_id == deadline.id,
            )
        ).all()
    }
    if current_ip_deadline_refs != {
        (row.id, row.docket_id) for row in linked_ip_deadline_refs
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_projection_changed",
                "message": "The linked IP legal deadline changed; reload before updating.",
            },
        )
    if current_ip_deadline_refs:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_workflow_required",
                "message": (
                    "IP legal-deadline lifecycle must be changed through the IP "
                    "legal-deadline workflow."
                ),
            },
        )
    expected_coverage_ids = {row.id for row in coverage_refs}
    coverage_rows = (
        list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.id.in_(sorted(expected_coverage_ids)),
                    IpDeadlineCoverage.matter_deadline_id == deadline.id,
                )
                .order_by(IpDeadlineCoverage.id)
                .with_for_update(of=IpDeadlineCoverage)
                .execution_options(populate_existing=True)
            )
        )
        if expected_coverage_ids
        else []
    )
    if (
        {row.id for row in coverage_rows} != expected_coverage_ids
        or {
            (row.id, row.docket_id)
            for row in session.execute(
                select(IpDeadlineCoverage.id, IpDeadlineCoverage.docket_id).where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id == deadline.id,
                )
            ).all()
        }
        != {(row.id, row.docket_id) for row in coverage_refs}
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_projection_changed",
                "message": "The linked IP coverage family changed; reload before updating.",
            },
        )
    if require_ip_coverage and not any(
        str(row.coverage_status) in _IP_COVERAGE_OPERATIONAL_STATUSES
        for row in coverage_rows
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_coverage_projection_inactive",
                "message": "The IP deadline coverage is no longer operational.",
            },
        )
    coverage_would_reopen = action == "reopen" or (
        action == "miss"
        and deadline.status not in (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
    )
    if coverage_rows and coverage_would_reopen:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_deadline_workflow_required",
                "message": (
                    "A completed IP-covered deadline cannot be reopened through the "
                    "generic deadline workflow."
                ),
            },
        )
    now = datetime.now(UTC)
    if action in {"complete", "cancel"} and coverage_rows:
        from caseops_api.services.ip_coverage_projection import (
            terminalize_coverage_only_deadline_projection,
        )

        terminalize_coverage_only_deadline_projection(
            session,
            company_id=context.company.id,
            matter_deadline_id=deadline.id,
            reason=(
                "Generic IP-covered deadline completed."
                if action == "complete"
                else "Generic IP-covered deadline cancelled."
            ),
            changed_at=now,
        )
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
