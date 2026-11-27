"""Uploaded KYC documents of a client (BUG-003, Nov 27 2026 workbook).

A KYC document is an identity or address proof file that belongs to one client
of one company. Its bytes live in the shared document store under the
``client-kyc`` namespace (``services/document_storage.py``); this row holds the
storage key, the typed document kind and the review evidence. KYC files are
never embedded, indexed or sent to an AI provider (PRD SEC-016): nothing in the
retrieval, OCR or translation pipelines reads this table.

A document that a reviewer has approved or rejected is evidence for that
decision. Removing it from the client's current pack retires the row
(``retired_at``) and keeps the bytes; a document nobody has reviewed yet is
deleted outright.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class KycDocumentType(StrEnum):
    PAN = "pan"
    # UIDAI permits keeping only a masked Aadhaar (first eight digits hidden).
    AADHAAR_MASKED = "aadhaar_masked"
    PASSPORT = "passport"
    ADDRESS_PROOF = "address_proof"
    OTHER = "other"


class KycDocumentReviewDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


_TYPE_SQL = "document_type IN ('pan', 'aadhaar_masked', 'passport', 'address_proof', 'other')"


class ClientKycDocument(Base):
    __tablename__ = "client_kyc_documents"
    __table_args__ = (
        # The client must belong to the same company as the row.
        ForeignKeyConstraint(
            ["client_id", "company_id"],
            ["clients.id", "clients.company_id"],
            ondelete="CASCADE",
            name="fk_client_kyc_documents_client_company",
        ),
        UniqueConstraint("storage_key", name="uq_client_kyc_documents_storage_key"),
        CheckConstraint(_TYPE_SQL, name="ck_client_kyc_documents_type"),
        CheckConstraint(
            "document_type <> 'other' OR label IS NOT NULL",
            name="ck_client_kyc_documents_other_label",
        ),
        CheckConstraint(
            "review_decision IS NULL OR review_decision IN ('approved', 'rejected')",
            name="ck_client_kyc_documents_review_decision",
        ),
        CheckConstraint("size_bytes > 0", name="ck_client_kyc_documents_size"),
        Index("ix_client_kyc_documents_client_company", "client_id", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    client_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Required for ``other``; never an identity number (see services/aadhaar_privacy.py).
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_hex: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    uploaded_by_portal_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    review_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_membership_id: Mapped[str | None] = mapped_column(
        ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False,
    )


__all__ = [
    "ClientKycDocument",
    "KycDocumentReviewDecision",
    "KycDocumentType",
]
