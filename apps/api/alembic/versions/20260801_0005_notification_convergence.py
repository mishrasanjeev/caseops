"""Extend durable notification intents with linkage, events, and fallback state.

Revision ID: 20260801_0005
Revises: 20260801_0004
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0005"
down_revision = "20260801_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.add_column(sa.Column("schedule_source_type", sa.String(40), nullable=True))
        batch_op.add_column(sa.Column("schedule_source_id", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("recipient_snapshot_json", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("provider_event_id", sa.String(255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "dispatch_owner", sa.String(32), nullable=False, server_default="durable_intent"
            )
        )
        batch_op.add_column(
            sa.Column("comparison_status", sa.String(32), nullable=False, server_default="not_run")
        )
        batch_op.add_column(sa.Column("suppression_reason", sa.String(160), nullable=True))
        batch_op.add_column(
            sa.Column(
                "fallback_intent_id",
                sa.String(36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_notification_intents_fallback_intent",
            "notification_delivery_intents",
            ["fallback_intent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_notification_delivery_intents_fallback_intent_id",
            ["fallback_intent_id"],
        )

    op.create_table(
        "notification_delivery_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "intent_id",
            sa.String(36),
            sa.ForeignKey("notification_delivery_intents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=True),
        sa.Column("provider_event_id", sa.String(255), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("error_redacted", sa.String(500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "company_id",
            "provider",
            "provider_event_id",
            name="uq_notification_delivery_provider_event",
        ),
    )
    op.create_index(
        "ix_notification_delivery_events_intent_time",
        "notification_delivery_events",
        ["intent_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_events_intent_time",
        table_name="notification_delivery_events",
    )
    op.drop_table("notification_delivery_events")
    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.drop_index("ix_notification_delivery_intents_fallback_intent_id")
        batch_op.drop_constraint(
            "fk_notification_intents_fallback_intent",
            type_="foreignkey",
        )
        batch_op.drop_column("fallback_intent_id")
        batch_op.drop_column("suppression_reason")
        batch_op.drop_column("comparison_status")
        batch_op.drop_column("dispatch_owner")
        batch_op.drop_column("provider_event_id")
        batch_op.drop_column("recipient_snapshot_json")
        batch_op.drop_column("schedule_source_id")
        batch_op.drop_column("schedule_source_type")
