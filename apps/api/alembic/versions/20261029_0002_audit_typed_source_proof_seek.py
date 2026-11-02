"""Type-leading lookup support for exact imported-source materialization proof.

Revision ID: 20261029_0002
Revises: 20261029_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Build one nonunique PostgreSQL index
concurrently under the canonical migration lock/statement budgets. Recover only
an invalid same-shape owned index; refuse conflicting names before any DDL.
MIGRATION-ROLLBACK: safe. Only this support index is removed transactionally;
all audit/source rows, source lineage, policies, existing indexes and data
classifications remain unchanged. SQLite requires the exact immediate parent.
The existing 0001 company-leading index remains intact on upgrade/downgrade.
An index declaration is not measured default/adverse/generic-plan acceptance.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261029_0002"
down_revision = "20261029_0001"
branch_labels = None
depends_on = None

INDEXES = ((
    "audit_events",
    "ix_audit_events_typed_source_proof_seek",
    ["target_type", "target_id", "company_id", "ip_docket_id", "action", "id"],
),)


_INDEX_STATE = sa.text("""
    SELECT c.relkind, t.relname AS owner, tn.nspname AS owner_schema,
           am.amname AS method, i.indisvalid, i.indisready, i.indisunique,
           i.indexprs IS NULL AS expression_free,
           pg_get_expr(i.indpred, i.indrelid) AS predicate,
           i.indnkeyatts = i.indnatts AS no_includes,
           ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, pos)
                 JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                 ORDER BY k.pos) AS columns,
           (SELECT bool_and(opc.opcdefault AND i.indcollation[k] = a.attcollation
                            AND i.indoption[k] = 0)
            FROM generate_series(0, i.indnkeyatts - 1) k
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[k]
            JOIN pg_opclass opc ON opc.oid = i.indclass[k]) AS standard_keys,
           current_schema() AS schema
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_index i ON i.indexrelid = c.oid
    LEFT JOIN pg_class t ON t.oid = i.indrelid
    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
    LEFT JOIN pg_am am ON am.oid = c.relam
    WHERE n.nspname = current_schema() AND c.relname = :name
""")


def _postgres_state(bind, table, name, columns):
    state = bind.execute(_INDEX_STATE, {"name": name}).mappings().first()
    if state is not None and not (
        state["relkind"] == "i"
        and state["owner"] == table
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["expression_free"]
        and state["predicate"] is None
        and state["no_includes"]
        and state["standard_keys"]
        and list(state["columns"]) == columns
    ):
        raise RuntimeError("Audit typed source-proof seek index has a conflicting shape.")
    return state


def _sqlite_exists(bind, table, name, columns):
    state = (
        bind.execute(
            sa.text("SELECT type, tbl_name FROM main.sqlite_master WHERE name = :name"),
            {"name": name},
        )
        .mappings()
        .first()
    )
    if state is None:
        return False
    if state["type"] != "index" or state["tbl_name"] != table:
        raise RuntimeError("Audit typed source-proof seek index has a conflicting shape.")
    indexes = bind.exec_driver_sql(f'PRAGMA main.index_list("{table}")').mappings().all()
    index = next(row for row in indexes if row["name"] == name)
    keys = [
        row
        for row in bind.exec_driver_sql(f'PRAGMA main.index_xinfo("{name}")').mappings()
        if row["key"]
    ]
    if not (
        not index["unique"]
        and not index["partial"]
        and index["origin"] == "c"
        and [row["name"] for row in keys] == columns
        and all(row["cid"] >= 0 and row["desc"] == 0 and row["coll"] == "BINARY" for row in keys)
    ):
        raise RuntimeError("Audit typed source-proof seek index has a conflicting shape.")
    sql = bind.scalar(
        sa.text("SELECT sql FROM main.sqlite_master WHERE name = :name"), {"name": name}
    )
    predicate = sql.rsplit(" WHERE ", 1)[-1] if " WHERE " in sql else None
    if predicate is not None:
        raise RuntimeError("Audit typed source-proof index predicate has a conflicting shape.")
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        schema = bind.scalar(sa.text("SELECT current_schema()"))
        if not schema:
            raise RuntimeError("Audit typed source-proof seek index schema is unavailable.")
        with op.get_context().autocommit_block():
            # A conflicting name must refuse before creating/dropping any sibling.
            for table, name, columns in INDEXES:
                _postgres_state(bind, table, name, columns)
            for table, name, columns in INDEXES:
                state = _postgres_state(bind, table, name, columns)
                if state is not None and not (state["indisvalid"] and state["indisready"]):
                    op.drop_index(
                        name, table_name=table, schema=schema, postgresql_concurrently=True
                    )
                    state = None
                if state is None:
                    op.create_index(
                        name,
                        table,
                        columns,
                        schema=schema,
                        postgresql_concurrently=True,
                        if_not_exists=True,
                    )
                state = _postgres_state(bind, table, name, columns)
                if state is None or not state["indisvalid"] or not state["indisready"]:
                    raise RuntimeError("Audit typed source-proof seek index is not ready.")
    elif bind.dialect.name == "sqlite":
        for table, name, columns in INDEXES:
            _sqlite_exists(bind, table, name, columns)
        for table, name, columns in INDEXES:
            if not _sqlite_exists(bind, table, name, columns):
                op.create_index(
                    name,
                    table,
                    columns,
                    schema="main",
                )
            if not _sqlite_exists(bind, table, name, columns):
                raise RuntimeError("Audit typed source-proof seek index is not ready.")
    else:
        raise RuntimeError("Unsupported audit source-proof seek index dialect.")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        states = [
            (table, name, _postgres_state(bind, table, name, columns))
            for table, name, columns in INDEXES
        ]
        for table, name, state in reversed(states):
            if state is not None:
                op.drop_index(name, table_name=table, schema=state["schema"])
    elif bind.dialect.name == "sqlite":
        if op.get_context().opts.get("destination_rev") != down_revision:
            raise RuntimeError("SQLite seek index downgrade requires exact immediate parent.")
        states = [
            (table, name, _sqlite_exists(bind, table, name, columns))
            for table, name, columns in INDEXES
        ]
        for table, name, exists in reversed(states):
            if exists:
                op.drop_index(name, table_name=table, schema="main")
    else:
        raise RuntimeError("Unsupported audit source-proof seek index dialect.")
