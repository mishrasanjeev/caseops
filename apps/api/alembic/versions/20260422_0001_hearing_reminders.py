"""MOD-TS-007 Sprint T first slice — hearing_reminders table.

Dark-launched on 2026-04-22: rows accumulate on every hearing create
so the worker can deliver the moment SendGrid (+ optionally MSG91)
credentials land in prod. See BUG-013 and
``memory/feedback_fix_vs_mitigation.md`` for the rationale —
persisting intent separately from delivery means flipping the feature
flag later doesn't need a backfill.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260422_0001"
down_revision = "20260421_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hearing_reminders",
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
            "hearing_id",
            sa.String(length=36),
            sa.ForeignKey("matter_hearings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column("recipient_phone", sa.String(length=40), nullable=True),
        sa.Column(
            "channel",
            sa.String(length=16),
            nullable=False,
            server_default="email",
        ),
        sa.Column(
            "scheduled_for", sa.DateTime(timezone=True), nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_message_id", sa.String(length=120), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "attempts", sa.Integer(), nullable=False, server_default="0",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "delivered_at", sa.DateTime(timezone=True), nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "hearing_id", "channel", "scheduled_for",
            name="uq_hearing_reminders_channel_time",
        ),
    )
    op.create_index(
        "ix_hearing_reminders_company_id",
        "hearing_reminders",
        ["company_id"],
    )
    op.create_index(
        "ix_hearing_reminders_matter_id",
        "hearing_reminders",
        ["matter_id"],
    )
    op.create_index(
        "ix_hearing_reminders_hearing_id",
        "hearing_reminders",
        ["hearing_id"],
    )
    op.create_index(
        "ix_hearing_reminders_scheduled_for",
        "hearing_reminders",
        ["scheduled_for"],
    )
    op.create_index(
        "ix_hearing_reminders_status",
        "hearing_reminders",
        ["status"],
    )
    # Composite index optimised for the worker's hot path:
    # ``WHERE status='queued' AND scheduled_for <= now()`` ORDER BY
    # scheduled_for ASC. Keeps queue drain O(log N) even at a few
    # hundred thousand rows.
    op.create_index(
        "ix_hearing_reminders_queue_pull",
        "hearing_reminders",
        ["status", "scheduled_for"],
    )


def downgrade() -> None:
    for idx in (
        "ix_hearing_reminders_queue_pull",
        "ix_hearing_reminders_status",
        "ix_hearing_reminders_scheduled_for",
        "ix_hearing_reminders_hearing_id",
        "ix_hearing_reminders_matter_id",
        "ix_hearing_reminders_company_id",
    ):
        op.drop_index(idx, table_name="hearing_reminders")
    op.drop_table("hearing_reminders")
