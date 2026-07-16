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
    MatterAttachment,
    MatterClientAssignment,
)
from caseops_api.schemas.clients import (
    ClientCreateRequest,
    ClientListResponse,
    ClientMatterLink,
    ClientRecord,
    ClientUpdateRequest,
    ClientVerificationUpdateRequest,
    KycDocumentRecord,
    KycRejectRequest,
    KycSubmitRequest,
    MatterClientAssignmentRecord,
    MatterClientAssignRequest,
    MatterClientVerificationListResponse,
    MatterClientVerificationRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.session_context import SessionContext

_ALLOWED_TYPES = {t.value for t in ClientType}
_ALLOWED_KYC = {s.value for s in ClientKycStatus}
_ADP10_STATUS_ALIASES = {
    "not_started": ClientKycStatus.NOT_REQUIRED.value,
    "pending": ClientKycStatus.SUBMITTED.value,
}
_ALLOWED_VERIFICATION_TRANSITIONS = {
    ClientKycStatus.NOT_REQUIRED.value: {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.REQUIRED.value: {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.REQUESTED.value: {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.UNDER_REVIEW.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.SUBMITTED.value: {
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.UNDER_REVIEW.value,
        ClientKycStatus.VERIFIED.value,
        ClientKycStatus.REJECTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.UNDER_REVIEW.value: {
        ClientKycStatus.UNDER_REVIEW.value,
        ClientKycStatus.VERIFIED.value,
        ClientKycStatus.REJECTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.VERIFIED.value: {
        ClientKycStatus.VERIFIED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.REJECTED.value: {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.UNDER_REVIEW.value,
        ClientKycStatus.REJECTED.value,
        ClientKycStatus.EXPIRED.value,
    },
    ClientKycStatus.EXPIRED.value: {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.SUBMITTED.value,
        ClientKycStatus.EXPIRED.value,
    },
}


def _normalize_kyc_status(value: str | ClientKycStatus | None) -> str:
    raw = str(value or ClientKycStatus.NOT_REQUIRED.value)
    return _ADP10_STATUS_ALIASES.get(raw, raw)


def _ensure_verification_transition(current: str, new_status: str) -> None:
    current = _normalize_kyc_status(current)
    new_status = _normalize_kyc_status(new_status)
    allowed = _ALLOWED_VERIFICATION_TRANSITIONS.get(current, {current})
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Client verification cannot move from {current!r} "
                f"to {new_status!r}."
            ),
        )


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
        kyc_status=_normalize_kyc_status(client.kyc_status),
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
    normalized_kyc = _normalize_kyc_status(payload.kyc_status)
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
        kyc_status=normalized_kyc,
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
    if "kyc_status" in update_data:
        if update_data["kyc_status"] not in _ALLOWED_KYC:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown kyc_status {update_data['kyc_status']!r}.",
            )
        update_data["kyc_status"] = _normalize_kyc_status(update_data["kyc_status"])
        _ensure_verification_transition(client.kyc_status, update_data["kyc_status"])
        if update_data["kyc_status"] in {
            ClientKycStatus.UNDER_REVIEW.value,
            ClientKycStatus.VERIFIED.value,
            ClientKycStatus.REJECTED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Use the verification workflow endpoint for review "
                    "status changes."
                ),
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
    if "kyc_status" in update_data:
        _apply_verification_status_side_effects(
            client, context=context, new_status=update_data["kyc_status"],
        )
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
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="assign a client to a matter",
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
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="remove a client from a matter",
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


def _document_payloads(
    documents: list[KycDocumentRecord],
    *,
    submitted: bool = False,
) -> list[dict]:
    payloads: list[dict] = []
    for doc in documents:
        item = doc.model_dump(mode="json")
        if submitted and item.get("status") in {"required", "requested", "pending"}:
            item["status"] = ClientKycStatus.SUBMITTED.value
        payloads.append(item)
    return payloads


def _document_audit_metadata(documents: list[KycDocumentRecord]) -> dict:
    attachment_count = sum(1 for d in documents if d.attachment_id)
    return {
        "document_count": len(documents),
        "attachment_reference_count": attachment_count,
        "document_type_count": sum(1 for d in documents if d.document_type),
    }


def _reject_direct_attachment_refs(documents: list[KycDocumentRecord]) -> None:
    if any(d.attachment_id for d in documents):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Verification attachment references must be submitted through "
                "the matter-scoped verification endpoint."
            ),
        )


def _validate_matter_attachment_refs(
    session: Session,
    *,
    matter: Matter,
    documents: list[KycDocumentRecord],
) -> None:
    attachment_ids = sorted({d.attachment_id for d in documents if d.attachment_id})
    if not attachment_ids:
        return
    found = set(
        session.scalars(
            select(MatterAttachment.id).where(
                MatterAttachment.id.in_(attachment_ids),
                MatterAttachment.matter_id == matter.id,
            )
        )
    )
    missing = set(attachment_ids) - found
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more verification document references are invalid.",
        )


def _apply_verification_status_side_effects(
    client: Client,
    *,
    context: SessionContext,
    new_status: str,
    rejection_reason: str | None = None,
) -> None:
    from datetime import UTC
    from datetime import datetime as _dt

    normalized = _normalize_kyc_status(new_status)
    client.kyc_status = normalized
    if normalized == ClientKycStatus.SUBMITTED.value:
        client.kyc_submitted_at = _dt.now(UTC)
        client.kyc_verified_at = None
        client.kyc_verified_by_membership_id = None
        client.kyc_rejection_reason = None
    elif normalized == ClientKycStatus.UNDER_REVIEW.value:
        if client.kyc_submitted_at is None:
            client.kyc_submitted_at = _dt.now(UTC)
        client.kyc_verified_at = None
        client.kyc_verified_by_membership_id = None
    elif normalized == ClientKycStatus.VERIFIED.value:
        client.kyc_verified_at = _dt.now(UTC)
        client.kyc_verified_by_membership_id = context.membership.id
        client.kyc_rejection_reason = None
    elif normalized == ClientKycStatus.REJECTED.value:
        client.kyc_verified_at = _dt.now(UTC)
        client.kyc_verified_by_membership_id = context.membership.id
        client.kyc_rejection_reason = (rejection_reason or "").strip()
    elif normalized in {
        ClientKycStatus.NOT_REQUIRED.value,
        ClientKycStatus.REQUIRED.value,
        ClientKycStatus.REQUESTED.value,
        ClientKycStatus.EXPIRED.value,
    }:
        client.kyc_verified_at = None
        client.kyc_verified_by_membership_id = None
        if normalized != ClientKycStatus.REJECTED.value:
            client.kyc_rejection_reason = None


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
    _ensure_verification_transition(client.kyc_status, ClientKycStatus.SUBMITTED.value)
    _reject_direct_attachment_refs(payload.documents)
    client.kyc_status = ClientKycStatus.SUBMITTED.value
    client.kyc_submitted_at = _dt.now(UTC)
    client.kyc_documents_json = _document_payloads(
        payload.documents, submitted=True,
    )
    # Clear any stale rejection / verification — this is a fresh cycle.
    client.kyc_rejection_reason = None
    client.kyc_verified_at = None
    client.kyc_verified_by_membership_id = None
    record_from_context(
        session, context,
        action="client.kyc_submitted",
        target_type="client",
        target_id=client.id,
        metadata={
            "status": ClientKycStatus.SUBMITTED.value,
            **_document_audit_metadata(payload.documents),
        },
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
    current_status = _normalize_kyc_status(client.kyc_status)
    if current_status not in (
        ClientKycStatus.SUBMITTED.value, ClientKycStatus.UNDER_REVIEW.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC cannot be verified from status {current_status!r}. "
                "Submit a KYC pack first."
            ),
        )
    client.kyc_status = ClientKycStatus.VERIFIED.value
    client.kyc_verified_at = _dt.now(UTC)
    client.kyc_verified_by_membership_id = context.membership.id
    client.kyc_rejection_reason = None
    record_from_context(
        session, context,
        action="client.kyc_verified",
        target_type="client",
        target_id=client.id,
        metadata={
            "status": ClientKycStatus.VERIFIED.value,
            "document_count": len(_kyc_documents(client)),
        },
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
    current_status = _normalize_kyc_status(client.kyc_status)
    if current_status not in (
        ClientKycStatus.SUBMITTED.value, ClientKycStatus.UNDER_REVIEW.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"KYC cannot be rejected from status {current_status!r}. "
                "Only a submitted or under-review pack can be rejected."
            ),
        )
    client.kyc_status = ClientKycStatus.REJECTED.value
    client.kyc_rejection_reason = payload.reason
    from datetime import UTC
    from datetime import datetime as _dt

    client.kyc_verified_at = _dt.now(UTC)
    client.kyc_verified_by_membership_id = context.membership.id
    record_from_context(
        session, context,
        action="client.kyc_rejected",
        target_type="client",
        target_id=client.id,
        metadata={
            "status": ClientKycStatus.REJECTED.value,
            "document_count": len(_kyc_documents(client)),
            "reason_present": True,
            "reason_length": len(payload.reason.strip()),
        },
    )
    session.commit()
    session.refresh(client)
    return _client_record(
        client, matters=_matter_links_for(session, client),
    )


def _matter_client_verification_record(
    assignment: MatterClientAssignment,
    client: Client,
) -> MatterClientVerificationRecord:
    return MatterClientVerificationRecord(
        client_id=client.id,
        client_name=client.name,
        client_type=client.client_type,
        role=assignment.role,
        is_primary=assignment.is_primary,
        status=_normalize_kyc_status(client.kyc_status),
        submitted_at=client.kyc_submitted_at,
        reviewed_at=client.kyc_verified_at,
        reviewer_membership_id=client.kyc_verified_by_membership_id,
        rejection_reason=client.kyc_rejection_reason,
        documents=_kyc_documents(client),
    )


def _load_matter_for_client_verification(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> Matter:
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
    return matter


def _load_matter_client_assignment(
    session: Session,
    *,
    matter: Matter,
    client_id: str,
) -> tuple[MatterClientAssignment, Client]:
    row = session.execute(
        select(MatterClientAssignment, Client)
        .join(Client, Client.id == MatterClientAssignment.client_id)
        .where(
            MatterClientAssignment.matter_id == matter.id,
            MatterClientAssignment.client_id == client_id,
            Client.company_id == matter.company_id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found for this matter.",
        )
    assignment, client = row
    return assignment, client


def list_matter_client_verifications(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> MatterClientVerificationListResponse:
    matter = _load_matter_for_client_verification(
        session, context=context, matter_id=matter_id,
    )
    rows = session.execute(
        select(MatterClientAssignment, Client)
        .join(Client, Client.id == MatterClientAssignment.client_id)
        .where(
            MatterClientAssignment.matter_id == matter.id,
            Client.company_id == context.company.id,
        )
        .order_by(MatterClientAssignment.is_primary.desc(), Client.name.asc())
    ).all()
    return MatterClientVerificationListResponse(
        matter_id=matter.id,
        clients=[
            _matter_client_verification_record(assignment, client)
            for assignment, client in rows
        ],
    )


def update_matter_client_verification(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    client_id: str,
    payload: ClientVerificationUpdateRequest,
) -> MatterClientVerificationRecord:
    matter = _load_matter_for_client_verification(
        session, context=context, matter_id=matter_id,
    )
    assignment, client = _load_matter_client_assignment(
        session, matter=matter, client_id=client_id,
    )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="update matter client verification",
    )
    documents = payload.documents
    if documents is not None:
        _validate_matter_attachment_refs(session, matter=matter, documents=documents)
        client.kyc_documents_json = _document_payloads(documents)

    previous_status = _normalize_kyc_status(client.kyc_status)
    new_status = (
        _normalize_kyc_status(payload.status)
        if payload.status is not None
        else previous_status
    )
    if payload.status is not None:
        if payload.status not in _ALLOWED_KYC:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown verification status {payload.status!r}.",
            )
        _ensure_verification_transition(client.kyc_status, new_status)
        if new_status == ClientKycStatus.REJECTED.value and not (
            payload.rejection_reason and payload.rejection_reason.strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="A rejection reason is required when rejecting verification.",
            )
        _apply_verification_status_side_effects(
            client,
            context=context,
            new_status=new_status,
            rejection_reason=payload.rejection_reason,
        )

    audit_documents = documents if documents is not None else _kyc_documents(client)
    record_from_context(
        session,
        context,
        action="client.verification_updated",
        target_type="client",
        target_id=client.id,
        matter_id=matter.id,
        metadata={
            "status": _normalize_kyc_status(client.kyc_status),
            "previous_status": previous_status,
            "reason_present": bool(payload.rejection_reason),
            "reason_length": len(payload.rejection_reason.strip())
            if payload.rejection_reason else 0,
            **_document_audit_metadata(audit_documents),
        },
    )
    session.commit()
    session.refresh(client)
    return _matter_client_verification_record(assignment, client)
