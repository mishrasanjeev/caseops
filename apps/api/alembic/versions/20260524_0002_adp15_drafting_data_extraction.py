"""ADP-15 drafting data extraction review queue.

Revision ID: 20260524_0002
Revises: 20260524_0001
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260524_0002"
down_revision = "20260524_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "drafting_data_extraction_fields",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("field_key", sa.String(length=80), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("proposed_value", sa.String(length=500), nullable=False),
        sa.Column("reviewed_value", sa.String(length=500), nullable=True),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "confidence_band",
            sa.String(length=16),
            nullable=False,
            server_default="low",
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="needs_review",
        ),
        sa.Column("source_snippet", sa.String(length=280), nullable=True),
        sa.Column(
            "source_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("source_char_start", sa.Integer(), nullable=True),
        sa.Column("source_char_end", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "status IN ('suggested', 'needs_review', 'confirmed', 'overridden', 'rejected')",
            name="ck_drafting_data_extraction_status",
        ),
        sa.CheckConstraint(
            "confidence_band IN ('high', 'medium', 'low')",
            name="ck_drafting_data_confidence_band",
        ),
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_company_id",
        "drafting_data_extraction_fields",
        ["company_id"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_matter_id",
        "drafting_data_extraction_fields",
        ["matter_id"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_source_attachment_id",
        "drafting_data_extraction_fields",
        ["source_attachment_id"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_created_by_membership_id",
        "drafting_data_extraction_fields",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_reviewed_by_membership_id",
        "drafting_data_extraction_fields",
        ["reviewed_by_membership_id"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_field_key",
        "drafting_data_extraction_fields",
        ["field_key"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_value_hash",
        "drafting_data_extraction_fields",
        ["value_hash"],
    )
    op.create_index(
        "ix_drafting_data_extraction_fields_status",
        "drafting_data_extraction_fields",
        ["status"],
    )
    op.create_index(
        "ix_drafting_data_extraction_company_matter",
        "drafting_data_extraction_fields",
        ["company_id", "matter_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_drafting_data_extraction_company_matter",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_status",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_value_hash",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_field_key",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_reviewed_by_membership_id",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_created_by_membership_id",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_source_attachment_id",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_matter_id",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_index(
        "ix_drafting_data_extraction_fields_company_id",
        table_name="drafting_data_extraction_fields",
    )
    op.drop_table("drafting_data_extraction_fields")
