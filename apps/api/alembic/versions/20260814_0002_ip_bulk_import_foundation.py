"""IPLF-032A neutral bulk import job owner plus typed IP staging rows.

Additive and unseeded. The legacy ``matter_bulk_import_jobs`` and
``employee_bulk_import_jobs`` owners are untouched and remain canonical for
their own domains; nothing is migrated out of them.

Revision ID: 20260814_0002
Revises: 20260814_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260814_0002"
down_revision = "20260814_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Bound the lock window: this migration only creates new tables, so it
        # must never wait behind a long-running writer.
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    op.create_table(
        "bulk_import_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="staged"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("committed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("preview_token", sa.String(length=64), nullable=True),
        sa.Column("preview_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("creator_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_bulk_import_job_company"),
        sa.UniqueConstraint(
            "company_id", "domain", "idempotency_key", name="uq_bulk_import_job_idempotency"
        ),
        sa.CheckConstraint("domain IN ('ip_trademark')", name="ck_bulk_import_job_domain"),
        sa.CheckConstraint(
            "status IN ('staged', 'preview_ready', 'committed', "
            "'committed_with_errors', 'failed', 'cancelled')",
            name="ck_bulk_import_job_status",
        ),
        sa.CheckConstraint("total_rows >= 0", name="ck_bulk_import_job_total_rows"),
    )
    op.create_index("ix_bulk_import_jobs_company_id", "bulk_import_jobs", ["company_id"])
    op.create_index(
        "ix_bulk_import_jobs_created_by_membership_id",
        "bulk_import_jobs",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_bulk_import_jobs_company_domain", "bulk_import_jobs", ["company_id", "domain"]
    )

    op.create_table(
        "ip_import_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column(
            "validation_status", sa.String(length=16), nullable=False, server_default="valid"
        ),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("commit_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("commit_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_docket_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_id", "company_id"],
            ["bulk_import_jobs.id", "bulk_import_jobs.company_id"],
            name="fk_ip_import_row_job_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_docket_id"], ["ip_docket_records.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "row_number", name="uq_ip_import_row_number"),
        sa.CheckConstraint("row_number > 0", name="ck_ip_import_row_number_positive"),
        sa.CheckConstraint(
            "validation_status IN ('valid', 'invalid')",
            name="ck_ip_import_row_validation_status",
        ),
        sa.CheckConstraint(
            "commit_status IN ('pending', 'committed', 'failed', 'skipped')",
            name="ck_ip_import_row_commit_status",
        ),
    )
    op.create_index("ix_ip_import_rows_company_id", "ip_import_rows", ["company_id"])
    op.create_index("ix_ip_import_rows_job_id", "ip_import_rows", ["job_id"])
    op.create_index("ix_ip_import_rows_created_docket_id", "ip_import_rows", ["created_docket_id"])
    op.create_index("ix_ip_import_rows_job_commit", "ip_import_rows", ["job_id", "commit_status"])


def downgrade() -> None:
    # Both tables are introduced by this revision and nothing else references
    # them, so an empty rollback is a clean drop in dependency-safe order.
    op.drop_index("ix_ip_import_rows_job_commit", table_name="ip_import_rows")
    op.drop_index("ix_ip_import_rows_created_docket_id", table_name="ip_import_rows")
    op.drop_index("ix_ip_import_rows_job_id", table_name="ip_import_rows")
    op.drop_index("ix_ip_import_rows_company_id", table_name="ip_import_rows")
    op.drop_table("ip_import_rows")
    op.drop_index("ix_bulk_import_jobs_company_domain", table_name="bulk_import_jobs")
    op.drop_index("ix_bulk_import_jobs_created_by_membership_id", table_name="bulk_import_jobs")
    op.drop_index("ix_bulk_import_jobs_company_id", table_name="bulk_import_jobs")
    op.drop_table("bulk_import_jobs")
