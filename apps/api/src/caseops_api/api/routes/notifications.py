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
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import desc, select
from sqlalchemy.orm import selectinload

from caseops_api.api.dependencies import (
    DbSession,
    get_current_context,
    require_capability,
)
from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.db.models import HearingReminder
from caseops_api.services.communications import (
    apply_sendgrid_communication_event,
)
from caseops_api.services.hearing_reminders import apply_sendgrid_event
from caseops_api.services.identity import SessionContext

logger = logging.getLogger(__name__)


webhook_router = APIRouter()
admin_router = APIRouter()

CurrentContext = Annotated[SessionContext, Depends(get_current_context)]
AdminContext = Annotated[
    SessionContext, Depends(require_capability("workspace:admin"))
]


class HearingReminderRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    company_id: str
    matter_id: str
    hearing_id: str
    recipient_email: str | None
    channel: str
    scheduled_for: datetime
    status: Literal[
        "queued", "sent", "delivered", "failed", "cancelled",
    ]
    provider: str | None
    provider_message_id: str | None
    last_error: str | None
    attempts: int
    sent_at: datetime | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class HearingReminderListResponse(BaseModel):
    reminders: list[HearingReminderRecord]
    total_queued: int
    total_sent: int
    total_delivered: int
    total_failed: int


class WebhookAckResponse(BaseModel):
    accepted: int
    matched: int


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
        raise WebhookConfigError(
            "SendGrid webhook public key is not configured."
        )
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
                "cryptography lib unavailable in local env; "
                "skipping sig check",
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
            body, signature, timestamp, settings.sendgrid_webhook_public_key,
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
            session, event=ev,
        )
        if hit_reminder or hit_communication:
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
            select(HearingReminder)
            .where(HearingReminder.company_id == context.company.id)
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
    _ = UTC  # reserved for future "due in N minutes" filter
    return HearingReminderListResponse(
        reminders=[HearingReminderRecord.model_validate(r) for r in rows],
        total_queued=totals["queued"],
        total_sent=totals["sent"],
        total_delivered=totals["delivered"],
        total_failed=totals["failed"],
    )
