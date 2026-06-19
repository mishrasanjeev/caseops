"""Tenant Google Workspace OAuth configuration.

Revision ID: 20260609_0001
Revises: 20260608_0003
Create Date: 2026-06-09
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260609_0001"
down_revision = "20260608_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "tenant_google_workspace_configurations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_client_secret_ref", sa.Text(), nullable=True),
        sa.Column("calendar_redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("gmail_redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("drive_redirect_uri", sa.String(length=500), nullable=True),
        sa.Column("scopes_json", sa.JSON(), nullable=True),
        sa.Column(
            "oauth_consent_model_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "scopes_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "webhook_runbook_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "redaction_rules_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "calendar_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "gmail_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "drive_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "last_test_status",
            sa.String(length=24),
            nullable=False,
            server_default="not_run",
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
            "updated_by_membership_id",
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
        sa.UniqueConstraint(
            "company_id",
            name="uq_tenant_google_workspace_configurations_company",
        ),
    )
    op.create_index(
        "ix_tgws_config_company",
        "tenant_google_workspace_configurations",
        ["company_id"],
    )
    op.create_index(
        "ix_tgws_config_created_by",
        "tenant_google_workspace_configurations",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_tgws_config_updated_by",
        "tenant_google_workspace_configurations",
        ["updated_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tgws_config_updated_by",
        table_name="tenant_google_workspace_configurations",
    )
    op.drop_index(
        "ix_tgws_config_created_by",
        table_name="tenant_google_workspace_configurations",
    )
    op.drop_index(
        "ix_tgws_config_company",
        table_name="tenant_google_workspace_configurations",
    )
    op.drop_table("tenant_google_workspace_configurations")
