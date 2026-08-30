"""Retain immutable IP cost evidence while reconciliation stays mutable.

Revision ID: 20260830_0003
Revises: 20260830_0002

IPLF-039F / UJ-52-EXC-01.  A matterless official fee is a retained legal
fact, not a draft billing row.  The service already creates it explicitly as
nonbillable, but the database previously allowed a later writer to rewrite
``matter_id``/``billable``/the amount/evidence reference and turn that same
row into a billing candidate.  That defeated both the nonbillable boundary
and the claim that the official-fee evidence is immutable.

This migration freezes the cost/evidence identity columns and rejects row
deletion.  Only the reconciliation projection columns remain mutable.  The
guard is implemented on PostgreSQL and SQLite so migration tests and local
acceptance exercise the same boundary as production.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260830_0003"
down_revision = "20260830_0002"
branch_labels = None
depends_on = None

TABLE = "ip_cost_items"
UPDATE_TRIGGER = "trg_ip_cost_items_evidence_immutable"
DELETE_TRIGGER = "trg_ip_cost_items_evidence_retained"
FUNCTION = "caseops_ip_cost_items_evidence_immutable"

# Reconciliation is deliberately absent.  These are the legal cost fact and
# its billing-reference identity; changing one means recording a new cost
# item, not mutating the evidence already captured.
IMMUTABLE_COLUMNS = (
    "id",
    "company_id",
    "docket_id",
    "matter_id",
    "category",
    "description",
    "amount_minor",
    "currency",
    "billable",
    "cost_nature",
    "rate_confidential",
    "fx_rate",
    "fx_rate_source",
    "fx_converted_at",
    "base_amount_minor",
    "base_currency",
    "evidence_reference",
    "billing_link_type",
    "billing_link_id",
    "created_by_membership_id",
    "created_at",
)


def _create_postgres_guards(bind: sa.Connection) -> None:
    old_row = ", ".join(f"OLD.{column}" for column in IMMUTABLE_COLUMNS)
    new_row = ", ".join(f"NEW.{column}" for column in IMMUTABLE_COLUMNS)
    bind.execute(
        sa.text(
            f"""
            CREATE FUNCTION {FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION
                        'IP cost evidence is retained; record a correction instead of deleting it';
                END IF;
                IF ROW({old_row}) IS DISTINCT FROM ROW({new_row}) THEN
                    RAISE EXCEPTION
                        'IP cost evidence is immutable; '
                        'record a correction instead of rewriting it';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {UPDATE_TRIGGER}
            BEFORE UPDATE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {DELETE_TRIGGER}
            BEFORE DELETE ON {TABLE}
            FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()
            """
        )
    )


def _create_sqlite_guards(bind: sa.Connection) -> None:
    changed = " OR ".join(
        f'OLD."{column}" IS NOT NEW."{column}"' for column in IMMUTABLE_COLUMNS
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {UPDATE_TRIGGER}
            BEFORE UPDATE ON {TABLE}
            FOR EACH ROW
            WHEN {changed}
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'IP cost evidence is immutable; record a correction instead of rewriting it'
                );
            END
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {DELETE_TRIGGER}
            BEFORE DELETE ON {TABLE}
            FOR EACH ROW
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'IP cost evidence is retained; record a correction instead of deleting it'
                );
            END
            """
        )
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        _create_postgres_guards(bind)
    else:
        _create_sqlite_guards(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {DELETE_TRIGGER} ON {TABLE}"))
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER} ON {TABLE}"))
        bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {FUNCTION}()"))
    else:
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {DELETE_TRIGGER}"))
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {UPDATE_TRIGGER}"))
