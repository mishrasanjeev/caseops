"""LegalWorkspace LW-S1 matter claims, filters, and tags.

Revision ID: 20260505_0001
Revises: 20260503_0001
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260505_0001"
down_revision = "20260503_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("matters") as batch:
        batch.add_column(sa.Column("claim_amount_minor", sa.BigInteger(), nullable=True))
        batch.add_column(
            sa.Column(
                "claim_currency",
                sa.String(length=3),
                nullable=False,
                server_default="INR",
            ),
        )
        batch.add_column(sa.Column("claim_amount_notes", sa.Text(), nullable=True))

    op.create_table(
        "matter_tags",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("color_key", sa.String(length=40), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "slug", name="uq_matter_tags_company_slug"),
    )
    op.create_index("ix_matter_tags_company_id", "matter_tags", ["company_id"])
    op.create_index(
        "ix_matter_tags_created_by_membership_id",
        "matter_tags",
        ["created_by_membership_id"],
    )

    op.create_table(
        "matter_tag_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["matter_tags.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("matter_id", "tag_id", name="uq_matter_tag_assignment"),
    )
    op.create_index(
        "ix_matter_tag_assignments_company_id",
        "matter_tag_assignments",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_tag_assignments_matter_id",
        "matter_tag_assignments",
        ["matter_id"],
    )
    op.create_index(
        "ix_matter_tag_assignments_tag_id",
        "matter_tag_assignments",
        ["tag_id"],
    )
    op.create_index(
        "ix_matter_tag_assignments_created_by_membership_id",
        "matter_tag_assignments",
        ["created_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_tag_assignments_created_by_membership_id",
        table_name="matter_tag_assignments",
    )
    op.drop_index("ix_matter_tag_assignments_tag_id", table_name="matter_tag_assignments")
    op.drop_index(
        "ix_matter_tag_assignments_matter_id",
        table_name="matter_tag_assignments",
    )
    op.drop_index(
        "ix_matter_tag_assignments_company_id",
        table_name="matter_tag_assignments",
    )
    op.drop_table("matter_tag_assignments")

    op.drop_index("ix_matter_tags_created_by_membership_id", table_name="matter_tags")
    op.drop_index("ix_matter_tags_company_id", table_name="matter_tags")
    op.drop_table("matter_tags")

    with op.batch_alter_table("matters") as batch:
        batch.drop_column("claim_amount_notes")
        batch.drop_column("claim_currency")
        batch.drop_column("claim_amount_minor")
