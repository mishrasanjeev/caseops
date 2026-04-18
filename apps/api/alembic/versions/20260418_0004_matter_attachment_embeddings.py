"""matter attachment embeddings + pgvector

Revision ID: 20260418_0004
Revises: 20260418_0003
Create Date: 2026-04-18 13:00:00

Extends matter_attachment_chunks with the same embedding shape that
authority_document_chunks already carries. Postgres gets the pgvector
column + HNSW cosine index; SQLite keeps embedding_json for tests.

Rationale: today tenant attachments are chunked but not embedded, so
semantic retrieval cannot return passages from a firm's own pleadings
or orders alongside the public corpus. This migration is the schema
half; services/matter_embeddings wires the column into the ingest
pipeline and services/retrieval unions the two sources behind a
tenant filter.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0004"
down_revision = "20260418_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Keep dimension in sync with authority_document_chunks so a single
# embedding provider can populate both without per-caller math.
EMBEDDING_DIMS = 1024


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.add_column(
        "matter_attachment_chunks",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "matter_attachment_chunks",
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
    )
    op.add_column(
        "matter_attachment_chunks",
        sa.Column("embedding_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "matter_attachment_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_matter_attachment_chunks_embedding_model"),
        "matter_attachment_chunks",
        ["embedding_model"],
        unique=False,
    )

    if dialect == "postgresql":
        # pgvector extension is idempotent — already created by
        # 20260417_0003 for authorities; re-running is a no-op.
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"ALTER TABLE matter_attachment_chunks "
            f"ADD COLUMN embedding_vector vector({EMBEDDING_DIMS})"
        )
        op.execute(
            "CREATE INDEX ix_matter_attachment_chunks_embedding_hnsw "
            "ON matter_attachment_chunks "
            "USING hnsw (embedding_vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute(
            "DROP INDEX IF EXISTS ix_matter_attachment_chunks_embedding_hnsw"
        )
        op.execute(
            "ALTER TABLE matter_attachment_chunks DROP COLUMN IF EXISTS embedding_vector"
        )

    op.drop_index(
        op.f("ix_matter_attachment_chunks_embedding_model"),
        table_name="matter_attachment_chunks",
    )
    op.drop_column("matter_attachment_chunks", "embedded_at")
    op.drop_column("matter_attachment_chunks", "embedding_json")
    op.drop_column("matter_attachment_chunks", "embedding_dimensions")
    op.drop_column("matter_attachment_chunks", "embedding_model")
