"""Recipient-owned actions on actual delivered, currently authorized IP receipts."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import aliased

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingReminder,
    HearingReminderDeliveryIntent,
    InAppNotification,
    IpDocketRecord,
    IpPortfolioRenewalOccurrence,
    IpPortfolioRenewalSeries,
    IpTrademarkParticularVersion,
    Matter,
    MatterHearing,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.schemas.in_app_notifications import (
    InAppNotificationUpdate,
    RecipientNotificationPage,
    RecipientNotificationRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_coverage_read import _TERMINAL_DOCKET_STATUSES
from caseops_api.services.ip_docket_access import _docket_or_404
from caseops_api.services.ip_portfolio_dates import date_expression
from caseops_api.services.ip_renewal_tracker_source import source_stop_reason_expression
from caseops_api.services.matter_access import visible_ip_dockets_filter


def _eligible_receipt_links(
    session, *, context, docket_id=None, candidate_ids=None, intent_ids=None
):
    due = date_expression("renewal_due_date")
    occurrence = (
        select(IpPortfolioRenewalOccurrence.id)
        .join(
            IpPortfolioRenewalSeries,
            and_(
                IpPortfolioRenewalSeries.id == IpPortfolioRenewalOccurrence.series_id,
                IpPortfolioRenewalSeries.company_id == IpPortfolioRenewalOccurrence.company_id,
            ),
        )
        .where(
            InAppNotification.source_type == "ip_portfolio_renewal_occurrence",
            InAppNotification.event_type == "renewal_source_date_occurrence",
            IpPortfolioRenewalOccurrence.id == InAppNotification.source_id,
            IpPortfolioRenewalOccurrence.company_id == InAppNotification.company_id,
            IpPortfolioRenewalOccurrence.recipient_membership_id == context.membership.id,
            IpPortfolioRenewalOccurrence.docket_id == IpDocketRecord.id,
            IpPortfolioRenewalOccurrence.source_version == IpDocketRecord.current_version,
            IpPortfolioRenewalOccurrence.delivery_key == NotificationDeliveryIntent.idempotency_key,
            IpPortfolioRenewalSeries.docket_id == IpDocketRecord.id,
            IpPortfolioRenewalSeries.recipient_membership_id == context.membership.id,
            IpPortfolioRenewalSeries.source_version == IpDocketRecord.current_version,
            IpPortfolioRenewalSeries.generation == IpPortfolioRenewalOccurrence.generation,
            IpPortfolioRenewalSeries.cancelled_at.is_(None),
            cast(IpPortfolioRenewalSeries.due_on, String) == due,
            IpPortfolioRenewalOccurrence.due_on == IpPortfolioRenewalSeries.due_on,
            NotificationDeliveryIntent.schedule_source_type == "ip_portfolio_renewal_series",
            NotificationDeliveryIntent.schedule_source_id == IpPortfolioRenewalSeries.id,
        )
        .correlate(
            InAppNotification,
            NotificationDeliveryIntent,
            IpDocketRecord,
            IpTrademarkParticularVersion,
        )
        .exists()
    )
    legacy = and_(
        InAppNotification.source_type == "ip_trademark_particular_version",
        InAppNotification.event_type == "renewal_source_date_1month",
        InAppNotification.source_id == IpTrademarkParticularVersion.id,
        NotificationDeliveryIntent.schedule_source_type == "ip_portfolio_renewal",
        NotificationDeliveryIntent.schedule_source_id == IpDocketRecord.id,
        NotificationDeliveryIntent.metadata_json["source_due_on"].as_string() == due,
        InAppNotification.metadata_json["source_due_on"].as_string() == due,
    )
    newer_reminder = aliased(HearingReminder)
    hearing = (
        select(HearingReminder.id)
        .join(
            MatterHearing,
            and_(
                MatterHearing.id == HearingReminder.hearing_id,
                MatterHearing.company_id == HearingReminder.company_id,
            ),
        )
        .where(
            InAppNotification.source_type == "hearing_reminder",
            InAppNotification.event_type == "hearing_upcoming",
            InAppNotification.source_id == HearingReminder.id + ":v1",
            HearingReminder.company_id == InAppNotification.company_id,
            HearingReminder.ip_docket_id == IpDocketRecord.id,
            HearingReminder.recipient_membership_id == context.membership.id,
            HearingReminder.channel == "in_app",
            HearingReminder.status.in_(("sent", "delivered")),
            select(HearingReminderDeliveryIntent.id)
            .where(
                HearingReminderDeliveryIntent.hearing_reminder_id == HearingReminder.id,
                HearingReminderDeliveryIntent.intent_id == NotificationDeliveryIntent.id,
                HearingReminderDeliveryIntent.is_primary.is_(True),
            )
            .correlate(HearingReminder, NotificationDeliveryIntent)
            .exists(),
            ~select(newer_reminder.id)
            .where(
                newer_reminder.company_id == HearingReminder.company_id,
                newer_reminder.hearing_id == HearingReminder.hearing_id,
                newer_reminder.schedule_generation > HearingReminder.schedule_generation,
            )
            .correlate(HearingReminder)
            .exists(),
            HearingReminder.scheduled_for == NotificationDeliveryIntent.scheduled_for,
            MatterHearing.ip_docket_id == IpDocketRecord.id,
            MatterHearing.status.not_in(("completed", "cancelled")),
            NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
            NotificationDeliveryIntent.schedule_source_id == MatterHearing.id,
        )
        .correlate(InAppNotification, NotificationDeliveryIntent, IpDocketRecord)
        .exists()
    )
    # Filter before pagination; ambiguous links fail closed rather than selecting a body.
    eligible = (
        select(
            InAppNotification.id.label("id"),
            IpDocketRecord.id.label("docket_id"),
            IpDocketRecord.title.label("target_label"),
            func.count().over(partition_by=InAppNotification.id).label("links"),
        )
        .join(
            NotificationDeliveryIntent,
            and_(
                NotificationDeliveryIntent.in_app_notification_id == InAppNotification.id,
                NotificationDeliveryIntent.company_id == InAppNotification.company_id,
                NotificationDeliveryIntent.recipient_membership_id
                == InAppNotification.recipient_membership_id,
                NotificationDeliveryIntent.source_type == InAppNotification.source_type,
                NotificationDeliveryIntent.source_id == InAppNotification.source_id,
                NotificationDeliveryIntent.event_type == InAppNotification.event_type,
                NotificationDeliveryIntent.matter_id.is_not_distinct_from(
                    InAppNotification.matter_id
                ),
            ),
        )
        .join(
            IpDocketRecord,
            and_(
                IpDocketRecord.id == NotificationDeliveryIntent.ip_docket_id,
                IpDocketRecord.company_id == InAppNotification.company_id,
            ),
        )
        .outerjoin(
            IpTrademarkParticularVersion,
            and_(
                IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
            ),
        )
        .join(
            CompanyMembership,
            and_(
                CompanyMembership.id == InAppNotification.recipient_membership_id,
                CompanyMembership.company_id == InAppNotification.company_id,
            ),
        )
        .join(User, User.id == CompanyMembership.user_id)
        .join(Company, Company.id == InAppNotification.company_id)
        .where(
            InAppNotification.company_id == context.company.id,
            InAppNotification.recipient_membership_id == context.membership.id,
            InAppNotification.status.in_(("unread", "read", "dismissed")),
            Company.is_active.is_(True),
            CompanyMembership.is_active.is_(True),
            User.id == context.user.id,
            User.is_active.is_(True),
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            IpDocketRecord.status.not_in(_TERMINAL_DOCKET_STATUSES),
            visible_ip_dockets_filter(session, context=context),
            or_(
                IpDocketRecord.matter_id.is_(None),
                select(Matter.id)
                .where(
                    Matter.id == IpDocketRecord.matter_id,
                    Matter.company_id == context.company.id,
                    Matter.is_active.is_(True),
                    Matter.status.in_(("intake", "active", "on_hold")),
                )
                .correlate(IpDocketRecord)
                .exists(),
            ),
            NotificationDeliveryIntent.channel == "in_app",
            NotificationDeliveryIntent.status == "delivered",
            NotificationDeliveryIntent.delivered_at.is_not(None),
            NotificationDeliveryIntent.neutralized_at.is_(None),
            NotificationDeliveryIntent.superseded_by_intent_id.is_(None),
            or_(
                and_(or_(occurrence, legacy), source_stop_reason_expression(due).is_(None)), hearing
            ),
        )
    )
    if docket_id is not None:
        eligible = eligible.where(IpDocketRecord.id == docket_id)
    if candidate_ids is not None:
        if not candidate_ids or len(candidate_ids) > 50:
            raise ValueError("A bounded nonempty receipt candidate set is required.")
        eligible = eligible.where(InAppNotification.id.in_(candidate_ids))
    if intent_ids is not None:
        if not intent_ids or len(intent_ids) > 50:
            raise ValueError("A bounded nonempty intent set is required.")
        eligible = eligible.where(NotificationDeliveryIntent.id.in_(intent_ids))
    return eligible.subquery()


def _current_receipts(session, *, context, docket_id):
    eligible = _eligible_receipt_links(session, context=context, docket_id=docket_id)
    return (
        select(InAppNotification)
        .join(eligible, eligible.c.id == InAppNotification.id)
        .where(
            eligible.c.links == 1,
        )
    )


def current_receipt_targets(session, *, context, candidate_ids, intent_ids):
    """Current IP receipt targets for an already bounded recipient-owned page."""
    eligible = _eligible_receipt_links(
        session, context=context, candidate_ids=candidate_ids, intent_ids=intent_ids
    )
    return select(eligible.c.id, eligible.c.docket_id, eligible.c.target_label).where(
        eligible.c.links == 1
    )


def _record(note, docket_id):
    def utc(value):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    return RecipientNotificationRecord(
        id=note.id,
        docket_id=docket_id,
        title=note.title,
        body=note.body,
        status=note.status,
        created_at=utc(note.created_at),
        read_at=utc(note.read_at),
    )


def list_recipient_notifications(
    session, *, context, docket_id, dismissed=False, cursor=None, limit=25
):
    if not 1 <= limit <= 50 or (cursor is not None and len(cursor) != 36):
        raise HTTPException(status_code=422, detail="Invalid notification page bounds.")
    statement = _current_receipts(session, context=context, docket_id=docket_id).where(
        (InAppNotification.status == "dismissed")
        if dismissed
        else InAppNotification.status.in_(("unread", "read")),
    )
    if cursor:
        statement = statement.where(InAppNotification.id > cursor)
    notes = list(session.scalars(statement.order_by(InAppNotification.id).limit(limit + 1)))
    return RecipientNotificationPage(
        items=[_record(note, docket_id) for note in notes[:limit]],
        next_cursor=notes[limit - 1].id if len(notes) > limit else None,
    )


def update_recipient_notification(
    session, *, context, docket_id, notification_id, payload: InAppNotificationUpdate
):
    # Match the canonical actor -> Matter -> docket -> child lock order. A
    # recipient may manage their receipt with read access; no write grant is added.
    _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:read",
    )
    note = session.scalar(
        select(InAppNotification)
        .where(
            InAppNotification.id == notification_id,
            InAppNotification.company_id == context.company.id,
            InAppNotification.recipient_membership_id == context.membership.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        note is None
        or session.scalar(
            _current_receipts(
                session,
                context=context,
                docket_id=docket_id,
            ).where(InAppNotification.id == notification_id)
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Notification not found.")
    if note.status == payload.status:
        return _record(note, docket_id)
    if note.status != payload.expected_status:
        raise HTTPException(
            status_code=409, detail="Notification changed; reload its current state."
        )
    before = note.status
    note.status = payload.status
    if payload.status == "read" and note.read_at is None:
        note.read_at = datetime.now(UTC)
    record_from_context(
        session,
        context=context,
        action="in_app_notification.status_changed",
        target_type="in_app_notification",
        target_id=note.id,
        metadata={"before": before, "after": note.status},
        ip_docket_id=docket_id,
    )
    session.commit()
    return _record(note, docket_id)
