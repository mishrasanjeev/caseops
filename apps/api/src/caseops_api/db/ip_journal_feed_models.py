"""Public Trade Marks Journal source store and tenant-scoped feed state.

The three ``ip_public_journal_*`` tables hold only what IP India publishes
publicly, with source lineage; they carry no tenant column and no tenant
writes them. Comparisons, hits and the per-workspace setting stay tenant-scoped
(``ip_journal_feed_settings``, ``ip_journal_feed_tenant_runs`` and the existing
journal-watch tables).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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


class IpPublicJournalCheck(Base):
    """One listing check of the public journal page (throttle and health)."""

    __tablename__ = "ip_public_journal_checks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('succeeded', 'failed', 'refused')",
            name="ck_ip_public_journal_check_status",
        ),
        Index("ix_ip_public_journal_checks_source_checked", "source_key", "checked_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listing_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issues_listed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    documents_discovered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpPublicJournalDocument(Base):
    """One officially listed journal PDF and its retrieval and parse outcome."""

    __tablename__ = "ip_public_journal_documents"
    __table_args__ = (
        UniqueConstraint(
            "source_key", "journal_number", "file_name", name="uq_ip_public_journal_document_file"
        ),
        CheckConstraint(
            "status IN ('pending', 'parsed', 'needs_review', 'failed')",
            name="ck_ip_public_journal_document_status",
        ),
        Index("ix_ip_public_journal_documents_status_date", "status", "journal_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_key: Mapped[str] = mapped_column(String(80), nullable=False)
    journal_number: Mapped[str] = mapped_column(String(40), nullable=False)
    journal_date: Mapped[date] = mapped_column(Date, nullable=False)
    available_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    file_name: Mapped[str] = mapped_column(String(400), nullable=False)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parser_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpPublicJournalEntry(Base):
    """One parsed advertisement, or one span of pages flagged for review."""

    __tablename__ = "ip_public_journal_entries"
    __table_args__ = (
        UniqueConstraint("document_id", "entry_index", name="uq_ip_public_journal_entry_index"),
        CheckConstraint(
            "status IN ('parsed', 'needs_review')",
            name="ck_ip_public_journal_entry_status",
        ),
        CheckConstraint(
            "status <> 'parsed' OR application_number IS NOT NULL",
            name="ck_ip_public_journal_entry_parsed_application",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ip_public_journal_documents.id",
            name="fk_ip_public_journal_entry_document",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    entry_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    review_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    journal_page: Mapped[str | None] = mapped_column(String(20), nullable=True)
    application_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    filing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mark_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    proprietor_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    class_numbers_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    goods_services_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    registry_office: Mapped[str | None] = mapped_column(String(80), nullable=True)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpJournalFeedSetting(Base):
    """Per-workspace opt-in; the feed compares as the member who enabled it."""

    __tablename__ = "ip_journal_feed_settings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_as_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_setting_run_as",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_setting_updated_by",
            ondelete="RESTRICT",
        ),
        Index("ix_ip_journal_feed_settings_run_as", "run_as_membership_id", "company_id"),
        Index("ix_ip_journal_feed_settings_updated_by", "updated_by_membership_id", "company_id"),
    )

    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", name="fk_ip_journal_feed_setting_company", ondelete="RESTRICT"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_as_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    updated_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IpJournalFeedTenantRun(Base):
    """One workspace's comparison of one public journal document."""

    __tablename__ = "ip_journal_feed_tenant_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_as_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_feed_tenant_run_actor",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "document_id", name="uq_ip_journal_feed_tenant_run"),
        CheckConstraint(
            "status IN ('completed', 'no_active_profiles', 'feature_unavailable', "
            "'actor_unavailable', 'incident_kill_switch', 'match_limit_exceeded', 'failed')",
            name="ck_ip_journal_feed_tenant_run_status",
        ),
        Index("ix_ip_journal_feed_tenant_runs_document", "document_id"),
        Index("ix_ip_journal_feed_tenant_runs_actor", "run_as_membership_id", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "companies.id", name="fk_ip_journal_feed_tenant_run_company", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "ip_public_journal_documents.id",
            name="fk_ip_journal_feed_tenant_run_document",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    run_as_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entries_compared: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matched_entries: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    publications_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hits_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ingestion_run_ids_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
