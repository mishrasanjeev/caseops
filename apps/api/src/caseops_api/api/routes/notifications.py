"""Notification admin surface + SendGrid event webhook (BUG-013).

Two endpoints:

- ``POST /api/webhooks/sendgrid/events`` — receives the event batch
  SendGrid POSTs after each send. Updates ``hearing_reminders``
  rows from ``sent`` → ``delivered`` / ``failed`` by matching
  ``X-Message-Id`` we captured on send.
- ``GET /api/admin/notifications`` — tenancy-scoped paged list of
  reminder rows for the matter-ops / admin dashboard.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from caseops_api.api.dependencies import (
    DbSession,
    require_capability,
)
from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.models import (
    CompanyMembership,
    EmailSuppression,
    HearingReminder,
    HearingReminderDeliveryIntent,
    NotificationDeliveryIntent,
)
from caseops_api.schemas.calendar import (
    NotificationRuleCreateRequest,
    NotificationRuleListResponse,
    NotificationRuleRecord,
    NotificationRuleUpdateRequest,
)
from caseops_api.schemas.notification_preferences import (
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.communications import (
    apply_sendgrid_communication_event,
)
from caseops_api.services.hearing_reminders import apply_sendgrid_event
from caseops_api.services.notification_delivery import (
    apply_notification_provider_event,
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.notification_preferences import (
    notification_preferences,
    update_tenant_notification_preferences,
    update_user_notification_preferences,
)
from caseops_api.services.notification_rules import (
    create_notification_rule,
    delete_notification_rule,
    list_notification_rules,
    update_notification_rule,
)
from caseops_api.services.session_context import SessionContext

logger = logging.getLogger(__name__)


webhook_router = APIRouter()
admin_router = APIRouter()
rules_router = APIRouter()
preferences_router = APIRouter()

AdminContext = Annotated[SessionContext, Depends(require_capability("notifications:manage"))]
PreferenceContext = Annotated[SessionContext, Depends(require_capability("calendar:view"))]


class HearingReminderRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    matter_id: str | None
    ip_docket_id: str | None
    hearing_id: str
    recipient_email: str | None
    channel: str
    scheduled_for: datetime
    status: Literal[
        "queued",
        "sent",
        "delivered",
        "failed",
        "cancelled",
    ]
    provider: str | None
    provider_message_id: str | None
    last_error: str | None
    attempts: int
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    intent_ids: list[str] = Field(default_factory=list)
    delivery_status: str | None = None
    destination_version: int | None = None
    superseded_by_intent_id: str | None = None
    fallback_sent: bool = False


class NotificationIntentRecord(BaseModel):
    id: str
    channel: str
    status: str
    event_type: str
    source_type: str
    source_id: str
    scheduled_for: datetime | None
    attempts: int
    destination_version: int
    destination: str | None
    critical: bool
    suppression_reason: str | None
    fallback_intent_id: str | None
    superseded_by_intent_id: str | None
    recovery_of_intent_id: str | None
    last_error_redacted: str | None
    created_at: datetime
    updated_at: datetime


class EmailSuppressionRecord(BaseModel):
    id: str
    provider: str
    category: str
    affected_address: str
    first_occurrence: datetime
    last_occurrence: datetime
    recovery_action: str | None
    recovered_at: datetime | None
    fallback_sent: bool


class NotificationMetrics(BaseModel):
    due: int
    attempted: int
    delivered: int
    suppressed: int
    bounced: int
    failed: int
    fallback: int
    stale_queue: int
    critical_alerts: int


class HearingReminderListResponse(BaseModel):
    reminders: list[HearingReminderRecord]
    total_queued: int
    total_sent: int
    total_delivered: int
    total_failed: int
    intents: list[NotificationIntentRecord] = Field(default_factory=list)
    suppressions: list[EmailSuppressionRecord] = Field(default_factory=list)
    metrics: NotificationMetrics | None = None


class NotificationTestResponse(BaseModel):
    intent: NotificationIntentRecord
    message: str


class SuppressionRecoveryRequest(BaseModel):
    recovery_action: str = Field(min_length=8, max_length=500)
    replacement_membership_id: str | None = None


class NotificationRecoveryPreview(BaseModel):
    original_intent_id: str
    recoverable: bool
    requires_changed_destination: bool
    next_destination_version: int
    current_status: str
    impact: str


class NotificationRecoveryRequest(BaseModel):
    replacement_membership_id: str | None = None
    recovery_action: str = Field(min_length=8, max_length=500)


class WebhookAckResponse(BaseModel):
    accepted: int
    matched: int


def _intent_record(intent: NotificationDeliveryIntent) -> NotificationIntentRecord:
    snapshot = intent.recipient_snapshot_json or {}
    return NotificationIntentRecord(
        id=intent.id,
        channel=str(intent.channel),
        status=str(intent.status),
        event_type=intent.event_type,
        source_type=intent.source_type,
        source_id=intent.source_id,
        scheduled_for=intent.scheduled_for,
        attempts=intent.attempts,
        destination_version=intent.destination_version,
        destination=str(snapshot.get("destination") or "") or None,
        critical=bool(intent.critical),
        suppression_reason=intent.suppression_reason,
        fallback_intent_id=intent.fallback_intent_id,
        superseded_by_intent_id=intent.superseded_by_intent_id,
        recovery_of_intent_id=intent.recovery_of_intent_id,
        last_error_redacted=intent.last_error_redacted,
        created_at=intent.created_at,
        updated_at=intent.updated_at,
    )


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _admin_notification_response(
    session,
    *,
    company_id: str,
    rows: list[HearingReminder],
    totals: dict[str, int],
    intents: list[NotificationDeliveryIntent],
    limit: int,
) -> HearingReminderListResponse:
    links = list(
        session.scalars(
            select(HearingReminderDeliveryIntent).where(
                HearingReminderDeliveryIntent.hearing_reminder_id.in_([row.id for row in rows])
            )
        )
    ) if rows else []
    linked_intents = {
        intent.id: intent
        for intent in session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.id.in_([link.intent_id for link in links])
            )
        )
    } if links else {}
    by_reminder: dict[str, list[HearingReminderDeliveryIntent]] = {}
    for link in links:
        by_reminder.setdefault(link.hearing_reminder_id, []).append(link)
    reminder_records: list[HearingReminderRecord] = []
    for row in rows:
        row_links = by_reminder.get(row.id, [])
        primary_link = next((link for link in row_links if link.is_primary), None)
        primary = linked_intents.get(primary_link.intent_id) if primary_link else None
        reminder_records.append(
            HearingReminderRecord.model_validate(row).model_copy(
                update={
                    "intent_ids": [link.intent_id for link in row_links],
                    "delivery_status": str(primary.status) if primary else None,
                    "destination_version": primary.destination_version if primary else None,
                    "superseded_by_intent_id": primary.superseded_by_intent_id if primary else None,
                    "fallback_sent": bool(primary and primary.fallback_intent_id),
                }
            )
        )
    suppressions = list(
        session.scalars(
            select(EmailSuppression)
            .where(EmailSuppression.company_id == company_id)
            .order_by(desc(EmailSuppression.last_event_at))
            .limit(limit)
        )
    )
    all_intents = list(
        session.scalars(
            select(NotificationDeliveryIntent).where(
                NotificationDeliveryIntent.company_id == company_id
            )
        )
    )
    now = datetime.now(UTC)
    due = sum(
        1 for intent in all_intents
        if str(intent.status) in {"queued", "retry_scheduled"}
        and (intent.scheduled_for is None or _aware(intent.scheduled_for) <= now)
    )
    failed_statuses = {"dead_letter", "blocked"}
    alert_statuses = failed_statuses | {"suppressed", "bounced"}
    return HearingReminderListResponse(
        reminders=reminder_records,
        total_queued=totals["queued"],
        total_sent=totals["sent"],
        total_delivered=totals["delivered"],
        total_failed=totals["failed"],
        intents=[_intent_record(intent) for intent in intents],
        suppressions=[
            EmailSuppressionRecord(
                id=item.id,
                provider=item.provider,
                category=str(item.reason),
                affected_address=item.recipient_email,
                first_occurrence=item.first_event_at,
                last_occurrence=item.last_event_at,
                recovery_action=item.recovery_action,
                recovered_at=item.recovered_at,
                fallback_sent=bool(item.fallback_sent),
            ) for item in suppressions
        ],
        metrics=NotificationMetrics(
            due=due,
            attempted=sum(intent.attempts > 0 for intent in all_intents),
            delivered=sum(str(intent.status) == "delivered" for intent in all_intents),
            suppressed=sum(str(intent.status) == "suppressed" for intent in all_intents),
            bounced=sum(str(intent.status) == "bounced" for intent in all_intents),
            failed=sum(str(intent.status) in failed_statuses for intent in all_intents),
            fallback=sum(bool(intent.fallback_intent_id) for intent in all_intents),
            stale_queue=sum(
                str(intent.status) in {"queued", "retry_scheduled"}
                and _aware(intent.created_at) <= now - timedelta(minutes=15)
                for intent in all_intents
            ),
            critical_alerts=sum(
                bool(intent.critical) and str(intent.status) in alert_statuses
                for intent in all_intents
            ),
        ),
    )


# ---------------------------------------------------------------
# SendGrid event webhook — https://docs.sendgrid.com/for-developers/
# tracking-events/event
# ---------------------------------------------------------------


class WebhookConfigError(Exception):
    """Raised when the SendGrid webhook cannot be safely verified
    AND the env doesn't permit the unverified fallback. The route
    layer translates this into a 503 so a misconfigured prod cannot
    silently accept unsigned events."""


def _is_local_env() -> bool:
    return not is_non_local_env(get_settings().env)


def _verify_sendgrid_signature(
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    public_key_b64: str | None,
) -> bool:
    """Verify SendGrid's ECDSA-signed webhook.

    P0-004 (2026-04-24, QG-NOTIF-003/-004) — fail closed outside
    local/test:

    - In local/test env, an unconfigured public key downgrades to
      "skip + warn" so dev work doesn't need a real ECDSA key.
    - In every other env (dev / staging / production), the absence
      of either ``CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY`` or the
      ``cryptography`` library raises ``WebhookConfigError`` so the
      route returns 503. Silent fail-open is gone.
    """
    local = _is_local_env()
    if not public_key_b64:
        if local:
            logger.warning(
                "SendGrid webhook signature check SKIPPED in local env — "
                "set CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY to enforce.",
            )
            return True
        logger.error(
            "SendGrid webhook signature key MISSING in non-local env — "
            "rejecting webhook to prevent silent fail-open.",
        )
        raise WebhookConfigError("SendGrid webhook public key is not configured.")
    if not signature or not timestamp:
        return False
    try:
        import base64

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError as exc:
        if local:
            logger.warning(
                "cryptography lib unavailable in local env; skipping sig check",
            )
            return True
        logger.error(
            "cryptography lib unavailable in non-local env — "
            "rejecting webhook to prevent silent fail-open.",
        )
        raise WebhookConfigError(
            "cryptography lib is required to verify SendGrid signatures."
        ) from exc
    try:
        key_der = base64.b64decode(public_key_b64)
        public_key = serialization.load_der_public_key(key_der)
        payload = timestamp.encode("utf-8") + body
        sig_bytes = base64.b64decode(signature)
        public_key.verify(sig_bytes, payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (ValueError, TypeError, InvalidSignature):
        return False


@webhook_router.post(
    "/sendgrid/events",
    response_model=WebhookAckResponse,
    summary="Receive SendGrid event-notification webhook",
)
async def sendgrid_events(
    request: Request,
    session: DbSession,
    signature: Annotated[str | None, Header(alias="X-Twilio-Email-Event-Webhook-Signature")] = None,
    timestamp: Annotated[str | None, Header(alias="X-Twilio-Email-Event-Webhook-Timestamp")] = None,
) -> WebhookAckResponse:
    body = await request.body()
    settings = get_settings()
    try:
        valid = _verify_sendgrid_signature(
            body,
            signature,
            timestamp,
            settings.sendgrid_webhook_public_key,
        )
    except WebhookConfigError as exc:
        # P0-004: fail closed when prod isn't configured to verify.
        # 503 because the request is well-formed; the SERVER is
        # missing config required to process it safely.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "SendGrid webhook verification is not available in this "
                "environment. Configure CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY "
                "and the cryptography dependency."
            ),
        ) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SendGrid webhook signature verification failed.",
        )
    try:
        events = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Malformed event payload: {exc}",
        ) from exc
    if not isinstance(events, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expected a JSON array of events.",
        )
    matched = 0
    for ev in events:
        if not isinstance(ev, dict):
            continue
        # The same SendGrid X-Message-Id is shared by hearing
        # reminders AND AutoMail sends. Try both handlers per
        # event — only one will find a matching row in practice.
        # Phase B M11 slice 2 (FT-048).
        hit_reminder = apply_sendgrid_event(session, event=ev)
        hit_communication = apply_sendgrid_communication_event(
            session,
            event=ev,
        )
        hit_intent = apply_notification_provider_event(session, event=ev)
        if hit_reminder or hit_communication or hit_intent:
            matched += 1
    session.commit()
    return WebhookAckResponse(accepted=len(events), matched=matched)


# ---------------------------------------------------------------
# Admin list — tenancy-scoped reminder dashboard
# ---------------------------------------------------------------


@admin_router.get(
    "/notifications",
    response_model=HearingReminderListResponse,
    summary="List hearing reminders for this workspace",
)
async def list_admin_notifications(
    context: AdminContext,
    session: DbSession,
    status_filter: Annotated[
        Literal["all", "queued", "sent", "delivered", "failed", "cancelled"],
        "query",
    ] = "all",
    limit: int = 50,
) -> HearingReminderListResponse:
    limit = max(1, min(limit, 200))
    stmt = (
        select(HearingReminder)
        .where(HearingReminder.company_id == context.company.id)
        .options(selectinload(HearingReminder.hearing))
        .order_by(
            desc(HearingReminder.scheduled_for),
            desc(HearingReminder.created_at),
        )
        .limit(limit)
    )
    if status_filter != "all":
        stmt = stmt.where(HearingReminder.status == status_filter)
    rows = list(session.scalars(stmt))

    # Counters — cheap group-by in Python since the tenant's reminder
    # count is bounded (hearings * offsets * users).
    all_rows = list(
        session.scalars(
            select(HearingReminder).where(HearingReminder.company_id == context.company.id)
        )
    )
    totals = {
        "queued": 0,
        "sent": 0,
        "delivered": 0,
        "failed": 0,
    }
    for r in all_rows:
        if r.status in totals:
            totals[r.status] += 1
    intents = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(NotificationDeliveryIntent.company_id == context.company.id)
            .order_by(
                desc(NotificationDeliveryIntent.created_at),
                desc(NotificationDeliveryIntent.id),
            )
            .limit(limit)
        )
    )
    return _admin_notification_response(
        session,
        company_id=context.company.id,
        rows=rows,
        totals=totals,
        intents=intents,
        limit=limit,
    )


@preferences_router.post(
    "/test",
    response_model=NotificationTestResponse,
    summary="Create and deliver a safe self-service in-app test notification.",
)
async def test_current_user_notification(
    context: PreferenceContext,
    session: DbSession,
) -> NotificationTestResponse:
    intent = enqueue_notification_delivery_intent(
        session,
        context=context,
        recipient_membership=context.membership,
        channel="in_app",
        event_type="notification_test",
        source_type="self_service_test",
        source_id=str(uuid4()),
        title="Test notification",
        body="Your CaseOps in-app notification channel is working.",
    )
    if intent is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The current notification target is not eligible.",
        )
    process_notification_delivery_intent(
        session,
        intent_id=intent.id,
        context=context,
    )
    record_from_context(
        session,
        context,
        action="notification.test.completed",
        target_type="notification_delivery_intent",
        target_id=intent.id,
        metadata={"channel": "in_app", "external_calls": 0},
    )
    session.commit()
    session.refresh(intent)
    return NotificationTestResponse(
        intent=_intent_record(intent),
        message="In-app test delivered without contacting an external provider.",
    )


@admin_router.post(
    "/notifications/suppressions/{suppression_id}/recover",
    response_model=EmailSuppressionRecord,
    summary="Recover a suppression while preserving its provider evidence.",
)
async def recover_admin_suppression(
    suppression_id: str,
    payload: SuppressionRecoveryRequest,
    context: AdminContext,
    session: DbSession,
) -> EmailSuppressionRecord:
    suppression = session.scalar(
        select(EmailSuppression).where(
            EmailSuppression.id == suppression_id,
            EmailSuppression.company_id == context.company.id,
        )
    )
    if suppression is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suppression not found.")
    if suppression.recovered_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Suppression has already been recovered.",
        )
    if suppression.reason == "bounce":
        if not payload.replacement_membership_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Permanent bounce recovery requires a changed destination.",
            )
        replacement = session.scalar(
            select(CompanyMembership).where(
                CompanyMembership.id == payload.replacement_membership_id,
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
            )
        )
        if (
            replacement is None
            or replacement.user is None
            or replacement.user.email.strip().lower() == suppression.recipient_email
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Permanent bounce recovery requires a different active destination.",
            )
    from caseops_api.services.email_suppression import recover_suppression

    recover_suppression(
        session,
        suppression=suppression,
        recovered_by_membership_id=context.membership.id,
        recovery_action=payload.recovery_action,
    )
    record_from_context(
        session,
        context,
        action="notification.suppression.recovered",
        target_type="email_suppression",
        target_id=suppression.id,
        metadata={
            "provider": suppression.provider,
            "category": suppression.reason,
            "changed_destination": bool(payload.replacement_membership_id),
        },
    )
    session.commit()
    return EmailSuppressionRecord(
        id=suppression.id,
        provider=suppression.provider,
        category=str(suppression.reason),
        affected_address=suppression.recipient_email,
        first_occurrence=suppression.first_event_at,
        last_occurrence=suppression.last_event_at,
        recovery_action=suppression.recovery_action,
        recovered_at=suppression.recovered_at,
        fallback_sent=bool(suppression.fallback_sent),
    )


@admin_router.get(
    "/notifications/intents/{intent_id}/recovery-preview",
    response_model=NotificationRecoveryPreview,
    summary="Preview a notification recovery without dispatching it.",
)
async def preview_notification_recovery(
    intent_id: str,
    context: AdminContext,
    session: DbSession,
) -> NotificationRecoveryPreview:
    intent = session.scalar(
        select(NotificationDeliveryIntent).where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == context.company.id,
        )
    )
    if intent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intent not found.")
    recoverable = str(intent.status) in {
        "blocked", "suppressed", "bounced", "dead_letter", "retry_scheduled",
    }
    return NotificationRecoveryPreview(
        original_intent_id=intent.id,
        recoverable=recoverable,
        requires_changed_destination=str(intent.status) == "bounced",
        next_destination_version=intent.destination_version + 1,
        current_status=str(intent.status),
        impact=(
            "Creates a new immutable destination/version and retains the original attempts, "
            "provider events, fallback, and failure evidence."
        ),
    )


@admin_router.post(
    "/notifications/intents/{intent_id}/recover",
    response_model=NotificationTestResponse,
    summary="Create a versioned recovery intent after preview.",
)
async def recover_notification_intent(
    intent_id: str,
    payload: NotificationRecoveryRequest,
    context: AdminContext,
    session: DbSession,
) -> NotificationTestResponse:
    original = session.scalar(
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == context.company.id,
        )
        .with_for_update(of=NotificationDeliveryIntent)
    )
    if original is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intent not found.")
    if str(original.status) not in {
        "blocked", "suppressed", "bounced", "dead_letter", "retry_scheduled",
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only failed, suppressed, bounced, blocked, or retrying intents "
                "are recoverable."
            ),
        )
    target_id = payload.replacement_membership_id or original.recipient_membership_id
    if not target_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Choose an active internal replacement destination for this recovery.",
        )
    replacement = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == target_id,
            CompanyMembership.company_id == context.company.id,
            CompanyMembership.is_active.is_(True),
        )
    )
    if replacement is None or replacement.user is None or not replacement.user.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery destination is not an active workspace membership.",
        )
    original_destination = str((original.recipient_snapshot_json or {}).get("destination") or "")
    if (
        str(original.status) == "bounced"
        and replacement.user.email.strip().lower() == original_destination.strip().lower()
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Permanent bounce recovery requires a changed destination.",
        )
    new_version = original.destination_version + 1
    recovered = enqueue_notification_delivery_intent(
        session,
        context=context,
        recipient_membership=replacement,
        channel=str(original.channel),
        event_type=original.event_type,
        source_type="notification_recovery",
        source_id=f"{original.id}:v{new_version}",
        matter=original.matter,
        notification_rule_id=original.notification_rule_id,
        title=original.title or "Recovered notification",
        body=original.body or "Open CaseOps to review this recovered notification.",
        destination_version=new_version,
        critical=bool(original.critical),
        escalation_membership=replacement,
        recovery_of_intent_id=original.id,
        schedule_source_type=original.schedule_source_type,
        schedule_source_id=original.schedule_source_id,
    )
    if recovered is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Recovery destination is not permitted for the source record.",
        )
    original.superseded_by_intent_id = recovered.id
    session.add(original)
    record_from_context(
        session,
        context,
        action="notification.delivery.recovered",
        target_type="notification_delivery_intent",
        target_id=recovered.id,
        matter_id=original.matter_id,
        metadata={
            "original_intent_id": original.id,
            "destination_version": new_version,
            "changed_destination": replacement.id != original.recipient_membership_id,
            "recovery_action": payload.recovery_action,
        },
    )
    if recovered.channel == "in_app":
        process_notification_delivery_intent(
            session,
            intent_id=recovered.id,
            context=context,
        )
    session.commit()
    session.refresh(recovered)
    return NotificationTestResponse(
        intent=_intent_record(recovered),
        message="Recovery intent created; original delivery evidence remains immutable.",
    )


@admin_router.get(
    "/notification-preferences",
    response_model=NotificationPreferenceResponse,
    summary="Read tenant and current-user notification preferences.",
)
async def get_admin_notification_preferences(
    context: AdminContext,
    session: DbSession,
) -> NotificationPreferenceResponse:
    return notification_preferences(session, context=context)


@admin_router.patch(
    "/notification-preferences",
    response_model=NotificationPreferenceResponse,
    summary="Update tenant-level notification defaults and policy.",
)
async def patch_admin_notification_preferences(
    context: AdminContext,
    session: DbSession,
    payload: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceResponse:
    return update_tenant_notification_preferences(
        session,
        context=context,
        payload=payload,
    )


@preferences_router.get(
    "",
    response_model=NotificationPreferenceResponse,
    summary="Read current user's notification preferences.",
)
async def get_notification_preferences(
    context: PreferenceContext,
    session: DbSession,
) -> NotificationPreferenceResponse:
    return notification_preferences(session, context=context)


@preferences_router.patch(
    "",
    response_model=NotificationPreferenceResponse,
    summary="Update current user's notification opt-in/opt-out preferences.",
)
async def patch_notification_preferences(
    context: PreferenceContext,
    session: DbSession,
    payload: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceResponse:
    return update_user_notification_preferences(
        session,
        context=context,
        payload=payload,
    )


@rules_router.get(
    "",
    response_model=NotificationRuleListResponse,
    summary="List tenant-scoped notification rules.",
)
async def list_rules(
    context: AdminContext,
    session: DbSession,
) -> NotificationRuleListResponse:
    return list_notification_rules(session, context=context)


@rules_router.post(
    "",
    response_model=NotificationRuleRecord,
    summary="Create a tenant-scoped notification rule.",
)
async def create_rule(
    context: AdminContext,
    session: DbSession,
    payload: NotificationRuleCreateRequest,
) -> NotificationRuleRecord:
    return create_notification_rule(session, context=context, payload=payload)


@rules_router.patch(
    "/{rule_id}",
    response_model=NotificationRuleRecord,
    summary="Update a tenant-scoped notification rule.",
)
async def patch_rule(
    context: AdminContext,
    session: DbSession,
    rule_id: str,
    payload: NotificationRuleUpdateRequest,
) -> NotificationRuleRecord:
    return update_notification_rule(
        session,
        context=context,
        rule_id=rule_id,
        payload=payload,
    )


@rules_router.delete(
    "/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a tenant-scoped notification rule.",
)
async def delete_rule(
    context: AdminContext,
    session: DbSession,
    rule_id: str,
) -> None:
    delete_notification_rule(session, context=context, rule_id=rule_id)
