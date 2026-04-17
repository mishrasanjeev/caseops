"""hearing packs + items

Revision ID: 20260417_0004
Revises: 20260417_0003
Create Date: 2026-04-17 06:00:00

Adds `hearing_packs` and `hearing_pack_items` for §4.5. A HearingPack is
always tenant-scoped (via matter_id) and always `review_required=True`
until a human reviews it. Items are typed so the UI can group them
into the PRD §9.6 sections.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260417_0004"
down_revision = "20260417_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hearing_packs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "hearing_id",
            sa.String(length=36),
            sa.ForeignKey("matter_hearings.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "generated_by_membership_id",
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
        sa.Column(
            "model_run_id",
            sa.String(length=36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_hearing_packs_matter_status",
        "hearing_packs",
        ["matter_id", "status"],
    )

    op.create_table(
        "hearing_pack_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "pack_id",
            sa.String(length=36),
            sa.ForeignKey("hearing_packs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("item_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("source_ref", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_hearing_pack_items_pack_rank",
        "hearing_pack_items",
        ["pack_id", "rank"],
    )


def downgrade() -> None:
    op.drop_index("ix_hearing_pack_items_pack_rank", table_name="hearing_pack_items")
    op.drop_table("hearing_pack_items")
    op.drop_index("ix_hearing_packs_matter_status", table_name="hearing_packs")
    op.drop_table("hearing_packs")
