"""P0 paid production safety and admin security readiness.

Revision ID: 20260609_0002
Revises: 20260609_0001
Create Date: 2026-06-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260609_0002"
down_revision = "20260609_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def _create_index(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_index(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    with op.batch_alter_table("provider_cost_profiles") as batch_op:
        batch_op.add_column(sa.Column("unit_label", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("tax_fee_notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "cost_basis",
                sa.String(length=24),
                nullable=False,
                server_default="estimated",
            )
        )
        batch_op.add_column(
            sa.Column(
                "confidence_level",
                sa.String(length=24),
                nullable=False,
                server_default="low",
            )
        )
        batch_op.add_column(sa.Column("evidence_ref", sa.String(length=500), nullable=True))
        batch_op.add_column(
            sa.Column(
                "founder_approval_status",
                sa.String(length=24),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("approved_by_platform_admin_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_provider_cost_profiles_approved_by_platform_admin_id"),
            ["approved_by_platform_admin_id"],
        )
        batch_op.create_foreign_key(
            "fk_provider_cost_profiles_approved_by_platform_admin",
            "platform_admin_memberships",
            ["approved_by_platform_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )

    with op.batch_alter_table("billing_margin_simulations") as batch_op:
        for column, column_type in (
            ("plan_code", sa.String(length=80)),
            ("scenario_code", sa.String(length=80)),
        ):
            batch_op.add_column(sa.Column(column, column_type, nullable=True))
            batch_op.create_index(op.f(f"ix_billing_margin_simulations_{column}"), [column])
        batch_op.add_column(
            sa.Column(
                "minimum_gross_margin_bps",
                sa.Integer(),
                nullable=False,
                server_default="7000",
            )
        )
        batch_op.add_column(
            sa.Column(
                "uses_unapproved_estimated_costs",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "readiness_blocked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "founder_approval_status",
                sa.String(length=24),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("approved_by_platform_admin_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_index(
            op.f("ix_billing_margin_simulations_approved_by_platform_admin_id"),
            ["approved_by_platform_admin_id"],
        )
        batch_op.create_foreign_key(
            "fk_billing_margin_simulations_approved_by_platform_admin",
            "platform_admin_memberships",
            ["approved_by_platform_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_table(
        "user_mfa_settings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default="not_enrolled",
        ),
        sa.Column("encrypted_totp_secret", sa.Text(), nullable=True),
        sa.Column("secret_displayed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_challenge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recovery_codes_generated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("user_id", name="uq_user_mfa_settings_user"),
    )
    _create_index("user_mfa_settings", "user_id")

    op.create_table(
        "user_mfa_recovery_codes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="active"),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("user_id", "code_hash", name="uq_user_mfa_recovery_code_hash"),
    )
    for column in ("user_id", "status"):
        _create_index("user_mfa_recovery_codes", column)

    op.create_table(
        "user_mfa_step_ups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in ("user_id", "membership_id", "purpose", "completed_at", "expires_at"):
        _create_index("user_mfa_step_ups", column)

    op.create_table(
        "tenant_security_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_admin_mfa_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "all_users_mfa_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "mfa_grace_period_days",
            sa.Integer(),
            nullable=False,
            server_default="7",
        ),
        sa.Column("mfa_enforced_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint("company_id", name="uq_tenant_security_policy_company"),
    )
    for column in ("company_id", "updated_by_membership_id"):
        _create_index("tenant_security_policies", column)

    op.create_table(
        "pine_labs_uat_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("environment", sa.String(length=24), nullable=False, server_default="uat"),
        sa.Column("provider_mode", sa.String(length=40), nullable=False, server_default="mock"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="in_progress"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "operator_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence_summary_json", sa.JSON(), nullable=True),
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
    for column in ("environment", "started_at", "operator_platform_admin_id"):
        _create_index("pine_labs_uat_runs", column)

    op.create_table(
        "pine_labs_uat_scenario_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("pine_labs_uat_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("scenario_code", sa.String(length=80), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("result_status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("webhook_id", sa.String(length=255), nullable=True),
        sa.Column("webhook_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("redacted_payload_json", sa.JSON(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column("attachment_refs_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
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
        sa.UniqueConstraint("run_id", "scenario_code", name="uq_pine_labs_uat_run_scenario"),
    )
    for column in (
        "run_id",
        "scenario_code",
        "provider_order_id",
        "provider_payment_id",
        "webhook_id",
        "observed_at",
        "created_by_platform_admin_id",
    ):
        _create_index("pine_labs_uat_scenario_evidence", column)

    op.create_table(
        "pine_labs_production_activation_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=36),
            sa.ForeignKey("pine_labs_uat_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("missing_scenarios_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("founder_go_no_go", sa.String(length=24), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "decided_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in ("run_id", "decision", "decided_by_platform_admin_id", "decided_at"):
        _create_index("pine_labs_production_activation_decisions", column)

    op.create_table(
        "production_billing_signoffs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="in_progress"),
        sa.Column(
            "signed_off_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("signed_off_at", sa.DateTime(timezone=True), nullable=True),
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
    for column in ("signed_off_by_platform_admin_id", "created_at"):
        _create_index("production_billing_signoffs", column)

    op.create_table(
        "production_billing_signoff_evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "signoff_id",
            sa.String(length=36),
            sa.ForeignKey("production_billing_signoffs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("check_code", sa.String(length=120), nullable=False),
        sa.Column("result_status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("operator_notes", sa.Text(), nullable=True),
        sa.Column(
            "recorded_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
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
        sa.UniqueConstraint("signoff_id", "check_code", name="uq_prod_billing_signoff_check"),
    )
    for column in (
        "signoff_id",
        "check_code",
        "recorded_by_platform_admin_id",
        "recorded_at",
    ):
        _create_index("production_billing_signoff_evidence", column)

    op.create_table(
        "billing_settlement_imports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "provider",
            sa.String(length=40),
            nullable=False,
            server_default="pine_labs_plural",
        ),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("settlement_period_start", sa.Date(), nullable=True),
        sa.Column("settlement_period_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="imported"),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exception_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "imported_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in ("status", "imported_by_platform_admin_id", "imported_at"):
        _create_index("billing_settlement_imports", column)

    op.create_table(
        "billing_settlement_rows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "settlement_import_id",
            sa.String(length=36),
            sa.ForeignKey("billing_settlement_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=40),
            nullable=False,
            server_default="pine_labs_plural",
        ),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("settlement_status", sa.String(length=40), nullable=False, server_default="received"),
        sa.Column("reconciliation_status", sa.String(length=40), nullable=False, server_default="unmatched"),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("net_settlement_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("settled_on", sa.Date(), nullable=True),
        sa.Column("raw_row_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("settlement_import_id", "row_hash", name="uq_settlement_import_row_hash"),
    )
    for column in (
        "settlement_import_id",
        "provider_order_id",
        "provider_payment_id",
        "payment_order_id",
        "reconciliation_status",
    ):
        _create_index("billing_settlement_rows", column)

    op.create_table(
        "billing_reconciliation_exceptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "settlement_import_id",
            sa.String(length=36),
            sa.ForeignKey("billing_settlement_imports.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "settlement_row_id",
            sa.String(length=36),
            sa.ForeignKey("billing_settlement_rows.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("exception_type", sa.String(length=60), nullable=False),
        sa.Column("severity", sa.String(length=24), nullable=False, server_default="warning"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("amount_delta_minor", sa.Integer(), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column(
            "resolved_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    for column in (
        "settlement_import_id",
        "settlement_row_id",
        "payment_order_id",
        "exception_type",
        "status",
        "resolved_by_platform_admin_id",
        "created_at",
    ):
        _create_index("billing_reconciliation_exceptions", column)

    op.create_table(
        "billing_refund_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="pine_labs_plural"),
        sa.Column("provider_refund_id", sa.String(length=255), nullable=True),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id",
            sa.String(length=36),
            sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="recorded"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_reversal_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
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
        sa.UniqueConstraint("provider", "provider_refund_id", name="uq_billing_refund_provider_id"),
    )
    for column in (
        "provider_refund_id",
        "provider_order_id",
        "payment_order_id",
        "company_id",
        "subscription_id",
        "status",
        "created_by_platform_admin_id",
    ):
        _create_index("billing_refund_records", column)

    op.create_table(
        "billing_credit_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            sa.String(length=36),
            sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "refund_record_id",
            sa.String(length=36),
            sa.ForeignKey("billing_refund_records.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("credit_note_number", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="issued"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tds_adjustment_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("attachment_storage_key", sa.String(length=500), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
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
        sa.UniqueConstraint("credit_note_number", name="uq_billing_credit_note_number"),
    )
    for column in (
        "company_id",
        "subscription_id",
        "payment_order_id",
        "refund_record_id",
        "credit_note_number",
        "status",
        "created_by_platform_admin_id",
    ):
        _create_index("billing_credit_notes", column)

    op.create_table(
        "billing_chargeback_disputes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="pine_labs_plural"),
        sa.Column("provider_dispute_id", sa.String(length=255), nullable=True),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
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
        sa.UniqueConstraint("provider", "provider_dispute_id", name="uq_billing_dispute_provider_id"),
    )
    for column in (
        "provider_dispute_id",
        "provider_order_id",
        "payment_order_id",
        "company_id",
        "status",
        "created_by_platform_admin_id",
    ):
        _create_index("billing_chargeback_disputes", column)

    op.create_table(
        "billing_provider_fee_reconciliations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default="pine_labs_plural"),
        sa.Column(
            "settlement_row_id",
            sa.String(length=36),
            sa.ForeignKey("billing_settlement_rows.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "payment_order_id",
            sa.String(length=36),
            sa.ForeignKey("billing_payment_orders.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expected_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("actual_fee_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delta_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
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
    for column in ("settlement_row_id", "payment_order_id", "status", "created_at"):
        _create_index("billing_provider_fee_reconciliations", column)

    op.create_table(
        "billing_tds_reconciliation_rows",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "subscription_id",
            sa.String(length=36),
            sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "invoice_id",
            sa.String(length=36),
            sa.ForeignKey("billing_manual_invoices.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "credit_note_id",
            sa.String(length=36),
            sa.ForeignKey("billing_credit_notes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payer_name", sa.String(length=255), nullable=True),
        sa.Column("payer_pan", sa.String(length=20), nullable=True),
        sa.Column("certificate_number", sa.String(length=120), nullable=True),
        sa.Column("financial_year", sa.String(length=20), nullable=True),
        sa.Column("gross_amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tds_deducted_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tds_deposited_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="open"),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
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
    )
    for column in (
        "company_id",
        "subscription_id",
        "invoice_id",
        "credit_note_id",
        "financial_year",
        "status",
        "created_by_platform_admin_id",
        "created_at",
    ):
        _create_index("billing_tds_reconciliation_rows", column)

    op.create_table(
        "case_tracking_support_matrix",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("court", sa.String(length=255), nullable=False),
        sa.Column("bench_jurisdiction", sa.String(length=255), nullable=True),
        sa.Column("lookup_method", sa.String(length=120), nullable=False),
        sa.Column("refresh_cost_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bulk_refresh_cost_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("rate_limit", sa.String(length=160), nullable=True),
        sa.Column("freshness_sla", sa.String(length=160), nullable=True),
        sa.Column("legal_tos_status", sa.String(length=80), nullable=False, server_default="unknown"),
        sa.Column("failure_code_mapping_json", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tenant_visible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status_notes", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.String(length=500), nullable=True),
        sa.Column(
            "created_by_platform_admin_id",
            sa.String(length=36),
            sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_platform_admin_id",
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
            "court",
            "bench_jurisdiction",
            "lookup_method",
            name="uq_case_tracking_support_matrix_scope",
        ),
    )
    for column in (
        "provider",
        "court",
        "bench_jurisdiction",
        "enabled",
        "tenant_visible",
        "created_by_platform_admin_id",
        "updated_by_platform_admin_id",
        "created_at",
    ):
        _create_index("case_tracking_support_matrix", column)


def downgrade() -> None:
    for table, columns in (
        (
            "case_tracking_support_matrix",
            (
                "provider",
                "court",
                "bench_jurisdiction",
                "enabled",
                "tenant_visible",
                "created_by_platform_admin_id",
                "updated_by_platform_admin_id",
                "created_at",
            ),
        ),
        (
            "billing_tds_reconciliation_rows",
            (
                "company_id",
                "subscription_id",
                "invoice_id",
                "credit_note_id",
                "financial_year",
                "status",
                "created_by_platform_admin_id",
                "created_at",
            ),
        ),
        (
            "billing_provider_fee_reconciliations",
            ("settlement_row_id", "payment_order_id", "status", "created_at"),
        ),
        (
            "billing_chargeback_disputes",
            (
                "provider_dispute_id",
                "provider_order_id",
                "payment_order_id",
                "company_id",
                "status",
                "created_by_platform_admin_id",
            ),
        ),
        (
            "billing_credit_notes",
            (
                "company_id",
                "subscription_id",
                "payment_order_id",
                "refund_record_id",
                "credit_note_number",
                "status",
                "created_by_platform_admin_id",
            ),
        ),
        (
            "billing_refund_records",
            (
                "provider_refund_id",
                "provider_order_id",
                "payment_order_id",
                "company_id",
                "subscription_id",
                "status",
                "created_by_platform_admin_id",
            ),
        ),
        (
            "billing_reconciliation_exceptions",
            (
                "settlement_import_id",
                "settlement_row_id",
                "payment_order_id",
                "exception_type",
                "status",
                "resolved_by_platform_admin_id",
                "created_at",
            ),
        ),
        (
            "billing_settlement_rows",
            (
                "settlement_import_id",
                "provider_order_id",
                "provider_payment_id",
                "payment_order_id",
                "reconciliation_status",
            ),
        ),
        (
            "billing_settlement_imports",
            ("status", "imported_by_platform_admin_id", "imported_at"),
        ),
        (
            "production_billing_signoff_evidence",
            (
                "signoff_id",
                "check_code",
                "recorded_by_platform_admin_id",
                "recorded_at",
            ),
        ),
        (
            "production_billing_signoffs",
            ("signed_off_by_platform_admin_id", "created_at"),
        ),
        (
            "pine_labs_production_activation_decisions",
            ("run_id", "decision", "decided_by_platform_admin_id", "decided_at"),
        ),
        (
            "pine_labs_uat_scenario_evidence",
            (
                "run_id",
                "scenario_code",
                "provider_order_id",
                "provider_payment_id",
                "webhook_id",
                "observed_at",
                "created_by_platform_admin_id",
            ),
        ),
        (
            "pine_labs_uat_runs",
            ("environment", "started_at", "operator_platform_admin_id"),
        ),
        ("tenant_security_policies", ("company_id", "updated_by_membership_id")),
        (
            "user_mfa_step_ups",
            ("user_id", "membership_id", "purpose", "completed_at", "expires_at"),
        ),
        ("user_mfa_recovery_codes", ("user_id", "status")),
        ("user_mfa_settings", ("user_id",)),
    ):
        for column in columns:
            _drop_index(table, column)
        op.drop_table(table)

    with op.batch_alter_table("billing_margin_simulations") as batch_op:
        batch_op.drop_constraint(
            "fk_billing_margin_simulations_approved_by_platform_admin",
            type_="foreignkey",
        )
        for column in (
            "approved_by_platform_admin_id",
            "scenario_code",
            "plan_code",
        ):
            batch_op.drop_index(op.f(f"ix_billing_margin_simulations_{column}"))
        for column in (
            "approved_by_platform_admin_id",
            "approved_at",
            "founder_approval_status",
            "readiness_blocked",
            "uses_unapproved_estimated_costs",
            "minimum_gross_margin_bps",
            "scenario_code",
            "plan_code",
        ):
            batch_op.drop_column(column)

    with op.batch_alter_table("provider_cost_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_provider_cost_profiles_approved_by_platform_admin",
            type_="foreignkey",
        )
        batch_op.drop_index(op.f("ix_provider_cost_profiles_approved_by_platform_admin_id"))
        for column in (
            "approved_by_platform_admin_id",
            "approved_at",
            "founder_approval_status",
            "evidence_ref",
            "confidence_level",
            "cost_basis",
            "tax_fee_notes",
            "unit_label",
        ):
            batch_op.drop_column(column)
