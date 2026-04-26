"""Statute section provenance — track where section_text came from.

Per docs/PRD_STATUTE_MODEL_2026-04-25.md + the 2026-04-26 hybrid
enrichment decision (scrape indiacode.nic.in first, Haiku fallback for
unparseable). Adds three columns to statute_sections:

- section_text_source: 'indiacode_scrape' | 'haiku_generated' | 'manual'
  — NULL until enrichment runs.
- section_text_fetched_at: TIMESTAMPTZ — when the text was last
  populated. Lets a future re-enrichment job target stale rows.
- is_provisional: BOOLEAN DEFAULT false — TRUE for Haiku-generated
  rows. The web UI must render an "AI-generated, not authoritative;
  verify against the official source" warning when this is TRUE.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260426_0002"
down_revision = "20260426_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "statute_sections",
        sa.Column("section_text_source", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "statute_sections",
        sa.Column(
            "section_text_fetched_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "statute_sections",
        sa.Column(
            "is_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("statute_sections", "is_provisional")
    op.drop_column("statute_sections", "section_text_fetched_at")
    op.drop_column("statute_sections", "section_text_source")
