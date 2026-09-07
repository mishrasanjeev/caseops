"""Add source-backed qualified court labels from the September 05 import.

Revision ID: 20260905_0003
Revises: 20260905_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: three indexed parent/alias lookups and inserts;
no matter rewrite, catalog-wide scan, or schema lock.
MIGRATION-ROLLBACK: restore-forward: retain reviewed aliases and resolved lineage;
correct catalog data forward rather than removing identities used by imports.
"""

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision = "20260905_0003"
down_revision = "20260905_0002"
branch_labels = None
depends_on = None

ALIASES = (
    (
        "district:india-gov:delhi:westdelhi",
        "Tis Hazari (West)",
        "tishazariwest",
        "https://delhidistrictcourts.nic.in/circulars",
    ),
    (
        "consumer:dcdrc:delhi:dwarka",
        "Dwarka-Consumer Forum",
        "dwarkaconsumerforum",
        "https://fsd.delhi.gov.in/fs/consumer-courts-delhi",
    ),
    (
        "tdsat:delhi",
        "TDSAT- New Delhi",
        "tdsatnewdelhi",
        "https://tdsat.gov.in/writereaddata/Delhi/docs/contact_detail.php",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    metadata = sa.MetaData()
    entries = sa.Table("forum_catalog_entries", metadata, autoload_with=bind)
    aliases = sa.Table("forum_catalog_aliases", metadata, autoload_with=bind)
    now = datetime.now(UTC)
    for entry_id, label, normalized, source_url in ALIASES:
        active = bind.execute(
            sa.select(entries.c.is_active).where(entries.c.id == entry_id)
        ).scalar_one_or_none()
        if active is None:
            raise RuntimeError(f"Missing reviewed forum catalog parent: {entry_id}")
        # An administrator's deactivation or previous alias decision is retained.
        if not active:
            continue
        existing = bind.execute(
            sa.select(aliases.c.id).where(
                aliases.c.forum_catalog_entry_id == entry_id,
                aliases.c.normalized_alias == normalized,
            )
        ).scalar_one_or_none()
        if existing:
            continue
        bind.execute(
            aliases.insert().values(
                id=str(uuid5(NAMESPACE_URL, f"caseops:ram05sep:{entry_id}:{normalized}")),
                forum_catalog_entry_id=entry_id,
                alias=label,
                normalized_alias=normalized,
                alias_type="local_name",
                source_name="Official court directory identity checked 2026-09-05",
                source_url=source_url,
                verification_status="verified",
                is_active=True,
                reviewed_at=now,
                record_version=1,
                created_at=now,
                updated_at=now,
            )
        )


def downgrade() -> None:
    # Data-only rollback retains the aliases; the owning schema's downgrade
    # separately enforces its evidence-removal guard.
    pass
