"""Slice A (MOD-TS-001-B) — judge_appointments career-history table.

Per docs/PRD_BENCH_MAPPING_2026-04-25.md §3 Slice A. The judges table
holds a single court_id FK (current appointment); judge_appointments
captures the full career timeline so /app/courts/judges/{id} can
render an "Also served on..." section.

Schema rationale:
- (judge_id, court_id, role, start_date) is unique to prevent
  duplicate appointments when the seeder re-runs against the same
  source.
- end_date is nullable so an active appointment is end_date IS NULL.
- source_url + source_evidence_text capture provenance per
  bench-aware drafting hard rules — no hand-curated rows without a
  cited source.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260425_0001"
down_revision = "20260424_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "judge_appointments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "judge_id",
            sa.String(length=36),
            sa.ForeignKey("judges.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "court_id",
            sa.String(length=36),
            sa.ForeignKey("courts.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "role",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_evidence_text", sa.Text(), nullable=True),
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
            "judge_id",
            "court_id",
            "role",
            "start_date",
            name="uq_judge_appointments_unique",
        ),
    )
    # Composite index for the typical "career timeline for one judge"
    # query (ORDER BY start_date ASC).
    op.create_index(
        "ix_judge_appointments_timeline",
        "judge_appointments",
        ["judge_id", "start_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_judge_appointments_timeline",
        table_name="judge_appointments",
    )
    op.drop_table("judge_appointments")
