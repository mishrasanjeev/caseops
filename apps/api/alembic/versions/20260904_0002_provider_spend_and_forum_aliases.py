"""Add tenant provider budgets and reviewed forum aliases.

Revision ID: 20260904_0002
Revises: 20260904_0001

DATA-GOVERNANCE-MAP: updated

MIGRATION-LOCK-RISK: acknowledged: PostgreSQL builds every index on the two
existing billing tables concurrently after the bounded provider-key backfill.
The remaining indexes are created on new empty tables. The only existing-table
constraint scan is the server-owned forum catalog, which is bounded below
1,000 rows by its seed contract.

MIGRATION-ROLLBACK: restore-forward: once provider policies, spend evidence, or
reviewed aliases exist, rollback must restore or roll forward rather than drop
those records. The destructive downgrade is for pre-release schema validation
only and must not be used after this revision serves traffic.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "20260904_0002"
down_revision = "20260904_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROVIDERS = ("indian-kanoon", "ecourtsindia")
_UNLIMITED_COMPANY_NAMES = ("gba law office", "pinelabs pvt. ltd.")
_ALIAS_SOURCE_NAME = "Reviewed CaseOps court-complex mapping, 2026-09-04"
_ALIAS_SOURCE_URL = "https://delhidistrictcourts.nic.in/aboutus"
_CONSUMER_SOURCE_URL = (
    "https://e-jagriti.gov.in/services/master/master/v2/getCommissionDetailsByStateId?stateId=7"
)
_CONSUMER_LABELS = {
    "consumer:dcdrc:delhi:dwarka": "District Consumer Commission, Dwarka",
    "consumer:dcdrc:delhi:janakpuri": "District Consumer Commission, Janakpuri",
    "consumer:dcdrc:delhi:qutub": "District Consumer Commission, Qutub",
    "consumer:dcdrc:delhi:ito": "District Consumer Commission, ITO",
    "consumer:dcdrc:delhi:kashmiri-gate": "District Consumer Commission, Kashmiri Gate",
    "consumer:dcdrc:delhi:tis-hazari": "District Consumer Commission, Tis Hazari",
}
_ALIASES = (
    (
        "district:india-gov:delhi:centraldelhi",
        "Tis Hazari",
        "tishazari",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:westdelhi",
        "Tis Hazari",
        "tishazari",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:eastdelhi",
        "Karkardooma",
        "karkardooma",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:northeast",
        "Karkardooma",
        "karkardooma",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:shahdara",
        "Karkardooma",
        "karkardooma",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:southwestdelhi",
        "Dwarka",
        "dwarka",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:southdelhi",
        "Saket",
        "saket",
        _ALIAS_SOURCE_URL,
    ),
    (
        "district:india-gov:delhi:southeastdelhi",
        "Saket",
        "saket",
        _ALIAS_SOURCE_URL,
    ),
    (
        "consumer:dcdrc:delhi:dwarka",
        "Dwarka_SWCF",
        "dwarkaswcf",
        _CONSUMER_SOURCE_URL,
    ),
    (
        "consumer:dcdrc:delhi:dwarka",
        "Dwarka DCDRC",
        "dwarkadcdrc",
        _CONSUMER_SOURCE_URL,
    ),
    (
        "consumer:dcdrc:delhi:janakpuri",
        "Janakpuri DCDRC",
        "janakpuridcdrc",
        _CONSUMER_SOURCE_URL,
    ),
    (
        "consumer:dcdrc:delhi:qutub",
        "Qutub DCDRC",
        "qutubdcdrc",
        _CONSUMER_SOURCE_URL,
    ),
    ("consumer:dcdrc:delhi:ito", "ITO", "ito", _CONSUMER_SOURCE_URL),
    (
        "consumer:dcdrc:delhi:kashmiri-gate",
        "Kashmiri Gate DCDRC",
        "kashmirigatedcdrc",
        _CONSUMER_SOURCE_URL,
    ),
    (
        "consumer:dcdrc:delhi:tis-hazari",
        "Tis Hazari DCDRC",
        "tishazaridcdrc",
        _CONSUMER_SOURCE_URL,
    ),
)


def _normalize_forum_value(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", value.strip().casefold())
    for suffix in ("courtscomplex", "courtcomplex", "courts", "court"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix):
            return normalized[: -len(suffix)]
    return normalized


def upgrade() -> None:
    now = datetime.now(UTC)
    bind = op.get_bind()
    with op.batch_alter_table("billing_usage_events") as batch:
        batch.add_column(sa.Column("provider_key", sa.String(length=80), nullable=True))
    with op.batch_alter_table("billing_usage_attribution") as batch:
        batch.add_column(sa.Column("provider_key", sa.String(length=80), nullable=True))

    op.execute(
        "UPDATE billing_usage_events SET provider_key = 'indian-kanoon' "
        "WHERE usage_type LIKE 'indian_kanoon_%'"
    )
    op.execute(
        "UPDATE billing_usage_events SET provider_key = 'ecourtsindia' "
        "WHERE usage_type = 'case_refresh'"
    )
    op.execute(
        "UPDATE billing_usage_attribution SET provider_key = ("
        "SELECT billing_usage_events.provider_key FROM billing_usage_events "
        "WHERE billing_usage_events.id = billing_usage_attribution.billing_usage_event_id"
        ") WHERE billing_usage_event_id IS NOT NULL"
    )

    existing_table_indexes = (
        (
            "ix_billing_usage_events_provider_key",
            "billing_usage_events",
            ["provider_key"],
        ),
        (
            "ix_billing_usage_events_company_provider_created",
            "billing_usage_events",
            ["company_id", "provider_key", "created_at"],
        ),
        (
            "ix_billing_usage_attribution_provider_key",
            "billing_usage_attribution",
            ["provider_key"],
        ),
    )
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for index_name, table_name, columns in existing_table_indexes:
                op.create_index(
                    index_name,
                    table_name,
                    columns,
                    postgresql_concurrently=True,
                )
    else:
        for index_name, table_name, columns in existing_table_indexes:
            op.create_index(index_name, table_name, columns)

    op.create_table(
        "company_provider_spend_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("monthly_limit_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("policy_source", sa.String(length=160), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "monthly_limit_minor IS NULL OR monthly_limit_minor >= 0",
            name="ck_company_provider_spend_policy_limit",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "provider_key",
            name="uq_company_provider_spend_policy",
        ),
    )
    op.create_index(
        "ix_company_provider_spend_policies_company_id",
        "company_provider_spend_policies",
        ["company_id"],
    )
    op.create_index(
        "ix_company_provider_spend_policies_provider_key",
        "company_provider_spend_policies",
        ["provider_key"],
    )

    op.create_table(
        "provider_spend_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("provider_key", sa.String(length=80), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("operation_key", sa.String(length=120), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount_minor >= 0", name="ck_provider_spend_reservation_amount"),
        sa.CheckConstraint(
            "status IN ('reserved', 'settled', 'released')",
            name="ck_provider_spend_reservation_status",
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_provider_spend_reservations_company_id",
        "provider_spend_reservations",
        ["company_id"],
    )
    op.create_index(
        "ix_provider_spend_reservations_provider_key",
        "provider_spend_reservations",
        ["provider_key"],
    )
    op.create_index(
        "ix_provider_spend_reservations_actor_membership_id",
        "provider_spend_reservations",
        ["actor_membership_id"],
    )
    op.create_index(
        "ix_provider_spend_reservations_status",
        "provider_spend_reservations",
        ["status"],
    )
    op.create_index(
        "ix_provider_spend_reservations_expires_at",
        "provider_spend_reservations",
        ["expires_at"],
    )
    op.create_index(
        "ix_provider_spend_reservations_company_provider_status_expiry",
        "provider_spend_reservations",
        ["company_id", "provider_key", "status", "expires_at"],
    )

    companies = sa.table(
        "companies",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
    )
    policies = sa.table(
        "company_provider_spend_policies",
        sa.column("id", sa.String()),
        sa.column("company_id", sa.String()),
        sa.column("provider_key", sa.String()),
        sa.column("monthly_limit_minor", sa.Integer()),
        sa.column("currency", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("policy_source", sa.String()),
        sa.column("reason", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    company_ids = list(
        op.get_bind().scalars(
            sa.select(companies.c.id).where(
                sa.func.lower(sa.func.trim(companies.c.name)).in_(_UNLIMITED_COMPANY_NAMES)
            )
        )
    )
    if company_ids:
        op.bulk_insert(
            policies,
            [
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "provider_key": provider,
                    "monthly_limit_minor": None,
                    "currency": "INR",
                    "is_active": True,
                    "policy_source": "user_authorized_named_exception_2026_09_04",
                    "reason": "Unlimited monthly provider access authorized by the founder.",
                    "created_at": now,
                    "updated_at": now,
                }
                for company_id in company_ids
                for provider in _PROVIDERS
            ],
        )

    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.add_column(sa.Column("normalized_name", sa.String(length=255), nullable=True))
        batch.create_index("ix_forum_catalog_entries_normalized_name", ["normalized_name"])
    for entry_id, entry_name in op.get_bind().execute(
        sa.text("SELECT id, name FROM forum_catalog_entries")
    ):
        op.get_bind().execute(
            sa.text(
                "UPDATE forum_catalog_entries SET normalized_name = :normalized "
                "WHERE id = :entry_id"
            ),
            {
                "entry_id": entry_id,
                "normalized": _normalize_forum_value(str(entry_name)),
            },
        )
    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.alter_column(
            "normalized_name",
            existing_type=sa.String(length=255),
            nullable=False,
        )

    op.create_table(
        "forum_catalog_aliases",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("forum_catalog_entry_id", sa.String(length=120), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("alias_type", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=160), nullable=False),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("record_version", sa.Integer(), nullable=False),
        sa.Column("created_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "alias_type IN ('court_complex', 'abbreviation', 'legacy_name', "
            "'local_name', 'spelling_variant', 'provider_label', 'other')",
            name="ck_forum_catalog_alias_type",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected')",
            name="ck_forum_catalog_alias_verification_status",
        ),
        sa.CheckConstraint(
            "record_version >= 0",
            name="ck_forum_catalog_alias_record_version",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_platform_admin_id"],
            ["platform_admin_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["forum_catalog_entry_id"],
            ["forum_catalog_entries.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_platform_admin_id"],
            ["platform_admin_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_platform_admin_id"],
            ["platform_admin_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "forum_catalog_entry_id",
            "normalized_alias",
            name="uq_forum_catalog_alias_entry_normalized",
        ),
    )
    op.create_index(
        "ix_forum_catalog_aliases_forum_catalog_entry_id",
        "forum_catalog_aliases",
        ["forum_catalog_entry_id"],
    )
    op.create_index(
        "ix_forum_catalog_aliases_normalized_alias",
        "forum_catalog_aliases",
        ["normalized_alias"],
    )
    op.create_index(
        "ix_forum_catalog_aliases_is_active",
        "forum_catalog_aliases",
        ["is_active"],
    )
    op.create_index(
        "ix_forum_catalog_aliases_normalized_active_verified",
        "forum_catalog_aliases",
        ["normalized_alias", "is_active", "verification_status"],
    )
    for actor_column in (
        "created_by_platform_admin_id",
        "reviewed_by_platform_admin_id",
        "updated_by_platform_admin_id",
    ):
        op.create_index(
            f"ix_forum_catalog_aliases_{actor_column}",
            "forum_catalog_aliases",
            [actor_column],
        )

    forum_entries = sa.table(
        "forum_catalog_entries",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("normalized_name", sa.String()),
        sa.column("lineage", sa.String()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    for entry_id, name in _CONSUMER_LABELS.items():
        location = name.rsplit(", ", 1)[-1]
        op.get_bind().execute(
            forum_entries.update()
            .where(forum_entries.c.id == entry_id)
            .values(
                name=name,
                normalized_name=_normalize_forum_value(name),
                lineage=f"District Commission > Delhi > {location}",
                updated_at=now,
            )
        )

    aliases = sa.table(
        "forum_catalog_aliases",
        sa.column("id", sa.String()),
        sa.column("forum_catalog_entry_id", sa.String()),
        sa.column("alias", sa.String()),
        sa.column("normalized_alias", sa.String()),
        sa.column("alias_type", sa.String()),
        sa.column("source_name", sa.String()),
        sa.column("source_url", sa.String()),
        sa.column("verification_status", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("reviewed_at", sa.DateTime(timezone=True)),
        sa.column("record_version", sa.Integer()),
        sa.column("created_by_platform_admin_id", sa.String()),
        sa.column("reviewed_by_platform_admin_id", sa.String()),
        sa.column("updated_by_platform_admin_id", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        aliases,
        [
            {
                "id": str(uuid4()),
                "forum_catalog_entry_id": entry_id,
                "alias": alias,
                "normalized_alias": normalized,
                "alias_type": "court_complex",
                "source_name": _ALIAS_SOURCE_NAME,
                "source_url": source_url,
                "verification_status": "verified",
                "is_active": True,
                "reviewed_at": now,
                "record_version": 0,
                "created_by_platform_admin_id": None,
                "reviewed_by_platform_admin_id": None,
                "updated_by_platform_admin_id": None,
                "created_at": now,
                "updated_at": now,
            }
            for entry_id, alias, normalized, source_url in _ALIASES
        ],
    )


def downgrade() -> None:
    forum_entries = sa.table(
        "forum_catalog_entries",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("lineage", sa.String()),
    )
    for entry_id, name in _CONSUMER_LABELS.items():
        location = name.rsplit(", ", 1)[-1]
        op.get_bind().execute(
            forum_entries.update()
            .where(forum_entries.c.id == entry_id)
            .values(name=location, lineage=f"District Commission > Delhi > {location}")
        )
    for actor_column in (
        "updated_by_platform_admin_id",
        "reviewed_by_platform_admin_id",
        "created_by_platform_admin_id",
    ):
        op.drop_index(
            f"ix_forum_catalog_aliases_{actor_column}",
            table_name="forum_catalog_aliases",
        )
    op.drop_index(
        "ix_forum_catalog_aliases_normalized_active_verified",
        table_name="forum_catalog_aliases",
    )
    op.drop_index("ix_forum_catalog_aliases_is_active", table_name="forum_catalog_aliases")
    op.drop_index("ix_forum_catalog_aliases_normalized_alias", table_name="forum_catalog_aliases")
    op.drop_index(
        "ix_forum_catalog_aliases_forum_catalog_entry_id",
        table_name="forum_catalog_aliases",
    )
    op.drop_table("forum_catalog_aliases")
    with op.batch_alter_table("forum_catalog_entries") as batch:
        batch.drop_index("ix_forum_catalog_entries_normalized_name")
        batch.drop_column("normalized_name")
    op.drop_index(
        "ix_provider_spend_reservations_company_provider_status_expiry",
        table_name="provider_spend_reservations",
    )
    op.drop_index(
        "ix_provider_spend_reservations_expires_at",
        table_name="provider_spend_reservations",
    )
    op.drop_index(
        "ix_provider_spend_reservations_status",
        table_name="provider_spend_reservations",
    )
    op.drop_index(
        "ix_provider_spend_reservations_actor_membership_id",
        table_name="provider_spend_reservations",
    )
    op.drop_index(
        "ix_provider_spend_reservations_provider_key",
        table_name="provider_spend_reservations",
    )
    op.drop_index(
        "ix_provider_spend_reservations_company_id",
        table_name="provider_spend_reservations",
    )
    op.drop_table("provider_spend_reservations")
    op.drop_index(
        "ix_company_provider_spend_policies_provider_key",
        table_name="company_provider_spend_policies",
    )
    op.drop_index(
        "ix_company_provider_spend_policies_company_id",
        table_name="company_provider_spend_policies",
    )
    op.drop_table("company_provider_spend_policies")
    with op.batch_alter_table("billing_usage_attribution") as batch:
        batch.drop_index("ix_billing_usage_attribution_provider_key")
        batch.drop_column("provider_key")
    with op.batch_alter_table("billing_usage_events") as batch:
        batch.drop_index("ix_billing_usage_events_company_provider_created")
        batch.drop_index("ix_billing_usage_events_provider_key")
        batch.drop_column("provider_key")
