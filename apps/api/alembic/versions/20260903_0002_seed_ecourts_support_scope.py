"""Seed the reviewed provider-wide eCourtsIndia support scope.

Revision ID: 20260903_0002
Revises: 20260903_0001

DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260903_0002"
down_revision = "20260903_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCOPE_ID = "6ed0fbb0-fd79-49e0-9a33-202609030002"
_EVIDENCE_REF = "https://ecourtsindia.com/api/docs;https://ecourtsindia.com/api/pricing"


def upgrade() -> None:
    now = datetime.now(UTC)
    support_matrix = sa.table(
        "case_tracking_support_matrix",
        sa.column("id", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("court", sa.String()),
        sa.column("bench_jurisdiction", sa.String()),
        sa.column("lookup_method", sa.String()),
        sa.column("refresh_cost_minor", sa.Integer()),
        sa.column("bulk_refresh_cost_minor", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("rate_limit", sa.String()),
        sa.column("freshness_sla", sa.String()),
        sa.column("legal_tos_status", sa.String()),
        sa.column("failure_code_mapping_json", sa.JSON()),
        sa.column("enabled", sa.Boolean()),
        sa.column("tenant_visible", sa.Boolean()),
        sa.column("status_notes", sa.Text()),
        sa.column("evidence_ref", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        support_matrix,
        [
            {
                "id": _SCOPE_ID,
                "provider": "ecourtsindia",
                "court": "*",
                "bench_jurisdiction": "All provider-published Indian courts and tribunals",
                "lookup_method": "cnr_or_case_number",
                "refresh_cost_minor": 15,
                "bulk_refresh_cost_minor": 15,
                "currency": "INR",
                "rate_limit": "100/minute; 3,000/hour; 50,000/day; concurrency 10",
                "freshness_sla": "Daily tracked-case refresh at 16:30 Asia/Kolkata",
                "legal_tos_status": "approved",
                "failure_code_mapping_json": {
                    "401": "authentication_failed",
                    "402": "billing_exhausted",
                    "404": "case_not_found",
                    "429": "rate_limited",
                    "5xx": "provider_unavailable",
                },
                "enabled": True,
                "tenant_visible": True,
                "status_notes": (
                    "Provider-wide scope derived from the reviewed eCourtsIndia partner "
                    "API contract; exact court-specific rows override this fallback."
                ),
                "evidence_ref": _EVIDENCE_REF,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM case_tracking_support_matrix WHERE id = :scope_id").bindparams(
            scope_id=_SCOPE_ID
        )
    )
