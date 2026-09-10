"""Append-only patent work-product evidence beside the canonical domain owners."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base


class IpPatentEvidenceVersion(Base):
    __tablename__ = "ip_patent_evidence_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["ip_patent_applications.id", "ip_patent_applications.company_id"],
            ondelete="RESTRICT",
            name="fk_patent_evidence_application",
        ),
        ForeignKeyConstraint(
            ["anchor_version_id", "company_id", "application_id"],
            [
                "ip_patent_application_versions.id",
                "ip_patent_application_versions.company_id",
                "ip_patent_application_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_evidence_anchor",
        ),
        ForeignKeyConstraint(
            ["predecessor_id", "company_id", "application_id"],
            [
                "ip_patent_evidence_versions.id",
                "ip_patent_evidence_versions.company_id",
                "ip_patent_evidence_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_evidence_predecessor",
        ),
        ForeignKeyConstraint(
            ["root_id", "company_id", "application_id"],
            [
                "ip_patent_evidence_versions.id",
                "ip_patent_evidence_versions.company_id",
                "ip_patent_evidence_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_evidence_root",
        ),
        ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_evidence_source",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
            name="fk_patent_evidence_actor",
        ),
        UniqueConstraint("id", "company_id", "application_id", name="uq_patent_evidence_owner"),
        UniqueConstraint(
            "company_id", "application_id", "sequence", name="uq_patent_evidence_sequence"
        ),
        UniqueConstraint(
            "company_id", "application_id", "root_id", "edition", name="uq_patent_evidence_edition"
        ),
        UniqueConstraint("company_id", "predecessor_id", name="uq_patent_evidence_successor"),
        CheckConstraint(
            "sequence > 0 AND edition > 0 AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_evidence_versions",
        ),
        CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id <> id", name="ck_patent_evidence_no_self"
        ),
        CheckConstraint(
            "(predecessor_id IS NULL AND root_id = id AND edition = 1) OR "
            "(predecessor_id IS NOT NULL AND root_id <> id AND edition > 1)",
            name="ck_patent_evidence_lineage",
        ),
        CheckConstraint(
            "length(source_sha256) = 64 AND length(manifest_sha256) = 64",
            name="ck_patent_evidence_hashes",
        ),
        CheckConstraint(
            "document_count >= 1 AND document_count <= 20", name="ck_patent_evidence_document_count"
        ),
        CheckConstraint(
            "document_kind IN ('claims','specification','drawings','abstract','sequence_listing',"
            "'translation','amendment','response','filing_package')",
            name="ck_patent_evidence_kind",
        ),
        Index("ix_patent_evidence_history", "company_id", "application_id", "root_id", "sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    root_id: Mapped[str] = mapped_column(String(36), nullable=False)
    predecessor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    edition: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class IpPatentEvidenceDocument(Base):
    __tablename__ = "ip_patent_evidence_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["evidence_id", "company_id", "application_id"],
            [
                "ip_patent_evidence_versions.id",
                "ip_patent_evidence_versions.company_id",
                "ip_patent_evidence_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_manifest_evidence",
        ),
        ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_manifest_document",
        ),
        UniqueConstraint("company_id", "evidence_id", "ordinal", name="uq_patent_manifest_ordinal"),
        UniqueConstraint(
            "company_id", "evidence_id", "document_version_id", name="uq_patent_manifest_version"
        ),
        CheckConstraint("ordinal >= 0 AND ordinal < 20", name="ck_patent_manifest_ordinal"),
        CheckConstraint("length(content_sha256) = 64", name="ck_patent_manifest_hash"),
        CheckConstraint(
            "document_kind IN ('claims','specification','drawings','abstract','sequence_listing',"
            "'translation','amendment','response')",
            name="ck_patent_manifest_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    document_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class IpPatentProsecutionEvent(Base):
    __tablename__ = "ip_patent_prosecution_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["ip_patent_applications.id", "ip_patent_applications.company_id"],
            ondelete="RESTRICT",
            name="fk_patent_prosecution_application",
        ),
        ForeignKeyConstraint(
            ["anchor_version_id", "company_id", "application_id"],
            [
                "ip_patent_application_versions.id",
                "ip_patent_application_versions.company_id",
                "ip_patent_application_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_prosecution_anchor",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "company_id", "application_id"],
            [
                "ip_patent_evidence_versions.id",
                "ip_patent_evidence_versions.company_id",
                "ip_patent_evidence_versions.application_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_prosecution_evidence",
        ),
        ForeignKeyConstraint(
            ["source_document_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
            name="fk_patent_prosecution_source",
        ),
        ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
            name="fk_patent_prosecution_actor",
        ),
        UniqueConstraint(
            "company_id", "application_id", "sequence", name="uq_patent_prosecution_sequence"
        ),
        CheckConstraint(
            "sequence > 0 AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_prosecution_versions",
        ),
        CheckConstraint("length(source_sha256) = 64", name="ck_patent_prosecution_hash"),
        CheckConstraint(
            "event_kind IN ('filing_preparation','filing','publication','examination_request',"
            "'office_action','response','hearing','amendment','grant','restoration')",
            name="ck_patent_prosecution_kind",
        ),
        Index("ix_patent_prosecution_date", "company_id", "application_id", "effective_on"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    anchor_version: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    effective_on: Mapped[date] = mapped_column(Date, nullable=False)
    source_document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    before_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    after_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    impact_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    exceptional_transition_reason: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
