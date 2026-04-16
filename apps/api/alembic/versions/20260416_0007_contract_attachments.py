"""Add contract attachments."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0007"
down_revision = "20260416_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contract_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("contract_id", sa.String(length=36), nullable=False),
        sa.Column("uploaded_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256_hex", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contract_id"], ["contracts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["uploaded_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        op.f("ix_contract_attachments_contract_id"),
        "contract_attachments",
        ["contract_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_contract_attachments_uploaded_by_membership_id"),
        "contract_attachments",
        ["uploaded_by_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_contract_attachments_uploaded_by_membership_id"),
        table_name="contract_attachments",
    )
    op.drop_index(op.f("ix_contract_attachments_contract_id"), table_name="contract_attachments")
    op.drop_table("contract_attachments")
