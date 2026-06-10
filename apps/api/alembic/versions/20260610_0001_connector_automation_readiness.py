"""Connector automation and communication readiness.

Revision ID: 20260610_0001
Revises: 20260609_0002
Create Date: 2026-06-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260610_0001"
down_revision = "20260609_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _idx(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_idx(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.create_table(
        "connector_health_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column(
            "account_ref_hash", sa.String(length=64), nullable=False, server_default="tenant"
        ),
        sa.Column("account_label", sa.String(length=120), nullable=True),
        sa.Column(
            "configured_state",
            sa.String(length=32),
            nullable=False,
            server_default="missing_config",
        ),
        sa.Column(
            "connected_state", sa.String(length=32), nullable=False, server_default="disabled"
        ),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("required_scopes_json", sa.JSON(), nullable=True),
        sa.Column("granted_scopes_json", sa.JSON(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("token_refresh_status", sa.String(length=40), nullable=True),
        sa.Column("webhook_status", sa.String(length=40), nullable=True),
        sa.Column("polling_status", sa.String(length=40), nullable=True),
        sa.Column("rate_limit_status", sa.String(length=40), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_reason", sa.String(length=160), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operational_alerts_json", sa.JSON(), nullable=True),
        sa.Column("setup_actions_json", sa.JSON(), nullable=True),
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
            "provider",
            "account_ref_hash",
            name="uq_connector_health_tenant_provider_account",
        ),
    )
    for column in ("company_id", "provider", "configured_state", "connected_state"):
        _idx("connector_health_records", column)

    op.create_table(
        "tenant_microsoft365_configurations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_client_secret_ref", sa.Text(), nullable=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=True),
        sa.Column("redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column(
            "admin_consent_approved", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("scopes_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mail_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("calendar_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("drive_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "last_test_status", sa.String(length=24), nullable=False, server_default="not_run"
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("company_id", name="uq_tenant_microsoft365_config_company"),
    )
    for column in ("company_id", "created_by_membership_id"):
        _idx("tenant_microsoft365_configurations", column)

    op.create_table(
        "drive_sync_controls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="google_drive"),
        sa.Column("allowed_folders_json", sa.JSON(), nullable=True),
        sa.Column("blocked_folders_json", sa.JSON(), nullable=True),
        sa.Column(
            "max_file_size_bytes",
            sa.Integer(),
            nullable=False,
            server_default=str(25 * 1024 * 1024),
        ),
        sa.Column("allowed_mime_types_json", sa.JSON(), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="review_import"),
        sa.Column("auto_import_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
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
            "company_id", "provider", name="uq_drive_sync_controls_tenant_provider"
        ),
    )
    for column in ("company_id", "provider"):
        _idx("drive_sync_controls", column)

    op.create_table(
        "drive_file_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "drive_connection_id",
            sa.String(length=36),
            sa.ForeignKey("user_drive_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default="google_drive"),
        sa.Column("provider_file_id", sa.String(length=255), nullable=False),
        sa.Column(
            "provider_version", sa.String(length=120), nullable=False, server_default="metadata"
        ),
        sa.Column("name", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("owner_display", sa.String(length=255), nullable=True),
        sa.Column("modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("folder_path", sa.String(length=1000), nullable=True),
        sa.Column("web_url", sa.String(length=1000), nullable=True),
        sa.Column(
            "suggested_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column(
            "imported_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
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
            "provider",
            "provider_file_id",
            "provider_version",
            name="uq_drive_file_candidates_provider_version",
        ),
    )
    for column in (
        "company_id",
        "drive_connection_id",
        "provider",
        "provider_file_id",
        "suggested_matter_id",
        "status",
        "imported_attachment_id",
        "linked_matter_id",
    ):
        _idx("drive_file_candidates", column)

    op.create_table(
        "calendar_event_candidates",
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
            sa.ForeignKey("user_calendar_connections.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("i_cal_uid", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("location", sa.String(length=500), nullable=True),
        sa.Column("organizer_display", sa.String(length=255), nullable=True),
        sa.Column("provider_status", sa.String(length=40), nullable=True),
        sa.Column(
            "suggested_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "linked_hearing_id",
            sa.String(length=36),
            sa.ForeignKey("matter_hearings.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("conflict_reason", sa.String(length=160), nullable=True),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
        sa.Column("sync_history_json", sa.JSON(), nullable=True),
        sa.Column(
            "reviewed_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
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
            "provider",
            "provider_event_id",
            name="uq_calendar_event_candidates_provider_event",
        ),
    )
    for column in (
        "company_id",
        "calendar_connection_id",
        "provider",
        "provider_event_id",
        "suggested_matter_id",
        "linked_matter_id",
        "linked_hearing_id",
        "status",
        "reviewed_by_membership_id",
    ):
        _idx("calendar_event_candidates", column)

    op.create_table(
        "inbound_email_aliases",
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
            nullable=True,
        ),
        sa.Column("alias_type", sa.String(length=24), nullable=False, server_default="tenant"),
        sa.Column("alias_address", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="disabled"),
        sa.Column("allowed_senders_json", sa.JSON(), nullable=True),
        sa.Column("allowed_domains_json", sa.JSON(), nullable=True),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column(
            "spam_security_status",
            sa.String(length=40),
            nullable=False,
            server_default="provider_unverified",
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("company_id", "alias_address", name="uq_inbound_alias_tenant_address"),
    )
    for column in (
        "company_id",
        "matter_id",
        "alias_address",
        "status",
        "created_by_membership_id",
    ):
        _idx("inbound_email_aliases", column)

    op.create_table(
        "inbound_email_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alias_id",
            sa.String(length=36),
            sa.ForeignKey("inbound_email_aliases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "matched_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="local_safe"),
        sa.Column("provider_message_id", sa.String(length=255), nullable=False),
        sa.Column("from_address_hash", sa.String(length=64), nullable=True),
        sa.Column("from_display", sa.String(length=255), nullable=True),
        sa.Column("to_addresses_json", sa.JSON(), nullable=True),
        sa.Column("cc_addresses_json", sa.JSON(), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snippet", sa.String(length=1000), nullable=True),
        sa.Column("attachment_metadata_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="new"),
        sa.Column("redacted_failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "linked_matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "communication_id",
            sa.String(length=36),
            sa.ForeignKey("communications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provenance_json", sa.JSON(), nullable=True),
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
            "provider_message_id",
            name="uq_inbound_email_event_tenant_provider_message",
        ),
    )
    for column in (
        "company_id",
        "alias_id",
        "matched_matter_id",
        "provider_message_id",
        "status",
        "linked_matter_id",
        "communication_id",
    ):
        _idx("inbound_email_events", column)

    op.create_table(
        "tenant_notification_preferences",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channels_json", sa.JSON(), nullable=True),
        sa.Column("event_categories_json", sa.JSON(), nullable=True),
        sa.Column(
            "digest_frequency", sa.String(length=24), nullable=False, server_default="immediate"
        ),
        sa.Column("quiet_hours_json", sa.JSON(), nullable=True),
        sa.Column("escalation_rules_json", sa.JSON(), nullable=True),
        sa.Column(
            "external_delivery_policy",
            sa.String(length=32),
            nullable=False,
            server_default="disabled_until_configured",
        ),
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
        sa.UniqueConstraint("company_id", name="uq_tenant_notification_preferences_company"),
    )
    _idx("tenant_notification_preferences", "company_id")

    op.create_table(
        "user_notification_preferences",
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
        sa.Column("channels_json", sa.JSON(), nullable=True),
        sa.Column("event_categories_json", sa.JSON(), nullable=True),
        sa.Column(
            "digest_frequency", sa.String(length=24), nullable=False, server_default="immediate"
        ),
        sa.Column("quiet_hours_json", sa.JSON(), nullable=True),
        sa.Column("escalation_rules_json", sa.JSON(), nullable=True),
        sa.Column("opt_out_categories_json", sa.JSON(), nullable=True),
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
            "company_id", "membership_id", name="uq_user_notification_preferences_membership"
        ),
    )
    for column in ("company_id", "membership_id"):
        _idx("user_notification_preferences", column)


def downgrade() -> None:
    for column in ("company_id", "membership_id"):
        _drop_idx("user_notification_preferences", column)
    op.drop_table("user_notification_preferences")

    _drop_idx("tenant_notification_preferences", "company_id")
    op.drop_table("tenant_notification_preferences")

    for column in (
        "company_id",
        "alias_id",
        "matched_matter_id",
        "provider_message_id",
        "status",
        "linked_matter_id",
        "communication_id",
    ):
        _drop_idx("inbound_email_events", column)
    op.drop_table("inbound_email_events")

    for column in (
        "company_id",
        "matter_id",
        "alias_address",
        "status",
        "created_by_membership_id",
    ):
        _drop_idx("inbound_email_aliases", column)
    op.drop_table("inbound_email_aliases")

    for column in (
        "company_id",
        "calendar_connection_id",
        "provider",
        "provider_event_id",
        "suggested_matter_id",
        "linked_matter_id",
        "linked_hearing_id",
        "status",
        "reviewed_by_membership_id",
    ):
        _drop_idx("calendar_event_candidates", column)
    op.drop_table("calendar_event_candidates")

    for column in (
        "company_id",
        "drive_connection_id",
        "provider",
        "provider_file_id",
        "suggested_matter_id",
        "status",
        "imported_attachment_id",
        "linked_matter_id",
    ):
        _drop_idx("drive_file_candidates", column)
    op.drop_table("drive_file_candidates")

    for column in ("company_id", "provider"):
        _drop_idx("drive_sync_controls", column)
    op.drop_table("drive_sync_controls")

    for column in ("company_id", "created_by_membership_id"):
        _drop_idx("tenant_microsoft365_configurations", column)
    op.drop_table("tenant_microsoft365_configurations")

    for column in ("company_id", "provider", "configured_state", "connected_state"):
        _drop_idx("connector_health_records", column)
    op.drop_table("connector_health_records")
