"""Add the canonical post-registration recordal foundation.

Revision ID: 20260825_0005
Revises: 20260825_0004
Create Date: 2026-08-25

IPLF-058A adds one typed recordal aggregate and links it to existing docket
events and title interests. Documents, costs, deadlines, registry snapshots,
access predicates, lifecycle and audit remain with their existing owners.

MIGRATION-LOCK-RISK: acknowledged: one additive empty table plus additive
nullable/defaulted columns, indexes and constraints; PostgreSQL lock timeout is
five seconds. SQLite test upgrades may rebuild altered tables.
MIGRATION-ROLLBACK: restore-forward: once recordal/title/event data uses the new
contract. A downgrade is allowed only while every added legal-data field is
still empty or at its migration default.
DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op

revision = "20260825_0005"
down_revision = "20260825_0004"
branch_labels = None
depends_on = None


def _set_lock_timeout() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def upgrade() -> None:
    _set_lock_timeout()
    op.create_table(
        "ip_post_registration_recordals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("recordal_type", sa.String(length=40), nullable=False),
        sa.Column("legal_basis", sa.Text(), nullable=False),
        sa.Column("form_code", sa.String(length=80), nullable=False),
        sa.Column("parties_json", sa.JSON(), nullable=False),
        sa.Column("executed_on", sa.Date(), nullable=True),
        sa.Column("effective_on", sa.Date(), nullable=True),
        sa.Column("affected_registration_refs_json", sa.JSON(), nullable=False),
        sa.Column("affected_classes_json", sa.JSON(), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("supporting_instrument_refs_json", sa.JSON(), nullable=False),
        sa.Column("fee_cost_item_refs_json", sa.JSON(), nullable=False),
        sa.Column("filing_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("acceptance_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("deadline_rule_key", sa.String(length=160), nullable=True),
        sa.Column("registry_snapshot_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "recordal_type IN ('renewal', 'restoration', 'assignment', 'transmission', "
            "'name_change', 'address_change', 'address_for_service_change', "
            "'registered_user', 'licence', 'association', 'division', 'limitation', "
            "'disclaimer', 'certified_copy', 'well_known_mark')",
            name="ck_ip_recordal_type",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'filed', 'defective', 'accepted', "
            "'rejected', 'withdrawn')",
            name="ck_ip_recordal_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_recordal_version_positive"),
        sa.CheckConstraint(
            "effective_on IS NULL OR executed_on IS NULL OR effective_on >= executed_on",
            name="ck_ip_recordal_effective_after_execution",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_recordal_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["registry_snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_ip_recordal_registry_snapshot_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_recordal_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_recordal_updater_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_recordal_id_company"),
    )
    op.create_index(
        "ix_ip_post_registration_recordals_docket_id",
        "ip_post_registration_recordals",
        ["docket_id"],
    )
    op.create_index(
        "ix_ip_post_registration_recordals_registry_snapshot_id",
        "ip_post_registration_recordals",
        ["registry_snapshot_id"],
    )
    op.create_index(
        "ix_ip_recordals_company_docket_status",
        "ip_post_registration_recordals",
        ["company_id", "docket_id", "status"],
    )
    op.create_index(
        "ix_ip_recordals_company_type_status",
        "ip_post_registration_recordals",
        ["company_id", "recordal_type", "status"],
    )
    op.create_index(
        "ix_ip_post_registration_recordals_created_by_membership_id",
        "ip_post_registration_recordals",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_ip_post_registration_recordals_updated_by_membership_id",
        "ip_post_registration_recordals",
        ["updated_by_membership_id"],
    )

    with op.batch_alter_table("ip_title_interests") as batch:
        batch.add_column(sa.Column("party_role", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("executed_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("source_recordal_id", sa.String(length=36), nullable=True))
        batch.add_column(
            sa.Column(
                "scope_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(sa.Column("registry_recorded_on", sa.Date(), nullable=True))
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch.add_column(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            )
        )
        batch.create_unique_constraint("uq_ip_title_interest_id_company", ["id", "company_id"])
        batch.create_check_constraint("ck_ip_title_interest_version_positive", "version > 0")
        batch.create_foreign_key(
            "fk_ip_title_interest_recordal_company",
            "ip_post_registration_recordals",
            ["source_recordal_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_ip_title_interests_source_recordal", ["source_recordal_id"])

    with op.batch_alter_table("ip_docket_events") as batch:
        batch.add_column(sa.Column("recordal_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_ip_docket_event_recordal_company",
            "ip_post_registration_recordals",
            ["recordal_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_ip_docket_event_recordal_kind",
            "recordal_id IS NULL OR event_kind = 'post_registration_recordal_transaction'",
        )
        batch.create_index("ix_ip_docket_events_recordal_id", ["recordal_id"])
        batch.create_index(
            "ix_ip_docket_events_company_recordal_sequence",
            ["company_id", "recordal_id", "sequence"],
        )


def _json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def downgrade() -> None:
    _set_lock_timeout()
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM ip_post_registration_recordals LIMIT 1")).first():
        raise RuntimeError("Restore-forward required: post-registration recordals exist.")
    if bind.execute(
        sa.text("SELECT 1 FROM ip_docket_events WHERE recordal_id IS NOT NULL LIMIT 1")
    ).first():
        raise RuntimeError("Restore-forward required: recordal docket events exist.")
    title_rows = bind.execute(
        sa.text(
            "SELECT party_role, executed_on, source_recordal_id, scope_json, "
            "registry_recorded_on, version FROM ip_title_interests"
        )
    ).mappings()
    for row in title_rows:
        if (
            row["party_role"] is not None
            or row["executed_on"] is not None
            or row["source_recordal_id"] is not None
            or (_json_value(row["scope_json"]) or {})
            or row["registry_recorded_on"] is not None
            or row["version"] != 1
        ):
            raise RuntimeError("Restore-forward required: extended title-interest data exists.")

    with op.batch_alter_table("ip_docket_events") as batch:
        batch.drop_index("ix_ip_docket_events_company_recordal_sequence")
        batch.drop_index("ix_ip_docket_events_recordal_id")
        batch.drop_constraint("ck_ip_docket_event_recordal_kind", type_="check")
        batch.drop_constraint("fk_ip_docket_event_recordal_company", type_="foreignkey")
        batch.drop_column("recordal_id")
    with op.batch_alter_table("ip_title_interests") as batch:
        batch.drop_index("ix_ip_title_interests_source_recordal")
        batch.drop_constraint("fk_ip_title_interest_recordal_company", type_="foreignkey")
        batch.drop_constraint("ck_ip_title_interest_version_positive", type_="check")
        batch.drop_constraint("uq_ip_title_interest_id_company", type_="unique")
        batch.drop_column("updated_at")
        batch.drop_column("version")
        batch.drop_column("registry_recorded_on")
        batch.drop_column("scope_json")
        batch.drop_column("source_recordal_id")
        batch.drop_column("executed_on")
        batch.drop_column("party_role")
    op.drop_table("ip_post_registration_recordals")
