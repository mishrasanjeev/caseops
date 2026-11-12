"""Exact structured identity indexes for patent disclosure/application versions.

Revision ID: 20261112_0001
Revises: 20261108_0003
DATA-GOVERNANCE-MAP: updated; patent tenant/source/history ownership unchanged.
MIGRATION-LOCK-RISK: acknowledged. PostgreSQL builds two nonunique expression
indexes concurrently under the migration connection's dedicated timeouts. Both
names are shape-checked before DDL. Interrupted same-shape indexes are dropped
concurrently and rebuilt; this is not an atomic two-index transaction.
MIGRATION-ROLLBACK: safe for retained data. Downgrade concurrently drops only
these shape-checked support indexes; query performance can regress until the
previous application release is restored. No column, row or constraint changes.
SQLite is a no-op in both directions. Other dialects are refused.
IPLF-080B/UJ-29, NFT-005/J14-M14. Execution/registry evidence is release-owned.
"""

import re

import sqlalchemy as sa

from alembic import op

revision = "20261112_0001"
down_revision = "20261108_0003"
branch_labels = None
depends_on = None

# Historical SQL must not import a moving runtime expression builder.
INDEXES = (
    (
        "ip_patent_family_versions", "ix_patent_family_versions_identity_key", "family_id",
        "ARRAY[CAST(company_id AS TEXT), CAST(family_id AS TEXT), CAST(version AS TEXT)]",
    ),
    (
        "ip_patent_application_versions", "ix_patent_application_versions_identity_key",
        "application_id",
        "ARRAY[CAST(company_id AS TEXT), CAST(application_id AS TEXT), CAST(version AS TEXT)]",
    ),
)

_INDEX_STATE = sa.text("""
    SELECT c.oid, c.relkind, t.relname AS owner, tn.nspname AS owner_schema,
           am.amname AS method, i.indisvalid, i.indisready, i.indislive,
           i.indisunique, i.indisprimary, i.indisexclusion,
           i.indnkeyatts, i.indnatts, i.indkey[0] AS attribute,
           pg_get_expr(i.indexprs, i.indrelid) AS expression,
           pg_get_expr(i.indpred, i.indrelid) AS predicate,
           opc.opcname, onsp.nspname AS opclass_schema, opc.opcdefault,
           opc.opcintype = 'pg_catalog.anyarray'::regtype AS array_input,
           opc.opcmethod = am.oid AS matching_method,
           i.indcollation[0] = (SELECT typcollation FROM pg_type
                               WHERE oid = 'text[]'::regtype) AS default_collation,
           i.indoption[0] AS options, current_schema() AS schema
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_index i ON i.indexrelid = c.oid
    LEFT JOIN pg_class t ON t.oid = i.indrelid
    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
    LEFT JOIN pg_am am ON am.oid = c.relam
    LEFT JOIN pg_opclass opc ON opc.oid = i.indclass[0]
    LEFT JOIN pg_namespace onsp ON onsp.oid = opc.opcnamespace
    WHERE n.nspname = current_schema() AND c.relname = :name
""")


def _expression_matches(expression, parent):
    if not isinstance(expression, str) or parent not in {"family_id", "application_id"}:
        return False

    def element(column):
        name = re.escape(column)
        cast = rf"(?:{name}|\(\s*{name}\s*\))\s*::\s*text"
        return rf"(?:{cast}|\(\s*{cast}\s*\))"

    body = r"ARRAY\[\s*" + r"\s*,\s*".join(
        element(column) for column in ("company_id", parent, "version")
    ) + r"\s*\]"
    return re.fullmatch(rf"\s*(?:{body}|\(\s*{body}\s*\))\s*", expression) is not None


def _postgres_state(bind, table, name, parent):
    state = bind.execute(_INDEX_STATE, {"name": name}).mappings().first()
    if state is not None and not (
        state["relkind"] == "i"
        and state["owner"] == table
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["indisprimary"] is False
        and state["indisexclusion"] is False
        and state["indnkeyatts"] == state["indnatts"] == 1
        and state["attribute"] == 0
        and state["predicate"] is None
        and state["opcname"] == "array_ops"
        and state["opclass_schema"] == "pg_catalog"
        and state["opcdefault"] is True
        and state["array_input"] is True
        and state["matching_method"] is True
        and state["default_collation"] is True
        and state["options"] == 0
        and _expression_matches(state["expression"], parent)
    ):
        raise RuntimeError(f"Patent version identity index {name} has a conflicting shape.")
    return state


def _ready(state):
    return state is not None and all(
        state[key] is True for key in ("indisvalid", "indisready", "indislive")
    )


def _change(*, remove):
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Unsupported patent version identity index dialect.")
    schema = bind.scalar(sa.text("SELECT current_schema()"))
    if not schema:
        raise RuntimeError("Patent version identity index schema is unavailable.")
    with op.get_context().autocommit_block():
        # Preflight both names so a conflicting second name cannot leave the first changed.
        for table, name, parent, _expression in INDEXES:
            _postgres_state(bind, table, name, parent)
        for table, name, parent, expression in INDEXES:
            state = _postgres_state(bind, table, name, parent)
            if state is not None and (remove or not _ready(state)):
                op.drop_index(name, table_name=table, schema=schema, postgresql_concurrently=True)
                state = None
            if remove:
                if _postgres_state(bind, table, name, parent) is not None:
                    raise RuntimeError(f"Patent version identity index {name} was not removed.")
                continue
            if state is None:
                op.create_index(
                    name, table, [sa.text(f"({expression})")], schema=schema, unique=False,
                    postgresql_using="btree", postgresql_concurrently=True, if_not_exists=True,
                )
            if not _ready(_postgres_state(bind, table, name, parent)):
                raise RuntimeError(f"Patent version identity index {name} is not ready.")


def upgrade() -> None:
    _change(remove=False)


def downgrade() -> None:
    _change(remove=True)
