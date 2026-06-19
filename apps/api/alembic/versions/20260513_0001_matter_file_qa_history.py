"""Matter File Q&A history and note exports.

Revision ID: 20260513_0001
Revises: 20260512_0002
Create Date: 2026-05-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260513_0001"
down_revision = "20260512_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "matter_file_qa_entries",
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
            "actor_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer_status", sa.String(length=32), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("answer_mode", sa.String(length=32), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("structured_items_json", sa.JSON(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column(
            "model_run_id",
            sa.String(length=36),
            sa.ForeignKey("model_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "exported_note_id",
            sa.String(length=36),
            sa.ForeignKey("matter_notes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "answer_status IN ("
            "'answered', 'partial_answer', 'insufficient_evidence', "
            "'processing_required', 'no_documents', 'error'"
            ")",
            name="ck_matter_file_qa_entries_answer_status",
        ),
        sa.CheckConstraint(
            "answer_mode IN ("
            "'direct', 'summary', 'sections', 'allegations', "
            "'evidence', 'chronology', 'gaps'"
            ")",
            name="ck_matter_file_qa_entries_answer_mode",
        ),
        sa.CheckConstraint(
            "confidence IN ('high', 'medium', 'low', 'insufficient')",
            name="ck_matter_file_qa_entries_confidence",
        ),
    )
    for column in (
        "company_id",
        "matter_id",
        "actor_membership_id",
        "answer_status",
        "answer_mode",
        "model_run_id",
        "exported_note_id",
        "created_at",
    ):
        op.create_index(
            f"ix_matter_file_qa_entries_{column}",
            "matter_file_qa_entries",
            [column],
        )


def downgrade() -> None:
    for column in (
        "created_at",
        "exported_note_id",
        "model_run_id",
        "answer_mode",
        "answer_status",
        "actor_membership_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_matter_file_qa_entries_{column}",
            table_name="matter_file_qa_entries",
        )
    op.drop_table("matter_file_qa_entries")
