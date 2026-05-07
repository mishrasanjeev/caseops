"""LegalWorkspace LW-S2 order metadata and timeline indicators.

Revision ID: 20260505_0002
Revises: 20260505_0001
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260505_0002"
down_revision = "20260505_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("matter_court_orders") as batch:
        batch.add_column(sa.Column("bench_name", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("judge_names_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("order_attachment_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("order_kind", sa.String(length=40), nullable=True))
        batch.add_column(
            sa.Column(
                "is_interim_order",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("stay_status", sa.String(length=24), nullable=True))
        batch.add_column(sa.Column("stay_effective_until", sa.Date(), nullable=True))
        batch.create_foreign_key(
            "fk_matter_court_orders_order_attachment_id",
            "matter_attachments",
            ["order_attachment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            "ix_matter_court_orders_order_attachment_id",
            ["order_attachment_id"],
        )
        batch.create_index(
            "ix_matter_court_orders_stay_status",
            ["stay_status"],
        )


def downgrade() -> None:
    with op.batch_alter_table("matter_court_orders") as batch:
        batch.drop_index("ix_matter_court_orders_stay_status")
        batch.drop_index("ix_matter_court_orders_order_attachment_id")
        batch.drop_constraint(
            "fk_matter_court_orders_order_attachment_id",
            type_="foreignkey",
        )
        batch.drop_column("stay_effective_until")
        batch.drop_column("stay_status")
        batch.drop_column("is_interim_order")
        batch.drop_column("order_kind")
        batch.drop_column("order_attachment_id")
        batch.drop_column("judge_names_json")
        batch.drop_column("bench_name")
