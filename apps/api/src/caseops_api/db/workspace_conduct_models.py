"""Retained workspace conduct acceptance receipts."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKeyConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class WorkspaceConductAcceptance(Base):
    __tablename__ = "workspace_conduct_acceptances"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_acceptance_membership",
            ondelete="RESTRICT",
        ),
    )

    company_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[str] = mapped_column(String(10), primary_key=True)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
