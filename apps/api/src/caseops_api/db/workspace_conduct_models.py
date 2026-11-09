"""Retained workspace conduct acceptance and report receipts."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
)
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


class WorkspaceConductReport(Base):
    __tablename__ = "workspace_conduct_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "reporter_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_reporter",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "target_membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_workspace_conduct_report_target",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "reporter_membership_id", "operation_id",
            name="uq_workspace_conduct_report_operation",
        ),
        CheckConstraint(
            "(target_kind IN ('note', 'file') AND target_kind = source_kind) OR "
            "(target_kind = 'user' AND target_membership_id IS NOT NULL "
            "AND source_kind IN ('note', 'file'))",
            name="ck_workspace_conduct_report_target",
        ),
        CheckConstraint(
            "routing IN ('workspace', 'publisher')",
            name="ck_workspace_conduct_report_routing",
        ),
        CheckConstraint(
            "reason IN ('harassment_threats', 'exploitation', 'impersonation', "
            "'unlawful_content', 'spam_malware_fraud', 'unauthorized_disclosure', 'other')",
            name="ck_workspace_conduct_report_reason",
        ),
        Index("ix_workspace_conduct_report_target", "company_id", "target_membership_id"),
        Index(
            "ix_workspace_conduct_report_workspace", "company_id", "routing", "received_at", "id",
        ),
        Index("ix_workspace_conduct_report_publisher", "routing", "received_at", "id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reporter_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    operation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    target_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source_matter_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_item_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    routing: Mapped[str] = mapped_column(String(9), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
