"""Index private projections that still hold a label, text or an embedding.

Each rebuild retires the previous private generation and keeps its rows. Those
rows used to keep every chunk's text and embedding forever, including text of
sources deleted afterwards (B4-ADJ-40). Retirement now blanks that payload, and
the bounded purge and the release integrity scan look for retired rows that
still hold it, and for tombstones that still hold a label. This partial index
holds only rows with a payload: after the purge, the active generation's live
rows. Both reads then seek the tenant's tombstones and retired generations in
the index instead of reading every retained row.

Revision ID: 20261106_0002
Revises: 20261106_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. PostgreSQL builds one nonunique partial index
concurrently; an interrupted build of the same shape is dropped and rebuilt, and
a conflicting name or predicate refuses before any DDL. No row is changed here:
the payload purge runs in bounded, separately committed maintenance batches.
MIGRATION-ROLLBACK: safe. Downgrade removes only this support index; no column,
row, generation, tombstone or audit record changes, and blanked retired payloads
are derived index copies that are not restored. SQLite requires the exact
immediate parent, with the shape checked before DROP.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261106_0002"
down_revision = "20261106_0001"
branch_labels = None
depends_on = None

TABLE = "private_index_projections"
NAME = "ix_private_projection_retained_payload"
COLUMNS = ["company_id", "is_tombstoned", "generation_id"]
PREDICATE = "content_text <> '' OR embedding_json IS NOT NULL OR label <> ''"
# pg_get_expr renders the stored predicate in this canonical form.
POSTGRES_PREDICATE = (
    "((content_text <> ''::text) OR (embedding_json IS NOT NULL) "
    "OR ((label)::text <> ''::text))"
)


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


def _postgres_state(bind):
    state = bind.execute(_INDEX_STATE, {"name": NAME}).mappings().first()
    if state is not None and not (
        state["relkind"] == "i"
        and state["owner"] == TABLE
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["expression_free"]
        and state["predicate"] == POSTGRES_PREDICATE
        and state["no_includes"]
        and state["standard_keys"]
        and list(state["columns"]) == COLUMNS
    ):
        raise RuntimeError("Private projection retained-payload index has a conflicting shape.")
    return state


def _sqlite_exists(bind):
    state = (
        bind.execute(
            sa.text("SELECT type, tbl_name, sql FROM main.sqlite_master WHERE name = :name"),
            {"name": NAME},
        )
        .mappings()
        .first()
    )
    if state is None:
        return False
    if state["type"] != "index" or state["tbl_name"] != TABLE:
        raise RuntimeError("Private projection retained-payload index has a conflicting shape.")
    indexes = bind.exec_driver_sql(f'PRAGMA main.index_list("{TABLE}")').mappings().all()
    index = next(row for row in indexes if row["name"] == NAME)
    keys = [
        row
        for row in bind.exec_driver_sql(f'PRAGMA main.index_xinfo("{NAME}")').mappings()
        if row["key"]
    ]
    predicate = state["sql"].rsplit(" WHERE ", 1)[-1] if " WHERE " in state["sql"] else None
    if not (
        not index["unique"]
        and bool(index["partial"])
        and index["origin"] == "c"
        and [row["name"] for row in keys] == COLUMNS
        and all(row["cid"] >= 0 and row["desc"] == 0 and row["coll"] == "BINARY" for row in keys)
        and predicate == PREDICATE
    ):
        raise RuntimeError("Private projection retained-payload index has a conflicting shape.")
    return True


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        schema = bind.scalar(sa.text("SELECT current_schema()"))
        if not schema:
            raise RuntimeError("Private projection retained-payload index schema is unavailable.")
        with op.get_context().autocommit_block():
            state = _postgres_state(bind)
            if state is not None and not (state["indisvalid"] and state["indisready"]):
                op.drop_index(NAME, table_name=TABLE, schema=schema, postgresql_concurrently=True)
                state = None
            if state is None:
                op.create_index(
                    NAME,
                    TABLE,
                    COLUMNS,
                    schema=schema,
                    postgresql_concurrently=True,
                    if_not_exists=True,
                    postgresql_where=sa.text(PREDICATE),
                )
            state = _postgres_state(bind)
            if state is None or not state["indisvalid"] or not state["indisready"]:
                raise RuntimeError("Private projection retained-payload index is not ready.")
    elif bind.dialect.name == "sqlite":
        if not _sqlite_exists(bind):
            op.create_index(NAME, TABLE, COLUMNS, schema="main", sqlite_where=sa.text(PREDICATE))
        if not _sqlite_exists(bind):
            raise RuntimeError("Private projection retained-payload index is not ready.")
    else:
        raise RuntimeError("Unsupported private projection retained-payload index dialect.")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        state = _postgres_state(bind)
        if state is not None:
            op.drop_index(NAME, table_name=TABLE, schema=state["schema"])
    elif bind.dialect.name == "sqlite":
        if op.get_context().opts.get("destination_rev") != down_revision:
            raise RuntimeError(
                "SQLite retained-payload index downgrade requires exact immediate parent."
            )
        if _sqlite_exists(bind):
            op.drop_index(NAME, table_name=TABLE, schema="main")
    else:
        raise RuntimeError("Unsupported private projection retained-payload index dialect.")
