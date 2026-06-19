"""Affidavit hearing-prep intelligence.

Revision ID: 20260511_0005
Revises: 20260511_0004
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0005"
down_revision = "20260511_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "affidavit_intelligence_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_run_id",
            sa.String(length=36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="no_findings",
        ),
        sa.Column(
            "extraction_method",
            sa.String(length=32),
            nullable=False,
            server_default="deterministic",
        ),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("missing_data_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("disclaimer", sa.Text(), nullable=False),
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
    )
    for column in (
        "company_id",
        "matter_id",
        "attachment_id",
        "model_run_id",
        "created_by_membership_id",
        "status",
        "source_hash",
    ):
        op.create_index(
            f"ix_affidavit_intelligence_runs_{column}",
            "affidavit_intelligence_runs",
            [column],
        )

    op.create_table(
        "affidavit_statements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_intelligence_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_chunk_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachment_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_chunk_index", sa.Integer(), nullable=True),
        sa.Column("page_reference", sa.String(length=80), nullable=True),
        sa.Column("statement_type", sa.String(length=40), nullable=False),
        sa.Column("statement_text", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column("dedupe_key", sa.String(length=80), nullable=False),
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
            "run_id",
            "dedupe_key",
            name="uq_affidavit_statement_run_key",
        ),
    )
    for column in (
        "run_id",
        "company_id",
        "matter_id",
        "attachment_id",
        "source_chunk_id",
        "statement_type",
        "review_status",
        "dedupe_key",
    ):
        op.create_index(
            f"ix_affidavit_statements_{column}",
            "affidavit_statements",
            [column],
        )

    op.create_table(
        "affidavit_questions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_intelligence_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "statement_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_chunk_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachment_chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_chunk_index", sa.Integer(), nullable=True),
        sa.Column("page_reference", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column("dedupe_key", sa.String(length=80), nullable=False),
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
            "run_id",
            "dedupe_key",
            name="uq_affidavit_question_run_key",
        ),
    )
    for column in (
        "run_id",
        "company_id",
        "matter_id",
        "attachment_id",
        "statement_id",
        "source_chunk_id",
        "category",
        "review_status",
        "dedupe_key",
    ):
        op.create_index(
            f"ix_affidavit_questions_{column}",
            "affidavit_questions",
            [column],
        )


def downgrade() -> None:
    for column in (
        "dedupe_key",
        "review_status",
        "category",
        "source_chunk_id",
        "statement_id",
        "attachment_id",
        "matter_id",
        "company_id",
        "run_id",
    ):
        op.drop_index(f"ix_affidavit_questions_{column}", table_name="affidavit_questions")
    op.drop_table("affidavit_questions")

    for column in (
        "dedupe_key",
        "review_status",
        "statement_type",
        "source_chunk_id",
        "attachment_id",
        "matter_id",
        "company_id",
        "run_id",
    ):
        op.drop_index(f"ix_affidavit_statements_{column}", table_name="affidavit_statements")
    op.drop_table("affidavit_statements")

    for column in (
        "source_hash",
        "status",
        "created_by_membership_id",
        "model_run_id",
        "attachment_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_affidavit_intelligence_runs_{column}",
            table_name="affidavit_intelligence_runs",
        )
    op.drop_table("affidavit_intelligence_runs")
