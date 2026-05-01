"""tenant_ai_policies.predictive_bench_strategy_enabled — PG-107.

Adds an opt-in tenant flag for predictive bench analytics. Default
false; existing tenants stay on evidence-only output.

Revision ID: 20260501_0001
Revises: 20260430_0001
Create Date: 2026-05-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260501_0001"
down_revision = "20260430_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.add_column(
            sa.Column(
                "predictive_bench_strategy_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.drop_column("predictive_bench_strategy_enabled")
