"""corpus quality: nullable decision_date + structured extraction columns

Revision ID: 20260419_0001
Revises: 20260418_0011
Create Date: 2026-04-19 00:30:00

Two bundled concerns, one migration:

Layer 1 — honest dates:
- authority_documents.decision_date becomes nullable. The ingest now
  returns None when the PDF has no parseable date rather than
  synthesising Jan 1 of the S3-prefix year (which produced 73 %
  fake dates across the pre-fix corpus).

Layer 2 — structured extraction (matches the external-partner
"typed chunks + case graph" shape):
- authority_documents gains ``case_number``, ``judges_json``,
  ``parties_json``, ``advocates_json``, ``sections_cited_json``,
  ``outcome_label``, ``structured_version``.
- authority_document_chunks gains ``chunk_role``,
  ``sections_cited_json``, ``authorities_cited_json``,
  ``outcome_tag``, ``related_chunk_ids_json``.

All new columns are nullable so the backfill can run lazily.
``structured_version`` lets a future prompt-tweak invalidate
just the rows that need re-extraction.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260419_0001"
down_revision = "20260418_0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Layer 1: decision_date → nullable.
    with op.batch_alter_table("authority_documents") as batch_op:
        batch_op.alter_column(
            "decision_date",
            existing_type=sa.Date(),
            nullable=True,
        )

        # Layer 2: structured extraction columns on the doc.
        batch_op.add_column(sa.Column("case_number", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("judges_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("parties_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("advocates_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("sections_cited_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("outcome_label", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("structured_version", sa.Integer(), nullable=True))

    # Layer 2: structured extraction columns on each chunk.
    with op.batch_alter_table("authority_document_chunks") as batch_op:
        batch_op.add_column(sa.Column("chunk_role", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("sections_cited_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("authorities_cited_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("outcome_tag", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("related_chunk_ids_json", sa.Text(), nullable=True))
        batch_op.create_index(
            "ix_authority_document_chunks_chunk_role",
            ["chunk_role"],
        )


def downgrade() -> None:
    with op.batch_alter_table("authority_document_chunks") as batch_op:
        batch_op.drop_index("ix_authority_document_chunks_chunk_role")
        batch_op.drop_column("related_chunk_ids_json")
        batch_op.drop_column("outcome_tag")
        batch_op.drop_column("authorities_cited_json")
        batch_op.drop_column("sections_cited_json")
        batch_op.drop_column("chunk_role")

    with op.batch_alter_table("authority_documents") as batch_op:
        batch_op.drop_column("structured_version")
        batch_op.drop_column("outcome_label")
        batch_op.drop_column("sections_cited_json")
        batch_op.drop_column("advocates_json")
        batch_op.drop_column("parties_json")
        batch_op.drop_column("judges_json")
        batch_op.drop_column("case_number")
        batch_op.alter_column(
            "decision_date",
            existing_type=sa.Date(),
            nullable=False,
        )
