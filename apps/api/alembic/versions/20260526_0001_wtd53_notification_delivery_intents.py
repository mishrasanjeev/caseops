"""WTD-5.3 durable notification delivery intents.

Revision ID: 20260526_0001
Revises: 20260524_0005
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0001"
down_revision = "20260524_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "notification_delivery_intents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "recipient_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "notification_rule_id",
            sa.String(length=36),
            sa.ForeignKey("notification_rules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "in_app_notification_id",
            sa.String(length=36),
            sa.ForeignKey("in_app_notifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column("dead_letter_reason", sa.String(length=160), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("body", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
            "idempotency_key",
            name="uq_notification_delivery_intent_idempotency",
        ),
    )
    op.create_index(
        "ix_notification_delivery_intents_company_id",
        "notification_delivery_intents",
        ["company_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_recipient_membership_id",
        "notification_delivery_intents",
        ["recipient_membership_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_matter_id",
        "notification_delivery_intents",
        ["matter_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_notification_rule_id",
        "notification_delivery_intents",
        ["notification_rule_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_in_app_notification_id",
        "notification_delivery_intents",
        ["in_app_notification_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_channel",
        "notification_delivery_intents",
        ["channel"],
    )
    op.create_index(
        "ix_notification_delivery_intents_event_type",
        "notification_delivery_intents",
        ["event_type"],
    )
    op.create_index(
        "ix_notification_delivery_intents_source_type",
        "notification_delivery_intents",
        ["source_type"],
    )
    op.create_index(
        "ix_notification_delivery_intents_source_id",
        "notification_delivery_intents",
        ["source_id"],
    )
    op.create_index(
        "ix_notification_delivery_intents_status",
        "notification_delivery_intents",
        ["status"],
    )
    op.create_index(
        "ix_notification_delivery_intents_next_attempt_at",
        "notification_delivery_intents",
        ["next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_intents_next_attempt_at",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_status",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_source_id",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_source_type",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_event_type",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_channel",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_in_app_notification_id",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_notification_rule_id",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_matter_id",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_recipient_membership_id",
        table_name="notification_delivery_intents",
    )
    op.drop_index(
        "ix_notification_delivery_intents_company_id",
        table_name="notification_delivery_intents",
    )
    op.drop_table("notification_delivery_intents")
