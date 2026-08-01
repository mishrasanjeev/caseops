from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    Company,
    CompanyMembership,
    InAppNotification,
    Matter,
    NotificationDeliveryChannel,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.matter_access import can_access
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.workflows.notification_intent_contracts import (
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
)

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|auth[_ -]?header|bearer|"
    r"client[_ -]?secret|private[_ -]?key|secret|signature|token|"
    r"webhook[_ -]?signature)\b\s*[:= ]\s*\S+"
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_.:-]{24,}\b")
_MAX_REDACTED_ERROR_LENGTH = 200
_MAX_INTENT_BODY_LENGTH = 500


@dataclass(frozen=True, slots=True)
class NotificationDeliveryProcessResult:
    intent_id: str
    status: str
    attempts: int
    delivered: bool
    external_calls: int
    retry_scheduled: bool
    dead_lettered: bool
    blocked: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_metadata(
    *,
    notification_rule_id: str | None,
    source_id: str,
    linked_court_order_id: str | None = None,
    triggered_by_membership_id: str | None = None,
) -> dict[str, object]:
    return {
        "notification_rule_ref": redact_identifier(notification_rule_id),
        "source_ref": redact_identifier(source_id),
        "linked_court_order_ref": redact_identifier(linked_court_order_id),
        "triggered_by_membership_ref": redact_identifier(triggered_by_membership_id),
        "has_linked_court_order": bool(linked_court_order_id),
        "has_triggering_membership": bool(triggered_by_membership_id),
    }


def _bounded_body(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    if len(cleaned) > _MAX_INTENT_BODY_LENGTH:
        return cleaned[: _MAX_INTENT_BODY_LENGTH - 3].rstrip() + "..."
    return cleaned


def notification_delivery_idempotency_key(
    *,
    company_id: str,
    recipient_membership_id: str,
    channel: str,
    event_type: str,
    source_type: str,
    source_id: str,
) -> str:
    raw = "|".join(
        (
            company_id,
            recipient_membership_id,
            channel,
            event_type,
            source_type,
            source_id,
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def redact_provider_error(value: object) -> str:
    text = str(value or "provider_error").strip() or "provider_error"
    text = _SECRET_ASSIGNMENT_RE.sub(r"\1=[redacted]", text)
    text = _URL_RE.sub("[url-redacted]", text)
    text = _EMAIL_RE.sub("[email-redacted]", text)
    text = _UUID_RE.sub("[id-redacted]", text)
    text = _PHONE_RE.sub("[phone-redacted]", text)
    text = _LONG_TOKEN_RE.sub("[token-redacted]", text)
    text = " ".join(text.split())
    if len(text) > _MAX_REDACTED_ERROR_LENGTH:
        return text[: _MAX_REDACTED_ERROR_LENGTH - 3].rstrip() + "..."
    return text


def retry_delay_for_attempt(attempts: int) -> timedelta:
    base = DEFAULT_RETRY_INITIAL_INTERVAL.total_seconds()
    max_delay = DEFAULT_RETRY_MAXIMUM_INTERVAL.total_seconds()
    exponent = max(0, attempts - 1)
    return timedelta(seconds=min(base * (2**exponent), max_delay))


def _delivery_result(intent: NotificationDeliveryIntent) -> NotificationDeliveryProcessResult:
    return NotificationDeliveryProcessResult(
        intent_id=intent.id,
        status=str(intent.status),
        attempts=intent.attempts,
        delivered=intent.status == NotificationDeliveryStatus.DELIVERED,
        external_calls=(
            1
            if intent.channel != NotificationDeliveryChannel.IN_APP
            and intent.provider_event_id is not None
            else 0
        ),
        retry_scheduled=intent.status == NotificationDeliveryStatus.RETRY_SCHEDULED,
        dead_lettered=intent.status == NotificationDeliveryStatus.DEAD_LETTER,
        blocked=intent.status == NotificationDeliveryStatus.BLOCKED,
    )


def _record_delivery_event(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    event_type: str,
    status_value: str,
    error: str | None = None,
    provider: str | None = None,
    provider_event_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    session.add(
        NotificationDeliveryEvent(
            company_id=intent.company_id,
            intent_id=intent.id,
            event_type=event_type,
            provider=provider,
            provider_event_id=provider_event_id,
            status=status_value,
            error_redacted=redact_provider_error(error) if error else None,
            metadata_json={
                "channel": str(intent.channel),
                "dispatch_owner": intent.dispatch_owner,
                "source_ref": redact_identifier(intent.source_id),
                **(metadata or {}),
            },
        )
    )


def _recipient_context(
    *,
    actor_context: SessionContext,
    membership: CompanyMembership,
) -> SessionContext:
    return SessionContext(
        company=actor_context.company,
        user=membership.user,
        membership=membership,
    )


def enqueue_notification_delivery_intent(
    session: Session,
    *,
    context: SessionContext,
    recipient_membership: CompanyMembership,
    channel: str,
    event_type: str,
    source_type: str,
    source_id: str,
    matter: Matter | None = None,
    notification_rule_id: str | None = None,
    title: str | None = None,
    body: str | None = None,
    linked_court_order_id: str | None = None,
) -> NotificationDeliveryIntent | None:
    if recipient_membership.company_id != context.company.id:
        return None
    if matter is not None:
        if matter.company_id != context.company.id:
            return None
        try:
            matter = assert_operational_matter(
                session,
                matter=matter,
                lock_for_write=True,
            )
        except MatterNotOperationalError:
            # Do not create a queue row that can never be delivered.  The
            # worker repeats the lifecycle check for already-existing intents.
            return None
        if not can_access(
            session,
            context=_recipient_context(
                actor_context=context,
                membership=recipient_membership,
            ),
            matter=matter,
        ):
            return None

    key = notification_delivery_idempotency_key(
        company_id=context.company.id,
        recipient_membership_id=recipient_membership.id,
        channel=channel,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
    )
    existing = session.scalar(
        select(NotificationDeliveryIntent).where(
            NotificationDeliveryIntent.company_id == context.company.id,
            NotificationDeliveryIntent.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing

    is_in_app = channel == NotificationDeliveryChannel.IN_APP
    settings = get_settings()
    suppression_reason = None
    if not is_in_app and channel == NotificationDeliveryChannel.EMAIL:
        from caseops_api.services.email_suppression import is_suppressed

        recipient_email = getattr(recipient_membership.user, "email", "") or ""
        suppression = is_suppressed(
            session,
            company_id=context.company.id,
            recipient_email=recipient_email,
        )
        if suppression is not None:
            suppression_reason = f"email_{suppression.reason}"
    external_ready = bool(
        channel == NotificationDeliveryChannel.EMAIL
        and settings.notification_external_delivery_enabled
        and settings.notification_external_delivery_provider == "sendgrid"
        and settings.sendgrid_api_key
        and settings.sendgrid_sender_email
        and not suppression_reason
    )
    blocked_external = not is_in_app and not external_ready
    # Do not retain message content for an external provider that is disabled.
    # This preserves the fail-closed privacy contract while allowing a provider
    # that is explicitly enabled to dispatch from the durable queue.
    retain_content = is_in_app or external_ready
    intent = NotificationDeliveryIntent(
        company_id=context.company.id,
        recipient_membership_id=recipient_membership.id,
        matter_id=matter.id if matter is not None else None,
        notification_rule_id=notification_rule_id,
        channel=channel,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        idempotency_key=key,
        status=(
            NotificationDeliveryStatus.QUEUED
            if is_in_app or external_ready
            else NotificationDeliveryStatus.BLOCKED
        ),
        attempts=0,
        max_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
        title=title if retain_content else None,
        body=_bounded_body(body) if retain_content else None,
        failed_at=_now() if blocked_external else None,
        dead_letter_reason=(
            None if not blocked_external else suppression_reason or "provider_disabled"
        ),
        metadata_json=_safe_metadata(
            notification_rule_id=notification_rule_id,
            source_id=source_id,
            linked_court_order_id=linked_court_order_id,
            triggered_by_membership_id=context.membership.id,
        ),
        schedule_source_type=("notification_rule" if notification_rule_id else source_type),
        schedule_source_id=notification_rule_id or source_id,
        recipient_snapshot_json={
            "membership_ref": redact_identifier(recipient_membership.id),
            "channel": str(channel),
        },
        dispatch_owner="durable_intent",
        comparison_status=(
            "canonical"
            if is_in_app
            else "dual_read_matched"
            if external_ready
            else "fallback_active"
        ),
        suppression_reason=suppression_reason,
    )
    if blocked_external:
        intent.last_error_redacted = (
            "recipient suppressed; in-app fallback required"
            if suppression_reason
            else "external provider disabled; in-app fallback required"
        )
    session.add(intent)
    session.flush()
    _record_delivery_event(
        session,
        intent=intent,
        event_type="intent_created",
        status_value=str(intent.status),
        error=intent.last_error_redacted,
    )
    if blocked_external:
        record_from_context(
            session,
            context,
            action="notification_delivery.external.blocked",
            target_type="notification_delivery_intent",
            target_id=intent.id,
            matter_id=matter.id if matter is not None else None,
            result=AuditResult.DENIED,
            metadata={
                "channel": channel,
                "reason": suppression_reason or "provider_disabled",
                "source_type": source_type,
                "source_ref": redact_identifier(source_id),
                "notification_rule_ref": redact_identifier(notification_rule_id),
                "recipient_membership_ref": redact_identifier(recipient_membership.id),
            },
        )
        fallback = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient_membership,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type=event_type,
            source_type=source_type,
            source_id=source_id,
            matter=matter,
            notification_rule_id=notification_rule_id,
            title=intent.title or "Delivery fallback",
            body=(
                intent.body
                or "An external notification could not be delivered. Review it in CaseOps."
            ),
            linked_court_order_id=linked_court_order_id,
        )
        if fallback is not None:
            intent.fallback_intent_id = fallback.id
            process_notification_delivery_intent(
                session,
                intent_id=fallback.id,
                context=context,
            )
            session.add(intent)
            session.flush()
    return intent


def record_notification_delivery_failure(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    raw_error: object,
    now: datetime | None = None,
) -> NotificationDeliveryProcessResult:
    if intent.status in {
        NotificationDeliveryStatus.SENT,
        NotificationDeliveryStatus.DELIVERED,
        NotificationDeliveryStatus.BLOCKED,
        NotificationDeliveryStatus.DEAD_LETTER,
    }:
        return _delivery_result(intent)
    current_time = now or _now()
    intent.attempts += 1
    intent.last_error_redacted = redact_provider_error(raw_error)
    intent.updated_at = current_time
    if intent.attempts >= intent.max_attempts:
        intent.status = NotificationDeliveryStatus.DEAD_LETTER
        intent.dead_letter_reason = "retry_limit_exhausted"
        intent.failed_at = current_time
        intent.next_attempt_at = None
    else:
        intent.status = NotificationDeliveryStatus.RETRY_SCHEDULED
        intent.next_attempt_at = current_time + retry_delay_for_attempt(intent.attempts)
    session.add(intent)
    _record_delivery_event(
        session,
        intent=intent,
        event_type="delivery_failed",
        status_value=str(intent.status),
        error=intent.last_error_redacted,
    )
    session.flush()
    return _delivery_result(intent)


def _ensure_in_app_fallback(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    context: SessionContext | None,
) -> None:
    if intent.fallback_intent_id is not None:
        return
    recipient = intent.recipient_membership
    if context is None:
        company = session.get(Company, intent.company_id)
        if company is None:
            return
        context = SessionContext(
            company=company,
            membership=recipient,
            user=recipient.user,
        )
    fallback = enqueue_notification_delivery_intent(
        session,
        context=context,
        recipient_membership=recipient,
        channel=NotificationDeliveryChannel.IN_APP,
        event_type=intent.event_type,
        source_type=intent.source_type,
        source_id=intent.source_id,
        matter=intent.matter,
        notification_rule_id=intent.notification_rule_id,
        title=intent.title or "Delivery fallback",
        body=intent.body or "An external notification could not be delivered.",
    )
    if fallback is None:
        return
    intent.fallback_intent_id = fallback.id
    process_notification_delivery_intent(
        session,
        intent_id=fallback.id,
        context=context,
    )
    session.add(intent)
    session.flush()


def process_notification_delivery_intent(
    session: Session,
    *,
    intent_id: str,
    company_id: str | None = None,
    context: SessionContext | None = None,
) -> NotificationDeliveryProcessResult:
    expected_company_id = company_id or (context.company.id if context is not None else None)
    if expected_company_id is None:
        raise ValueError("Notification delivery processing requires company scope.")
    intent = session.scalar(
        select(NotificationDeliveryIntent)
        .options(
            joinedload(NotificationDeliveryIntent.recipient_membership).joinedload(
                CompanyMembership.user
            ),
            joinedload(NotificationDeliveryIntent.matter),
        )
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == expected_company_id,
        )
    )
    if intent is None:
        raise ValueError("Notification delivery intent not found.")
    if intent.status in {
        NotificationDeliveryStatus.SENT,
        NotificationDeliveryStatus.DELIVERED,
        NotificationDeliveryStatus.BLOCKED,
        NotificationDeliveryStatus.DEAD_LETTER,
    }:
        return _delivery_result(intent)

    # Serialize the final delivery decision with matter disposal.  The initial
    # eager load is intentionally treated as advisory: another transaction may
    # have disposed the matter (and blocked this intent) since it entered the
    # identity map.  Lock parent first, then refresh+lock the intent, matching
    # the lifecycle transition's lock order.
    matter_disposed = False
    if intent.matter_id is not None:
        matter = session.get(Matter, intent.matter_id)
        if matter is None:
            matter_disposed = True
        else:
            try:
                assert_operational_matter(
                    session,
                    matter=matter,
                    lock_for_write=True,
                )
            except MatterNotOperationalError:
                matter_disposed = True

    intent = session.scalar(
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == expected_company_id,
        )
        .with_for_update(of=NotificationDeliveryIntent)
        .execution_options(populate_existing=True)
    )
    if intent is None:
        raise ValueError("Notification delivery intent not found.")
    if intent.status in {
        NotificationDeliveryStatus.SENT,
        NotificationDeliveryStatus.DELIVERED,
        NotificationDeliveryStatus.BLOCKED,
        NotificationDeliveryStatus.DEAD_LETTER,
    }:
        return _delivery_result(intent)
    if matter_disposed:
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "matter_disposed"
        intent.last_error_redacted = "Matter disposed before delivery."
        intent.failed_at = _now()
        intent.next_attempt_at = None
        session.add(intent)
        session.flush()
        return _delivery_result(intent)
    if (
        intent.status == NotificationDeliveryStatus.RETRY_SCHEDULED
        and intent.next_attempt_at is not None
        and intent.next_attempt_at > _now()
    ):
        return _delivery_result(intent)
    if intent.channel != NotificationDeliveryChannel.IN_APP:
        settings = get_settings()
        provider_ready = bool(
            intent.channel == NotificationDeliveryChannel.EMAIL
            and settings.notification_external_delivery_enabled
            and settings.notification_external_delivery_provider == "sendgrid"
            and settings.sendgrid_api_key
            and settings.sendgrid_sender_email
        )
        if not provider_ready:
            intent.status = NotificationDeliveryStatus.BLOCKED
            intent.dead_letter_reason = "provider_disabled"
            intent.last_error_redacted = "external provider disabled"
            intent.failed_at = _now()
            session.add(intent)
            _record_delivery_event(
                session,
                intent=intent,
                event_type="delivery_blocked",
                status_value=str(intent.status),
                error=intent.last_error_redacted,
            )
            session.flush()
            _ensure_in_app_fallback(session, intent=intent, context=context)
            return _delivery_result(intent)

        from caseops_api.services.email_suppression import is_suppressed

        recipient_email = intent.recipient_membership.user.email
        suppression = is_suppressed(
            session,
            company_id=intent.company_id,
            recipient_email=recipient_email,
        )
        if suppression is not None:
            intent.status = NotificationDeliveryStatus.BLOCKED
            intent.dead_letter_reason = f"email_{suppression.reason}"
            intent.suppression_reason = intent.dead_letter_reason
            intent.last_error_redacted = "recipient suppressed"
            intent.failed_at = _now()
            _record_delivery_event(
                session,
                intent=intent,
                event_type="delivery_suppressed",
                status_value=str(intent.status),
                error=intent.last_error_redacted,
                provider="sendgrid",
            )
            session.flush()
            _ensure_in_app_fallback(session, intent=intent, context=context)
            return _delivery_result(intent)

        from caseops_api.services.communications import _send_via_sendgrid

        intent.attempts += 1
        try:
            success, provider_event_id, error = _send_via_sendgrid(
                to_email=recipient_email,
                recipient_name=intent.recipient_membership.user.full_name,
                subject=intent.title or "CaseOps notification",
                body_text=intent.body or "Open CaseOps to review this notification.",
                custom_args={"notification_intent_id": intent.id},
            )
        except Exception as exc:  # noqa: BLE001 - provider/network boundary
            success, provider_event_id, error = False, None, str(exc)
        if not success:
            intent.attempts -= 1
            result = record_notification_delivery_failure(
                session,
                intent=intent,
                raw_error=error or "sendgrid delivery failed",
            )
            if result.dead_lettered:
                _ensure_in_app_fallback(session, intent=intent, context=context)
            return result
        intent.status = NotificationDeliveryStatus.SENT
        intent.provider_event_id = provider_event_id
        intent.next_attempt_at = None
        intent.updated_at = _now()
        intent.last_error_redacted = None
        _record_delivery_event(
            session,
            intent=intent,
            event_type="provider_accepted",
            status_value=str(intent.status),
            provider="sendgrid",
            provider_event_id=provider_event_id,
        )
        session.flush()
        return _delivery_result(intent)
    if intent.matter is not None and context is not None:
        recipient_context = _recipient_context(
            actor_context=context,
            membership=intent.recipient_membership,
        )
        if not can_access(session, context=recipient_context, matter=intent.matter):
            return record_notification_delivery_failure(
                session,
                intent=intent,
                raw_error="matter access denied",
            )

    existing = session.scalar(
        select(InAppNotification).where(
            InAppNotification.company_id == intent.company_id,
            InAppNotification.recipient_membership_id == (intent.recipient_membership_id),
            InAppNotification.event_type == intent.event_type,
            InAppNotification.source_type == intent.source_type,
            InAppNotification.source_id == intent.source_id,
        )
    )
    current_time = _now()
    if existing is None:
        existing = InAppNotification(
            company_id=intent.company_id,
            recipient_membership_id=intent.recipient_membership_id,
            event_type=intent.event_type,
            source_type=intent.source_type,
            source_id=intent.source_id,
            matter_id=intent.matter_id,
            title=intent.title or "Notification",
            body=intent.body,
            metadata_json=dict(intent.metadata_json or {}),
        )
        session.add(existing)
        session.flush()
        if context is not None:
            record_from_context(
                session,
                context,
                action="notification.in_app.created",
                target_type="in_app_notification",
                target_id=existing.id,
                matter_id=intent.matter_id,
                metadata={
                    "notification_delivery_intent_ref": redact_identifier(intent.id),
                    "notification_rule_ref": redact_identifier(intent.notification_rule_id),
                    "recipient_membership_ref": redact_identifier(intent.recipient_membership_id),
                    "event_type": intent.event_type,
                    "source_type": intent.source_type,
                    "source_ref": redact_identifier(intent.source_id),
                },
            )
    intent.attempts += 1
    intent.status = NotificationDeliveryStatus.DELIVERED
    intent.delivered_at = current_time
    intent.next_attempt_at = None
    intent.in_app_notification_id = existing.id
    intent.updated_at = current_time
    session.add(intent)
    _record_delivery_event(
        session,
        intent=intent,
        event_type="delivered",
        status_value=str(intent.status),
    )
    session.flush()
    return _delivery_result(intent)


def process_notification_delivery_intent_by_id(
    intent_id: str,
    *,
    company_id: str,
) -> NotificationDeliveryProcessResult:
    from caseops_api.db.session import get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        result = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            company_id=company_id,
        )
        session.commit()
        return result


def drain_notification_delivery_intents(
    session: Session,
    *,
    limit: int = 100,
) -> dict[str, int]:
    now = _now()
    rows = list(
        session.execute(
            select(
                NotificationDeliveryIntent.id,
                NotificationDeliveryIntent.company_id,
            )
            .where(
                NotificationDeliveryIntent.status.in_(
                    (
                        NotificationDeliveryStatus.QUEUED,
                        NotificationDeliveryStatus.RETRY_SCHEDULED,
                    )
                ),
                or_(
                    NotificationDeliveryIntent.next_attempt_at.is_(None),
                    NotificationDeliveryIntent.next_attempt_at <= now,
                ),
            )
            .order_by(NotificationDeliveryIntent.created_at, NotificationDeliveryIntent.id)
            .limit(limit)
        ).all()
    )
    report = {
        "examined": len(rows),
        "sent": 0,
        "delivered": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "blocked": 0,
        "external_calls": 0,
    }
    for intent_id, company_id in rows:
        result = process_notification_delivery_intent(
            session,
            intent_id=intent_id,
            company_id=company_id,
        )
        report["sent"] += int(result.status == NotificationDeliveryStatus.SENT)
        report["delivered"] += int(result.delivered)
        report["retry_scheduled"] += int(result.retry_scheduled)
        report["dead_lettered"] += int(result.dead_lettered)
        report["blocked"] += int(result.blocked)
        report["external_calls"] += result.external_calls
        session.commit()
    return report


def apply_notification_provider_event(session: Session, *, event: dict) -> bool:
    intent_id = str(event.get("notification_intent_id") or "").strip()
    provider_message_id = str(event.get("sg_message_id") or event.get("smtp-id") or "").strip()
    intent: NotificationDeliveryIntent | None = None
    if intent_id:
        intent = session.get(NotificationDeliveryIntent, intent_id)
    if intent is None and provider_message_id:
        prefix = provider_message_id.split(".", 1)[0]
        intent = session.scalar(
            select(NotificationDeliveryIntent)
            .where(NotificationDeliveryIntent.provider_event_id.like(f"{prefix}%"))
            .limit(1)
        )
    if intent is None:
        return False
    if provider_message_id and intent.provider_event_id:
        expected_prefix = intent.provider_event_id.split(".", 1)[0]
        actual_prefix = provider_message_id.split(".", 1)[0]
        if actual_prefix != expected_prefix:
            return False
    event_type = str(event.get("event") or "").lower()
    provider_event_key = str(event.get("sg_event_id") or "").strip() or None
    if provider_event_key:
        duplicate = session.scalar(
            select(NotificationDeliveryEvent.id).where(
                NotificationDeliveryEvent.company_id == intent.company_id,
                NotificationDeliveryEvent.provider == "sendgrid",
                NotificationDeliveryEvent.provider_event_id == provider_event_key,
            )
        )
        if duplicate is not None:
            return True
    when_raw = event.get("timestamp")
    when = datetime.fromtimestamp(int(when_raw), tz=UTC) if when_raw else _now()
    error = event.get("reason") or event.get("response")
    if event_type == "delivered":
        intent.status = NotificationDeliveryStatus.DELIVERED
        intent.delivered_at = when
        intent.failed_at = None
        intent.last_error_redacted = None
    elif event_type in {"bounce", "dropped", "blocked", "spamreport"}:
        intent.status = NotificationDeliveryStatus.DEAD_LETTER
        intent.dead_letter_reason = f"sendgrid_{event_type}"
        intent.failed_at = when
        intent.last_error_redacted = redact_provider_error(error or event_type)
        intent.next_attempt_at = None
        from caseops_api.services.email_suppression import (
            reason_for_event,
            record_suppression,
        )

        email = str(event.get("email") or intent.recipient_membership.user.email).strip()
        suppression_reason = reason_for_event(event_type)
        if email and suppression_reason is not None:
            record_suppression(
                session,
                company_id=intent.company_id,
                recipient_email=email,
                reason=suppression_reason,
                detail=str(error) if error else None,
                source_message_id=provider_message_id or intent.provider_event_id,
            )
        _ensure_in_app_fallback(session, intent=intent, context=None)
    elif event_type in {"unsubscribe", "group_unsubscribe"}:
        from caseops_api.services.email_suppression import (
            reason_for_event,
            record_suppression,
        )

        email = str(event.get("email") or intent.recipient_membership.user.email).strip()
        suppression_reason = reason_for_event(event_type)
        if email and suppression_reason is not None:
            record_suppression(
                session,
                company_id=intent.company_id,
                recipient_email=email,
                reason=suppression_reason,
                detail=str(error) if error else None,
                source_message_id=provider_message_id or intent.provider_event_id,
            )
    elif event_type not in {"open", "click", "deferred", "processed"}:
        return False
    _record_delivery_event(
        session,
        intent=intent,
        event_type=f"provider_{event_type}",
        status_value=str(intent.status),
        error=str(error) if error else None,
        provider="sendgrid",
        provider_event_id=provider_event_key,
        metadata={"provider_message_ref": redact_identifier(provider_message_id)},
    )
    intent.updated_at = when
    session.add(intent)
    session.flush()
    return True


__all__ = [
    "NotificationDeliveryProcessResult",
    "enqueue_notification_delivery_intent",
    "apply_notification_provider_event",
    "drain_notification_delivery_intents",
    "notification_delivery_idempotency_key",
    "process_notification_delivery_intent",
    "process_notification_delivery_intent_by_id",
    "record_notification_delivery_failure",
    "redact_provider_error",
    "retry_delay_for_attempt",
]
