"""Complete Delhi district court forum catalog.

Revision ID: 20260623_0001
Revises: 20260613_0001
Create Date: 2026-06-23
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260623_0001"
down_revision = "20260613_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)


_SOURCE_NAME = "CaseOps LW-S4 baseline forum catalog"
_SOURCE_URL = (
    "docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md"
    "#slice-lw-s4-forum-hierarchy"
)


def _catalog_table() -> sa.Table:
    return sa.table(
        "forum_catalog_entries",
        sa.column("id", sa.String),
        sa.column("parent_id", sa.String),
        sa.column("court_id", sa.String),
        sa.column("name", sa.String),
        sa.column("forum_type", sa.String),
        sa.column("forum_level", sa.String),
        sa.column("state", sa.String),
        sa.column("district", sa.String),
        sa.column("city", sa.String),
        sa.column("consumer_level", sa.String),
        sa.column("source_name", sa.String),
        sa.column("source_url", sa.String),
        sa.column("lineage", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )


def _entry(
    entry_id: str,
    name: str,
    district: str,
    city: str,
    display_order: int,
    now: datetime,
) -> dict[str, object]:
    return {
        "id": entry_id,
        "parent_id": None,
        "court_id": None,
        "name": name,
        "forum_type": "district_court",
        "forum_level": "lower_court",
        "state": "Delhi",
        "district": district,
        "city": city,
        "consumer_level": None,
        "source_name": _SOURCE_NAME,
        "source_url": _SOURCE_URL,
        "lineage": f"District Court > Delhi > {district} > {city}",
        "display_order": display_order,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _delhi_entries(now: datetime) -> list[dict[str, object]]:
    return [
        _entry(
            "district:delhi:central",
            "Tis Hazari Courts Complex",
            "Central & West",
            "Tis Hazari",
            100,
            now,
        ),
        _entry(
            "district:delhi:new-delhi",
            "Patiala House Courts Complex",
            "New Delhi",
            "New Delhi",
            101,
            now,
        ),
        _entry(
            "district:delhi:karkardooma",
            "Karkardooma Courts Complex",
            "East, North-East & Shahdara",
            "Karkardooma",
            102,
            now,
        ),
        _entry(
            "district:delhi:rohini",
            "Rohini Courts Complex",
            "North & North-West",
            "Rohini",
            103,
            now,
        ),
        _entry(
            "district:delhi:dwarka",
            "Dwarka Courts Complex",
            "South-West",
            "Dwarka",
            104,
            now,
        ),
        _entry(
            "district:delhi:south",
            "Saket Courts Complex",
            "South & South-East",
            "Saket",
            105,
            now,
        ),
        _entry(
            "district:delhi:rouse-avenue",
            "Rouse Avenue Courts Complex",
            "Special Courts / Central",
            "Rouse Avenue",
            106,
            now,
        ),
    ]


def _upsert_entry(conn: sa.Connection, table: sa.Table, entry: dict[str, object]) -> None:
    update_values = {
        key: value for key, value in entry.items() if key not in {"id", "created_at"}
    }
    result = conn.execute(
        table.update().where(table.c.id == entry["id"]).values(**update_values)
    )
    if result.rowcount == 0:
        conn.execute(table.insert().values(**entry))


def upgrade() -> None:
    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)
    for entry in _delhi_entries(now):
        _upsert_entry(conn, table, entry)


def downgrade() -> None:
    conn = op.get_bind()
    table = _catalog_table()
    conn.execute(
        table.delete().where(
            table.c.id.in_(
                [
                    "district:delhi:karkardooma",
                    "district:delhi:rohini",
                    "district:delhi:dwarka",
                    "district:delhi:rouse-avenue",
                ]
            )
        )
    )
    now = datetime.now(UTC)
    for entry in [
        _entry(
            "district:delhi:central",
            "Central District Court, Delhi",
            "Central",
            "New Delhi",
            100,
            now,
        ),
        _entry(
            "district:delhi:new-delhi",
            "New Delhi District Court",
            "New Delhi",
            "New Delhi",
            101,
            now,
        ),
        _entry(
            "district:delhi:south",
            "South District Court, Delhi",
            "South",
            "Saket",
            102,
            now,
        ),
    ]:
        update_values = {
            key: value
            for key, value in entry.items()
            if key not in {"id", "created_at"}
        }
        conn.execute(
            table.update().where(table.c.id == entry["id"]).values(**update_values)
        )
