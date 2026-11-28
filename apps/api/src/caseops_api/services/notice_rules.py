"""Business rules for primary notices, shared by every notice write path.

A notice reaches the database through four writers: the matter Notices upload
(``POST /api/matters/{id}/attachments`` with ``document_type=notice``), the
matter attachment metadata PATCH, the company notice register create and the
register PATCH.  Every one of them builds a :class:`NoticeState` and asks this
module for violations, so a rule cannot be enforced on one path and forgotten
on another.  The web forms mirror these rules field by field
(``apps/web/lib/notice-rules.ts``); the API remains the authority.

Edits are judged by :func:`new_notice_violations`: a PATCH may not introduce a
violation, but a legacy row that already broke a rule before these rules
existed can still receive unrelated edits (for example ``Mark reply sent``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

# UTC+14 is the latest civil time zone.  A date counts as "in the future" only
# when it is after today everywhere, so a user east of the server is never
# refused their own today.  Browsers apply the stricter local-today bound.
_LATEST_CIVIL_ZONE = timezone(timedelta(hours=14))

NOTICE_DIRECTIONS = ("received", "sent")

# Every notice date must fall in this window; outside it is a typing slip.
NOTICE_MIN_DATE = date(1900, 1, 1)
NOTICE_MAX_DATE = date(2100, 12, 31)
NOTICE_DATE_RANGE_MESSAGE = "Enter a date between 1900 and 2100."


def notice_today() -> date:
    return datetime.now(_LATEST_CIVIL_ZONE).date()


@dataclass(frozen=True)
class NoticeState:
    direction: str
    subject: str | None
    notice_type: str | None
    received_on: date | None
    sent_on: date | None
    reply_required: bool
    reply_sent: bool
    reply_due_on: date | None
    reply_sent_on: date | None
    amount_minor: int | None
    dispute_amount_minor: int | None
    recovered_amount_minor: int | None


@dataclass(frozen=True)
class NoticeRuleViolation:
    """One failed rule.  ``field`` is the canonical register field name."""

    field: str
    code: str
    message: str


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def notice_rule_violations(
    state: NoticeState,
    *,
    today: date | None = None,
) -> list[NoticeRuleViolation]:
    today = today or notice_today()
    received = state.direction != "sent"
    violations: list[NoticeRuleViolation] = []

    def add(field: str, code: str, message: str) -> None:
        violations.append(NoticeRuleViolation(field, code, message))

    def in_range(field: str, value: date | None) -> bool:
        # A browser date control completes a half-typed year as 0001 or 0020;
        # such a date is real to the calendar but never a notice date.
        if value is None or NOTICE_MIN_DATE <= value <= NOTICE_MAX_DATE:
            return True
        add(field, f"{field}_out_of_range", NOTICE_DATE_RANGE_MESSAGE)
        return False

    received_on = state.received_on if in_range("received_on", state.received_on) else None
    if received:
        if state.received_on is None:
            add("received_on", "received_on_required", "Enter the date of receipt.")
        elif received_on is not None and received_on > today:
            add(
                "received_on",
                "received_on_in_future",
                "Date of receipt cannot be in the future.",
            )
    else:
        if state.sent_on is None:
            add("sent_on", "sent_on_required", "Enter the notice sent date.")
        elif in_range("sent_on", state.sent_on) and state.sent_on > today:
            add("sent_on", "sent_on_in_future", "Notice sent date cannot be in the future.")
    if _blank(state.subject):
        add("subject", "subject_required", "Enter the notice subject.")
    if _blank(state.notice_type):
        add("type", "type_required", "Enter the type of notice.")

    if received:
        if state.reply_required and not state.reply_sent and state.reply_due_on is None:
            add(
                "reply_due_on",
                "reply_due_on_required",
                "Enter the reply due date, or clear Reply required.",
            )
        if (
            in_range("reply_due_on", state.reply_due_on)
            and state.reply_due_on is not None
            and received_on is not None
            and state.reply_due_on < received_on
        ):
            add(
                "reply_due_on",
                "reply_due_on_before_receipt",
                "Reply due date cannot be earlier than the date of receipt.",
            )
        if state.reply_sent_on is not None and in_range("reply_sent_on", state.reply_sent_on):
            if received_on is not None and state.reply_sent_on < received_on:
                add(
                    "reply_sent_on",
                    "reply_sent_on_before_receipt",
                    "Reply sent date cannot be earlier than the date of receipt.",
                )
            elif state.reply_sent_on > today:
                add(
                    "reply_sent_on",
                    "reply_sent_on_in_future",
                    "Reply sent date cannot be in the future.",
                )

    for field, value, label in (
        ("amount_minor", state.amount_minor, "Amount"),
        ("dispute_amount_minor", state.dispute_amount_minor, "Dispute amount"),
        ("recovered_amount_minor", state.recovered_amount_minor, "Recovered amount"),
    ):
        if value is not None and value < 0:
            add(field, f"{field}_negative", f"{label} cannot be negative.")
    if (
        not received
        and state.dispute_amount_minor is not None
        and state.recovered_amount_minor is not None
        and 0 <= state.dispute_amount_minor < state.recovered_amount_minor
    ):
        add(
            "recovered_amount_minor",
            "recovered_exceeds_dispute",
            "Recovered amount cannot exceed the dispute amount.",
        )
    return violations


def new_notice_violations(
    before: NoticeState | None,
    after: NoticeState,
    *,
    today: date | None = None,
) -> list[NoticeRuleViolation]:
    """Violations ``after`` has that ``before`` did not already have."""

    today = today or notice_today()
    existing = (
        {(item.field, item.code) for item in notice_rule_violations(before, today=today)}
        if before is not None
        else set()
    )
    return [
        item
        for item in notice_rule_violations(after, today=today)
        if (item.field, item.code) not in existing
    ]


def raise_notice_violations(
    violations: list[NoticeRuleViolation],
    *,
    field_prefix: str = "",
) -> None:
    """Refuse the write with one RFC 7807 ``errors[]`` entry per field.

    ``field_prefix`` maps canonical names to the caller's own parameter names
    (``notice_`` on the matter attachment form), so a client can anchor each
    message to the input it came from.
    """

    if not violations:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=[
            {
                "loc": ["body", f"{field_prefix}{item.field}"],
                "msg": item.message,
                "type": f"notice_{item.code}",
            }
            for item in violations
        ],
    )


_WHITESPACE = re.compile(r"\s+")


def normalized_notice_text(value: str | None) -> str:
    """Comparison key for duplicate detection: case- and spacing-insensitive."""

    return _WHITESPACE.sub(" ", value or "").strip().casefold()


# (direction, business date, subject, counterparty), normalized.  The one
# definition of "the same details" for both notice stores: a register notice
# and a notice attached to a matter are compared with this same key.
NoticeDuplicateKey = tuple[str, date | None, str, str]


def notice_duplicate_key(
    *,
    direction: str | None,
    received_on: date | None,
    sent_on: date | None,
    subject: str | None,
    counterparty: str | None,
) -> NoticeDuplicateKey:
    sent = direction == "sent"
    return (
        "sent" if sent else "received",
        sent_on if sent else received_on,
        normalized_notice_text(subject),
        normalized_notice_text(counterparty),
    )


def attachment_notice_duplicate_key(attachment: Any) -> NoticeDuplicateKey:
    """Key of a primary notice stored as a matter attachment."""

    sent = attachment.notice_direction == "sent"
    return notice_duplicate_key(
        direction=attachment.notice_direction,
        received_on=attachment.notice_received_on,
        sent_on=attachment.notice_sent_on,
        subject=attachment.notice_subject,
        counterparty=(
            attachment.notice_authority
            if sent
            else attachment.notice_received_from or attachment.notice_source
        ),
    )


def register_notice_duplicate_key(notice: Any) -> NoticeDuplicateKey:
    """Key of a company register notice (a row or a create payload)."""

    sent = notice.direction == "sent"
    return notice_duplicate_key(
        direction=notice.direction,
        received_on=notice.received_on,
        sent_on=notice.sent_on,
        subject=notice.subject,
        counterparty=notice.authority if sent else notice.received_from,
    )


def lock_notice_duplicate_key(
    session: Session,
    *,
    company_id: str,
    key: NoticeDuplicateKey,
) -> None:
    """Serialize same-details register writes in one tenant on PostgreSQL.

    A register notice has no parent row both writers would lock, so two
    concurrent identical creates (or an edit racing a create) could each pass
    the duplicate check.  The transaction-scoped advisory lock makes the second
    writer wait until the first commits and then see its row.  Register writers
    take it before they lock any linked Matter, and matter writers never take
    it, so it cannot join a lock cycle with the Matter lock that serializes a
    matter's own notice writes.  SQLite serializes writers already.
    """

    if session.get_bind().dialect.name != "postgresql":
        return
    direction, business_date, subject, counterparty = key
    material = "\x1f".join(
        (
            "notice-duplicate",
            company_id,
            direction,
            business_date.isoformat() if business_date else "",
            subject,
            counterparty,
        )
    )
    lock_key = int.from_bytes(
        hashlib.sha256(material.encode()).digest()[:8], byteorder="big", signed=True,
    )
    session.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


def notice_duplicate_conflict(
    *,
    kind: str,
    existing_id: str,
    existing_subject: str | None,
    existing_direction: str,
    existing_date: date | None,
    existing_filename: str | None,
    scope: str = "this matter",
    existing_source_kind: str = "legacy_attachment",
    existing_matter_id: str | None = None,
) -> HTTPException:
    """409 naming the notice the caller would duplicate.

    ``same_file`` is never overridable: identical bytes are already on record.
    ``same_details`` may be a genuinely separate notice (two notices served the
    same day with the same subject), so the caller may resubmit with
    ``allow_duplicate``; that override is audited.  ``source_kind`` says which
    store holds the existing notice (``standalone`` register row or a matter
    ``legacy_attachment`` on ``matter_id``) so a client can link to it.
    """

    same_file = kind == "same_file"
    message = (
        f"This file is already attached to {scope} as a notice."
        if same_file
        else (
            "A notice with the same direction, date, subject and counterparty "
            "already exists."
        )
    )
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "type": "notice_duplicate",
            "message": message,
            "duplicate_kind": kind,
            "override_allowed": not same_file,
            "existing_notice": {
                "id": existing_id,
                "subject": existing_subject,
                "direction": existing_direction,
                "notice_date": existing_date.isoformat() if existing_date else None,
                "filename": existing_filename,
                "source_kind": existing_source_kind,
                "matter_id": existing_matter_id,
            },
        },
    )


__all__ = [
    "NOTICE_DATE_RANGE_MESSAGE",
    "NOTICE_DIRECTIONS",
    "NOTICE_MAX_DATE",
    "NOTICE_MIN_DATE",
    "NoticeDuplicateKey",
    "NoticeRuleViolation",
    "NoticeState",
    "attachment_notice_duplicate_key",
    "lock_notice_duplicate_key",
    "new_notice_violations",
    "normalized_notice_text",
    "notice_duplicate_conflict",
    "notice_duplicate_key",
    "register_notice_duplicate_key",
    "notice_rule_violations",
    "notice_today",
    "raise_notice_violations",
]
