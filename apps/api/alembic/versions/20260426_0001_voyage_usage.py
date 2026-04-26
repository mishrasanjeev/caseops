"""Voyage embedding-spend ledger (mirror of model_runs for Anthropic).

Companion to the $1,002.40 / $343 (Anthropic / Voyage) Apr 18-26 burn
audit. Without an on-DB ledger the only spend signal was the Voyage
console — by then we had already burned $43-70/day for a week.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0001"
down_revision = "20260425_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voyage_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True, index=True,
        ),
        sa.Column("purpose", sa.String(length=80), nullable=False, index=True),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_type", sa.String(length=16), nullable=False, server_default="document"),
        sa.Column("texts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dimensions", sa.Integer(), nullable=False, server_default="1024"),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=64), nullable=False, server_default="ok"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_voyage_usage_created_at_status",
        "voyage_usage",
        ["created_at", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_voyage_usage_created_at_status", table_name="voyage_usage")
    op.drop_table("voyage_usage")
