"""Persistent bulk matter creation, import history, and complete template fields.

Revision ID: 20260717_0002
Revises: 20260717_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260717_0002"
down_revision = "20260717_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matters") as batch_op:
        batch_op.add_column(sa.Column("responsible_lawyer_membership_id", sa.String(36)))
        batch_op.add_column(sa.Column("matter_type", sa.String(120)))
        batch_op.add_column(sa.Column("client_code", sa.String(80)))
        batch_op.add_column(sa.Column("client_contact_number", sa.String(40)))
        batch_op.add_column(sa.Column("client_email", sa.String(320)))
        batch_op.add_column(sa.Column("opposing_counsel", sa.String(255)))
        batch_op.add_column(sa.Column("filing_number", sa.String(120)))
        batch_op.add_column(sa.Column("filing_date", sa.Date()))
        batch_op.create_foreign_key(
            "fk_matters_responsible_lawyer_membership_id",
            "company_memberships",
            ["responsible_lawyer_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_matters_responsible_lawyer_membership_id",
            ["responsible_lawyer_membership_id"],
        )
        batch_op.create_index("ix_matters_filing_number", ["filing_number"])

    op.create_table(
        "matter_bulk_import_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(160)),
        sa.Column("manifest_format", sa.String(12), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="validated"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("validation_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_matter_bulk_import_jobs_company_id",
        "matter_bulk_import_jobs",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_bulk_import_jobs_created_by_membership_id",
        "matter_bulk_import_jobs",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_matter_bulk_import_jobs_status",
        "matter_bulk_import_jobs",
        ["status"],
    )
    op.create_index(
        "ix_matter_bulk_import_jobs_expires_at",
        "matter_bulk_import_jobs",
        ["expires_at"],
    )

    op.create_table(
        "matter_bulk_import_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(36),
            sa.ForeignKey("matter_bulk_import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="invalid"),
        sa.Column(
            "created_matter_id",
            sa.String(36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("job_id", "row_number", name="uq_matter_import_job_row"),
    )
    op.create_index(
        "ix_matter_bulk_import_rows_company_id",
        "matter_bulk_import_rows",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_bulk_import_rows_job_id",
        "matter_bulk_import_rows",
        ["job_id"],
    )
    op.create_index(
        "ix_matter_bulk_import_rows_status",
        "matter_bulk_import_rows",
        ["status"],
    )
    op.create_index(
        "ix_matter_bulk_import_rows_created_matter_id",
        "matter_bulk_import_rows",
        ["created_matter_id"],
    )


def downgrade() -> None:
    op.drop_table("matter_bulk_import_rows")
    op.drop_table("matter_bulk_import_jobs")
    with op.batch_alter_table("matters") as batch_op:
        batch_op.drop_index("ix_matters_filing_number")
        batch_op.drop_index("ix_matters_responsible_lawyer_membership_id")
        batch_op.drop_constraint(
            "fk_matters_responsible_lawyer_membership_id",
            type_="foreignkey",
        )
        batch_op.drop_column("filing_date")
        batch_op.drop_column("filing_number")
        batch_op.drop_column("opposing_counsel")
        batch_op.drop_column("client_email")
        batch_op.drop_column("client_contact_number")
        batch_op.drop_column("client_code")
        batch_op.drop_column("matter_type")
        batch_op.drop_column("responsible_lawyer_membership_id")
