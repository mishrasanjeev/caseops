"""gmail mailbox sync foundation.

Revision ID: 20260608_0002
Revises: 20260608_0001
Create Date: 2026-06-08 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260608_0002"
down_revision = "20260608_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _idx(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_idx(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.create_table(
        "user_mailbox_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("provider_account_id", sa.String(length=255), nullable=True),
        sa.Column("display_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("encrypted_token_ref", sa.Text(), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column("last_history_id", sa.String(length=120), nullable=True),
        sa.Column("watch_resource_id", sa.String(length=255), nullable=True),
        sa.Column("watch_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_import_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["company_memberships.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            "provider",
            name="uq_mailbox_connections_company_membership_provider",
        ),
    )
    for column in ("company_id", "membership_id", "status"):
        _idx("user_mailbox_connections", column)

    op.create_table(
        "mailbox_message_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("mailbox_connection_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=True),
        sa.Column("communication_id", sa.String(length=36), nullable=True),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("provider_thread_id", sa.String(length=255), nullable=True),
        sa.Column("history_id", sa.String(length=120), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("sender_email_hash", sa.String(length=64), nullable=True),
        sa.Column("sender_name", sa.String(length=255), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("snippet", sa.String(length=1000), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_letter_reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mailbox_connection_id"],
            ["user_mailbox_connections.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["communication_id"],
            ["communications.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mailbox_connection_id",
            "provider_message_id",
            name="uq_mailbox_message_import_connection_message",
        ),
    )
    for column in (
        "company_id",
        "mailbox_connection_id",
        "matter_id",
        "communication_id",
        "provider_message_id",
        "status",
    ):
        _idx("mailbox_message_imports", column)

    op.create_table(
        "mailbox_attachment_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("message_import_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=True),
        sa.Column("provider_attachment_ref_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_provider_attachment_ref", sa.Text(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("imported_attachment_id", sa.String(length=36), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["message_import_id"],
            ["mailbox_message_imports.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["imported_attachment_id"],
            ["matter_attachments.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_import_id",
            "provider_attachment_ref_hash",
            name="uq_mailbox_attachment_candidate_message_ref",
        ),
    )
    for column in (
        "company_id",
        "message_import_id",
        "matter_id",
        "imported_attachment_id",
        "status",
    ):
        _idx("mailbox_attachment_candidates", column)

    op.create_table(
        "mailbox_webhook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=True),
        sa.Column("mailbox_connection_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=24), nullable=False),
        sa.Column("history_id", sa.String(length=120), nullable=False),
        sa.Column("email_address_hash", sa.String(length=64), nullable=True),
        sa.Column("raw_payload_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["mailbox_connection_id"],
            ["user_mailbox_connections.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "history_id",
            "email_address_hash",
            name="uq_mailbox_webhook_provider_history_address",
        ),
    )
    for column in (
        "company_id",
        "mailbox_connection_id",
        "provider",
        "history_id",
        "email_address_hash",
        "status",
    ):
        _idx("mailbox_webhook_events", column)


def downgrade() -> None:
    for column in (
        "company_id",
        "mailbox_connection_id",
        "provider",
        "history_id",
        "email_address_hash",
        "status",
    ):
        _drop_idx("mailbox_webhook_events", column)
    op.drop_table("mailbox_webhook_events")

    for column in (
        "company_id",
        "message_import_id",
        "matter_id",
        "imported_attachment_id",
        "status",
    ):
        _drop_idx("mailbox_attachment_candidates", column)
    op.drop_table("mailbox_attachment_candidates")

    for column in (
        "company_id",
        "mailbox_connection_id",
        "matter_id",
        "communication_id",
        "provider_message_id",
        "status",
    ):
        _drop_idx("mailbox_message_imports", column)
    op.drop_table("mailbox_message_imports")

    for column in ("company_id", "membership_id", "status"):
        _drop_idx("user_mailbox_connections", column)
    op.drop_table("user_mailbox_connections")

