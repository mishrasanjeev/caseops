"""Proceeding sheet intelligence signals.

Revision ID: 20260511_0004
Revises: 20260511_0003
Create Date: 2026-05-11
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260511_0004"
down_revision = "20260511_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matter_proceeding_signals",
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
            "court_order_id",
            sa.String(length=36),
            sa.ForeignKey("matter_court_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sync_run_id",
            sa.String(length=36),
            sa.ForeignKey("matter_court_sync_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("signal_text", sa.Text(), nullable=False),
        sa.Column("action_required", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("hearing_on", sa.Date(), nullable=True),
        sa.Column("order_kind", sa.String(length=40), nullable=True),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("source_snippet", sa.Text(), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=32),
            nullable=False,
            server_default="review_required",
        ),
        sa.Column(
            "generated_task_id",
            sa.String(length=36),
            sa.ForeignKey("matter_tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "generated_deadline_id",
            sa.String(length=36),
            sa.ForeignKey("matter_deadlines.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "extraction_method",
            sa.String(length=32),
            nullable=False,
            server_default="deterministic",
        ),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
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
            "company_id",
            "matter_id",
            "court_order_id",
            "dedupe_key",
            name="uq_matter_proceeding_signal_order_key",
        ),
    )
    for column in (
        "company_id",
        "matter_id",
        "court_order_id",
        "sync_run_id",
        "signal_type",
        "due_on",
        "hearing_on",
        "review_status",
        "generated_task_id",
        "generated_deadline_id",
        "source_hash",
        "dedupe_key",
    ):
        op.create_index(
            f"ix_matter_proceeding_signals_{column}",
            "matter_proceeding_signals",
            [column],
        )


def downgrade() -> None:
    for column in (
        "dedupe_key",
        "source_hash",
        "generated_deadline_id",
        "generated_task_id",
        "review_status",
        "hearing_on",
        "due_on",
        "signal_type",
        "sync_run_id",
        "court_order_id",
        "matter_id",
        "company_id",
    ):
        op.drop_index(
            f"ix_matter_proceeding_signals_{column}",
            table_name="matter_proceeding_signals",
        )
    op.drop_table("matter_proceeding_signals")
