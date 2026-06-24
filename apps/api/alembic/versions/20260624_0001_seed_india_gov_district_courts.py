"""Seed India.gov.in district court forum catalog.

Revision ID: 20260624_0001
Revises: 20260623_0001
Create Date: 2026-06-24
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import sqlalchemy as sa

from alembic import op

revision = "20260624_0001"
down_revision = "20260623_0001"
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


_SOURCE_NAME = "India.gov.in District Courts Contact Directory"
_DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "caseops_api"
    / "scripts"
    / "seed_data"
    / "india_gov_district_courts.json"
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


def _slug(value: str) -> str:
    normalized = value.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
    return re.sub(r"-+", "-", normalized).strip("-")


def _site_slug(site_url: str, title: str) -> str:
    try:
        host = urlparse(site_url).hostname or ""
    except ValueError:
        host = ""
    first_label = host.split(".", 1)[0]
    return _slug(first_label or title)


def _entry_id(state_name: str, court: dict[str, object]) -> str:
    base = (
        "district:india-gov:"
        f"{_slug(state_name)}:"
        f"{_site_slug(str(court.get('site_url') or ''), str(court.get('title') or ''))}"
    )
    if len(base) <= 120:
        return base
    digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
    return f"{base[:109]}-{digest}"


def _load_seed() -> dict[str, object]:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def _upsert_entry(conn: sa.Connection, table: sa.Table, entry: dict[str, object]) -> None:
    update_values = {key: value for key, value in entry.items() if key not in {"id", "created_at"}}
    result = conn.execute(table.update().where(table.c.id == entry["id"]).values(**update_values))
    if result.rowcount == 0:
        conn.execute(table.insert().values(**entry))


def upgrade() -> None:
    seed = _load_seed()
    if seed.get("unfiltered_total") != 724 or seed.get("per_state_total") != 724:
        raise RuntimeError("India.gov.in district court seed failed scrape total validation.")
    validation = seed.get("validation")
    if not isinstance(validation, dict) or validation.get("missing_from_state_count") != 0:
        raise RuntimeError("India.gov.in district court seed failed state coverage validation.")

    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)

    conn.execute(
        table.update()
        .where(table.c.forum_type == "district_court")
        .values(is_active=False, updated_at=now)
    )

    states = seed.get("states")
    if not isinstance(states, list):
        raise RuntimeError("India.gov.in district court seed is missing states.")

    seen_ids: set[str] = set()
    for state_index, state in enumerate(states, start=1):
        if not isinstance(state, dict):
            continue
        state_name = str(state.get("state_name") or "").strip()
        courts = state.get("courts")
        if not state_name or not isinstance(courts, list):
            continue
        for court_index, court in enumerate(courts, start=1):
            if not isinstance(court, dict):
                continue
            title = str(court.get("title") or "").strip()
            district = str(court.get("district_name") or "").strip()
            site_url = str(court.get("site_url") or "").strip()
            if not title or not district:
                continue
            entry_id = _entry_id(state_name, court)
            if entry_id in seen_ids:
                continue
            seen_ids.add(entry_id)
            _upsert_entry(
                conn,
                table,
                {
                    "id": entry_id,
                    "parent_id": None,
                    "court_id": None,
                    "name": title,
                    "forum_type": "district_court",
                    "forum_level": "lower_court",
                    "state": state_name,
                    "district": district,
                    "city": None,
                    "consumer_level": None,
                    "source_name": _SOURCE_NAME,
                    "source_url": site_url or seed.get("source_url"),
                    "lineage": f"District Court > {state_name} > {district} > {title}",
                    "display_order": 1000 + state_index * 1000 + court_index,
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
        .where(table.c.id.like("district:india-gov:%"))
        .values(is_active=False, updated_at=now)
    )
    conn.execute(
        table.update()
        .where(
            table.c.forum_type == "district_court",
            table.c.id.not_like("district:india-gov:%"),
        )
        .values(is_active=True, updated_at=now)
    )
