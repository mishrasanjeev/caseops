"""ADP-20 durable Outlook sync retry state.

Revision ID: 20260526_0003
Revises: 20260526_0002
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0003"
down_revision = "20260526_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.add_column(
        "calendar_event_syncs",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("dead_letter_reason", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("durable_last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_calendar_event_syncs_company_status_next_attempt",
        "calendar_event_syncs",
        ["company_id", "sync_status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_calendar_event_syncs_company_status_next_attempt",
        table_name="calendar_event_syncs",
    )
    op.drop_column("calendar_event_syncs", "durable_last_attempt_at")
    op.drop_column("calendar_event_syncs", "dead_letter_reason")
    op.drop_column("calendar_event_syncs", "next_attempt_at")
    op.drop_column("calendar_event_syncs", "max_attempts")
    op.drop_column("calendar_event_syncs", "attempts")
