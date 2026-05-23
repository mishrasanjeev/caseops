"""ADP-02 AI token governance quota fields.

Revision ID: 20260523_0001
Revises: 20260522_0001
Create Date: 2026-05-23
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260523_0001"
down_revision = "20260522_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.add_column(sa.Column("user_monthly_token_budget", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "token_warning_threshold_percent",
                sa.Integer(),
                nullable=False,
                server_default="90",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.drop_column("token_warning_threshold_percent")
        batch.drop_column("user_monthly_token_budget")
