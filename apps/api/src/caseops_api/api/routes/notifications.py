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
from caseops_api.core.settings import get_settings
from caseops_api.db.models import HearingReminder
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


def _verify_sendgrid_signature(
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    public_key_b64: str | None,
) -> bool:
    """Verify SendGrid's ECDSA-signed webhook. Disabled when no
    public key is configured (UAT / initial rollout); logged loudly
    so ops can't forget to wire it."""
    if not public_key_b64:
        logger.warning(
            "SendGrid webhook signature check SKIPPED — set "
            "CASEOPS_SENDGRID_WEBHOOK_PUBLIC_KEY to enforce.",
        )
        return True
    if not signature or not timestamp:
        return False
    try:
        import base64

        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:  # pragma: no cover — cryptography already in tree
        logger.warning("cryptography lib unavailable; skipping sig check")
        return True
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
    if not _verify_sendgrid_signature(
        body, signature, timestamp, settings.sendgrid_webhook_public_key,
    ):
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
        if apply_sendgrid_event(session, event=ev):
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
