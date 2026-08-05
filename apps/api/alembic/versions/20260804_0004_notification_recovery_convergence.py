"""Finish notification recovery, lineage, and fail-closed scheduling.

Revision ID: 20260804_0004
Revises: 20260804_0003
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260804_0004"
down_revision = "20260804_0003"
branch_labels = None
depends_on = None


def _event_key(*parts: object) -> str:
    return sha256("|".join(str(part or "") for part in parts).encode()).hexdigest()


def upgrade() -> None:
    with op.batch_alter_table("hearing_reminders") as batch_op:
        batch_op.drop_constraint("uq_hearing_reminders_channel_time", type_="unique")
        batch_op.create_unique_constraint(
            "uq_hearing_reminders_recipient_channel_time",
            ["hearing_id", "recipient_membership_id", "channel", "scheduled_for"],
        )
    with op.batch_alter_table("matter_hearings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "time_status", sa.String(24), nullable=False,
                server_default="time_not_published",
            )
        )
        batch_op.add_column(sa.Column("hearing_time", sa.Time(), nullable=True))
        batch_op.add_column(sa.Column("session_label", sa.String(80), nullable=True))
        batch_op.add_column(
            sa.Column("timezone", sa.String(64), nullable=False, server_default="Asia/Kolkata")
        )
        batch_op.add_column(sa.Column("reminder_policy_json", sa.JSON(), nullable=True))

    with op.batch_alter_table("email_suppressions") as batch_op:
        batch_op.add_column(
            sa.Column("provider", sa.String(40), nullable=False, server_default="sendgrid")
        )
        batch_op.add_column(sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("recovery_action", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "recovered_by_membership_id",
                sa.String(36),
                sa.ForeignKey(
                    "company_memberships.id",
                    name="fk_email_suppressions_recovered_by_membership",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("fallback_sent", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute(sa.text("UPDATE email_suppressions SET first_event_at = created_at"))
    with op.batch_alter_table("email_suppressions") as batch_op:
        batch_op.alter_column(
            "first_event_at", existing_type=sa.DateTime(timezone=True), nullable=False
        )

    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.alter_column(
            "recipient_membership_id", existing_type=sa.String(36), nullable=True
        )
        batch_op.add_column(
            sa.Column(
                "recipient_portal_user_id",
                sa.String(36),
                sa.ForeignKey(
                    "portal_users.id",
                    name="fk_notification_intents_recipient_portal_user",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("recipient_external_ref", sa.String(120), nullable=True))
        batch_op.add_column(
            sa.Column("destination_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(
            sa.Column(
                "escalation_membership_id",
                sa.String(36),
                sa.ForeignKey(
                    "company_memberships.id",
                    name="fk_notification_intents_escalation_membership",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "confidentiality_mode",
                sa.String(24),
                nullable=False,
                server_default="minimal",
            )
        )
        batch_op.add_column(
            sa.Column(
                "superseded_by_intent_id",
                sa.String(36),
                sa.ForeignKey(
                    "notification_delivery_intents.id",
                    name="fk_notification_intents_superseded_by",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "recovery_of_intent_id",
                sa.String(36),
                sa.ForeignKey(
                    "notification_delivery_intents.id",
                    name="fk_notification_intents_recovery_of",
                    ondelete="SET NULL",
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("provider_state_occurred_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_notification_delivery_exactly_one_recipient",
            "(CASE WHEN recipient_membership_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN recipient_portal_user_id IS NOT NULL THEN 1 ELSE 0 END + "
            "CASE WHEN recipient_external_ref IS NOT NULL THEN 1 ELSE 0 END) = 1",
        )
        batch_op.create_index(
            "ix_notification_delivery_intents_recipient_portal_user_id",
            ["recipient_portal_user_id"],
        )
        batch_op.create_index(
            "ix_notification_delivery_intents_scheduled_for", ["scheduled_for"]
        )
        batch_op.create_index(
            "ix_notification_delivery_intents_superseded_by_intent_id",
            ["superseded_by_intent_id"],
        )
        batch_op.create_index(
            "ix_notification_delivery_intents_recovery_of_intent_id",
            ["recovery_of_intent_id"],
        )

    with op.batch_alter_table("notification_delivery_events") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(64), nullable=True))
        batch_op.add_column(
            sa.Column("applied_to_state", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column(
                "received_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            )
        )
    bind = op.get_bind()
    events = bind.execute(
        sa.text(
            "SELECT id, company_id, provider, provider_event_id, event_type, occurred_at "
            "FROM notification_delivery_events"
        )
    ).mappings()
    for event in events:
        key = _event_key(
            event["company_id"], event["provider"],
            event["provider_event_id"] or event["id"], event["event_type"],
            event["occurred_at"],
        )
        bind.execute(
            sa.text(
                "UPDATE notification_delivery_events SET idempotency_key=:key WHERE id=:id"
            ),
            {"key": key, "id": event["id"]},
        )
    with op.batch_alter_table("notification_delivery_events") as batch_op:
        batch_op.alter_column("idempotency_key", existing_type=sa.String(64), nullable=False)
        batch_op.create_unique_constraint(
            "uq_notification_delivery_event_idempotency",
            ["company_id", "provider", "idempotency_key"],
        )

    op.create_table(
        "hearing_reminder_delivery_intents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "hearing_reminder_id",
            sa.String(36),
            sa.ForeignKey("hearing_reminders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "intent_id",
            sa.String(36),
            sa.ForeignKey("notification_delivery_intents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "hearing_reminder_id", "intent_id", name="uq_hearing_reminder_intent"
        ),
    )
    op.create_index(
        "ix_hearing_reminder_delivery_intents_hearing_reminder_id",
        "hearing_reminder_delivery_intents",
        ["hearing_reminder_id"],
    )
    op.create_index(
        "ix_hearing_reminder_delivery_intents_intent_id",
        "hearing_reminder_delivery_intents",
        ["intent_id"],
    )

    reminders = bind.execute(
        sa.text(
            "SELECT id, company_id, matter_id, recipient_membership_id, recipient_email, "
            "channel, scheduled_for, status, provider, provider_message_id, last_error, "
            "attempts, sent_at, delivered_at, created_at, updated_at FROM hearing_reminders"
        )
    ).mappings()
    status_map = {
        "queued": "queued",
        "sent": "sent",
        "delivered": "delivered",
        "failed": "dead_letter",
        "cancelled": "cancelled",
    }
    now = datetime.now(UTC)
    for reminder in reminders:
        intent_id = str(uuid4())
        target_ref = reminder["recipient_membership_id"] or f"legacy:{reminder['id']}"
        idem = _event_key(
            reminder["company_id"], target_ref, reminder["channel"],
            "hearing_upcoming", "hearing_reminder", reminder["id"],
        )
        mapped_status = status_map.get(str(reminder["status"]), "dead_letter")
        bind.execute(
            sa.text(
                "INSERT INTO notification_delivery_intents "
                "(id, company_id, recipient_membership_id, recipient_external_ref, "
                "matter_id, channel, event_type, source_type, source_id, idempotency_key, "
                "status, attempts, max_attempts, scheduled_for, last_error_redacted, "
                "dead_letter_reason, delivered_at, failed_at, schedule_source_type, "
                "schedule_source_id, recipient_snapshot_json, provider_event_id, "
                "dispatch_owner, comparison_status, destination_version, critical, "
                "confidentiality_mode, created_at, updated_at) "
                "VALUES (:id, :company_id, :membership_id, :external_ref, :matter_id, "
                ":channel, 'hearing_upcoming', 'hearing_reminder', :source_id, :idem, "
                ":status, :attempts, 3, :scheduled_for, :error, :dead_letter_reason, "
                ":delivered_at, :failed_at, 'matter_hearing', :source_id, :snapshot, "
                ":provider_event_id, 'durable_intent', 'legacy_backfilled', 1, 1, "
                "'minimal', :created_at, :updated_at)"
            ),
            {
                "id": intent_id,
                "company_id": reminder["company_id"],
                "membership_id": reminder["recipient_membership_id"],
                "external_ref": None if reminder["recipient_membership_id"] else target_ref,
                "matter_id": reminder["matter_id"],
                "channel": reminder["channel"],
                "source_id": reminder["id"],
                "idem": idem,
                "status": mapped_status,
                "attempts": reminder["attempts"] or 0,
                "scheduled_for": reminder["scheduled_for"],
                "error": reminder["last_error"],
                "dead_letter_reason": "legacy_failed" if mapped_status == "dead_letter" else None,
                "delivered_at": reminder["delivered_at"],
                "failed_at": reminder["updated_at"] if mapped_status == "dead_letter" else None,
                "snapshot": json.dumps(
                    {
                        "target_type": (
                            "membership"
                            if reminder["recipient_membership_id"]
                            else "legacy_external"
                        ),
                        "destination": reminder["recipient_email"],
                        "destination_version": 1,
                        "backfilled": True,
                    }
                ),
                "provider_event_id": reminder["provider_message_id"],
                "created_at": reminder["created_at"] or now,
                "updated_at": reminder["updated_at"] or now,
            },
        )
        bind.execute(
            sa.text(
                "INSERT INTO hearing_reminder_delivery_intents "
                "(id, hearing_reminder_id, intent_id, is_primary, created_at) "
                "VALUES (:id, :reminder_id, :intent_id, :primary, :created_at)"
            ),
            {
                "id": str(uuid4()),
                "reminder_id": reminder["id"],
                "intent_id": intent_id,
                "primary": True,
                "created_at": reminder["created_at"] or now,
            },
        )


def downgrade() -> None:
    op.drop_index(
        "ix_hearing_reminder_delivery_intents_intent_id",
        table_name="hearing_reminder_delivery_intents",
    )
    op.drop_index(
        "ix_hearing_reminder_delivery_intents_hearing_reminder_id",
        table_name="hearing_reminder_delivery_intents",
    )
    op.drop_table("hearing_reminder_delivery_intents")
    with op.batch_alter_table("notification_delivery_events") as batch_op:
        batch_op.drop_constraint("uq_notification_delivery_event_idempotency", type_="unique")
        batch_op.drop_column("received_at")
        batch_op.drop_column("applied_to_state")
        batch_op.drop_column("idempotency_key")
    with op.batch_alter_table("notification_delivery_intents") as batch_op:
        batch_op.drop_index("ix_notification_delivery_intents_recovery_of_intent_id")
        batch_op.drop_index("ix_notification_delivery_intents_superseded_by_intent_id")
        batch_op.drop_index("ix_notification_delivery_intents_scheduled_for")
        batch_op.drop_index("ix_notification_delivery_intents_recipient_portal_user_id")
        batch_op.drop_constraint("ck_notification_delivery_exactly_one_recipient", type_="check")
        for column in (
            "provider_state_occurred_at", "recovery_of_intent_id", "superseded_by_intent_id",
            "confidentiality_mode", "escalation_membership_id", "critical",
            "scheduled_for", "destination_version", "recipient_external_ref",
            "recipient_portal_user_id",
        ):
            batch_op.drop_column(column)
        batch_op.alter_column(
            "recipient_membership_id", existing_type=sa.String(36), nullable=False
        )
    with op.batch_alter_table("email_suppressions") as batch_op:
        for column in (
            "fallback_sent", "recovered_by_membership_id", "recovered_at",
            "recovery_action", "first_event_at", "provider",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("matter_hearings") as batch_op:
        for column in (
            "reminder_policy_json", "timezone", "session_label", "hearing_time", "time_status",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("hearing_reminders") as batch_op:
        batch_op.drop_constraint(
            "uq_hearing_reminders_recipient_channel_time", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_hearing_reminders_channel_time",
            ["hearing_id", "channel", "scheduled_for"],
        )
