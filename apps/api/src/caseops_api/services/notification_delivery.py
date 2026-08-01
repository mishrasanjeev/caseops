from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    AuditResult,
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
        external_calls=0,
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
) -> None:
    session.add(
        NotificationDeliveryEvent(
            company_id=intent.company_id,
            intent_id=intent.id,
            event_type=event_type,
            provider=None,
            provider_event_id=None,
            status=status_value,
            error_redacted=redact_provider_error(error) if error else None,
            metadata_json={
                "channel": str(intent.channel),
                "dispatch_owner": intent.dispatch_owner,
                "source_ref": redact_identifier(intent.source_id),
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
            if is_in_app
            else NotificationDeliveryStatus.BLOCKED
        ),
        attempts=0,
        max_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
        title=title if is_in_app else None,
        body=_bounded_body(body) if is_in_app else None,
        failed_at=None if is_in_app else _now(),
        dead_letter_reason=(
            None if is_in_app else suppression_reason or "provider_disabled"
        ),
        metadata_json=_safe_metadata(
            notification_rule_id=notification_rule_id,
            source_id=source_id,
            linked_court_order_id=linked_court_order_id,
            triggered_by_membership_id=context.membership.id,
        ),
        schedule_source_type=(
            "notification_rule" if notification_rule_id else source_type
        ),
        schedule_source_id=notification_rule_id or source_id,
        recipient_snapshot_json={
            "membership_ref": redact_identifier(recipient_membership.id),
            "channel": str(channel),
        },
        dispatch_owner="durable_intent",
        comparison_status="canonical" if is_in_app else "fallback_active",
        suppression_reason=suppression_reason,
    )
    if not is_in_app:
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
    if not is_in_app:
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
                "recipient_membership_ref": redact_identifier(
                    recipient_membership.id
                ),
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
            title=title or "Delivery fallback",
            body=(
                _bounded_body(body)
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
    if intent.channel != NotificationDeliveryChannel.IN_APP:
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "provider_disabled"
        intent.last_error_redacted = "external provider disabled"
        intent.failed_at = _now()
        session.add(intent)
        session.flush()
        return _delivery_result(intent)
    if (
        intent.status == NotificationDeliveryStatus.RETRY_SCHEDULED
        and intent.next_attempt_at is not None
        and intent.next_attempt_at > _now()
    ):
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
            InAppNotification.recipient_membership_id == (
                intent.recipient_membership_id
            ),
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
                    "notification_rule_ref": redact_identifier(
                        intent.notification_rule_id
                    ),
                    "recipient_membership_ref": redact_identifier(
                        intent.recipient_membership_id
                    ),
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


__all__ = [
    "NotificationDeliveryProcessResult",
    "enqueue_notification_delivery_intent",
    "notification_delivery_idempotency_key",
    "process_notification_delivery_intent",
    "process_notification_delivery_intent_by_id",
    "record_notification_delivery_failure",
    "redact_provider_error",
    "retry_delay_for_attempt",
]
