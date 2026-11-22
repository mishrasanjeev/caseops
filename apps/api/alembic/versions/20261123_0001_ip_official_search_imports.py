"""Tenant-scoped lineage for saved IP India official search result pages.

Revision ID: 20261123_0001
Revises: 20261112_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new, empty table and its indexes are
created. Existing tables are referenced by foreign keys only; no existing row
is scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward once used. Downgrade drops the table only
while it is empty and refuses before any DDL when an import row exists,
because linked rows are the lineage that registry snapshots point back to.
IPLF-052D/UJ-07, UJ-31. Re-chain down_revision after the in-flight release
(20261121_0001, 20261122_0001-0003) lands on main.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261123_0001"
down_revision = "20261112_0001"
branch_labels = None
depends_on = None

TABLE = "ip_official_search_imports"


def _membership_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "company_id"],
        ["company_memberships.id", "company_memberships.company_id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("source_kind", sa.String(40), nullable=False),
        sa.Column("official_url", sa.String(800), nullable=False),
        sa.Column("search_query_json", sa.JSON(), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_kind", sa.String(8), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column("parse_status", sa.String(24), nullable=False),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("published_values_json", sa.JSON(), nullable=False),
        sa.Column("review_items_json", sa.JSON(), nullable=False),
        sa.Column("attribution", sa.String(200), nullable=False),
        sa.Column("resolution_status", sa.String(24), nullable=False),
        sa.Column("resolution_reason", sa.String(500), nullable=True),
        sa.Column("linked_docket_id", sa.String(36), nullable=True),
        sa.Column("linked_application_id", sa.String(36), nullable=True),
        sa.Column("registry_snapshot_id", sa.String(36), nullable=True),
        sa.Column("import_job_id", sa.String(36), nullable=True),
        sa.Column("uploaded_by_membership_id", sa.String(36), nullable=False),
        sa.Column("resolved_by_membership_id", sa.String(36), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ip_official_search_import_company",
            ondelete="RESTRICT",
        ),
        _membership_fk("uploaded_by_membership_id", "fk_ip_official_search_import_uploader"),
        _membership_fk("resolved_by_membership_id", "fk_ip_official_search_import_resolver"),
        sa.ForeignKeyConstraint(
            ["linked_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_official_search_import_docket",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["linked_application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_official_search_import_application",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["registry_snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_ip_official_search_import_snapshot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["import_job_id", "company_id"],
            ["bulk_import_jobs.id", "bulk_import_jobs.company_id"],
            name="fk_ip_official_search_import_job",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source_kind IN ('ipindia_estatus', 'ipindia_eregister', 'ipindia_public_search')",
            name="ck_ip_official_search_import_source_kind",
        ),
        sa.CheckConstraint(
            "content_kind IN ('html', 'pdf')",
            name="ck_ip_official_search_import_content_kind",
        ),
        sa.CheckConstraint(
            "parse_status IN ('parsed', 'needs_review', 'unreadable')",
            name="ck_ip_official_search_import_parse_status",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('pending', 'linked', 'staged_new_record', 'dismissed')",
            name="ck_ip_official_search_import_resolution",
        ),
        sa.CheckConstraint(
            "length(file_sha256) = 64 AND byte_size > 0",
            name="ck_ip_official_search_import_file",
        ),
        sa.CheckConstraint(
            "resolution_status <> 'linked' OR "
            "(linked_application_id IS NOT NULL AND registry_snapshot_id IS NOT NULL)",
            name="ck_ip_official_search_import_linked_target",
        ),
        sa.CheckConstraint(
            "resolution_status <> 'staged_new_record' OR import_job_id IS NOT NULL",
            name="ck_ip_official_search_import_staged_job",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_official_search_import_id_company"),
        sa.UniqueConstraint("company_id", "file_sha256", name="uq_ip_official_search_import_file"),
    )
    for name, columns in (
        ("ix_ip_official_search_imports_company_uploaded", ["company_id", "uploaded_at"]),
        ("ix_ip_official_search_imports_uploader", ["uploaded_by_membership_id", "company_id"]),
        ("ix_ip_official_search_imports_resolver", ["resolved_by_membership_id", "company_id"]),
        ("ix_ip_official_search_imports_docket", ["linked_docket_id", "company_id"]),
        ("ix_ip_official_search_imports_application", ["linked_application_id", "company_id"]),
        ("ix_ip_official_search_imports_snapshot", ["registry_snapshot_id", "company_id"]),
        ("ix_ip_official_search_imports_job", ["import_job_id", "company_id"]),
    ):
        op.create_index(name, TABLE, columns)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.scalar(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")) is not None:
        raise RuntimeError(
            f"{TABLE} holds retained official-page lineage; restore-forward only"
        )
    op.drop_table(TABLE)
