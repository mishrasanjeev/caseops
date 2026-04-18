"""courts, benches, judges master tables (§7.1)

Revision ID: 20260418_0003
Revises: 20260418_0002
Create Date: 2026-04-18 10:00:00

Turns `Matter.court_name` (a free string) into an FK reference to a
`courts` master table. The string column stays — it's the freeform
fallback for courts we haven't catalogued yet. The FK is nullable so
existing matters don't need a data backfill to keep working.

Seeded with 7 courts that cover most of our current corpus:
Supreme Court, and the five target High Courts + Patna HC (a leftover
from the early ingestion labelled `High Court of India`). Seeding is
done in code via a data migration so we don't ship a CSV fixture.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0003"
down_revision = "20260418_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "courts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("short_name", sa.String(length=80), nullable=False),
        sa.Column("forum_level", sa.String(length=40), nullable=False),
        sa.Column("jurisdiction", sa.String(length=120), nullable=True),
        sa.Column("seat_city", sa.String(length=120), nullable=True),
        sa.Column("hc_catalog_key", sa.String(length=40), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_courts_name"),
    )
    op.create_index("ix_courts_forum_level", "courts", ["forum_level"])

    op.create_table(
        "benches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "court_id",
            sa.String(length=36),
            sa.ForeignKey("courts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("seat_city", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("court_id", "name", name="uq_benches_court_name"),
    )

    op.create_table(
        "judges",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "court_id",
            sa.String(length=36),
            sa.ForeignKey("courts.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("honorific", sa.String(length=80), nullable=True),
        sa.Column("current_position", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("court_id", "full_name", name="uq_judges_court_name"),
    )
    op.create_index("ix_judges_full_name", "judges", ["full_name"])

    op.add_column(
        "matters",
        sa.Column("court_id", sa.String(length=36), nullable=True),
    )
    # SQLite can't ALTER TABLE to add a foreign key after the fact
    # (alembic batch mode would rewrite the table, which is heavier
    # than we need for a nullable reference column). Skip the FK on
    # SQLite — the tests don't exercise it, and Postgres gets the
    # real constraint.
    if op.get_bind().dialect.name != "sqlite":
        op.create_foreign_key(
            "fk_matters_court_id",
            "matters",
            "courts",
            ["court_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Seed the courts master table. Done via raw DML so it survives
    # downgrades cleanly.
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    seeds = [
        ("supreme-court-india", "Supreme Court of India", "SC", "supreme_court", "India", "New Delhi", "sc"),
        ("delhi-hc", "Delhi High Court", "Delhi HC", "high_court", "Delhi", "New Delhi", "delhi"),
        ("bombay-hc", "Bombay High Court", "Bombay HC", "high_court", "Maharashtra", "Mumbai", "bombay"),
        ("madras-hc", "Madras High Court", "Madras HC", "high_court", "Tamil Nadu", "Chennai", "madras"),
        ("karnataka-hc", "Karnataka High Court", "Karnataka HC", "high_court", "Karnataka", "Bengaluru", "karnataka"),
        ("telangana-hc", "Telangana High Court", "Telangana HC", "high_court", "Telangana", "Hyderabad", "telangana"),
        ("patna-hc", "Patna High Court", "Patna HC", "high_court", "Bihar", "Patna", "patna"),
    ]
    op.bulk_insert(
        sa.table(
            "courts",
            sa.column("id", sa.String),
            sa.column("name", sa.String),
            sa.column("short_name", sa.String),
            sa.column("forum_level", sa.String),
            sa.column("jurisdiction", sa.String),
            sa.column("seat_city", sa.String),
            sa.column("hc_catalog_key", sa.String),
            sa.column("is_active", sa.Boolean),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {
                "id": seed_id,
                "name": name,
                "short_name": short,
                "forum_level": forum,
                "jurisdiction": jur,
                "seat_city": city,
                "hc_catalog_key": catalog_key,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for (seed_id, name, short, forum, jur, city, catalog_key) in seeds
        ],
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        op.drop_constraint("fk_matters_court_id", "matters", type_="foreignkey")
    op.drop_column("matters", "court_id")
    op.drop_index("ix_judges_full_name", table_name="judges")
    op.drop_table("judges")
    op.drop_table("benches")
    op.drop_index("ix_courts_forum_level", table_name="courts")
    op.drop_table("courts")
