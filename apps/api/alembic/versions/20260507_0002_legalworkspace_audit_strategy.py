"""LegalWorkspace LW-S11 matter audit and strategy entries.

Revision ID: 20260507_0002
Revises: 20260507_0001
Create Date: 2026-05-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260507_0002"
down_revision = "20260507_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "matter_strategy_entries",
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
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("entry_type", sa.String(length=24), nullable=False, server_default="plan"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column(
            "owner_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_recommendation_id",
            sa.String(length=36),
            sa.ForeignKey("recommendations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_matter_strategy_entries_company_id", "matter_strategy_entries", ["company_id"])
    op.create_index("ix_matter_strategy_entries_matter_id", "matter_strategy_entries", ["matter_id"])
    op.create_index(
        "ix_matter_strategy_entries_owner_membership_id",
        "matter_strategy_entries",
        ["owner_membership_id"],
    )
    op.create_index(
        "ix_matter_strategy_entries_created_by_membership_id",
        "matter_strategy_entries",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_matter_strategy_entries_updated_by_membership_id",
        "matter_strategy_entries",
        ["updated_by_membership_id"],
    )
    op.create_index(
        "ix_matter_strategy_entries_source_recommendation_id",
        "matter_strategy_entries",
        ["source_recommendation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_strategy_entries_source_recommendation_id",
        table_name="matter_strategy_entries",
    )
    op.drop_index(
        "ix_matter_strategy_entries_updated_by_membership_id",
        table_name="matter_strategy_entries",
    )
    op.drop_index(
        "ix_matter_strategy_entries_created_by_membership_id",
        table_name="matter_strategy_entries",
    )
    op.drop_index(
        "ix_matter_strategy_entries_owner_membership_id",
        table_name="matter_strategy_entries",
    )
    op.drop_index("ix_matter_strategy_entries_matter_id", table_name="matter_strategy_entries")
    op.drop_index("ix_matter_strategy_entries_company_id", table_name="matter_strategy_entries")
    op.drop_table("matter_strategy_entries")
