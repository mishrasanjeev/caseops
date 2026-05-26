"""ADP-20 Outlook tenant configuration readiness.

Revision ID: 20260526_0002
Revises: 20260526_0001
Create Date: 2026-05-26
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260526_0002"
down_revision = "20260526_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_outlook_configurations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(length=24),
            nullable=False,
            server_default="outlook",
        ),
        sa.Column("client_id", sa.String(length=255), nullable=True),
        sa.Column("encrypted_client_secret_ref", sa.Text(), nullable=True),
        sa.Column(
            "tenant_id",
            sa.String(length=255),
            nullable=False,
            server_default="organizations",
        ),
        sa.Column("redirect_uri", sa.String(length=500), nullable=True),
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
            "durable_runbook_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "rollback_approved",
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
            "provider",
            name="uq_tenant_outlook_configurations_company_provider",
        ),
    )
    op.create_index(
        "ix_tenant_outlook_configurations_company_id",
        "tenant_outlook_configurations",
        ["company_id"],
    )
    op.create_index(
        "ix_tenant_outlook_configurations_created_by_membership_id",
        "tenant_outlook_configurations",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_tenant_outlook_configurations_updated_by_membership_id",
        "tenant_outlook_configurations",
        ["updated_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_outlook_configurations_updated_by_membership_id",
        table_name="tenant_outlook_configurations",
    )
    op.drop_index(
        "ix_tenant_outlook_configurations_created_by_membership_id",
        table_name="tenant_outlook_configurations",
    )
    op.drop_index(
        "ix_tenant_outlook_configurations_company_id",
        table_name="tenant_outlook_configurations",
    )
    op.drop_table("tenant_outlook_configurations")
