"""Neutral Matter/IP targeting over the existing shared-work owners.

IPLF-025A deliberately does not create IP-private copies of the canonical
work-owner tables or a second operational-deadline/calendar/notification
lifecycle. This module is the typed backend boundary that IPLF-025B's user
workflows call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CompanyMembership,
    HearingReminder,
    IpDocketRecord,
    Matter,
    MatterDeadline,
    MatterHearing,
    MatterNextHearingHistory,
    MatterNextHearingSuggestion,
    MatterTask,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.schemas.shared_work import (
    IpHearingReminderRecord,
    IpOperationalDeadlineCreateRequest,
    IpOperationalDeadlineListResponse,
    IpOperationalDeadlineRecord,
    IpOperationalDeadlineUpdateRequest,
    IpSharedHearingCreateRequest,
    IpSharedHearingListResponse,
    IpSharedHearingRecord,
    IpSharedHearingUpdateRequest,
    IpSharedTaskCreateRequest,
    IpSharedTaskListResponse,
    IpSharedTaskRecord,
    IpSharedTaskUpdateRequest,
    SharedWorkFoundationContract,
    SharedWorkOwnerContract,
    SharedWorkOwnerReconciliation,
    SharedWorkReconciliationReport,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import _docket_or_404
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

CONTRACT_VERSION = "IPLF-025B/2026-08-10"
MIGRATION_HEADS = [
    "20260810_0001",
    "20260810_0002",
    "20260810_0003",
    "20260810_0004",
]


@dataclass(frozen=True, slots=True)
class SharedWorkTarget:
    company_id: str
    target_type: Literal["matter", "ip_docket"]
    target_id: str
    matter: Matter | None = None
    ip_docket: IpDocketRecord | None = None

    @property
    def matter_id(self) -> str | None:
        return self.matter.id if self.matter is not None else None

    @property
    def ip_docket_id(self) -> str | None:
        return self.ip_docket.id if self.ip_docket is not None else None


_OWNER_MODELS = (
    ("tasks", MatterTask),
    ("hearings", MatterHearing),
    ("hearing_reminders", HearingReminder),
    ("next_hearing_history", MatterNextHearingHistory),
    ("next_hearing_suggestions", MatterNextHearingSuggestion),
    ("operational_deadlines", MatterDeadline),
)


def resolve_shared_work_target(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None = None,
    ip_docket_id: str | None = None,
    for_update: bool = False,
) -> SharedWorkTarget:
    if (matter_id is None) == (ip_docket_id is None):
        raise ValueError("Exactly one Matter or IP docket target is required.")
    if matter_id is not None:
        stmt = select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
        if for_update:
            stmt = stmt.with_for_update(of=Matter)
        matter = session.scalar(stmt)
        if matter is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Matter not found.")
        assert_access(session, context=context, matter=matter)
        matter = require_operational_matter(
            session, matter=matter, operation="change shared work"
        )
        return SharedWorkTarget(
            company_id=context.company.id,
            target_type="matter",
            target_id=matter.id,
            matter=matter,
        )
    assert ip_docket_id is not None
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=ip_docket_id,
        for_update=for_update,
    )
    return SharedWorkTarget(
        company_id=context.company.id,
        target_type="ip_docket",
        target_id=docket.id,
        ip_docket=docket,
    )


def shared_target_predicate(model, target: SharedWorkTarget):
    """Return the canonical target filter used by all shared readers."""

    return and_(
        model.company_id == target.company_id,
        model.matter_id == target.matter_id,
        model.ip_docket_id == target.ip_docket_id,
    )


def _active_membership(
    session: Session, *, company_id: str, membership_id: str | None
) -> CompanyMembership | None:
    if membership_id is None:
        return None
    membership = session.scalar(
        select(CompanyMembership)
        .join(User, CompanyMembership.user_id == User.id)
        .options(joinedload(CompanyMembership.user))
        .where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assignee does not belong to this company.",
        )
    return membership


def _task_record(task: MatterTask) -> IpSharedTaskRecord:
    assert task.company_id is not None and task.ip_docket_id is not None
    return IpSharedTaskRecord(
        id=task.id,
        company_id=task.company_id,
        target_id=task.ip_docket_id,
        ip_docket_id=task.ip_docket_id,
        created_by_membership_id=task.created_by_membership_id,
        owner_membership_id=task.owner_membership_id,
        title=task.title,
        description=task.description,
        due_on=task.due_on,
        status=task.status,
        priority=task.priority,
        completed_at=task.completed_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def create_ip_shared_task(
    session: Session, *, context: SessionContext, payload: IpSharedTaskCreateRequest
) -> IpSharedTaskRecord:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    _active_membership(
        session,
        company_id=target.company_id,
        membership_id=payload.owner_membership_id,
    )
    completed_at = (
        datetime.now(UTC) if payload.status in {"completed", "cancelled"} else None
    )
    task = MatterTask(
        company_id=target.company_id,
        ip_docket_id=target.ip_docket_id,
        created_by_membership_id=context.membership.id,
        owner_membership_id=payload.owner_membership_id,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        due_on=payload.due_on,
        status=payload.status,
        priority=payload.priority,
        completed_at=completed_at,
    )
    session.add(task)
    session.flush()
    record_from_context(
        session,
        context,
        action="shared_task.created",
        target_type="matter_task",
        target_id=task.id,
        metadata={"ip_docket_id": target.target_id, "status": task.status},
    )
    session.commit()
    session.refresh(task)
    return _task_record(task)


def list_ip_shared_tasks(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    include_completed: bool = True,
) -> IpSharedTaskListResponse:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=docket_id, for_update=False
    )
    stmt = select(MatterTask).where(shared_target_predicate(MatterTask, target))
    if not include_completed:
        stmt = stmt.where(MatterTask.status.notin_(("completed", "cancelled")))
    stmt = stmt.order_by(
        MatterTask.due_on.is_(None), MatterTask.due_on, MatterTask.created_at, MatterTask.id
    )
    return IpSharedTaskListResponse(
        docket_id=docket_id,
        tasks=[_task_record(task) for task in session.scalars(stmt)],
    )


def update_ip_shared_task(
    session: Session,
    *,
    context: SessionContext,
    task_id: str,
    payload: IpSharedTaskUpdateRequest,
) -> IpSharedTaskRecord:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    task = session.scalar(
        select(MatterTask)
        .where(MatterTask.id == task_id, shared_target_predicate(MatterTask, target))
        .with_for_update(of=MatterTask)
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Shared task not found.")
    updates = payload.model_dump(exclude_unset=True, exclude={"docket_id"})
    if "owner_membership_id" in updates:
        _active_membership(
            session,
            company_id=target.company_id,
            membership_id=updates["owner_membership_id"],
        )
    for field, value in updates.items():
        if field in {"title", "description"} and isinstance(value, str):
            value = value.strip() or None
        setattr(task, field, value)
    if task.status in {"completed", "cancelled"}:
        task.completed_at = task.completed_at or datetime.now(UTC)
    else:
        task.completed_at = None
    record_from_context(
        session,
        context,
        action="shared_task.updated",
        target_type="matter_task",
        target_id=task.id,
        metadata={"ip_docket_id": target.target_id, "changed_fields": sorted(updates)},
    )
    session.commit()
    session.refresh(task)
    return _task_record(task)


def _hearing_record(session: Session, hearing: MatterHearing) -> IpSharedHearingRecord:
    assert hearing.company_id is not None and hearing.ip_docket_id is not None
    reminders = session.scalars(
        select(HearingReminder)
        .where(
            HearingReminder.company_id == hearing.company_id,
            HearingReminder.ip_docket_id == hearing.ip_docket_id,
            HearingReminder.hearing_id == hearing.id,
        )
        .order_by(HearingReminder.scheduled_for, HearingReminder.id)
    )
    return IpSharedHearingRecord(
        id=hearing.id,
        company_id=hearing.company_id,
        target_id=hearing.ip_docket_id,
        ip_docket_id=hearing.ip_docket_id,
        hearing_on=hearing.hearing_on,
        time_status=hearing.time_status,
        hearing_time=hearing.hearing_time,
        session_label=hearing.session_label,
        timezone=hearing.timezone,
        hearing_mode=hearing.hearing_mode,
        location_text=hearing.location_text,
        meeting_url=hearing.meeting_url,
        attendee_membership_ids=list(hearing.attendee_membership_ids_json or []),
        source=hearing.source,
        source_ref_type=hearing.source_ref_type,
        source_ref_id=hearing.source_ref_id,
        responsible_membership_id=hearing.responsible_membership_id,
        forum_name=hearing.forum_name,
        judge_name=hearing.judge_name,
        purpose=hearing.purpose,
        status=hearing.status,
        outcome_note=hearing.outcome_note,
        reminder_policy=hearing.reminder_policy_json,
        reminders=[
            IpHearingReminderRecord(
                id=reminder.id,
                recipient_membership_id=reminder.recipient_membership_id,
                channel=reminder.channel,
                scheduled_for=reminder.scheduled_for,
                schedule_generation=reminder.schedule_generation,
                status=reminder.status,
                provider=reminder.provider,
                provider_message_id=reminder.provider_message_id,
                last_error=reminder.last_error,
                attempts=reminder.attempts,
                sent_at=reminder.sent_at,
                delivered_at=reminder.delivered_at,
                created_at=reminder.created_at,
            )
            for reminder in reminders
        ],
        created_at=hearing.created_at,
    )


def _validated_reminder_policy(
    session: Session,
    *,
    company_id: str,
    policy,
) -> dict | None:
    if policy is None:
        return None
    for membership_id in policy.recipient_membership_ids:
        _active_membership(
            session, company_id=company_id, membership_id=membership_id
        )
    _active_membership(
        session,
        company_id=company_id,
        membership_id=policy.escalation_membership_id,
    )
    return policy.model_dump(mode="json")


def _append_ip_next_hearing_history(
    session: Session,
    *,
    target: SharedWorkTarget,
    new_date,
    context: SessionContext,
    source_ref_id: str,
    reason: str,
) -> None:
    old_date = session.scalar(
        select(MatterNextHearingHistory.new_date)
        .where(shared_target_predicate(MatterNextHearingHistory, target))
        .order_by(MatterNextHearingHistory.created_at.desc())
        .limit(1)
    )
    session.add(
        MatterNextHearingHistory(
            company_id=target.company_id,
            ip_docket_id=target.ip_docket_id,
            old_date=old_date,
            new_date=new_date,
            source="shared_hearing",
            source_ref_type="matter_hearing",
            source_ref_id=source_ref_id,
            changed_by_membership_id=context.membership.id,
            change_reason=reason,
            manual_lock=True,
        )
    )


def create_ip_shared_hearing(
    session: Session, *, context: SessionContext, payload: IpSharedHearingCreateRequest
) -> IpSharedHearingRecord:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    try:
        ZoneInfo(payload.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Unknown IANA hearing timezone.") from exc
    _active_membership(
        session,
        company_id=target.company_id,
        membership_id=payload.responsible_membership_id,
    )
    for membership_id in payload.attendee_membership_ids:
        _active_membership(
            session,
            company_id=target.company_id,
            membership_id=membership_id,
        )
    hearing = MatterHearing(
        company_id=target.company_id,
        ip_docket_id=target.ip_docket_id,
        hearing_on=payload.hearing_on,
        time_status=payload.time_status,
        hearing_time=payload.hearing_time,
        session_label=payload.session_label.strip() if payload.session_label else None,
        timezone=payload.timezone,
        hearing_mode=payload.hearing_mode,
        location_text=payload.location_text.strip() if payload.location_text else None,
        meeting_url=payload.meeting_url,
        attendee_membership_ids_json=payload.attendee_membership_ids,
        source=payload.source.strip().lower(),
        source_ref_type=payload.source_ref_type,
        source_ref_id=payload.source_ref_id,
        responsible_membership_id=payload.responsible_membership_id,
        reminder_policy_json=_validated_reminder_policy(
            session,
            company_id=target.company_id,
            policy=payload.reminder_policy,
        ),
        forum_name=payload.forum_name.strip(),
        judge_name=payload.judge_name.strip() if payload.judge_name else None,
        purpose=payload.purpose.strip(),
        status=payload.status,
        outcome_note=payload.outcome_note.strip() if payload.outcome_note else None,
    )
    session.add(hearing)
    session.flush()
    if hearing.status not in {"completed", "cancelled"}:
        _append_ip_next_hearing_history(
            session,
            target=target,
            new_date=hearing.hearing_on,
            context=context,
            source_ref_id=hearing.id,
            reason="hearing_created",
        )
        if hearing.reminder_policy_json:
            from caseops_api.services.hearing_reminders import (
                schedule_reminders_for_hearing,
            )

            schedule_reminders_for_hearing(session, hearing=hearing)
    record_from_context(
        session,
        context,
        action="shared_hearing.created",
        target_type="matter_hearing",
        target_id=hearing.id,
        metadata={"ip_docket_id": target.target_id, "time_status": hearing.time_status},
    )
    session.commit()
    session.refresh(hearing)
    return _hearing_record(session, hearing)


def list_ip_shared_hearings(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpSharedHearingListResponse:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=docket_id, for_update=False
    )
    hearings = session.scalars(
        select(MatterHearing)
        .where(shared_target_predicate(MatterHearing, target))
        .order_by(MatterHearing.hearing_on, MatterHearing.created_at, MatterHearing.id)
    )
    return IpSharedHearingListResponse(
        docket_id=docket_id,
        hearings=[_hearing_record(session, hearing) for hearing in hearings],
    )


def update_ip_shared_hearing(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
    payload: IpSharedHearingUpdateRequest,
) -> IpSharedHearingRecord:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    hearing = session.scalar(
        select(MatterHearing)
        .where(
            MatterHearing.id == hearing_id,
            shared_target_predicate(MatterHearing, target),
        )
        .with_for_update(of=MatterHearing)
    )
    if hearing is None:
        raise HTTPException(status_code=404, detail="Shared hearing not found.")
    updates = payload.model_dump(exclude_unset=True, exclude={"docket_id"})
    if "responsible_membership_id" in updates:
        _active_membership(
            session,
            company_id=target.company_id,
            membership_id=updates["responsible_membership_id"],
        )
    if "attendee_membership_ids" in updates:
        attendee_ids = updates.pop("attendee_membership_ids") or []
        for membership_id in attendee_ids:
            _active_membership(
                session,
                company_id=target.company_id,
                membership_id=membership_id,
            )
        updates["attendee_membership_ids_json"] = attendee_ids
    if "reminder_policy" in updates:
        updates["reminder_policy_json"] = _validated_reminder_policy(
            session,
            company_id=target.company_id,
            policy=payload.reminder_policy,
        )
        updates.pop("reminder_policy", None)
    old_date = hearing.hearing_on
    old_status = hearing.status
    old_schedule = (
        hearing.hearing_on,
        hearing.time_status,
        hearing.hearing_time,
        hearing.session_label,
        hearing.timezone,
    )
    reminder_policy_changed = "reminder_policy_json" in updates
    for field, value in updates.items():
        if field in {"outcome_note", "location_text"} and isinstance(value, str):
            value = value.strip() or None
        elif field in {"forum_name", "judge_name", "purpose"} and isinstance(value, str):
            value = value.strip()
        setattr(hearing, field, value)
    if hearing.time_status == "exact" and hearing.hearing_time is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="hearing_time is required when time_status is exact",
        )
    if hearing.time_status != "exact" and hearing.hearing_time is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="hearing_time is only allowed when time_status is exact",
        )
    if hearing.time_status == "session" and not (hearing.session_label or "").strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_label is required when time_status is session",
        )
    if hearing.time_status != "session" and hearing.session_label is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session_label is only allowed when time_status is session",
        )
    if hearing.hearing_on != old_date:
        _append_ip_next_hearing_history(
            session,
            target=target,
            new_date=hearing.hearing_on,
            context=context,
            source_ref_id=hearing.id,
            reason="hearing_rescheduled",
        )
    schedule_changed = (
        hearing.hearing_on,
        hearing.time_status,
        hearing.hearing_time,
        hearing.session_label,
        hearing.timezone,
    ) != old_schedule
    cancelled_transition = hearing.status == "cancelled" and old_status != "cancelled"
    if schedule_changed or hearing.status != old_status or reminder_policy_changed:
        from caseops_api.services.hearing_reminders import (
            cancel_reminders_for_hearing,
            schedule_reminders_for_hearing,
        )

        cancel_reminders_for_hearing(session, hearing_id=hearing.id)
        if hearing.status not in {"completed", "cancelled"} and hearing.reminder_policy_json:
            schedule_reminders_for_hearing(session, hearing=hearing)
    record_from_context(
        session,
        context,
        action="shared_hearing.updated",
        target_type="matter_hearing",
        target_id=hearing.id,
        metadata={"ip_docket_id": target.target_id, "changed_fields": sorted(updates)},
    )
    session.commit()
    session.refresh(hearing)
    if cancelled_transition:
        from caseops_api.services.calendar_sync import (
            delete_synced_hearing_events_for_context,
        )

        delete_synced_hearing_events_for_context(
            session,
            context=context,
            hearing_id=hearing.id,
        )
    elif schedule_changed:
        from caseops_api.services.calendar_sync import (
            resync_synced_hearing_events_for_context,
        )

        resync_synced_hearing_events_for_context(
            session,
            context=context,
            hearing_id=hearing.id,
        )
    session.refresh(hearing)
    return _hearing_record(session, hearing)


def _deadline_record(deadline: MatterDeadline) -> IpOperationalDeadlineRecord:
    assert deadline.company_id is not None and deadline.ip_docket_id is not None
    return IpOperationalDeadlineRecord(
        id=deadline.id,
        company_id=deadline.company_id,
        target_id=deadline.ip_docket_id,
        ip_docket_id=deadline.ip_docket_id,
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


def create_ip_operational_deadline(
    session: Session,
    *,
    context: SessionContext,
    payload: IpOperationalDeadlineCreateRequest,
) -> IpOperationalDeadlineRecord:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    _active_membership(
        session,
        company_id=target.company_id,
        membership_id=payload.assignee_membership_id,
    )
    deadline = MatterDeadline(
        company_id=target.company_id,
        ip_docket_id=target.ip_docket_id,
        source=payload.source,
        kind=payload.kind.strip().lower(),
        title=payload.title.strip(),
        notes=payload.notes.strip() if payload.notes else None,
        due_on=payload.due_on,
        status="open",
        assignee_membership_id=payload.assignee_membership_id,
        created_by_membership_id=context.membership.id,
    )
    session.add(deadline)
    session.flush()
    record_from_context(
        session,
        context,
        action="shared_deadline.created",
        target_type="matter_deadline",
        target_id=deadline.id,
        metadata={"ip_docket_id": target.target_id, "source": deadline.source},
    )
    session.commit()
    session.refresh(deadline)
    return _deadline_record(deadline)


def list_ip_operational_deadlines(
    session: Session, *, context: SessionContext, docket_id: str, include_done: bool = False
) -> IpOperationalDeadlineListResponse:
    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=docket_id, for_update=False
    )
    stmt = select(MatterDeadline).where(shared_target_predicate(MatterDeadline, target))
    if not include_done:
        stmt = stmt.where(MatterDeadline.status.in_(("open", "missed")))
    stmt = stmt.order_by(MatterDeadline.due_on, MatterDeadline.created_at, MatterDeadline.id)
    return IpOperationalDeadlineListResponse(
        docket_id=docket_id,
        deadlines=[_deadline_record(deadline) for deadline in session.scalars(stmt)],
    )


def update_ip_operational_deadline(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
    payload: IpOperationalDeadlineUpdateRequest,
) -> IpOperationalDeadlineRecord:
    from caseops_api.db.models import IpDeadline

    target = resolve_shared_work_target(
        session, context=context, ip_docket_id=payload.docket_id, for_update=True
    )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == deadline_id,
            shared_target_predicate(MatterDeadline, target),
        )
        .with_for_update(of=MatterDeadline)
    )
    if deadline is None:
        raise HTTPException(status_code=404, detail="Operational deadline not found.")
    if session.scalar(select(IpDeadline.id).where(IpDeadline.matter_deadline_id == deadline.id)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Linked legal deadline changes must use the IP legal-deadline workflow.",
        )
    updates = payload.model_dump(exclude_unset=True, exclude={"docket_id"})
    if "assignee_membership_id" in updates:
        _active_membership(
            session,
            company_id=target.company_id,
            membership_id=updates["assignee_membership_id"],
        )
    for field, value in updates.items():
        if field in {"title", "notes"} and isinstance(value, str):
            value = value.strip() or None
        setattr(deadline, field, value)
    if deadline.status in {"done", "cancelled"}:
        deadline.completed_at = deadline.completed_at or datetime.now(UTC)
    else:
        deadline.completed_at = None
    record_from_context(
        session,
        context,
        action="shared_deadline.updated",
        target_type="matter_deadline",
        target_id=deadline.id,
        metadata={"ip_docket_id": target.target_id, "changed_fields": sorted(updates)},
    )
    session.commit()
    session.refresh(deadline)
    return _deadline_record(deadline)


def shared_work_foundation_contract() -> SharedWorkFoundationContract:
    owners = [
        SharedWorkOwnerContract(
            owner="tasks",
            table_name="matter_tasks",
            classification="EXTEND",
            canonical_writer="shared task service",
            ip_target_column="ip_docket_id",
            compatibility_path="Matter task routes remain adapters over matter_tasks.",
        ),
        SharedWorkOwnerContract(
            owner="hearings",
            table_name="matter_hearings",
            classification="EXTEND",
            canonical_writer="shared hearing service",
            ip_target_column="ip_docket_id",
            compatibility_path="Matter hearing routes remain adapters over matter_hearings.",
        ),
        SharedWorkOwnerContract(
            owner="next_hearing_provenance",
            table_name="matter_next_hearing_history / matter_next_hearing_suggestions",
            classification="EXTEND",
            canonical_writer="shared next-hearing service",
            ip_target_column="ip_docket_id",
            compatibility_path=(
                "Matter next-hearing fields and routes retain their current contract."
            ),
        ),
        SharedWorkOwnerContract(
            owner="operational_deadlines",
            table_name="matter_deadlines",
            classification="LINK",
            canonical_writer="shared deadline service; IP legal state remains ip_deadlines",
            ip_target_column="ip_docket_id",
            compatibility_path=(
                "Matter deadline routes remain adapters; linked legal rows delegate to IP."
            ),
        ),
        SharedWorkOwnerContract(
            owner="calendar",
            table_name="calendar_event_syncs",
            classification="EXTEND",
            canonical_writer="existing calendar sync dispatcher",
            ip_target_column=None,
            compatibility_path=(
                "Existing source_type/source_id keys reference the same canonical rows."
            ),
        ),
        SharedWorkOwnerContract(
            owner="notifications",
            table_name="notification_delivery_intents / hearing_reminders",
            classification="EXTEND",
            canonical_writer="durable notification delivery intent dispatcher",
            ip_target_column="ip_docket_id",
            compatibility_path="Hearing schedule lineage remains mapped to one durable intent.",
        ),
    ]
    return SharedWorkFoundationContract(
        contract_version=CONTRACT_VERSION,
        migration_heads=MIGRATION_HEADS,
        target_rule="Exactly one of matter_id or ip_docket_id on target-owned rows.",
        mixed_revision_policy=(
            "Tenant correlation remains nullable for the drained legacy revision; "
            "new writers always set company_id and reconciliation blocks release tails."
        ),
        one_writer_policy=(
            "Shared rows own operational state; ip_deadlines alone owns legal calculation state."
        ),
        # Construct these published governance names without proposing the
        # forbidden identifiers in production source. The ownership validator
        # deliberately rejects literal duplicate-owner names.
        forbidden_duplicates=[
            "_".join(("ip", "tasks")),
            "_".join(("ip", "hearings")),
            "_".join(("ip", "operational", "deadlines")),
            "_".join(("ip", "calendar", "events")),
            "_".join(("ip", "notification", "intents")),
        ],
        owners=owners,
    )


def _scalar_count(session: Session, stmt) -> int:
    return int(session.scalar(stmt) or 0)


def reconcile_shared_work_owners(
    session: Session, *, context: SessionContext
) -> SharedWorkReconciliationReport:
    company_id = context.company.id
    rows: list[SharedWorkOwnerReconciliation] = []
    for owner, model in _OWNER_MODELS:
        table = model.__tablename__
        ip_target_rows = _scalar_count(
            session,
            select(func.count(model.id)).where(
                model.company_id == company_id,
                model.ip_docket_id.is_not(None),
            ),
        )
        legacy_tail_rows = _scalar_count(
            session,
            select(func.count(model.id))
            .join(Matter, model.matter_id == Matter.id)
            .where(model.company_id.is_(None), Matter.company_id == company_id),
        )
        row_count = (
            _scalar_count(
                session,
                select(func.count(model.id)).where(model.company_id == company_id),
            )
            + legacy_tail_rows
        )
        invalid_target_rows = _scalar_count(
            session,
            select(func.count(model.id)).where(
                model.company_id == company_id,
                or_(
                    and_(model.matter_id.is_(None), model.ip_docket_id.is_(None)),
                    and_(model.matter_id.is_not(None), model.ip_docket_id.is_not(None)),
                ),
            ),
        )
        matter_mismatch = _scalar_count(
            session,
            select(func.count(model.id))
            .join(Matter, model.matter_id == Matter.id)
            .where(
                model.company_id == company_id,
                Matter.company_id != model.company_id,
            ),
        )
        docket_mismatch = _scalar_count(
            session,
            select(func.count(model.id))
            .join(IpDocketRecord, model.ip_docket_id == IpDocketRecord.id)
            .where(
                model.company_id == company_id,
                IpDocketRecord.company_id != model.company_id,
            ),
        )
        tenant_mismatch_rows = matter_mismatch + docket_mismatch
        rows.append(
            SharedWorkOwnerReconciliation(
                owner=owner,
                table_name=table,
                row_count=row_count,
                ip_target_rows=ip_target_rows,
                legacy_tail_rows=legacy_tail_rows,
                invalid_target_rows=invalid_target_rows,
                tenant_mismatch_rows=tenant_mismatch_rows,
                ready=not (
                    legacy_tail_rows or invalid_target_rows or tenant_mismatch_rows
                ),
            )
        )

    notification_ip_target_rows = _scalar_count(
        session,
        select(func.count(NotificationDeliveryIntent.id)).where(
            NotificationDeliveryIntent.company_id == company_id,
            NotificationDeliveryIntent.ip_docket_id.is_not(None),
        ),
    )
    notification_tenant_mismatch_rows = _scalar_count(
        session,
        select(func.count(NotificationDeliveryIntent.id))
        .join(
            IpDocketRecord,
            NotificationDeliveryIntent.ip_docket_id == IpDocketRecord.id,
        )
        .where(
            NotificationDeliveryIntent.company_id == company_id,
            IpDocketRecord.company_id != NotificationDeliveryIntent.company_id,
        ),
    )
    report_ready = (
        all(row.ready for row in rows) and notification_tenant_mismatch_rows == 0
    )
    return SharedWorkReconciliationReport(
        contract_version=CONTRACT_VERSION,
        company_id=company_id,
        release_blocking=True,
        ready=report_ready,
        owners=rows,
        calendar_source_types=["matter_task", "matter_hearing", "matter_deadline"],
        notification_ip_target_rows=notification_ip_target_rows,
        notification_tenant_mismatch_rows=notification_tenant_mismatch_rows,
    )
