"""Fence durable portfolio deliveries without adopting legacy executors.

Revision ID: 20261026_0001
Revises: 20261022_0001
DATA-GOVERNANCE-MAP: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml.
Dispatch state, ownership identifiers and expiry retain the existing tenant
profile. No new retention, provider transmission or disposition is authorized.
MIGRATION-LOCK-RISK: acknowledged. Additive metadata uses env.py's lock/SQL
budgets; PostgreSQL queue indexes build concurrently and recover failed builds.
MIGRATION-ROLLBACK: restore-forward. Never discard dispatch/ownership receipts.
Legacy rows and old inserts remain protocol zero; no running job is adopted.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261026_0001"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None

_TABLE = "ip_portfolio_export_jobs"
_CHECK = "ck_ip_portfolio_export_dispatch_protocol"
_CLAIM_CHECK = "ck_ip_portfolio_export_claim_state"
_CLAIM_SQL = (
    "dispatch_protocol_version = 0 OR "
    "(status = 'running' AND worker_claim_token IS NOT NULL "
    "AND worker_claim_expires_at IS NOT NULL) OR "
    "(status <> 'running' AND worker_claim_token IS NULL "
    "AND worker_claim_expires_at IS NULL)"
)
_INDEXES = (
    (
        "ix_ip_portfolio_exports_requester_status",
        ["company_id", "requested_by_membership_id", "status", "id"],
    ),
    ("ix_ip_portfolio_exports_queue", ["dispatch_protocol_version", "status", "created_at", "id"]),
    (
        "ix_ip_portfolio_exports_recovery",
        ["dispatch_protocol_version", "status", "worker_claim_expires_at", "created_at", "id"],
    ),
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


def _require_index_shape(state, name, columns):
    if not (
        state["relkind"] == "i" and state["owner"] == _TABLE
        and state["owner_schema"] == state["schema"] and state["method"] == "btree"
        and state["indisunique"] is False and state["plain"] and state["no_includes"]
        and state["standard_keys"] and list(state["columns"]) == columns
    ):
        raise RuntimeError(f"Portfolio export queue index has a conflicting shape: {name}")


def _indexes(bind):
    for name, columns in _INDEXES:
        if bind.dialect.name == "postgresql":
            state = bind.execute(_INDEX_STATE, {"name": name}).mappings().first()
            if state is not None:
                _require_index_shape(state, name, columns)
                if not state["indisvalid"] or not state["indisready"]:
                    op.drop_index(name, table_name=_TABLE, postgresql_concurrently=True)
        else:
            state = next(
                (row for row in sa.inspect(bind).get_indexes(_TABLE) if row["name"] == name), None
            )
            if state is not None and (
                state["column_names"] != columns or state["unique"]
                or (state.get("dialect_options") or {}).get("sqlite_where") is not None
            ):
                raise RuntimeError(f"Portfolio export queue index has a conflicting shape: {name}")
        op.create_index(
            name, _TABLE, columns, postgresql_concurrently=True, if_not_exists=True
        )
        if bind.dialect.name == "postgresql":
            state = bind.execute(_INDEX_STATE, {"name": name}).mappings().one()
            _require_index_shape(state, name, columns)
            if not state["indisvalid"] or not state["indisready"]:
                raise RuntimeError(f"Portfolio export queue index is not ready: {name}")


def upgrade():
    bind = op.get_bind()
    existing = {column["name"]: column for column in sa.inspect(bind).get_columns(_TABLE)}
    additions = (
        sa.Column("dispatch_protocol_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_claim_token", sa.String(length=36), nullable=True),
        sa.Column("worker_claim_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    # A concurrent-index failure has already committed these columns. Reuse
    # them without changing a legacy row or resetting a populated claim.
    for column in additions:
        current = existing.get(column.name)
        if current is None:
            op.add_column(_TABLE, column)
            continue
        correct_type = (
            isinstance(current["type"], sa.Integer) if column.name == "dispatch_protocol_version"
            else isinstance(current["type"], sa.String) and current["type"].length == 36
            if column.name == "worker_claim_token"
            else isinstance(current["type"], sa.DateTime)
            and (bind.dialect.name != "postgresql" or current["type"].timezone)
        )
        correct_default = (
            str(current["default"]).strip("'() ") == "0"
            if column.name == "dispatch_protocol_version" else current["default"] is None
        )
        if not (
            correct_type and correct_default and current["nullable"] == column.nullable
            and not current.get("computed")
        ):
            raise RuntimeError(
                f"Portfolio export worker column has a conflicting shape: {column.name}"
            )
    checks = {item["name"]: item for item in sa.inspect(bind).get_check_constraints(_TABLE)}
    if _CHECK not in checks:
        with op.batch_alter_table(_TABLE) as batch:
            batch.create_check_constraint(_CHECK, "dispatch_protocol_version IN (0, 1)")
    else:
        expression = "".join(checks[_CHECK]["sqltext"].split()).replace("(", "").replace(")", "")
        if expression not in {
            "dispatch_protocol_versionIN0,1", "dispatch_protocol_version=ANYARRAY[0,1]",
        }:
            raise RuntimeError("Portfolio export dispatch constraint has a conflicting shape.")
    if _CLAIM_CHECK not in checks:
        with op.batch_alter_table(_TABLE) as batch:
            batch.create_check_constraint(_CLAIM_CHECK, _CLAIM_SQL)
    else:
        def normalized(expression):
            return "".join(expression.lower().split()).replace(
                "::text", ""
            ).replace("(", "").replace(")", "")

        if normalized(checks[_CLAIM_CHECK]["sqltext"]) != normalized(_CLAIM_SQL):
            raise RuntimeError("Portfolio export claim constraint has a conflicting shape.")
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            _indexes(bind)
    else:
        _indexes(bind)


def downgrade():
    raise RuntimeError("Portfolio export dispatch and claim receipts require restore-forward.")
