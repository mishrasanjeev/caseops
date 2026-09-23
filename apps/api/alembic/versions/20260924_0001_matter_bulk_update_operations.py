"""Persist sanitized tenant-scoped matter bulk-update operation history."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260924_0001"
down_revision = "20260920_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_bulk_update_operations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploader_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("changed_rows", sa.Integer(), nullable=False),
        sa.Column("invalid_rows", sa.Integer(), nullable=False),
        sa.Column("applied_rows", sa.Integer(), nullable=False),
        sa.Column("failed_rows", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_matter_bulk_update_operations_company_id",
        "matter_bulk_update_operations",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_bulk_update_operations_uploader_membership_id",
        "matter_bulk_update_operations",
        ["uploader_membership_id"],
    )
    op.create_index(
        "ix_matter_bulk_update_operations_company_created",
        "matter_bulk_update_operations",
        ["company_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_bulk_update_operations_company_created",
        table_name="matter_bulk_update_operations",
    )
    op.drop_index(
        "ix_matter_bulk_update_operations_uploader_membership_id",
        table_name="matter_bulk_update_operations",
    )
    op.drop_index(
        "ix_matter_bulk_update_operations_company_id",
        table_name="matter_bulk_update_operations",
    )
    op.drop_table("matter_bulk_update_operations")
