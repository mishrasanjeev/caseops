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

from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Communication,
    CommunicationStatus,
    Matter,
)
from caseops_api.schemas.communications import (
    CommunicationCreateRequest,
    CommunicationListResponse,
    CommunicationRecord,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access


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


__all__ = [
    "create_matter_communication",
    "list_matter_communications",
]
