"""Tenant/ACL-first SQL tracker counts and keyset-paginated current facts."""

from calendar import monthrange
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_, select

from caseops_api.db.models import (
    InAppNotification,
    IpDocketRecord,
    IpIdentifier,
    IpPortfolioRenewalOccurrence,
    IpPortfolioRenewalSeries,
    IpTrademarkParticularVersion,
    Matter,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
)
from caseops_api.schemas.ip_renewal_tracker import IpRenewalTrackerResponse, IpRenewalTrackerRow
from caseops_api.services import ip_renewal_tracker
from caseops_api.services.ip_coverage_read import _TERMINAL_DOCKET_STATUSES
from caseops_api.services.ip_domain_policy import TRADEMARK_RECORD_TYPES
from caseops_api.services.ip_portfolio_dates import (
    current_dates,
    date_expression,
    docket_date_edit_operational,
    imported_proof_expression,
)
from caseops_api.services.ip_portfolio_search import portfolio_target_search_predicate
from caseops_api.services.ip_renewal_tracker import month_start, policy
from caseops_api.services.ip_renewal_tracker_source import source_stop_reason_expression
from caseops_api.services.matter_access import visible_ip_dockets_filter


def latest_intent_column(column):
    return (
        select(column)
        .select_from(IpPortfolioRenewalOccurrence)
        .join(
            NotificationDeliveryIntent,
            and_(
                NotificationDeliveryIntent.company_id == IpPortfolioRenewalOccurrence.company_id,
                NotificationDeliveryIntent.idempotency_key
                == IpPortfolioRenewalOccurrence.delivery_key,
            ),
        )
        .where(
            IpPortfolioRenewalOccurrence.company_id == IpDocketRecord.company_id,
            IpPortfolioRenewalOccurrence.docket_id == IpDocketRecord.id,
        )
        .where(
            IpPortfolioRenewalOccurrence.source_version == IpDocketRecord.current_version,
            IpPortfolioRenewalOccurrence.generation == IpPortfolioRenewalSeries.generation,
        )
        .order_by(
            IpPortfolioRenewalOccurrence.local_on.desc(),
            IpPortfolioRenewalOccurrence.created_at.desc(),
            IpPortfolioRenewalOccurrence.id.desc(),
        )
        .limit(1)
        .correlate(IpDocketRecord, IpPortfolioRenewalSeries)
        .scalar_subquery()
    )


def _operational_predicate(due):
    return and_(
        IpDocketRecord.is_active.is_(True),
        IpDocketRecord.status.not_in(_TERMINAL_DOCKET_STATUSES),
        or_(
            IpPortfolioRenewalSeries.cancelled_at.is_(None),
            IpPortfolioRenewalSeries.cancellation_reason.in_(("source_overdue", "missing_date")),
        ),
        source_stop_reason_expression(due).is_(None),
    )


def category_predicates(*, session, context, horizon_days=90, now=None):
    now = now or ip_renewal_tracker._now()
    settings = policy(session, company=context.company)
    zone = ZoneInfo(settings["timezone"])
    today = now.astimezone(zone).date()
    year, month = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    last = monthrange(year, month)[1]
    day = last if today.day == monthrange(today.year, today.month)[1] else min(today.day, last)
    active_until = today.replace(year=year, month=month, day=day)
    due = date_expression("renewal_due_date")
    day_start = datetime.combine(today, time(), zone).astimezone(UTC)
    day_end = datetime.combine(today + timedelta(days=1), time(), zone).astimezone(UTC)
    occurrence_today = (
        select(IpPortfolioRenewalOccurrence.id)
        .where(
            IpPortfolioRenewalOccurrence.company_id == IpDocketRecord.company_id,
            IpPortfolioRenewalOccurrence.docket_id == IpDocketRecord.id,
            IpPortfolioRenewalOccurrence.local_on == today,
            IpPortfolioRenewalOccurrence.generation == IpPortfolioRenewalSeries.generation,
            IpPortfolioRenewalOccurrence.source_version == IpDocketRecord.current_version,
        )
        .correlate(IpDocketRecord, IpPortfolioRenewalSeries)
        .exists()
    )
    eligible = _operational_predicate(due)
    active = and_(eligible, due >= today.isoformat(), due <= active_until.isoformat())
    return {
        "upcoming": and_(
            eligible,
            due >= today.isoformat(),
            due <= (today + timedelta(days=horizon_days)).isoformat(),
        ),
        "active": active,
        "due_today": and_(
            active,
            or_(
                occurrence_today,
                and_(
                    IpPortfolioRenewalSeries.next_reminder_at >= day_start,
                    IpPortfolioRenewalSeries.next_reminder_at < day_end,
                ),
            ),
        ),
        "overdue": and_(eligible, due < today.isoformat()),
        "missing": and_(eligible, due.is_(None)),
        "failed": and_(
            eligible,
            latest_intent_column(NotificationDeliveryIntent.status).in_(
                ("retry_scheduled", "failed", "blocked", "dead_lettered")
            ),
            func.coalesce(latest_intent_column(NotificationDeliveryIntent.suppression_reason), "")
            != "renewal_quiet_hours",
        ),
    }


def scoped_tracker_query(session, *, context):
    return (
        select(
            IpDocketRecord,
            IpTrademarkParticularVersion,
            IpPortfolioRenewalSeries,
            imported_proof_expression().label("import_proven"),
            source_stop_reason_expression(date_expression("renewal_due_date")).label("stop_reason"),
        )
        .join(
            IpTrademarkParticularVersion,
            and_(
                IpTrademarkParticularVersion.company_id == IpDocketRecord.company_id,
                IpTrademarkParticularVersion.docket_id == IpDocketRecord.id,
                IpTrademarkParticularVersion.version == IpDocketRecord.current_version,
            ),
        )
        .outerjoin(
            IpPortfolioRenewalSeries,
            and_(
                IpPortfolioRenewalSeries.company_id == IpDocketRecord.company_id,
                IpPortfolioRenewalSeries.docket_id == IpDocketRecord.id,
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
            IpDocketRecord.company_id == context.company.id,
            IpDocketRecord.record_type.in_(TRADEMARK_RECORD_TYPES),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            visible_ip_dockets_filter(session, context=context),
            or_(
                IpDocketRecord.matter_id.is_(None),
                and_(
                    Matter.is_active.is_(True), Matter.status.in_(("intake", "active", "on_hold"))
                ),
            ),
        )
    )


def _row(
    session,
    *,
    context,
    docket,
    version,
    series,
    proven,
    stop_reason,
    settings,
    now,
    latest=None,
    numbers=None,
    delivered_at=None,
    last_attempt_at=None,
):
    dates = current_dates(session, version=version, docket_id=docket.id, imported_proven=proven)
    due = dates["source_renewal_due_on"]
    today = now.astimezone(ZoneInfo(settings["timezone"])).date()
    status = (
        "missing_date"
        if due is None
        else "overdue"
        if due < today
        else "active"
        if month_start(due) <= today
        else "scheduled"
    )
    operational = (
        docket_date_edit_operational(docket)
        and stop_reason is None
        and (
            not series
            or not series.cancelled_at
            or series.cancellation_reason in {"source_overdue", "missing_date"}
        )
    )
    if not operational:
        status = "cancelled"
    if latest and status not in {"cancelled", "missing_date", "overdue"}:
        if (
            latest.status in {"retry_scheduled", "failed", "blocked", "dead_lettered"}
            and latest.suppression_reason != "renewal_quiet_hours"
        ):
            status = "failed"
        elif latest.status == "delivered":
            status = "sent"
    return IpRenewalTrackerRow(
        **dates,
        docket_title=docket.title,
        docket_operational=docket_date_edit_operational(docket),
        application_numbers=numbers or [],
        nice_classes=ip_renewal_tracker.source_class_numbers(version.classes_json),
        reminder_start_on=month_start(due) if due and due.year > 1 else None,
        next_reminder_at=series.next_reminder_at if series and not series.cancelled_at else None,
        timezone=settings["timezone"],
        cadence_days=settings["cadence_days"],
        delivery_time=settings["delivery_time"],
        days_remaining=(due - today).days if due else None,
        status=status,
        last_attempt_at=last_attempt_at,
        delivered_at=delivered_at,
        last_error=(latest.last_error_redacted if latest else None)
        or (
            {
                "ambiguous_source_renewal_terms": "Conflicting current renewal terms need review.",
                "source_applications_terminal": "No current active application remains.",
                "source_renewal_completed_or_cancelled": "The current renewal term is closed.",
            }.get(stop_reason)
        ),
    )


def list_tracker(
    session, *, context, category=None, query=None, limit=50, cursor=None, horizon_days=90
):
    if (
        not 1 <= limit <= 100
        or not 1 <= horizon_days <= 365
        or (query is not None and len(query) > 200)
    ):
        raise HTTPException(status_code=422, detail="Invalid tracker bounds.")
    now = ip_renewal_tracker._now()
    predicates = category_predicates(
        session=session, context=context, horizon_days=horizon_days, now=now
    )
    statement = scoped_tracker_query(session, context=context)
    if query and query.strip():
        statement = statement.where(
            portfolio_target_search_predicate(company_id=context.company.id, query=query)
        )
    count_columns = [
        func.coalesce(func.sum(case((predicate, 1), else_=0)), 0).label(key)
        for key, predicate in predicates.items()
    ]
    counts = dict(
        session.execute(statement.with_only_columns(*count_columns).order_by(None)).mappings().one()
    )
    if category:
        if category not in predicates:
            raise HTTPException(status_code=422, detail="Unknown tracker category.")
        statement = statement.where(predicates[category])
    if cursor:
        if len(cursor) != 36:
            raise HTTPException(status_code=400, detail="Invalid tracker cursor.")
        statement = statement.where(IpDocketRecord.id > cursor)
    page = list(session.execute(statement.order_by(IpDocketRecord.id).limit(limit + 1)))
    settings = policy(session, company=context.company)
    rows = _hydrate_page(session, context=context, page=page[:limit], settings=settings, now=now)
    return IpRenewalTrackerResponse(
        rows=rows,
        counts=counts,
        limit=limit,
        next_cursor=page[limit - 1][0].id if len(page) > limit else None,
    )


def _hydrate_page(session, *, context, page, settings, now):
    ids = [row[0].id for row in page]
    if not ids:
        return []
    latest_ids = (
        dict(
            session.execute(
                select(IpDocketRecord.id, latest_intent_column(NotificationDeliveryIntent.id))
                .outerjoin(
                    IpPortfolioRenewalSeries,
                    and_(
                        IpPortfolioRenewalSeries.company_id == IpDocketRecord.company_id,
                        IpPortfolioRenewalSeries.docket_id == IpDocketRecord.id,
                    ),
                )
                .where(IpDocketRecord.company_id == context.company.id, IpDocketRecord.id.in_(ids))
            ).all()
        )
        if ids
        else {}
    )
    intents = (
        {
            row.id: row
            for row in session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.company_id == context.company.id,
                    NotificationDeliveryIntent.id.in_(
                        [value for value in latest_ids.values() if value]
                    ),
                )
            )
        }
        if ids
        else {}
    )
    delivered = dict(
        session.execute(
            select(
                IpPortfolioRenewalSeries.docket_id,
                NotificationDeliveryIntent.delivered_at,
            )
            .select_from(IpPortfolioRenewalSeries)
            .join(
                NotificationDeliveryIntent,
                and_(
                    NotificationDeliveryIntent.company_id == IpPortfolioRenewalSeries.company_id,
                    NotificationDeliveryIntent.idempotency_key
                    == IpPortfolioRenewalSeries.last_delivery_key,
                    NotificationDeliveryIntent.ip_docket_id == IpPortfolioRenewalSeries.docket_id,
                ),
            )
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
                IpPortfolioRenewalSeries.company_id == context.company.id,
                IpPortfolioRenewalSeries.docket_id.in_(ids),
                NotificationDeliveryIntent.event_type.in_(
                    ("renewal_source_date_1month", "renewal_source_date_occurrence")
                ),
                NotificationDeliveryIntent.channel == "in_app",
                NotificationDeliveryIntent.status == "delivered",
            )
        ).all()
    )
    attempted = (
        dict(
            session.execute(
                select(
                    NotificationDeliveryEvent.intent_id,
                    func.max(NotificationDeliveryEvent.occurred_at),
                )
                .where(
                    NotificationDeliveryEvent.company_id == context.company.id,
                    NotificationDeliveryEvent.intent_id.in_(list(intents)),
                    NotificationDeliveryEvent.event_type.in_(
                        ("delivery_claimed", "delivery_failed", "delivered")
                    ),
                )
                .group_by(NotificationDeliveryEvent.intent_id)
            ).all()
        )
        if intents
        else {}
    )
    number_rows = select(
        IpIdentifier.docket_id.label("docket_id"),
        IpIdentifier.raw_value.label("raw_value"),
        func.row_number()
        .over(partition_by=IpIdentifier.docket_id, order_by=IpIdentifier.id)
        .label("position"),
    )
    number_rows = number_rows.where(
        IpIdentifier.company_id == context.company.id,
        IpIdentifier.docket_id.in_(ids),
        IpIdentifier.identifier_kind == "application",
        IpIdentifier.effective_until.is_(None),
        IpIdentifier.superseded_by_identifier_id.is_(None),
    ).subquery()
    numbers = {}
    if ids:
        for docket_id, raw in session.execute(
            select(number_rows.c.docket_id, number_rows.c.raw_value).where(
                number_rows.c.position <= 50
            )
        ):
            numbers.setdefault(docket_id, []).append(raw)
    rows = []
    for docket, version, series, proven, stop_reason in page:
        latest = intents.get(latest_ids.get(docket.id))
        rows.append(
            _row(
                session,
                context=context,
                docket=docket,
                version=version,
                series=series,
                proven=proven,
                stop_reason=stop_reason,
                settings=settings,
                now=now,
                latest=latest,
                numbers=numbers.get(docket.id),
                delivered_at=delivered.get(docket.id),
                last_attempt_at=attempted.get(latest.id) if latest else None,
            )
        )
    return rows


def tracker_row(session, *, context, docket_id):
    record = session.execute(
        scoped_tracker_query(session, context=context).where(IpDocketRecord.id == docket_id)
    ).one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    return _hydrate_page(
        session,
        context=context,
        page=[record],
        settings=policy(session, company=context.company),
        now=ip_renewal_tracker._now(),
    )[0]
