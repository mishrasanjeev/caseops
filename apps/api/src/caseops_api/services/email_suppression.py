"""Tenant-scoped email suppression — write path (from SendGrid webhook
events) and read path (pre-flight check before send).

Auth-flow mailers (account setup, password reset, portal access) MUST
NOT consult this list. A user who unsubscribed from matter mail must
still be able to reset their password. Each call site that wants
suppression checking calls ``is_suppressed`` explicitly; the function
is not bolted onto the SendGrid send helper.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import EmailSuppression, EmailSuppressionReason

# SendGrid event names that translate to a suppression entry. Anything
# not in this map is left to the per-row event handlers (delivered /
# open / click / deferred) that don't write suppressions.
_EVENT_TO_REASON: dict[str, EmailSuppressionReason] = {
    "bounce": EmailSuppressionReason.BOUNCE,
    "dropped": EmailSuppressionReason.DROPPED,
    "spamreport": EmailSuppressionReason.SPAM_REPORT,
    "spam_report": EmailSuppressionReason.SPAM_REPORT,
    "unsubscribe": EmailSuppressionReason.UNSUBSCRIBE,
    "group_unsubscribe": EmailSuppressionReason.GROUP_UNSUBSCRIBE,
    "groupunsubscribe": EmailSuppressionReason.GROUP_UNSUBSCRIBE,
}


def reason_for_event(event_name: str) -> EmailSuppressionReason | None:
    """Map a SendGrid event name to an ``EmailSuppressionReason``.

    Returns ``None`` for events that should not produce a suppression
    (delivered, open, click, deferred, processed). Caller decides how
    to use the result.
    """
    return _EVENT_TO_REASON.get((event_name or "").strip().lower())


def is_suppressed(
    session: Session,
    *,
    company_id: str,
    recipient_email: str,
) -> EmailSuppression | None:
    """Return the suppression row for ``recipient_email`` in this
    tenant if one exists, else ``None``. Lower-cased for matching.
    """
    if not recipient_email:
        return None
    return session.scalar(
        select(EmailSuppression).where(
            EmailSuppression.company_id == company_id,
            EmailSuppression.recipient_email == recipient_email.strip().lower(),
            EmailSuppression.recovered_at.is_(None),
        )
    )


def record_suppression(
    session: Session,
    *,
    company_id: str,
    recipient_email: str,
    reason: EmailSuppressionReason,
    detail: str | None = None,
    source_message_id: str | None = None,
) -> EmailSuppression:
    """Idempotent upsert. If a row exists for this
    ``(company_id, recipient_email)`` pair, refresh ``reason`` /
    ``detail`` / ``source_message_id`` / ``last_event_at`` so the
    operator surface always shows the most recent reason. Otherwise
    insert a new row.

    Returns the persisted row. Caller is responsible for committing
    the session — this matches the webhook handler's batch-commit
    pattern in ``api.routes.notifications.sendgrid_events``.
    """
    from datetime import UTC, datetime

    normalised = recipient_email.strip().lower()
    if not normalised:
        raise ValueError("recipient_email is required")

    existing = session.scalar(
        select(EmailSuppression).where(
            EmailSuppression.company_id == company_id,
            EmailSuppression.recipient_email == normalised,
        )
    )
    now = datetime.now(UTC)
    if existing is not None:
        # Re-applying a webhook event for the same address bumps
        # last_event_at and refreshes reason/detail. Keeps the most
        # recent context visible without losing the original
        # created_at.
        existing.reason = reason.value
        if detail is not None:
            existing.detail = detail[:500] if detail else None
        if source_message_id is not None:
            existing.source_message_id = source_message_id
        existing.last_event_at = now
        existing.recovered_at = None
        existing.recovered_by_membership_id = None
        existing.recovery_action = None
        return existing

    row = EmailSuppression(
        company_id=company_id,
        recipient_email=normalised,
        reason=reason.value,
        detail=detail[:500] if detail else None,
        source_message_id=source_message_id,
        last_event_at=now,
        first_event_at=now,
        created_at=now,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        # Race: another worker committed the row between our SELECT
        # and INSERT. Roll back and refetch — the unique constraint
        # held the line. Caller's outer transaction continues.
        session.rollback()
        return session.scalar(
            select(EmailSuppression).where(
                EmailSuppression.company_id == company_id,
                EmailSuppression.recipient_email == normalised,
            )
        )  # type: ignore[return-value]
    return row


def recover_suppression(
    session: Session,
    *,
    suppression: EmailSuppression,
    recovered_by_membership_id: str,
    recovery_action: str,
) -> EmailSuppression:
    """Deactivate a suppression without deleting its provider evidence."""
    from datetime import UTC, datetime

    action = " ".join(recovery_action.split())
    if len(action) < 8:
        raise ValueError("A specific suppression recovery action is required.")
    suppression.recovered_at = datetime.now(UTC)
    suppression.recovered_by_membership_id = recovered_by_membership_id
    suppression.recovery_action = action[:500]
    session.add(suppression)
    session.flush()
    return suppression


__all__ = [
    "is_suppressed",
    "reason_for_event",
    "recover_suppression",
    "record_suppression",
]
