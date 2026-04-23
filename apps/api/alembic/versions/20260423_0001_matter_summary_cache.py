"""EG-005 (2026-04-23) — matter executive summary cache columns.

Codex enterprise gap EG-005: every GET / DOCX / PDF on the matter
summary endpoint hit the LLM, paying ~$0.006 per call even when the
underlying matter dossier hadn't changed. A user opening the cockpit
+ exporting both formats triggered three identical Haiku calls.

Cache the structured summary on the matter row itself so:

- GET /matters/{id}/summary returns the cached payload when present
  and within TTL.
- POST /matters/{id}/summary/regenerate forces a refresh.
- DOCX / PDF exports reuse the same cached payload — no extra LLM
  spend on format conversion.

The cache is intentionally a plain JSON column (not a separate table)
because there is exactly one summary per matter and the lifecycle
matches the matter's own lifetime — when the matter is deleted, the
cache goes with it. ``model_run_id`` lets us trace which LLM call
produced the cached value.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260423_0001"
down_revision = "20260422_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matters") as batch:
        batch.add_column(
            sa.Column(
                "executive_summary_json", sa.JSON(), nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "executive_summary_generated_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "executive_summary_model_run_id",
                sa.String(length=36),
                nullable=True,
            ),
        )
        # Soft FK only — model_runs may be pruned for retention reasons,
        # and a stale cache entry pointing at a deleted run is still
        # useful (the JSON payload itself is what the UI renders).
        batch.create_foreign_key(
            "fk_matters_executive_summary_model_run",
            "model_runs",
            ["executive_summary_model_run_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("matters") as batch:
        batch.drop_constraint(
            "fk_matters_executive_summary_model_run", type_="foreignkey"
        )
        batch.drop_column("executive_summary_model_run_id")
        batch.drop_column("executive_summary_generated_at")
        batch.drop_column("executive_summary_json")
