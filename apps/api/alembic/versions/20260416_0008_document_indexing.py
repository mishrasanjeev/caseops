"""Add document processing metadata and chunk indexes."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0008"
down_revision = "20260416_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matter_attachments",
        sa.Column("processing_status", sa.String(length=24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("extracted_char_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("matter_attachments", sa.Column("extraction_error", sa.Text(), nullable=True))
    op.add_column("matter_attachments", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "matter_attachments",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "contract_attachments",
        sa.Column("processing_status", sa.String(length=24), nullable=False, server_default="pending"),
    )
    op.add_column(
        "contract_attachments",
        sa.Column("extracted_char_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("contract_attachments", sa.Column("extraction_error", sa.Text(), nullable=True))
    op.add_column("contract_attachments", sa.Column("extracted_text", sa.Text(), nullable=True))
    op.add_column(
        "contract_attachments",
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "matter_attachment_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["matter_attachments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attachment_id", "chunk_index", name="uq_matter_attachment_chunk_index"),
    )
    op.create_index(
        op.f("ix_matter_attachment_chunks_attachment_id"),
        "matter_attachment_chunks",
        ["attachment_id"],
        unique=False,
    )

    op.create_table(
        "contract_attachment_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attachment_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attachment_id"], ["contract_attachments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attachment_id",
            "chunk_index",
            name="uq_contract_attachment_chunk_index",
        ),
    )
    op.create_index(
        op.f("ix_contract_attachment_chunks_attachment_id"),
        "contract_attachment_chunks",
        ["attachment_id"],
        unique=False,
    )

def downgrade() -> None:
    op.drop_index(
        op.f("ix_contract_attachment_chunks_attachment_id"),
        table_name="contract_attachment_chunks",
    )
    op.drop_table("contract_attachment_chunks")
    op.drop_index(
        op.f("ix_matter_attachment_chunks_attachment_id"),
        table_name="matter_attachment_chunks",
    )
    op.drop_table("matter_attachment_chunks")

    op.drop_column("contract_attachments", "processed_at")
    op.drop_column("contract_attachments", "extracted_text")
    op.drop_column("contract_attachments", "extraction_error")
    op.drop_column("contract_attachments", "extracted_char_count")
    op.drop_column("contract_attachments", "processing_status")

    op.drop_column("matter_attachments", "processed_at")
    op.drop_column("matter_attachments", "extracted_text")
    op.drop_column("matter_attachments", "extraction_error")
    op.drop_column("matter_attachments", "extracted_char_count")
    op.drop_column("matter_attachments", "processing_status")
