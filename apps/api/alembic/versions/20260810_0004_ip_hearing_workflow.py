"""Add complete hearing logistics to the canonical hearing owner.

Revision ID: 20260810_0004
Revises: 20260810_0003
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0004"
down_revision = "20260810_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matter_hearings") as batch_op:
        batch_op.add_column(sa.Column("location_text", sa.String(500), nullable=True))
        batch_op.add_column(sa.Column("meeting_url", sa.String(2048), nullable=True))
        batch_op.add_column(sa.Column("attendee_membership_ids_json", sa.JSON(), nullable=True))
    with op.batch_alter_table("hearing_reminders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "schedule_generation",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.drop_constraint(
            "uq_hearing_reminders_recipient_channel_time",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_hearing_reminders_recipient_channel_time_generation",
            [
                "hearing_id",
                "recipient_membership_id",
                "channel",
                "scheduled_for",
                "schedule_generation",
            ],
        )


def downgrade() -> None:
    # A replacement generation may intentionally share the same delivery time
    # as a cancelled predecessor. Coalesce those rows before restoring the
    # legacy uniqueness contract.
    op.execute(
        sa.text(
            "DELETE FROM hearing_reminders WHERE id NOT IN ("
            "SELECT MIN(id) FROM hearing_reminders GROUP BY "
            "hearing_id, recipient_membership_id, channel, scheduled_for)"
        )
    )
    with op.batch_alter_table("hearing_reminders") as batch_op:
        batch_op.drop_constraint(
            "uq_hearing_reminders_recipient_channel_time_generation",
            type_="unique",
        )
        batch_op.create_unique_constraint(
            "uq_hearing_reminders_recipient_channel_time",
            ["hearing_id", "recipient_membership_id", "channel", "scheduled_for"],
        )
        batch_op.drop_column("schedule_generation")
    with op.batch_alter_table("matter_hearings") as batch_op:
        batch_op.drop_column("attendee_membership_ids_json")
        batch_op.drop_column("meeting_url")
        batch_op.drop_column("location_text")
