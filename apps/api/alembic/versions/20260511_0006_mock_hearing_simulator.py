"""Mock hearing simulator V1.

Revision ID: 20260511_0006
Revises: 20260511_0005
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0006"
down_revision = "20260511_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "mock_hearing_sessions",
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
            "source_affidavit_run_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_intelligence_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "mode",
            sa.String(length=40),
            nullable=False,
            server_default="client_preparation",
        ),
        sa.Column("participant_label", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column("disclaimer", sa.Text(), nullable=False),
        sa.Column("scorecard_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("total_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("answered_questions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "unsupported_assertion_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "missing_document_reference_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("contradiction_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("review_required_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("average_response_seconds", sa.Float(), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        "source_affidavit_run_id",
        "created_by_membership_id",
        "mode",
        "status",
        "review_status",
    ):
        op.create_index(
            f"ix_mock_hearing_sessions_{column}",
            "mock_hearing_sessions",
            [column],
        )

    op.create_table(
        "mock_hearing_questions",
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
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("mock_hearing_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_affidavit_run_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_intelligence_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_affidavit_question_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_affidavit_statement_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_statements.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="SET NULL"),
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
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("difficulty_label", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
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
            "session_id",
            "turn_index",
            name="uq_mock_hearing_question_session_turn",
        ),
    )
    for column in (
        "company_id",
        "matter_id",
        "session_id",
        "source_affidavit_run_id",
        "source_affidavit_question_id",
        "source_affidavit_statement_id",
        "source_attachment_id",
        "source_chunk_id",
        "category",
        "status",
    ):
        op.create_index(
            f"ix_mock_hearing_questions_{column}",
            "mock_hearing_questions",
            [column],
        )

    op.create_table(
        "mock_hearing_responses",
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
            "session_id",
            sa.String(length=36),
            sa.ForeignKey("mock_hearing_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.String(length=36),
            sa.ForeignKey("mock_hearing_questions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_affidavit_question_id",
            sa.String(length=36),
            sa.ForeignKey("affidavit_questions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("response_text", sa.Text(), nullable=False),
        sa.Column("response_word_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=True),
        sa.Column("answered_question", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "consistency_with_affidavit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "unsupported_assertion_added",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "missing_document_reference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "contradiction_with_source",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("response_completeness", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("feedback_text", sa.Text(), nullable=False),
        sa.Column("evaluation_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("source_quote", sa.Text(), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="review_required",
        ),
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
        "session_id",
        "question_id",
        "source_affidavit_question_id",
        "review_status",
    ):
        op.create_index(
            f"ix_mock_hearing_responses_{column}",
            "mock_hearing_responses",
            [column],
        )


def downgrade() -> None:
    for column in (
        "review_status",
        "source_affidavit_question_id",
        "question_id",
        "session_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_mock_hearing_responses_{column}",
            table_name="mock_hearing_responses",
        )
    op.drop_table("mock_hearing_responses")

    for column in (
        "status",
        "category",
        "source_chunk_id",
        "source_attachment_id",
        "source_affidavit_statement_id",
        "source_affidavit_question_id",
        "source_affidavit_run_id",
        "session_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_mock_hearing_questions_{column}",
            table_name="mock_hearing_questions",
        )
    op.drop_table("mock_hearing_questions")

    for column in (
        "review_status",
        "status",
        "mode",
        "created_by_membership_id",
        "source_affidavit_run_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_mock_hearing_sessions_{column}",
            table_name="mock_hearing_sessions",
        )
    op.drop_table("mock_hearing_sessions")
