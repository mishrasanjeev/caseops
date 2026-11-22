"""Add the paid "IP workspace" add-on to catalog 2026.11.v1.

Owner decision 2026-11-22: IP workspace is sold as an add-on at Rs 9,999 a month
or Rs 99,990 a year (ten months), GST-exclusive like the other Firm and GC
add-ons. Only a Firm or GC base plan may carry it; Solo, trial and internal
plans may not. ``feature_summary_json.eligible_segments`` records that rule and
``billing_entitlements.resolve_entitlements`` enforces it, so the add-on grants
nothing on an ineligible plan. It grants exactly the entitlement keys
``ip_capability_catalog.IP_FEATURES`` gates on, and nothing else.

Revision ID: 20261122_0001
Revises: 20261112_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Inserts one plan, two prices and eight
entitlement rows into three small reference tables; no DDL, no index build, no
rewrite of existing rows.
MIGRATION-ROLLBACK: restore-forward. A subscription item or checkout may
reference the add-on as soon as it ships, so downgrade refuses; restore the
reviewed backup.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20261122_0001"
down_revision = "20261112_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")

CATALOG_VERSION = "2026.11.v1"
PLAN_CODE = "addon_ip_workspace"
PLAN_ID = "bpv-addon-ip-workspace-202611"
GST_BPS = 1800
ELIGIBLE_SEGMENTS = ["firm", "gc"]
# (price id, paise, interval). Annual is ten months, the catalog convention.
PRICES = [
    ("bpp-addon-ip-workspace-month-202611", 999900, "month"),
    ("bpp-addon-ip-workspace-year-202611", 9999000, "year"),
]
# Every key ip_capability_catalog.IP_FEATURES gates on; pinned by a test.
ENTITLEMENT_KEYS = (
    "ip_costs",
    "ip_deadline_automation",
    "ip_filing_operations",
    "ip_notification_automation",
    "ip_registry_sync",
    "ip_rule_governance",
    "ip_watch",
    "ip_workspace",
)


def upgrade() -> None:
    conn = op.get_bind()
    catalog = conn.execute(
        sa.text("SELECT 1 FROM billing_plan_versions WHERE version = :version LIMIT 1"),
        {"version": CATALOG_VERSION},
    ).first()
    if catalog is None:
        raise RuntimeError("catalog 2026.11.v1 must exist before the IP workspace add-on")
    existing = conn.execute(
        sa.text(
            "SELECT 1 FROM billing_plan_versions "
            "WHERE version = :version AND plan_code = :plan_code LIMIT 1"
        ),
        {"version": CATALOG_VERSION, "plan_code": PLAN_CODE},
    ).first()
    if existing is not None:
        return

    now = datetime.now(UTC)
    op.bulk_insert(
        sa.table(
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
        ),
        [
            {
                "id": PLAN_ID,
                "plan_code": PLAN_CODE,
                "version": CATALOG_VERSION,
                "segment": "add_on",
                "display_name": "IP workspace",
                "description": (
                    "Trademark, patent and design dockets, portfolio, renewals, journal "
                    "watch, Madrid, recordals, IP documents and client reporting."
                ),
                "status": "active",
                "publicly_visible": True,
                "trial_eligible": False,
                "feature_summary_json": {"eligible_segments": ELIGIBLE_SEGMENTS},
                "created_at": now,
                "updated_at": now,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
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
        ),
        [
            {
                "id": price_id,
                "plan_version_id": PLAN_ID,
                "currency": "INR",
                "amount_minor": amount,
                "interval": interval,
                "tax_behavior": "exclusive",
                "tax_rate_bps": GST_BPS,
                "provider_plan_reference": f"{CATALOG_VERSION}:{PLAN_CODE}:{interval}",
                "provider_plan_id": None,
                "effective_from": now,
                "effective_until": None,
            }
            for price_id, amount, interval in PRICES
        ],
    )
    op.bulk_insert(
        sa.table(
            "billing_plan_entitlements",
            sa.column("id", sa.String),
            sa.column("plan_version_id", sa.String),
            sa.column("entitlement_key", sa.String),
            sa.column("value_type", sa.String),
            sa.column("value_json", sa.JSON),
        ),
        [
            {
                "id": str(uuid4()),
                "plan_version_id": PLAN_ID,
                "entitlement_key": key,
                "value_type": "boolean",
                "value_json": True,
            }
            for key in ENTITLEMENT_KEYS
        ],
    )


def downgrade() -> None:
    raise RuntimeError("The IP workspace add-on is restore-forward; restore the reviewed backup.")
