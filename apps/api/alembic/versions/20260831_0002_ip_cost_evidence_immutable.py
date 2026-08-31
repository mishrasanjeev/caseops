"""Retain immutable IP costs with append-only correction lineage.

Revision ID: 20260831_0002
Revises: 20260831_0001

IPLF-039F / UJ-52-EXC-01. Matterless official fees are retained legal facts,
not draft billing rows. This revision closes four database-level gaps:

* cost/evidence identity is immutable, while parent-owned docket disposition
  may still exercise the declared ``ON DELETE CASCADE``;
* corrections and voids are append-only rows, with a replacement cost for a
  supersession and no replacement for a void;
* matterless/nonbillable/estimate reconciliation projections are constrained
  to their terminal status with no canonical amount or difference; and
* new creator/reconciler/correction actors must be active members of the cost
  tenant at the time the evidence or reconciliation is written.

Existing terminal rows are normalized before the stronger checks are added.
No invoice, payment, time-entry, or outside-counsel accounting state is added.

DATA-GOVERNANCE-MAP: updated

MIGRATION-LOCK-RISK: acknowledged - the correction indexes are built on the
new, empty table before application writers can insert correction rows.
MIGRATION-ROLLBACK: restore-forward - once correction evidence exists this
migration refuses downgrade so append-only legal evidence cannot be discarded.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260831_0002"
down_revision = "20260831_0001"
branch_labels = None
depends_on = None

COST_TABLE = "ip_cost_items"
CORRECTION_TABLE = "ip_cost_item_corrections"
COST_UPDATE_TRIGGER = "trg_ip_cost_items_evidence_immutable"
COST_DELETE_TRIGGER = "trg_ip_cost_items_evidence_retained"
COST_ACTOR_INSERT_TRIGGER = "trg_ip_cost_items_actor_tenant_insert"
COST_RECONCILER_INSERT_TRIGGER = "trg_ip_cost_items_reconciler_tenant_insert"
COST_RECONCILER_TRIGGER = "trg_ip_cost_items_reconciler_tenant_update"
CORRECTION_UPDATE_TRIGGER = "trg_ip_cost_corrections_append_only"
CORRECTION_DELETE_TRIGGER = "trg_ip_cost_corrections_retained"
CORRECTION_ACTOR_TRIGGER = "trg_ip_cost_corrections_actor_tenant_insert"
COST_FUNCTION = "caseops_ip_cost_items_guard"
CORRECTION_FUNCTION = "caseops_ip_cost_corrections_guard"

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

_OLD_CHECKS = {
    "ck_ip_cost_item_matterless_is_nonbillable": (
        "matter_id IS NOT NULL OR (billable = false AND billing_link_type IS NULL)"
    ),
    "ck_ip_cost_item_nonbillable_has_no_billing_link": (
        "billable = true OR billing_link_type IS NULL"
    ),
    "ck_ip_cost_item_estimate_has_no_billing_link": (
        "cost_nature = 'actual' OR billing_link_type IS NULL"
    ),
}

_STRONG_CHECKS = {
    "ck_ip_cost_item_matterless_is_nonbillable": (
        "matter_id IS NOT NULL OR (billable = false AND billing_link_type IS NULL "
        "AND reconciliation_status = 'nonbillable' "
        "AND canonical_amount_minor IS NULL "
        "AND reconciliation_difference_minor IS NULL)"
    ),
    "ck_ip_cost_item_nonbillable_has_no_billing_link": (
        "billable = true OR (billing_link_type IS NULL "
        "AND reconciliation_status = 'nonbillable' "
        "AND canonical_amount_minor IS NULL "
        "AND reconciliation_difference_minor IS NULL)"
    ),
    "ck_ip_cost_item_estimate_has_no_billing_link": (
        "cost_nature = 'actual' OR (billing_link_type IS NULL "
        "AND reconciliation_status IN ('estimate', 'nonbillable') "
        "AND canonical_amount_minor IS NULL "
        "AND reconciliation_difference_minor IS NULL)"
    ),
    "ck_ip_cost_item_reconciliation_status": (
        "reconciliation_status IN ('matched', 'mismatch', 'missing', "
        "'unlinked', 'estimate', 'nonbillable')"
    ),
}


def _normalize_terminal_projections(bind: sa.Connection) -> None:
    bind.execute(
        sa.text(
            "UPDATE ip_cost_items SET reconciliation_status = 'nonbillable', "
            "canonical_amount_minor = NULL, reconciliation_difference_minor = NULL "
            "WHERE matter_id IS NULL OR billable = false"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE ip_cost_items SET reconciliation_status = 'estimate', "
            "canonical_amount_minor = NULL, reconciliation_difference_minor = NULL "
            "WHERE billable = true AND cost_nature = 'estimate'"
        )
    )


def _replace_cost_checks() -> None:
    with op.batch_alter_table(COST_TABLE) as batch:
        for name in _OLD_CHECKS:
            batch.drop_constraint(name, type_="check")
        for name, expression in _STRONG_CHECKS.items():
            batch.create_check_constraint(name, expression)
        batch.create_unique_constraint(
            "uq_ip_cost_item_id_company_docket",
            ["id", "company_id", "docket_id"],
        )


def _create_correction_table() -> None:
    op.create_table(
        CORRECTION_TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("source_cost_item_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("replacement_cost_item_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("evidence_reference", sa.String(500), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_cost_correction_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            name="fk_ip_cost_correction_source_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            name="fk_ip_cost_correction_replacement_scope",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "action IN ('void', 'supersede')",
            name="ck_ip_cost_correction_action",
        ),
        sa.CheckConstraint(
            "(action = 'void' AND replacement_cost_item_id IS NULL) OR "
            "(action = 'supersede' AND replacement_cost_item_id IS NOT NULL)",
            name="ck_ip_cost_correction_replacement",
        ),
        sa.CheckConstraint(
            "replacement_cost_item_id IS NULL OR "
            "replacement_cost_item_id <> source_cost_item_id",
            name="ck_ip_cost_correction_not_self",
        ),
        sa.UniqueConstraint(
            "source_cost_item_id",
            name="uq_ip_cost_correction_source",
        ),
        sa.UniqueConstraint(
            "replacement_cost_item_id",
            name="uq_ip_cost_correction_replacement",
        ),
    )
    op.create_index(
        "ix_ip_cost_corrections_company_docket",
        CORRECTION_TABLE,
        ["company_id", "docket_id"],
    )
    op.create_index(
        "ix_ip_cost_corrections_source_scope",
        CORRECTION_TABLE,
        ["source_cost_item_id", "company_id", "docket_id"],
    )
    op.create_index(
        "ix_ip_cost_corrections_replacement_scope",
        CORRECTION_TABLE,
        ["replacement_cost_item_id", "company_id", "docket_id"],
    )
    for column in (
        "docket_id",
        "source_cost_item_id",
        "replacement_cost_item_id",
        "created_by_membership_id",
    ):
        op.create_index(
            f"ix_ip_cost_item_corrections_{column}",
            CORRECTION_TABLE,
            [column],
        )


def _create_postgres_guards(bind: sa.Connection) -> None:
    old_row = ", ".join(f"OLD.{column}" for column in IMMUTABLE_COLUMNS)
    new_row = ", ".join(f"NEW.{column}" for column in IMMUTABLE_COLUMNS)
    bind.execute(
        sa.text(
            f"""
            CREATE FUNCTION {COST_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    IF EXISTS (
                        SELECT 1 FROM ip_docket_records
                        WHERE id = OLD.docket_id AND company_id = OLD.company_id
                    ) THEN
                        RAISE EXCEPTION
                            'IP cost evidence is retained; append a void or supersession';
                    END IF;
                    RETURN OLD;
                END IF;
                IF TG_OP = 'INSERT' THEN
                    IF NEW.created_by_membership_id IS NULL OR NOT EXISTS (
                        SELECT 1 FROM company_memberships
                        WHERE id = NEW.created_by_membership_id
                          AND company_id = NEW.company_id
                          AND is_active = true
                    ) THEN
                        RAISE EXCEPTION
                            'IP cost creator must be an active member of the cost tenant';
                    END IF;
                ELSIF ROW({old_row}) IS DISTINCT FROM ROW({new_row}) THEN
                    RAISE EXCEPTION
                        'IP cost evidence is immutable; append a void or supersession';
                END IF;
                IF NEW.reconciled_by_membership_id IS NOT NULL
                   AND (
                       TG_OP = 'INSERT'
                       OR NEW.reconciled_by_membership_id IS DISTINCT FROM
                          OLD.reconciled_by_membership_id
                   )
                   AND NOT EXISTS (
                    SELECT 1 FROM company_memberships
                    WHERE id = NEW.reconciled_by_membership_id
                      AND company_id = NEW.company_id
                      AND is_active = true
                ) THEN
                    RAISE EXCEPTION
                        'IP cost reconciler must be an active member of the cost tenant';
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
            CREATE TRIGGER {COST_UPDATE_TRIGGER}
            BEFORE INSERT OR UPDATE ON {COST_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {COST_FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {COST_DELETE_TRIGGER}
            BEFORE DELETE ON {COST_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {COST_FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE FUNCTION {CORRECTION_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'UPDATE' THEN
                    RAISE EXCEPTION 'IP cost corrections are append-only';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    IF EXISTS (
                        SELECT 1 FROM ip_docket_records
                        WHERE id = OLD.docket_id AND company_id = OLD.company_id
                    ) THEN
                        RAISE EXCEPTION 'IP cost corrections are retained';
                    END IF;
                    RETURN OLD;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM company_memberships
                    WHERE id = NEW.created_by_membership_id
                      AND company_id = NEW.company_id
                      AND is_active = true
                ) THEN
                    RAISE EXCEPTION
                        'IP cost correction actor must be an active member of the cost tenant';
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
            CREATE TRIGGER {CORRECTION_UPDATE_TRIGGER}
            BEFORE INSERT OR UPDATE ON {CORRECTION_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {CORRECTION_FUNCTION}()
            """
        )
    )
    bind.execute(
        sa.text(
            f"""
            CREATE TRIGGER {CORRECTION_DELETE_TRIGGER}
            BEFORE DELETE ON {CORRECTION_TABLE}
            FOR EACH ROW EXECUTE FUNCTION {CORRECTION_FUNCTION}()
            """
        )
    )


def _create_sqlite_guards(bind: sa.Connection) -> None:
    changed = " OR ".join(
        f'OLD."{column}" IS NOT NEW."{column}"' for column in IMMUTABLE_COLUMNS
    )
    statements = (
        f"""
        CREATE TRIGGER {COST_UPDATE_TRIGGER}
        BEFORE UPDATE ON {COST_TABLE}
        FOR EACH ROW WHEN {changed}
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost evidence is immutable; append a void or supersession'
            );
        END
        """,
        f"""
        CREATE TRIGGER {COST_DELETE_TRIGGER}
        BEFORE DELETE ON {COST_TABLE}
        FOR EACH ROW WHEN EXISTS (
            SELECT 1 FROM ip_docket_records
            WHERE id = OLD.docket_id AND company_id = OLD.company_id
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost evidence is retained; append a void or supersession'
            );
        END
        """,
        f"""
        CREATE TRIGGER {COST_ACTOR_INSERT_TRIGGER}
        BEFORE INSERT ON {COST_TABLE}
        FOR EACH ROW WHEN NEW.created_by_membership_id IS NULL OR NOT EXISTS (
            SELECT 1 FROM company_memberships
            WHERE id = NEW.created_by_membership_id
              AND company_id = NEW.company_id
              AND is_active = 1
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost creator must be an active member of the cost tenant'
            );
        END
        """,
        f"""
        CREATE TRIGGER {COST_RECONCILER_INSERT_TRIGGER}
        BEFORE INSERT ON {COST_TABLE}
        FOR EACH ROW WHEN NEW.reconciled_by_membership_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM company_memberships
            WHERE id = NEW.reconciled_by_membership_id
              AND company_id = NEW.company_id
              AND is_active = 1
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost reconciler must be an active member of the cost tenant'
            );
        END
        """,
        f"""
        CREATE TRIGGER {COST_RECONCILER_TRIGGER}
        BEFORE UPDATE OF reconciled_by_membership_id ON {COST_TABLE}
        FOR EACH ROW WHEN NEW.reconciled_by_membership_id IS NOT NULL
        AND NEW.reconciled_by_membership_id IS NOT OLD.reconciled_by_membership_id
        AND NOT EXISTS (
            SELECT 1 FROM company_memberships
            WHERE id = NEW.reconciled_by_membership_id
              AND company_id = NEW.company_id
              AND is_active = 1
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost reconciler must be an active member of the cost tenant'
            );
        END
        """,
        f"""
        CREATE TRIGGER {CORRECTION_UPDATE_TRIGGER}
        BEFORE UPDATE ON {CORRECTION_TABLE}
        FOR EACH ROW
        BEGIN
            SELECT RAISE(ABORT, 'IP cost corrections are append-only');
        END
        """,
        f"""
        CREATE TRIGGER {CORRECTION_DELETE_TRIGGER}
        BEFORE DELETE ON {CORRECTION_TABLE}
        FOR EACH ROW WHEN EXISTS (
            SELECT 1 FROM ip_docket_records
            WHERE id = OLD.docket_id AND company_id = OLD.company_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'IP cost corrections are retained');
        END
        """,
        f"""
        CREATE TRIGGER {CORRECTION_ACTOR_TRIGGER}
        BEFORE INSERT ON {CORRECTION_TABLE}
        FOR EACH ROW WHEN NOT EXISTS (
            SELECT 1 FROM company_memberships
            WHERE id = NEW.created_by_membership_id
              AND company_id = NEW.company_id
              AND is_active = 1
        )
        BEGIN
            SELECT RAISE(
                ABORT,
                'IP cost correction actor must be an active member of the cost tenant'
            );
        END
        """,
    )
    for statement in statements:
        bind.execute(sa.text(statement))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
    _normalize_terminal_projections(bind)
    _replace_cost_checks()
    _create_correction_table()
    if bind.dialect.name == "postgresql":
        _create_postgres_guards(bind)
    else:
        _create_sqlite_guards(bind)


def _drop_guards(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        for trigger, table in (
            (CORRECTION_DELETE_TRIGGER, CORRECTION_TABLE),
            (CORRECTION_UPDATE_TRIGGER, CORRECTION_TABLE),
            (COST_DELETE_TRIGGER, COST_TABLE),
            (COST_UPDATE_TRIGGER, COST_TABLE),
        ):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {CORRECTION_FUNCTION}()"))
        bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {COST_FUNCTION}()"))
    else:
        for trigger in (
            CORRECTION_ACTOR_TRIGGER,
            CORRECTION_DELETE_TRIGGER,
            CORRECTION_UPDATE_TRIGGER,
            COST_RECONCILER_TRIGGER,
            COST_RECONCILER_INSERT_TRIGGER,
            COST_ACTOR_INSERT_TRIGGER,
            COST_DELETE_TRIGGER,
            COST_UPDATE_TRIGGER,
        ):
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))


def downgrade() -> None:
    bind = op.get_bind()
    has_corrections = bind.scalar(
        sa.text(f"SELECT EXISTS (SELECT 1 FROM {CORRECTION_TABLE} LIMIT 1)")
    )
    if has_corrections:
        raise RuntimeError(
            "20260831_0002 cannot be downgraded after IP cost correction evidence "
            "exists; preserve the append-only rows and restore or roll forward."
        )
    _drop_guards(bind)
    op.drop_table(CORRECTION_TABLE)
    with op.batch_alter_table(COST_TABLE) as batch:
        batch.drop_constraint("uq_ip_cost_item_id_company_docket", type_="unique")
        for name in reversed(_STRONG_CHECKS):
            batch.drop_constraint(name, type_="check")
        for name, expression in _OLD_CHECKS.items():
            batch.create_check_constraint(name, expression)
