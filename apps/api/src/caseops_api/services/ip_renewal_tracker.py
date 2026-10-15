"""Bounded recurrence orchestration over the existing notification delivery owner."""

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from time import monotonic
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, func, literal, or_, select

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    InAppNotification,
    IpDocketRecord,
    IpPortfolioRenewalOccurrence,
    IpPortfolioRenewalSeries,
    IpTrademarkParticularVersion,
    IpWorkspaceConfiguration,
    NotificationDeliveryIntent,
    TenantNotificationPreference,
    UserNotificationPreference,
)
from caseops_api.services.ip_coverage_read import _TERMINAL_DOCKET_STATUSES
from caseops_api.services.ip_docket_access import _docket_or_404
from caseops_api.services.ip_domain_policy import TRADEMARK_RECORD_TYPES
from caseops_api.services.ip_portfolio_dates import current_dates, date_expression
from caseops_api.services.ip_renewal_tracker_policy import INVALID_POLICY, validated_policy
from caseops_api.services.ip_renewal_tracker_source import source_stop_reason_expression
from caseops_api.services.session_context import SessionContext

SOURCE = "ip_portfolio_renewal_occurrence"
SCHEDULE = "ip_portfolio_renewal_series"
EVENT = "renewal_source_date_occurrence"


def _now():
    return datetime.now(UTC)


def _aware(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def month_start(due):
    year, month = (due.year - 1, 12) if due.month == 1 else (due.year, due.month - 1)
    return date(year, month, min(due.day, monthrange(year, month)[1]))


def local_stamp(day, *, timezone, delivery_time):
    local = datetime.combine(day, time.fromisoformat(delivery_time), tzinfo=ZoneInfo(timezone))
    # fold=0 selects the first ambiguous instant. A gap moves forward by its size.
    return local.astimezone(UTC)


def policy(session, *, company):
    config = session.scalar(
        select(IpWorkspaceConfiguration).where(IpWorkspaceConfiguration.company_id == company.id)
    )
    return validated_policy(config, company=company)


def _current(session, *, docket):
    return session.scalar(
        select(IpTrademarkParticularVersion).where(
            IpTrademarkParticularVersion.company_id == docket.company_id,
            IpTrademarkParticularVersion.docket_id == docket.id,
            IpTrademarkParticularVersion.version == docket.current_version,
        )
    )


def _stop_reason(session, *, docket, due):
    if (
        not docket.is_active
        or docket.archived_by_matter_disposal
        or docket.status in _TERMINAL_DOCKET_STATUSES
    ):
        return "source_docket_terminal"
    return session.scalar(
        select(source_stop_reason_expression(literal(due.isoformat())))
        .select_from(IpDocketRecord)
        .where(IpDocketRecord.id == docket.id, IpDocketRecord.company_id == docket.company_id)
    )


def _closed(session, *, docket, due):
    return _stop_reason(session, docket=docket, due=due) is not None


def _cancel(session, *, series, reason, now):
    from caseops_api.services.notification_delivery import cancel_pending_notification_intents

    intent_ids = (
        list(
            session.scalars(
                select(NotificationDeliveryIntent.id)
                .join(
                    IpPortfolioRenewalOccurrence,
                    and_(
                        IpPortfolioRenewalOccurrence.company_id
                        == NotificationDeliveryIntent.company_id,
                        IpPortfolioRenewalOccurrence.delivery_key
                        == NotificationDeliveryIntent.idempotency_key,
                    ),
                )
                .where(
                    IpPortfolioRenewalOccurrence.company_id == series.company_id,
                    IpPortfolioRenewalOccurrence.docket_id == series.docket_id,
                    IpPortfolioRenewalOccurrence.source_version == series.source_version,
                    IpPortfolioRenewalOccurrence.generation == series.generation,
                    NotificationDeliveryIntent.status.in_(("queued", "retry_scheduled")),
                )
            )
        )
        if series.id
        else []
    )
    cancel_pending_notification_intents(
        session,
        company_id=series.company_id,
        schedule_source_type=SCHEDULE,
        schedule_source_id=series.id,
        cancellation_reason=reason,
        intent_ids=intent_ids,
    )
    # Legacy first occurrences remain owned by their original source fence.
    cancel_pending_notification_intents(
        session,
        company_id=series.company_id,
        schedule_source_type="ip_portfolio_renewal",
        schedule_source_id=series.docket_id,
        cancellation_reason=reason,
        intent_ids=intent_ids,
    )
    series.next_reminder_at = None
    series.cancelled_at, series.cancellation_reason = now, reason


def _delivered_today(session, *, series, local_on):
    zone = ZoneInfo(series.timezone)
    start = datetime.combine(local_on, time(), zone).astimezone(UTC)
    end = datetime.combine(local_on + timedelta(days=1), time(), zone).astimezone(UTC)
    return (
        session.scalar(
            select(NotificationDeliveryIntent.id)
            .join(
                InAppNotification,
                and_(
                    InAppNotification.id == NotificationDeliveryIntent.in_app_notification_id,
                    InAppNotification.company_id == NotificationDeliveryIntent.company_id,
                    InAppNotification.recipient_membership_id
                    == NotificationDeliveryIntent.recipient_membership_id,
                ),
            )
            .where(
                NotificationDeliveryIntent.company_id == series.company_id,
                NotificationDeliveryIntent.idempotency_key == series.last_delivery_key,
                NotificationDeliveryIntent.ip_docket_id == series.docket_id,
                NotificationDeliveryIntent.recipient_membership_id
                == series.recipient_membership_id,
                NotificationDeliveryIntent.metadata_json["source_due_on"].as_string()
                == series.due_on.isoformat(),
                NotificationDeliveryIntent.delivered_at >= start,
                NotificationDeliveryIntent.delivered_at < end,
                NotificationDeliveryIntent.status == "delivered",
            )
            .limit(1)
        )
        is not None
    )


def record_delivery_receipt(session, *, intent):
    """Called only after the canonical in-app owner persisted an actual receipt."""
    if (
        intent.channel != "in_app"
        or intent.status != "delivered"
        or not intent.in_app_notification_id
        or intent.event_type not in {EVENT, "renewal_source_date_1month"}
    ):
        return
    series = session.scalar(
        select(IpPortfolioRenewalSeries).where(
            IpPortfolioRenewalSeries.company_id == intent.company_id,
            IpPortfolioRenewalSeries.docket_id == intent.ip_docket_id,
            IpPortfolioRenewalSeries.recipient_membership_id == intent.recipient_membership_id,
        )
    )
    if series is not None:
        series.last_delivery_key = intent.idempotency_key


def synchronize_series(session, *, context, docket_id, legacy_intent=None, now=None):
    """Caller owns Company/docket locks and commits this with canonical particulars."""
    now = now or _now()
    docket = session.get(IpDocketRecord, docket_id)
    version = _current(session, docket=docket)
    facts = current_dates(session, version=version, docket_id=docket.id)
    series = session.scalar(
        select(IpPortfolioRenewalSeries)
        .where(
            IpPortfolioRenewalSeries.company_id == context.company.id,
            IpPortfolioRenewalSeries.docket_id == docket.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    due = facts["source_renewal_due_on"]
    settings = policy(session, company=context.company)
    today = now.astimezone(ZoneInfo(settings["timezone"])).date()
    stopped = _stop_reason(session, docket=docket, due=due) if due else None
    if due is None or stopped or due < today:
        if series:
            _cancel(
                session,
                series=series,
                reason="missing_date" if due is None else stopped or "source_overdue",
                now=now,
            )
            series.source_version = version.version
            series.policy_error = series.reconcile_after = None
            for key, value in settings.items():
                setattr(series, key, value)
        return series
    changed = (
        series is None
        or series.policy_error is not None
        or series.cancellation_reason == "recipient_or_source_not_authorized"
        or (
            series.source_version,
            series.due_on,
            series.timezone,
            series.cadence_days,
            series.delivery_time,
            series.policy_version,
        )
        != (
            version.version,
            due,
            settings["timezone"],
            settings["cadence_days"],
            settings["delivery_time"],
            settings["policy_version"],
        )
    )
    if not changed:
        if legacy_intent is not None:
            _attach_legacy(session, series=series, intent=legacy_intent)
        return series
    previous_due = series.due_on if series else None
    if series:
        _cancel(session, series=series, reason="source_or_policy_superseded", now=now)
        series.generation += 1
    else:
        series = IpPortfolioRenewalSeries(
            company_id=context.company.id,
            docket_id=docket.id,
            recipient_membership_id=context.membership.id,
            generation=1,
        )
        session.add(series)
    series.source_version, series.due_on, series.start_on = version.version, due, month_start(due)
    for key, value in settings.items():
        setattr(series, key, value)
    series.cancelled_at = series.cancellation_reason = None
    series.policy_error = series.reconcile_after = None
    first_day = max(series.start_on, today)
    session.flush()
    if previous_due == due and _delivered_today(session, series=series, local_on=today):
        first_day = today + timedelta(days=series.cadence_days)
    series.next_reminder_at = (
        max(
            local_stamp(first_day, timezone=series.timezone, delivery_time=series.delivery_time),
            now,
        )
        if first_day <= due
        else None
    )
    if legacy_intent is None:
        legacy_intent = session.scalar(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == series.company_id,
                NotificationDeliveryIntent.ip_docket_id == docket.id,
                NotificationDeliveryIntent.recipient_membership_id
                == series.recipient_membership_id,
                NotificationDeliveryIntent.source_type == "ip_trademark_particular_version",
                NotificationDeliveryIntent.source_id == version.id,
                NotificationDeliveryIntent.event_type == "renewal_source_date_1month",
                NotificationDeliveryIntent.channel == "in_app",
            )
            .order_by(
                NotificationDeliveryIntent.created_at.desc(), NotificationDeliveryIntent.id.desc()
            )
            .limit(1)
        )
    if legacy_intent is not None:
        _attach_legacy(session, series=series, intent=legacy_intent)
    session.flush()
    return series


def _attach_legacy(session, *, series, intent):
    if intent.status in {"cancelled", "blocked"}:
        return
    if intent.status == "delivered" and intent.in_app_notification_id:
        series.last_delivery_key = intent.idempotency_key
    if series.delivery_time != "09:00":
        from caseops_api.services.notification_delivery import cancel_pending_notification_intents

        cancel_pending_notification_intents(
            session,
            company_id=series.company_id,
            schedule_source_type="ip_portfolio_renewal",
            schedule_source_id=series.docket_id,
            cancellation_reason="renewal_delivery_time_changed",
        )
        return
    occurrence_day = _aware(intent.scheduled_for).astimezone(ZoneInfo(series.timezone)).date()
    existing = session.scalar(
        select(IpPortfolioRenewalOccurrence.id).where(
            IpPortfolioRenewalOccurrence.series_id == series.id,
            IpPortfolioRenewalOccurrence.generation == series.generation,
            IpPortfolioRenewalOccurrence.local_on == occurrence_day,
        )
    )
    if existing is None:
        session.add(
            IpPortfolioRenewalOccurrence(
                company_id=series.company_id,
                docket_id=series.docket_id,
                series_id=series.id,
                generation=series.generation,
                source_version=series.source_version,
                recipient_membership_id=series.recipient_membership_id,
                due_on=series.due_on,
                local_on=occurrence_day,
                scheduled_for=intent.scheduled_for,
                delivery_key=intent.idempotency_key,
            )
        )


def _preferences_allow(session, *, series, now):
    rows = [
        session.scalar(
            select(TenantNotificationPreference).where(
                TenantNotificationPreference.company_id == series.company_id
            )
        ),
        session.scalar(
            select(UserNotificationPreference).where(
                UserNotificationPreference.company_id == series.company_id,
                UserNotificationPreference.membership_id == series.recipient_membership_id,
            )
        ),
    ]
    for row in rows:
        if row is None:
            continue
        if (row.channels_json or {}).get("in_app") is False or (
            row.event_categories_json or {}
        ).get("compliance_deadlines") is False:
            return False
        if row.digest_frequency == "disabled" or "compliance_deadlines" in (
            getattr(row, "opt_out_categories_json", None) or []
        ):
            return False
    return True


def quiet_hours_retry_at(session, *, intent, now):
    rows = [
        session.scalar(
            select(TenantNotificationPreference).where(
                TenantNotificationPreference.company_id == intent.company_id
            )
        ),
        session.scalar(
            select(UserNotificationPreference).where(
                UserNotificationPreference.company_id == intent.company_id,
                UserNotificationPreference.membership_id == intent.recipient_membership_id,
            )
        ),
    ]
    candidate = now
    for _ in range(4):
        ends = []
        for row in rows:
            quiet = (row.quiet_hours_json or {}) if row else {}
            if not quiet.get("enabled"):
                continue
            try:
                zone = ZoneInfo(quiet.get("timezone") or "Asia/Kolkata")
                start, end = time.fromisoformat(quiet["start"]), time.fromisoformat(quiet["end"])
                local = candidate.astimezone(zone)
                clock = local.time().replace(tzinfo=None)
                inside = start <= clock < end if start < end else clock >= start or clock < end
                if inside:
                    end_day = local.date() + timedelta(days=int(end <= clock))
                    ends.append(datetime.combine(end_day, end, zone).astimezone(UTC))
            except (KeyError, TypeError, ValueError):
                # Malformed retained policy never authorizes a notification.
                ends.append(now + timedelta(days=1))
        if not ends:
            return candidate if candidate > now else None
        candidate = max(ends)
    return max(candidate, now + timedelta(days=1))


def occurrence_is_current(session, *, intent, now=None):
    now = now or _now()
    pair = session.execute(
        select(IpPortfolioRenewalOccurrence, IpPortfolioRenewalSeries)
        .join(
            IpPortfolioRenewalSeries,
            IpPortfolioRenewalSeries.id == IpPortfolioRenewalOccurrence.series_id,
        )
        .where(
            IpPortfolioRenewalOccurrence.company_id == intent.company_id,
            IpPortfolioRenewalOccurrence.id == intent.source_id,
        )
    ).one_or_none()
    if pair is None:
        return False
    occurrence, series = pair
    docket = session.get(IpDocketRecord, series.docket_id)
    version = _current(session, docket=docket) if docket is not None else None
    company = session.get(Company, intent.company_id)
    if version is None or company is None or _closed(session, docket=docket, due=series.due_on):
        return False
    try:
        settings = policy(session, company=company)
    except HTTPException:
        return False
    facts = current_dates(session, version=version, docket_id=docket.id)
    today = now.astimezone(ZoneInfo(series.timezone)).date()
    return bool(
        intent.channel == "in_app"
        and intent.source_type == SOURCE
        and intent.event_type == EVENT
        and intent.schedule_source_type == SCHEDULE
        and intent.schedule_source_id == series.id
        and intent.ip_docket_id == docket.id
        and intent.recipient_membership_id
        == series.recipient_membership_id
        == occurrence.recipient_membership_id
        and occurrence.delivery_key == intent.idempotency_key
        and occurrence.generation == series.generation
        and series.cancelled_at is None
        and occurrence.source_version == series.source_version == version.version
        and facts["source_renewal_due_on"] == occurrence.due_on == series.due_on
        and series.start_on <= today <= series.due_on
        and occurrence.local_on == today
        and all(getattr(series, key) == value for key, value in settings.items())
        and _preferences_allow(session, series=series, now=now)
    )


def legacy_occurrence_is_current(session, *, intent, now):
    """Additional recurrence/preferences fence; never replaces import provenance."""
    company = session.get(Company, intent.company_id)
    if company is None:
        return False
    try:
        settings = policy(session, company=company)
    except HTTPException:
        return False
    try:
        due = date.fromisoformat((intent.metadata_json or {})["source_due_on"])
    except (KeyError, TypeError, ValueError):
        return False
    today = now.astimezone(ZoneInfo(settings["timezone"])).date()
    docket = session.get(IpDocketRecord, intent.ip_docket_id)
    if (
        docket is None
        or due < today
        or today < month_start(due)
        or _closed(session, docket=docket, due=due)
    ):
        return False
    if not _preferences_allow(
        session,
        series=SimpleNamespace(
            company_id=intent.company_id,
            recipient_membership_id=intent.recipient_membership_id,
            timezone=settings["timezone"],
        ),
        now=now,
    ):
        return False
    occurrence = session.scalar(
        select(IpPortfolioRenewalOccurrence).where(
            IpPortfolioRenewalOccurrence.company_id == intent.company_id,
            IpPortfolioRenewalOccurrence.delivery_key == intent.idempotency_key,
        )
    )
    if occurrence is None:
        return settings["delivery_time"] == "09:00"
    series = session.get(IpPortfolioRenewalSeries, occurrence.series_id)
    return bool(
        series
        and not series.cancelled_at
        and series.generation == occurrence.generation
        and series.source_version == occurrence.source_version == docket.current_version
        and occurrence.local_on <= today
        and occurrence.due_on == series.due_on == due
        and all(getattr(series, key) == value for key, value in settings.items())
    )


def occurrence_body(session, *, occurrence, version, docket, now, timezone):
    data = version.representation_json or {}
    mark = data.get("text")
    label = (mark if isinstance(mark, str) and mark else docket.title)[:120]
    classes = ", ".join(str(number) for number in source_class_numbers(version.classes_json))[:55]
    from caseops_api.db.models import IpIdentifier

    number = session.scalar(
        select(IpIdentifier.raw_value)
        .where(
            IpIdentifier.company_id == docket.company_id,
            IpIdentifier.docket_id == docket.id,
            IpIdentifier.identifier_kind == "application",
            IpIdentifier.is_primary.is_(True),
            IpIdentifier.effective_until.is_(None),
            IpIdentifier.superseded_by_identifier_id.is_(None),
        )
        .order_by(IpIdentifier.id)
        .limit(1)
    )
    remaining = (occurrence.due_on - now.astimezone(ZoneInfo(timezone)).date()).days
    urgency = "Renewal due today" if remaining == 0 else f"Renewal due in {remaining} days"
    return (
        f"{label}; application {str(number or 'not recorded')[:65]}; "
        f"classes {classes or 'not recorded'}. "
        f"{urgency}. Source date {occurrence.due_on.isoformat()} (not a verified legal deadline). "
        f"/app/ip?docket={docket.id}"
    )


def source_class_numbers(rows):
    values = (row.get("class_number") if isinstance(row, dict) else row for row in rows or [])
    return sorted({value for value in values if type(value) is int and 1 <= value <= 45})


def advance_series(session, *, context, docket_id, now=None):
    from caseops_api.services.notification_delivery import enqueue_notification_delivery_intent

    now = now or _now()
    docket = _docket_or_404(
        session,
        context=context,
        docket_id=docket_id,
        for_update=True,
        required_capability="ip:read",
    )
    series = synchronize_series(session, context=context, docket_id=docket.id, now=now)
    if series is None or series.next_reminder_at is None or _aware(series.next_reminder_at) > now:
        return False
    today = now.astimezone(ZoneInfo(series.timezone)).date()
    # Missed pending occurrences are cancelled, not replayed as a historical burst.
    old_keys = select(IpPortfolioRenewalOccurrence.delivery_key).where(
        IpPortfolioRenewalOccurrence.company_id == series.company_id,
        IpPortfolioRenewalOccurrence.series_id == series.id,
        IpPortfolioRenewalOccurrence.docket_id == series.docket_id,
        IpPortfolioRenewalOccurrence.source_version == series.source_version,
        IpPortfolioRenewalOccurrence.generation == series.generation,
        IpPortfolioRenewalOccurrence.local_on < today,
    )
    from sqlalchemy import update

    session.execute(
        update(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.company_id == series.company_id,
            NotificationDeliveryIntent.idempotency_key.in_(old_keys),
            NotificationDeliveryIntent.status.in_(("queued", "retry_scheduled")),
        )
        .values(
            status="cancelled",
            suppression_reason="missed_occurrence_superseded",
            next_attempt_at=None,
        )
    )
    occurrence = session.scalar(
        select(IpPortfolioRenewalOccurrence).where(
            IpPortfolioRenewalOccurrence.series_id == series.id,
            IpPortfolioRenewalOccurrence.generation == series.generation,
            IpPortfolioRenewalOccurrence.local_on == today,
        )
    )
    if occurrence is None and not _delivered_today(session, series=series, local_on=today):
        occurrence = IpPortfolioRenewalOccurrence(
            company_id=series.company_id,
            docket_id=series.docket_id,
            series_id=series.id,
            generation=series.generation,
            source_version=series.source_version,
            recipient_membership_id=series.recipient_membership_id,
            due_on=series.due_on,
            local_on=today,
            scheduled_for=now,
        )
        session.add(occurrence)
        session.flush()
        recipient = session.get(CompanyMembership, series.recipient_membership_id)
        version = _current(session, docket=docket)
        intent = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel="in_app",
            event_type=EVENT,
            source_type=SOURCE,
            source_id=occurrence.id,
            ip_docket=docket,
            title="Trademark renewal due soon",
            body=occurrence_body(
                session,
                occurrence=occurrence,
                version=version,
                docket=docket,
                now=now,
                timezone=series.timezone,
            ),
            scheduled_for=now,
            schedule_source_type=SCHEDULE,
            schedule_source_id=series.id,
        )
        if intent is not None:
            occurrence.delivery_key = intent.idempotency_key
            intent.metadata_json = {
                "source_due_on": series.due_on.isoformat(),
                "occurrence_on": today.isoformat(),
                "source_version": series.source_version,
            }
    next_day = today + timedelta(days=series.cadence_days)
    series.next_reminder_at = (
        local_stamp(next_day, timezone=series.timezone, delivery_time=series.delivery_time)
        if next_day <= series.due_on
        else None
    )
    session.flush()
    return True


def reconcile_renewal_series(session, *, limit=100, now=None, max_seconds=30):
    """One bounded page; every item commits/releases locks before the next."""
    from caseops_api.services.private_retrieval import lock_private_authority_writer

    now = now or _now()
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    if not 1 <= max_seconds <= 60:
        raise ValueError("max_seconds must be between 1 and 60")
    deadline = monotonic() + max_seconds
    if session.new or session.dirty or session.deleted:
        raise RuntimeError("Renewal reconciliation requires a clean, worker-owned session.")
    candidate = (
        select(
            IpDocketRecord.company_id,
            IpDocketRecord.id,
            IpTrademarkParticularVersion.created_by_membership_id,
        )
        .join(
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
                CompanyMembership.id == IpTrademarkParticularVersion.created_by_membership_id,
                CompanyMembership.company_id == IpDocketRecord.company_id,
            ),
        )
        .join(Company, and_(Company.id == IpDocketRecord.company_id, Company.is_active.is_(True)))
        .outerjoin(
            IpPortfolioRenewalSeries,
            and_(
                IpPortfolioRenewalSeries.company_id == IpDocketRecord.company_id,
                IpPortfolioRenewalSeries.docket_id == IpDocketRecord.id,
            ),
        )
        .outerjoin(
            IpWorkspaceConfiguration,
            IpWorkspaceConfiguration.company_id == IpDocketRecord.company_id,
        )
        .where(
            IpDocketRecord.record_type.in_(TRADEMARK_RECORD_TYPES),
            or_(
                IpPortfolioRenewalSeries.id.is_not(None),
                and_(
                    IpDocketRecord.is_active.is_(True),
                    IpDocketRecord.archived_by_matter_disposal.is_(False),
                    IpDocketRecord.status.not_in(_TERMINAL_DOCKET_STATUSES),
                ),
            ),
            or_(
                IpPortfolioRenewalSeries.reconcile_after.is_(None),
                IpPortfolioRenewalSeries.reconcile_after <= now,
                IpPortfolioRenewalSeries.source_version != IpDocketRecord.current_version,
                IpPortfolioRenewalSeries.policy_version
                != func.coalesce(IpWorkspaceConfiguration.version, 0),
            ),
            or_(
                IpPortfolioRenewalSeries.id.is_not(None),
                and_(
                    date_expression("renewal_due_date").is_not(None),
                    date_expression("renewal_due_date")
                    >= (now.date() - timedelta(days=1)).isoformat(),
                ),
            ),
            or_(
                IpPortfolioRenewalSeries.id.is_(None),
                IpPortfolioRenewalSeries.next_reminder_at <= now,
                IpPortfolioRenewalSeries.reconcile_after <= now,
                IpPortfolioRenewalSeries.source_version != IpDocketRecord.current_version,
                IpPortfolioRenewalSeries.policy_version
                != func.coalesce(IpWorkspaceConfiguration.version, 0),
                IpPortfolioRenewalSeries.timezone
                != func.coalesce(IpWorkspaceConfiguration.timezone, Company.timezone),
            ),
        )
        .order_by(IpPortfolioRenewalSeries.next_reminder_at, IpDocketRecord.id)
        .limit(limit)
    )
    selected = list(session.execute(candidate))
    session.rollback()
    counts = {"examined": len(selected), "advanced": 0, "blocked": 0, "invalid_policy": 0}
    for company_id, docket_id, creator_id in selected:
        if monotonic() >= deadline:
            break
        try:
            lock_private_authority_writer(session, company_id=company_id)
            series = session.scalar(
                select(IpPortfolioRenewalSeries).where(
                    IpPortfolioRenewalSeries.company_id == company_id,
                    IpPortfolioRenewalSeries.docket_id == docket_id,
                )
            )
            membership = session.get(
                CompanyMembership, series.recipient_membership_id if series else creator_id
            )
            context = SessionContext(
                company=session.get(Company, company_id),
                membership=membership,
                user=membership.user,
            )
            counts["advanced"] += int(
                advance_series(session, context=context, docket_id=docket_id, now=now)
            )
            session.commit()
        except HTTPException as error:
            session.rollback()
            lock_private_authority_writer(session, company_id=company_id)
            docket = session.scalar(
                select(IpDocketRecord)
                .where(IpDocketRecord.company_id == company_id, IpDocketRecord.id == docket_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            series = session.scalar(
                select(IpPortfolioRenewalSeries)
                .where(
                    IpPortfolioRenewalSeries.company_id == company_id,
                    IpPortfolioRenewalSeries.docket_id == docket_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            invalid_policy = (
                isinstance(error.detail, dict) and error.detail.get("code") == INVALID_POLICY
            )
            policy_version = (
                session.scalar(
                    select(IpWorkspaceConfiguration.version).where(
                        IpWorkspaceConfiguration.company_id == company_id
                    )
                )
                or 0
            )
            if series is None and docket is not None and not invalid_policy:
                try:
                    series = synchronize_series(
                        session, context=context, docket_id=docket_id, now=now
                    )
                except HTTPException as policy_error:
                    if (
                        not isinstance(policy_error.detail, dict)
                        or policy_error.detail.get("code") != INVALID_POLICY
                    ):
                        raise
                    invalid_policy = True
            if series is None and docket is not None and invalid_policy:
                version = _current(session, docket=docket)
                due = current_dates(session, version=version, docket_id=docket_id)[
                    "source_renewal_due_on"
                ]
                if due is not None:
                    series = IpPortfolioRenewalSeries(
                        company_id=company_id,
                        docket_id=docket_id,
                        source_version=docket.current_version,
                        generation=1,
                        due_on=due,
                        start_on=month_start(due),
                        recipient_membership_id=creator_id,
                        policy_version=policy_version,
                        policy_error=INVALID_POLICY,
                        reconcile_after=now + timedelta(minutes=15),
                    )
                    session.add(series)
            if series is not None:
                _cancel(
                    session,
                    series=series,
                    reason="renewal_policy_invalid"
                    if invalid_policy
                    else "recipient_or_source_not_authorized",
                    now=now,
                )
                series.source_version = docket.current_version
                series.policy_version = policy_version
                series.policy_error = INVALID_POLICY if invalid_policy else None
                series.reconcile_after = now + timedelta(minutes=15)
            if docket is not None:
                from caseops_api.services.audit import record_from_context

                record_from_context(
                    session,
                    context,
                    action="ip_renewal_tracker.reconcile_blocked",
                    target_type="ip_renewal_tracker",
                    target_id=f"{docket_id}:v{docket.current_version}:p{policy_version}",
                    ip_docket_id=docket_id,
                    result="failed" if invalid_policy else "denied",
                    metadata={
                        "reason": INVALID_POLICY
                        if invalid_policy
                        else "recipient_or_source_not_authorized",
                        "source_version": docket.current_version,
                        "policy_version": policy_version,
                        "retry_after": (now + timedelta(minutes=15)).isoformat(),
                    },
                )
            session.commit()
            counts["blocked"] += 1
            counts["invalid_policy"] += int(invalid_policy)
        except Exception:
            session.rollback()
            raise
    return counts
