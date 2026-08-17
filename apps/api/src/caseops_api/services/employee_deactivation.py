from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    HearingReminder,
    HearingReminderStatus,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    IpWorkspaceConfiguration,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
    MatterHearing,
    MatterTask,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
)
from caseops_api.services.ip_coverage_projection import (
    tombstone_membership_calendar_projections,
)
from caseops_api.services.session_context import SessionContext

_TERMINAL_DOCKET_STATUSES = ("archived", "abandoned", "transferred", "retired", "closed")


def tombstone_membership_calendar_syncs_before_deactivation(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> int:
    """Durably withdraw every external calendar copy for a fenced leaver."""

    result = tombstone_membership_calendar_projections(
        session,
        company_id=company_id,
        membership_id=membership_id,
        reason="membership_deactivated",
    )
    return len(result.tombstoned_sync_ids)


def _operational_parent_predicate() -> object:
    return and_(
        IpDocketRecord.is_active.is_(True),
        IpDocketRecord.archived_by_matter_disposal.is_(False),
        IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
        or_(
            IpDocketRecord.matter_id.is_(None),
            and_(
                Matter.id.is_not(None),
                Matter.is_active.is_(True),
                Matter.status.notin_(("disposed", "closed")),
            ),
        ),
    )


def _count(session: Session, statement: object) -> int:
    return int(session.scalar(statement) or 0)


def operational_ip_live_reference_counts(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> dict[str, int]:
    """Inventory every bounded live IP role held by one membership.

    Callers hold the membership assignment fence. The parent/lifecycle filters
    deliberately retain immutable terminal history while making this result an
    authoritative pre-deactivation postcondition for operational IP work.
    """

    from caseops_api.services.ip_operations import _coverages_for_member

    context_membership = session.get(CompanyMembership, membership_id)
    if context_membership is None:
        return {}
    context = SessionContext(
        company=context_membership.company,
        user=context_membership.user,
        membership=context_membership,
    )
    counts: dict[str, int] = {}
    operational_deadline_rows = operational_ip_docket_deadlines_for_membership(
        session,
        company_id=company_id,
        membership_id=membership_id,
    )
    counts["ip_docket_deadlines"] = len(
        {deadline.id for deadline, _docket in operational_deadline_rows}
    )
    counts["ip_deadline_coverages"] = len(
        _coverages_for_member(
            session,
            context=context,
            membership_id=membership_id,
            include_auxiliary_roles=True,
        )
    )
    direct_task_count = _count(
        session,
        select(func.count(MatterTask.id))
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.id == MatterTask.ip_docket_id,
                IpDocketRecord.company_id == MatterTask.company_id,
            ),
        )
        .outerjoin(
            Matter,
            and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
        )
        .where(
            MatterTask.company_id == company_id,
            MatterTask.matter_id.is_(None),
            MatterTask.owner_membership_id == membership_id,
            MatterTask.status.notin_(("completed", "cancelled")),
            MatterTask.neutralized_at.is_(None),
            MatterTask.cancelled_by_matter_disposal.is_(False),
            _operational_parent_predicate(),
        ),
    )
    linked_matter_task_count = _count(
        session,
        select(func.count(func.distinct(MatterTask.id)))
        .join(
            Matter,
            and_(
                Matter.id == MatterTask.matter_id,
                Matter.company_id == MatterTask.company_id,
            ),
        )
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.matter_id == Matter.id,
                IpDocketRecord.company_id == Matter.company_id,
            ),
        )
        .where(
            MatterTask.company_id == company_id,
            MatterTask.matter_id.is_not(None),
            MatterTask.owner_membership_id == membership_id,
            MatterTask.status.notin_(("completed", "cancelled")),
            MatterTask.neutralized_at.is_(None),
            MatterTask.cancelled_by_matter_disposal.is_(False),
            _operational_parent_predicate(),
        ),
    )
    counts["ip_docket_tasks"] = direct_task_count + linked_matter_task_count
    direct_hearing_rows = list(
        session.scalars(
            select(MatterHearing)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == MatterHearing.ip_docket_id,
                    IpDocketRecord.company_id == MatterHearing.company_id,
                ),
            )
            .outerjoin(
                Matter,
                and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
            )
            .where(
                MatterHearing.company_id == company_id,
                MatterHearing.matter_id.is_(None),
                MatterHearing.status.in_(("scheduled", "adjourned")),
                MatterHearing.neutralized_at.is_(None),
                MatterHearing.cancelled_by_matter_disposal.is_(False),
                _operational_parent_predicate(),
            )
        )
    )
    linked_matter_hearing_rows = list(
        session.scalars(
            select(MatterHearing)
            .join(
                Matter,
                and_(
                    Matter.id == MatterHearing.matter_id,
                    Matter.company_id == MatterHearing.company_id,
                ),
            )
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.matter_id == Matter.id,
                    IpDocketRecord.company_id == Matter.company_id,
                ),
            )
            .where(
                MatterHearing.company_id == company_id,
                MatterHearing.matter_id.is_not(None),
                MatterHearing.status.in_(("scheduled", "adjourned")),
                MatterHearing.neutralized_at.is_(None),
                MatterHearing.cancelled_by_matter_disposal.is_(False),
                _operational_parent_predicate(),
            )
        ).unique()
    )
    hearing_rows = {
        hearing.id: hearing
        for hearing in (*direct_hearing_rows, *linked_matter_hearing_rows)
    }.values()
    counts["ip_docket_hearings"] = sum(
        (
            hearing.responsible_membership_id == membership_id
            or membership_id in (hearing.attendee_membership_ids_json or [])
            or membership_id
            in ((hearing.reminder_policy_json or {}).get("recipient_membership_ids") or [])
            or (hearing.reminder_policy_json or {}).get("escalation_membership_id")
            == membership_id
        )
        for hearing in hearing_rows
    )
    counts["ip_hearing_reminders"] = _count(
        session,
        select(func.count(HearingReminder.id))
        .join(MatterHearing, MatterHearing.id == HearingReminder.hearing_id)
        .join(IpDocketRecord, IpDocketRecord.id == HearingReminder.ip_docket_id)
        .outerjoin(
            Matter,
            and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
        )
        .where(
            HearingReminder.company_id == company_id,
            HearingReminder.recipient_membership_id == membership_id,
            HearingReminder.status == HearingReminderStatus.QUEUED,
            HearingReminder.neutralized_at.is_(None),
            MatterHearing.status.in_(("scheduled", "adjourned")),
            _operational_parent_predicate(),
        ),
    )
    counts["ip_notification_deliveries"] = len(
        operational_ip_notification_intents_for_membership(
            session,
            company_id=company_id,
            membership_id=membership_id,
        )
    )
    counts["ip_related_right_obligations"] = _count(
        session,
        select(func.count(IpRelatedRightObligation.id))
        .join(IpDocketRecord, IpDocketRecord.id == IpRelatedRightObligation.docket_id)
        .outerjoin(
            Matter,
            and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
        )
        .outerjoin(
            MatterDeadline,
            MatterDeadline.id == IpRelatedRightObligation.matter_deadline_id,
        )
        .where(
            IpRelatedRightObligation.company_id == company_id,
            IpRelatedRightObligation.owner_membership_id == membership_id,
            IpRelatedRightObligation.status == "open",
            _operational_parent_predicate(),
            or_(
                IpRelatedRightObligation.matter_deadline_id.is_(None),
                and_(
                    MatterDeadline.status.in_(
                        (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                    ),
                    MatterDeadline.neutralized_at.is_(None),
                    MatterDeadline.cancelled_by_matter_disposal.is_(False),
                ),
            ),
        ),
    )
    counts["ip_responsibility_assignments"] = _count(
        session,
        select(func.count(IpResponsibilityAssignment.id))
        .join(IpDeadline, IpDeadline.id == IpResponsibilityAssignment.deadline_id)
        .join(IpDocketRecord, IpDocketRecord.id == IpResponsibilityAssignment.docket_id)
        .outerjoin(
            Matter,
            and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
        )
        .where(
            IpResponsibilityAssignment.company_id == company_id,
            IpResponsibilityAssignment.membership_id == membership_id,
            IpResponsibilityAssignment.effective_until.is_(None),
            IpDeadline.state.in_(("confirmed", "overdue")),
            _operational_parent_predicate(),
        ),
    )
    counts["ip_workspace_escalation"] = _count(
        session,
        select(func.count(IpWorkspaceConfiguration.id)).where(
            IpWorkspaceConfiguration.company_id == company_id,
            IpWorkspaceConfiguration.escalation_owner_membership_id == membership_id,
        ),
    )
    counts["ip_linked_matter_roles"] = _count(
        session,
        select(func.count(func.distinct(Matter.id)))
        .join(IpDocketRecord, IpDocketRecord.matter_id == Matter.id)
        .where(
            Matter.company_id == company_id,
            or_(
                Matter.assignee_membership_id == membership_id,
                Matter.responsible_lawyer_membership_id == membership_id,
            ),
            Matter.is_active.is_(True),
            Matter.status.notin_(("disposed", "closed")),
            IpDocketRecord.company_id == company_id,
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
        ),
    )
    return {key: value for key, value in counts.items() if value}


def operational_ip_docket_deadlines_for_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> list[tuple[MatterDeadline, IpDocketRecord]]:
    """Return every operational IP-owned/covered deadline assigned to a member."""

    rows: dict[tuple[str, str], tuple[MatterDeadline, IpDocketRecord]] = {}
    direct_rows = list(
        session.execute(
            select(MatterDeadline, IpDocketRecord)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == MatterDeadline.ip_docket_id,
                    IpDocketRecord.company_id == MatterDeadline.company_id,
                ),
            )
            .outerjoin(
                Matter,
                and_(
                    Matter.id == IpDocketRecord.matter_id,
                    Matter.company_id == IpDocketRecord.company_id,
                ),
            )
            .where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.matter_id.is_(None),
                MatterDeadline.assignee_membership_id == membership_id,
                MatterDeadline.status.in_((MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                IpDocketRecord.company_id == company_id,
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.id.is_not(None),
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
            )
            .order_by(IpDocketRecord.id, MatterDeadline.id)
        ).all()
    )
    for deadline, docket in direct_rows:
        rows[(deadline.id, docket.id)] = (deadline, docket)

    linked_matter_rows = list(
        session.execute(
            select(MatterDeadline, IpDocketRecord)
            .join(
                Matter,
                and_(
                    Matter.id == MatterDeadline.matter_id,
                    Matter.company_id == MatterDeadline.company_id,
                ),
            )
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.matter_id == Matter.id,
                    IpDocketRecord.company_id == Matter.company_id,
                ),
            )
            .where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.matter_id.is_not(None),
                MatterDeadline.ip_docket_id.is_(None),
                MatterDeadline.assignee_membership_id == membership_id,
                MatterDeadline.status.in_(
                    (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                ),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                _operational_parent_predicate(),
            )
            .order_by(IpDocketRecord.id, MatterDeadline.id)
        ).all()
    )
    for deadline, docket in linked_matter_rows:
        rows[(deadline.id, docket.id)] = (deadline, docket)

    coverage_rows = list(
        session.execute(
            select(MatterDeadline, IpDocketRecord)
            .join(
                IpDeadlineCoverage,
                IpDeadlineCoverage.matter_deadline_id == MatterDeadline.id,
            )
            .join(IpDocketRecord, IpDocketRecord.id == IpDeadlineCoverage.docket_id)
            .outerjoin(
                Matter,
                and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
            )
            .where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.assignee_membership_id == membership_id,
                MatterDeadline.status.in_(
                    (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                ),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.coverage_status.notin_(("inactive_lifecycle", "completed")),
                _operational_parent_predicate(),
            )
            .order_by(IpDocketRecord.id, MatterDeadline.id)
        ).all()
    )
    for deadline, docket in coverage_rows:
        rows[(deadline.id, docket.id)] = (deadline, docket)

    legal_rows = list(
        session.execute(
            select(MatterDeadline, IpDocketRecord)
            .join(IpDeadline, IpDeadline.matter_deadline_id == MatterDeadline.id)
            .join(IpDocketRecord, IpDocketRecord.id == IpDeadline.docket_id)
            .outerjoin(
                Matter,
                and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
            )
            .where(
                MatterDeadline.company_id == company_id,
                MatterDeadline.assignee_membership_id == membership_id,
                MatterDeadline.status.in_(
                    (MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)
                ),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                IpDeadline.company_id == company_id,
                IpDeadline.state.in_(("confirmed", "overdue")),
                _operational_parent_predicate(),
            )
            .order_by(IpDocketRecord.id, MatterDeadline.id)
        ).all()
    )
    for deadline, docket in legal_rows:
        rows[(deadline.id, docket.id)] = (deadline, docket)
    return sorted(rows.values(), key=lambda item: (item[1].id, item[0].id))


def operational_ip_notification_intents_for_membership(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
) -> list[tuple[NotificationDeliveryIntent, IpDocketRecord]]:
    """Resolve live IP delivery participants through either supported linkage shape."""

    role_predicate = or_(
        NotificationDeliveryIntent.recipient_membership_id == membership_id,
        NotificationDeliveryIntent.escalation_membership_id == membership_id,
    )
    status_predicate = NotificationDeliveryIntent.status.in_(
        (NotificationDeliveryStatus.QUEUED, NotificationDeliveryStatus.RETRY_SCHEDULED)
    )
    rows: dict[str, tuple[NotificationDeliveryIntent, IpDocketRecord]] = {}
    direct_rows = list(
        session.execute(
            select(NotificationDeliveryIntent, IpDocketRecord)
            .join(IpDocketRecord, IpDocketRecord.id == NotificationDeliveryIntent.ip_docket_id)
            .outerjoin(
                Matter,
                and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
            )
            .where(
                NotificationDeliveryIntent.company_id == company_id,
                role_predicate,
                status_predicate,
                NotificationDeliveryIntent.neutralized_at.is_(None),
                _operational_parent_predicate(),
            )
        ).all()
    )
    for intent, docket in direct_rows:
        rows[intent.id] = (intent, docket)
    legal_rows = list(
        session.execute(
            select(NotificationDeliveryIntent, IpDocketRecord)
            .join(
                IpDeadline,
                and_(
                    NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                    NotificationDeliveryIntent.schedule_source_id == IpDeadline.id,
                ),
            )
            .join(IpDocketRecord, IpDocketRecord.id == IpDeadline.docket_id)
            .outerjoin(
                Matter,
                and_(Matter.id == IpDocketRecord.matter_id, Matter.company_id == company_id),
            )
            .where(
                NotificationDeliveryIntent.company_id == company_id,
                role_predicate,
                status_predicate,
                NotificationDeliveryIntent.neutralized_at.is_(None),
                IpDeadline.company_id == company_id,
                IpDeadline.state.in_(("confirmed", "overdue")),
                _operational_parent_predicate(),
            )
        ).all()
    )
    for intent, docket in legal_rows:
        rows[intent.id] = (intent, docket)
    return sorted(rows.values(), key=lambda item: item[0].id)


def assert_no_operational_ip_work_before_deactivation(
    session: Session,
    *,
    context: SessionContext,
    membership: CompanyMembership,
) -> None:
    """Require the atomic offboarding workflow when active IP work exists.

    The caller must already hold ``membership`` through the shared assignment
    fence. Every writer that can add one of these roles takes the same fence
    first, making this check authoritative through the caller's commit.
    """

    counts = operational_ip_live_reference_counts(
        session,
        company_id=context.company.id,
        membership_id=membership.id,
    )
    if not counts:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "employee_offboarding_required",
            "message": (
                "This employee has operational IP work. Use employee offboarding "
                "to reassign it before deactivation."
            ),
            "live_reference_counts": counts,
        },
    )
