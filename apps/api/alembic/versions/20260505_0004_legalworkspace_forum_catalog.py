"""LegalWorkspace LW-S4 forum hierarchy catalog.

Revision ID: 20260505_0004
Revises: 20260505_0003
Create Date: 2026-05-05
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "20260505_0004"
down_revision = "20260505_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SOURCE_NAME = "CaseOps LW-S4 baseline forum catalog"
_SOURCE_URL = "docs/PRD_LEGALWORKSPACE_ENHANCEMENTS_2026-05-05.md#slice-lw-s4-forum-hierarchy"


def _entry(
    entry_id: str,
    name: str,
    forum_type: str,
    forum_level: str,
    *,
    parent_id: str | None = None,
    court_id: str | None = None,
    state: str | None = None,
    district: str | None = None,
    city: str | None = None,
    consumer_level: str | None = None,
    lineage: str,
    display_order: int,
) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "id": entry_id,
        "parent_id": parent_id,
        "court_id": court_id,
        "name": name,
        "forum_type": forum_type,
        "forum_level": forum_level,
        "state": state,
        "district": district,
        "city": city,
        "consumer_level": consumer_level,
        "source_name": _SOURCE_NAME,
        "source_url": _SOURCE_URL,
        "lineage": lineage,
        "display_order": display_order,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }


def upgrade() -> None:
    op.create_table(
        "forum_catalog_entries",
        sa.Column("id", sa.String(length=120), primary_key=True),
        sa.Column(
            "parent_id",
            sa.String(length=120),
            sa.ForeignKey("forum_catalog_entries.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "court_id",
            sa.String(length=36),
            sa.ForeignKey("courts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("forum_type", sa.String(length=40), nullable=False),
        sa.Column("forum_level", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column("district", sa.String(length=120), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("consumer_level", sa.String(length=24), nullable=True),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("lineage", sa.String(length=500), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_forum_catalog_entries_parent_id", "forum_catalog_entries", ["parent_id"])
    op.create_index("ix_forum_catalog_entries_court_id", "forum_catalog_entries", ["court_id"])
    op.create_index("ix_forum_catalog_entries_forum_type", "forum_catalog_entries", ["forum_type"])
    op.create_index("ix_forum_catalog_entries_forum_level", "forum_catalog_entries", ["forum_level"])
    op.create_index("ix_forum_catalog_entries_state", "forum_catalog_entries", ["state"])
    op.create_index("ix_forum_catalog_entries_district", "forum_catalog_entries", ["district"])

    with op.batch_alter_table("matters") as batch:
        batch.add_column(sa.Column("forum_catalog_entry_id", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("forum_state", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("forum_district", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("forum_city", sa.String(length=120), nullable=True))
        batch.add_column(sa.Column("forum_consumer_level", sa.String(length=24), nullable=True))
        batch.create_index("ix_matters_forum_catalog_entry_id", ["forum_catalog_entry_id"])
        if op.get_bind().dialect.name != "sqlite":
            batch.create_foreign_key(
                "fk_matters_forum_catalog_entry_id",
                "forum_catalog_entries",
                ["forum_catalog_entry_id"],
                ["id"],
                ondelete="SET NULL",
            )

    entries = [
        _entry(
            "sc:india",
            "Supreme Court of India",
            "supreme_court",
            "supreme_court",
            court_id="supreme-court-india",
            city="New Delhi",
            lineage="Supreme Court > India",
            display_order=10,
        ),
    ]

    high_courts = [
        ("hc:andhra-pradesh", "Andhra Pradesh High Court", "andhra-pradesh-hc", "Andhra Pradesh", "Amaravati"),
        ("hc:bihar", "Patna High Court", "patna-hc", "Bihar", "Patna"),
        ("hc:bombay", "Bombay High Court", "bombay-hc", "Maharashtra", "Mumbai"),
        ("hc:chhattisgarh", "Chhattisgarh High Court", "chhattisgarh-hc", "Chhattisgarh", "Bilaspur"),
        ("hc:delhi", "Delhi High Court", "delhi-hc", "Delhi", "New Delhi"),
        ("hc:gujarat", "Gujarat High Court", "gujarat-hc", "Gujarat", "Ahmedabad"),
        ("hc:himachal-pradesh", "Himachal Pradesh High Court", "himachal-hc", "Himachal Pradesh", "Shimla"),
        ("hc:jammu-kashmir-ladakh", "Jammu & Kashmir and Ladakh High Court", "jammu-kashmir-hc", "Jammu & Kashmir", "Srinagar"),
        ("hc:jharkhand", "Jharkhand High Court", "jharkhand-hc", "Jharkhand", "Ranchi"),
        ("hc:karnataka", "Karnataka High Court", "karnataka-hc", "Karnataka", "Bengaluru"),
        ("hc:kerala", "Kerala High Court", "kerala-hc", "Kerala", "Kochi"),
        ("hc:madhya-pradesh", "Madhya Pradesh High Court", "madhya-pradesh-hc", "Madhya Pradesh", "Jabalpur"),
        ("hc:madras", "Madras High Court", "madras-hc", "Tamil Nadu", "Chennai"),
        ("hc:manipur", "Manipur High Court", "manipur-hc", "Manipur", "Imphal"),
        ("hc:meghalaya", "Meghalaya High Court", "meghalaya-hc", "Meghalaya", "Shillong"),
        ("hc:orissa", "Orissa High Court", "orissa-hc", "Odisha", "Cuttack"),
        ("hc:punjab-haryana", "Punjab and Haryana High Court", "punjab-hc", "Punjab and Haryana", "Chandigarh"),
        ("hc:rajasthan", "Rajasthan High Court", "rajasthan-hc", "Rajasthan", "Jodhpur"),
        ("hc:sikkim", "Sikkim High Court", "sikkim-hc", "Sikkim", "Gangtok"),
        ("hc:telangana", "Telangana High Court", "telangana-hc", "Telangana", "Hyderabad"),
        ("hc:tripura", "Tripura High Court", "tripura-hc", "Tripura", "Agartala"),
        ("hc:uttarakhand", "Uttarakhand High Court", "uttarakhand-hc", "Uttarakhand", "Nainital"),
        # Present in the public HC corpus catalog but not yet present as Court
        # rows in every environment; map when the Court seed exists later.
        ("hc:allahabad", "Allahabad High Court", None, "Uttar Pradesh", "Prayagraj"),
        ("hc:calcutta", "Calcutta High Court", None, "West Bengal", "Kolkata"),
    ]
    for index, (entry_id, name, court_id, state, city) in enumerate(high_courts, start=20):
        entries.append(
            _entry(
                entry_id,
                name,
                "high_court",
                "high_court",
                court_id=court_id,
                state=state,
                city=city,
                lineage=f"High Court > {state} > {name}",
                display_order=index,
            )
        )

    district_courts = [
        ("district:delhi:central", "Central District Court, Delhi", "Delhi", "Central", "New Delhi"),
        ("district:delhi:new-delhi", "New Delhi District Court", "Delhi", "New Delhi", "New Delhi"),
        ("district:delhi:south", "South District Court, Delhi", "Delhi", "South", "Saket"),
        ("district:maharashtra:mumbai-city", "Mumbai City Civil and Sessions Court", "Maharashtra", "Mumbai City", "Mumbai"),
        ("district:karnataka:bengaluru-urban", "Bengaluru Urban District Court", "Karnataka", "Bengaluru Urban", "Bengaluru"),
        ("district:tamil-nadu:chennai", "Chennai District Court", "Tamil Nadu", "Chennai", "Chennai"),
    ]
    for index, (entry_id, name, state, district, city) in enumerate(district_courts, start=100):
        entries.append(
            _entry(
                entry_id,
                name,
                "district_court",
                "lower_court",
                state=state,
                district=district,
                city=city,
                lineage=f"District Court > {state} > {district} > {city}",
                display_order=index,
            )
        )

    consumer_forums = [
        ("consumer:ncdrc", None, "National Consumer Disputes Redressal Commission", None, None, "New Delhi", "national", 200),
        ("consumer:scdrc:delhi", "consumer:ncdrc", "Delhi State Consumer Disputes Redressal Commission", "Delhi", None, "New Delhi", "state", 210),
        ("consumer:scdrc:maharashtra", "consumer:ncdrc", "Maharashtra State Consumer Disputes Redressal Commission", "Maharashtra", None, "Mumbai", "state", 211),
        ("consumer:scdrc:karnataka", "consumer:ncdrc", "Karnataka State Consumer Disputes Redressal Commission", "Karnataka", None, "Bengaluru", "state", 212),
        ("consumer:dcdrc:central-delhi", "consumer:scdrc:delhi", "Central Delhi District Consumer Disputes Redressal Commission", "Delhi", "Central", "New Delhi", "district", 230),
        ("consumer:dcdrc:mumbai", "consumer:scdrc:maharashtra", "Mumbai District Consumer Disputes Redressal Commission", "Maharashtra", "Mumbai City", "Mumbai", "district", 231),
        ("consumer:dcdrc:bengaluru-urban", "consumer:scdrc:karnataka", "Bengaluru Urban District Consumer Disputes Redressal Commission", "Karnataka", "Bengaluru Urban", "Bengaluru", "district", 232),
    ]
    for entry_id, parent_id, name, state, district, city, level, order in consumer_forums:
        label = "NCDRC" if level == "national" else ("SCDRC" if level == "state" else "DCDRC")
        lineage_bits = ["Consumer Forum", label]
        if state:
            lineage_bits.append(state)
        if district:
            lineage_bits.append(district)
        entries.append(
            _entry(
                entry_id,
                name,
                "consumer_forum",
                "tribunal",
                parent_id=parent_id,
                state=state,
                district=district,
                city=city,
                consumer_level=level,
                lineage=" > ".join(lineage_bits),
                display_order=order,
            )
        )

    op.bulk_insert(
        sa.table(
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
        ),
        entries,
    )


def downgrade() -> None:
    with op.batch_alter_table("matters") as batch:
        if op.get_bind().dialect.name != "sqlite":
            batch.drop_constraint("fk_matters_forum_catalog_entry_id", type_="foreignkey")
        batch.drop_index("ix_matters_forum_catalog_entry_id")
        batch.drop_column("forum_consumer_level")
        batch.drop_column("forum_city")
        batch.drop_column("forum_district")
        batch.drop_column("forum_state")
        batch.drop_column("forum_catalog_entry_id")

    op.drop_index("ix_forum_catalog_entries_district", table_name="forum_catalog_entries")
    op.drop_index("ix_forum_catalog_entries_state", table_name="forum_catalog_entries")
    op.drop_index("ix_forum_catalog_entries_forum_level", table_name="forum_catalog_entries")
    op.drop_index("ix_forum_catalog_entries_forum_type", table_name="forum_catalog_entries")
    op.drop_index("ix_forum_catalog_entries_court_id", table_name="forum_catalog_entries")
    op.drop_index("ix_forum_catalog_entries_parent_id", table_name="forum_catalog_entries")
    op.drop_table("forum_catalog_entries")
