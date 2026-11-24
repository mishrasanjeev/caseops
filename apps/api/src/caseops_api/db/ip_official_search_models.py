"""Tenant-owned lineage for result pages a lawyer saved from IP India's own search."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from caseops_api.db.base import Base

OFFICIAL_SEARCH_SOURCE_KINDS = ("ipindia_estatus", "ipindia_eregister", "ipindia_public_search")
OFFICIAL_SEARCH_PARSE_STATUSES = ("parsed", "needs_review", "unreadable")
OFFICIAL_SEARCH_RESOLUTIONS = ("pending", "linked", "staged_new_record", "dismissed")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


class IpOfficialSearchImport(Base):
    """One uploaded IP India result page: lineage, read fields and review reasons.

    The uploaded bytes are not retained. The row keeps the file's SHA-256 and
    size, the fixed official URL for the chosen search, the acting member and
    only the fields the parser could read reliably; everything else is a
    review item with a reason.
    """

    __tablename__ = "ip_official_search_imports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ip_official_search_import_company",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_official_search_import_uploader",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["resolved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_official_search_import_resolver",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["linked_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_official_search_import_docket",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["linked_application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_official_search_import_application",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["registry_snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_ip_official_search_import_snapshot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["import_job_id", "company_id"],
            ["bulk_import_jobs.id", "bulk_import_jobs.company_id"],
            name="fk_ip_official_search_import_job",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            _in("source_kind", OFFICIAL_SEARCH_SOURCE_KINDS),
            name="ck_ip_official_search_import_source_kind",
        ),
        CheckConstraint(
            "content_kind IN ('html', 'pdf')",
            name="ck_ip_official_search_import_content_kind",
        ),
        CheckConstraint(
            _in("parse_status", OFFICIAL_SEARCH_PARSE_STATUSES),
            name="ck_ip_official_search_import_parse_status",
        ),
        CheckConstraint(
            _in("resolution_status", OFFICIAL_SEARCH_RESOLUTIONS),
            name="ck_ip_official_search_import_resolution",
        ),
        CheckConstraint(
            "length(file_sha256) = 64 AND byte_size > 0",
            name="ck_ip_official_search_import_file",
        ),
        CheckConstraint(
            "resolution_status <> 'linked' OR "
            "(linked_application_id IS NOT NULL AND registry_snapshot_id IS NOT NULL)",
            name="ck_ip_official_search_import_linked_target",
        ),
        CheckConstraint(
            "resolution_status <> 'staged_new_record' OR import_job_id IS NOT NULL",
            name="ck_ip_official_search_import_staged_job",
        ),
        UniqueConstraint("id", "company_id", name="uq_ip_official_search_import_id_company"),
        UniqueConstraint("company_id", "file_sha256", name="uq_ip_official_search_import_file"),
        Index(
            "ix_ip_official_search_imports_company_uploaded",
            "company_id",
            "uploaded_at",
        ),
        Index(
            "ix_ip_official_search_imports_uploader",
            "uploaded_by_membership_id",
            "company_id",
        ),
        Index(
            "ix_ip_official_search_imports_resolver",
            "resolved_by_membership_id",
            "company_id",
        ),
        Index("ix_ip_official_search_imports_docket", "linked_docket_id", "company_id"),
        Index(
            "ix_ip_official_search_imports_application",
            "linked_application_id",
            "company_id",
        ),
        Index("ix_ip_official_search_imports_snapshot", "registry_snapshot_id", "company_id"),
        Index("ix_ip_official_search_imports_job", "import_job_id", "company_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    company_id: Mapped[str] = mapped_column(String(36), nullable=False)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    official_url: Mapped[str] = mapped_column(String(800), nullable=False)
    search_query_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_kind: Mapped[str] = mapped_column(String(8), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(40), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(24), nullable=False)
    fields_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    published_values_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    review_items_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    attribution: Mapped[str] = mapped_column(String(200), nullable=False)
    resolution_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    resolution_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    linked_docket_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    linked_application_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    registry_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    import_job_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_by_membership_id: Mapped[str] = mapped_column(String(36), nullable=False)
    resolved_by_membership_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
