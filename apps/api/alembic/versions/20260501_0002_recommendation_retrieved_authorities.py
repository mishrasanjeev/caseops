"""recommendations.retrieved_authorities_json — PG-109 source-used panel.

JSON list of retrieved authority identifiers the LLM was given for the
recommendation. UI surfaces "considered M, cited N" by intersecting
this list with options[*].supporting_citations.

Revision ID: 20260501_0002
Revises: 20260501_0001
Create Date: 2026-05-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260501_0002"
down_revision = "20260501_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.add_column(
            sa.Column(
                "retrieved_authorities_json",
                sa.Text(),
                nullable=False,
                server_default=sa.text("'[]'"),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("recommendations") as batch:
        batch.drop_column("retrieved_authorities_json")
