"""Phase C-3 (2026-04-24, MOD-TS-016) — outside-counsel portal service.

Sister to ``portal_matters`` (the C-2 client portal). This module
serves the OC half of the portal:

- list assigned matters (grant role='outside_counsel')
- view a single assigned matter
- upload work product (virus-scanned, OC-isolated)
- list work product (cross-counsel-isolated by default)
- submit invoice (lands status='needs_review', never auto-approved)
- list invoices (cross-counsel-isolated by default)
- submit time entry (firm reviews, attaches to invoice line items
  later; never auto-billed)
- list time entries (cross-counsel-isolated by default)

Why a separate service from ``portal_matters``: keeping the two
role surfaces in different modules makes the role gate explicit at
the import site. ``services/portal_matters._assert_grant`` accepts a
``role`` param but the C-2 routes only ever pass ``role='client'``;
this module always passes ``role='outside_counsel'`` so the wrong
caller cannot accidentally reach the wrong service.

Cross-counsel isolation: every list endpoint here applies
``_apply_oc_visibility_filter`` which restricts the query to rows
submitted by the calling portal user UNLESS
``Matter.oc_cross_visibility_enabled`` is True. Internal users (firm
side) reach these tables through the existing matters/billing
services and are unaffected.

Invoices land in ``InvoiceStatus.NEEDS_REVIEW`` — a new value on the
StrEnum that a firm-side reviewer must explicitly transition to
ISSUED before any payment side-effects fire.
"""
from __future__ import annotations

from datetime import date as date_cls
from typing import BinaryIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditActorType,
    AuditResult,
    InvoiceStatus,
    Matter,
    MatterAttachment,
    MatterInvoice,
    MatterInvoiceLineItem,
    MatterPortalGrant,
    MatterTimeEntry,
    PortalUser,
)
from caseops_api.services.audit import record_audit
from caseops_api.services.document_storage import (
    persist_matter_attachment,
    resolve_storage_path,
    sanitize_filename,
)
from caseops_api.services.file_security import verify_upload
from caseops_api.services.virus_scan import reject_if_infected


def _assert_oc_grant(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> tuple[Matter, MatterPortalGrant]:
    """Strict outside-counsel grant assertion. Same 404-on-miss shape
    as the client gate so a probe cannot distinguish a missing matter
    from a wrong-role grant from a foreign-tenant matter."""
    grant = session.scalars(
        select(MatterPortalGrant).where(
            MatterPortalGrant.portal_user_id == portal_user.id,
            MatterPortalGrant.matter_id == matter_id,
            MatterPortalGrant.role == "outside_counsel",
            MatterPortalGrant.revoked_at.is_(None),
        )
    ).first()
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    matter = session.get(Matter, matter_id)
    if matter is None or matter.company_id != portal_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )
    return matter, grant


def list_oc_assigned_matters(
    session: Session, *, portal_user: PortalUser
) -> list[tuple[MatterPortalGrant, Matter]]:
    rows = session.execute(
        select(MatterPortalGrant, Matter)
        .join(Matter, Matter.id == MatterPortalGrant.matter_id)
        .where(
            MatterPortalGrant.portal_user_id == portal_user.id,
            MatterPortalGrant.role == "outside_counsel",
            MatterPortalGrant.revoked_at.is_(None),
            Matter.company_id == portal_user.company_id,
        )
        .order_by(MatterPortalGrant.granted_at.desc())
    ).all()
    return [(g, m) for g, m in rows]


def get_oc_assigned_matter(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> Matter:
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    return matter


# ---------- work product (file upload) ----------


def upload_oc_work_product(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    filename: str,
    content_type: str | None,
    stream: BinaryIO,
    request_ip: str | None = None,
) -> MatterAttachment:
    """Persist an OC upload as a MatterAttachment with
    submitted_by_portal_user_id set. Same magic-byte + virus-scan
    pipeline as the internal upload path. Quarantines the file on
    infection.
    """
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    verify_upload(filename=filename, content_type=content_type, stream=stream)

    attachment = MatterAttachment(
        matter_id=matter.id,
        uploaded_by_membership_id=None,
        submitted_by_portal_user_id=portal_user.id,
        original_filename=sanitize_filename(filename),
        storage_key="pending",
        content_type=content_type,
        size_bytes=0,
        sha256_hex="0" * 64,
    )
    session.add(attachment)
    session.flush()

    try:
        stored = persist_matter_attachment(
            company_id=portal_user.company_id,
            matter_id=matter.id,
            attachment_id=attachment.id,
            filename=filename,
            stream=stream,
        )
        try:
            reject_if_infected(
                resolve_storage_path(stored.storage_key),
                filename=filename,
            )
        except Exception:
            try:
                resolve_storage_path(stored.storage_key).unlink(missing_ok=True)
            except Exception:
                pass
            raise
        attachment.storage_key = stored.storage_key
        attachment.size_bytes = stored.size_bytes
        attachment.sha256_hex = stored.sha256_hex
        session.add(attachment)
        session.commit()
        record_audit(
            session,
            company_id=portal_user.company_id,
            actor_type=AuditActorType.SYSTEM,
            actor_label=f"portal:{portal_user.email}",
            target_type="matter_attachment",
            target_id=attachment.id,
            matter_id=matter.id,
            action="portal_oc.upload_work_product",
            result=AuditResult.SUCCESS,
            metadata={
                "portal_user_id": portal_user.id,
                "filename": attachment.original_filename,
            },
            ip=request_ip,
            commit=True,
        )
    except Exception:
        session.rollback()
        raise

    return attachment


def list_oc_work_product(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[MatterAttachment]:
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    stmt = (
        select(MatterAttachment)
        .where(
            MatterAttachment.matter_id == matter.id,
            MatterAttachment.submitted_by_portal_user_id.is_not(None),
        )
        .order_by(MatterAttachment.created_at.desc())
    )
    if not matter.oc_cross_visibility_enabled:
        # Cross-counsel iso: only THIS portal user's uploads.
        stmt = stmt.where(
            MatterAttachment.submitted_by_portal_user_id == portal_user.id
        )
    return list(session.scalars(stmt).all())


# ---------- invoices ----------


def submit_oc_invoice(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    invoice_number: str,
    issued_on: date_cls,
    due_on: date_cls | None,
    currency: str,
    line_items: list[dict],
    notes: str | None = None,
    request_ip: str | None = None,
) -> MatterInvoice:
    """Create a MatterInvoice + line items submitted by the OC.
    Lands in `status=NEEDS_REVIEW` so a firm-side user must approve
    before any billing side-effects (Pine Labs link, dispatch) fire.
    """
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    if not invoice_number.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="invoice_number is required.",
        )
    if not line_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one line item is required.",
        )
    subtotal = 0
    for li in line_items:
        amount = int(li.get("amount_minor") or 0)
        if amount < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Line-item amount must be non-negative.",
            )
        subtotal += amount

    invoice = MatterInvoice(
        company_id=portal_user.company_id,
        matter_id=matter.id,
        issued_by_membership_id=None,
        submitted_by_portal_user_id=portal_user.id,
        invoice_number=invoice_number.strip(),
        client_name=None,
        status=InvoiceStatus.NEEDS_REVIEW,
        currency=currency.strip().upper() or "INR",
        subtotal_amount_minor=subtotal,
        tax_amount_minor=0,
        total_amount_minor=subtotal,
        amount_received_minor=0,
        balance_due_minor=subtotal,
        issued_on=issued_on,
        due_on=due_on,
        notes=notes,
    )
    session.add(invoice)
    session.flush()
    for li in line_items:
        amount = int(li.get("amount_minor") or 0)
        item = MatterInvoiceLineItem(
            invoice_id=invoice.id,
            description=str(li.get("description") or "").strip()[:500],
            duration_minutes=None,
            unit_rate_amount_minor=amount,
            line_total_amount_minor=amount,
        )
        session.add(item)
    session.commit()
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        target_type="matter_invoice",
        target_id=invoice.id,
        matter_id=matter.id,
        action="portal_oc.submit_invoice",
        result=AuditResult.SUCCESS,
        metadata={
            "portal_user_id": portal_user.id,
            "invoice_number": invoice.invoice_number,
            "subtotal_amount_minor": subtotal,
        },
        ip=request_ip,
        commit=True,
    )
    return invoice


def list_oc_invoices(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[MatterInvoice]:
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    stmt = (
        select(MatterInvoice)
        .where(
            MatterInvoice.matter_id == matter.id,
            MatterInvoice.submitted_by_portal_user_id.is_not(None),
        )
        .order_by(MatterInvoice.created_at.desc())
    )
    if not matter.oc_cross_visibility_enabled:
        stmt = stmt.where(
            MatterInvoice.submitted_by_portal_user_id == portal_user.id
        )
    return list(session.scalars(stmt).all())


# ---------- time entries ----------


def submit_oc_time_entry(
    session: Session,
    *,
    portal_user: PortalUser,
    matter_id: str,
    work_date: date_cls,
    description: str,
    duration_minutes: int,
    billable: bool,
    rate_currency: str,
    rate_amount_minor: int | None,
    request_ip: str | None = None,
) -> MatterTimeEntry:
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    if duration_minutes <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="duration_minutes must be positive.",
        )
    if not description.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="description is required.",
        )
    total = (rate_amount_minor or 0) * duration_minutes // 60
    entry = MatterTimeEntry(
        matter_id=matter.id,
        author_membership_id=None,
        submitted_by_portal_user_id=portal_user.id,
        work_date=work_date,
        description=description.strip()[:500],
        duration_minutes=duration_minutes,
        billable=billable,
        rate_currency=rate_currency.strip().upper() or "INR",
        rate_amount_minor=rate_amount_minor,
        total_amount_minor=total,
    )
    session.add(entry)
    session.commit()
    record_audit(
        session,
        company_id=portal_user.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label=f"portal:{portal_user.email}",
        target_type="matter_time_entry",
        target_id=entry.id,
        matter_id=matter.id,
        action="portal_oc.submit_time_entry",
        result=AuditResult.SUCCESS,
        metadata={
            "portal_user_id": portal_user.id,
            "duration_minutes": duration_minutes,
        },
        ip=request_ip,
        commit=True,
    )
    return entry


def list_oc_time_entries(
    session: Session, *, portal_user: PortalUser, matter_id: str
) -> list[MatterTimeEntry]:
    matter, _grant = _assert_oc_grant(
        session, portal_user=portal_user, matter_id=matter_id,
    )
    stmt = (
        select(MatterTimeEntry)
        .where(
            MatterTimeEntry.matter_id == matter.id,
            MatterTimeEntry.submitted_by_portal_user_id.is_not(None),
        )
        .order_by(MatterTimeEntry.work_date.desc(), MatterTimeEntry.created_at.desc())
    )
    if not matter.oc_cross_visibility_enabled:
        stmt = stmt.where(
            MatterTimeEntry.submitted_by_portal_user_id == portal_user.id
        )
    return list(session.scalars(stmt).all())


__all__ = [
    "get_oc_assigned_matter",
    "list_oc_assigned_matters",
    "list_oc_invoices",
    "list_oc_time_entries",
    "list_oc_work_product",
    "submit_oc_invoice",
    "submit_oc_time_entry",
    "upload_oc_work_product",
]
