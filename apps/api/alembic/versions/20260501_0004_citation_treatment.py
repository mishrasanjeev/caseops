"""authority_citations treatment columns - PG-006 Phase 1A.

Adds the four good-law / treatment columns to authority_citations:

  treatment                  - StrEnum stored as varchar(24).
  treatment_evidence_text    - 500-char snippet around the cue verb.
  treatment_confidence       - numeric(4,3) in [0, 1].
  treatment_classified_at    - timestamptz of last classification.

Existing rows backfill to "neutral" with confidence/evidence/timestamp
NULL. The dedicated backfill script in scripts/backfill_citation_treatment.py
re-runs the heuristic classifier against the corpus and rewrites these
rows in place.

Revision ID: 20260501_0004
Revises: 20260501_0003
Create Date: 2026-05-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260501_0004"
down_revision = "20260501_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("authority_citations") as batch:
        batch.add_column(
            sa.Column(
                "treatment",
                sa.String(24),
                nullable=False,
                server_default="neutral",
            ),
        )
        batch.add_column(
            sa.Column(
                "treatment_evidence_text",
                sa.String(500),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "treatment_confidence",
                sa.Numeric(4, 3),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "treatment_classified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    op.create_index(
        "ix_authority_citations_treatment",
        "authority_citations",
        ["treatment"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_citations_treatment",
        table_name="authority_citations",
    )
    with op.batch_alter_table("authority_citations") as batch:
        batch.drop_column("treatment_classified_at")
        batch.drop_column("treatment_confidence")
        batch.drop_column("treatment_evidence_text")
        batch.drop_column("treatment")
