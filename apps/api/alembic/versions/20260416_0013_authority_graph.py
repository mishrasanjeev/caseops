"""add authority graph

Revision ID: 20260416_0013
Revises: 20260416_0012
Create Date: 2026-04-16 23:59:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0013"
down_revision = "20260416_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authority_citations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_authority_document_id", sa.String(length=36), nullable=False),
        sa.Column("cited_authority_document_id", sa.String(length=36), nullable=True),
        sa.Column("citation_text", sa.String(length=255), nullable=False),
        sa.Column("normalized_reference", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cited_authority_document_id"],
            ["authority_documents.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_authority_document_id"],
            ["authority_documents.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_authority_document_id",
            "normalized_reference",
            name="uq_authority_citation_reference",
        ),
    )
    op.create_index(
        "ix_authority_citations_cited_authority_document_id",
        "authority_citations",
        ["cited_authority_document_id"],
        unique=False,
    )
    op.create_index(
        "ix_authority_citations_normalized_reference",
        "authority_citations",
        ["normalized_reference"],
        unique=False,
    )
    op.create_index(
        "ix_authority_citations_source_authority_document_id",
        "authority_citations",
        ["source_authority_document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_citations_source_authority_document_id",
        table_name="authority_citations",
    )
    op.drop_index(
        "ix_authority_citations_normalized_reference",
        table_name="authority_citations",
    )
    op.drop_index(
        "ix_authority_citations_cited_authority_document_id",
        table_name="authority_citations",
    )
    op.drop_table("authority_citations")
