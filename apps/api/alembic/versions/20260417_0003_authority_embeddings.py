"""authority embeddings + pgvector

Revision ID: 20260417_0003
Revises: 20260417_0002
Create Date: 2026-04-17 02:00:00

Makes authority_document_chunks embedding-aware.

- On Postgres: CREATE EXTENSION vector, add `embedding_vector vector(N)`,
  build an HNSW index for cosine search, and a btree on embedding_model
  for filtering by provenance.
- On SQLite (used in tests only): we do not have pgvector, so the
  embedding is stored as JSON in `embedding_json` and retrieval in test
  paths computes cosine in Python. Alembic runs the Postgres branch only
  on Postgres connections.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260417_0003"
down_revision = "20260417_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default embedding dimension. The production model we target (BAAI/bge-base-en-v1.5)
# emits 768-dim vectors; Voyage's voyage-3-law emits 1024. We pick 1024 here
# so either provider fits — callers pad to the column size.
EMBEDDING_DIMS = 1024


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    op.add_column(
        "authority_document_chunks",
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "authority_document_chunks",
        sa.Column("embedding_dimensions", sa.Integer(), nullable=True),
    )
    op.add_column(
        "authority_document_chunks",
        sa.Column("embedding_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "authority_document_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_authority_document_chunks_embedding_model"),
        "authority_document_chunks",
        ["embedding_model"],
        unique=False,
    )

    if dialect == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(
            f"ALTER TABLE authority_document_chunks "
            f"ADD COLUMN embedding_vector vector({EMBEDDING_DIMS})"
        )
        # HNSW with cosine — legal retrieval tends to want direction similarity
        # more than magnitude. Parameters follow pgvector defaults.
        op.execute(
            "CREATE INDEX ix_authority_document_chunks_embedding_hnsw "
            "ON authority_document_chunks "
            "USING hnsw (embedding_vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_authority_document_chunks_embedding_hnsw")
        op.execute("ALTER TABLE authority_document_chunks DROP COLUMN IF EXISTS embedding_vector")

    op.drop_index(
        op.f("ix_authority_document_chunks_embedding_model"),
        table_name="authority_document_chunks",
    )
    op.drop_column("authority_document_chunks", "embedded_at")
    op.drop_column("authority_document_chunks", "embedding_json")
    op.drop_column("authority_document_chunks", "embedding_dimensions")
    op.drop_column("authority_document_chunks", "embedding_model")
