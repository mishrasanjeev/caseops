"""Hearing reminder scheduling + worker (MOD-TS-007 / Sprint T slice).

Dark-launched on 2026-04-22. Three moving parts:

1. :func:`schedule_reminders_for_hearing` — called from
   ``services.matters.create_matter_hearing`` (and when a hearing is
   rescheduled). Creates one ``HearingReminder`` row per
   ``settings.hearing_reminder_offsets_hours`` × eligible recipient.
   Offsets in the past are skipped — no "you have a hearing in
   -4 hours" emails.

2. :func:`cancel_reminders_for_hearing` — called when a hearing is
   cancelled. Flips pending rows to ``CANCELLED`` so the worker
   skips them.

3. :func:`run_reminder_worker` — idempotent pull-and-send loop.
   Honours ``settings.hearing_reminders_enabled`` as the flip that
   turns dark-launch into live delivery. When the flag is OFF (or
   the SendGrid key is missing), it **logs "would send"** and leaves
   rows at ``QUEUED`` so flipping the flag later starts real sends
   without a backfill.

The provider integration is pluggable: ``_send_via_sendgrid`` is the
only real path today. MSG91 SMS drops in alongside it when creds are
available.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    HearingReminder,
    HearingReminderChannel,
    HearingReminderStatus,
    MatterHearing,
    User,
)

logger = logging.getLogger(__name__)


def _hearing_start_at(hearing: MatterHearing) -> datetime:
    """Pin a UTC-aware datetime for the hearing. ``hearing_on`` is a
    Date; we treat the hearing as starting at 10:00 IST (~04:30 UTC)
    for reminder purposes. When we add explicit time fields to
    ``MatterHearing`` this helper becomes a straight read."""
    return datetime.combine(
        hearing.hearing_on, time(4, 30), tzinfo=UTC,
    )


def _as_utc(value: datetime) -> datetime:
    """Normalise datetimes to UTC-aware. SQLite round-trips tz-naive
    values (it has no timezone support), so some comparisons blow up
    without this coercion even though prod Postgres stores + returns
    them tz-aware."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _eligible_recipients(
    session: Session, *, hearing: MatterHearing,
) -> list[tuple[str | None, str | None]]:
    """Return ``(membership_id, email)`` tuples for the owners / admins
    / partners on the hearing's matter. We start with the matter's
    assignee when present and fall back to the workspace's active
    owner so a solo-practice tenant always has at least one target.
    """
    # Membership via assignee, then via owner/admin/partner in the company.
    targets: list[tuple[str | None, str | None]] = []
    seen: set[str] = set()
    matter = hearing.matter
    if matter.assignee_membership and matter.assignee_membership.user:
        mid = matter.assignee_membership.id
        email = matter.assignee_membership.user.email
        if email and mid not in seen:
            targets.append((mid, email))
            seen.add(mid)
    stmt = (
        select(CompanyMembership)
        .join(User, CompanyMembership.user_id == User.id)
        .where(
            CompanyMembership.company_id == matter.company_id,
            CompanyMembership.is_active.is_(True),
            CompanyMembership.role.in_(("owner", "admin", "partner")),
        )
    )
    for m in session.scalars(stmt):
        if m.user is None or not m.user.email:
            continue
        if m.id in seen:
            continue
        targets.append((m.id, m.user.email))
        seen.add(m.id)
    return targets


def schedule_reminders_for_hearing(
    session: Session, *, hearing: MatterHearing,
) -> list[HearingReminder]:
    """Create :class:`HearingReminder` rows for each configured
    offset × eligible recipient. Idempotent — the uniqueness
    constraint on ``(hearing_id, channel, scheduled_for)`` means a
    second call on the same hearing is a no-op (we catch IntegrityError
    and skip).
    """
    settings = get_settings()
    offsets = settings.hearing_reminder_offsets_hours or []
    if not offsets:
        return []
    hearing_at = _hearing_start_at(hearing)
    now = datetime.now(UTC)
    recipients = _eligible_recipients(session, hearing=hearing)
    if not recipients:
        return []

    created: list[HearingReminder] = []
    for offset_h in offsets:
        send_at = hearing_at - timedelta(hours=int(offset_h))
        if send_at <= now:
            # Hearing is too close; skip the "T-24h" reminder once T-24h
            # is already in the past. The sooner offsets can still fire.
            continue
        for membership_id, email in recipients:
            reminder = HearingReminder(
                company_id=hearing.matter.company_id,
                matter_id=hearing.matter_id,
                hearing_id=hearing.id,
                recipient_membership_id=membership_id,
                recipient_email=email,
                channel=HearingReminderChannel.EMAIL,
                scheduled_for=send_at,
                status=HearingReminderStatus.QUEUED,
            )
            # Use a nested transaction (SAVEPOINT) so an
            # IntegrityError on this single reminder doesn't roll back
            # the enclosing hearing-create transaction. A full
            # ``session.rollback()`` here would nuke the hearing row
            # the caller JUST inserted — observed as "MatterHearing
            # not persistent" in test_company_profile_and_matters.
            sp = session.begin_nested()
            try:
                session.add(reminder)
                session.flush()
                sp.commit()
                created.append(reminder)
            except IntegrityError:
                # Another concurrent create beat us — safe to skip.
                sp.rollback()
                continue
    return created


def cancel_reminders_for_hearing(
    session: Session, *, hearing_id: str,
) -> int:
    """Flip every pending reminder for ``hearing_id`` to CANCELLED.
    Called when the caller rescheduled or cancelled a hearing so the
    old reminders don't fire against a stale time.
    """
    pending = list(
        session.scalars(
            select(HearingReminder).where(
                HearingReminder.hearing_id == hearing_id,
                HearingReminder.status == HearingReminderStatus.QUEUED,
            )
        )
    )
    for r in pending:
        r.status = HearingReminderStatus.CANCELLED
    return len(pending)


def _sendgrid_configured() -> bool:
    settings = get_settings()
    return bool(settings.sendgrid_api_key and settings.sendgrid_sender_email)


def _render_email(
    *,
    hearing: MatterHearing,
    recipient_email: str,
    offset_hours: float,
) -> tuple[str, str, str]:
    """Render (subject, html, plaintext). Keep the body short and
    factual — lawyers skim reminder emails. Link back to the matter
    cockpit so the reader can open the hearing page in one click."""
    matter = hearing.matter
    forum = hearing.forum_name or matter.court_name or "the scheduled forum"
    when = hearing.hearing_on.isoformat()
    subject = (
        f"Hearing in ~{int(round(offset_hours))}h · "
        f"{matter.matter_code} · {when}"
    )
    matter_url = f"https://caseops.ai/app/matters/{matter.id}/hearings"
    purpose = hearing.purpose or "Hearing"
    judge = f" (before {hearing.judge_name})" if hearing.judge_name else ""
    plaintext = (
        f"Hi,\n\n"
        f"Reminder: {purpose} on {when} at {forum}{judge}.\n\n"
        f"Matter: {matter.title} ({matter.matter_code})\n"
        f"Cockpit: {matter_url}\n\n"
        f"— CaseOps"
    )
    html = (
        f"<p>Reminder: <strong>{purpose}</strong> on <strong>{when}</strong> "
        f"at <strong>{forum}</strong>{judge}.</p>"
        f"<p>Matter: <a href='{matter_url}'>{matter.title} "
        f"({matter.matter_code})</a></p>"
        f"<p style='color:#6d727a;font-size:12px'>— CaseOps</p>"
    )
    _ = recipient_email  # reserved for per-recipient personalisation later
    return subject, html, plaintext


def _send_via_sendgrid(
    *,
    to_email: str,
    subject: str,
    html: str,
    plaintext: str,
) -> tuple[bool, str | None, str | None]:
    """Return ``(success, provider_message_id, error)``.

    Uses the SendGrid Web API directly via httpx to avoid pulling in
    the full ``sendgrid`` Python SDK for a single endpoint.
    """
    import httpx

    settings = get_settings()
    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {
                "email": settings.sendgrid_sender_email,
                "name": settings.sendgrid_sender_name,
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": plaintext},
                {"type": "text/html", "value": html},
            ],
        },
        timeout=20,
    )
    if response.status_code in (200, 202):
        # SendGrid returns the X-Message-Id header on accept; useful
        # for tying webhook deliveries back to this row.
        msg_id = response.headers.get("X-Message-Id") or response.headers.get(
            "x-message-id"
        )
        return True, msg_id, None
    return (
        False,
        None,
        f"sendgrid {response.status_code}: {response.text[:200]}",
    )


# MOD-TS-007 (2026-04-26) — SMS via Twilio. Gated by
# ``CASEOPS_TWILIO_ENABLED=true`` so the default deployment never
# burns money on a test SMS. Required env when enabled:
#   CASEOPS_TWILIO_ACCOUNT_SID
#   CASEOPS_TWILIO_AUTH_TOKEN
#   CASEOPS_TWILIO_FROM_NUMBER
#
# Cost discipline: each SMS costs ~₹0.50–₹2.00 in India depending on
# length + alphanumeric sender registration. The reminder worker still
# respects the per-hearing/per-channel uniqueness constraint, so this
# never doubles the bill on a retry.
def _twilio_sms_configured() -> bool:
    settings = get_settings()
    return bool(
        getattr(settings, "twilio_enabled", False)
        and getattr(settings, "twilio_account_sid", None)
        and getattr(settings, "twilio_auth_token", None)
        and getattr(settings, "twilio_from_number", None)
    )


def _send_via_twilio_sms(
    *, to_phone: str, body: str,
) -> tuple[bool, str | None, str | None]:
    """Return ``(success, provider_message_id, error)``.

    Twilio's Messages API. Uses httpx directly + basic-auth rather
    than the SDK to keep the install footprint small. Truncates body
    at 1500 chars (Twilio caps at 1600 for concatenated SMS in India).
    """
    import httpx

    settings = get_settings()
    sid = settings.twilio_account_sid
    token = settings.twilio_auth_token
    from_number = settings.twilio_from_number
    payload = {
        "From": from_number,
        "To": to_phone,
        "Body": body[:1500],
    }
    response = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        auth=(sid, token),
        data=payload,
        timeout=20,
    )
    if response.status_code in (200, 201):
        try:
            msg_id = response.json().get("sid")
        except Exception:  # noqa: BLE001
            msg_id = None
        return True, msg_id, None
    return (
        False,
        None,
        f"twilio {response.status_code}: {response.text[:200]}",
    )


def _whatsapp_configured() -> bool:
    """WhatsApp via Meta Cloud API. Requires Meta-approved templates
    so this stays a hard 'not configured' until both
    ``CASEOPS_WHATSAPP_ENABLED=true`` and the per-deployment template
    name + access token + phone-number-id env vars land."""
    settings = get_settings()
    return bool(
        getattr(settings, "whatsapp_enabled", False)
        and getattr(settings, "whatsapp_access_token", None)
        and getattr(settings, "whatsapp_phone_number_id", None)
        and getattr(settings, "whatsapp_template_name", None)
    )


def run_reminder_worker(
    session: Session,
    *,
    now: datetime | None = None,
    limit: int = 100,
    mode: Literal["auto", "dry_run", "live"] = "auto",
) -> dict:
    """Pull QUEUED reminders whose ``scheduled_for`` has passed and
    dispatch them. Returns a telemetry dict.

    ``mode``:
      * ``auto`` — send when the feature flag + provider are both
        configured; otherwise log "would send" and leave QUEUED.
      * ``dry_run`` — never send. Useful for ops smoke.
      * ``live`` — always attempt send; fail loudly if the provider
        isn't configured. For emergency manual runs only.

    Safe to call repeatedly — every row is status-scoped so the next
    call skips ones already SENT / DELIVERED / FAILED / CANCELLED.
    """
    settings = get_settings()
    now = _as_utc(now or datetime.now(UTC))
    # SQLite is tz-naive (stores a bare ISO string), so we bind a
    # tz-naive UTC equivalent for the DB compare. Postgres accepts
    # both and normalises. A belt-and-braces Python filter ensures
    # correctness even if a dialect quirk lets a future row through.
    now_for_db = now.replace(tzinfo=None)
    due_raw = list(
        session.scalars(
            select(HearingReminder)
            .where(
                HearingReminder.status == HearingReminderStatus.QUEUED,
                HearingReminder.scheduled_for <= now_for_db,
            )
            .order_by(HearingReminder.scheduled_for.asc())
            .limit(limit)
        )
    )
    due = [r for r in due_raw if _as_utc(r.scheduled_for) <= now]

    enabled = settings.hearing_reminders_enabled
    # Per-channel provider status. The auto-mode "live?" decision uses
    # email's status as the canonical signal (back-compat with the
    # pre-multichannel behaviour); per-row dispatch checks the
    # channel-specific provider before sending.
    provider_ok = _sendgrid_configured()
    sms_provider_ok = _twilio_sms_configured()
    whatsapp_provider_ok = _whatsapp_configured()
    if mode == "auto":
        effective_live = enabled and provider_ok
    elif mode == "dry_run":
        effective_live = False
    elif mode == "live":
        if not provider_ok:
            raise RuntimeError(
                "run_reminder_worker(mode='live') requires SendGrid "
                "credentials; set CASEOPS_SENDGRID_API_KEY + "
                "CASEOPS_SENDGRID_SENDER_EMAIL."
            )
        effective_live = True
    else:  # pragma: no cover — guarded by Literal
        raise ValueError(f"unknown mode {mode!r}")

    report = {
        "mode": mode,
        "effective_live": effective_live,
        "enabled_flag": enabled,
        "provider_configured": provider_ok,
        "sms_provider_configured": sms_provider_ok,
        "whatsapp_provider_configured": whatsapp_provider_ok,
        "due_count": len(due),
        "sent": 0,
        "would_send": 0,
        "failed": 0,
        "skipped_missing_email": 0,
        "skipped_missing_phone": 0,
        "skipped_provider_disabled": 0,
    }

    for r in due:
        # Channel-specific recipient validation. Email needs an email;
        # SMS / WhatsApp need a phone. Missing-recipient is FAILED so
        # the dashboard surfaces it (operator must add a phone before
        # the worker can send).
        if r.channel == HearingReminderChannel.EMAIL and not r.recipient_email:
            r.status = HearingReminderStatus.FAILED
            r.last_error = "no recipient email on reminder row"
            r.updated_at = now
            report["skipped_missing_email"] += 1
            continue
        if r.channel in (
            HearingReminderChannel.SMS, HearingReminderChannel.WHATSAPP,
        ) and not r.recipient_phone:
            r.status = HearingReminderStatus.FAILED
            r.last_error = (
                f"no recipient phone on reminder row (channel={r.channel})"
            )
            r.updated_at = now
            report["skipped_missing_phone"] += 1
            continue

        hearing = session.get(MatterHearing, r.hearing_id)
        if hearing is None:
            r.status = HearingReminderStatus.CANCELLED
            r.updated_at = now
            continue

        hearing_at = _hearing_start_at(hearing)
        offset_hours = max(
            (hearing_at - _as_utc(r.scheduled_for)).total_seconds() / 3600.0,
            0.0,
        )
        subject, html, plaintext = _render_email(
            hearing=hearing,
            recipient_email=r.recipient_email or "",
            offset_hours=offset_hours,
        )
        r.attempts += 1

        if not effective_live:
            report["would_send"] += 1
            logger.info(
                "hearing_reminders: would send id=%s channel=%s to=%s "
                "subject=%r (mode=%s enabled=%s provider_ok=%s)",
                r.id, r.channel,
                r.recipient_email or r.recipient_phone, subject, mode,
                enabled, provider_ok,
            )
            # Leave status at QUEUED so live-flip later drains the
            # backlog. Update last_error so the dashboard shows
            # "stuck at queued" only when something real is blocking.
            r.last_error = None
            r.updated_at = now
            continue

        # Channel-aware dispatch. Per-channel provider check happens
        # here (not at the top of the loop) so EMAIL rows still send
        # even if SMS/WhatsApp aren't wired — channels degrade
        # independently.
        if r.channel == HearingReminderChannel.EMAIL:
            success, msg_id, err = _send_via_sendgrid(
                to_email=r.recipient_email or "",
                subject=subject,
                html=html,
                plaintext=plaintext,
            )
            r.provider = "sendgrid"
        elif r.channel == HearingReminderChannel.SMS:
            if not sms_provider_ok:
                # SMS adapter disabled or unconfigured. Don't burn
                # money, don't fail the row — leave QUEUED so a
                # later live-flip drains the backlog.
                report["skipped_provider_disabled"] += 1
                r.last_error = (
                    "SMS provider disabled (set CASEOPS_TWILIO_ENABLED=true "
                    "and provide CASEOPS_TWILIO_ACCOUNT_SID + "
                    "CASEOPS_TWILIO_AUTH_TOKEN + CASEOPS_TWILIO_FROM_NUMBER)"
                )
                r.updated_at = now
                continue
            success, msg_id, err = _send_via_twilio_sms(
                to_phone=r.recipient_phone or "",
                body=plaintext,
            )
            r.provider = "twilio"
        elif r.channel == HearingReminderChannel.WHATSAPP:
            # WhatsApp Cloud API requires Meta-approved templates +
            # tenant-level template name. Stub stays "not configured"
            # until the deployment opts in. Leave QUEUED so the
            # operator can flip the env var later without losing rows.
            report["skipped_provider_disabled"] += 1
            r.last_error = (
                "WhatsApp provider disabled (set CASEOPS_WHATSAPP_ENABLED=true "
                "with CASEOPS_WHATSAPP_ACCESS_TOKEN + "
                "CASEOPS_WHATSAPP_PHONE_NUMBER_ID + "
                "CASEOPS_WHATSAPP_TEMPLATE_NAME after Meta template approval)"
            )
            r.updated_at = now
            continue
        else:
            # IN_APP or unknown channel — handled by the in-app
            # reminders surface, not this worker.
            report["skipped_provider_disabled"] += 1
            r.last_error = (
                f"channel {r.channel!r} is not handled by the email/SMS "
                "worker"
            )
            r.updated_at = now
            continue

        r.updated_at = now
        if success:
            r.status = HearingReminderStatus.SENT
            r.sent_at = now
            r.provider_message_id = msg_id
            r.last_error = None
            report["sent"] += 1
        else:
            r.status = HearingReminderStatus.FAILED
            r.last_error = err
            report["failed"] += 1

    session.commit()
    return report


def apply_sendgrid_event(
    session: Session, *, event: dict,
) -> bool:
    """Update a ``HearingReminder`` row from a single SendGrid event.

    Events we care about — full list at
    https://docs.sendgrid.com/for-developers/tracking-events/event —
    are ``delivered`` / ``bounce`` / ``dropped`` / ``deferred`` /
    ``open`` / ``click`` / ``spamreport``. We match the row by
    ``sg_message_id`` (header SendGrid echoes back into event JSON).

    Returns True when a row was updated, False when no match or the
    event type wasn't one we track. Idempotent — re-applying the same
    event is a no-op (we only forward-move status).
    """
    sg_message_id = event.get("sg_message_id") or event.get("smtp-id")
    if not sg_message_id:
        return False
    # SendGrid's sg_message_id is ``<msg-id>.filterdrecvN-…`` — the
    # prefix up to the first dot matches the X-Message-Id header we
    # captured at send time.
    prefix = sg_message_id.split(".", 1)[0]
    candidates = list(
        session.scalars(
            select(HearingReminder).where(
                HearingReminder.provider_message_id.like(f"{prefix}%")
            )
        )
    )
    if not candidates:
        return False
    event_type = (event.get("event") or "").lower()
    ts = event.get("timestamp")
    when = (
        datetime.fromtimestamp(int(ts), tz=UTC) if ts else datetime.now(UTC)
    )
    updated = False
    for row in candidates:
        prior = row.status
        if event_type in ("delivered",):
            row.status = HearingReminderStatus.DELIVERED
            row.delivered_at = when
        elif event_type in ("bounce", "dropped", "blocked", "spamreport"):
            row.status = HearingReminderStatus.FAILED
            row.last_error = (
                f"sendgrid:{event_type}: {event.get('reason') or event.get('response') or ''}"
            )[:500]
        else:
            # open / click / deferred — log but don't regress status.
            continue
        row.updated_at = when
        if row.status != prior:
            updated = True
    return updated


def list_reminders_for_matter(
    session: Session, *, company_id: str, matter_id: str,
) -> list[HearingReminder]:
    """Strict Ledger #5 (BUG-013 in-app visibility): tenant-scoped
    per-matter reminders, ordered by scheduled_for descending so
    the most recent / next-up rows render first. Both the admin
    notifications page and the per-matter cockpit Hearings tab
    surface the same data — this helper is what the per-matter
    endpoint calls. Caller MUST have already verified the matter
    is in the caller's tenant."""
    return list(
        session.scalars(
            select(HearingReminder)
            .where(
                HearingReminder.company_id == company_id,
                HearingReminder.matter_id == matter_id,
            )
            .order_by(HearingReminder.scheduled_for.desc())
        )
    )


__all__ = [
    "schedule_reminders_for_hearing",
    "cancel_reminders_for_hearing",
    "list_reminders_for_matter",
    "run_reminder_worker",
    "apply_sendgrid_event",
]
