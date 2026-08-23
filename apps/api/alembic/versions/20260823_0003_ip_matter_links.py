"""Add governed many-to-many IP and Matter links.

Revision ID: 20260823_0003
Revises: 20260823_0002
Create Date: 2026-08-23

IPLF-044 preserves ``ip_docket_records`` and ``matters`` as independent
lifecycle owners. This additive link history backfills the existing operational
Matter pointer and permits additional litigation, advisory, appeal, enforcement,
billing, and other references without copying either parent's state.

MIGRATION-LOCK-RISK: acknowledged: one new table is created and existing docket
rows with a Matter pointer are read in deterministic primary-key order for link
backfill; no existing row is updated.
MIGRATION-ROLLBACK: restore-forward: downgrade refuses after any user-created or
retired link exists. Pure deterministic migration links may be removed safely.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa

from alembic import op

revision = "20260823_0003"
down_revision = "20260823_0002"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    op.create_table(
        "ip_matter_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("matter_id", sa.String(36), nullable=False),
        sa.Column("relation_role", sa.String(32), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("source_reference", sa.String(512), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retirement_reason", sa.Text(), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column("retired_by_membership_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_matter_link_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_ip_matter_link_matter_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_matter_link_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retired_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_matter_link_retirer_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_matter_link_id_company"),
        sa.CheckConstraint(
            "relation_role IN ('operational', 'litigation', 'advisory', 'appeal', "
            "'enforcement', 'billing', 'other')",
            name="ck_ip_matter_link_relation_role",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'system', 'migration')",
            name="ck_ip_matter_link_source",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR retired_at >= effective_from",
            name="ck_ip_matter_link_effective_range",
        ),
        sa.CheckConstraint(
            "(retired_at IS NULL AND retired_by_membership_id IS NULL AND "
            "retirement_reason IS NULL) OR "
            "(retired_at IS NOT NULL AND retired_by_membership_id IS NOT NULL AND "
            "retirement_reason IS NOT NULL)",
            name="ck_ip_matter_link_retirement_contract",
        ),
    )
    op.create_index(
        "uq_ip_matter_links_active_role",
        "ip_matter_links",
        ["company_id", "docket_id", "matter_id", "relation_role"],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
        sqlite_where=sa.text("retired_at IS NULL"),
    )
    op.create_index(
        "uq_ip_matter_links_active_operational",
        "ip_matter_links",
        ["company_id", "docket_id"],
        unique=True,
        postgresql_where=sa.text(
            "retired_at IS NULL AND relation_role = 'operational'"
        ),
        sqlite_where=sa.text("retired_at IS NULL AND relation_role = 'operational'"),
    )
    op.create_index(
        "ix_ip_matter_links_company_docket_effective",
        "ip_matter_links",
        ["company_id", "docket_id", "effective_from"],
    )
    op.create_index(
        "ix_ip_matter_links_company_matter_effective",
        "ip_matter_links",
        ["company_id", "matter_id", "effective_from"],
    )
    rows = bind.execute(
        sa.text(
            "SELECT id, company_id, matter_id, created_at "
            "FROM ip_docket_records WHERE matter_id IS NOT NULL ORDER BY id"
        )
    ).mappings()
    for row in rows:
        link_id = str(
            uuid5(
                NAMESPACE_URL,
                f"caseops:ip-matter-link:{row['company_id']}:{row['id']}:{row['matter_id']}",
            )
        )
        bind.execute(
            sa.text(
                "INSERT INTO ip_matter_links ("
                "id, company_id, docket_id, matter_id, relation_role, effective_from, "
                "retired_at, source, source_reference, reason, "
                "retirement_reason, created_by_membership_id, "
                "retired_by_membership_id, created_at, updated_at"
                ") VALUES ("
                ":id, :company_id, :docket_id, :matter_id, 'operational', :created_at, "
                "NULL, 'migration', :source_reference, :reason, NULL, NULL, NULL, "
                ":created_at, :created_at)"
            ),
            {
                "id": link_id,
                "company_id": row["company_id"],
                "docket_id": row["id"],
                "matter_id": row["matter_id"],
                "source_reference": f"ip_docket_records:{row['id']}:matter_id",
                "reason": "Backfilled from the existing operational Matter pointer.",
                "created_at": row["created_at"],
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    incompatible = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ip_matter_links "
            "WHERE source <> 'migration' OR retired_at IS NOT NULL "
            "OR relation_role <> 'operational'"
        )
    ).scalar_one()
    if incompatible:
        raise RuntimeError(
            "refusing to downgrade: retained governed IP Matter-link history "
            "requires the IPLF-044 contract"
        )
    op.drop_table("ip_matter_links")
