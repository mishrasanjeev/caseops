"""ENH-001: verification tokens behind the QR code on every issued billing PDF.

Each generated PDF gets its own unguessable token (32 random bytes). The QR
code and the printed link carry the token; the database keeps only its
SHA-256, so a database read cannot be turned back into working links. After
the PDF is drawn, the SHA-256 of the exact served bytes is recorded, so a
verifier can tell an altered copy from the original.

The public lookup returns minimal facts (document type and number, issue date,
issuing firm, amount, status, fingerprint). It never returns the client, the
matter or a tenant identifier, an unknown and a malformed token get the same
404, and tokens are revoked when the document is voided.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    BillingDocumentVerification,
    BillingManualInvoice,
    InvoiceStatus,
    MatterInvoice,
    utcnow,
)
from caseops_api.schemas.document_branding import (
    BillingDocumentVerificationResponse,
    VerificationState,
)

TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
SOURCE_MATTER_INVOICE = "matter_invoice"
SOURCE_SAAS_INVOICE = "billing_manual_invoice"
OUTSIDE_COUNSEL_DOCUMENT_KIND = "outside_counsel_invoice"

# The one definition of an issued billing document, for matter invoices and
# CaseOps's own invoices alike (both use these status strings). A draft, or an
# outside-counsel submission the firm has not approved, is not issued: its PDF
# carries a status watermark and no signature, and its verification link must
# not call it genuine. Void documents are revoked, not "not issued".
ISSUED_DOCUMENT_STATUSES = frozenset(
    {InvoiceStatus.ISSUED, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID}
)


def is_issued_status(value: str | None) -> bool:
    return value is not None and str(value) in ISSUED_DOCUMENT_STATUSES

DOCUMENT_TYPE_LABELS = {
    "matter_invoice": "Invoice",
    "matter_tax_invoice": "Tax invoice",
    "matter_invoice_receipt": "Invoice and payment receipt",
    "outside_counsel_invoice": "Outside counsel invoice",
    "saas_invoice": "CaseOps subscription invoice",
}
STATUS_LABELS = {
    "draft": "Draft (not issued)",
    "needs_review": "Submitted for review (not approved)",
    "issued": "Issued",
    "partially_paid": "Partially paid",
    "paid": "Paid",
    "void": "Void (cancelled)",
}


@dataclass(frozen=True, slots=True)
class IssuedVerification:
    row: BillingDocumentVerification
    token: str
    url: str


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def verification_url(token: str) -> str:
    return f"{str(get_settings().public_app_url).rstrip('/')}/verify/{token}"


def issue_verification(
    session: Session,
    *,
    company_id: str,
    document_kind: str,
    source_type: str,
    source_id: str,
    matter_id: str | None,
    document_number: str,
    issued_on: date,
    issuer_name: str,
    amount_minor: int,
    currency: str,
    document_status: str,
    generated_by_membership_id: str | None,
) -> IssuedVerification:
    """Stage a verification row for a PDF about to be drawn.

    A void document is staged already revoked: its QR code still resolves, and
    says the document was cancelled.
    """

    token = secrets.token_urlsafe(32)
    row = BillingDocumentVerification(
        company_id=company_id,
        matter_id=matter_id,
        document_kind=document_kind,
        source_type=source_type,
        source_id=source_id,
        document_number=document_number[:80],
        document_issued_on=issued_on,
        issuer_name=issuer_name[:255],
        amount_minor=amount_minor,
        currency=currency,
        status_at_generation=document_status,
        token_hash=token_hash(token),
        generated_by_membership_id=generated_by_membership_id,
    )
    if document_status == "void":
        row.revoked_at = utcnow()
        row.revoked_reason = "The document was voided."
    session.add(row)
    session.flush()
    return IssuedVerification(row=row, token=token, url=verification_url(token))


def record_pdf_fingerprint(issued: IssuedVerification, sha256: str) -> None:
    issued.row.pdf_sha256 = sha256


def revoke_verifications(
    session: Session,
    *,
    company_id: str,
    source_type: str,
    source_id: str,
    reason: str,
) -> int:
    """Revoke every live token for one source document (same transaction)."""

    result = session.execute(
        update(BillingDocumentVerification)
        .where(
            BillingDocumentVerification.company_id == company_id,
            BillingDocumentVerification.source_type == source_type,
            BillingDocumentVerification.source_id == source_id,
            BillingDocumentVerification.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow(), revoked_reason=reason[:255])
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


def _current_status(session: Session, row: BillingDocumentVerification) -> str | None:
    if row.source_type == SOURCE_MATTER_INVOICE:
        return session.scalar(
            select(MatterInvoice.status).where(
                MatterInvoice.id == row.source_id,
                MatterInvoice.company_id == row.company_id,
            )
        )
    if row.source_type == SOURCE_SAAS_INVOICE:
        return session.scalar(
            select(BillingManualInvoice.status).where(
                BillingManualInvoice.id == row.source_id,
                BillingManualInvoice.company_id == row.company_id,
            )
        )
    return None


_NOT_FOUND = "This verification link is not valid."


def verify_billing_document(session: Session, *, token: str) -> BillingDocumentVerificationResponse:
    if not TOKEN_PATTERN.fullmatch(token or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    row = session.scalar(
        select(BillingDocumentVerification).where(
            BillingDocumentVerification.token_hash == token_hash(token)
        )
    )
    if row is None or row.pdf_sha256 is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND)
    current = _current_status(session, row)
    revoked_at = row.revoked_at
    revoked_reason = row.revoked_reason
    if current is None and revoked_at is None:
        # The source record is gone: the copy can no longer be vouched for.
        revoked_at = row.generated_at
        revoked_reason = "The document is no longer held by the issuer."
    if current == "void" and revoked_at is None:
        revoked_at = row.generated_at
        revoked_reason = "The document was voided."
    current_status = current or "unavailable"
    state: VerificationState
    if revoked_at is not None:
        state = "revoked"
    elif is_issued_status(row.status_at_generation) and is_issued_status(current):
        state = "valid"
    else:
        # A draft or review copy stays "not issued" even after the document is
        # issued: the copy in hand is still the unsigned, watermarked one.
        state = "not_issued"
    return BillingDocumentVerificationResponse(
        state=state,
        document_type=DOCUMENT_TYPE_LABELS.get(row.document_kind, "Billing document"),
        document_number=row.document_number,
        issued_on=row.document_issued_on,
        issuer_name=row.issuer_name,
        issuer_supplied_by_counsel=row.document_kind == OUTSIDE_COUNSEL_DOCUMENT_KIND,
        amount_minor=row.amount_minor,
        currency=row.currency,
        status_at_generation=STATUS_LABELS.get(row.status_at_generation, row.status_at_generation),
        current_status=STATUS_LABELS.get(current_status, "No longer available"),
        generated_at=row.generated_at,
        pdf_sha256=row.pdf_sha256,
        revoked_at=revoked_at,
        revoked_reason=revoked_reason,
    )
