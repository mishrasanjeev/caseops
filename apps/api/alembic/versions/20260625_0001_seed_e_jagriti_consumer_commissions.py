"""Seed e-Jagriti consumer commission forum catalog.

Revision ID: 20260625_0001
Revises: 20260624_0001
Create Date: 2026-06-25
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision = "20260625_0001"
down_revision = "20260624_0001"
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


_SOURCE_NAME = "e-Jagriti master commission directory"
_DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "caseops_api"
    / "scripts"
    / "seed_data"
    / "e_jagriti_consumer_commissions.json"
)
_BASELINE_CONSUMER_IDS = (
    "consumer:ncdrc",
    "consumer:scdrc:delhi",
    "consumer:scdrc:maharashtra",
    "consumer:scdrc:karnataka",
    "consumer:dcdrc:central-delhi",
    "consumer:dcdrc:mumbai",
    "consumer:dcdrc:bengaluru-urban",
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


def _load_seed() -> dict[str, object]:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _validate_seed(seed: dict[str, object]) -> None:
    validation = seed.get("validation")
    if not isinstance(validation, dict):
        raise RuntimeError("e-Jagriti consumer commission seed is missing validation.")
    expected = {
        "state_count": 36,
        "all_commission_row_count": 55,
        "state_detail_total_row_count": 730,
        "district_commission_row_count": 676,
    }
    for key, value in expected.items():
        if validation.get(key) != value:
            raise RuntimeError(f"e-Jagriti seed failed {key} validation.")
    if validation.get("states_without_district_commissions") != []:
        raise RuntimeError("e-Jagriti seed has states without DCDRC rows.")


def _state_entry_name(state_name: str, commission: dict[str, object]) -> str:
    official = str(commission.get("official_name") or "").strip()
    if int(commission.get("circuit_addition_bench_status") or 0) == 1:
        return f"{official.title()} - {state_name} SCDRC"
    return f"{state_name} State Consumer Disputes Redressal Commission"


def _district_entry_name(district_name: str) -> str:
    return f"{district_name} District Consumer Disputes Redressal Commission"


def _upsert_entry(conn: sa.Connection, table: sa.Table, entry: dict[str, object]) -> None:
    update_values = {key: value for key, value in entry.items() if key not in {"id", "created_at"}}
    result = conn.execute(table.update().where(table.c.id == entry["id"]).values(**update_values))
    if result.rowcount == 0:
        conn.execute(table.insert().values(**entry))


def upgrade() -> None:
    seed = _load_seed()
    _validate_seed(seed)

    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)

    conn.execute(
        table.update()
        .where(table.c.forum_type == "consumer_forum")
        .values(is_active=False, updated_at=now)
    )

    national_url = str(seed.get("all_commissions_url") or seed.get("source_home_url") or "")
    _upsert_entry(
        conn,
        table,
        {
            "id": "consumer:ncdrc",
            "parent_id": None,
            "court_id": None,
            "name": "National Consumer Disputes Redressal Commission",
            "forum_type": "consumer_forum",
            "forum_level": "tribunal",
            "state": None,
            "district": None,
            "city": "New Delhi",
            "consumer_level": "national",
            "source_name": _SOURCE_NAME,
            "source_url": national_url,
            "lineage": "Consumer Forum > NCDRC",
            "display_order": 200,
            "is_active": True,
            "created_at": now,
            "updated_at": now,
        },
    )

    states = seed.get("states")
    if not isinstance(states, list):
        raise RuntimeError("e-Jagriti consumer commission seed is missing states.")

    seen_ids = {"consumer:ncdrc"}
    for state_index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            continue
        state_name = str(state.get("state_name") or "").strip()
        source_url = str(state.get("source_url") or seed.get("source_home_url") or "")
        state_commissions = state.get("state_commissions")
        district_commissions = state.get("district_commissions")
        if (
            not state_name
            or not isinstance(state_commissions, list)
            or not isinstance(district_commissions, list)
        ):
            continue

        main_state_entry_id: str | None = None
        for commission_index, commission in enumerate(state_commissions, start=1):
            if not isinstance(commission, dict):
                continue
            commission_id = int(commission.get("commission_id") or 0)
            if commission_id <= 0:
                continue
            entry_id = f"consumer:scdrc:{commission_id}"
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            if main_state_entry_id is None:
                main_state_entry_id = entry_id
            name = _state_entry_name(state_name, commission)
            _upsert_entry(
                conn,
                table,
                {
                    "id": entry_id,
                    "parent_id": "consumer:ncdrc",
                    "court_id": None,
                    "name": name,
                    "forum_type": "consumer_forum",
                    "forum_level": "tribunal",
                    "state": state_name,
                    "district": None,
                    "city": None,
                    "consumer_level": "state",
                    "source_name": _SOURCE_NAME,
                    "source_url": str(commission.get("source_url") or source_url),
                    "lineage": f"Consumer Forum > SCDRC > {state_name}",
                    "display_order": 2000 + state_index * 100 + commission_index,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )

        if main_state_entry_id is None:
            raise RuntimeError(f"e-Jagriti seed missing SCDRC row for {state_name}.")

        for district_index, commission in enumerate(district_commissions, start=1):
            if not isinstance(commission, dict):
                continue
            commission_id = int(commission.get("commission_id") or 0)
            district_name = str(commission.get("district_name") or "").strip()
            if commission_id <= 0 or not district_name:
                continue
            entry_id = f"consumer:dcdrc:{commission_id}"
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            name = _district_entry_name(district_name)
            _upsert_entry(
                conn,
                table,
                {
                    "id": entry_id,
                    "parent_id": main_state_entry_id,
                    "court_id": None,
                    "name": name,
                    "forum_type": "consumer_forum",
                    "forum_level": "tribunal",
                    "state": state_name,
                    "district": district_name,
                    "city": None,
                    "consumer_level": "district",
                    "source_name": _SOURCE_NAME,
                    "source_url": str(commission.get("source_url") or source_url),
                    "lineage": f"Consumer Forum > DCDRC > {state_name} > {district_name}",
                    "display_order": 100000 + state_index * 1000 + district_index,
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                },
            )


def downgrade() -> None:
    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)
    conn.execute(
        table.update()
        .where(table.c.source_name == _SOURCE_NAME)
        .values(is_active=False, updated_at=now)
    )
    conn.execute(
        table.update()
        .where(table.c.id.in_(_BASELINE_CONSUMER_IDS))
        .values(is_active=True, updated_at=now)
    )
