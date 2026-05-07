"""LegalWorkspace LW-S6 employee bulk import jobs.

Revision ID: 20260506_0002
Revises: 20260506_0001
Create Date: 2026-05-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260506_0002"
down_revision = "20260506_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "employee_bulk_import_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="previewed",
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invalid_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_employee_bulk_import_jobs_company_id",
        "employee_bulk_import_jobs",
        ["company_id"],
    )
    op.create_index(
        "ix_employee_bulk_import_jobs_created_by_membership_id",
        "employee_bulk_import_jobs",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_employee_bulk_import_jobs_status",
        "employee_bulk_import_jobs",
        ["status"],
    )
    op.create_index(
        "ix_employee_bulk_import_jobs_expires_at",
        "employee_bulk_import_jobs",
        ["expires_at"],
    )

    op.create_table(
        "employee_bulk_import_rows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.String(length=36),
            sa.ForeignKey("employee_bulk_import_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("errors_json", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="invalid",
        ),
        sa.Column(
            "created_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_employee_bulk_import_rows_company_id",
        "employee_bulk_import_rows",
        ["company_id"],
    )
    op.create_index(
        "ix_employee_bulk_import_rows_job_id",
        "employee_bulk_import_rows",
        ["job_id"],
    )
    op.create_index(
        "ix_employee_bulk_import_rows_status",
        "employee_bulk_import_rows",
        ["status"],
    )
    op.create_index(
        "ix_employee_bulk_import_rows_created_membership_id",
        "employee_bulk_import_rows",
        ["created_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_employee_bulk_import_rows_created_membership_id",
        table_name="employee_bulk_import_rows",
    )
    op.drop_index("ix_employee_bulk_import_rows_status", table_name="employee_bulk_import_rows")
    op.drop_index("ix_employee_bulk_import_rows_job_id", table_name="employee_bulk_import_rows")
    op.drop_index(
        "ix_employee_bulk_import_rows_company_id",
        table_name="employee_bulk_import_rows",
    )
    op.drop_table("employee_bulk_import_rows")

    op.drop_index(
        "ix_employee_bulk_import_jobs_expires_at",
        table_name="employee_bulk_import_jobs",
    )
    op.drop_index("ix_employee_bulk_import_jobs_status", table_name="employee_bulk_import_jobs")
    op.drop_index(
        "ix_employee_bulk_import_jobs_created_by_membership_id",
        table_name="employee_bulk_import_jobs",
    )
    op.drop_index(
        "ix_employee_bulk_import_jobs_company_id",
        table_name="employee_bulk_import_jobs",
    )
    op.drop_table("employee_bulk_import_jobs")
