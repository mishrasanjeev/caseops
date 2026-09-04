"""Make automatic next-hearing sync fail-closed and concurrency safe.

Revision ID: 20260904_0001
Revises: 20260903_0002

DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260904_0001"
down_revision = "20260903_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _court_name_identity(case_number: str, court_name: str) -> str:
    normalized_case = re.sub(r"\s+", " ", case_number).strip().upper()
    normalized_court = re.sub(r"[^A-Za-z0-9]+", " ", court_name).strip().upper()
    normalized_court = re.sub(r"\s+", " ", normalized_court)
    digest = hashlib.sha256(normalized_court.encode("utf-8")).hexdigest()[:24]
    return f"case:{normalized_case}|court-name:{digest}"


def upgrade() -> None:
    bind = op.get_bind()
    tracked_cases = sa.table(
        "tracked_cases",
        sa.column("id", sa.String()),
        sa.column("company_id", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("identity_key", sa.String()),
        sa.column("case_number", sa.String()),
        sa.column("court_name", sa.String()),
    )
    rows = list(
        bind.execute(
            sa.select(
                tracked_cases.c.id,
                tracked_cases.c.company_id,
                tracked_cases.c.provider,
                tracked_cases.c.case_number,
                tracked_cases.c.court_name,
            ).where(
                tracked_cases.c.identity_key.like("%|court:UNKNOWN"),
                tracked_cases.c.case_number.is_not(None),
                tracked_cases.c.court_name.is_not(None),
            )
        ).mappings()
    )
    for row in rows:
        identity_key = _court_name_identity(row["case_number"], row["court_name"])
        collision = bind.scalar(
            sa.select(tracked_cases.c.id).where(
                tracked_cases.c.company_id == row["company_id"],
                tracked_cases.c.provider == row["provider"],
                tracked_cases.c.identity_key == identity_key,
                tracked_cases.c.id != row["id"],
            )
        )
        if collision is None:
            bind.execute(
                tracked_cases.update()
                .where(tracked_cases.c.id == row["id"])
                .values(identity_key=identity_key)
            )

    operations = sa.table(
        "tracked_case_provider_operations",
        sa.column("id", sa.String()),
        sa.column("tracked_case_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("response_class", sa.String()),
        sa.column("error_redacted", sa.Text()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    running = list(
        bind.execute(
            sa.select(
                operations.c.id,
                operations.c.tracked_case_id,
                operations.c.created_at,
            )
            .where(operations.c.status == "running")
            .order_by(operations.c.tracked_case_id, operations.c.created_at.desc())
        ).mappings()
    )
    seen: set[str] = set()
    now = datetime.now(UTC)
    for row in running:
        tracked_case_id = row["tracked_case_id"]
        if tracked_case_id not in seen:
            seen.add(tracked_case_id)
            continue
        bind.execute(
            operations.update()
            .where(operations.c.id == row["id"])
            .values(
                status="failed",
                response_class="concurrent_refresh",
                error_redacted="Superseded duplicate running refresh.",
                completed_at=now,
                updated_at=now,
            )
        )

    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "uq_tracking_operation_one_running",
                "tracked_case_provider_operations",
                ["tracked_case_id"],
                unique=True,
                postgresql_concurrently=True,
                postgresql_where=sa.text("status = 'running'"),
            )
    else:
        # MIGRATION-LOCK-RISK: acknowledged: non-PostgreSQL paths are isolated
        # development/test databases and never serve concurrent production writes.
        op.create_index(
            "uq_tracking_operation_one_running",
            "tracked_case_provider_operations",
            ["tracked_case_id"],
            unique=True,
            sqlite_where=sa.text("status = 'running'"),
        )
    op.execute(
        sa.text(
            "UPDATE case_tracking_support_matrix "
            "SET freshness_sla = :freshness_sla, updated_at = :updated_at "
            "WHERE provider = 'ecourtsindia' AND court = '*'"
        ).bindparams(
            freshness_sla="Daily tracked-case refresh at 18:00 Asia/Kolkata",
            updated_at=now,
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.drop_index(
                "uq_tracking_operation_one_running",
                table_name="tracked_case_provider_operations",
                postgresql_concurrently=True,
            )
    else:
        op.drop_index(
            "uq_tracking_operation_one_running",
            table_name="tracked_case_provider_operations",
        )
    op.execute(
        sa.text(
            "UPDATE case_tracking_support_matrix "
            "SET freshness_sla = :freshness_sla, updated_at = :updated_at "
            "WHERE provider = 'ecourtsindia' AND court = '*'"
        ).bindparams(
            freshness_sla="Daily tracked-case refresh at 16:30 Asia/Kolkata",
            updated_at=datetime.now(UTC),
        )
    )
