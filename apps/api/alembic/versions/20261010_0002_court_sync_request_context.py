"""Retain court queue provider isolation across independent execution.

Revision ID: 20261010_0002
Revises: 20261010_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL: removing
the durable provider-isolation marker would discard unknown legacy policy.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261010_0002"
down_revision = "20261010_0001"
branch_labels = None
depends_on = None

_TABLE = "matter_court_sync_jobs"
_INDEXES = (
    ("ix_matter_court_sync_jobs_queue", ["status", "queued_at", "updated_at", "id"]),
    ("ix_matter_court_sync_jobs_recovery", ["status", "started_at", "id"]),
)
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


def _require_index_shape(state, name: str, columns: list[str]) -> None:
    if not (
        state["relkind"] == "i"
        and state["owner"] == _TABLE
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["plain"]
        and state["no_includes"]
        and state["standard_keys"]
        and list(state["columns"]) == columns
    ):
        raise RuntimeError(f"Existing court queue index has a conflicting shape: {name}")


def _indexes(bind) -> None:
    for name, columns in _INDEXES:
        if bind.dialect.name == "postgresql":
            state = bind.execute(_INDEX_STATE, {"name": name}).mappings().first()
            if state is not None:
                _require_index_shape(state, name, columns)
                if not state["indisvalid"] or not state["indisready"]:
                    op.drop_index(name, table_name=_TABLE, postgresql_concurrently=True)
        else:
            state = next(
                (row for row in sa.inspect(bind).get_indexes(_TABLE) if row["name"] == name),
                None,
            )
            if state is not None and (
                state["column_names"] != columns
                or state["unique"]
                or (state.get("dialect_options") or {}).get("sqlite_where") is not None
            ):
                raise RuntimeError(f"Existing court queue index has a conflicting shape: {name}")
        op.create_index(
            name,
            _TABLE,
            columns,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        if bind.dialect.name == "postgresql":
            state = bind.execute(_INDEX_STATE, {"name": name}).mappings().one()
            _require_index_shape(state, name, columns)
            if not state["indisvalid"] or not state["indisready"]:
                raise RuntimeError(f"Court queue index is not ready: {name}")


def upgrade() -> None:
    bind = op.get_bind()
    existing = next(
        (
            column
            for column in sa.inspect(bind).get_columns(_TABLE)
            if column["name"] == "no_paid_providers"
        ),
        None,
    )
    # A concurrent build commits the column first. Restart without rewriting
    # captured human FALSE or automated/unknown TRUE receipts.
    if existing is None:
        op.add_column(
            _TABLE,
            sa.Column("no_paid_providers", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    elif not (
        isinstance(existing["type"], sa.Boolean)
        and not existing["nullable"]
        and str(existing["default"]).strip().lower()
        == ("true" if bind.dialect.name == "postgresql" else "1")
        and not existing.get("computed")
    ):
        raise RuntimeError("Existing court no-paid marker has a conflicting shape.")
    # env.py supplies dedicated migration budgets. Release the column lock
    # before scans; do not assume a small production table.
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            _indexes(bind)
    else:
        _indexes(bind)


def downgrade() -> None:
    raise RuntimeError(
        "Court provider-isolation receipts must be retained; restore-forward required."
    )
