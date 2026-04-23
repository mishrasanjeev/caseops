"""Phase B / J12 / M11 — communications log service.

Slice 1: manual logging only. The lawyer types into a "Log
communication" form and we record what they pasted in. Slice 2 will
add a Send-via-SendGrid path on the same row (status pivots from
``logged`` → ``queued`` → ``sent`` → ``delivered``).

Tenant isolation contract: every read and every write joins on
``Matter.company_id == context.company.id``. Without that join a
matter_id could be guessed and another tenant's history disclosed.
The service helper that loads the matter (``_load_matter``) raises
404 — we never report 403 on a matter the caller doesn't own
because that confirms the matter exists.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    EmailTemplate,
    Matter,
)
from caseops_api.schemas.communications import (
    CommunicationCreateRequest,
    CommunicationListResponse,
    CommunicationRecord,
)
from caseops_api.schemas.email_templates import EmailSendRequest
from caseops_api.services.email_templates import render_template
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access

logger = logging.getLogger(__name__)


def _load_matter(
    session: Session, *, context: SessionContext, matter_id: str,
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        # Same 404 the rest of the matter surface returns when the
        # caller doesn't own the matter — never confirm existence to
        # an unauthorised tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    return matter


def list_matter_communications(
    session: Session, *, context: SessionContext, matter_id: str,
) -> CommunicationListResponse:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    rows = list(
        session.scalars(
            select(Communication)
            .where(Communication.matter_id == matter.id)
            .order_by(Communication.occurred_at.desc())
        )
    )
    return CommunicationListResponse(
        matter_id=matter.id,
        communications=[CommunicationRecord.model_validate(r) for r in rows],
    )


def create_matter_communication(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: CommunicationCreateRequest,
) -> CommunicationRecord:
    matter = _load_matter(session, context=context, matter_id=matter_id)
    occurred = payload.occurred_at or datetime.now(UTC)
    row = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        client_id=payload.client_id,
        direction=payload.direction,
        channel=payload.channel,
        subject=payload.subject,
        body=payload.body,
        recipient_name=payload.recipient_name,
        recipient_email=str(payload.recipient_email)
        if payload.recipient_email else None,
        recipient_phone=payload.recipient_phone,
        # Slice 1 is manual logging — terminal status is LOGGED. Slice
        # 2's send path will start at QUEUED instead.
        status=CommunicationStatus.LOGGED,
        occurred_at=occurred,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return CommunicationRecord.model_validate(row)


def send_matter_email(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: EmailSendRequest,
) -> CommunicationRecord:
    """Phase B M11 slice 2 — Compose & send.

    Picks the named template, renders it with the user-supplied
    variables, dispatches via SendGrid, and writes the resulting
    ``communications`` row. The webhook handler later transitions
    ``status`` from ``sent`` → ``delivered`` / ``opened`` /
    ``bounced`` as events arrive (matched by external_message_id).

    Refuses to send when:

    - the template doesn't belong to the caller's company (404)
    - the template declares required variables the caller did not
      supply (400 — actionable detail lists the missing names)
    - SendGrid isn't configured in this env (503)
    """
    matter = _load_matter(session, context=context, matter_id=matter_id)

    template = session.scalar(
        select(EmailTemplate).where(
            EmailTemplate.id == payload.template_id,
            EmailTemplate.company_id == context.company.id,
            EmailTemplate.is_active.is_(True),
        )
    )
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email template not found or archived.",
        )

    rendered = render_template(template=template, variables=payload.variables)
    if rendered.missing_variables:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Required template variables are missing: "
                + ", ".join(rendered.missing_variables)
            ),
        )

    settings = get_settings()
    if not (settings.sendgrid_api_key and settings.sendgrid_sender_email):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Email sending is not configured for this workspace. "
                "Ask your workspace admin to set up SendGrid."
            ),
        )

    success, message_id, error = _send_via_sendgrid(
        to_email=str(payload.recipient_email),
        recipient_name=payload.recipient_name,
        subject=rendered.subject,
        body_text=rendered.body,
    )
    now = datetime.now(UTC)
    row = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        client_id=payload.client_id,
        direction=CommunicationDirection.OUTBOUND,
        channel=CommunicationChannel.EMAIL,
        subject=rendered.subject,
        body=rendered.body,
        recipient_name=payload.recipient_name,
        recipient_email=str(payload.recipient_email),
        status=CommunicationStatus.SENT if success else CommunicationStatus.FAILED,
        occurred_at=now,
        external_message_id=message_id,
        metadata_json={
            "template_id": template.id,
            "template_name": template.name,
            "send_error": error,
        } if (template or error) else None,
        created_by_membership_id=context.membership.id,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    if not success:
        # Surface the failure but the row is still persisted so the
        # operator can see it on the Communications tab. The 502 has
        # an actionable detail.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"SendGrid refused the message: {error}. The communication "
                "was logged with status=failed; you can re-send from a "
                "fresh Compose dialog."
            ),
        )
    return CommunicationRecord.model_validate(row)


def _send_via_sendgrid(
    *,
    to_email: str,
    recipient_name: str | None,
    subject: str,
    body_text: str,
) -> tuple[bool, str | None, str | None]:
    """Direct SendGrid Web API call. Mirrors the helper in
    services.hearing_reminders so we don't pull in the full SDK
    for one POST.

    Returns ``(success, provider_message_id, error)``. On 200/202
    the X-Message-Id header lets the webhook handler tie a delivery
    event back to the originating row.
    """
    import httpx

    settings = get_settings()
    to_block: dict = {"email": to_email}
    if recipient_name:
        to_block["name"] = recipient_name
    response = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={
            "Authorization": f"Bearer {settings.sendgrid_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "personalizations": [{"to": [to_block]}],
            "from": {
                "email": settings.sendgrid_sender_email,
                "name": settings.sendgrid_sender_name,
            },
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": body_text},
            ],
        },
        timeout=20,
    )
    if response.status_code in (200, 202):
        msg_id = response.headers.get("X-Message-Id") or response.headers.get(
            "x-message-id"
        )
        return True, msg_id, None
    return (
        False,
        None,
        f"sendgrid {response.status_code}: {response.text[:200]}",
    )


# SendGrid event names we promote to a CommunicationStatus.
_SENDGRID_EVENT_TO_STATUS: dict[str, str] = {
    "delivered": CommunicationStatus.DELIVERED,
    "open": CommunicationStatus.OPENED,
    "bounce": CommunicationStatus.BOUNCED,
    "dropped": CommunicationStatus.BOUNCED,
    "spamreport": CommunicationStatus.BOUNCED,
}

# Status promotion order — never demote (e.g. an "open" event
# arriving after "delivered" should keep the row at OPENED;
# a stray "delivered" arriving after "opened" should not regress).
_STATUS_RANK: dict[str, int] = {
    CommunicationStatus.LOGGED: 0,
    CommunicationStatus.QUEUED: 1,
    CommunicationStatus.FAILED: 2,
    CommunicationStatus.SENT: 3,
    CommunicationStatus.DELIVERED: 4,
    CommunicationStatus.OPENED: 5,
    CommunicationStatus.BOUNCED: 6,
}


def apply_sendgrid_communication_event(
    session: Session, *, event: dict,
) -> bool:
    """Update a ``Communication`` row from a SendGrid event payload.

    Match key is ``sg_message_id`` from the event ↔
    ``Communication.external_message_id`` we stored at send time.
    Returns True when a row was updated; False when there was no
    matching row (event for a different sender / hearing-reminder
    channel — silently ignored).

    Idempotent: replaying the same event is safe; status only moves
    forward in the rank table above.
    """
    sg_message_id = (event.get("sg_message_id") or "").strip()
    event_name = (event.get("event") or "").strip().lower()
    if not sg_message_id or not event_name:
        return False

    target_status = _SENDGRID_EVENT_TO_STATUS.get(event_name)
    if target_status is None:
        # Many SendGrid events (processed, click, deferred) we
        # ignore — they don't change the high-level status the UI
        # cares about.
        return False

    # SendGrid mangles message IDs in the X-Message-Id header
    # ("ABCDEF.filterdrecv-12345") and in the webhook's
    # sg_message_id ("ABCDEF.filterdrecv-12345.0"). Match the prefix
    # before the second dot.
    base_id = sg_message_id.split(".")[0]
    row = session.scalar(
        select(Communication).where(
            Communication.external_message_id.like(f"{base_id}%"),
        )
    )
    if row is None:
        return False

    if _STATUS_RANK.get(target_status, -1) > _STATUS_RANK.get(row.status, -1):
        row.status = target_status

    timestamp_iso = event.get("timestamp")
    when = (
        datetime.fromtimestamp(int(timestamp_iso), tz=UTC)
        if isinstance(timestamp_iso, (int, float))
        else datetime.now(UTC)
    )
    if event_name == "delivered" and row.delivered_at is None:
        row.delivered_at = when
    if event_name == "open" and row.opened_at is None:
        row.opened_at = when
    session.flush()
    return True


__all__ = [
    "apply_sendgrid_communication_event",
    "create_matter_communication",
    "list_matter_communications",
    "send_matter_email",
]
