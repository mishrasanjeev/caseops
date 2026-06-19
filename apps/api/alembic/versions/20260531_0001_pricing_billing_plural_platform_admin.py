# ruff: noqa: E501
"""pricing, SaaS billing, Plural checkout, and platform admin foundation.

Revision ID: 20260531_0001
Revises: 20260526_0006
Create Date: 2026-05-31 10:00:00
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260531_0001"
down_revision = "20260526_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")

CATALOG_VERSION = "2026.05.v1"
GST_BPS = 1800
GIB = 1024**3
MIB = 1024**2


def _id(prefix: str, code: str, *, max_length: int = 36) -> str:
    raw = f"{prefix}-{code.replace('_', '-')}"
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    head_length = max_length - len(digest) - 1
    return f"{raw[:head_length].rstrip('-')}-{digest}"


PLAN_ROWS = [
    ("trial", "trial", "Free Trial", "14-day no-card trial.", False, True),
    ("solo_core", "solo", "Solo Core", "Entry plan for solo lawyers.", True, True),
    ("solo_pro", "solo", "Solo Pro", "Hero solo plan for high-context practice.", True, True),
    ("solo_elite", "solo", "Solo Elite", "High-volume solo litigation plan.", True, True),
    ("firm_starter", "firm", "Firm Starter", "Small firm operating plan.", True, True),
    ("firm_growth", "firm", "Firm Growth", "Hero plan for growing law firms.", True, True),
    ("firm_pro", "firm", "Firm Pro", "Large firm plan with API-ready controls.", True, False),
    ("firm_enterprise", "firm", "Firm Enterprise", "Custom firm contract.", True, False),
    (
        "gc_monitoring",
        "gc",
        "Litigation Monitoring Only",
        "Corporate monitoring wedge.",
        True,
        False,
    ),
    ("gc_starter", "gc", "GC Starter", "Corporate legal operations starter.", True, False),
    (
        "gc_professional",
        "gc",
        "GC Professional",
        "Mature corporate legal operations plan.",
        True,
        False,
    ),
    ("gc_enterprise", "gc", "GC Enterprise", "Custom corporate legal contract.", True, False),
    (
        "grandfathered_free",
        "internal",
        "Grandfathered Free",
        "Non-billable migration subscription for existing tenants.",
        False,
        False,
    ),
    ("addon_user_firm", "add_on", "Extra firm user", "1 additional internal user.", True, False),
    (
        "addon_user_corporate_legal",
        "add_on",
        "Extra corporate legal user",
        "1 additional legal/admin user.",
        True,
        False,
    ),
    ("addon_viewer", "add_on", "Extra viewer/business user", "1 viewer.", True, False),
    (
        "addon_cases_500",
        "add_on",
        "Tracked case pack 500",
        "500 additional tracked cases.",
        True,
        False,
    ),
    (
        "addon_cases_1000",
        "add_on",
        "Tracked case pack 1000",
        "1,000 additional tracked cases.",
        True,
        False,
    ),
    ("addon_ai_250", "add_on", "AI credit pack 250", "250 credits, 12-month expiry.", True, False),
    (
        "addon_ai_1000",
        "add_on",
        "AI credit pack 1000",
        "1,000 credits, 12-month expiry.",
        True,
        False,
    ),
    (
        "addon_ai_5000",
        "add_on",
        "AI credit pack 5000",
        "5,000 credits, 12-month expiry.",
        True,
        False,
    ),
    (
        "addon_storage_100gb",
        "add_on",
        "Extra storage 100 GB",
        "100 GB additional storage.",
        True,
        False,
    ),
    ("addon_api_access", "add_on", "API access", "API keys and dashboard.", True, False),
    ("addon_migration_basic", "add_on", "Basic migration", "CSV import and guided setup.", True, False),
    (
        "addon_migration_firm",
        "add_on",
        "Firm migration",
        "Matter, client, and document import assistance.",
        True,
        False,
    ),
    (
        "addon_migration_enterprise",
        "add_on",
        "Enterprise migration",
        "Custom mapping, QA, and launch support.",
        True,
        False,
    ),
    (
        "addon_research_memo",
        "add_on",
        "Legal research memo",
        "Human/editor-assisted memo.",
        True,
        False,
    ),
]

PRICE_ROWS = {
    "trial": [(0, "one_time", "inclusive")],
    "solo_core": [(99900, "month", "inclusive"), (999000, "year", "inclusive")],
    "solo_pro": [(199900, "month", "inclusive"), (1999000, "year", "inclusive")],
    "solo_elite": [(399900, "month", "inclusive"), (3999000, "year", "inclusive")],
    "firm_starter": [(599900, "month", "exclusive"), (6299000, "year", "exclusive")],
    "firm_growth": [(1999900, "month", "exclusive"), (20999000, "year", "exclusive")],
    "firm_pro": [(4999900, "month", "exclusive"), (52499000, "year", "exclusive")],
    "firm_enterprise": [(None, "custom", "exclusive")],
    "gc_monitoring": [(15000000, "year", "exclusive")],
    "gc_starter": [(30000000, "year", "exclusive")],
    "gc_professional": [(80000000, "year", "exclusive")],
    "gc_enterprise": [(None, "custom", "exclusive")],
    "grandfathered_free": [(0, "custom", "exclusive")],
    "addon_user_firm": [(69900, "month", "exclusive")],
    "addon_user_corporate_legal": [(150000, "month", "exclusive")],
    "addon_viewer": [(19900, "month", "exclusive")],
    "addon_cases_500": [(249900, "month", "exclusive")],
    "addon_cases_1000": [(449900, "month", "exclusive")],
    "addon_ai_250": [(119900, "one_time", "exclusive")],
    "addon_ai_1000": [(399900, "one_time", "exclusive")],
    "addon_ai_5000": [(1499900, "one_time", "exclusive")],
    "addon_storage_100gb": [(149900, "month", "exclusive")],
    "addon_api_access": [(500000, "month", "exclusive")],
    "addon_migration_basic": [(1000000, "one_time", "exclusive")],
    "addon_migration_firm": [(2500000, "one_time", "exclusive")],
    "addon_migration_enterprise": [(7500000, "one_time", "exclusive")],
    "addon_research_memo": [(500000, "one_time", "exclusive")],
}

ENTITLEMENTS = {
    "trial": {
        "users_internal_limit": 2,
        "users_viewer_limit": 0,
        "matters_active_limit": 10,
        "tracked_cases_limit": 10,
        "ai_credits_monthly": 25,
        "storage_bytes_limit": 500 * MIB,
        "manual_case_refreshes_daily": 2,
        "case_refresh_cadence": "weekday_daily",
        "api_access_enabled": False,
        "audit_export_enabled": False,
        "sso_enabled": False,
    },
    "solo_core": {
        "users_internal_limit": 2,
        "users_viewer_limit": 0,
        "matters_active_limit": 50,
        "tracked_cases_limit": 50,
        "ai_credits_monthly": 100,
        "storage_bytes_limit": 2 * GIB,
        "manual_case_refreshes_daily": 5,
        "case_refresh_cadence": "weekday_daily",
        "api_access_enabled": False,
        "audit_export_enabled": False,
        "sso_enabled": False,
    },
    "solo_pro": {
        "users_internal_limit": 4,
        "users_viewer_limit": 0,
        "matters_active_limit": 250,
        "tracked_cases_limit": 200,
        "ai_credits_monthly": 300,
        "storage_bytes_limit": 10 * GIB,
        "manual_case_refreshes_daily": 10,
        "case_refresh_cadence": "daily",
        "api_access_enabled": False,
        "audit_export_enabled": False,
        "sso_enabled": False,
    },
    "solo_elite": {
        "users_internal_limit": 6,
        "users_viewer_limit": 0,
        "matters_active_limit": 1000,
        "tracked_cases_limit": 750,
        "ai_credits_monthly": 800,
        "storage_bytes_limit": 50 * GIB,
        "manual_case_refreshes_daily": 25,
        "case_refresh_cadence": "priority_daily",
        "api_access_enabled": False,
        "audit_export_enabled": "basic",
        "sso_enabled": False,
    },
    "firm_starter": {
        "users_internal_limit": 5,
        "users_viewer_limit": 0,
        "matters_active_limit": 300,
        "tracked_cases_limit": 250,
        "ai_credits_monthly": 300,
        "storage_bytes_limit": 25 * GIB,
        "manual_case_refreshes_daily": 10,
        "case_refresh_cadence": "smart_weekday_daily",
        "api_access_enabled": False,
        "audit_export_enabled": "basic",
        "sso_enabled": False,
    },
    "firm_growth": {
        "users_internal_limit": 15,
        "users_viewer_limit": 10,
        "matters_active_limit": 1500,
        "tracked_cases_limit": 1000,
        "ai_credits_monthly": 1200,
        "storage_bytes_limit": 150 * GIB,
        "manual_case_refreshes_daily": 50,
        "case_refresh_cadence": "smart_daily",
        "api_access_enabled": "add_on",
        "audit_export_enabled": True,
        "sso_enabled": False,
    },
    "firm_pro": {
        "users_internal_limit": 50,
        "users_viewer_limit": 50,
        "matters_active_limit": 5000,
        "tracked_cases_limit": 2500,
        "ai_credits_monthly": 3000,
        "storage_bytes_limit": 500 * GIB,
        "manual_case_refreshes_daily": 150,
        "case_refresh_cadence": "priority_smart_daily",
        "api_access_enabled": True,
        "audit_export_enabled": True,
        "sso_enabled": "ready",
    },
    "gc_monitoring": {
        "users_internal_limit": 3,
        "users_viewer_limit": 25,
        "matters_active_limit": 500,
        "tracked_cases_limit": 5000,
        "ai_credits_monthly": 1000,
        "storage_bytes_limit": 50 * GIB,
        "manual_case_refreshes_daily": 100,
        "case_refresh_cadence": "daily",
        "api_access_enabled": False,
        "audit_export_enabled": True,
        "sso_enabled": False,
    },
    "gc_starter": {
        "users_internal_limit": 5,
        "users_viewer_limit": 25,
        "matters_active_limit": 1000,
        "tracked_cases_limit": 5000,
        "ai_credits_monthly": 10000,
        "storage_bytes_limit": 250 * GIB,
        "manual_case_refreshes_daily": 150,
        "case_refresh_cadence": "daily",
        "api_access_enabled": "add_on",
        "audit_export_enabled": True,
        "sso_enabled": False,
    },
    "gc_professional": {
        "users_internal_limit": 15,
        "users_viewer_limit": 100,
        "matters_active_limit": 10000,
        "tracked_cases_limit": 25000,
        "ai_credits_monthly": 30000,
        "storage_bytes_limit": 1024 * GIB,
        "manual_case_refreshes_daily": 500,
        "case_refresh_cadence": "priority_daily",
        "api_access_enabled": True,
        "audit_export_enabled": True,
        "sso_enabled": "ready",
    },
    "firm_enterprise": {
        "users_internal_limit": None,
        "users_viewer_limit": None,
        "matters_active_limit": None,
        "tracked_cases_limit": None,
        "ai_credits_monthly": None,
        "storage_bytes_limit": None,
        "manual_case_refreshes_daily": None,
        "case_refresh_cadence": "SLA/custom",
        "api_access_enabled": True,
        "audit_export_enabled": True,
        "sso_enabled": True,
    },
    "gc_enterprise": {
        "users_internal_limit": None,
        "users_viewer_limit": None,
        "matters_active_limit": None,
        "tracked_cases_limit": None,
        "ai_credits_monthly": None,
        "storage_bytes_limit": None,
        "manual_case_refreshes_daily": None,
        "case_refresh_cadence": "SLA/custom",
        "api_access_enabled": True,
        "audit_export_enabled": True,
        "sso_enabled": True,
    },
    "grandfathered_free": {
        "users_internal_limit": None,
        "users_viewer_limit": None,
        "matters_active_limit": None,
        "tracked_cases_limit": None,
        "ai_credits_monthly": None,
        "storage_bytes_limit": None,
        "manual_case_refreshes_daily": None,
        "case_refresh_cadence": "manual_grandfathered",
        "api_access_enabled": True,
        "audit_export_enabled": True,
        "sso_enabled": "ready",
    },
    "addon_user_firm": {"users_internal_limit": 1},
    "addon_user_corporate_legal": {"users_internal_limit": 1},
    "addon_viewer": {"users_viewer_limit": 1},
    "addon_cases_500": {"tracked_cases_limit": 500},
    "addon_cases_1000": {"tracked_cases_limit": 1000},
    "addon_ai_250": {"ai_credits_topup": 250, "expires_after_months": 12},
    "addon_ai_1000": {"ai_credits_topup": 1000, "expires_after_months": 12},
    "addon_ai_5000": {"ai_credits_topup": 5000, "expires_after_months": 12},
    "addon_storage_100gb": {"storage_bytes_limit": 100 * GIB},
    "addon_api_access": {"api_access_enabled": True},
    "addon_migration_basic": {},
    "addon_migration_firm": {},
    "addon_migration_enterprise": {},
    "addon_research_memo": {},
}

PLATFORM_CAPABILITIES = [
    "platform:admin",
    "platform:billing_view",
    "platform:billing_manage",
    "platform:payment_reconcile",
    "platform:plan_manage",
    "platform:usage_view",
    "platform:manual_override",
]


def upgrade() -> None:
    _create_tables()
    _extend_legacy_webhook_events()
    _seed_catalog()
    _seed_grandfathered_subscriptions()
    _seed_configured_founder()


def downgrade() -> None:
    op.drop_index("ix_payment_webhook_events_provider_subscription_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider_payment_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_webhook_id", table_name="payment_webhook_events")
    with op.batch_alter_table("payment_webhook_events") as batch:
        batch.drop_column("provider_subscription_id")
        batch.drop_column("provider_payment_id")
        batch.drop_column("webhook_timestamp")
        batch.drop_column("webhook_id")

    for table_name in [
        "billing_overage_policies",
        "billing_coupon_redemptions",
        "billing_coupons",
        "billing_manual_invoices",
        "billing_admin_notes",
        "billing_enrollments",
        "billing_profit_rollups",
        "billing_usage_rollups",
        "billing_usage_attribution",
        "billing_usage_events",
        "billing_credit_ledger",
        "billing_provider_events",
        "billing_payment_orders",
        "billing_checkout_sessions",
        "billing_subscription_items",
        "billing_subscriptions",
        "billing_accounts",
        "billing_plan_entitlements",
        "billing_plan_prices",
        "billing_plan_versions",
        "platform_admin_audit_events",
        "platform_admin_memberships",
    ]:
        op.drop_table(table_name)


def _create_tables() -> None:
    op.create_table(
        "platform_admin_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("capabilities_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("mfa_required", sa.Boolean(), nullable=False),
        sa.Column("mfa_enforced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_platform_admin_id"], ["platform_admin_memberships.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_id", name="uq_platform_admin_memberships_user"),
    )
    op.create_index("ix_platform_admin_memberships_user_id", "platform_admin_memberships", ["user_id"])
    op.create_index("ix_platform_admin_memberships_status", "platform_admin_memberships", ["status"])
    op.create_index(
        "uq_platform_admin_memberships_one_active",
        "platform_admin_memberships",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "platform_admin_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_membership_id", sa.String(length=36), sa.ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("result", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("platform_admin_id", "actor_user_id", "actor_membership_id", "company_id", "action"):
        op.create_index(f"ix_platform_admin_audit_events_{col}", "platform_admin_audit_events", [col])

    op.create_table(
        "billing_plan_versions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_code", sa.String(length=80), nullable=False),
        sa.Column("version", sa.String(length=40), nullable=False),
        sa.Column("segment", sa.String(length=40), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("publicly_visible", sa.Boolean(), nullable=False),
        sa.Column("trial_eligible", sa.Boolean(), nullable=False),
        sa.Column("feature_summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("plan_code", "version", name="uq_billing_plan_versions_code_version"),
    )
    for col in ("plan_code", "version", "segment", "status"):
        op.create_index(f"ix_billing_plan_versions_{col}", "billing_plan_versions", [col])

    op.create_table(
        "billing_plan_prices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_version_id", sa.String(length=36), sa.ForeignKey("billing_plan_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("interval", sa.String(length=24), nullable=False),
        sa.Column("tax_behavior", sa.String(length=24), nullable=False),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False),
        sa.Column("provider_plan_reference", sa.String(length=160), nullable=True),
        sa.Column("provider_plan_id", sa.String(length=255), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_billing_plan_prices_plan_version_id", "billing_plan_prices", ["plan_version_id"])
    op.create_index("ix_billing_plan_prices_interval", "billing_plan_prices", ["interval"])

    op.create_table(
        "billing_plan_entitlements",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("plan_version_id", sa.String(length=36), sa.ForeignKey("billing_plan_versions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entitlement_key", sa.String(length=80), nullable=False),
        sa.Column("value_type", sa.String(length=24), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("plan_version_id", "entitlement_key", name="uq_billing_plan_entitlements_plan_key"),
    )
    op.create_index("ix_billing_plan_entitlements_plan_version_id", "billing_plan_entitlements", ["plan_version_id"])
    op.create_index("ix_billing_plan_entitlements_entitlement_key", "billing_plan_entitlements", ["entitlement_key"])

    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_email", sa.String(length=320), nullable=True),
        sa.Column("billing_name", sa.String(length=255), nullable=True),
        sa.Column("billing_phone", sa.String(length=40), nullable=True),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("billing_address_json", sa.JSON(), nullable=True),
        sa.Column("tax_treatment", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", name="uq_billing_accounts_company"),
    )
    op.create_index("ix_billing_accounts_company_id", "billing_accounts", ["company_id"])

    op.create_table(
        "billing_subscriptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_account_id", sa.String(length=36), sa.ForeignKey("billing_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_version_id", sa.String(length=36), sa.ForeignKey("billing_plan_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("segment", sa.String(length=40), nullable=False),
        sa.Column("billing_interval", sa.String(length=24), nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trial_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_customer_id", sa.String(length=255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("provider_mandate_id", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("externally_billable", sa.Boolean(), nullable=False),
        sa.Column("entitlement_overrides_json", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "billing_account_id", "plan_version_id", "status", "segment", "provider_subscription_id", "source"):
        op.create_index(f"ix_billing_subscriptions_{col}", "billing_subscriptions", [col])
    op.create_index(
        "uq_billing_subscriptions_company_active",
        "billing_subscriptions",
        ["company_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('active', 'trialing', 'grace', 'manual_active')"),
        postgresql_where=sa.text("status IN ('active', 'trialing', 'grace', 'manual_active')"),
    )

    op.create_table(
        "billing_subscription_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_code", sa.String(length=80), nullable=False),
        sa.Column("item_type", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("interval", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("provider_item_id", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("subscription_id", "item_code", "item_type", "status"):
        op.create_index(f"ix_billing_subscription_items_{col}", "billing_subscription_items", [col])

    _create_checkout_payment_usage_tables()
    _create_finance_tables()


def _create_checkout_payment_usage_tables() -> None:
    op.create_table(
        "billing_checkout_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("billing_account_id", sa.String(length=36), sa.ForeignKey("billing_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("plan_version_id", sa.String(length=36), sa.ForeignKey("billing_plan_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("checkout_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("success_url", sa.String(length=1000), nullable=True),
        sa.Column("cancel_url", sa.String(length=1000), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("provider_checkout_url", sa.String(length=1000), nullable=True),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), sa.ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "billing_account_id", "subscription_id", "plan_version_id", "checkout_type", "status", "provider_order_id", "provider_payment_id", "provider_subscription_id", "created_by_membership_id"):
        op.create_index(f"ix_billing_checkout_sessions_{col}", "billing_checkout_sessions", [col])

    op.create_table(
        "billing_payment_orders",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checkout_session_id", sa.String(length=36), sa.ForeignKey("billing_checkout_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("merchant_reference", sa.String(length=160), nullable=False),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("provider_link_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_paid_minor", sa.Integer(), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("payment_url", sa.String(length=1000), nullable=True),
        sa.Column("return_signature_verified", sa.Boolean(), nullable=False),
        sa.Column("provider_payload_json", sa.JSON(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("merchant_reference", name="uq_billing_payment_orders_merchant_ref"),
    )
    for col in ("company_id", "checkout_session_id", "subscription_id", "merchant_reference", "provider_order_id", "provider_payment_id", "provider_link_id", "status"):
        op.create_index(f"ix_billing_payment_orders_{col}", "billing_payment_orders", [col])

    op.create_table(
        "billing_provider_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
        sa.Column("webhook_id", sa.String(length=255), nullable=True),
        sa.Column("webhook_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("signature_digest", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=True),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("processing_status", sa.String(length=32), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_billing_provider_event"),
        sa.UniqueConstraint("provider", "webhook_id", name="uq_billing_provider_webhook"),
    )
    for col in ("provider", "provider_event_id", "webhook_id", "event_type", "provider_order_id", "provider_payment_id", "provider_subscription_id", "resource_id"):
        op.create_index(f"ix_billing_provider_events_{col}", "billing_provider_events", [col])

    op.create_table(
        "billing_credit_ledger",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("credit_bucket", sa.String(length=40), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("source_object_type", sa.String(length=80), nullable=True),
        sa.Column("source_object_id", sa.String(length=120), nullable=True),
        sa.Column("actor_membership_id", sa.String(length=36), sa.ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "subscription_id", "event_type", "source_object_id", "actor_membership_id", "platform_admin_id"):
        op.create_index(f"ix_billing_credit_ledger_{col}", "billing_credit_ledger", [col])

    op.create_table(
        "billing_usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("usage_type", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit", sa.String(length=40), nullable=False),
        sa.Column("estimated_cost_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("source_type", sa.String(length=80), nullable=True),
        sa.Column("source_id", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "subscription_id", "usage_type", "source_type", "source_id"):
        op.create_index(f"ix_billing_usage_events_{col}", "billing_usage_events", [col])

    op.create_table(
        "billing_usage_attribution",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("billing_usage_event_id", sa.String(length=36), sa.ForeignKey("billing_usage_events.id", ondelete="CASCADE"), nullable=True),
        sa.Column("actor_membership_id", sa.String(length=36), sa.ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("matter_id", sa.String(length=36), sa.ForeignKey("matters.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tracked_case_id", sa.String(length=36), sa.ForeignKey("tracked_cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feature_key", sa.String(length=80), nullable=False),
        sa.Column("purpose", sa.String(length=120), nullable=True),
        sa.Column("display_label", sa.String(length=255), nullable=True),
        sa.Column("credits_debited", sa.Integer(), nullable=False),
        sa.Column("provider_units", sa.Integer(), nullable=False),
        sa.Column("estimated_internal_cost_minor", sa.Integer(), nullable=False),
        sa.Column("tenant_visible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "subscription_id", "billing_usage_event_id", "actor_membership_id", "matter_id", "tracked_case_id", "feature_key", "purpose"):
        op.create_index(f"ix_billing_usage_attribution_{col}", "billing_usage_attribution", [col])


def _create_finance_tables() -> None:
    op.create_table(
        "billing_usage_rollups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("usage_type", sa.String(length=40), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_minor", sa.Integer(), nullable=False),
        sa.Column("revenue_allocated_minor", sa.Integer(), nullable=False),
        sa.Column("gross_margin_bps", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "period_start", "period_end", "usage_type", name="uq_billing_usage_rollup_period_type"),
    )
    for col in ("company_id", "period_start", "period_end", "usage_type"):
        op.create_index(f"ix_billing_usage_rollups_{col}", "billing_usage_rollups", [col])

    op.create_table(
        "billing_profit_rollups",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recognized_revenue_minor", sa.Integer(), nullable=False),
        sa.Column("gross_revenue_minor", sa.Integer(), nullable=False),
        sa.Column("discount_minor", sa.Integer(), nullable=False),
        sa.Column("tax_collected_minor", sa.Integer(), nullable=False),
        sa.Column("payment_gateway_cost_minor", sa.Integer(), nullable=False),
        sa.Column("llm_cost_minor", sa.Integer(), nullable=False),
        sa.Column("embedding_cost_minor", sa.Integer(), nullable=False),
        sa.Column("case_refresh_cost_minor", sa.Integer(), nullable=False),
        sa.Column("document_processing_cost_minor", sa.Integer(), nullable=False),
        sa.Column("storage_cost_minor", sa.Integer(), nullable=False),
        sa.Column("manual_support_cost_minor", sa.Integer(), nullable=False),
        sa.Column("manual_research_cost_minor", sa.Integer(), nullable=False),
        sa.Column("total_variable_cost_minor", sa.Integer(), nullable=False),
        sa.Column("gross_profit_minor", sa.Integer(), nullable=False),
        sa.Column("gross_margin_bps", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "subscription_id", "period_start", "period_end"):
        op.create_index(f"ix_billing_profit_rollups_{col}", "billing_profit_rollups", [col])

    op.create_table(
        "billing_enrollments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_email", sa.String(length=320), nullable=True),
        sa.Column("contact_mobile", sa.String(length=40), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("segment", sa.String(length=40), nullable=False),
        sa.Column("selected_plan", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("utm_json", sa.JSON(), nullable=True),
        sa.Column("bar_council_number", sa.String(length=80), nullable=True),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("coupon_code", sa.String(length=80), nullable=True),
        sa.Column("sales_owner_platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status_timestamps_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "contact_email", "segment", "selected_plan", "status"):
        op.create_index(f"ix_billing_enrollments_{col}", "billing_enrollments", [col])

    op.create_table(
        "billing_admin_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=True),
        sa.Column("enrollment_id", sa.String(length=36), sa.ForeignKey("billing_enrollments.id", ondelete="CASCADE"), nullable=True),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="CASCADE"), nullable=True),
        sa.Column("note_type", sa.String(length=40), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("company_id", "enrollment_id", "subscription_id"):
        op.create_index(f"ix_billing_admin_notes_{col}", "billing_admin_notes", [col])

    op.create_table(
        "billing_manual_invoices",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("po_number", sa.String(length=120), nullable=True),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False),
        sa.Column("tds_deducted_minor", sa.Integer(), nullable=False),
        sa.Column("amount_received_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("payment_reference", sa.String(length=255), nullable=True),
        sa.Column("attachment_storage_key", sa.String(length=500), nullable=True),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("invoice_number", name="uq_billing_manual_invoice_number"),
    )
    for col in ("company_id", "subscription_id", "status"):
        op.create_index(f"ix_billing_manual_invoices_{col}", "billing_manual_invoices", [col])

    _create_coupon_overage_tables()


def _create_coupon_overage_tables() -> None:
    op.create_table(
        "billing_coupons",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("discount_type", sa.String(length=24), nullable=False),
        sa.Column("discount_value", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("duration", sa.String(length=24), nullable=False),
        sa.Column("duration_periods", sa.Integer(), nullable=True),
        sa.Column("max_redemptions", sa.Integer(), nullable=True),
        sa.Column("redeemed_count", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("segment_scope_json", sa.JSON(), nullable=True),
        sa.Column("plan_scope_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_billing_coupons_code"),
    )
    for col in ("code", "status"):
        op.create_index(f"ix_billing_coupons_{col}", "billing_coupons", [col])

    op.create_table(
        "billing_coupon_redemptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("coupon_id", sa.String(length=36), sa.ForeignKey("billing_coupons.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checkout_session_id", sa.String(length=36), sa.ForeignKey("billing_checkout_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("subscription_id", sa.String(length=36), sa.ForeignKey("billing_subscriptions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("discount_amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("redeemed_by_membership_id", sa.String(length=36), sa.ForeignKey("company_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("coupon_id", "company_id", "checkout_session_id", "subscription_id"):
        op.create_index(f"ix_billing_coupon_redemptions_{col}", "billing_coupon_redemptions", [col])

    op.create_table(
        "billing_overage_policies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("company_id", sa.String(length=36), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("overage_allowed", sa.Boolean(), nullable=False),
        sa.Column("unit_prices_json", sa.JSON(), nullable=True),
        sa.Column("cap_amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_platform_admin_id", sa.String(length=36), sa.ForeignKey("platform_admin_memberships.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", name="uq_billing_overage_policies_company"),
    )
    op.create_index("ix_billing_overage_policies_company_id", "billing_overage_policies", ["company_id"])


def _extend_legacy_webhook_events() -> None:
    with op.batch_alter_table("payment_webhook_events") as batch:
        batch.add_column(sa.Column("webhook_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("webhook_timestamp", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("provider_payment_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("provider_subscription_id", sa.String(length=255), nullable=True))
    op.create_index("ix_payment_webhook_events_webhook_id", "payment_webhook_events", ["webhook_id"])
    op.create_index("ix_payment_webhook_events_provider_payment_id", "payment_webhook_events", ["provider_payment_id"])
    op.create_index("ix_payment_webhook_events_provider_subscription_id", "payment_webhook_events", ["provider_subscription_id"])


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or value is None:
        return "integer"
    if isinstance(value, str):
        return "string"
    return "json"


def _bulk_insert_missing(
    table_name: str,
    table: sa.TableClause,
    rows: list[dict[str, object]],
    *,
    key_columns: tuple[str, ...],
) -> None:
    if not rows:
        return
    conn = op.get_bind()
    missing: list[dict[str, object]] = []
    predicate = " AND ".join(f"{column} = :{column}" for column in key_columns)
    query = sa.text(f"SELECT 1 FROM {table_name} WHERE {predicate} LIMIT 1")
    for row in rows:
        params = {column: row[column] for column in key_columns}
        if conn.execute(query, params).first() is None:
            missing.append(row)
    if missing:
        op.bulk_insert(table, missing)


def _seed_catalog() -> None:
    now = datetime.now(UTC)
    plan_table = sa.table(
        "billing_plan_versions",
        sa.column("id", sa.String),
        sa.column("plan_code", sa.String),
        sa.column("version", sa.String),
        sa.column("segment", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.Text),
        sa.column("status", sa.String),
        sa.column("publicly_visible", sa.Boolean),
        sa.column("trial_eligible", sa.Boolean),
        sa.column("feature_summary_json", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    _bulk_insert_missing(
        "billing_plan_versions",
        plan_table,
        [
            {
                "id": _id("bpv", code),
                "plan_code": code,
                "version": CATALOG_VERSION,
                "segment": segment,
                "display_name": name,
                "description": description,
                "status": "active",
                "publicly_visible": publicly_visible,
                "trial_eligible": trial_eligible,
                "feature_summary_json": {},
                "created_at": now,
                "updated_at": now,
            }
            for code, segment, name, description, publicly_visible, trial_eligible in PLAN_ROWS
        ],
        key_columns=("plan_code", "version"),
    )
    price_table = sa.table(
        "billing_plan_prices",
        sa.column("id", sa.String),
        sa.column("plan_version_id", sa.String),
        sa.column("currency", sa.String),
        sa.column("amount_minor", sa.Integer),
        sa.column("interval", sa.String),
        sa.column("tax_behavior", sa.String),
        sa.column("tax_rate_bps", sa.Integer),
        sa.column("provider_plan_reference", sa.String),
        sa.column("provider_plan_id", sa.String),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("effective_until", sa.DateTime(timezone=True)),
    )
    price_records = []
    for code, rows in PRICE_ROWS.items():
        for amount, interval, tax_behavior in rows:
            price_records.append(
                {
                    "id": _id("bpp", f"{code}-{interval}"),
                    "plan_version_id": _id("bpv", code),
                    "currency": "INR",
                    "amount_minor": amount,
                    "interval": interval,
                    "tax_behavior": tax_behavior,
                    "tax_rate_bps": GST_BPS,
                    "provider_plan_reference": f"{CATALOG_VERSION}:{code}:{interval}",
                    "provider_plan_id": None,
                    "effective_from": now,
                    "effective_until": None,
                }
            )
    _bulk_insert_missing(
        "billing_plan_prices",
        price_table,
        price_records,
        key_columns=("id",),
    )

    entitlement_table = sa.table(
        "billing_plan_entitlements",
        sa.column("id", sa.String),
        sa.column("plan_version_id", sa.String),
        sa.column("entitlement_key", sa.String),
        sa.column("value_type", sa.String),
        sa.column("value_json", sa.JSON),
    )
    ent_records = []
    for code, entitlements in ENTITLEMENTS.items():
        for key, value in entitlements.items():
            ent_records.append(
                {
                    "id": str(uuid4()),
                    "plan_version_id": _id("bpv", code),
                    "entitlement_key": key,
                    "value_type": _value_type(value),
                    "value_json": value,
                }
            )
    _bulk_insert_missing(
        "billing_plan_entitlements",
        entitlement_table,
        ent_records,
        key_columns=("plan_version_id", "entitlement_key"),
    )


def _seed_grandfathered_subscriptions() -> None:
    conn = op.get_bind()
    now = datetime.now(UTC)
    period_end = now + timedelta(days=3650)
    rows = conn.execute(
        sa.text(
            "SELECT id, primary_contact_email, billing_contact_name, billing_contact_email, "
            "company_type FROM companies WHERE is_active = true"
        )
    ).mappings()
    for company in rows:
        existing = conn.execute(
            sa.text("SELECT id FROM billing_subscriptions WHERE company_id = :company_id LIMIT 1"),
            {"company_id": company["id"]},
        ).first()
        if existing:
            continue
        account_id = str(uuid4())
        subscription_id = str(uuid4())
        conn.execute(
            sa.text(
                "INSERT INTO billing_accounts "
                "(id, company_id, billing_email, billing_name, created_at, updated_at) "
                "VALUES (:id, :company_id, :email, :name, :created_at, :updated_at)"
            ),
            {
                "id": account_id,
                "company_id": company["id"],
                "email": company["billing_contact_email"] or company["primary_contact_email"],
                "name": company["billing_contact_name"],
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO billing_subscriptions "
                "(id, company_id, billing_account_id, plan_version_id, status, segment, "
                "billing_interval, current_period_start, current_period_end, "
                "cancel_at_period_end, provider, source, externally_billable, "
                "created_at, updated_at) "
                "VALUES (:id, :company_id, :account_id, :plan_version_id, "
                "'manual_active', :segment, 'custom', :period_start, :period_end, "
                ":cancel_at_period_end, 'manual', 'migration', :externally_billable, "
                ":created_at, :updated_at)"
            ),
            {
                "id": subscription_id,
                "company_id": company["id"],
                "account_id": account_id,
                "plan_version_id": _id("bpv", "grandfathered_free"),
                "segment": company["company_type"] or "internal",
                "period_start": now,
                "period_end": period_end,
                "cancel_at_period_end": False,
                "externally_billable": False,
                "created_at": now,
                "updated_at": now,
            },
        )
        conn.execute(
            sa.text(
                "INSERT INTO billing_subscription_items "
                "(id, subscription_id, item_code, item_type, quantity, amount_minor, "
                "currency, interval, status, created_at, updated_at) "
                "VALUES (:id, :subscription_id, 'grandfathered_free', 'base_plan', 1, "
                "0, 'INR', 'custom', 'active', :created_at, :updated_at)"
            ),
            {
                "id": str(uuid4()),
                "subscription_id": subscription_id,
                "created_at": now,
                "updated_at": now,
            },
        )


def _seed_configured_founder() -> None:
    email = (os.environ.get("CASEOPS_PLATFORM_SUPER_ADMIN_EMAIL") or "").strip().lower()
    if not email:
        return
    conn = op.get_bind()
    user = conn.execute(
        sa.text(
            "SELECT users.id FROM users "
            "JOIN company_memberships ON company_memberships.user_id = users.id "
            "WHERE lower(users.email) = :email "
            "AND users.is_active = true "
            "AND company_memberships.role = 'owner' "
            "AND company_memberships.is_active = true "
            "LIMIT 1"
        ),
        {"email": email},
    ).first()
    if user is None:
        return
    now = datetime.now(UTC)
    existing = conn.execute(
        sa.text("SELECT id FROM platform_admin_memberships WHERE user_id = :user_id LIMIT 1"),
        {"user_id": user.id},
    ).first()
    if existing:
        conn.execute(
            sa.text(
                "UPDATE platform_admin_memberships SET status='active', role='super_admin', "
                "capabilities_json=:capabilities, updated_at=:updated_at WHERE id=:id"
            ),
            {
                "id": existing.id,
                "capabilities": json.dumps(PLATFORM_CAPABILITIES),
                "updated_at": now,
            },
        )
        return
    conn.execute(
        sa.text(
            "INSERT INTO platform_admin_memberships "
            "(id, user_id, role, capabilities_json, status, mfa_required, "
            "created_at, updated_at) "
            "VALUES (:id, :user_id, 'super_admin', :capabilities, 'active', :mfa_required, "
            ":created_at, :updated_at)"
        ),
        {
            "id": str(uuid4()),
            "user_id": user.id,
            "capabilities": json.dumps(PLATFORM_CAPABILITIES),
            "mfa_required": False,
            "created_at": now,
            "updated_at": now,
        },
    )
