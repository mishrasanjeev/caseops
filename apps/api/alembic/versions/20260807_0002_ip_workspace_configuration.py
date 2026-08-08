"""Add versioned IP workspace configuration and readiness test evidence.

Revision ID: 20260807_0002
Revises: 20260807_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260807_0002"
down_revision = "20260807_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ip_workspace_configurations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("enabled_asset_types_json", sa.JSON(), nullable=False),
        sa.Column("jurisdictions_json", sa.JSON(), nullable=False),
        sa.Column("offices_json", sa.JSON(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("holiday_calendar_key", sa.String(120), nullable=False),
        sa.Column("working_day_policy_json", sa.JSON(), nullable=False),
        sa.Column("document_taxonomy_version", sa.String(80), nullable=False),
        sa.Column("event_catalog_version", sa.String(80), nullable=False),
        sa.Column("deadline_rule_versions_json", sa.JSON(), nullable=False),
        sa.Column("notification_channels_json", sa.JSON(), nullable=False),
        sa.Column("critical_event_policy_json", sa.JSON(), nullable=False),
        sa.Column("escalation_owner_membership_id", sa.String(36), nullable=False),
        sa.Column("provider_keys_json", sa.JSON(), nullable=False),
        sa.Column("provider_terms_version", sa.String(80), nullable=True),
        sa.Column("provider_terms_accepted_by_membership_id", sa.String(36), nullable=True),
        sa.Column("provider_terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled_automations_json", sa.JSON(), nullable=False),
        sa.Column("workspace_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_by_membership_id", sa.String(36), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            name="fk_ip_workspace_config_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_updater_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_terms_accepted_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_terms_actor_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["escalation_owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_config_escalation_owner_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_workspace_config_id_company"),
        sa.UniqueConstraint("company_id", name="uq_ip_workspace_config_company"),
    )
    op.create_index(
        "ix_ip_workspace_configurations_company_id",
        "ip_workspace_configurations",
        ["company_id"],
    )
    op.create_index(
        "ix_ip_workspace_configurations_escalation_owner_membership_id",
        "ip_workspace_configurations",
        ["escalation_owner_membership_id"],
    )
    op.create_index(
        "ix_ip_workspace_config_terms_actor",
        "ip_workspace_configurations",
        ["provider_terms_accepted_by_membership_id"],
    )
    op.create_index(
        "ix_ip_workspace_configurations_updated_by_membership_id",
        "ip_workspace_configurations",
        ["updated_by_membership_id"],
    )

    op.create_table(
        "ip_workspace_test_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("configuration_id", sa.String(36), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("test_kind", sa.String(40), nullable=False),
        sa.Column("feature_id", sa.String(80), nullable=True),
        sa.Column("provider_key", sa.String(80), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=False),
        sa.Column("performed_by_membership_id", sa.String(36), nullable=False),
        sa.Column(
            "performed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["configuration_id", "company_id"],
            ["ip_workspace_configurations.id", "ip_workspace_configurations.company_id"],
            name="fk_ip_workspace_test_config_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["performed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_workspace_test_actor_company",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_ip_workspace_test_results_configuration_id",
        "ip_workspace_test_results",
        ["configuration_id"],
    )
    op.create_index(
        "ix_ip_workspace_test_results_performed_by_membership_id",
        "ip_workspace_test_results",
        ["performed_by_membership_id"],
    )
    op.create_index(
        "ix_ip_workspace_tests_company_config",
        "ip_workspace_test_results",
        ["company_id", "configuration_id", "config_version"],
    )


def downgrade() -> None:
    op.drop_table("ip_workspace_test_results")
    op.drop_table("ip_workspace_configurations")
