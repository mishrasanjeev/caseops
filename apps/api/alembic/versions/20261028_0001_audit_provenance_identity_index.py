"""Bound exact tenant/source provenance probes without changing their predicate.

Revision ID: 20261028_0001
Revises: 20261026_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. PostgreSQL builds/rebuilds concurrently under
the existing migration budgets; ordinary downgrade DROP remains transactional
with its bounded table lock. SQLite serves isolated development/tests.
MIGRATION-ROLLBACK: safe. Drops only this support index, never audit/business
rows. SQLite refuses non-parent/unknown destinations before DROP.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261028_0001"
down_revision = "20261026_0001"
branch_labels = None
depends_on = None

_TABLE = "audit_events"
_NAME = "ix_audit_events_source_provenance"
_COLUMNS = ["company_id", "action", "target_type", "target_id", "ip_docket_id"]
_INDEX_STATE = sa.text("""
    SELECT c.relkind, t.relname AS owner, tn.nspname AS owner_schema,
           am.amname AS method, i.indisvalid, i.indisready, i.indisunique,
           i.indpred IS NULL AND i.indexprs IS NULL AS plain,
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


def _postgres_state(bind):
    state = bind.execute(_INDEX_STATE, {"name": _NAME}).mappings().first()
    if state is not None and not (
        state["relkind"] == "i"
        and state["owner"] == _TABLE
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["plain"]
        and state["no_includes"]
        and state["standard_keys"]
        and list(state["columns"]) == _COLUMNS
    ):
        raise RuntimeError("Audit provenance index has a conflicting shape.")
    return state


def _sqlite_exists(bind):
    state = (
        bind.execute(
            sa.text("SELECT type, tbl_name FROM main.sqlite_master WHERE name = :name"),
            {"name": _NAME},
        )
        .mappings()
        .first()
    )
    if state is None:
        return False
    if state["type"] != "index" or state["tbl_name"] != _TABLE:
        raise RuntimeError("Audit provenance index has a conflicting shape.")
    indexes = bind.exec_driver_sql(f'PRAGMA main.index_list("{_TABLE}")').mappings().all()
    index = next(row for row in indexes if row["name"] == _NAME)
    keys = [
        row
        for row in bind.exec_driver_sql(f'PRAGMA main.index_xinfo("{_NAME}")').mappings()
        if row["key"]
    ]
    if not (
        not index["unique"]
        and not index["partial"]
        and index["origin"] == "c"
        and [row["name"] for row in keys] == _COLUMNS
        and all(row["cid"] >= 0 and row["desc"] == 0 and row["coll"] == "BINARY" for row in keys)
    ):
        raise RuntimeError("Audit provenance index has a conflicting shape.")
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        schema = bind.scalar(sa.text("SELECT current_schema()"))
        if not schema:
            raise RuntimeError("Audit provenance index schema is unavailable.")
        with op.get_context().autocommit_block():
            state = _postgres_state(bind)
            if state is not None:
                if state["indisvalid"] and state["indisready"]:
                    return
                op.drop_index(_NAME, table_name=_TABLE, schema=schema, postgresql_concurrently=True)
            op.create_index(
                _NAME,
                _TABLE,
                _COLUMNS,
                schema=schema,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
            state = _postgres_state(bind)
            if state is None or not state["indisvalid"] or not state["indisready"]:
                raise RuntimeError("Audit provenance index is not ready.")
    elif bind.dialect.name == "sqlite":
        if not _sqlite_exists(bind):
            op.create_index(_NAME, _TABLE, _COLUMNS, schema="main")
        if not _sqlite_exists(bind):
            raise RuntimeError("Audit provenance index is not ready.")
    else:
        raise RuntimeError("Unsupported audit provenance index dialect.")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        state = _postgres_state(bind)
        if state is not None:
            # Keep rollback available if a later historical downgrade refuses.
            op.drop_index(_NAME, table_name=_TABLE, schema=state["schema"])
    elif bind.dialect.name == "sqlite":
        if op.get_context().opts.get("destination_rev") != down_revision:
            raise RuntimeError("SQLite index downgrade requires the exact immediate parent.")
        if _sqlite_exists(bind):
            op.drop_index(_NAME, table_name=_TABLE, schema="main")
    else:
        raise RuntimeError("Unsupported audit provenance index dialect.")
