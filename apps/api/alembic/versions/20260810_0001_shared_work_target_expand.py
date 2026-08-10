"""Expand canonical shared-work owners for IP docket targets.

Revision ID: 20260810_0001
Revises: 20260809_0001

This revision is intentionally additive and safe for the previous application
revision.  Legacy Matter writers can continue supplying only ``matter_id``;
the target and tenant columns remain nullable until the new writer is live.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260810_0001"
down_revision = "20260809_0001"
branch_labels = None
depends_on = None


def _add_target_columns(table_name: str, *, add_company: bool) -> None:
    if add_company:
        op.add_column(table_name, sa.Column("company_id", sa.String(36), nullable=True))
        op.create_index(f"ix_{table_name}_company_id", table_name, ["company_id"])
    op.add_column(table_name, sa.Column("ip_docket_id", sa.String(36), nullable=True))
    op.create_index(f"ix_{table_name}_ip_docket_id", table_name, ["ip_docket_id"])
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.alter_column("matter_id", existing_type=sa.String(36), nullable=True)


def upgrade() -> None:
    _add_target_columns("matter_tasks", add_company=True)
    _add_target_columns("matter_hearings", add_company=True)
    _add_target_columns("hearing_reminders", add_company=False)
    _add_target_columns("matter_next_hearing_history", add_company=False)
    _add_target_columns("matter_next_hearing_suggestions", add_company=False)
    _add_target_columns("matter_deadlines", add_company=True)

    op.add_column(
        "matter_hearings", sa.Column("hearing_mode", sa.String(32), nullable=True)
    )
    op.add_column(
        "matter_hearings",
        sa.Column("source", sa.String(40), nullable=False, server_default="manual"),
    )
    op.add_column(
        "matter_hearings", sa.Column("source_ref_type", sa.String(40), nullable=True)
    )
    op.add_column(
        "matter_hearings", sa.Column("source_ref_id", sa.String(120), nullable=True)
    )
    op.add_column(
        "matter_hearings",
        sa.Column("responsible_membership_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_matter_hearings_responsible_membership_id",
        "matter_hearings",
        ["responsible_membership_id"],
    )

    op.add_column(
        "notification_delivery_intents",
        sa.Column("ip_docket_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_notification_delivery_intents_ip_docket_id",
        "notification_delivery_intents",
        ["ip_docket_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_intents_ip_docket_id",
        table_name="notification_delivery_intents",
    )
    op.drop_column("notification_delivery_intents", "ip_docket_id")

    op.drop_index(
        "ix_matter_hearings_responsible_membership_id", table_name="matter_hearings"
    )
    for column in (
        "responsible_membership_id",
        "source_ref_id",
        "source_ref_type",
        "source",
        "hearing_mode",
    ):
        op.drop_column("matter_hearings", column)

    for table_name, had_company in reversed(
        (
            ("matter_tasks", True),
            ("matter_hearings", True),
            ("hearing_reminders", False),
            ("matter_next_hearing_history", False),
            ("matter_next_hearing_suggestions", False),
            ("matter_deadlines", True),
        )
    ):
        with op.batch_alter_table(table_name) as batch_op:
            batch_op.alter_column("matter_id", existing_type=sa.String(36), nullable=False)
        op.drop_index(f"ix_{table_name}_ip_docket_id", table_name=table_name)
        op.drop_column(table_name, "ip_docket_id")
        if had_company:
            op.drop_index(f"ix_{table_name}_company_id", table_name=table_name)
            op.drop_column(table_name, "company_id")
