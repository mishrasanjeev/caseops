"""Single-writer renewal workflow and operational projection."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Communication,
    CompanyMembership,
    IpClientInstruction,
    IpCostItem,
    IpDeadline,
    IpDocketEvent,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentVersion,
    IpRenewalTerm,
    IpResponsibilityAssignment,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
)
from caseops_api.schemas.ip_renewals import (
    IpClientInstructionAcknowledgeRequest,
    IpClientInstructionCreateRequest,
    IpClientInstructionRecord,
    IpRenewalDeadlineSummary,
    IpRenewalFeeSummary,
    IpRenewalFoundationContract,
    IpRenewalPortfolioCounts,
    IpRenewalPortfolioResponse,
    IpRenewalReminderIntentRecord,
    IpRenewalReminderScheduleRequest,
    IpRenewalReminderScheduleResponse,
    IpRenewalReminderSummary,
    IpRenewalTermCreateRequest,
    IpRenewalTermListResponse,
    IpRenewalTermRecord,
    IpRenewalTermTransitionRequest,
    IpRenewalWorkflowRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import visible_ip_dockets_filter
from caseops_api.services.notification_delivery import (
    cancel_pending_notification_intents,
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext

_CONFIRMED_DEADLINE_STATES = {"confirmed", "overdue"}
_FILING_EVENT_KINDS = {"filing", "renewal_filing"}
_ACCEPTANCE_EVENT_KINDS = {"acceptance", "renewal_acceptance"}
_TRANSITIONS: dict[str, set[str]] = {
    "due": {"instructed", "filing_in_progress", "filed", "grace", "overdue", "cancelled"},
    "instructed": {"filing_in_progress", "filed", "grace", "overdue", "cancelled"},
    "filing_in_progress": {"filed", "grace", "overdue", "cancelled"},
    "filed": {"accepted", "grace", "overdue", "cancelled"},
    "accepted": {"completed", "cancelled"},
    "grace": {"filing_in_progress", "filed", "overdue", "cancelled"},
    "overdue": {"filing_in_progress", "filed", "grace", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
_REMINDER_SCHEDULE_SOURCE = "ip_renewal_term"
_REMINDER_RECIPIENT_ROLES = {"primary", "backup"}
_ESCALATION_RECIPIENT_ROLES = {"supervisor", "docketing"}
_REMINDER_TERMINAL_STATES = {
    "filing_in_progress",
    "filed",
    "accepted",
    "completed",
    "cancelled",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _assert_reference_unchanged(
    *, current: str | None, proposed: str | None, label: str
) -> None:
    if current is not None and proposed is not None and current != proposed:
        raise _conflict(
            "ip_renewal_evidence_immutable",
            f"Recorded {label} evidence cannot be replaced; use the legal-event correction flow.",
        )


def _docket(session: Session, context: SessionContext, docket_id: str, *, write: bool):
    from caseops_api.services.ip_operations import _docket_or_404

    return _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=write,
        required_capability="ip:write",
    )


def _term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    write: bool,
) -> tuple[object, IpRenewalTerm]:
    docket = _docket(session, context, docket_id, write=write)
    statement = select(IpRenewalTerm).where(
        IpRenewalTerm.id == term_id,
        IpRenewalTerm.company_id == context.company.id,
        IpRenewalTerm.docket_id == docket.id,
    )
    if write:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = session.scalar(statement)
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal term not found.")
    return docket, row


def _event(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    event_id: str,
    kinds: set[str],
    label: str,
) -> IpDocketEvent:
    row = session.scalar(
        select(IpDocketEvent).where(
            IpDocketEvent.id == event_id,
            IpDocketEvent.company_id == context.company.id,
            IpDocketEvent.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} event not found.")
    if row.candidate_status != "confirmed" or row.event_kind not in kinds:
        raise _conflict(
            "ip_renewal_event_not_verified",
            f"{label} must be a confirmed {', '.join(sorted(kinds))} event.",
        )
    return row


def _deadline(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    deadline_id: str,
    kind: str,
    label: str,
) -> IpDeadline:
    row = session.scalar(
        select(IpDeadline).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == context.company.id,
            IpDeadline.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} deadline not found.")
    if row.state not in _CONFIRMED_DEADLINE_STATES or row.deadline_kind != kind:
        raise _conflict(
            "ip_renewal_deadline_not_confirmed",
            f"{label} must be a confirmed {kind} legal deadline.",
        )
    return row


def _cost_item(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    cost_item_id: str,
) -> IpCostItem:
    row = session.scalar(
        select(IpCostItem).where(
            IpCostItem.id == cost_item_id,
            IpCostItem.company_id == context.company.id,
            IpCostItem.docket_id == docket_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal fee cost item not found.")
    return row


def _document(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    document_id: str,
) -> IpDocument:
    row = session.scalar(
        select(IpDocument).where(
            IpDocument.id == document_id,
            IpDocument.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="IP renewal certificate not found.")
    current_version = session.scalar(
        select(IpDocumentVersion).where(
            IpDocumentVersion.company_id == context.company.id,
            IpDocumentVersion.document_id == row.id,
            IpDocumentVersion.version == row.current_version,
        )
    )
    linked = session.scalar(
        select(IpDocumentLink.id).where(
            IpDocumentLink.company_id == context.company.id,
            IpDocumentLink.document_id == row.id,
            IpDocumentLink.docket_id == docket_id,
        )
    )
    if current_version is None or current_version.state != "accepted" or linked is None:
        raise _conflict(
            "ip_renewal_certificate_not_accepted",
            "The certificate must be an accepted current IP document linked to this docket.",
        )
    return row


def _instructions(
    session: Session, *, company_id: str, term_id: str
) -> list[IpClientInstruction]:
    return list(
        session.scalars(
            select(IpClientInstruction)
            .where(
                IpClientInstruction.company_id == company_id,
                IpClientInstruction.renewal_term_id == term_id,
            )
            .order_by(IpClientInstruction.instruction_version)
        ).all()
    )


def _record(session: Session, row: IpRenewalTerm) -> IpRenewalTermRecord:
    return IpRenewalTermRecord.model_validate(row).model_copy(
        update={
            "instructions": [
                IpClientInstructionRecord.model_validate(instruction)
                for instruction in _instructions(
                    session, company_id=row.company_id, term_id=row.id
                )
            ]
        }
    )


def _deadline_summary(row: IpDeadline) -> IpRenewalDeadlineSummary:
    return IpRenewalDeadlineSummary(
        id=row.id,
        title=row.title,
        deadline_kind=row.deadline_kind,
        result_on=row.result_on,
        result_at=row.result_at,
        state=row.state,
        certainty=row.certainty,
        rule_citation=row.rule_citation,
        source_version=row.source_version,
        explanation=row.explanation,
    )


def _deadline_date(row: IpDeadline) -> date | None:
    if row.result_on is not None:
        return row.result_on
    if row.result_at is not None:
        return _aware(row.result_at).date()
    return None


def _calendar_phase(
    *, renewal_deadline: IpDeadline, grace_deadline: IpDeadline | None, today: date
) -> str:
    renewal_on = _deadline_date(renewal_deadline)
    grace_on = _deadline_date(grace_deadline) if grace_deadline is not None else None
    if renewal_on is None or today <= renewal_on:
        return "due"
    if grace_on is not None and today <= grace_on:
        return "grace"
    return "overdue"


def _reporting_state(term: IpRenewalTerm, calendar_phase: str) -> str:
    if term.state in {"due", "instructed"} and calendar_phase in {"grace", "overdue"}:
        return calendar_phase
    return term.state


def _action_required(
    *, term: IpRenewalTerm, instructions: list[IpClientInstruction], reporting_state: str
) -> str:
    if term.state in {"completed", "cancelled"}:
        return "none"
    current = next(
        (row for row in reversed(instructions) if row.status != "superseded"),
        None,
    )
    if reporting_state == "overdue" and term.state in {"due", "instructed"}:
        return "resolve_overdue_term"
    if reporting_state == "grace" and term.state in {"due", "instructed"}:
        return "resolve_grace_period"
    if current is None:
        return "request_instruction"
    if current.status == "pending":
        return "review_instruction"
    if term.state == "instructed":
        return "record_filing_initiation"
    if term.state == "filing_in_progress":
        return "record_filing"
    if term.state == "filed":
        return "record_registry_acceptance"
    if term.state == "accepted":
        return "record_certificate_and_next_term"
    if term.state == "grace":
        return "resolve_grace_period"
    if term.state == "overdue":
        return "resolve_overdue_term"
    return "request_instruction"


def _reminder_summary(intents: list[NotificationDeliveryIntent]) -> IpRenewalReminderSummary:
    queued_statuses = {
        str(NotificationDeliveryStatus.QUEUED),
        str(NotificationDeliveryStatus.RETRY_SCHEDULED),
    }
    delivered_statuses = {
        str(NotificationDeliveryStatus.SENT),
        str(NotificationDeliveryStatus.DELIVERED),
    }
    cancelled_status = str(NotificationDeliveryStatus.CANCELLED)
    queued = [row for row in intents if str(row.status) in queued_statuses]
    delivered = [row for row in intents if str(row.status) in delivered_statuses]
    failed = [
        row
        for row in intents
        if str(row.status) not in queued_statuses | delivered_statuses | {cancelled_status}
    ]
    next_scheduled = min(
        (row.scheduled_for for row in queued if row.scheduled_for is not None),
        default=None,
    )
    last_delivered = max(
        (row.delivered_at for row in delivered if row.delivered_at is not None),
        default=None,
    )
    return IpRenewalReminderSummary(
        total=len(intents),
        queued=len(queued),
        sent_or_delivered=len(delivered),
        cancelled=sum(str(row.status) == cancelled_status for row in intents),
        blocked_or_failed=len(failed),
        next_scheduled_for=next_scheduled,
        last_delivered_at=last_delivered,
    )


def _fee_summary(row: IpCostItem | None) -> IpRenewalFeeSummary | None:
    if row is None:
        return None
    return IpRenewalFeeSummary(
        id=row.id,
        category=row.category,
        description=row.description,
        cost_nature=row.cost_nature,
        billable=row.billable,
        evidence_reference=row.evidence_reference,
        billing_link_type=row.billing_link_type,
        billing_link_id=row.billing_link_id,
        reconciliation_status=row.reconciliation_status,
        reconciled_at=row.reconciled_at,
    )


def _workflow_record(
    session: Session,
    *,
    docket: IpDocketRecord,
    term: IpRenewalTerm,
    deadline_by_id: dict[str, IpDeadline],
    cost_by_id: dict[str, IpCostItem],
    reminders_by_term: dict[str, list[NotificationDeliveryIntent]],
    today: date,
) -> IpRenewalWorkflowRecord:
    renewal_deadline = deadline_by_id[term.renewal_deadline_id]
    grace_deadline = (
        deadline_by_id.get(term.grace_deadline_id) if term.grace_deadline_id else None
    )
    instructions = _instructions(session, company_id=term.company_id, term_id=term.id)
    phase = (
        "closed"
        if term.state in {"completed", "cancelled"}
        else _calendar_phase(
            renewal_deadline=renewal_deadline,
            grace_deadline=grace_deadline,
            today=today,
        )
    )
    reporting_state = term.state if phase == "closed" else _reporting_state(term, phase)
    renewal_on = _deadline_date(renewal_deadline)
    grace_on = _deadline_date(grace_deadline) if grace_deadline is not None else None
    return IpRenewalWorkflowRecord(
        docket_id=docket.id,
        docket_title=docket.title,
        primary_identifier=docket.primary_identifier,
        record_type=docket.record_type,
        term=_record(session, term),
        renewal_deadline=_deadline_summary(renewal_deadline),
        grace_deadline=_deadline_summary(grace_deadline) if grace_deadline else None,
        fee=_fee_summary(cost_by_id.get(term.fee_cost_item_id or "")),
        reporting_state=reporting_state,
        calendar_phase=phase,
        action_required=_action_required(
            term=term,
            instructions=instructions,
            reporting_state=reporting_state,
        ),
        days_until_renewal=(renewal_on - today).days if renewal_on else None,
        days_until_grace_end=(grace_on - today).days if grace_on else None,
        state_reconciliation_required=(
            reporting_state != term.state and term.state not in {"completed", "cancelled"}
        ),
        reminders=_reminder_summary(reminders_by_term.get(term.id, [])),
    )


def list_renewal_portfolio(
    session: Session, *, context: SessionContext
) -> IpRenewalPortfolioResponse:
    dockets = list(
        session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                visible_ip_dockets_filter(session, context=context),
            )
        ).all()
    )
    docket_by_id = {row.id: row for row in dockets}
    if not docket_by_id:
        return IpRenewalPortfolioResponse(
            generated_at=_now(), items=[], counts=IpRenewalPortfolioCounts()
        )
    terms = list(
        session.scalars(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id.in_(sorted(docket_by_id)),
            )
            .order_by(IpRenewalTerm.updated_at.desc(), IpRenewalTerm.id)
        ).all()
    )
    deadline_ids = {
        deadline_id
        for term in terms
        for deadline_id in (term.renewal_deadline_id, term.grace_deadline_id)
        if deadline_id
    }
    deadlines = list(
        session.scalars(
            select(IpDeadline).where(
                IpDeadline.company_id == context.company.id,
                IpDeadline.id.in_(sorted(deadline_ids)),
            )
        ).all()
    )
    deadline_by_id = {row.id: row for row in deadlines}
    cost_ids = {term.fee_cost_item_id for term in terms if term.fee_cost_item_id}
    costs = list(
        session.scalars(
            select(IpCostItem).where(
                IpCostItem.company_id == context.company.id,
                IpCostItem.id.in_(sorted(cost_ids)),
            )
        ).all()
    ) if cost_ids else []
    cost_by_id = {row.id: row for row in costs}
    intents = list(
        session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type == _REMINDER_SCHEDULE_SOURCE,
                NotificationDeliveryIntent.schedule_source_id.in_(
                    [term.id for term in terms]
                ),
            )
        ).all()
    ) if terms else []
    reminders_by_term: dict[str, list[NotificationDeliveryIntent]] = {}
    for intent in intents:
        reminders_by_term.setdefault(str(intent.schedule_source_id), []).append(intent)
    today = date.today()
    items = [
        _workflow_record(
            session,
            docket=docket_by_id[term.docket_id],
            term=term,
            deadline_by_id=deadline_by_id,
            cost_by_id=cost_by_id,
            reminders_by_term=reminders_by_term,
            today=today,
        )
        for term in terms
        if term.renewal_deadline_id in deadline_by_id
    ]
    counts = Counter(row.reporting_state for row in items)
    return IpRenewalPortfolioResponse(
        generated_at=_now(),
        items=items,
        counts=IpRenewalPortfolioCounts(
            total=len(items),
            action_required=sum(row.action_required != "none" for row in items),
            **{state: counts[state] for state in _TRANSITIONS},
        ),
    )


def _cancel_renewal_reminders(
    session: Session, *, company_id: str, term_id: str, reason: str
) -> int:
    return cancel_pending_notification_intents(
        session,
        company_id=company_id,
        schedule_source_type=_REMINDER_SCHEDULE_SOURCE,
        schedule_source_id=term_id,
        cancellation_reason=reason,
    )


def _scheduled_at(deadline_on: date, *, offset_days: int) -> datetime:
    # 09:00 IST expressed in UTC. The legal date remains authoritative; this
    # timestamp only controls when the operational in-app reminder appears.
    return datetime.combine(
        deadline_on - timedelta(days=offset_days),
        time(hour=3, minute=30),
        tzinfo=UTC,
    )


def schedule_renewal_instruction_reminders(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    payload: IpRenewalReminderScheduleRequest,
) -> IpRenewalReminderScheduleResponse:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    if (
        term.state != payload.expected_state
        or term.version != payload.expected_version
        or _aware(term.updated_at) != _aware(payload.expected_updated_at)
    ):
        raise _conflict(
            "ip_renewal_term_stale",
            "The renewal term changed; refresh before scheduling reminders.",
        )
    if term.state in _REMINDER_TERMINAL_STATES:
        raise _conflict(
            "ip_renewal_reminders_not_applicable",
            "Instruction reminders are not applicable after filing starts or the term closes.",
        )
    current_instruction = session.scalar(
        select(IpClientInstruction.id).where(
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.renewal_term_id == term.id,
            IpClientInstruction.status != "superseded",
        )
    )
    if current_instruction is not None:
        raise _conflict(
            "ip_renewal_instruction_already_received",
            "An instruction is already recorded; review it instead of sending a "
            "no-instruction reminder.",
        )
    renewal_deadline = _deadline(
        session,
        context=context,
        docket_id=docket.id,
        deadline_id=term.renewal_deadline_id,
        kind="renewal",
        label="Renewal",
    )
    renewal_on = _deadline_date(renewal_deadline)
    if renewal_on is None:
        raise _conflict(
            "ip_renewal_deadline_date_required",
            "The confirmed renewal deadline has no reportable date.",
        )
    now = _now()
    assignments = list(
        session.scalars(
            select(IpResponsibilityAssignment)
            .where(
                IpResponsibilityAssignment.company_id == context.company.id,
                IpResponsibilityAssignment.docket_id == docket.id,
                IpResponsibilityAssignment.deadline_id == renewal_deadline.id,
                IpResponsibilityAssignment.effective_from <= now,
                or_(
                    IpResponsibilityAssignment.effective_until.is_(None),
                    IpResponsibilityAssignment.effective_until > now,
                ),
            )
            .order_by(IpResponsibilityAssignment.role, IpResponsibilityAssignment.id)
        ).all()
    )
    recipient_assignments = [
        row for row in assignments if row.role in _REMINDER_RECIPIENT_ROLES
    ]
    escalation_assignments = [
        row for row in assignments if row.role in _ESCALATION_RECIPIENT_ROLES
    ]
    if not recipient_assignments:
        raise _conflict(
            "ip_renewal_responsibility_required",
            "Assign an active primary or backup owner to the renewal deadline first.",
        )
    membership_ids = {
        row.membership_id for row in recipient_assignments + escalation_assignments
    }
    memberships = {
        row.id: row
        for row in session.scalars(
            select(CompanyMembership).where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id.in_(sorted(membership_ids)),
                CompanyMembership.is_active.is_(True),
            )
        ).all()
    }
    active_recipients = [
        row for row in recipient_assignments if row.membership_id in memberships
    ]
    if not active_recipients:
        raise _conflict(
            "ip_renewal_responsibility_required",
            "The renewal deadline has no active primary or backup owner.",
        )
    role_by_membership = {
        row.membership_id: row.role
        for row in recipient_assignments + escalation_assignments
        if row.membership_id in memberships
    }
    label_by_membership = {
        row.membership_id: row.membership_label_snapshot
        for row in recipient_assignments + escalation_assignments
    }
    existing_ids = set(
        session.scalars(
            select(NotificationDeliveryIntent.id).where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type
                == _REMINDER_SCHEDULE_SOURCE,
                NotificationDeliveryIntent.schedule_source_id == term.id,
            )
        ).all()
    )
    planned: list[tuple[IpResponsibilityAssignment, str, datetime, bool]] = []
    for assignment in active_recipients:
        planned.append((assignment, "renewal_instruction_requested", now, False))
        for offset in payload.reminder_offsets_days:
            scheduled_for = _scheduled_at(renewal_on, offset_days=offset)
            if scheduled_for > now:
                planned.append(
                    (
                        assignment,
                        f"renewal_instruction_{offset}d",
                        scheduled_for,
                        offset <= 7,
                    )
                )
    escalation_at = max(_scheduled_at(renewal_on, offset_days=0), now)
    for assignment in escalation_assignments:
        if assignment.membership_id in memberships:
            planned.append(
                (
                    assignment,
                    "renewal_no_instruction_escalation",
                    escalation_at,
                    True,
                )
            )
    for assignment, event_type, scheduled_for, critical in planned:
        recipient = memberships[assignment.membership_id]
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel="in_app",
            event_type=event_type,
            source_type=_REMINDER_SCHEDULE_SOURCE,
            source_id=term.id,
            ip_docket=docket,
            title="Trademark renewal instruction required",
            body=(
                f"{docket.title} renewal is due {renewal_on.isoformat()}. "
                "Record and verify the client's instruction in CaseOps."
            ),
            scheduled_for=scheduled_for,
            critical=critical,
            schedule_source_type=_REMINDER_SCHEDULE_SOURCE,
            schedule_source_id=term.id,
        )
        if intent is not None and scheduled_for <= now:
            process_notification_delivery_intent(
                session,
                intent_id=intent.id,
                context=context,
            )
    rows = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type
                == _REMINDER_SCHEDULE_SOURCE,
                NotificationDeliveryIntent.schedule_source_id == term.id,
            )
            .order_by(
                NotificationDeliveryIntent.scheduled_for,
                NotificationDeliveryIntent.id,
            )
        ).all()
    )
    record_from_context(
        session,
        context,
        action="ip_renewal_term.instruction_reminders_scheduled",
        target_type="ip_renewal_term",
        target_id=term.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "deadline_id": renewal_deadline.id,
            "offsets_days": payload.reminder_offsets_days,
            "intent_count": len(rows),
            "recipient_membership_ids": sorted(role_by_membership),
        },
    )
    session.commit()
    return IpRenewalReminderScheduleResponse(
        term_id=term.id,
        created_count=sum(row.id not in existing_ids for row in rows),
        existing_count=sum(row.id in existing_ids for row in rows),
        intents=[
            IpRenewalReminderIntentRecord(
                id=row.id,
                recipient_membership_id=row.recipient_membership_id,
                recipient_label=label_by_membership.get(
                    str(row.recipient_membership_id), "Assigned renewal owner"
                ),
                role=role_by_membership.get(
                    str(row.recipient_membership_id), "assigned"
                ),
                event_type=row.event_type,
                status=str(row.status),
                scheduled_for=row.scheduled_for,
                delivered_at=row.delivered_at,
            )
            for row in rows
        ],
    )


def renewal_foundation_contract() -> IpRenewalFoundationContract:
    return IpRenewalFoundationContract()


def list_renewal_terms(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpRenewalTermListResponse:
    docket = _docket(session, context, docket_id, write=False)
    rows = list(
        session.scalars(
            select(IpRenewalTerm)
            .where(
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id == docket.id,
            )
            .order_by(IpRenewalTerm.term_sequence, IpRenewalTerm.id)
        ).all()
    )
    return IpRenewalTermListResponse(
        items=[_record(session, row) for row in rows], total=len(rows)
    )


def create_renewal_term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpRenewalTermCreateRequest,
) -> IpRenewalTermRecord:
    docket = _docket(session, context, docket_id, write=True)
    _event(
        session,
        context=context,
        docket_id=docket.id,
        event_id=payload.registration_event_id,
        kinds={"registration"},
        label="Registration",
    )
    _deadline(
        session,
        context=context,
        docket_id=docket.id,
        deadline_id=payload.renewal_deadline_id,
        kind="renewal",
        label="Renewal",
    )
    if payload.grace_deadline_id:
        _deadline(
            session,
            context=context,
            docket_id=docket.id,
            deadline_id=payload.grace_deadline_id,
            kind="renewal_grace",
            label="Grace-period",
        )
    if payload.fee_cost_item_id:
        _cost_item(
            session,
            context=context,
            docket_id=docket.id,
            cost_item_id=payload.fee_cost_item_id,
        )
    duplicate = session.scalar(
        select(IpRenewalTerm.id).where(
            IpRenewalTerm.company_id == context.company.id,
            IpRenewalTerm.docket_id == docket.id,
            IpRenewalTerm.registration_event_id == payload.registration_event_id,
            IpRenewalTerm.renewal_deadline_id == payload.renewal_deadline_id,
        )
    )
    if duplicate is not None:
        raise _conflict(
            "ip_renewal_term_exists",
            "A renewal term already exists for this registration event and deadline.",
        )
    next_sequence = int(
        session.scalar(
            select(func.coalesce(func.max(IpRenewalTerm.term_sequence), 0)).where(
                IpRenewalTerm.company_id == context.company.id,
                IpRenewalTerm.docket_id == docket.id,
            )
        )
        or 0
    ) + 1
    row = IpRenewalTerm(
        company_id=context.company.id,
        docket_id=docket.id,
        term_sequence=next_sequence,
        registration_event_id=payload.registration_event_id,
        renewal_deadline_id=payload.renewal_deadline_id,
        grace_deadline_id=payload.grace_deadline_id,
        fee_cost_item_id=payload.fee_cost_item_id,
        state="due",
        version=1,
        created_by_membership_id=context.membership.id,
        updated_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="ip_renewal_term.created",
        target_type="ip_renewal_term",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "registration_event_id": row.registration_event_id,
            "renewal_deadline_id": row.renewal_deadline_id,
            "grace_deadline_id": row.grace_deadline_id,
        },
    )
    session.commit()
    session.refresh(row)
    return _record(session, row)


def create_client_instruction(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    payload: IpClientInstructionCreateRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    if term.state in {"completed", "cancelled"}:
        raise _conflict(
            "ip_renewal_term_terminal",
            "A terminal renewal term cannot receive a new client instruction.",
        )
    current = session.scalar(
        select(IpClientInstruction)
        .where(
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.renewal_term_id == term.id,
            IpClientInstruction.status != "superseded",
        )
        .order_by(IpClientInstruction.instruction_version.desc())
        .with_for_update()
    )
    if current is None:
        if payload.expected_current_instruction_id is not None:
            raise _conflict(
                "ip_client_instruction_stale",
                "No current client instruction exists; refresh and retry.",
            )
        instruction_version = 1
    else:
        if (
            payload.expected_current_instruction_id != current.id
            or payload.expected_current_row_version != current.row_version
        ):
            raise _conflict(
                "ip_client_instruction_stale",
                "The current client instruction changed; refresh before creating a revision.",
            )
        current.status = "superseded"
        current.row_version += 1
        current.updated_at = _now()
        instruction_version = current.instruction_version + 1
    if payload.source_communication_id:
        communication = session.scalar(
            select(Communication).where(
                Communication.id == payload.source_communication_id,
                Communication.company_id == context.company.id,
            )
        )
        if communication is None:
            raise HTTPException(status_code=404, detail="Source communication not found.")
    row = IpClientInstruction(
        company_id=context.company.id,
        docket_id=term.docket_id,
        renewal_term_id=term.id,
        instruction_version=instruction_version,
        row_version=1,
        decision=payload.decision,
        status="pending",
        scope_json=payload.scope,
        options_json=payload.options,
        instruction_deadline_at=payload.instruction_deadline_at,
        source_channel=payload.source_channel.strip(),
        source_communication_id=payload.source_communication_id,
        authority_name=payload.authority_name.strip(),
        authority_reference=(
            payload.authority_reference.strip() if payload.authority_reference else None
        ),
        evidence_refs_json=[reference.strip() for reference in payload.evidence_refs],
        received_at=payload.received_at,
        supersedes_instruction_id=current.id if current is not None else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.flush()
    cancelled_reminders = _cancel_renewal_reminders(
        session,
        company_id=context.company.id,
        term_id=term.id,
        reason="renewal_instruction_received",
    )
    record_from_context(
        session,
        context,
        action="ip_client_instruction.created",
        target_type="ip_client_instruction",
        target_id=row.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "renewal_term_id": term.id,
            "instruction_version": row.instruction_version,
            "decision": row.decision,
            "supersedes_instruction_id": row.supersedes_instruction_id,
            "cancelled_reminder_count": cancelled_reminders,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)


def acknowledge_client_instruction(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    instruction_id: str,
    payload: IpClientInstructionAcknowledgeRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    instruction = session.scalar(
        select(IpClientInstruction)
        .where(
            IpClientInstruction.id == instruction_id,
            IpClientInstruction.company_id == context.company.id,
            IpClientInstruction.docket_id == docket.id,
            IpClientInstruction.renewal_term_id == term.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if instruction is None:
        raise HTTPException(status_code=404, detail="Client instruction not found.")
    if (
        instruction.status != payload.expected_status
        or instruction.row_version != payload.expected_row_version
        or _aware(instruction.updated_at) != _aware(payload.expected_updated_at)
    ):
        raise _conflict(
            "ip_client_instruction_stale",
            "The client instruction changed; refresh before acknowledging it.",
        )
    if payload.resulting_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.resulting_event_id,
            kinds={"client_instruction"},
            label="Resulting instruction",
        )
    now = _now()
    instruction.status = payload.status
    instruction.row_version += 1
    instruction.acknowledged_at = now
    instruction.acknowledged_by_membership_id = context.membership.id
    instruction.acknowledgement_reason = payload.reason.strip()
    instruction.resulting_event_id = payload.resulting_event_id
    instruction.updated_at = now
    if (
        payload.status == "accepted"
        and instruction.decision == "renew"
        and term.state == "due"
    ):
        term.state = "instructed"
        term.version += 1
        term.updated_by_membership_id = context.membership.id
        term.updated_at = now
    record_from_context(
        session,
        context,
        action=f"ip_client_instruction.{payload.status}",
        target_type="ip_client_instruction",
        target_id=instruction.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "renewal_term_id": term.id,
            "instruction_version": instruction.instruction_version,
            "decision": instruction.decision,
            "resulting_event_id": instruction.resulting_event_id,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)


def transition_renewal_term(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    term_id: str,
    payload: IpRenewalTermTransitionRequest,
) -> IpRenewalTermRecord:
    docket, term = _term(
        session,
        context=context,
        docket_id=docket_id,
        term_id=term_id,
        write=True,
    )
    if (
        term.state != payload.expected_state
        or term.version != payload.expected_version
        or _aware(term.updated_at) != _aware(payload.expected_updated_at)
    ):
        raise _conflict(
            "ip_renewal_term_stale",
            "The renewal term changed; refresh before transitioning it.",
        )
    if payload.target_state not in _TRANSITIONS[term.state]:
        raise _conflict(
            "ip_renewal_transition_invalid",
            f"A renewal cannot transition from {term.state} to {payload.target_state}.",
        )
    if payload.target_state == "instructed":
        accepted_renewal_instruction = session.scalar(
            select(IpClientInstruction.id).where(
                IpClientInstruction.company_id == context.company.id,
                IpClientInstruction.renewal_term_id == term.id,
                IpClientInstruction.status == "accepted",
                IpClientInstruction.decision == "renew",
            )
        )
        if accepted_renewal_instruction is None:
            raise _conflict(
                "ip_renewal_instruction_required",
                "An accepted renew instruction is required before marking the term instructed.",
            )
    _assert_reference_unchanged(
        current=term.fee_cost_item_id,
        proposed=payload.fee_cost_item_id,
        label="fee",
    )
    _assert_reference_unchanged(
        current=term.filing_event_id,
        proposed=payload.filing_event_id,
        label="filing",
    )
    _assert_reference_unchanged(
        current=term.acceptance_event_id,
        proposed=payload.acceptance_event_id,
        label="acceptance",
    )
    _assert_reference_unchanged(
        current=term.certificate_document_id,
        proposed=payload.certificate_document_id,
        label="certificate",
    )
    _assert_reference_unchanged(
        current=term.next_term_deadline_id,
        proposed=payload.next_term_deadline_id,
        label="next-term deadline",
    )
    if payload.fee_cost_item_id:
        _cost_item(
            session,
            context=context,
            docket_id=docket.id,
            cost_item_id=payload.fee_cost_item_id,
        )
    if payload.filing_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.filing_event_id,
            kinds=_FILING_EVENT_KINDS,
            label="Renewal filing",
        )
    if payload.acceptance_event_id:
        _event(
            session,
            context=context,
            docket_id=docket.id,
            event_id=payload.acceptance_event_id,
            kinds=_ACCEPTANCE_EVENT_KINDS,
            label="Registry acceptance",
        )
    if payload.certificate_document_id:
        _document(
            session,
            context=context,
            docket_id=docket.id,
            document_id=payload.certificate_document_id,
        )
    if payload.next_term_deadline_id:
        next_deadline = _deadline(
            session,
            context=context,
            docket_id=docket.id,
            deadline_id=payload.next_term_deadline_id,
            kind="renewal",
            label="Next-term renewal",
        )
        acceptance_event_id = payload.acceptance_event_id or term.acceptance_event_id
        if next_deadline.trigger_event_id != acceptance_event_id:
            raise _conflict(
                "ip_renewal_next_term_trigger_mismatch",
                "The next-term deadline must be calculated from this term's acceptance event.",
            )
    now = _now()
    term.state = payload.target_state
    term.version += 1
    term.updated_by_membership_id = context.membership.id
    term.updated_at = now
    if payload.fee_cost_item_id is not None:
        term.fee_cost_item_id = payload.fee_cost_item_id
    if payload.filing_initiated_reference is not None:
        term.filing_initiated_reference = payload.filing_initiated_reference.strip()
    if payload.filing_event_id is not None:
        term.filing_event_id = payload.filing_event_id
    if payload.acceptance_event_id is not None:
        term.acceptance_event_id = payload.acceptance_event_id
    if payload.certificate_document_id is not None:
        term.certificate_document_id = payload.certificate_document_id
    if payload.next_term_deadline_id is not None:
        term.next_term_deadline_id = payload.next_term_deadline_id
    if payload.target_state == "completed":
        term.completed_at = now
    cancelled_reminders = 0
    if payload.target_state in _REMINDER_TERMINAL_STATES:
        cancelled_reminders = _cancel_renewal_reminders(
            session,
            company_id=context.company.id,
            term_id=term.id,
            reason=f"renewal_transitioned_to_{payload.target_state}",
        )
    record_from_context(
        session,
        context,
        action=f"ip_renewal_term.{payload.target_state}",
        target_type="ip_renewal_term",
        target_id=term.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "from_state": payload.expected_state,
            "to_state": payload.target_state,
            "reason": payload.reason.strip(),
            "filing_event_id": term.filing_event_id,
            "acceptance_event_id": term.acceptance_event_id,
            "certificate_document_id": term.certificate_document_id,
            "next_term_deadline_id": term.next_term_deadline_id,
            "cancelled_reminder_count": cancelled_reminders,
        },
    )
    session.commit()
    session.refresh(term)
    return _record(session, term)
