"""IPLF-080B/UJ-29/NFT-005/J14-M14: exact structured-key/index-health contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import Text, create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.schema import CreateIndex
from sqlalchemy.sql.elements import Cast

from caseops_api.db.models import IpPatentApplicationVersion, IpPatentFamilyVersion
from caseops_api.db.version_identity import (
    VERSION_IDENTITY_INDEX_STATE,
    VERSION_IDENTITY_INDEXES,
    version_identity_index_issues,
    version_identity_index_shape_matches,
    version_identity_key,
)
from caseops_api.scripts import check_database_indexes


def _state(name):
    table, parent = VERSION_IDENTITY_INDEXES[name]
    return {
        "index_name": name, "index_kind": "i", "owner": table,
        "owner_schema": "public", "schema": "public", "method": "btree",
        "indisunique": False, "indisprimary": False, "indisexclusion": False,
        "predicate_free": True, "one_expression": True,
        "standard_key": True, "indisvalid": True, "indisready": True, "indislive": True,
        "expression": f"ARRAY[(company_id)::text, ({parent})::text, (version)::text]",
    }


@pytest.mark.parametrize("name", VERSION_IDENTITY_INDEXES)
@pytest.mark.parametrize("formatting", [
    "canonical", "bare", "outer", "spacing", "cast_parentheses",
])
def test_version_identity_health_accepts_only_equivalent_cast_formatting(name, formatting):
    state = _state(name)
    if formatting == "bare":
        parent = VERSION_IDENTITY_INDEXES[name][1]
        state["expression"] = f"ARRAY[company_id::text,{parent}::text,version::text]"
    elif formatting == "outer":
        state["expression"] = "(" + state["expression"] + ")"
    elif formatting == "spacing":
        state["expression"] = state["expression"].replace(",", ",\n  ")
    elif formatting == "cast_parentheses":
        parent = VERSION_IDENTITY_INDEXES[name][1]
        state["expression"] = f"(ARRAY[((company_id)::text),(({parent})::text),((version)::text)])"
    assert version_identity_index_shape_matches(state, name=name)


@pytest.mark.parametrize("name", VERSION_IDENTITY_INDEXES)
@pytest.mark.parametrize("change", [
    {"index_name": "other_index"}, {"index_kind": "r"},
    {"owner": "other_versions"}, {"owner_schema": "other"},
    {"method": "hash"}, {"indisunique": True}, {"indisprimary": True},
    {"indisexclusion": True}, {"predicate_free": False},
    {"predicate_free": "true"}, {"one_expression": False}, {"standard_key": False},
    {"expression": None},
    {"expression": "ARRAY[company_id::text,version::text]"},
    {"expression": "ARRAY[company_id::text,family_id::text,version::text,version::text]"},
    {"expression": "ARRAY[company_id::text,version::text,family_id::text]"},
    {"expression": "ARRAY[company_id::text,(family_id || '')::text,version::text]"},
    {"expression": "ARRAY[company_id::text,lower(family_id)::text,version::text]"},
])
def test_version_identity_health_refuses_foreign_or_changed_index_shapes(name, change):
    if isinstance(change.get("expression"), str):
        change = {**change, "expression": change["expression"].replace(
            "family_id", VERSION_IDENTITY_INDEXES[name][1]
        )}
    assert not version_identity_index_shape_matches({**_state(name), **change}, name=name)


@pytest.mark.parametrize("model,parent", [
    (IpPatentFamilyVersion, "family_id"), (IpPatentApplicationVersion, "application_id"),
])
def test_metadata_and_lookup_share_one_typed_structured_identity(model, parent):
    table = model.__table__
    expression = version_identity_key(table.c.company_id, table.c[parent], table.c.version)
    assert isinstance(expression, array) and len(expression.clauses) == 3
    assert all(isinstance(item, Cast) and isinstance(item.type, Text)
               for item in expression.clauses)
    assert all(actual.clause.compare(expected) for actual, expected in zip(
        expression.clauses, (table.c.company_id, table.c[parent], table.c.version), strict=True
    ))
    name, = [name for name, (owner, _parent) in VERSION_IDENTITY_INDEXES.items()
             if owner == table.name]
    assert VERSION_IDENTITY_INDEXES[name] == (table.name, parent)
    index, = [index for index in table.indexes if index.name == name]
    assert not index.unique and index.info["caseops_postgresql_only"] is True
    assert index.expressions[0].compare(expression)
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
    assert "USING" not in ddl or "USING btree" in ddl
    assert "ARRAY[" in ddl and "CREATE INDEX" in ddl and "UNIQUE" not in ddl
    assert check_database_indexes._declared_indexes()[table.name][name].postgresql_only


@pytest.mark.parametrize("model", [IpPatentFamilyVersion, IpPatentApplicationVersion])
def test_sqlite_table_creation_omits_only_postgres_identity_indexes(model):
    engine = create_engine("sqlite://")
    try:
        model.__table__.create(engine)
        names = {row["name"] for row in inspect(engine).get_indexes(model.__tablename__)}
        assert names, "Normal SQLite support indexes must still be created."
        assert not names.intersection(VERSION_IDENTITY_INDEXES)
    finally:
        engine.dispose()


@pytest.mark.parametrize("key,problem", [
    ("indisvalid", "version_identity_index_not_ready"),
    ("indisready", "version_identity_index_not_ready"),
    ("indislive", "version_identity_index_not_ready"),
    ("expression", "version_identity_index_shape"),
])
def test_version_identity_health_refuses_bad_indexes_without_hiding_other_names(key, problem):
    seen = []
    names = list(VERSION_IDENTITY_INDEXES)

    def execute(statement, parameters):
        assert statement is VERSION_IDENTITY_INDEX_STATE
        name = parameters["name"]
        seen.append(name)
        state = _state(name)
        if name == names[0]:
            state[key] = "ARRAY[]::text[]" if key == "expression" else False
        return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: state))

    connection = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=execute)
    assert version_identity_index_issues(connection) == [{
        "table_name": VERSION_IDENTITY_INDEXES[names[0]][0], "index_name": names[0],
        "problem": problem,
    }]
    assert seen == names


def test_sqlite_health_never_executes_a_postgres_catalog_probe():
    def execute(*_args, **_kwargs):
        pytest.fail("SQLite must not execute PostgreSQL catalog SQL.")

    connection = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"), execute=execute)
    assert version_identity_index_issues(connection) == []


def test_sqlite_health_honors_postgres_only_metadata_without_weakening_normal_indexes(monkeypatch):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            IpPatentFamilyVersion.__table__.create(connection)
            IpPatentApplicationVersion.__table__.create(connection)
            connection.exec_driver_sql("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
            connection.execute(text("INSERT INTO alembic_version VALUES (:version)"),
                               {"version": "identity-test"})
            monkeypatch.setattr(check_database_indexes, "_required_schema_revision",
                                lambda: "identity-test")
            report = check_database_indexes.build_index_health_report(connection)
            assert report["status"] == "ok", report
            assert report["missing_declared_indexes"] == report["mismatched_declared_indexes"] == []
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_postgres_health_rejects_missing_and_same_name_wrong_identity_indexes(migration_pg_engine):
    with migration_pg_engine.connect() as connection:
        baseline = check_database_indexes.build_index_health_report(connection)
        assert baseline["status"] == "ok", baseline
        quote = connection.dialect.identifier_preparer.quote
        for name, (table, _parent) in VERSION_IDENTITY_INDEXES.items():
            for wrong_shape in (False, True):
                boundary = connection.begin_nested()
                try:
                    # These identifiers come only from the fixed, code-owned registry.
                    connection.exec_driver_sql(f"DROP INDEX {quote(name)}")
                    if wrong_shape:
                        connection.exec_driver_sql(
                            f"CREATE INDEX {quote(name)} ON {quote(table)} (company_id)"
                        )
                    report = check_database_indexes.build_index_health_report(connection)
                    assert report["status"] == "failed"
                    if wrong_shape:
                        assert {"table_name": table, "index_name": name,
                                "problem": "version_identity_index_shape"} in report[
                                    "mismatched_declared_indexes"
                                ]
                    else:
                        assert {"table_name": table, "index_name": name} in report[
                            "missing_declared_indexes"
                        ]
                finally:
                    boundary.rollback()
                restored = check_database_indexes.build_index_health_report(connection)
                assert restored["status"] == "ok", restored
