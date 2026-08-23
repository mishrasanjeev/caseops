"""Scope existing IP parties to opposition proceedings.

Revision ID: 20260823_0002
Revises: 20260823_0001
Create Date: 2026-08-23

IPLF-040B keeps ``ip_parties_and_roles`` and ``ip_docket_events`` as the
canonical owners. The nullable proceeding link distinguishes parties for two
oppositions against the same application, while legacy docket-level parties
remain valid. Opposition profile revisions are stored as typed append-only
docket events, so the existing stage-event trigger is widened rather than a
parallel history table being introduced.

MIGRATION-LOCK-RISK: acknowledged: one nullable column, composite foreign key,
and index are added to an existing IP table; no backfill or row rewrite occurs.
MIGRATION-ROLLBACK: restore-forward: downgrade refuses while proceeding-scoped
parties or opposition profile evidence exist.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260823_0002"
down_revision = "20260823_0001"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def _profile_predicate(dialect: str, prefix: str = "OLD") -> str:
    if dialect == "postgresql":
        return (
            "COALESCE((" + prefix + ".payload_json ->> "
            "'opposition_stage_transition')::boolean, false) OR "
            "COALESCE((" + prefix + ".payload_json ->> "
            "'opposition_profile_revision')::boolean, false)"
        )
    return (
        "COALESCE(json_extract(" + prefix + ".payload_json, "
        "'$.opposition_stage_transition'), 0) = 1 OR "
        "COALESCE(json_extract(" + prefix + ".payload_json, "
        "'$.opposition_profile_revision'), 0) = 1"
    )


def _install_event_guard(bind: sa.Connection, *, profile_aware: bool) -> None:
    if bind.dialect.name == "postgresql":
        predicate = (
            _profile_predicate("postgresql")
            if profile_aware
            else "COALESCE((OLD.payload_json ->> 'opposition_stage_transition')::boolean, false)"
        )
        op.execute(
            sa.text(
                f"""
                CREATE OR REPLACE FUNCTION reject_ip_docket_event_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF {predicate} THEN
                        RAISE EXCEPTION 'opposition events are append-only';
                    END IF;
                    IF TG_OP = 'DELETE' THEN
                        RETURN OLD;
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ip_docket_events_append_only_update")
        op.execute("DROP TRIGGER IF EXISTS trg_ip_docket_events_append_only_delete")
        predicate = (
            _profile_predicate("sqlite")
            if profile_aware
            else "COALESCE(json_extract(OLD.payload_json, '$.opposition_stage_transition'), 0) = 1"
        )
        for operation in ("UPDATE", "DELETE"):
            op.execute(
                sa.text(
                    f"""
                    CREATE TRIGGER trg_ip_docket_events_append_only_{operation.lower()}
                    BEFORE {operation} ON ip_docket_events
                    WHEN {predicate}
                    BEGIN
                        SELECT RAISE(ABORT, 'opposition events are append-only');
                    END
                    """
                )
            )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    with op.batch_alter_table("ip_parties_and_roles") as batch:
        batch.add_column(sa.Column("proceeding_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_ip_party_proceeding_company",
            "ip_proceedings",
            ["proceeding_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        batch.create_index(
            "ix_ip_parties_proceeding_company",
            ["proceeding_id", "company_id"],
        )
    _install_event_guard(bind, profile_aware=True)


def downgrade() -> None:
    bind = op.get_bind()
    scoped_parties = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ip_parties_and_roles WHERE proceeding_id IS NOT NULL"
        )
    ).scalar_one()
    profile_events = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ip_docket_events "
            "WHERE event_kind = 'opposition_profile'"
        )
    ).scalar_one()
    if scoped_parties or profile_events:
        raise RuntimeError(
            "refusing to downgrade: retained opposition workspace evidence requires "
            "the IPLF-040B contract"
        )
    with op.batch_alter_table("ip_parties_and_roles") as batch:
        batch.drop_index("ix_ip_parties_proceeding_company")
        batch.drop_constraint("fk_ip_party_proceeding_company", type_="foreignkey")
        batch.drop_column("proceeding_id")
    _install_event_guard(bind, profile_aware=False)
