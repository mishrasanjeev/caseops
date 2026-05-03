"""recommendations.strategy_payload_json — litigation strategy planner.

Adds a nullable TEXT column to the existing ``recommendations`` table.
Populated only for rows with ``type='litigation_strategy'``; null on
every other recommendation row. The Pydantic schema on the strategy
service validates the payload shape on read/write — the column is just
opaque JSON to the database.

Revision ID: 20260503_0001
Revises: 20260501_0004
Create Date: 2026-05-03
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260503_0001"
down_revision = "20260501_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(
            sa.Column(
                "strategy_payload_json",
                sa.Text(),
                nullable=True,
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_column("strategy_payload_json")
