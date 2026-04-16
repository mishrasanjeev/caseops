"""Add matter attachments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0003"
down_revision = "20260416_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["matter_id"],
            ["matters.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_matter_attachments_matter_id"),
        "matter_attachments",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_attachments_uploaded_by_membership_id"),
        "matter_attachments",
        ["uploaded_by_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_matter_attachments_uploaded_by_membership_id"),
        table_name="matter_attachments",
    )
    op.drop_index(op.f("ix_matter_attachments_matter_id"), table_name="matter_attachments")
    op.drop_table("matter_attachments")
