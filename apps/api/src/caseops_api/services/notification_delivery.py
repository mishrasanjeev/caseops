from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    Company,
    CompanyMembership,
    HearingReminder,
    HearingReminderDeliveryIntent,
    InAppNotification,
    IpDeadline,
    IpDocketRecord,
    Matter,
    MatterPortalGrant,
    NotificationDeliveryChannel,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    PortalUser,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.matter_access import can_access, can_access_ip_docket
from caseops_api.services.matter_operational_guard import (
    MatterNotOperationalError,
    assert_operational_matter,
    matter_is_operational,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.workflows.notification_intent_contracts import (
    DEFAULT_RETRY_INITIAL_INTERVAL,
    DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
    DEFAULT_RETRY_MAXIMUM_INTERVAL,
)

_URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d[\d\s().-]{8,}\d)(?!\d)")
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_.:-]{24,}\b")
_MAX_REDACTED_ERROR_LENGTH = 200
_MAX_REDACTION_INPUT_LENGTH = 2_000
_MAX_INTENT_BODY_LENGTH = 500
_SECRET_KEYS = {
    "apikey",
    "authorization",
    "authheader",
    "bearer",
    "clientsecret",
    "privatekey",
    "secret",
    "signature",
    "token",
    "webhooksignature",
}
_TOKEN_EDGE_PUNCTUATION = "\"'<>[]{}(),;"
NOTIFICATION_DISPATCH_CLAIM_PREFIX = "dispatch_claim:"
_NOTIFICATION_DISPATCH_CLAIM_PREFIX = NOTIFICATION_DISPATCH_CLAIM_PREFIX
_NOTIFICATION_PROVIDER_LEASE = timedelta(minutes=5)
NOTIFICATION_DISPATCH_CLAIM_IN_FLIGHT_CODE = "notification_dispatch_claim_in_flight"
NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_REASONS = frozenset(
    {
        "dispatch_provider_outcome_unknown",
        "dispatch_claim_expired_provider_outcome_unknown",
    }
)
NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_CODE = (
    "notification_provider_outcome_unknown_reconciliation_required"
)
NotificationDispatchClaimState = Literal[
    "none",
    "live",
    "expired",
    "manual_reconciliation",
]


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


@dataclass(frozen=True, slots=True)
class _IpDeadlineDeliveryTarget:
    declared: bool
    deadline_id: str | None
    docket_id: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def notification_intent_requires_provider_reconciliation(
    intent: NotificationDeliveryIntent,
) -> bool:
    """Return whether a resend could duplicate an accepted provider dispatch."""

    return notification_dispatch_claim_state(intent) in {
        "expired",
        "manual_reconciliation",
    }


def notification_dispatch_claim_state(
    intent: NotificationDeliveryIntent,
    *,
    now: datetime | None = None,
) -> NotificationDispatchClaimState:
    """Classify an external dispatch claim without changing the intent.

    A caller that acts on ``live`` or ``expired`` must hold the exact Intent
    row lock. The mutation helper below is the only generic transition from an
    expired raw claim to the canonical ambiguous-provider outcome.
    """

    if str(intent.dead_letter_reason or "") in NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_REASONS:
        return "manual_reconciliation"
    if not str(intent.provider_event_id or "").startswith(
        _NOTIFICATION_DISPATCH_CLAIM_PREFIX
    ):
        return "none"
    current_time = now or _now()
    if intent.next_attempt_at is not None and _as_utc(intent.next_attempt_at) > current_time:
        return "live"
    return "expired"


def materialize_expired_notification_dispatch_claim(
    intent: NotificationDeliveryIntent,
    *,
    now: datetime | None = None,
) -> bool:
    """Persist-ready UNKNOWN transition; caller holds exact Intent FOR UPDATE."""

    current_time = now or _now()
    if notification_dispatch_claim_state(intent, now=current_time) != "expired":
        return False
    intent.status = NotificationDeliveryStatus.DEAD_LETTER
    intent.dead_letter_reason = "dispatch_claim_expired_provider_outcome_unknown"
    intent.last_error_redacted = "Provider dispatch outcome is unknown."
    intent.failed_at = current_time
    intent.next_attempt_at = None
    intent.dispatch_owner = "durable_intent"
    intent.updated_at = current_time
    return True


def notification_provider_reconciliation_detail() -> dict[str, str]:
    return {
        "code": NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_CODE,
        "message": (
            "The notification provider may already have accepted this delivery. "
            "Generic recovery is disabled until provider evidence proves absence."
        ),
    }


def notification_dispatch_claim_in_flight_detail() -> dict[str, str]:
    return {
        "code": NOTIFICATION_DISPATCH_CLAIM_IN_FLIGHT_CODE,
        "message": (
            "The notification provider dispatch is still in flight. Wait for "
            "its claim lease to finalize before taking an operator action."
        ),
    }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


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
    recipient_membership_id: str | None = None,
    recipient_target_key: str | None = None,
    channel: str,
    event_type: str,
    source_type: str,
    source_id: str,
) -> str:
    raw = "|".join(
        (
            company_id,
            recipient_target_key or recipient_membership_id or "missing-target",
            channel,
            event_type,
            source_type,
            source_id,
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()


def _normalized_secret_key(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def _redact_secret_tokens(text: str) -> str:
    """Redact key/value secrets in linear time without regex backtracking."""
    tokens = text.split()
    redacted: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        candidate = token.strip(_TOKEN_EDGE_PUNCTUATION)
        separator_index = min(
            (position for position in (candidate.find("="), candidate.find(":")) if position >= 0),
            default=-1,
        )
        key_text = candidate[:separator_index] if separator_index >= 0 else candidate
        key = _normalized_secret_key(key_text)
        consumed_key_tokens = 1
        if key not in _SECRET_KEYS and index + 1 < len(tokens):
            paired_key = _normalized_secret_key(f"{candidate}{tokens[index + 1]}")
            if paired_key in _SECRET_KEYS:
                key = paired_key
                consumed_key_tokens = 2
        if key not in _SECRET_KEYS:
            redacted.append(token)
            index += 1
            continue

        redacted.append(f"{key_text or 'secret'}=[redacted]")
        index += consumed_key_tokens
        inline_value = separator_index >= 0 and separator_index < len(candidate) - 1
        if inline_value:
            continue
        if index < len(tokens) and tokens[index] in {"=", ":"}:
            index += 1
        if index < len(tokens):
            index += 1
    return " ".join(redacted)


def _redact_email_tokens(text: str) -> str:
    """Redact email-like whitespace-delimited tokens in linear time."""
    redacted: list[str] = []
    for token in text.split():
        candidate = token.strip(f"{_TOKEN_EDGE_PUNCTUATION}.:")
        local, separator, domain = candidate.partition("@")
        suffix = domain.rpartition(".")[2]
        if separator and local and domain and suffix.isalpha() and len(suffix) >= 2:
            redacted.append(token.replace(candidate, "[email-redacted]", 1))
        else:
            redacted.append(token)
    return " ".join(redacted)


def redact_provider_error(value: object) -> str:
    text = str(value or "provider_error").strip() or "provider_error"
    text = " ".join(text[:_MAX_REDACTION_INPUT_LENGTH].split())
    text = _redact_secret_tokens(text)
    text = _URL_RE.sub("[url-redacted]", text)
    text = _redact_email_tokens(text)
    text = _UUID_RE.sub("[id-redacted]", text)
    text = _PHONE_RE.sub("[phone-redacted]", text)
    text = _LONG_TOKEN_RE.sub("[token-redacted]", text)
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
            and not str(intent.provider_event_id).startswith(
                _NOTIFICATION_DISPATCH_CLAIM_PREFIX
            )
            else 0
        ),
        retry_scheduled=intent.status == NotificationDeliveryStatus.RETRY_SCHEDULED,
        dead_lettered=intent.status in {
            NotificationDeliveryStatus.DEAD_LETTER,
            NotificationDeliveryStatus.BOUNCED,
        },
        blocked=intent.status in {
            NotificationDeliveryStatus.BLOCKED,
            NotificationDeliveryStatus.SUPPRESSED,
            NotificationDeliveryStatus.CANCELLED,
        },
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
    idempotency_key: str | None = None,
    applied_to_state: bool = True,
) -> NotificationDeliveryEvent:
    event = NotificationDeliveryEvent(
            company_id=intent.company_id,
            intent_id=intent.id,
            event_type=event_type,
            provider=provider,
            provider_event_id=provider_event_id,
            idempotency_key=(
                idempotency_key
                or sha256(
                    f"{intent.id}|{event_type}|{status_value}|{intent.attempts}|{uuid4()}".encode()
                ).hexdigest()
            ),
            status=status_value,
            applied_to_state=applied_to_state,
            error_redacted=redact_provider_error(error) if error else None,
            metadata_json={
                "channel": str(intent.channel),
                "dispatch_owner": intent.dispatch_owner,
                "source_ref": redact_identifier(intent.source_id),
                **(metadata or {}),
            },
        )
    session.add(event)
    return event


def _terminal_statuses() -> set[str]:
    return {
        NotificationDeliveryStatus.DELIVERED,
        NotificationDeliveryStatus.BLOCKED,
        NotificationDeliveryStatus.SUPPRESSED,
        NotificationDeliveryStatus.BOUNCED,
        NotificationDeliveryStatus.CANCELLED,
        NotificationDeliveryStatus.DEAD_LETTER,
    }


def _notification_claim_is_live(
    intent: NotificationDeliveryIntent,
    *,
    now: datetime | None = None,
) -> bool:
    return notification_dispatch_claim_state(intent, now=now) == "live"


def _recipient_email(intent: NotificationDeliveryIntent) -> str:
    if intent.recipient_membership is not None and intent.recipient_membership.user is not None:
        return str(intent.recipient_membership.user.email or "").strip().lower()
    snapshot = intent.recipient_snapshot_json or {}
    return str(snapshot.get("destination") or "").strip().lower()


def _recipient_name(intent: NotificationDeliveryIntent) -> str:
    if intent.recipient_membership is not None and intent.recipient_membership.user is not None:
        return str(intent.recipient_membership.user.full_name or "CaseOps user")
    snapshot = intent.recipient_snapshot_json or {}
    return str(snapshot.get("display_name") or "CaseOps user")


def _recipient_still_permitted(
    session: Session,
    intent: NotificationDeliveryIntent,
) -> bool:
    membership = (
        session.get(CompanyMembership, intent.recipient_membership_id)
        if intent.recipient_membership_id is not None
        else None
    )
    matter = session.get(Matter, intent.matter_id) if intent.matter_id is not None else None
    ip_target = _intent_ip_deadline_target(session, intent=intent)
    resolved_docket_id = ip_target.docket_id or intent.ip_docket_id
    ip_docket = (
        session.get(IpDocketRecord, resolved_docket_id)
        if resolved_docket_id is not None
        else None
    )
    linked_ip_matter = (
        session.get(Matter, ip_docket.matter_id)
        if ip_docket is not None and ip_docket.matter_id is not None
        else None
    )
    if intent.recipient_membership_id:
        membership_active = bool(
            membership
            and membership.company_id == intent.company_id
            and membership.is_active
            and membership.user
            and membership.user.is_active
        )
        if not membership_active or membership is None:
            return False
        company = session.get(Company, intent.company_id)
        if company is None:
            return False
        recipient_context = SessionContext(
            company=company,
            user=membership.user,
            membership=membership,
        )
        if intent.matter_id is not None:
            if (
                matter is None
                or matter.id != intent.matter_id
                or matter.company_id != intent.company_id
                or not matter_is_operational(matter)
                or not can_access(session, context=recipient_context, matter=matter)
            ):
                return False
        if ip_docket is not None:
            if (
                ip_docket.company_id != intent.company_id
                or not ip_docket.is_active
                or ip_docket.archived_by_matter_disposal
                or not can_access_ip_docket(
                    session,
                    context=recipient_context,
                    docket=ip_docket,
                )
            ):
                return False
            if ip_docket.matter_id is not None and (
                linked_ip_matter is None
                or linked_ip_matter.id != ip_docket.matter_id
                or not matter_is_operational(linked_ip_matter)
                or not can_access(
                    session,
                    context=recipient_context,
                    matter=linked_ip_matter,
                )
            ):
                return False
            if intent.matter_id is not None and intent.matter_id != ip_docket.matter_id:
                return False
        elif intent.ip_docket_id is not None:
            # The durable target disappeared between queueing and dispatch.
            return False
        return True
    if intent.recipient_portal_user_id:
        portal_user = session.get(PortalUser, intent.recipient_portal_user_id)
        if (
            not portal_user
            or portal_user.company_id != intent.company_id
            or not portal_user.is_active
        ):
            return False
        # IP portal grants are deliberately not part of the M2 internal-access
        # slice. A portal recipient linked to an IP docket therefore fails
        # closed until the existing portal-grant owner is generalized later.
        if ip_docket is not None or intent.ip_docket_id is not None:
            return False
        if intent.matter_id is None:
            return True
        return session.scalar(
            select(MatterPortalGrant.id).where(
                MatterPortalGrant.portal_user_id == portal_user.id,
                MatterPortalGrant.matter_id == intent.matter_id,
            )
        ) is not None
    if ip_docket is not None or intent.ip_docket_id is not None:
        # Approved external destinations do not carry an internal IP grant.
        return False
    snapshot = intent.recipient_snapshot_json or {}
    return bool(
        intent.recipient_external_ref
        and snapshot.get("approved") is True
        and snapshot.get("approval_ref")
        and snapshot.get("destination")
    )


def _intent_ip_deadline_target(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
) -> _IpDeadlineDeliveryTarget:
    """Resolve legacy legal reminders that were queued as Matter-only work."""

    declares_ip_deadline = bool(
        intent.schedule_source_type == "ip_deadline"
        or intent.source_type == "ip_deadline"
    )
    if not declares_ip_deadline:
        return _IpDeadlineDeliveryTarget(
            declared=False,
            deadline_id=None,
            docket_id=intent.ip_docket_id,
        )
    deadline_id = (
        intent.schedule_source_id
        if intent.schedule_source_type == "ip_deadline"
        else intent.source_id.split(":", 1)[0]
        if intent.source_type == "ip_deadline"
        else None
    )
    if not deadline_id:
        return _IpDeadlineDeliveryTarget(True, None, None)
    row = session.execute(
        select(IpDeadline.id, IpDeadline.docket_id).where(
            IpDeadline.id == deadline_id,
            IpDeadline.company_id == intent.company_id,
        )
    ).one_or_none()
    if row is None:
        return _IpDeadlineDeliveryTarget(True, deadline_id, None)
    return _IpDeadlineDeliveryTarget(True, row.id, row.docket_id)


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
    recipient_membership: CompanyMembership | None = None,
    recipient_portal_user: PortalUser | None = None,
    recipient_external_ref: str | None = None,
    destination_snapshot: dict[str, object] | None = None,
    destination_version: int = 1,
    channel: str,
    event_type: str,
    source_type: str,
    source_id: str,
    matter: Matter | None = None,
    ip_docket: IpDocketRecord | None = None,
    notification_rule_id: str | None = None,
    title: str | None = None,
    body: str | None = None,
    linked_court_order_id: str | None = None,
    scheduled_for: datetime | None = None,
    critical: bool = False,
    escalation_membership: CompanyMembership | None = None,
    recovery_of_intent_id: str | None = None,
    confidentiality_mode: str = "minimal",
    schedule_source_type: str | None = None,
    schedule_source_id: str | None = None,
) -> NotificationDeliveryIntent | None:
    if matter is not None and ip_docket is not None:
        raise ValueError("A notification may target a Matter or an IP docket, not both.")
    targets = [
        recipient_membership is not None,
        recipient_portal_user is not None,
        bool(recipient_external_ref),
    ]
    if sum(targets) != 1:
        raise ValueError("Exactly one notification recipient target is required.")
    if recipient_membership is not None and (
        recipient_membership.company_id != context.company.id
        or not recipient_membership.is_active
        or not recipient_membership.user.is_active
    ):
        return None
    if recipient_portal_user is not None and recipient_portal_user.company_id != context.company.id:
        return None
    if recipient_external_ref and not (
        destination_snapshot
        and destination_snapshot.get("approved") is True
        and destination_snapshot.get("approval_ref")
    ):
        return None
    if escalation_membership is not None and (
        escalation_membership.company_id != context.company.id
        or not escalation_membership.is_active
    ):
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
        if recipient_membership is not None:
            if not can_access(
                session,
                context=_recipient_context(
                    actor_context=context,
                    membership=recipient_membership,
                ),
                matter=matter,
            ):
                return None
        elif recipient_portal_user is not None:
            grant = session.scalar(
                select(MatterPortalGrant.id).where(
                    MatterPortalGrant.portal_user_id == recipient_portal_user.id,
                    MatterPortalGrant.matter_id == matter.id,
                )
            )
            if grant is None:
                return None
    if ip_docket is not None:
        if (
            ip_docket.company_id != context.company.id
            or not ip_docket.is_active
            or ip_docket.archived_by_matter_disposal
        ):
            return None
        if recipient_membership is not None:
            recipient_context = _recipient_context(
                actor_context=context,
                membership=recipient_membership,
            )
            if not can_access_ip_docket(
                session,
                context=recipient_context,
                docket=ip_docket,
            ):
                return None
            if ip_docket.matter_id is not None:
                linked_matter = session.scalar(
                    select(Matter).where(
                        Matter.id == ip_docket.matter_id,
                        Matter.company_id == context.company.id,
                    )
                )
                if (
                    linked_matter is None
                    or not matter_is_operational(linked_matter)
                    or not can_access(
                        session,
                        context=recipient_context,
                        matter=linked_matter,
                    )
                ):
                    return None
        elif recipient_portal_user is not None:
            # The later portal-owner slice must add an explicit target-aware
            # portal grant. Internal access and linked-Matter visibility never
            # substitute for it.
            return None

    target_key = (
        f"membership:{recipient_membership.id}"
        if recipient_membership is not None
        else f"portal:{recipient_portal_user.id}"
        if recipient_portal_user is not None
        else f"external:{recipient_external_ref}:v{destination_version}"
    )

    key = notification_delivery_idempotency_key(
        company_id=context.company.id,
        recipient_target_key=target_key,
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
    if is_in_app and recipient_membership is None:
        return None
    settings = get_settings()
    suppression_reason = None
    if not is_in_app and channel == NotificationDeliveryChannel.EMAIL:
        from caseops_api.services.email_suppression import is_suppressed

        recipient_email = (
            getattr(recipient_membership.user, "email", "")
            if recipient_membership is not None
            else getattr(recipient_portal_user, "email", "")
            if recipient_portal_user is not None
            else str((destination_snapshot or {}).get("destination") or "")
        )
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
    safe_title = title if is_in_app else "CaseOps notification"
    safe_body = (
        body if is_in_app else "Open CaseOps to review this notification securely."
    )
    snapshot = dict(destination_snapshot or {})
    if recipient_membership is not None:
        snapshot.update(
            {
                "target_type": "membership",
                "target_ref": recipient_membership.id,
                "destination": (
                    str(recipient_membership.user.email).strip().lower()
                    if channel == NotificationDeliveryChannel.EMAIL
                    else None
                ),
            }
        )
    elif recipient_portal_user is not None:
        snapshot.update(
            {
                "target_type": "portal_user",
                "target_ref": recipient_portal_user.id,
                "destination": recipient_portal_user.email.strip().lower(),
            }
        )
    else:
        snapshot.update({"target_type": "approved_external", "target_ref": recipient_external_ref})
    snapshot.update(
        {
            "channel": str(channel),
            "destination_version": destination_version,
            "captured_at": _now().isoformat(),
        }
    )
    intent = NotificationDeliveryIntent(
        company_id=context.company.id,
        recipient_membership_id=(recipient_membership.id if recipient_membership else None),
        recipient_portal_user_id=(recipient_portal_user.id if recipient_portal_user else None),
        recipient_external_ref=recipient_external_ref,
        destination_version=destination_version,
        matter_id=matter.id if matter is not None else None,
        ip_docket_id=ip_docket.id if ip_docket is not None else None,
        notification_rule_id=notification_rule_id,
        channel=channel,
        event_type=event_type,
        source_type=source_type,
        source_id=source_id,
        idempotency_key=key,
        status=(
            NotificationDeliveryStatus.QUEUED
            if is_in_app or external_ready
            else NotificationDeliveryStatus.SUPPRESSED
            if suppression_reason
            else NotificationDeliveryStatus.BLOCKED
        ),
        attempts=0,
        max_attempts=DEFAULT_RETRY_MAXIMUM_ATTEMPTS,
        title=safe_title if retain_content else None,
        body=_bounded_body(safe_body) if retain_content else None,
        scheduled_for=scheduled_for,
        critical=critical,
        escalation_membership_id=(escalation_membership.id if escalation_membership else None),
        recovery_of_intent_id=recovery_of_intent_id,
        confidentiality_mode=("minimal" if not is_in_app else confidentiality_mode),
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
        schedule_source_type=(
            schedule_source_type
            or ("notification_rule" if notification_rule_id else source_type)
        ),
        schedule_source_id=schedule_source_id or notification_rule_id or source_id,
        recipient_snapshot_json=snapshot,
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
        # A notification rule owns its rendered message contract, so an
        # external-only rule that cannot dispatch falls back to the generic
        # safe notice used by the legacy path. Direct durable intents may use
        # their caller-supplied in-app copy, while the blocked external row
        # itself remains content-free in both cases.
        fallback_title = title if notification_rule_id is None else None
        fallback_body = _bounded_body(body) if notification_rule_id is None else None
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
                "recipient_target_ref": redact_identifier(target_key),
            },
        )
        fallback_recipient = recipient_membership or escalation_membership
        fallback = (
            enqueue_notification_delivery_intent(
                session,
                context=context,
                recipient_membership=fallback_recipient,
                channel=NotificationDeliveryChannel.IN_APP,
                event_type=event_type,
                source_type=source_type,
                source_id=source_id,
                matter=matter,
                ip_docket=ip_docket,
                notification_rule_id=notification_rule_id,
                title=fallback_title or "Delivery fallback",
                body=(
                    fallback_body
                    or "An external notification could not be delivered. Review it in CaseOps."
                ),
                linked_court_order_id=linked_court_order_id,
                scheduled_for=scheduled_for,
                critical=critical,
                escalation_membership=escalation_membership,
                schedule_source_type=schedule_source_type,
                schedule_source_id=schedule_source_id,
            )
            if fallback_recipient is not None
            else None
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
    elif critical and not is_in_app and recipient_membership is not None:
        companion = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient_membership,
            channel=NotificationDeliveryChannel.IN_APP,
            event_type=event_type,
            source_type=source_type,
            source_id=source_id,
            matter=matter,
            ip_docket=ip_docket,
            notification_rule_id=notification_rule_id,
            title=title or "Critical reminder",
            body=body or "Review this critical reminder in CaseOps.",
            linked_court_order_id=linked_court_order_id,
            scheduled_for=scheduled_for,
            critical=True,
            escalation_membership=escalation_membership,
            schedule_source_type=schedule_source_type,
            schedule_source_id=schedule_source_id,
        )
        if companion is not None:
            intent.fallback_intent_id = companion.id
            session.add(intent)
            session.flush()
    return intent


def record_notification_delivery_failure(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    raw_error: object,
    now: datetime | None = None,
    retryable: bool = True,
) -> NotificationDeliveryProcessResult:
    if intent.status in _terminal_statuses():
        return _delivery_result(intent)
    current_time = now or _now()
    intent.attempts += 1
    intent.last_error_redacted = redact_provider_error(raw_error)
    intent.updated_at = current_time
    if not retryable or intent.attempts >= intent.max_attempts:
        intent.status = NotificationDeliveryStatus.DEAD_LETTER
        intent.dead_letter_reason = (
            "retry_limit_exhausted" if retryable else "non_retryable_provider_failure"
        )
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
    if recipient is None and intent.escalation_membership_id:
        recipient = session.get(CompanyMembership, intent.escalation_membership_id)
    if (
        recipient is None
        or not recipient.is_active
        or recipient.user is None
        or not recipient.user.is_active
    ):
        return
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
        ip_docket=(
            session.get(IpDocketRecord, intent.ip_docket_id)
            if intent.ip_docket_id is not None
            else None
        ),
        notification_rule_id=intent.notification_rule_id,
        title=intent.title or "Delivery fallback",
        body=intent.body or "An external notification could not be delivered.",
        scheduled_for=intent.scheduled_for,
        critical=bool(intent.critical),
        escalation_membership=recipient,
        recovery_of_intent_id=intent.recovery_of_intent_id,
        confidentiality_mode=intent.confidentiality_mode,
        schedule_source_type=intent.schedule_source_type,
        schedule_source_id=intent.schedule_source_id,
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


def _is_retryable_provider_error(value: object) -> bool:
    text = str(value or "").lower()
    if any(token in text for token in ("timeout", "timed out", "connection", "429", "rate limit")):
        return True
    match = re.search(r"\b(?:sendgrid|provider)\s+(\d{3})\b", text)
    return bool(match and int(match.group(1)) >= 500)


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
    if intent.status in _terminal_statuses():
        return _delivery_result(intent)
    if intent.status == NotificationDeliveryStatus.SENT and _notification_claim_is_live(intent):
        return _delivery_result(intent)
    if intent.status == NotificationDeliveryStatus.SENT and not str(
        intent.provider_event_id or ""
    ).startswith(_NOTIFICATION_DISPATCH_CLAIM_PREFIX):
        return _delivery_result(intent)
    if intent.scheduled_for is not None and _as_utc(intent.scheduled_for) > _now():
        return _delivery_result(intent)

    # The first load is advisory. External dispatch fences the recipient before
    # any parent/intent lock so employee deactivation and disclosure have one
    # global order. Legacy IP-deadline reminders were queued as Matter-only
    # intents; resolve their immutable legal deadline here so they receive the
    # same IP reauthorization as newly docket-bound replacement intents.
    ip_deadline_target = _intent_ip_deadline_target(session, intent=intent)
    resolved_ip_docket_id = ip_deadline_target.docket_id
    advisory_docket = (
        session.scalar(
            select(IpDocketRecord).where(
                IpDocketRecord.id == resolved_ip_docket_id,
                IpDocketRecord.company_id == expected_company_id,
            )
        )
        if resolved_ip_docket_id is not None
        else None
    )
    delivery_membership_ids = {
        membership_id
        for membership_id in (
            intent.recipient_membership_id,
            intent.escalation_membership_id,
        )
        if membership_id is not None
    }
    if intent.channel != NotificationDeliveryChannel.IN_APP:
        # External delivery is an irreversible disclosure boundary. Fence it
        # with employee deactivation before any Matter/docket/intent lock.
        locked_memberships = lock_company_memberships_for_assignment(
            session,
            company_id=expected_company_id,
            membership_ids=delivery_membership_ids,
        )
        locked_users = {
            membership.user_id: membership.user
            for membership in locked_memberships.values()
        }
    else:
        # Court-order writers deliver in-app notices synchronously while they
        # already own the Matter lock. Taking Membership here would invert the
        # global Membership -> Matter order. A fresh, unlocked read is enough:
        # this path has no external side effect and an inactive user cannot
        # authenticate to observe a concurrently-created internal row.
        locked_memberships = {
            row.id: row
            for row in session.scalars(
                select(CompanyMembership)
                .options(joinedload(CompanyMembership.user))
                .where(
                    CompanyMembership.company_id == expected_company_id,
                    CompanyMembership.id.in_(sorted(delivery_membership_ids)),
                )
                .order_by(CompanyMembership.id)
                .execution_options(populate_existing=True)
            ).all()
        }
        locked_users = {
            membership.user_id: membership.user
            for membership in locked_memberships.values()
            if membership.user is not None
        }
    locked_matter_ids = sorted(
        {
            matter_id
            for matter_id in (
                intent.matter_id,
                advisory_docket.matter_id if advisory_docket is not None else None,
            )
            if matter_id is not None
        }
    )
    locked_matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == expected_company_id,
                    Matter.id.in_(locked_matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
        if locked_matter_ids
        else []
    )
    matter_by_id = {row.id: row for row in locked_matters}
    matter = matter_by_id.get(intent.matter_id) if intent.matter_id is not None else None
    linked_ip_matter = (
        matter_by_id.get(advisory_docket.matter_id)
        if advisory_docket is not None and advisory_docket.matter_id is not None
        else None
    )
    ip_docket = (
        session.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == resolved_ip_docket_id,
                IpDocketRecord.company_id == expected_company_id,
            )
            .with_for_update(of=IpDocketRecord)
            .execution_options(populate_existing=True)
        )
        if resolved_ip_docket_id is not None
        else None
    )
    locked_ip_deadline = (
        session.scalar(
            select(IpDeadline)
            .where(
                IpDeadline.id == ip_deadline_target.deadline_id,
                IpDeadline.company_id == expected_company_id,
                IpDeadline.docket_id == resolved_ip_docket_id,
            )
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
        if ip_deadline_target.declared
        and ip_deadline_target.deadline_id is not None
        and resolved_ip_docket_id is not None
        else None
    )

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
    if intent.status in _terminal_statuses():
        return _delivery_result(intent)
    if intent.status == NotificationDeliveryStatus.SENT and _notification_claim_is_live(intent):
        return _delivery_result(intent)
    if intent.status == NotificationDeliveryStatus.SENT and str(
        intent.provider_event_id or ""
    ).startswith(_NOTIFICATION_DISPATCH_CLAIM_PREFIX):
        # SendGrid offers no idempotent-send key. After a worker disappears we
        # cannot distinguish "provider accepted, response lost" from "never
        # called"; retrying could disclose twice. Recover the expired lease to
        # an auditable terminal state and require deliberate/manual repair.
        materialize_expired_notification_dispatch_claim(intent)
        session.add(intent)
        _record_delivery_event(
            session,
            intent=intent,
            event_type="delivery_claim_expired",
            status_value=str(intent.status),
            error=intent.last_error_redacted,
            provider="sendgrid",
        )
        _ensure_in_app_fallback(session, intent=intent, context=context)
        session.commit()
        return _delivery_result(intent)
    if intent.status == NotificationDeliveryStatus.SENT and not str(
        intent.provider_event_id or ""
    ).startswith(_NOTIFICATION_DISPATCH_CLAIM_PREFIX):
        return _delivery_result(intent)
    recipient_membership = (
        locked_memberships.get(intent.recipient_membership_id)
        if intent.recipient_membership_id is not None
        else None
    )
    recipient_user = (
        locked_users.get(recipient_membership.user_id)
        if recipient_membership is not None
        else None
    )
    ip_deadline_target_invalid = ip_deadline_target.declared and (
        locked_ip_deadline is None
        or str(locked_ip_deadline.state) not in {"confirmed", "overdue"}
        or ip_docket is None
        or locked_ip_deadline.docket_id != ip_docket.id
        or (
            intent.ip_docket_id is not None
            and intent.ip_docket_id != ip_docket.id
        )
    )
    if ip_deadline_target_invalid:
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "ip_deadline_target_inactive"
        intent.last_error_redacted = "IP deadline target is missing or no longer operational."
        intent.failed_at = _now()
        intent.next_attempt_at = None
        session.add(intent)
        _record_delivery_event(
            session,
            intent=intent,
            event_type="delivery_target_blocked",
            status_value=str(intent.status),
            error=intent.last_error_redacted,
        )
        session.flush()
        return _delivery_result(intent)
    matter_disposed = (
        intent.matter_id is not None
        and (matter is None or not matter_is_operational(matter))
    ) or (
        ip_docket is not None
        and ip_docket.matter_id is not None
        and (
            linked_ip_matter is None
            or not matter_is_operational(linked_ip_matter)
        )
    )
    if matter_disposed:
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "matter_disposed"
        intent.last_error_redacted = "Matter disposed before delivery."
        intent.failed_at = _now()
        intent.next_attempt_at = None
        session.add(intent)
        session.flush()
        return _delivery_result(intent)
    if not _recipient_still_permitted(session, intent):
        intent.status = NotificationDeliveryStatus.BLOCKED
        intent.dead_letter_reason = "recipient_permission_revoked"
        intent.last_error_redacted = "Recipient is inactive or no longer permitted."
        intent.failed_at = _now()
        intent.next_attempt_at = None
        session.add(intent)
        _record_delivery_event(
            session,
            intent=intent,
            event_type="delivery_permission_blocked",
            status_value=str(intent.status),
            error=intent.last_error_redacted,
        )
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

        if intent.recipient_membership_id is not None and (
            recipient_membership is None
            or recipient_user is None
            or not recipient_membership.is_active
            or not recipient_user.is_active
        ):
            intent.status = NotificationDeliveryStatus.BLOCKED
            intent.dead_letter_reason = "recipient_permission_revoked"
            intent.last_error_redacted = "Recipient is inactive or no longer permitted."
            intent.failed_at = _now()
            intent.next_attempt_at = None
            session.add(intent)
            session.flush()
            return _delivery_result(intent)
        recipient_email = (
            str(recipient_user.email or "").strip().lower()
            if recipient_user is not None
            else _recipient_email(intent)
        )
        if not recipient_email:
            return record_notification_delivery_failure(
                session,
                intent=intent,
                raw_error="recipient destination missing",
                retryable=False,
            )
        suppression = is_suppressed(
            session,
            company_id=intent.company_id,
            recipient_email=recipient_email,
        )
        if suppression is not None:
            intent.status = NotificationDeliveryStatus.SUPPRESSED
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

        recipient_name = (
            str(recipient_user.full_name or "CaseOps user")
            if recipient_user is not None
            else _recipient_name(intent)
        )
        claim_marker = f"{_NOTIFICATION_DISPATCH_CLAIM_PREFIX}{uuid4().hex}"
        intent.attempts += 1
        intent.status = NotificationDeliveryStatus.SENT
        intent.provider_event_id = claim_marker
        intent.dispatch_owner = "provider_claim"
        intent.next_attempt_at = _now() + _NOTIFICATION_PROVIDER_LEASE
        intent.updated_at = _now()
        intent.last_error_redacted = None
        session.add(intent)
        _record_delivery_event(
            session,
            intent=intent,
            event_type="delivery_claimed",
            status_value=str(intent.status),
            provider="sendgrid",
            metadata={"claim_lease_seconds": int(_NOTIFICATION_PROVIDER_LEASE.total_seconds())},
        )
        # This commit is the winner point against deactivation/access revoke.
        # A writer that commits first blocks the claim; a claim that commits
        # first is an authorized disclosure and cannot later be cancelled as
        # merely queued work. No SQL transaction remains over SendGrid I/O.
        session.commit()
        try:
            success, provider_event_id, error = _send_via_sendgrid(
                to_email=recipient_email,
                recipient_name=recipient_name,
                subject="CaseOps notification",
                body_text="Open CaseOps to review this notification securely.",
                custom_args={
                    "notification_intent_id": intent.id,
                },
            )
        except Exception as exc:  # noqa: BLE001 - provider/network boundary
            success, provider_event_id, error = False, None, str(exc)

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
            session.rollback()
            raise ValueError("Notification delivery intent not found.")
        if (
            intent.status != NotificationDeliveryStatus.SENT
            or intent.provider_event_id != claim_marker
        ):
            # A stale provider callback is audit evidence only. It must never
            # resurrect a lifecycle/access-blocked or cancelled intent.
            _record_delivery_event(
                session,
                intent=intent,
                event_type="provider_callback_discarded",
                status_value=str(intent.status),
                error=error if not success else None,
                provider="sendgrid",
                provider_event_id=provider_event_id,
                applied_to_state=False,
            )
            session.commit()
            return _delivery_result(intent)
        if not success:
            intent.provider_event_id = None
            intent.dispatch_owner = "durable_intent"
            intent.next_attempt_at = None
            if _is_retryable_provider_error(error):
                # A transport exception after dispatch has an ambiguous
                # provider outcome: SendGrid may have accepted the message
                # before the response was lost. Automatic retry would risk a
                # duplicate disclosure, so require explicit reconciliation.
                intent.status = NotificationDeliveryStatus.DEAD_LETTER
                intent.dead_letter_reason = "dispatch_provider_outcome_unknown"
                intent.last_error_redacted = "Notification provider outcome is unknown."
                intent.failed_at = _now()
                intent.updated_at = _now()
                _record_delivery_event(
                    session,
                    intent=intent,
                    event_type="provider_dispatch_outcome_unknown",
                    status_value=str(intent.status),
                    error=intent.last_error_redacted,
                    provider="sendgrid",
                )
                session.add(intent)
                _ensure_in_app_fallback(session, intent=intent, context=context)
                session.commit()
                return _delivery_result(intent)
            intent.attempts -= 1
            result = record_notification_delivery_failure(
                session,
                intent=intent,
                raw_error=error or "sendgrid delivery failed",
                retryable=_is_retryable_provider_error(error),
            )
            if result.dead_lettered:
                _ensure_in_app_fallback(session, intent=intent, context=context)
            session.commit()
            return result
        intent.status = NotificationDeliveryStatus.SENT
        intent.provider_event_id = provider_event_id
        intent.dispatch_owner = "durable_intent"
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
        session.commit()
        return _delivery_result(intent)
    if intent.matter is not None and context is not None and intent.recipient_membership:
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
        if intent.recipient_membership_id is None:
            intent.status = NotificationDeliveryStatus.BLOCKED
            intent.dead_letter_reason = "in_app_requires_internal_membership"
            session.add(intent)
            session.flush()
            return _delivery_result(intent)
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
                or_(
                    NotificationDeliveryIntent.status.in_(
                        (
                            NotificationDeliveryStatus.QUEUED,
                            NotificationDeliveryStatus.RETRY_SCHEDULED,
                        )
                    ),
                    (
                        NotificationDeliveryIntent.status
                        == NotificationDeliveryStatus.SENT
                    )
                    & NotificationDeliveryIntent.provider_event_id.startswith(
                        _NOTIFICATION_DISPATCH_CLAIM_PREFIX
                    )
                    & NotificationDeliveryIntent.next_attempt_at.is_not(None)
                    & (NotificationDeliveryIntent.next_attempt_at <= now),
                ),
                or_(
                    NotificationDeliveryIntent.next_attempt_at.is_(None),
                    NotificationDeliveryIntent.next_attempt_at <= now,
                ),
                or_(
                    NotificationDeliveryIntent.scheduled_for.is_(None),
                    NotificationDeliveryIntent.scheduled_for <= now,
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
        _project_legacy_hearing_reminders(session, intent_id=intent_id)
        session.commit()
    return report


def cancel_pending_notification_intents(
    session: Session,
    *,
    company_id: str,
    schedule_source_type: str,
    schedule_source_id: str,
    superseded_by_intent_id: str | None = None,
    exclude_source_id_prefix: str | None = None,
    cancellation_reason: str = "schedule_cancelled_or_superseded",
    intent_ids: Iterable[str] | None = None,
) -> int:
    """Atomically cancel pending delivery children for a closed/superseded schedule."""
    statement = (
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.company_id == company_id,
            NotificationDeliveryIntent.schedule_source_type == schedule_source_type,
            NotificationDeliveryIntent.schedule_source_id == schedule_source_id,
            NotificationDeliveryIntent.status.in_(
                (
                    NotificationDeliveryStatus.QUEUED,
                    NotificationDeliveryStatus.RETRY_SCHEDULED,
                )
            ),
        )
        .order_by(NotificationDeliveryIntent.id)
        .with_for_update(of=NotificationDeliveryIntent)
    )
    if exclude_source_id_prefix:
        statement = statement.where(
            ~NotificationDeliveryIntent.source_id.startswith(exclude_source_id_prefix)
        )
    selected_intent_ids = sorted(set(intent_ids or ()))
    if intent_ids is not None:
        if not selected_intent_ids:
            return 0
        statement = statement.where(
            NotificationDeliveryIntent.id.in_(selected_intent_ids)
        )
    intents = list(
        session.scalars(statement.execution_options(populate_existing=True))
    )
    now = _now()
    for intent in intents:
        intent.status = NotificationDeliveryStatus.CANCELLED
        intent.next_attempt_at = None
        intent.failed_at = now
        intent.dead_letter_reason = cancellation_reason[:160]
        intent.superseded_by_intent_id = superseded_by_intent_id
        intent.updated_at = now
        _record_delivery_event(
            session,
            intent=intent,
            event_type="schedule_cancelled",
            status_value=str(intent.status),
        )
        session.add(intent)
        _project_legacy_hearing_reminders(session, intent_id=intent.id)
    session.flush()
    return len(intents)


def link_hearing_reminder_intent(
    session: Session,
    *,
    hearing_reminder_id: str,
    intent_id: str,
    is_primary: bool,
) -> HearingReminderDeliveryIntent:
    existing = session.scalar(
        select(HearingReminderDeliveryIntent).where(
            HearingReminderDeliveryIntent.hearing_reminder_id == hearing_reminder_id,
            HearingReminderDeliveryIntent.intent_id == intent_id,
        )
    )
    if existing is not None:
        return existing
    link = HearingReminderDeliveryIntent(
        hearing_reminder_id=hearing_reminder_id,
        intent_id=intent_id,
        is_primary=is_primary,
    )
    session.add(link)
    session.flush()
    return link


def _project_legacy_hearing_reminders(session: Session, *, intent_id: str) -> None:
    """Keep legacy rows as a read-only compatibility projection of durable truth."""
    intent = session.get(NotificationDeliveryIntent, intent_id)
    if intent is None:
        return
    projection = {
        NotificationDeliveryStatus.QUEUED: "queued",
        NotificationDeliveryStatus.RETRY_SCHEDULED: "queued",
        NotificationDeliveryStatus.SENT: "sent",
        NotificationDeliveryStatus.DELIVERED: "delivered",
        NotificationDeliveryStatus.BLOCKED: "failed",
        NotificationDeliveryStatus.SUPPRESSED: "failed",
        NotificationDeliveryStatus.BOUNCED: "failed",
        NotificationDeliveryStatus.DEAD_LETTER: "failed",
        NotificationDeliveryStatus.CANCELLED: "cancelled",
    }
    links = list(
        session.scalars(
            select(HearingReminderDeliveryIntent).where(
                HearingReminderDeliveryIntent.intent_id == intent_id,
                HearingReminderDeliveryIntent.is_primary.is_(True),
            )
        )
    )
    for link in links:
        reminder = session.get(HearingReminder, link.hearing_reminder_id)
        if reminder is None:
            continue
        permission_revoked = intent.dead_letter_reason == "recipient_permission_revoked"
        reminder.status = (
            "cancelled"
            if permission_revoked
            else projection.get(str(intent.status), "failed")
        )
        reminder.provider = "sendgrid" if intent.provider_event_id else reminder.provider
        reminder.provider_message_id = intent.provider_event_id or reminder.provider_message_id
        reminder.last_error = (
            "Recipient permission was removed before delivery."
            if permission_revoked
            else intent.last_error_redacted
        )
        reminder.sent_at = reminder.sent_at or (
            intent.updated_at if intent.status == NotificationDeliveryStatus.SENT else None
        )
        reminder.delivered_at = intent.delivered_at
        reminder.attempts = intent.attempts
        reminder.updated_at = _now()
        session.add(reminder)


def project_linked_hearing_reminder_intent(
    session: Session,
    *,
    intent_id: str,
) -> None:
    """Refresh the legacy reminder projection without provider I/O."""

    _project_legacy_hearing_reminders(session, intent_id=intent_id)


def cancel_linked_hearing_reminder_intent_for_inactive_recipient(
    session: Session,
    *,
    intent_id: str,
) -> bool:
    """Cancel an undispatched linked intent after recipient deactivation.

    This state-only compatibility fence takes Membership/User before Intent,
    performs no provider I/O, and deliberately leaves a committed dispatch
    claim or provider-final state untouched.
    """

    advisory = session.get(NotificationDeliveryIntent, intent_id)
    if advisory is None or advisory.recipient_membership_id is None:
        return False
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=advisory.company_id,
        membership_ids=(advisory.recipient_membership_id,),
    )
    recipient = memberships.get(advisory.recipient_membership_id)
    recipient_user = recipient.user if recipient is not None else None
    if (
        recipient is not None
        and recipient_user is not None
        and recipient.is_active
        and recipient_user.is_active
    ):
        return False
    intent = session.scalar(
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == advisory.company_id,
        )
        .with_for_update(of=NotificationDeliveryIntent)
        .execution_options(populate_existing=True)
    )
    if intent is None or intent.status not in {
        NotificationDeliveryStatus.QUEUED,
        NotificationDeliveryStatus.RETRY_SCHEDULED,
        NotificationDeliveryStatus.BLOCKED,
    }:
        return False
    now = _now()
    intent.status = NotificationDeliveryStatus.CANCELLED
    intent.dead_letter_reason = "recipient_permission_revoked"
    intent.last_error_redacted = "Recipient permission was removed before delivery."
    intent.failed_at = now
    intent.next_attempt_at = None
    intent.updated_at = now
    session.add(intent)
    _record_delivery_event(
        session,
        intent=intent,
        event_type="delivery_permission_cancelled",
        status_value=str(intent.status),
        error=intent.last_error_redacted,
    )
    _project_legacy_hearing_reminders(session, intent_id=intent.id)
    return True


def _lock_notification_provider_event_intent(
    session: Session,
    *,
    advisory_intent: NotificationDeliveryIntent,
) -> NotificationDeliveryIntent | None:
    """Lock lifecycle parents, then refresh the exact webhook intent.

    This path deliberately takes no Membership/User lock. Employee and access
    writers use Membership -> parent -> Intent; taking Membership after a
    parent here would add the reverse edge. The final Intent lock serializes
    provider webhooks with those writers and operator actions.
    """

    company_id = advisory_intent.company_id
    intent_id = advisory_intent.id
    ip_target = _intent_ip_deadline_target(session, intent=advisory_intent)
    docket_id = ip_target.docket_id or advisory_intent.ip_docket_id
    advisory_docket = (
        session.scalar(
            select(IpDocketRecord).where(
                IpDocketRecord.id == docket_id,
                IpDocketRecord.company_id == company_id,
            )
        )
        if docket_id is not None
        else None
    )
    matter_ids = sorted(
        {
            value
            for value in (
                advisory_intent.matter_id,
                advisory_docket.matter_id if advisory_docket is not None else None,
            )
            if value is not None
        }
    )
    if matter_ids:
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == company_id,
                    Matter.id.in_(matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
    if docket_id is not None:
        session.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == docket_id,
                IpDocketRecord.company_id == company_id,
            )
            .with_for_update(of=IpDocketRecord)
            .execution_options(populate_existing=True)
        )
    if ip_target.deadline_id is not None and docket_id is not None:
        session.scalar(
            select(IpDeadline)
            .where(
                IpDeadline.id == ip_target.deadline_id,
                IpDeadline.company_id == company_id,
                IpDeadline.docket_id == docket_id,
            )
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
    return session.scalar(
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == company_id,
        )
        .with_for_update(of=NotificationDeliveryIntent)
        .execution_options(populate_existing=True)
    )


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
    intent = _lock_notification_provider_event_intent(
        session,
        advisory_intent=intent,
    )
    if intent is None:
        return False
    if provider_message_id and intent.provider_event_id:
        expected_prefix = intent.provider_event_id.split(".", 1)[0]
        actual_prefix = provider_message_id.split(".", 1)[0]
        if actual_prefix != expected_prefix:
            return False
    event_type = str(event.get("event") or "").lower()
    supported = {
        "delivered", "bounce", "dropped", "blocked", "spamreport",
        "unsubscribe", "group_unsubscribe", "open", "click", "deferred", "processed",
    }
    if event_type not in supported:
        return False
    provider_event_key = str(event.get("sg_event_id") or "").strip() or None
    when_raw = event.get("timestamp")
    when = datetime.fromtimestamp(int(when_raw), tz=UTC) if when_raw else _now()
    event_idempotency_key = sha256(
        "|".join(
            (
                intent.company_id,
                "sendgrid",
                provider_event_key or provider_message_id,
                event_type,
                str(when_raw or ""),
                str(event.get("email") or "").strip().lower(),
            )
        ).encode()
    ).hexdigest()
    duplicate = session.scalar(
        select(NotificationDeliveryEvent.id).where(
            NotificationDeliveryEvent.company_id == intent.company_id,
            NotificationDeliveryEvent.provider == "sendgrid",
            NotificationDeliveryEvent.idempotency_key == event_idempotency_key,
        )
    )
    if duplicate is not None:
        return True
    error = event.get("reason") or event.get("response")
    if notification_dispatch_claim_state(intent) != "none":
        # A raw or typed ambiguous dispatch has no trustworthy provider receipt
        # to correlate. Preserve it for explicit reconciliation; webhook state
        # is durable evidence only and can never resurrect or close the intent.
        _record_delivery_event(
            session,
            intent=intent,
            event_type=f"provider_{event_type}",
            status_value=str(intent.status),
            error=str(error) if error else None,
            provider="sendgrid",
            provider_event_id=provider_event_key,
            metadata={"provider_message_ref": redact_identifier(provider_message_id)},
            idempotency_key=event_idempotency_key,
            applied_to_state=False,
        )
        intent.updated_at = _now()
        session.add(intent)
        session.flush()
        return True
    applied_to_state = False
    current_status = str(intent.status)
    current_state_at = (
        _as_utc(intent.provider_state_occurred_at)
        if intent.provider_state_occurred_at is not None
        else None
    )
    chronological = current_state_at is None or when >= current_state_at
    if event_type == "delivered":
        if chronological and current_status not in _terminal_statuses():
            intent.status = NotificationDeliveryStatus.DELIVERED
            intent.delivered_at = when
            intent.failed_at = None
            intent.last_error_redacted = None
            applied_to_state = True
    elif event_type in {"bounce", "dropped", "blocked", "spamreport"}:
        if current_status not in _terminal_statuses():
            intent.status = (
                NotificationDeliveryStatus.BOUNCED
                if event_type == "bounce"
                else NotificationDeliveryStatus.SUPPRESSED
                if event_type in {"dropped", "spamreport"}
                else NotificationDeliveryStatus.DEAD_LETTER
            )
            intent.dead_letter_reason = f"sendgrid_{event_type}"
            intent.failed_at = when
            intent.last_error_redacted = redact_provider_error(error or event_type)
            intent.next_attempt_at = None
            applied_to_state = True
        from caseops_api.services.email_suppression import (
            reason_for_event,
            record_suppression,
        )

        email = str(event.get("email") or _recipient_email(intent)).strip()
        suppression_reason = reason_for_event(event_type)
        suppression = None
        if email and suppression_reason is not None:
            suppression = record_suppression(
                session,
                company_id=intent.company_id,
                recipient_email=email,
                reason=suppression_reason,
                detail=str(error) if error else None,
                source_message_id=provider_message_id or intent.provider_event_id,
            )
        _ensure_in_app_fallback(session, intent=intent, context=None)
        if suppression is not None and intent.fallback_intent_id is not None:
            suppression.fallback_sent = True
            session.add(suppression)
    elif event_type in {"unsubscribe", "group_unsubscribe"}:
        from caseops_api.services.email_suppression import (
            reason_for_event,
            record_suppression,
        )

        email = str(event.get("email") or _recipient_email(intent)).strip()
        suppression_reason = reason_for_event(event_type)
        if email and suppression_reason is not None:
            suppression = record_suppression(
                session,
                company_id=intent.company_id,
                recipient_email=email,
                reason=suppression_reason,
                detail=str(error) if error else None,
                source_message_id=provider_message_id or intent.provider_event_id,
            )
            intent.suppression_reason = f"email_{suppression.reason}"
            if current_status not in _terminal_statuses():
                intent.status = NotificationDeliveryStatus.SUPPRESSED
                intent.failed_at = when
                intent.next_attempt_at = None
                _ensure_in_app_fallback(session, intent=intent, context=None)
                suppression.fallback_sent = intent.fallback_intent_id is not None
                applied_to_state = True
    elif event_type == "processed":
        if chronological and current_status == NotificationDeliveryStatus.QUEUED:
            intent.status = NotificationDeliveryStatus.SENT
            applied_to_state = True
    elif event_type == "deferred":
        # SendGrid has accepted the message and continues retrying delivery.
        # Treat deferral as provider-state evidence only; application replay
        # would submit a duplicate external message.
        pass
    if applied_to_state:
        intent.provider_state_occurred_at = when
    _record_delivery_event(
        session,
        intent=intent,
        event_type=f"provider_{event_type}",
        status_value=str(intent.status),
        error=str(error) if error else None,
        provider="sendgrid",
        provider_event_id=provider_event_key,
        metadata={"provider_message_ref": redact_identifier(provider_message_id)},
        idempotency_key=event_idempotency_key,
        applied_to_state=applied_to_state,
    )
    intent.updated_at = _now()
    session.add(intent)
    _project_legacy_hearing_reminders(session, intent_id=intent.id)
    session.flush()
    return True


__all__ = [
    "NOTIFICATION_DISPATCH_CLAIM_IN_FLIGHT_CODE",
    "NOTIFICATION_DISPATCH_CLAIM_PREFIX",
    "NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_CODE",
    "NOTIFICATION_PROVIDER_OUTCOME_UNKNOWN_REASONS",
    "NotificationDeliveryProcessResult",
    "enqueue_notification_delivery_intent",
    "apply_notification_provider_event",
    "cancel_linked_hearing_reminder_intent_for_inactive_recipient",
    "cancel_pending_notification_intents",
    "drain_notification_delivery_intents",
    "notification_delivery_idempotency_key",
    "notification_dispatch_claim_in_flight_detail",
    "notification_dispatch_claim_state",
    "notification_intent_requires_provider_reconciliation",
    "notification_provider_reconciliation_detail",
    "link_hearing_reminder_intent",
    "project_linked_hearing_reminder_intent",
    "process_notification_delivery_intent",
    "process_notification_delivery_intent_by_id",
    "record_notification_delivery_failure",
    "redact_provider_error",
    "retry_delay_for_attempt",
    "materialize_expired_notification_dispatch_claim",
]
