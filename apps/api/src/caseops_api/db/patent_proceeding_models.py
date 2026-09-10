"""Typed patent detail on the canonical proceeding; sealed source snapshots."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class IpPatentProceedingDetail(Base):
    __tablename__ = "ip_patent_proceeding_details"
    __table_args__ = (
        ForeignKeyConstraint(
            ["id", "company_id", "docket_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id", "ip_proceedings.docket_id"],
            name="fk_patent_proceeding_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["ip_patent_applications.id", "ip_patent_applications.company_id"],
            name="fk_patent_proceeding_application",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("id", "company_id", "application_id", name="uq_patent_proceeding_owner"),
        CheckConstraint("lifecycle_version >= 0", name="ck_patent_proceeding_lifecycle"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    docket_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(255), nullable=False)
    lifecycle_version: Mapped[int] = mapped_column(Integer, nullable=False)


class IpPatentProceedingEvent(Base):
    __tablename__ = "ip_patent_proceeding_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["proceeding_id", "company_id", "application_id"],
            [
                "ip_patent_proceeding_details.id",
                "ip_patent_proceeding_details.company_id",
                "ip_patent_proceeding_details.application_id",
            ],
            name="fk_patent_opposition_proceeding",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["ip_patent_applications.id", "ip_patent_applications.company_id"],
            name="fk_patent_opposition_application",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["anchor_version_id", "company_id", "application_id"],
            [
                "ip_patent_application_versions.id",
                "ip_patent_application_versions.company_id",
                "ip_patent_application_versions.application_id",
            ],
            name="fk_patent_opposition_anchor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            name="fk_patent_opposition_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "company_id", "application_id"],
            [
                "ip_patent_evidence_versions.id",
                "ip_patent_evidence_versions.company_id",
                "ip_patent_evidence_versions.application_id",
            ],
            name="fk_patent_opposition_evidence",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_patent_opposition_actor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "application_id", "sequence", name="uq_patent_opposition_sequence"
        ),
        UniqueConstraint(
            "company_id", "proceeding_id", "revision", name="uq_patent_opposition_revision"
        ),
        CheckConstraint(
            "revision > 0 AND revision <= 100 AND sequence > 0 "
            "AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_opposition_versions",
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_patent_opposition_hash"),
        CheckConstraint(
            "after_stage IN ('notice_recorded','response_preparation','response_filed',"
            "'hearing_recorded','decided','withdrawn')",
            name="ck_patent_opposition_stage",
        ),
        CheckConstraint(
            "(revision = 1 AND before_stage IS NULL AND after_stage = 'notice_recorded') "
            "OR (revision > 1 AND before_stage IS NOT NULL)",
            name="ck_patent_opposition_initial",
        ),
        CheckConstraint(
            "(after_stage IN ('decided','withdrawn') AND outcome IS NOT NULL) "
            "OR (after_stage NOT IN ('decided','withdrawn') AND outcome IS NULL)",
            name="ck_patent_opposition_outcome",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proceeding_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    before_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    after_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    proceeding_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    outcome: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    exceptional_transition_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    impact_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
