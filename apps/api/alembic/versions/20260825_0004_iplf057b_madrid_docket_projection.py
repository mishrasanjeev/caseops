"""Backfill the canonical docket projection for Madrid records.

Revision ID: 20260825_0004
Revises: 20260825_0003
Create Date: 2026-08-25

IPLF-057B keeps TrademarkInternationalRegistration as the legal fact owner.
This migration repairs the required ip_trademark_particular_versions projection
used by existing docket, cost, document, and deadline services.

MIGRATION-LOCK-RISK: acknowledged: bounded insert-select backfill with no table
rewrite; PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: restore-forward; the compatibility projection is valid data
and is intentionally retained on downgrade.
DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260825_0004"
down_revision = "20260825_0003"
branch_labels = None
depends_on = None


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    records = bind.execute(
        sa.text(
            """
            SELECT r.*
            FROM trademark_international_registrations AS r
            WHERE NOT EXISTS (
                SELECT 1
                FROM ip_trademark_particular_versions AS p
                WHERE p.company_id = r.company_id
                  AND p.docket_id = r.docket_id
                  AND p.version = 1
            )
            ORDER BY r.company_id, r.id
            """
        )
    ).mappings()
    projection = sa.table(
        "ip_trademark_particular_versions",
        sa.column("id", sa.String(36)),
        sa.column("company_id", sa.String(36)),
        sa.column("docket_id", sa.String(36)),
        sa.column("version", sa.Integer()),
        sa.column("form_key", sa.String(80)),
        sa.column("form_version", sa.String(40)),
        sa.column("mark_kind", sa.String(40)),
        sa.column("representation_json", sa.JSON()),
        sa.column("classes_json", sa.JSON()),
        sa.column("use_priority_json", sa.JSON()),
        sa.column("parties_json", sa.JSON()),
        sa.column("agent_json", sa.JSON()),
        sa.column("filing_manifest_json", sa.JSON()),
        sa.column("readiness_status", sa.String(24)),
        sa.column("readiness_errors_json", sa.JSON()),
        sa.column("created_by_membership_id", sa.String(36)),
        sa.column("finalized_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    for row in records:
        classes = list(_json_value(row["classes_json"]) or [])
        goods = dict(_json_value(row["goods_services_json"]) or {})
        priorities = list(_json_value(row["priority_claims_json"]) or [])
        bind.execute(
            sa.insert(projection).values(
                id=str(uuid4()),
                company_id=row["company_id"],
                docket_id=row["docket_id"],
                version=1,
                form_key=row["form_kind"] or "MADRID_RECORD",
                form_version="source-recorded-v1",
                mark_kind="word",
                representation_json={
                    "text": row["mark_name"],
                    "evidence_reference": row["source_reference"],
                },
                classes_json=[
                    {
                        "class_number": class_number,
                        "specification": goods.get(str(class_number), ""),
                    }
                    for class_number in classes
                ],
                use_priority_json={"claims": priorities} if priorities else None,
                parties_json=[{"role": "holder", "name": row["holder_name"]}],
                agent_json=({"name": row["local_agent_name"]} if row["local_agent_name"] else None),
                filing_manifest_json=[
                    {
                        "key": "madrid_source",
                        "label": "Madrid source record",
                        "required": True,
                        "evidence_reference": row["source_reference"],
                    }
                ],
                readiness_status="ready",
                readiness_errors_json=[],
                created_by_membership_id=row["created_by_membership_id"],
                finalized_at=now,
                created_at=now,
            )
        )


def downgrade() -> None:
    # Restore-forward: shared docket readers may already rely on these valid
    # projections, so a revision rollback must not delete them.
    return None
