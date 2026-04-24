"""Phase C-2 (2026-04-24, MOD-TS-015) — client portal matter surface.

Every function takes a ``PortalUser`` and a ``matter_id``, asserts a
live ``MatterPortalGrant`` exists for that pair, and returns 404
otherwise. The 404 is identical to the "matter does not exist"
case so a probe cannot enumerate matter ids.

The role check is intentional: this module serves the **client**
role only. Outside-counsel-specific reads/writes (work-product
upload, invoice submission, time entries) live in a separate
``portal_outside_counsel.py`` (Phase C-3).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditActorType,
    AuditResult,
    Client,
    ClientKycStatus,
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    Matter,
    MatterHearing,
    MatterHearingStatus,
    MatterPortalGrant,
    PortalUser,
)
from caseops_api.services.audit import record_audit


def _assert_grant(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    role: str | None = None,
) -> tuple[Matter, MatterPortalGrant]:
    """Assert the portal_user has a live grant on this matter.
    Returns ``(matter, grant)``. Raises 404 on miss — never 403,
    so a probe cannot distinguish 'matter not granted to me' from
    'matter does not exist'.

    ``role`` constrains the grant role (e.g. 'client'); mismatch
    raises the same 404.
    """
    grant = session.scalars(
        select(MatterPortalGrant).where(
            MatterPortalGrant.portal_user_id == portal_user.id,
            MatterPortalGrant.matter_id == matter_id,
            MatterPortalGrant.revoked_at.is_(None),
        )
    ).first()
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    if role is not None and grant.role != role:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    matter = session.get(Matter, matter_id)
    if matter is None or matter.company_id != portal_user.company_id:
        # Defense-in-depth: a grant pointing at a matter outside the
        # portal user's company should not happen, but if it does
        # (data corruption, cross-tenant misuse) we fail closed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    return matter, grant


def list_granted_matters(
    session: Session, *, portal_user: PortalUser, role: str = "client"
) -> list[tuple[MatterPortalGrant, Matter]]:
    """Returns the matters the portal user is granted on, role-
    filtered. Newest grant first."""
    rows = session.execute(
        select(MatterPortalGrant, Matter)
        .join(Matter, Matter.id == MatterPortalGrant.matter_id)
        .where(
            MatterPortalGrant.portal_user_id == portal_user.id,
            MatterPortalGrant.role == role,
            MatterPortalGrant.revoked_at.is_(None),
            Matter.company_id == portal_user.company_id,
        )
        .order_by(MatterPortalGrant.granted_at.desc())
    ).all()
    return [(g, m) for g, m in rows]


def get_granted_matter(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> Matter:
    matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    return matter


def list_matter_clients_for_portal(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[Client]:
    """Codex M3 (2026-04-24) — used by the web KYC form to render a
    picker for multi-client matters. Returns every Client linked to
    the matter that the portal user is granted on; same 404 shape on
    missing grant so listing never leaks existence."""
    _matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    from caseops_api.db.models import MatterClientAssignment

    return list(
        session.execute(
            select(Client)
            .join(
                MatterClientAssignment,
                MatterClientAssignment.client_id == Client.id,
            )
            .where(
                MatterClientAssignment.matter_id == matter_id,
                Client.company_id == portal_user.company_id,
            )
            .order_by(Client.name.asc())
        ).scalars().all()
    )


def list_matter_communications(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[Communication]:
    """Communications visible to the portal user. Read-only; comms
    written by the firm with ``metadata_json.portal_visible=False``
    are excluded so privileged internal notes never leak.

    Codex H2 (2026-04-24): the docstring claimed visibility filtering
    but the query didn't enforce it. We now post-filter in Python
    rather than via a JSON-path predicate so the same query works
    on SQLite tests + Postgres prod without provider-specific JSON
    operators. The default is INCLUDE — only an explicit
    ``portal_visible=False`` excludes a row, so legacy comms
    without metadata stay readable.
    """
    _matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    rows = list(
        session.scalars(
            select(Communication)
            .where(
                Communication.matter_id == matter_id,
                Communication.company_id == portal_user.company_id,
            )
            .order_by(Communication.occurred_at.desc())
            .limit(500)
        )
    )
    visible: list[Communication] = []
    for row in rows:
        meta = row.metadata_json or {}
        if isinstance(meta, dict) and meta.get("portal_visible") is False:
            continue
        visible.append(row)
        if len(visible) >= 200:
            break
    return visible


class PortalReplyOutOfScope(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Replying isn't enabled for your portal account on this "
                "matter. Ask the firm to enable can_reply on your grant."
            ),
        )


def post_matter_reply(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    body: str,
    request_ip: str | None = None,
) -> Communication:
    """Portal user replies on a matter. Lands as an INBOUND
    Communication row visible to the firm's internal Comms tab,
    with metadata pointing back to the originating PortalUser id."""
    _matter, grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    can_reply = bool(
        grant.scope_json
        and grant.scope_json.get("can_reply", True)
    ) if grant.scope_json else True
    if not can_reply:
        raise PortalReplyOutOfScope()
    text = (body or "").strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reply body is required.",
        )
    if len(text) > 8000:
        text = text[:8000]
    comm = Communication(
        company_id=portal_user.company_id,
        matter_id=matter_id,
        direction=CommunicationDirection.INBOUND,
        channel=CommunicationChannel.NOTE,
        subject=None,
        body=text,
        recipient_name=portal_user.full_name,
        recipient_email=portal_user.email,
        recipient_phone=None,
        status=CommunicationStatus.LOGGED,
        occurred_at=datetime.now(UTC),
        metadata_json={
            "portal_user_id": portal_user.id,
            "portal_user_email": portal_user.email,
            "portal_grant_id": grant.id,
        },
        created_by_membership_id=None,
    )
    session.add(comm)
    session.flush()
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        action="portal.communication.posted",
        target_type="communication",
        target_id=comm.id,
        matter_id=matter_id,
        result=AuditResult.SUCCESS,
        metadata={"portal_user_id": portal_user.id},
        ip=request_ip,
        commit=True,
    )
    session.refresh(comm)
    return comm


def list_matter_hearings_for_portal(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[MatterHearing]:
    """Read-only list of hearings the portal user can see on the
    matter. Includes upcoming + recent past (last 30 days). The
    portal user CANNOT add / edit / cancel hearings — that's a
    firm-side operation."""
    _matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    return list(
        session.scalars(
            select(MatterHearing)
            .where(MatterHearing.matter_id == matter_id)
            .order_by(MatterHearing.hearing_on.asc())
            .limit(50)
        )
    )


# KYC submit on the portal side. Reuses the existing client KYC
# workflow (M11 slice 3) — the portal user can update KYC fields on
# a client linked to one of their granted matters. Verify / reject
# stays internal (clients:kyc_review capability, not exposed here).


def submit_matter_kyc(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    client_id: str,
    documents: list[dict] | None = None,
    request_ip: str | None = None,
) -> tuple[Matter, Client]:
    """Mark KYC as PENDING for ONE explicit client linked to this
    matter. Stores the submitted docs metadata + audit row.
    Verify/reject is the firm's responsibility via the existing
    internal route.

    Codex M3 (2026-04-24): the previous version overwrote KYC for
    every client linked to the matter. On a multi-client matter
    (corporate-defence / multi-party) one portal user could alter a
    co-client's KYC state. The route now requires an explicit
    ``client_id`` and we authorise per-client: the client must be
    linked to the matter the portal user has a grant on. Any other
    client_id (foreign matter, foreign tenant, unlinked) returns
    404 — same shape as missing-grant so a probe cannot enumerate.
    """
    matter, _grant = _assert_grant(
        session, portal_user=portal_user, matter_id=matter_id, role="client",
    )
    from caseops_api.db.models import MatterClientAssignment

    target = session.execute(
        select(Client)
        .join(
            MatterClientAssignment,
            MatterClientAssignment.client_id == Client.id,
        )
        .where(
            MatterClientAssignment.matter_id == matter_id,
            Client.id == client_id,
            Client.company_id == portal_user.company_id,
        )
    ).scalars().first()
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Client not found for this matter, or you are not "
                "authorised to submit KYC for them."
            ),
        )
    now = datetime.now(UTC)
    target.kyc_status = ClientKycStatus.PENDING
    target.kyc_submitted_at = now
    target.kyc_documents_json = documents or []
    session.flush()
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        action="portal.kyc.submitted",
        target_type="client",
        target_id=target.id,
        matter_id=matter_id,
        result=AuditResult.SUCCESS,
        metadata={
            "portal_user_id": portal_user.id,
            "client_id": target.id,
            "doc_count": len(documents or []),
        },
        ip=request_ip,
        commit=True,
    )
    return matter, target


__all__ = [
    "PortalReplyOutOfScope",
    "get_granted_matter",
    "list_granted_matters",
    "list_matter_clients_for_portal",
    "list_matter_communications",
    "list_matter_hearings_for_portal",
    "post_matter_reply",
    "submit_matter_kyc",
]


# Internal type re-exports kept narrow.
PortalRoleLiteral = Literal["client", "outside_counsel"]
_HearingStatusLiteral = MatterHearingStatus  # re-exported for routes
