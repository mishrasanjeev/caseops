"""Slice B (MOD-TS-001-C) — matter_cause_list_entries.judges_json column.

Per docs/PRD_BENCH_MAPPING_2026-04-25.md §3 Slice B. Resolves the
free-text bench_name into FK references to Judge rows so the matter
hearings tab can render per-judge clickable links.

JSON shape (when populated):
    [
      {"judge_id": "uuid", "matched_alias": "Justice X", "confidence": "exact"},
      ...
    ]

NULL when the row has not been processed by the resolver yet
(distinguish from "[]" which means "processed but no resolution").
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0003"
down_revision = "20260425_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matter_cause_list_entries",
        sa.Column("judges_json", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matter_cause_list_entries", "judges_json")
