"""Embedded passages of verified statute sections (US-010/US-011).

Revision ID: 20261126_0101
Revises: 20261124_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new empty table; its indexes are built on
its own empty columns and its foreign keys reference existing statute keys. No
existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before any DDL, like the
research-answers head below it, so a downgrade through this revision never
changes the schema before a later refusal. The table holds only derived
embeddings of public statute text: to stop semantic statute retrieval, delete
its rows; the statute index job rebuilds them.

On PostgreSQL the chunks also get ``embedding_vector vector(1024)`` and an HNSW
cosine index with the same parameters as authority_document_chunks. SQLite
(tests) keeps the JSON-encoded vector only.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261126_0101"
down_revision = "20261124_0002"
branch_labels = None
depends_on = None

_TABLE = "statute_section_chunks"
EMBEDDING_DIMS = 1024


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == "postgresql"
    if postgres:
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "statute_id",
            sa.String(64),
            sa.ForeignKey("statutes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.String(36),
            sa.ForeignKey("statute_sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_number", sa.String(64), nullable=False),
        sa.Column("section_label", sa.String(500), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("exact_source_version", sa.String(160), nullable=False),
        sa.Column("chunker_version", sa.String(40), nullable=False),
        sa.Column("embedded_text_sha256", sa.String(64), nullable=False),
        sa.Column("embedding_model", sa.String(120), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "section_id", "chunk_index", name="uq_statute_section_chunks_section_index"
        ),
        sa.CheckConstraint(
            "char_start >= 0 AND char_end > char_start",
            name="ck_statute_section_chunks_span",
        ),
    )
    op.create_index("ix_statute_section_chunks_statute_id", _TABLE, ["statute_id"])
    op.create_index("ix_statute_section_chunks_embedding_model", _TABLE, ["embedding_model"])
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute(f"ALTER TABLE {_TABLE} ADD COLUMN embedding_vector vector({EMBEDDING_DIMS})")
        op.execute(
            "CREATE INDEX ix_statute_section_chunks_embedding_hnsw "
            f"ON {_TABLE} USING hnsw (embedding_vector vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)"
        )


def downgrade() -> None:
    raise RuntimeError("Statute section embeddings are retained; restore-forward only.")
