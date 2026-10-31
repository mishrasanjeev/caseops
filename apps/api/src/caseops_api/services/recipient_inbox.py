"""Recipient-owned delivered alerts with bounded candidate work and fresh ACLs.

Pagination advances over at most 50 owned receipt candidates, including obsolete
receipts. It never scans history until a page fills. A page may therefore be
empty with a continuation. Only currently correlated, authorized source labels
are returned. Cursor contents are authenticated and encrypted.
"""

import base64
import hashlib
import hmac
import json
import re
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    HearingReminder,
    HearingReminderDeliveryIntent,
    InAppNotification,
    Matter,
    MatterHearing,
    NotificationDeliveryIntent,
    User,
)
from caseops_api.schemas.recipient_inbox import InboxPage, InboxRecord, InboxTarget
from caseops_api.services.assignment_memberships import lock_company_memberships_for_assignment
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.in_app_notifications import current_receipt_targets
from caseops_api.services.matter_access import visible_matters_filter

CURSOR_TTL_SECONDS = 3600
MAX_CANDIDATES = 50
_REMINDER_SOURCE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}:v1")
_CURSOR_FIELDS = {"v", "company", "member", "user", "view", "limit", "created", "id", "iat", "exp"}


def _utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _cursor_cipher():
    key = hmac.new(
        get_settings().auth_secret.encode(),
        b"caseops-recipient-inbox-cursor-v1",
        hashlib.sha256,
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _cursor_scope(context, view, limit):
    return {
        "v": 1,
        "company": context.company.id,
        "member": context.membership.id,
        "user": context.user.id,
        "view": view,
        "limit": limit,
    }


def encode_inbox_cursor(context, view, limit, created_at, row_id, *, now=None):
    now = _utc(now or datetime.now(UTC))
    issued = int(now.timestamp())
    payload = {
        **_cursor_scope(context, view, limit),
        "created": _utc(created_at).isoformat(),
        "id": row_id,
        "iat": issued,
        "exp": issued + CURSOR_TTL_SECONDS,
    }
    return (
        _cursor_cipher()
        .encrypt_at_time(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), issued
        )
        .decode("ascii")
    )


def decode_inbox_cursor(value, context, view, limit, *, now=None):
    """This clock is cursor-local; authentication JWT time is never changed."""
    now = _utc(now or datetime.now(UTC))
    try:
        if not isinstance(value, str) or not value or len(value) > 4000:
            raise ValueError
        payload = json.loads(
            _cursor_cipher().decrypt_at_time(
                value.encode("ascii"), CURSOR_TTL_SECONDS, int(now.timestamp())
            )
        )
        if not isinstance(payload, dict) or set(payload) != _CURSOR_FIELDS:
            raise ValueError
        if any(
            payload.get(key) != expected
            for key, expected in _cursor_scope(context, view, limit).items()
        ):
            raise ValueError
        if (
            type(payload["v"]) is not int
            or type(payload["limit"]) is not int
            or type(payload["iat"]) is not int
            or type(payload["exp"]) is not int
            or payload["exp"] - payload["iat"] != CURSOR_TTL_SECONDS
            or payload["iat"] > now.timestamp()
            or now.timestamp() >= payload["exp"]
        ):
            raise ValueError
        row_id = payload["id"]
        if (
            not isinstance(row_id, str)
            or not 1 <= len(row_id) <= 36
            or any(ord(ch) < 32 for ch in row_id)
        ):
            raise ValueError
        created = datetime.fromisoformat(payload["created"])
        if created.tzinfo is None or created.utcoffset() is None:
            raise ValueError
        return _utc(created), row_id
    except (InvalidToken, ValueError, TypeError, KeyError, UnicodeError, OverflowError) as exc:
        raise HTTPException(
            400, "Invalid notification continuation. Reload notifications."
        ) from exc


def recipient_candidate_statement(context, *, limit, after=None):
    """The recipient chronological index bounds membership before policy work."""
    statement = select(InAppNotification.id, InAppNotification.created_at).where(
        InAppNotification.company_id == context.company.id,
        InAppNotification.recipient_membership_id == context.membership.id,
    )
    if after is not None:
        created, row_id = after
        statement = statement.where(
            or_(
                InAppNotification.created_at < created,
                and_(InAppNotification.created_at == created, InAppNotification.id < row_id),
            )
        )
    return statement.order_by(
        InAppNotification.created_at.desc(), InAppNotification.id.desc()
    ).limit(limit + 1)


def receipt_link_statement(context, candidate_ids):
    """Seek two linked IDs, before policy; never count arbitrary link history."""
    if not candidate_ids or len(candidate_ids) > MAX_CANDIDATES:
        raise ValueError("Bounded receipt candidates required.")
    first_intent = aliased(NotificationDeliveryIntent, name="inbox_first_intent")
    second_intent = aliased(NotificationDeliveryIntent, name="inbox_second_intent")
    first = (
        select(first_intent.id)
        .where(
            first_intent.in_app_notification_id == InAppNotification.id,
        )
        .order_by(first_intent.id)
        .limit(1)
        .correlate(InAppNotification)
        .scalar_subquery()
    )
    second = (
        select(second_intent.id)
        .where(
            second_intent.in_app_notification_id == InAppNotification.id,
            second_intent.id > first,
        )
        .order_by(second_intent.id)
        .limit(1)
        .correlate(InAppNotification)
        .scalar_subquery()
    )
    return select(
        InAppNotification.id,
        first.label("first_id"),
        second.label("second_id"),
        func.substr(InAppNotification.source_id, 1, 40).label("bounded_source_id"),
    ).where(
        InAppNotification.id.in_(candidate_ids),
        InAppNotification.company_id == context.company.id,
        InAppNotification.recipient_membership_id == context.membership.id,
    )


def matter_receipt_targets(session, *, context, candidate_ids, intent_ids, reminder_ids):
    """Actual delivered Matter hearing receipts, not generic unverified titles."""
    if (
        not reminder_ids
        or len(reminder_ids) > len(candidate_ids)
        or len(candidate_ids) > MAX_CANDIDATES
    ):
        raise ValueError("Bounded exact reminder candidates required.")
    # Fixed primary-key candidates before current policy. Keeping a tenant or
    # status filter inside this boundary lets a low estimate choose a broad
    # company/history index. The outer query still checks every current source,
    # tenant, recipient, lifecycle, delivery and parent-visibility predicate.
    candidates = (
        select(
            HearingReminder.id,
            HearingReminder.company_id,
            HearingReminder.hearing_id,
            HearingReminder.matter_id,
            HearingReminder.ip_docket_id,
            HearingReminder.recipient_membership_id,
            HearingReminder.channel,
            HearingReminder.scheduled_for,
            HearingReminder.status,
            HearingReminder.schedule_generation,
        )
        .where(HearingReminder.id.in_(reminder_ids))
        .order_by(HearingReminder.id)
        .limit(len(reminder_ids))
    )
    candidates = candidates.cte("inbox_exact_reminders").prefix_with(
        "MATERIALIZED", dialect="postgresql"
    )
    reminder = aliased(HearingReminder, candidates)
    newer = aliased(HearingReminder)
    # Seek the exact schedule PK from its canonical public source identity.
    # Keeping only `reminder.id || ':v1' = source_id` can instead inspect every
    # reminder generation for the hearing. These scalar checks are portable on
    # SQLite/PostgreSQL and bounded by the fixed 39-byte source shape.
    reminder_id = func.substr(InAppNotification.source_id, 1, 36)
    digits = func.replace(reminder_id, "-", "")
    nonhex = digits
    for digit in "0123456789abcdef":
        nonhex = func.replace(nonhex, digit, "")
    canonical_source = and_(
        func.length(InAppNotification.source_id) == 39,
        func.substr(InAppNotification.source_id, 37, 3) == ":v1",
        *(func.substr(reminder_id, position, 1) == "-" for position in (9, 14, 19, 24)),
        func.length(digits) == 32,
        nonhex == "",
    )
    return (
        select(InAppNotification.id, Matter.id, Matter.title)
        .join(
            NotificationDeliveryIntent,
            and_(
                NotificationDeliveryIntent.in_app_notification_id == InAppNotification.id,
                NotificationDeliveryIntent.company_id == InAppNotification.company_id,
                NotificationDeliveryIntent.recipient_membership_id
                == InAppNotification.recipient_membership_id,
                NotificationDeliveryIntent.source_id == InAppNotification.source_id,
                NotificationDeliveryIntent.source_type == InAppNotification.source_type,
                NotificationDeliveryIntent.event_type == InAppNotification.event_type,
                NotificationDeliveryIntent.matter_id == InAppNotification.matter_id,
            ),
        )
        .join(
            Matter,
            and_(Matter.id == InAppNotification.matter_id, Matter.company_id == context.company.id),
        )
        .join(
            MatterHearing,
            and_(
                MatterHearing.id == NotificationDeliveryIntent.schedule_source_id,
                MatterHearing.company_id == context.company.id,
                MatterHearing.matter_id == Matter.id,
                MatterHearing.ip_docket_id.is_(None),
            ),
        )
        .join(
            reminder,
            and_(
                reminder.id == reminder_id,
                reminder.id + ":v1" == InAppNotification.source_id,
                canonical_source,
                reminder.company_id == context.company.id,
                reminder.hearing_id == MatterHearing.id,
                reminder.matter_id == Matter.id,
                reminder.ip_docket_id.is_(None),
                reminder.recipient_membership_id == context.membership.id,
                reminder.channel == "in_app",
                reminder.scheduled_for == NotificationDeliveryIntent.scheduled_for,
            ),
        )
        .join(
            CompanyMembership,
            and_(
                CompanyMembership.id == InAppNotification.recipient_membership_id,
                CompanyMembership.company_id == context.company.id,
            ),
        )
        .join(User, User.id == CompanyMembership.user_id)
        .join(Company, Company.id == context.company.id)
        .where(
            InAppNotification.id.in_(candidate_ids),
            NotificationDeliveryIntent.id.in_(intent_ids),
            InAppNotification.company_id == context.company.id,
            InAppNotification.recipient_membership_id == context.membership.id,
            InAppNotification.status.in_(("unread", "read", "dismissed")),
            Company.is_active.is_(True),
            CompanyMembership.is_active.is_(True),
            User.id == context.user.id,
            User.is_active.is_(True),
            InAppNotification.source_type == "hearing_reminder",
            InAppNotification.event_type == "hearing_upcoming",
            NotificationDeliveryIntent.ip_docket_id.is_(None),
            NotificationDeliveryIntent.channel == "in_app",
            NotificationDeliveryIntent.status == "delivered",
            NotificationDeliveryIntent.delivered_at.is_not(None),
            NotificationDeliveryIntent.neutralized_at.is_(None),
            NotificationDeliveryIntent.superseded_by_intent_id.is_(None),
            NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
            Matter.is_active.is_(True),
            Matter.status.in_(("intake", "active", "on_hold")),
            MatterHearing.status.not_in(("completed", "cancelled")),
            MatterHearing.cancelled_by_matter_disposal.is_(False),
            reminder.status.in_(("sent", "delivered")),
            select(HearingReminderDeliveryIntent.id)
            .where(
                HearingReminderDeliveryIntent.hearing_reminder_id == reminder.id,
                HearingReminderDeliveryIntent.intent_id == NotificationDeliveryIntent.id,
                HearingReminderDeliveryIntent.is_primary.is_(True),
            )
            .correlate(reminder, NotificationDeliveryIntent)
            .exists(),
            # A scalar LIMIT retains the parameterized generation seek. EXISTS
            # may decorrelate into an anti join that scans all older schedules.
            select(newer.schedule_generation)
            .where(
                newer.company_id == context.company.id,
                newer.hearing_id == MatterHearing.id,
                newer.schedule_generation > reminder.schedule_generation,
            )
            .order_by(newer.schedule_generation)
            .limit(1)
            .correlate(
                MatterHearing,
                reminder,
            )
            .scalar_subquery()
            .is_(None),
            visible_matters_filter(session, context=context),
        )
    )


def eligible_inbox_targets(session, context, candidate_ids):
    links = list(session.execute(receipt_link_statement(context, candidate_ids)))
    # More than one linked intent is an ambiguous receipt, even if only one
    # would pass a later source filter. No body/target is selected arbitrarily.
    sole = {row.id: row.first_id for row in links if row.first_id and row.second_id is None}
    if not sole:
        return {}
    ids, intents = tuple(sole), tuple(sole.values())
    # This bounded hint narrows only the PK candidate read. It grants no
    # authority: the SQL below rechecks the complete original source binding.
    reminder_ids = tuple(
        sorted(
            {
                row.bounded_source_id[:36]
                for row in links
                if row.id in sole and _REMINDER_SOURCE.fullmatch(row.bounded_source_id or "")
            }
        )
    )
    rows = (
        [
            (row[0], "matter", row[1], row[2])
            for row in session.execute(
                matter_receipt_targets(
                    session,
                    context=context,
                    candidate_ids=ids,
                    intent_ids=intents,
                    reminder_ids=reminder_ids,
                )
            )
        ]
        if reminder_ids
        else []
    )
    if membership_has_capability(session, context.membership, "ip:read"):
        rows.extend(
            (row[0], "ip_docket", row[1], row[2])
            for row in session.execute(
                current_receipt_targets(
                    session, context=context, candidate_ids=ids, intent_ids=intents
                )
            )
        )
    counts = {}
    for row in rows:
        counts[row[0]] = counts.get(row[0], 0) + 1
    return {row[0]: (row[1], row[2], row[3]) for row in rows if counts[row[0]] == 1}


def list_recipient_inbox(session, *, context, view="active", limit=25, cursor=None):
    if (
        view not in {"active", "dismissed"}
        or type(limit) is not int
        or not 1 <= limit <= MAX_CANDIDATES
    ):
        raise HTTPException(422, "Invalid notification page bounds.")
    after = decode_inbox_cursor(cursor, context, view, limit) if cursor is not None else None
    candidates = list(
        session.execute(recipient_candidate_statement(context, limit=limit, after=after))
    )
    page = candidates[:limit]
    targets = (
        eligible_inbox_targets(session, context, tuple(row.id for row in page)) if page else {}
    )
    items = []
    if targets:
        records = {
            row.id: row
            for row in session.execute(
                select(
                    InAppNotification.id,
                    InAppNotification.status,
                    InAppNotification.created_at,
                    InAppNotification.read_at,
                    InAppNotification.source_type,
                ).where(
                    InAppNotification.id.in_(tuple(targets)),
                    InAppNotification.company_id == context.company.id,
                    InAppNotification.recipient_membership_id == context.membership.id,
                )
            )
        }
        for candidate in page:
            record = records.get(candidate.id)
            if record is None or (record.status == "dismissed") != (view == "dismissed"):
                continue
            if record.status not in {"unread", "read", "dismissed"}:
                continue
            kind, target_id, label = targets[candidate.id]
            items.append(
                InboxRecord(
                    id=record.id,
                    title="Hearing reminder"
                    if record.source_type == "hearing_reminder"
                    else "IP renewal alert",
                    body="Open the current record to review its details.",
                    status=record.status,
                    created_at=_utc(record.created_at),
                    read_at=_utc(record.read_at) if record.read_at is not None else None,
                    target=InboxTarget(kind=kind, id=target_id),
                    target_label=label,
                )
            )
    more = len(candidates) > limit
    return InboxPage(
        items=items,
        next_cursor=encode_inbox_cursor(context, view, limit, page[-1].created_at, page[-1].id)
        if more
        else None,
        history_exhausted=not more,
    )


def _one_inbox_record(session, context, notification_id):
    target = eligible_inbox_targets(session, context, (notification_id,)).get(notification_id)
    note = (
        session.scalar(
            select(InAppNotification)
            .where(
                InAppNotification.id == notification_id,
                InAppNotification.company_id == context.company.id,
                InAppNotification.recipient_membership_id == context.membership.id,
            )
            .execution_options(populate_existing=True)
        )
        if target
        else None
    )
    if note is None:
        raise HTTPException(404, "Notification not found.")
    kind, target_id, label = target
    return InboxRecord(
        id=note.id,
        title="Hearing reminder" if note.source_type == "hearing_reminder" else "IP renewal alert",
        body="Open the current record to review its details.",
        status=note.status,
        created_at=_utc(note.created_at),
        read_at=_utc(note.read_at) if note.read_at is not None else None,
        target=InboxTarget(kind=kind, id=target_id),
        target_label=label,
    )


def update_inbox_record(session, *, context, notification_id, payload):
    """Change only this recipient's receipt, under the canonical parent fence."""
    from caseops_api.services.in_app_notifications import update_recipient_notification
    from caseops_api.services.matters import _get_matter_model

    current = _one_inbox_record(session, context, notification_id)
    if current.target.kind == "ip_docket":
        from caseops_api.services.ip_docket_access import _docket_or_404

        _docket_or_404(
            session,
            context=context,
            docket_id=current.target.id,
            for_update=True,
            required_capability="ip:read",
        )
        # Hold the receipt through the global sole-link check and canonical
        # mutation. A second, even ineligible, link must not be ignored by the
        # narrower per-docket reader and discovered only after the commit.
        owned = session.scalar(
            select(InAppNotification.id)
            .where(
                InAppNotification.id == notification_id,
                InAppNotification.company_id == context.company.id,
                InAppNotification.recipient_membership_id == context.membership.id,
            )
            .with_for_update()
        )
        if owned is None or eligible_inbox_targets(session, context, (notification_id,)).get(
            notification_id
        ) != (current.target.kind, current.target.id, current.target_label):
            raise HTTPException(404, "Notification not found.")
        update_recipient_notification(
            session,
            context=context,
            docket_id=current.target.id,
            notification_id=notification_id,
            payload=payload,
        )
        return _one_inbox_record(session, context, notification_id)

    # Read access is sufficient to manage an owned receipt. No Matter-write,
    # staff, founder or other tenant authority is fabricated for this action.
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    actor = memberships.get(context.membership.id)
    if actor is None or not actor.is_active or actor.user is None or not actor.user.is_active:
        raise HTTPException(403, "An active membership is required.")
    context.membership, context.user = actor, actor.user
    _get_matter_model(
        session,
        context=context,
        matter_id=current.target.id,
        lock_for_update=True,
        load_locked_children=False,
        commit_access_denial=False,
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
    if note is None or eligible_inbox_targets(session, context, (notification_id,)).get(
        notification_id
    ) != (current.target.kind, current.target.id, current.target_label):
        raise HTTPException(404, "Notification not found.")
    if note.status != payload.status:
        if note.status != payload.expected_status:
            raise HTTPException(409, "Notification changed. Reload its current state.")
        before = note.status
        note.status = payload.status
        if payload.status == "read" and note.read_at is None:
            note.read_at = datetime.now(UTC)
        record_from_context(
            session,
            context,
            action="in_app_notification.status_changed",
            target_type="in_app_notification",
            target_id=note.id,
            matter_id=current.target.id,
            metadata={"before": before, "after": note.status},
        )
        session.add(note)
        session.commit()
    return _one_inbox_record(session, context, notification_id)
