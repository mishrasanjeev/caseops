"""Slice D (MOD-TS-001-E) — judge_aliases table.

Per docs/PRD_BENCH_MAPPING_2026-04-25.md §3 Slice D. Replaces
ILIKE-on-judges_json matching in services/bench_strategy_context.py
with FK-based lookup against alias rows.

Schema rationale:
- alias_text is normalised (lowercased, punctuation stripped) so
  ILIKE/equality lookups are case-insensitive without per-query
  upper/lower work.
- (judge_id, alias_text) unique to prevent duplicates from re-running
  the backfill.
- source captures provenance for audit + admin de-dup.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0002"
down_revision = "20260425_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_aliases",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "judge_id",
            sa.String(length=36),
            sa.ForeignKey("judges.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("alias_text", sa.String(length=255), nullable=False, index=True),
        sa.Column("alias_normalised", sa.String(length=255), nullable=False, index=True),
        sa.Column("source", sa.String(length=64), nullable=False),
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
        sa.UniqueConstraint(
            "judge_id", "alias_normalised",
            name="uq_judge_aliases_unique",
        ),
    )


def downgrade() -> None:
    op.drop_table("judge_aliases")
