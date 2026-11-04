# ruff: noqa: E501
"""Publish the 2026.11.v1 SaaS plan catalog.

Adds a new catalog version beside 2026.05.v1 instead of mutating it: existing
subscriptions keep their plan_version_id and its entitlements. The new version
cuts tracked-case allowances to what the eCourtsIndia refresh ceiling can fund,
adds a per-plan ``provider_spend_monthly_minor`` budget, sets annual prices to
ten months, and omits entitlement keys the product does not enforce
(case_refresh_cadence, api_access_enabled, audit_export_enabled, sso_enabled).
Decision record: docs/PRICING_COMPETITIVE_REVIEW_2026-11-04.md.

Revision ID: 20261104_0001
Revises: 20261102_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Inserts about 200 catalog rows into three
small reference tables; no DDL, no index build, no rewrite of existing rows.
MIGRATION-ROLLBACK: restore-forward. Subscriptions may reference the new
catalog rows as soon as it ships, so downgrade refuses; restore the reviewed backup.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20261104_0001"
down_revision = "20261102_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")

CATALOG_VERSION = "2026.11.v1"
GST_BPS = 1800
GIB = 1024**3
MIB = 1024**2


def _id(prefix: str, code: str, *, max_length: int = 36) -> str:
    raw = f"{prefix}-{code.replace('_', '-')}-202611"
    if len(raw) <= max_length:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    head_length = max_length - len(digest) - 1
    return f"{raw[:head_length].rstrip('-')}-{digest}"


# (code, segment, display name, description, publicly visible, trial eligible)
PLAN_ROWS = [
    ("trial", "trial", "Free Trial", "14-day trial, no card required.", False, True),
    ("solo_core", "solo", "Solo Core", "For an advocate with one clerk.", True, True),
    ("solo_pro", "solo", "Solo Pro", "For an advocate with a small chamber team.", True, True),
    ("solo_elite", "solo", "Solo Elite", "For a high-volume chamber.", True, True),
    ("firm_starter", "firm", "Firm Starter", "For a small firm.", True, True),
    ("firm_growth", "firm", "Firm Growth", "For a growing litigation firm.", True, True),
    ("firm_pro", "firm", "Firm Pro", "For a large firm.", True, False),
    ("firm_enterprise", "firm", "Firm Enterprise", "Custom firm contract.", True, False),
    ("gc_monitoring", "gc", "Litigation Monitoring", "Court tracking and alerts for a corporate legal team.", True, False),
    ("gc_starter", "gc", "GC Starter", "Matters, tracking and drafting for a corporate legal team.", True, False),
    ("gc_professional", "gc", "GC Professional", "For a mature corporate legal function.", True, False),
    ("gc_enterprise", "gc", "GC Enterprise", "Custom corporate legal contract.", True, False),
    ("grandfathered_free", "internal", "Grandfathered Free", "Non-billable migration subscription for existing tenants.", False, False),
    ("addon_user_firm", "add_on", "Extra firm user", "1 additional internal user.", True, False),
    ("addon_user_corporate_legal", "add_on", "Extra corporate legal user", "1 additional legal/admin user.", True, False),
    ("addon_viewer", "add_on", "Extra viewer/business user", "1 viewer.", True, False),
    ("addon_cases_500", "add_on", "Tracked case pack 500", "500 additional tracked cases with scheduled refresh.", True, False),
    ("addon_cases_1000", "add_on", "Tracked case pack 1000", "1,000 additional tracked cases with scheduled refresh.", True, False),
    ("addon_ai_250", "add_on", "AI credit pack 250", "250 credits, 12-month expiry.", True, False),
    ("addon_ai_1000", "add_on", "AI credit pack 1000", "1,000 credits, 12-month expiry.", True, False),
    ("addon_ai_5000", "add_on", "AI credit pack 5000", "5,000 credits, 12-month expiry.", True, False),
    ("addon_storage_100gb", "add_on", "Extra storage 100 GB", "100 GB additional storage.", True, False),
    # Not sellable: no tenant API-key feature exists yet.
    ("addon_api_access", "add_on", "API access", "Not available yet.", False, False),
    ("addon_migration_basic", "add_on", "Basic migration", "CSV import and guided setup.", True, False),
    ("addon_migration_firm", "add_on", "Firm migration", "Matter, client, and document import assistance.", True, False),
    ("addon_migration_enterprise", "add_on", "Enterprise migration", "Custom mapping, QA, and launch support.", True, False),
    ("addon_research_memo", "add_on", "Legal research memo", "Human/editor-assisted memo.", True, False),
]

# Minor units (paise). Annual monthly-plan prices are ten months (two months free).
PRICE_ROWS = {
    "trial": [(0, "one_time", "inclusive")],
    "solo_core": [(99900, "month", "inclusive"), (999000, "year", "inclusive")],
    "solo_pro": [(199900, "month", "inclusive"), (1999000, "year", "inclusive")],
    "solo_elite": [(399900, "month", "inclusive"), (3999000, "year", "inclusive")],
    "firm_starter": [(599900, "month", "exclusive"), (5999000, "year", "exclusive")],
    "firm_growth": [(1799900, "month", "exclusive"), (17999000, "year", "exclusive")],
    "firm_pro": [(4999900, "month", "exclusive"), (49999000, "year", "exclusive")],
    "firm_enterprise": [(None, "custom", "exclusive")],
    "gc_monitoring": [(15000000, "year", "exclusive")],
    "gc_starter": [(30000000, "year", "exclusive")],
    "gc_professional": [(80000000, "year", "exclusive")],
    "gc_enterprise": [(None, "custom", "exclusive")],
    "grandfathered_free": [(0, "custom", "exclusive")],
    "addon_user_firm": [(69900, "month", "exclusive")],
    "addon_user_corporate_legal": [(150000, "month", "exclusive")],
    "addon_viewer": [(19900, "month", "exclusive")],
    "addon_cases_500": [(499900, "month", "exclusive")],
    "addon_cases_1000": [(899900, "month", "exclusive")],
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


def _plan(
    users: int,
    viewers: int,
    matters: int,
    tracked: int,
    credits: int,
    storage: int,
    manual_refreshes: int,
    provider_spend_minor: int,
) -> dict[str, object]:
    return {
        "users_internal_limit": users,
        "users_viewer_limit": viewers,
        "matters_active_limit": matters,
        "tracked_cases_limit": tracked,
        "ai_credits_monthly": credits,
        "storage_bytes_limit": storage,
        "manual_case_refreshes_daily": manual_refreshes,
        # Shared Indian Kanoon + eCourtsIndia budget per calendar month. Sized
        # to fund six refreshes per tracked case at INR 1.65 plus research.
        "provider_spend_monthly_minor": provider_spend_minor,
    }


_UNLIMITED = {
    "users_internal_limit": None,
    "users_viewer_limit": None,
    "matters_active_limit": None,
    "tracked_cases_limit": None,
    "ai_credits_monthly": None,
    "storage_bytes_limit": None,
    "manual_case_refreshes_daily": None,
}

ENTITLEMENTS: dict[str, dict[str, object]] = {
    "trial": _plan(2, 0, 10, 10, 50, 500 * MIB, 2, 30_000),
    "solo_core": _plan(2, 0, 50, 15, 100, 5 * GIB, 5, 60_000),
    "solo_pro": _plan(4, 0, 250, 40, 250, 20 * GIB, 10, 100_000),
    "solo_elite": _plan(6, 0, 1000, 120, 600, 50 * GIB, 25, 200_000),
    "firm_starter": _plan(5, 0, 300, 150, 500, 25 * GIB, 10, 250_000),
    "firm_growth": _plan(15, 10, 1500, 400, 1500, 150 * GIB, 50, 500_000),
    "firm_pro": _plan(50, 50, 5000, 1000, 3500, 500 * GIB, 150, 1_100_000),
    "gc_monitoring": _plan(3, 25, 500, 750, 600, 50 * GIB, 100, 850_000),
    "gc_starter": _plan(5, 25, 1000, 1500, 2500, 250 * GIB, 150, 1_600_000),
    "gc_professional": _plan(15, 100, 10000, 4000, 8000, 1024 * GIB, 500, 4_100_000),
    # Custom contracts keep the default provider budget until operations set
    # an explicit company provider spend policy for the signed order form.
    "firm_enterprise": dict(_UNLIMITED),
    "gc_enterprise": dict(_UNLIMITED),
    "grandfathered_free": dict(_UNLIMITED),
    "addon_user_firm": {"users_internal_limit": 1},
    "addon_user_corporate_legal": {"users_internal_limit": 1},
    "addon_viewer": {"users_viewer_limit": 1},
    "addon_cases_500": {"tracked_cases_limit": 500, "provider_spend_monthly_minor": 500_000},
    "addon_cases_1000": {"tracked_cases_limit": 1000, "provider_spend_monthly_minor": 1_000_000},
    "addon_ai_250": {"ai_credits_topup": 250, "expires_after_months": 12},
    "addon_ai_1000": {"ai_credits_topup": 1000, "expires_after_months": 12},
    "addon_ai_5000": {"ai_credits_topup": 5000, "expires_after_months": 12},
    "addon_storage_100gb": {"storage_bytes_limit": 100 * GIB},
    "addon_api_access": {},
    "addon_migration_basic": {},
    "addon_migration_firm": {},
    "addon_migration_enterprise": {},
    "addon_research_memo": {},
}


def _value_type(value: object) -> str:
    # Same classification as the 2026.05.v1 seed (None is an unlimited integer).
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) or value is None:
        return "integer"
    if isinstance(value, str):
        return "string"
    return "json"


def upgrade() -> None:
    now = datetime.now(UTC)
    conn = op.get_bind()
    existing = conn.execute(
        sa.text("SELECT 1 FROM billing_plan_versions WHERE version = :version LIMIT 1"),
        {"version": CATALOG_VERSION},
    ).first()
    if existing is not None:
        return

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
    op.bulk_insert(
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
    op.bulk_insert(
        price_table,
        [
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
            for code, rows in PRICE_ROWS.items()
            for amount, interval, tax_behavior in rows
        ],
    )

    entitlement_table = sa.table(
        "billing_plan_entitlements",
        sa.column("id", sa.String),
        sa.column("plan_version_id", sa.String),
        sa.column("entitlement_key", sa.String),
        sa.column("value_type", sa.String),
        sa.column("value_json", sa.JSON),
    )
    op.bulk_insert(
        entitlement_table,
        [
            {
                "id": str(uuid4()),
                "plan_version_id": _id("bpv", code),
                "entitlement_key": key,
                "value_type": _value_type(value),
                "value_json": value,
            }
            for code, entitlements in ENTITLEMENTS.items()
            for key, value in entitlements.items()
        ],
    )


def downgrade() -> None:
    raise RuntimeError("Pricing catalog 2026.11.v1 is restore-forward; restore the reviewed backup.")
