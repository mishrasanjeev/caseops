"""Litigation intelligence review action ledger.

Revision ID: 20260512_0001
Revises: 20260511_0006
Create Date: 2026-05-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260512_0001"
down_revision = "20260511_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "litigation_intelligence_review_actions",
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
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=160), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status_before", sa.String(length=64), nullable=False),
        sa.Column("status_after", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_type in ("
            "'proceeding_signal', 'affidavit_statement', 'affidavit_question', "
            "'mock_hearing_session', 'mock_hearing_response', 'predictive_signal', "
            "'bench_context'"
            ")",
            name="ck_li_review_actions_item_type",
        ),
        sa.CheckConstraint(
            "source_type in ("
            "'matter_proceeding_signal', 'affidavit_statement', 'affidavit_question', "
            "'mock_hearing_session', 'mock_hearing_response', 'predictive_signal_item', "
            "'predictive_signal_run'"
            ")",
            name="ck_li_review_actions_source_type",
        ),
        sa.CheckConstraint(
            "action in ('mark_reviewed', 'accept', 'reject', 'edit_note')",
            name="ck_li_review_actions_action",
        ),
    )
    for column in (
        "company_id",
        "matter_id",
        "item_type",
        "item_id",
        "source_type",
        "source_id",
        "action",
        "actor_membership_id",
        "created_at",
    ):
        op.create_index(
            f"ix_litigation_intelligence_review_actions_{column}",
            "litigation_intelligence_review_actions",
            [column],
        )


def downgrade() -> None:
    for column in (
        "created_at",
        "actor_membership_id",
        "action",
        "source_id",
        "source_type",
        "item_id",
        "item_type",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_litigation_intelligence_review_actions_{column}",
            table_name="litigation_intelligence_review_actions",
        )
    op.drop_table("litigation_intelligence_review_actions")
