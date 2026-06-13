"""Brutal gap readiness evidence and trust scaffolding.

Revision ID: 20260613_0001
Revises: 20260610_0001
Create Date: 2026-06-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260613_0001"
down_revision = "20260610_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _idx(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_idx(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.create_table(
        "connector_secret_rotation_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("affected_app", sa.String(length=160), nullable=False),
        sa.Column("credential_label", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="blocked"),
        sa.Column(
            "old_credential_revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "validation_performed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("rotation_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("residual_risk", sa.Text(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column(
            "last_evidence_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "recorded_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
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
            "provider",
            "affected_app",
            "credential_label",
            name="uq_connector_secret_rotation_scope",
        ),
    )
    for column in (
        "provider",
        "affected_app",
        "status",
        "last_evidence_at",
        "recorded_by_platform_admin_id",
    ):
        _idx("connector_secret_rotation_evidence", column)

    op.create_table(
        "platform_operational_readiness_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("gate_code", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="blocked"),
        sa.Column(
            "readiness_classification",
            sa.String(length=40),
            nullable=False,
            server_default="founder-only",
        ),
        sa.Column("blocker_reason", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner_label", sa.String(length=160), nullable=True),
        sa.Column(
            "recorded_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
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
        sa.UniqueConstraint("category", "gate_code", name="uq_platform_readiness_gate"),
    )
    for column in (
        "category",
        "gate_code",
        "status",
        "last_evidence_at",
        "recorded_by_platform_admin_id",
    ):
        _idx("platform_operational_readiness_evidence", column)

    op.create_table(
        "tenant_enterprise_identity_configurations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idp_label", sa.String(length=160), nullable=True),
        sa.Column("oidc_status", sa.String(length=32), nullable=False, server_default="disabled"),
        sa.Column("saml_status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column("scim_status", sa.String(length=32), nullable=False, server_default="planned"),
        sa.Column(
            "sso_enforcement_status",
            sa.String(length=32),
            nullable=False,
            server_default="disabled",
        ),
        sa.Column("domains_json", sa.JSON(), nullable=True),
        sa.Column("required_evidence_json", sa.JSON(), nullable=True),
        sa.Column(
            "last_test_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_run",
        ),
        sa.Column("last_tested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "not_enabled_reason",
            sa.Text(),
            nullable=False,
            server_default=(
                "SSO, SAML, and SCIM are readiness-only until an IdP UAT pass is recorded."
            ),
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
        sa.UniqueConstraint("company_id", name="uq_tenant_enterprise_identity_company"),
    )
    for column in ("company_id", "updated_by_membership_id"):
        _idx("tenant_enterprise_identity_configurations", column)

    op.create_table(
        "agent_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "principal_type",
            sa.String(length=32),
            nullable=False,
            server_default="user",
        ),
        sa.Column(
            "principal_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("scopes_json", sa.JSON(), nullable=False),
        sa.Column("tool_budget_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_budget", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "human_approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="disabled"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    for column in ("company_id", "principal_membership_id", "status", "created_by_membership_id"):
        _idx("agent_grants", column)

    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grant_id",
            sa.String(length=36),
            sa.ForeignKey("agent_grants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("workflow_key", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="blocked"),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column(
            "started_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_json", sa.JSON(), nullable=True),
    )
    for column in ("company_id", "grant_id", "status", "started_by_membership_id"):
        _idx("agent_executions", column)

    op.create_table(
        "agent_tool_calls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "execution_id",
            sa.String(length=36),
            sa.ForeignKey("agent_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(length=120), nullable=False),
        sa.Column("scope", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="blocked"),
        sa.Column(
            "approval_status",
            sa.String(length=32),
            nullable=False,
            server_default="required",
        ),
        sa.Column("redacted_input_json", sa.JSON(), nullable=True),
        sa.Column("redacted_output_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in ("execution_id", "tool_name", "status"):
        _idx("agent_tool_calls", column)

    op.create_table(
        "ai_governance_approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workflow_key", sa.String(length=120), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=False),
        sa.Column("artifact_ref", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column(
            "eval_run_id",
            sa.String(length=36),
            sa.ForeignKey("evaluation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "regression_gate_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_run",
        ),
        sa.Column(
            "safety_gate_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_run",
        ),
        sa.Column(
            "hallucination_gate_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_run",
        ),
        sa.Column(
            "legal_disclaimer_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "approved_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
    )
    for column in (
        "company_id",
        "workflow_key",
        "artifact_type",
        "status",
        "eval_run_id",
        "approved_by_membership_id",
    ):
        _idx("ai_governance_approvals", column)


def downgrade() -> None:
    for column in (
        "company_id",
        "workflow_key",
        "artifact_type",
        "status",
        "eval_run_id",
        "approved_by_membership_id",
    ):
        _drop_idx("ai_governance_approvals", column)
    op.drop_table("ai_governance_approvals")

    for column in ("execution_id", "tool_name", "status"):
        _drop_idx("agent_tool_calls", column)
    op.drop_table("agent_tool_calls")

    for column in ("company_id", "grant_id", "status", "started_by_membership_id"):
        _drop_idx("agent_executions", column)
    op.drop_table("agent_executions")

    for column in ("company_id", "principal_membership_id", "status", "created_by_membership_id"):
        _drop_idx("agent_grants", column)
    op.drop_table("agent_grants")

    for column in ("company_id", "updated_by_membership_id"):
        _drop_idx("tenant_enterprise_identity_configurations", column)
    op.drop_table("tenant_enterprise_identity_configurations")

    for column in (
        "category",
        "gate_code",
        "status",
        "last_evidence_at",
        "recorded_by_platform_admin_id",
    ):
        _drop_idx("platform_operational_readiness_evidence", column)
    op.drop_table("platform_operational_readiness_evidence")

    for column in (
        "provider",
        "affected_app",
        "status",
        "last_evidence_at",
        "recorded_by_platform_admin_id",
    ):
        _drop_idx("connector_secret_rotation_evidence", column)
    op.drop_table("connector_secret_rotation_evidence")
