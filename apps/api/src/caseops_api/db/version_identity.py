"""One structured key for exact PostgreSQL immutable-version lookups."""

from __future__ import annotations

import re

from sqlalchemy import Text, cast, text
from sqlalchemy.dialects.postgresql import array

VERSION_IDENTITY_INDEXES = {
    "ix_patent_family_versions_identity_key": ("ip_patent_family_versions", "family_id"),
    "ix_patent_application_versions_identity_key": (
        "ip_patent_application_versions", "application_id"
    ),
}


def version_identity_key(company_id, parent_id, version):
    # A structured value preserves all three fields without delimiter or hash collisions.
    return array([cast(value, Text) for value in (company_id, parent_id, version)], type_=Text)


VERSION_IDENTITY_INDEX_STATE = text("""
    SELECT c.relname AS index_name, c.relkind AS index_kind,
           t.relname AS owner, tn.nspname AS owner_schema,
           am.amname AS method, i.indisunique, i.indisprimary, i.indisexclusion,
           i.indisvalid, i.indisready, i.indislive,
           pg_get_expr(i.indexprs, i.indrelid) AS expression,
           i.indpred IS NULL AS predicate_free,
           i.indnkeyatts = 1 AND i.indnatts = 1 AND i.indkey[0] = 0 AS one_expression,
           opc.opcdefault AND opc.opcname = 'array_ops'
             AND opn.nspname = 'pg_catalog' AND opc.opcintype = 'anyarray'::regtype
             AND opc.opcmethod = am.oid
             AND i.indoption[0] = 0
             AND i.indcollation[0] = (
                 SELECT typcollation FROM pg_type WHERE oid = 'text[]'::regtype
             ) AS standard_key,
           current_schema() AS schema
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    LEFT JOIN pg_index i ON i.indexrelid = c.oid
    LEFT JOIN pg_class t ON t.oid = i.indrelid
    LEFT JOIN pg_namespace tn ON tn.oid = t.relnamespace
    LEFT JOIN pg_am am ON am.oid = c.relam
    LEFT JOIN pg_opclass opc ON opc.oid = i.indclass[0]
    LEFT JOIN pg_namespace opn ON opn.oid = opc.opcnamespace
    WHERE n.nspname = current_schema() AND c.relname = :name
""")


def version_identity_index_shape_matches(state, *, name: str) -> bool:
    table, parent = VERSION_IDENTITY_INDEXES[name]
    expression = re.sub(r"\s+", "", state["expression"] or "")
    if expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1]
    casts = [rf"(?:{column}|\({column}\))::text" for column in ("company_id", parent, "version")]
    fields = [rf"(?:{item}|\({item}\))" for item in casts]
    return bool(
        state["index_name"] == name
        and state["index_kind"] == "i"
        and state["owner"] == table
        and state["owner_schema"] == state["schema"]
        and state["method"] == "btree"
        and state["indisunique"] is False
        and state["indisprimary"] is False
        and state["indisexclusion"] is False
        and state["predicate_free"] is True
        and state["one_expression"] is True
        and state["standard_key"] is True
        and re.fullmatch(r"ARRAY\[" + ",".join(fields) + r"\]", expression)
    )


def version_identity_index_issues(connection) -> list[dict[str, str]]:
    if connection.dialect.name != "postgresql":
        return []
    issues = []
    for name, (table, _parent) in VERSION_IDENTITY_INDEXES.items():
        state = connection.execute(VERSION_IDENTITY_INDEX_STATE, {"name": name}).mappings().first()
        # The ordinary declared-index check retains the missing-name finding.
        if state is not None and not version_identity_index_shape_matches(state, name=name):
            issues.append({"table_name": table, "index_name": name,
                           "problem": "version_identity_index_shape"})
        elif state is not None and any(state[key] is not True for key in (
            "indisvalid", "indisready", "indislive"
        )):
            issues.append({"table_name": table, "index_name": name,
                           "problem": "version_identity_index_not_ready"})
    return issues
