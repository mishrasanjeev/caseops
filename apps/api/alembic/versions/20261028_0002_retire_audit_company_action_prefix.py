"""Retire only the redundant audit prefix after validating its full replacement.

Revision ID: 20261028_0002
Revises: 20261028_0001
DATA-GOVERNANCE-MAP: unchanged. No row, ACL, provenance or table-content change.
MIGRATION-LOCK-RISK: acknowledged. PostgreSQL retirement is concurrent under
the existing migration budgets. Downgrade restores the prefix with an ordinary
transactional CREATE; its bounded ShareLock can wait for a concurrent writer.
MIGRATION-ROLLBACK: safe. Restore the exact immediate-parent index catalogue;
retain the full index for the parent's later transactional downgrade. SQLite
refuses non-parent/unknown downgrade destinations before any DDL.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261028_0002"
down_revision = "20261028_0001"
branch_labels = None
depends_on = None

_TABLE = "audit_events"
_LEGACY = "ix_audit_events_company_action"
_FULL = "ix_audit_events_source_provenance"
_PREFIX = ["company_id", "action"]
_COLUMNS = [*_PREFIX, "target_type", "target_id", "ip_docket_id"]
_INDEX_STATE = sa.text("""
    SELECT c.relkind, t.relkind AS table_kind, t.relname AS owner,
           tn.nspname AS owner_schema, n.nspname AS schema,
           c.relowner = t.relowner AS same_role_owner,
           am.amname AS method, i.indisvalid, i.indisready, i.indislive,
           i.indisunique, i.indisprimary, i.indisexclusion,
           NOT EXISTS (SELECT 1 FROM pg_constraint con WHERE con.conindid = c.oid)
               AS no_constraint,
           i.indpred IS NULL AND i.indexprs IS NULL AS plain,
           i.indnkeyatts = i.indnatts AS no_includes,
           i.indnkeyatts AS key_count,
           ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(attnum, pos)
                 JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                 ORDER BY k.pos) AS columns,
           (SELECT bool_and(opc.opcdefault AND opc.opcnamespace = 'pg_catalog'::regnamespace
                            AND i.indcollation[k] = a.attcollation AND i.indoption[k] = 0)
            FROM generate_series(0, i.indnkeyatts - 1) k
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[k]
            JOIN pg_opclass opc ON opc.oid = i.indclass[k]) AS standard_keys
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_index i ON i.indexrelid = c.oid
    LEFT JOIN pg_class t ON t.oid = i.indrelid
    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
    LEFT JOIN pg_am am ON am.oid = c.relam
    WHERE n.nspname = current_schema() AND c.relname = :name
""")


def _postgres_state(bind, name, columns):
    state = bind.execute(_INDEX_STATE, {"name": name}).mappings().first()
    if state is not None and not (
        state["relkind"] == "i"
        and state["table_kind"] == "r"
        and state["owner"] == _TABLE
        and state["owner_schema"] == state["schema"]
        and state["same_role_owner"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["indisprimary"] is False
        and state["indisexclusion"] is False
        and state["no_constraint"]
        and state["plain"]
        and state["no_includes"]
        and state["key_count"] == len(columns)
        and state["standard_keys"]
        and list(state["columns"]) == columns
    ):
        raise RuntimeError(f"Audit index has a conflicting shape: {name}")
    return state


def _healthy(state):
    return state is not None and state["indisvalid"] and state["indisready"] and state["indislive"]


def _sqlite_exists(bind, name, columns):
    state = bind.execute(
        sa.text("SELECT type, tbl_name FROM main.sqlite_master WHERE name = :name"),
        {"name": name},
    ).mappings().first()
    if state is None:
        return False
    if state["type"] != "index" or state["tbl_name"] != _TABLE:
        raise RuntimeError(f"Audit index has a conflicting shape: {name}")
    indexes = bind.exec_driver_sql(f'PRAGMA main.index_list("{_TABLE}")').mappings().all()
    index = next(row for row in indexes if row["name"] == name)
    keys = [row for row in bind.exec_driver_sql(f'PRAGMA main.index_xinfo("{name}")').mappings()
            if row["key"]]
    if not (
        not index["unique"]
        and not index["partial"]
        and index["origin"] == "c"
        and [row["name"] for row in keys] == columns
        and all(row["cid"] >= 0 and row["desc"] == 0 and row["coll"] == "BINARY" for row in keys)
    ):
        raise RuntimeError(f"Audit index has a conflicting shape: {name}")
    return True


def _require_full(bind):
    if bind.dialect.name == "postgresql":
        state = _postgres_state(bind, _FULL, _COLUMNS)
        if not _healthy(state):
            raise RuntimeError("Full audit provenance index is missing or unready.")
        return state
    if not _sqlite_exists(bind, _FULL, _COLUMNS):
        raise RuntimeError("Full audit provenance index is missing or unready.")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        _require_full(bind)
        if _postgres_state(bind, _LEGACY, _PREFIX) is None:
            return
        with op.get_context().autocommit_block():
            full = _require_full(bind)
            legacy = _postgres_state(bind, _LEGACY, _PREFIX)
            if legacy is not None:
                # An interrupted concurrent DROP may leave this exact prefix invalid.
                op.drop_index(
                    _LEGACY, table_name=_TABLE, schema=full["schema"],
                    postgresql_concurrently=True,
                )
            _require_full(bind)
            if _postgres_state(bind, _LEGACY, _PREFIX) is not None:
                raise RuntimeError("Legacy audit prefix retirement is incomplete.")
    elif bind.dialect.name == "sqlite":
        _require_full(bind)
        if _sqlite_exists(bind, _LEGACY, _PREFIX):
            op.drop_index(_LEGACY, table_name=_TABLE, schema="main")
        _require_full(bind)
        if _sqlite_exists(bind, _LEGACY, _PREFIX):
            raise RuntimeError("Legacy audit prefix retirement is incomplete.")
    else:
        raise RuntimeError("Unsupported audit prefix retirement dialect.")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        full = _require_full(bind)
        legacy = _postgres_state(bind, _LEGACY, _PREFIX)
        if legacy is None:
            # No autocommit: a later parent DROP refusal must roll this CREATE back.
            op.create_index(_LEGACY, _TABLE, _PREFIX, schema=full["schema"])
            legacy = _postgres_state(bind, _LEGACY, _PREFIX)
        if not _healthy(legacy):
            raise RuntimeError("Restored legacy audit prefix is unready.")
        _require_full(bind)
    elif bind.dialect.name == "sqlite":
        if op.get_context().opts.get("destination_rev") != down_revision:
            raise RuntimeError("SQLite index downgrade requires the exact immediate parent.")
        _require_full(bind)
        if not _sqlite_exists(bind, _LEGACY, _PREFIX):
            op.create_index(_LEGACY, _TABLE, _PREFIX, schema="main")
        if not _sqlite_exists(bind, _LEGACY, _PREFIX):
            raise RuntimeError("Restored legacy audit prefix is unready.")
        _require_full(bind)
    else:
        raise RuntimeError("Unsupported audit prefix retirement dialect.")
