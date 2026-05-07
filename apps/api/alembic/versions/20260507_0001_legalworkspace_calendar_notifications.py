"""LegalWorkspace LW-S10 calendar sync and notifications.

Revision ID: 20260507_0001
Revises: 20260506_0004
Create Date: 2026-05-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260507_0001"
down_revision = "20260506_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_calendar_connections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
        sa.Column("display_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("encrypted_token_ref", sa.Text(), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_calendar_connections_company_membership_provider",
        ),
    )
    op.create_index(
        "ix_user_calendar_connections_company_id",
        "user_calendar_connections",
        ["company_id"],
    )
    op.create_index(
        "ix_user_calendar_connections_membership_id",
        "user_calendar_connections",
        ["membership_id"],
    )
    op.create_index(
        "ix_user_calendar_connections_status",
        "user_calendar_connections",
        ["status"],
    )

    op.create_table(
        "calendar_event_syncs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "calendar_connection_id",
            sa.String(length=36),
            sa.ForeignKey("user_calendar_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
        sa.Column("sync_status", sa.String(length=24), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "calendar_connection_id",
            "source_type",
            "source_id",
            name="uq_calendar_event_sync_connection_source",
        ),
    )
    op.create_index("ix_calendar_event_syncs_company_id", "calendar_event_syncs", ["company_id"])
    op.create_index(
        "ix_calendar_event_syncs_calendar_connection_id",
        "calendar_event_syncs",
        ["calendar_connection_id"],
    )
    op.create_index("ix_calendar_event_syncs_source_type", "calendar_event_syncs", ["source_type"])
    op.create_index("ix_calendar_event_syncs_source_id", "calendar_event_syncs", ["source_id"])
    op.create_index("ix_calendar_event_syncs_sync_status", "calendar_event_syncs", ["sync_status"])

    op.create_table(
        "notification_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scope_type", sa.String(length=24), nullable=False),
        sa.Column("scope_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("channels_json", sa.JSON(), nullable=True),
        sa.Column("offset_minutes", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_notification_rules_company_id", "notification_rules", ["company_id"])
    op.create_index("ix_notification_rules_scope_type", "notification_rules", ["scope_type"])
    op.create_index("ix_notification_rules_scope_id", "notification_rules", ["scope_id"])
    op.create_index("ix_notification_rules_event_type", "notification_rules", ["event_type"])
    op.create_index(
        "ix_notification_rules_created_by_membership_id",
        "notification_rules",
        ["created_by_membership_id"],
    )

    op.create_table(
        "in_app_notifications",
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
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "recipient_membership_id",
            "event_type",
            "source_type",
            "source_id",
            name="uq_in_app_notification_recipient_source",
        ),
    )
    op.create_index("ix_in_app_notifications_company_id", "in_app_notifications", ["company_id"])
    op.create_index(
        "ix_in_app_notifications_recipient_membership_id",
        "in_app_notifications",
        ["recipient_membership_id"],
    )
    op.create_index("ix_in_app_notifications_event_type", "in_app_notifications", ["event_type"])
    op.create_index("ix_in_app_notifications_matter_id", "in_app_notifications", ["matter_id"])
    op.create_index("ix_in_app_notifications_status", "in_app_notifications", ["status"])


def downgrade() -> None:
    op.drop_index("ix_in_app_notifications_status", table_name="in_app_notifications")
    op.drop_index("ix_in_app_notifications_matter_id", table_name="in_app_notifications")
    op.drop_index("ix_in_app_notifications_event_type", table_name="in_app_notifications")
    op.drop_index(
        "ix_in_app_notifications_recipient_membership_id",
        table_name="in_app_notifications",
    )
    op.drop_index("ix_in_app_notifications_company_id", table_name="in_app_notifications")
    op.drop_table("in_app_notifications")

    op.drop_index(
        "ix_notification_rules_created_by_membership_id",
        table_name="notification_rules",
    )
    op.drop_index("ix_notification_rules_event_type", table_name="notification_rules")
    op.drop_index("ix_notification_rules_scope_id", table_name="notification_rules")
    op.drop_index("ix_notification_rules_scope_type", table_name="notification_rules")
    op.drop_index("ix_notification_rules_company_id", table_name="notification_rules")
    op.drop_table("notification_rules")

    op.drop_index("ix_calendar_event_syncs_sync_status", table_name="calendar_event_syncs")
    op.drop_index("ix_calendar_event_syncs_source_id", table_name="calendar_event_syncs")
    op.drop_index("ix_calendar_event_syncs_source_type", table_name="calendar_event_syncs")
    op.drop_index(
        "ix_calendar_event_syncs_calendar_connection_id",
        table_name="calendar_event_syncs",
    )
    op.drop_index("ix_calendar_event_syncs_company_id", table_name="calendar_event_syncs")
    op.drop_table("calendar_event_syncs")

    op.drop_index("ix_user_calendar_connections_status", table_name="user_calendar_connections")
    op.drop_index(
        "ix_user_calendar_connections_membership_id",
        table_name="user_calendar_connections",
    )
    op.drop_index(
        "ix_user_calendar_connections_company_id",
        table_name="user_calendar_connections",
    )
    op.drop_table("user_calendar_connections")
