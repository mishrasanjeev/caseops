"""add authority corpus

Revision ID: 20260416_0012
Revises: 20260416_0011
Create Date: 2026-04-16 23:20:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0012"
down_revision = "20260416_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authority_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("adapter_name", sa.String(length=120), nullable=False),
        sa.Column("court_name", sa.String(length=255), nullable=False),
        sa.Column("forum_level", sa.String(length=40), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("case_reference", sa.String(length=255), nullable=True),
        sa.Column("bench_name", sa.String(length=255), nullable=True),
        sa.Column("neutral_citation", sa.String(length=255), nullable=True),
        sa.Column("decision_date", sa.Date(), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("document_text", sa.Text(), nullable=True),
        sa.Column(
            "extracted_char_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_key", name="uq_authority_document_canonical_key"),
    )
    op.create_index(
        "ix_authority_documents_case_reference",
        "authority_documents",
        ["case_reference"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_court_name",
        "authority_documents",
        ["court_name"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_decision_date",
        "authority_documents",
        ["decision_date"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_document_type",
        "authority_documents",
        ["document_type"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_forum_level",
        "authority_documents",
        ["forum_level"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_source",
        "authority_documents",
        ["source"],
        unique=False,
    )
    op.create_index(
        "ix_authority_documents_source_reference",
        "authority_documents",
        ["source_reference"],
        unique=False,
    )

    op.create_table(
        "authority_document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("authority_document_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "token_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["authority_document_id"],
            ["authority_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "authority_document_id",
            "chunk_index",
            name="uq_authority_document_chunk_index",
        ),
    )
    op.create_index(
        "ix_authority_document_chunks_authority_document_id",
        "authority_document_chunks",
        ["authority_document_id"],
        unique=False,
    )

    op.create_table(
        "authority_ingestion_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("requested_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("adapter_name", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column(
            "imported_document_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_authority_ingestion_runs_requested_by_membership_id",
        "authority_ingestion_runs",
        ["requested_by_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_authority_ingestion_runs_source",
        "authority_ingestion_runs",
        ["source"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_ingestion_runs_source",
        table_name="authority_ingestion_runs",
    )
    op.drop_index(
        "ix_authority_ingestion_runs_requested_by_membership_id",
        table_name="authority_ingestion_runs",
    )
    op.drop_table("authority_ingestion_runs")

    op.drop_index(
        "ix_authority_document_chunks_authority_document_id",
        table_name="authority_document_chunks",
    )
    op.drop_table("authority_document_chunks")

    op.drop_index(
        "ix_authority_documents_source_reference",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_source",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_forum_level",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_document_type",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_decision_date",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_court_name",
        table_name="authority_documents",
    )
    op.drop_index(
        "ix_authority_documents_case_reference",
        table_name="authority_documents",
    )
    op.drop_table("authority_documents")
