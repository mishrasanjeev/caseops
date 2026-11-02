"""Minimized self-request evidence; no deletion or fulfillment authority."""

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class AccountDeletionRequest(Base):
    __tablename__ = "account_deletion_requests"
    __table_args__ = (
        # Only received/open requests exist in this protocol. A future reviewed
        # fulfillment protocol must explicitly migrate this retained boundary.
        UniqueConstraint("subject_user_id", name="uq_account_deletion_request_subject"),
        ForeignKeyConstraint(
            ["submitted_by_membership_id", "submitted_from_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_account_deletion_request_routing_membership",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status = 'received'", name="ck_account_deletion_request_received"),
        CheckConstraint(
            "confirmation_version = 'account-deletion-v1'",
            name="ck_account_deletion_request_confirmation",
        ),
        CheckConstraint(
            "submitted_realm IN ('tenant_web', 'native')", name="ck_account_deletion_request_realm"
        ),
        Index(
            "ix_account_deletion_request_routing",
            "submitted_from_company_id",
            "submitted_by_membership_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    subject_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_from_company_id: Mapped[str] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    submitted_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confirmation_version: Mapped[str] = mapped_column(String(24), nullable=False)
    submitted_realm: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
