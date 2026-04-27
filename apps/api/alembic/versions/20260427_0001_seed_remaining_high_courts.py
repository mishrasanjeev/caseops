"""Seed the 16 remaining Indian High Courts into the courts master table.

The 2026-04-18 initial migration seeded only 6 HCs (delhi, bombay, madras,
karnataka, telangana, patna). Allahabad + Calcutta were added later. This
migration brings the catalog to 24 distinct HCs — matching HC_COURT_CATALOG
in services/corpus_ingest.py — so backfill_hc_judges_from_corpus can
extend judge coverage to every HC the corpus ingester pulls from.

Idempotent via per-id "if not exists" check (raw DML; some rows may
already be present from manual seeds).
"""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "20260427_0001"
down_revision = "20260426_0003"
branch_labels = None
depends_on = None


_NEW_HCS: list[tuple[str, str, str, str, str, str]] = [
    # (id, name, short_name, jurisdiction, seat_city, hc_catalog_key)
    ("andhra-pradesh-hc", "Andhra Pradesh High Court", "AP HC",
     "Andhra Pradesh", "Amaravati", "andhra-pradesh"),
    ("chhattisgarh-hc", "Chhattisgarh High Court", "Chhattisgarh HC",
     "Chhattisgarh", "Bilaspur", "chhattisgarh"),
    ("gujarat-hc", "Gujarat High Court", "Gujarat HC",
     "Gujarat", "Ahmedabad", "gujarat"),
    ("himachal-hc", "Himachal Pradesh High Court", "HP HC",
     "Himachal Pradesh", "Shimla", "himachal"),
    ("jammu-kashmir-hc", "Jammu & Kashmir and Ladakh High Court", "J&K HC",
     "Jammu & Kashmir", "Srinagar", "jammu-kashmir"),
    ("jharkhand-hc", "Jharkhand High Court", "Jharkhand HC",
     "Jharkhand", "Ranchi", "jharkhand"),
    ("kerala-hc", "Kerala High Court", "Kerala HC",
     "Kerala", "Kochi", "kerala"),
    ("madhya-pradesh-hc", "Madhya Pradesh High Court", "MP HC",
     "Madhya Pradesh", "Jabalpur", "madhya-pradesh"),
    ("manipur-hc", "Manipur High Court", "Manipur HC",
     "Manipur", "Imphal", "manipur"),
    ("meghalaya-hc", "Meghalaya High Court", "Meghalaya HC",
     "Meghalaya", "Shillong", "meghalaya"),
    ("orissa-hc", "Orissa High Court", "Orissa HC",
     "Odisha", "Cuttack", "orissa"),
    ("punjab-hc", "Punjab and Haryana High Court", "P&H HC",
     "Punjab and Haryana", "Chandigarh", "punjab"),
    ("rajasthan-hc", "Rajasthan High Court", "Rajasthan HC",
     "Rajasthan", "Jodhpur", "rajasthan"),
    ("sikkim-hc", "Sikkim High Court", "Sikkim HC",
     "Sikkim", "Gangtok", "sikkim"),
    ("tripura-hc", "Tripura High Court", "Tripura HC",
     "Tripura", "Agartala", "tripura"),
    ("uttarakhand-hc", "Uttarakhand High Court", "Uttarakhand HC",
     "Uttarakhand", "Nainital", "uttarakhand"),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(UTC)
    for cid, name, short, jurisdiction, seat, key in _NEW_HCS:
        # Idempotent insert — courts.id is the unique key.
        existing = bind.execute(
            sa.text("SELECT 1 FROM courts WHERE id = :id"),
            {"id": cid},
        ).first()
        if existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO courts "
                "(id, name, short_name, forum_level, jurisdiction, "
                " seat_city, hc_catalog_key, is_active, created_at, updated_at) "
                "VALUES (:id, :name, :short, 'high_court', :jur, :seat, "
                "  :key, TRUE, :now, :now)"
            ),
            {
                "id": cid, "name": name, "short": short, "jur": jurisdiction,
                "seat": seat, "key": key, "now": now,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for cid, *_ in _NEW_HCS:
        bind.execute(sa.text("DELETE FROM courts WHERE id = :id"), {"id": cid})
