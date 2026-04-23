"""Clients CRUD (MOD-TS-009).

Tenant-scoped: every query filters by ``context.company.id``. Cross-
tenant IDs resolve to 404 from the caller's perspective — the same
pattern used across ``matters`` / ``contracts`` / ``outside_counsel``.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from caseops_api.db.models import (
    Client,
    ClientKycStatus,
    ClientType,
    Matter,
    MatterClientAssignment,
)
from caseops_api.schemas.clients import (
    ClientCreateRequest,
    ClientListResponse,
    ClientMatterLink,
    ClientRecord,
    ClientUpdateRequest,
    KycDocumentRecord,
    KycRejectRequest,
    KycSubmitRequest,
    MatterClientAssignmentRecord,
    MatterClientAssignRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access

_ALLOWED_TYPES = {t.value for t in ClientType}
_ALLOWED_KYC = {s.value for s in ClientKycStatus}


def _client_record(
    client: Client, *, matters: list[ClientMatterLink] | None = None,
) -> ClientRecord:
    matters = matters or []
    total = len(matters)
    active = sum(1 for m in matters if m.status == "active")
    return ClientRecord(
        id=client.id,
        company_id=client.company_id,
        name=client.name,
        client_type=client.client_type,
        primary_contact_name=client.primary_contact_name,
        primary_contact_email=client.primary_contact_email,
        primary_contact_phone=client.primary_contact_phone,
        address_line_1=client.address_line_1,
        address_line_2=client.address_line_2,
        city=client.city,
        state=client.state,
        postal_code=client.postal_code,
        country=client.country,
        pan=client.pan,
        gstin=client.gstin,
        internal_notes=client.internal_notes,
        kyc_status=client.kyc_status,
        kyc_submitted_at=client.kyc_submitted_at,
        kyc_verified_at=client.kyc_verified_at,
        kyc_verified_by_membership_id=client.kyc_verified_by_membership_id,
        kyc_rejection_reason=client.kyc_rejection_reason,
        kyc_documents=_kyc_documents(client),
        is_active=client.is_active,
        active_matters_count=active,
        total_matters_count=total,
        matters=matters,
        created_at=client.created_at,
        updated_at=client.updated_at,
    )


def _matter_links_for(session: Session, client: Client) -> list[ClientMatterLink]:
    """Expand ``client.assignments`` into user-facing matter summaries,
    joining ``Matter`` for title/code/status."""
    if not client.assignments:
        return []
    matter_ids = {a.matter_id for a in client.assignments}
    matters = session.scalars(
        select(Matter).where(Matter.id.in_(matter_ids))
    ).all()
    by_id = {m.id: m for m in matters}
    out: list[ClientMatterLink] = []
    for a in client.assignments:
        m = by_id.get(a.matter_id)
        if m is None:
            continue
        out.append(
            ClientMatterLink(
                matter_id=m.id,
                matter_code=m.matter_code,
                matter_title=m.title,
                role=a.role,
                is_primary=a.is_primary,
                status=m.status,
            )
        )
    return out


def create_client(
    session: Session, *, context: SessionContext, payload: ClientCreateRequest,
) -> ClientRecord:
    if payload.client_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown client_type {payload.client_type!r}.",
        )
    if payload.kyc_status not in _ALLOWED_KYC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown kyc_status {payload.kyc_status!r}.",
        )

    client = Client(
        company_id=context.company.id,
        name=payload.name.strip(),
        client_type=payload.client_type,
        primary_contact_name=(
            payload.primary_contact_name.strip()
            if payload.primary_contact_name else None
        ),
        primary_contact_email=payload.primary_contact_email,
        primary_contact_phone=(
            payload.primary_contact_phone.strip()
            if payload.primary_contact_phone else None
        ),
        address_line_1=(
            payload.address_line_1.strip() if payload.address_line_1 else None
        ),
        address_line_2=(
            payload.address_line_2.strip() if payload.address_line_2 else None
        ),
        city=payload.city.strip() if payload.city else None,
        state=payload.state.strip() if payload.state else None,
        postal_code=(
            payload.postal_code.strip() if payload.postal_code else None
        ),
        country=payload.country.strip() if payload.country else None,
        pan=payload.pan.strip().upper() if payload.pan else None,
        gstin=payload.gstin.strip().upper() if payload.gstin else None,
        internal_notes=payload.internal_notes,
        kyc_status=payload.kyc_status,
        created_by_membership_id=context.membership.id,
    )
    session.add(client)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A client named {payload.name!r} already exists as type "
                f"{payload.client_type!r}. Pick a different name or type."
            ),
        ) from exc
    record_from_context(
        session,
        context,
        action="client.created",
        target_type="client",
        target_id=client.id,
        metadata={
            "name": client.name,
            "client_type": client.client_type,
        },
    )
    session.commit()
    session.refresh(client)
    return _client_record(client, matters=[])


def list_clients(
    session: Session, *, context: SessionContext,
) -> ClientListResponse:
    stmt = (
        select(Client)
        .where(Client.company_id == context.company.id)
        .options(selectinload(Client.assignments))
        .order_by(Client.is_active.desc(), func.lower(Client.name))
    )
    clients = list(session.scalars(stmt))
    records = [
        _client_record(c, matters=_matter_links_for(session, c))
        for c in clients
    ]
    return ClientListResponse(clients=records, next_cursor=None)


def _get_client_model(
    session: Session, *, context: SessionContext, client_id: str,
) -> Client:
    client = session.scalar(
        select(Client)
        .where(Client.id == client_id, Client.company_id == context.company.id)
        .options(selectinload(Client.assignments))
    )
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found.",
        )
    return client


def get_client(
    session: Session, *, context: SessionContext, client_id: str,
) -> ClientRecord:
    client = _get_client_model(session, context=context, client_id=client_id)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def update_client(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
    payload: ClientUpdateRequest,
) -> ClientRecord:
    client = _get_client_model(session, context=context, client_id=client_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "client_type" in update_data and update_data["client_type"] not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown client_type {update_data['client_type']!r}.",
        )
    if "kyc_status" in update_data and update_data["kyc_status"] not in _ALLOWED_KYC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown kyc_status {update_data['kyc_status']!r}.",
        )
    for field in ("name", "primary_contact_name", "primary_contact_phone",
                  "address_line_1", "address_line_2", "postal_code",
                  "city", "state", "country", "pan", "gstin"):
        if field in update_data and update_data[field] is not None:
            value = str(update_data[field]).strip()
            if field in ("pan", "gstin"):
                value = value.upper()
            update_data[field] = value
    for key, value in update_data.items():
        setattr(client, key, value)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "That (name, client_type) pair is already in use by another "
                "client in this workspace."
            ),
        ) from exc
    record_from_context(
        session,
        context,
        action="client.updated",
        target_type="client",
        target_id=client.id,
        metadata={"fields": sorted(update_data.keys())},
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def archive_client(
    session: Session, *, context: SessionContext, client_id: str,
) -> ClientRecord:
    """Soft-delete — flip ``is_active`` to false. Keeps the rows
    linked to historical matters for audit continuity."""
    client = _get_client_model(session, context=context, client_id=client_id)
    client.is_active = False
    record_from_context(
        session,
        context,
        action="client.archived",
        target_type="client",
        target_id=client.id,
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def unarchive_client(
    session: Session, *, context: SessionContext, client_id: str,
) -> ClientRecord:
    """Reverse archive_client — flip ``is_active`` back to true.

    Phase B / BUG-025 (Hari 2026-04-23): closes "no unarchive
    functionality after archiving a client." Idempotent — calling on
    an already-active client just no-ops the audit row and returns
    the current record so the UI's optimistic refresh is safe.
    """
    client = _get_client_model(session, context=context, client_id=client_id)
    if not client.is_active:
        client.is_active = True
        record_from_context(
            session,
            context,
            action="client.unarchived",
            target_type="client",
            target_id=client.id,
        )
        session.commit()
        session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


# ---------------------------------------------------------------
# Per-matter assignment
# ---------------------------------------------------------------


def assign_client_to_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    payload: MatterClientAssignRequest,
) -> MatterClientAssignmentRecord:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    client = _get_client_model(
        session, context=context, client_id=payload.client_id,
    )

    existing = session.scalar(
        select(MatterClientAssignment).where(
            MatterClientAssignment.matter_id == matter.id,
            MatterClientAssignment.client_id == client.id,
        )
    )
    if existing is not None:
        # Idempotent: update role / is_primary if the caller re-posts.
        existing.role = payload.role
        existing.is_primary = payload.is_primary
        session.commit()
        session.refresh(existing)
        return MatterClientAssignmentRecord.model_validate(existing)

    assignment = MatterClientAssignment(
        matter_id=matter.id,
        client_id=client.id,
        role=payload.role,
        is_primary=payload.is_primary,
    )
    session.add(assignment)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.client_assigned",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"client_id": client.id, "role": payload.role},
    )
    session.commit()
    session.refresh(assignment)
    return MatterClientAssignmentRecord.model_validate(assignment)


def remove_client_from_matter(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    client_id: str,
) -> None:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.",
        )
    assert_access(session, context=context, matter=matter)
    assignment = session.scalar(
        select(MatterClientAssignment).where(
            MatterClientAssignment.matter_id == matter_id,
            MatterClientAssignment.client_id == client_id,
        )
    )
    if assignment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such client assignment on this matter.",
        )
    session.delete(assignment)
    record_from_context(
        session,
        context,
        action="matter.client_unassigned",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"client_id": client_id},
    )
    session.commit()


# ---------------------------------------------------------------
# Phase B M11 slice 3 — KYC lifecycle (US-037 / FT-049 / MOD-TS-013)
# ---------------------------------------------------------------


def _kyc_documents(client: Client) -> list[KycDocumentRecord]:
    """Hydrate the JSON column into typed records. A bad blob (older
    schema, hand-edited DB row) returns an empty list rather than
    blowing up the GET — the lawyer can re-submit to repair."""
    raw = client.kyc_documents_json or []
    out: list[KycDocumentRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            out.append(KycDocumentRecord.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out


def submit_client_kyc(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
    payload: KycSubmitRequest,
) -> ClientRecord:
    """Lawyer collects KYC documents from the client and submits the
    pack for verification. Status moves to ``pending``. Idempotent —
    a re-submission overwrites the document list and resets any prior
    rejection reason so a re-attempt looks clean."""
    from datetime import UTC
    from datetime import datetime as _dt

    client = _get_client_model(session, context=context, client_id=client_id)
    client.kyc_status = ClientKycStatus.PENDING
    client.kyc_submitted_at = _dt.now(UTC)
    client.kyc_documents_json = [d.model_dump() for d in payload.documents]
    # Clear any stale rejection / verification — this is a fresh cycle.
    client.kyc_rejection_reason = None
    client.kyc_verified_at = None
    client.kyc_verified_by_membership_id = None
    record_from_context(
        session, context,
        action="client.kyc_submitted",
        target_type="client",
        target_id=client.id,
        metadata={"document_count": len(payload.documents)},
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def verify_client_kyc(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
) -> ClientRecord:
    """Staff reviewer approves a submitted KYC pack. Refuses to verify
    a client that hasn't been submitted (must go via /submit first)
    so the audit trail can never claim a verification with no
    documents on file."""
    from datetime import UTC
    from datetime import datetime as _dt

    client = _get_client_model(session, context=context, client_id=client_id)
    if client.kyc_status not in (
        ClientKycStatus.PENDING.value, ClientKycStatus.REJECTED.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC cannot be verified from status {client.kyc_status!r}. "
                "Submit a KYC pack first."
            ),
        )
    client.kyc_status = ClientKycStatus.VERIFIED
    client.kyc_verified_at = _dt.now(UTC)
    client.kyc_verified_by_membership_id = context.membership.id
    client.kyc_rejection_reason = None
    record_from_context(
        session, context,
        action="client.kyc_verified",
        target_type="client",
        target_id=client.id,
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def reject_client_kyc(
    session: Session,
    *,
    context: SessionContext,
    client_id: str,
    payload: KycRejectRequest,
) -> ClientRecord:
    """Staff reviewer rejects a submitted KYC pack with a reason. The
    reason MUST be present (schema enforces min_length=4) so the
    lawyer who has to re-collect docs knows what to fix."""
    client = _get_client_model(session, context=context, client_id=client_id)
    if client.kyc_status != ClientKycStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC cannot be rejected from status {client.kyc_status!r}. "
                "Only a pending submission can be rejected."
            ),
        )
    client.kyc_status = ClientKycStatus.REJECTED
    client.kyc_rejection_reason = payload.reason
    client.kyc_verified_at = None
    client.kyc_verified_by_membership_id = None
    record_from_context(
        session, context,
        action="client.kyc_rejected",
        target_type="client",
        target_id=client.id,
        metadata={"reason": payload.reason[:200]},
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )
