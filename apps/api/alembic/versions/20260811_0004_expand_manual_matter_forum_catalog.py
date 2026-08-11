"""Expand the manual-matter forum hierarchy and specialist tribunals.

Revision ID: 20260811_0004
Revises: 20260811_0003
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260811_0004"
down_revision = "20260811_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUIREMENT_SOURCE = "Manual Matter Creation Enhancement - 11 Aug 2026"
_REQUIREMENT_URL = "docs/MANUAL_MATTER_FORUM_CATALOG_2026-08-11.md"


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
    forum_type: str,
    lineage: str,
    display_order: int,
    now: datetime,
    *,
    parent_id: str | None = None,
    state: str | None = None,
    district: str | None = None,
    city: str | None = None,
    consumer_level: str | None = None,
    source_name: str = _REQUIREMENT_SOURCE,
    source_url: str = _REQUIREMENT_URL,
) -> dict[str, object]:
    return {
        "id": entry_id,
        "parent_id": parent_id,
        "court_id": None,
        "name": name,
        "forum_type": forum_type,
        "forum_level": "tribunal",
        "state": state,
        "district": district,
        "city": city,
        "consumer_level": consumer_level,
        "source_name": source_name,
        "source_url": source_url,
        "lineage": lineage,
        "display_order": display_order,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def _upsert(conn: sa.Connection, table: sa.Table, entry: dict[str, object]) -> None:
    updates = {key: value for key, value in entry.items() if key not in {"id", "created_at"}}
    result = conn.execute(table.update().where(table.c.id == entry["id"]).values(**updates))
    if result.rowcount == 0:
        conn.execute(table.insert().values(**entry))


def _specialist_entries(now: datetime) -> list[dict[str, object]]:
    drt_source = "Department of Financial Services DRT/DRAT portal"
    drt_url = "https://drt.gov.in/"
    nclt_url = "https://nclt.gov.in/national-company-law-tribunal-benches"
    nclat_url = "https://nclat.nic.in/about-NCLAT"
    tdsat_url = "https://www.tdsat.gov.in/Delhi/Delhi.php"
    appellate_url = "https://atfp.gov.in/about.html"
    entries = [
        _entry(
            "drt:delhi:drat",
            "DRAT",
            "drt_drat",
            "DRAT / DRT > Delhi > DRAT",
            400,
            now,
            state="Delhi",
            city="New Delhi",
            source_name=drt_source,
            source_url=drt_url,
        ),
    ]
    for index, name in enumerate(("DRT-1", "DRT-2", "DRT-3"), start=401):
        entries.append(
            _entry(
                f"drt:delhi:{name.casefold()}",
                name,
                "drt_drat",
                f"DRAT / DRT > Delhi > {name}",
                index,
                now,
                parent_id="drt:delhi:drat",
                state="Delhi",
                city="New Delhi",
                source_name=drt_source,
                source_url=drt_url,
            )
        )
    for index, (slug, name) in enumerate(
        (
            ("po-court", "PO"),
            ("registrar-court", "Registrar"),
            ("recovery-officer-court", "Recovery Officer"),
        ),
        start=420,
    ):
        entries.append(
            _entry(
                f"recovery:delhi:{slug}",
                name,
                "recovery_forum",
                f"Recovery Forums > Delhi > {name}",
                index,
                now,
                state="Delhi",
                city="New Delhi",
                source_name=drt_source,
                source_url=drt_url,
            )
        )
    entries.extend(
        [
            _entry(
                "company-law:nclat",
                "NCLAT",
                "company_law_tribunal",
                "NCLAT / NCLT > NCLAT",
                440,
                now,
                city="New Delhi",
                source_name="National Company Law Appellate Tribunal",
                source_url=nclat_url,
            ),
            _entry(
                "company-law:nclt",
                "NCLT",
                "company_law_tribunal",
                "NCLAT / NCLT > NCLT",
                441,
                now,
                parent_id="company-law:nclat",
                source_name="National Company Law Tribunal",
                source_url=nclt_url,
            ),
            _entry(
                "tdsat:delhi",
                "TDSAT",
                "tdsat",
                "TDSAT > New Delhi",
                460,
                now,
                state="Delhi",
                city="New Delhi",
                source_name="Telecom Disputes Settlement and Appellate Tribunal",
                source_url=tdsat_url,
            ),
        ]
    )
    for index, (slug, name) in enumerate(
        (("ed", "ED"), ("fema", "FEMA"), ("ndps", "NDPS")),
        start=480,
    ):
        entries.append(
            _entry(
                f"appellate-tribunal:{slug}",
                name,
                "appellate_tribunal",
                f"Appellate Tribunal > {name}",
                index,
                now,
                city="New Delhi",
                source_name="Appellate Tribunal under SAFEMA",
                source_url=appellate_url,
            )
        )
    return entries


def _delhi_consumer_entries(now: datetime) -> list[dict[str, object]]:
    locations = (
        ("dwarka", "Dwarka"),
        ("janakpuri", "Janakpuri"),
        ("qutub", "Qutub"),
        ("ito", "ITO"),
        ("kashmiri-gate", "Kashmiri Gate"),
        ("tis-hazari", "Tis Hazari"),
    )
    return [
        _entry(
            f"consumer:dcdrc:delhi:{slug}",
            name,
            "consumer_forum",
            f"District Commission > Delhi > {name}",
            300 + index,
            now,
            parent_id="consumer:scdrc:11070000",
            state="Delhi",
            district=name,
            city=name,
            consumer_level="district",
        )
        for index, (slug, name) in enumerate(locations)
    ]


def _refresh_consumer_lineages(conn: sa.Connection, table: sa.Table, now: datetime) -> None:
    rows = conn.execute(
        sa.select(
            table.c.id,
            table.c.name,
            table.c.state,
            table.c.district,
            table.c.consumer_level,
        ).where(table.c.forum_type == "consumer_forum")
    ).mappings()
    for row in rows:
        level = row["consumer_level"]
        if level == "national":
            lineage = f"NCDRC > {row['name']}"
        elif level == "state":
            lineage = f"State Commission > {row['state']} > {row['name']}"
        elif level == "district":
            place = row["district"] or row["name"]
            lineage = f"District Commission > {row['state']} > {place}"
        else:
            continue
        conn.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(lineage=lineage, updated_at=now)
        )


def upgrade() -> None:
    conn = op.get_bind()
    table = _catalog_table()
    now = datetime.now(UTC)
    _refresh_consumer_lineages(conn, table, now)
    for entry in [*_delhi_consumer_entries(now), *_specialist_entries(now)]:
        _upsert(conn, table, entry)


def downgrade() -> None:
    conn = op.get_bind()
    table = _catalog_table()
    ids = [
        *(entry["id"] for entry in _delhi_consumer_entries(datetime.now(UTC))),
        *(entry["id"] for entry in _specialist_entries(datetime.now(UTC))),
    ]
    conn.execute(table.delete().where(table.c.id.in_(ids)))
    now = datetime.now(UTC)
    rows = conn.execute(
        sa.select(
            table.c.id,
            table.c.state,
            table.c.district,
            table.c.consumer_level,
        ).where(table.c.forum_type == "consumer_forum")
    ).mappings()
    for row in rows:
        level = row["consumer_level"]
        if level == "national":
            lineage = "Consumer Forum > NCDRC"
        elif level == "state":
            lineage = f"Consumer Forum > SCDRC > {row['state']}"
        elif level == "district":
            lineage = (
                f"Consumer Forum > DCDRC > {row['state']} > {row['district']}"
            )
        else:
            continue
        conn.execute(
            table.update()
            .where(table.c.id == row["id"])
            .values(lineage=lineage, updated_at=now)
        )
