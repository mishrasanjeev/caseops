"""Add the internal, non-billable ``sales_demo`` plan to catalog 2026.11.v1.

The sales team demonstrates CaseOps from one synthetic-data production
workspace (``caseops-sales-demo``). A platform admin assigns this plan with the
existing manual subscription control (``manual_active``, non-billable). It
carries Firm Growth's working limits, every IP entitlement the IP capability
catalogue gates on, and a zero monthly provider budget, so interactive
Indian Kanoon and eCourtsIndia calls from the workspace are refused before any
external request. It is not publicly visible, not trial-eligible and not sold.
Decision record: the owner accepted the sales demo workspace plan on
2026-11-21.

Revision ID: 20261121_0001
Revises: 20261112_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Inserts one plan, one price and sixteen
entitlement rows into three small reference tables; no DDL, no index build, no
rewrite of existing rows.
MIGRATION-ROLLBACK: restore-forward. A subscription may reference the plan as
soon as it ships, so downgrade refuses; restore the reviewed backup.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20261121_0001"
down_revision = "20261112_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")

CATALOG_VERSION = "2026.11.v1"
PLAN_CODE = "sales_demo"
PLAN_ID = "bpv-sales-demo-202611"
PRICE_ID = "bpp-sales-demo-custom-202611"
GIB = 1024**3

# Firm Growth's working limits; the provider budget is zero by design.
ENTITLEMENTS: dict[str, object] = {
    "users_internal_limit": 15,
    "users_viewer_limit": 10,
    "matters_active_limit": 1500,
    "tracked_cases_limit": 400,
    "ai_credits_monthly": 1500,
    "storage_bytes_limit": 150 * GIB,
    "manual_case_refreshes_daily": 50,
    "provider_spend_monthly_minor": 0,
    # Every key ip_capability_catalog.IP_FEATURES gates on.
    "ip_costs": True,
    "ip_deadline_automation": True,
    "ip_filing_operations": True,
    "ip_notification_automation": True,
    "ip_registry_sync": True,
    "ip_rule_governance": True,
    "ip_watch": True,
    "ip_workspace": True,
}


def _value_type(value: object) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    raise TypeError("unsupported entitlement value")


def upgrade() -> None:
    conn = op.get_bind()
    catalog = conn.execute(
        sa.text("SELECT 1 FROM billing_plan_versions WHERE version = :version LIMIT 1"),
        {"version": CATALOG_VERSION},
    ).first()
    if catalog is None:
        raise RuntimeError("catalog 2026.11.v1 must exist before the sales demo plan")
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
                "segment": "internal",
                "display_name": "Sales Demo (internal)",
                "description": "Non-billable synthetic-data demo workspace. Not for sale.",
                "status": "active",
                "publicly_visible": False,
                "trial_eligible": False,
                "feature_summary_json": {},
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
                "id": PRICE_ID,
                "plan_version_id": PLAN_ID,
                "currency": "INR",
                "amount_minor": 0,
                "interval": "custom",
                "tax_behavior": "exclusive",
                "tax_rate_bps": 1800,
                "provider_plan_reference": f"{CATALOG_VERSION}:{PLAN_CODE}:custom",
                "provider_plan_id": None,
                "effective_from": now,
                "effective_until": None,
            }
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
                "value_type": _value_type(value),
                "value_json": value,
            }
            for key, value in ENTITLEMENTS.items()
        ],
    )


def downgrade() -> None:
    raise RuntimeError("The sales demo plan is restore-forward; restore the reviewed backup.")
