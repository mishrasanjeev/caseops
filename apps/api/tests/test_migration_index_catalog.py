"""Real DDL negative controls for a historical whole-catalog comparison."""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from tests.migration_index_catalog import (
    interrupted_index_catalog,
    require_index_additions,
    schema_catalog,
)


@pytest.mark.parametrize(
    "change",
    [
        "DROP INDEX retained_index",
        "DROP INDEX retained_index;CREATE INDEX retained_index ON retained (value)",
        "CREATE INDEX unrelated_index ON retained (value)",
        "ALTER TABLE retained ADD COLUMN unexpected TEXT",
        "CREATE TRIGGER unexpected AFTER INSERT ON retained BEGIN SELECT 1; END",
    ],
)
def test_catalog_rejects_unrelated_schema_damage_after_an_owned_index(change):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE retained (id INTEGER PRIMARY KEY,value TEXT)")
            connection.exec_driver_sql("CREATE INDEX retained_index ON retained (id,value)")
            connection.exec_driver_sql("INSERT INTO retained VALUES (1,'retained')")
        before = schema_catalog(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE INDEX owned_index ON retained (value,id)")
        expected = (("retained", "owned_index", ["value", "id"]),)
        require_index_additions(before, schema_catalog(engine), expected)
        # Keep effectful DDL outside the assertion, including negative controls.
        with engine.begin() as connection:
            statements = change.split(";CREATE")
            connection.exec_driver_sql(statements[0])
            if len(statements) == 2:
                connection.exec_driver_sql("CREATE" + statements[1])
        damaged = schema_catalog(engine)
        with pytest.raises(AssertionError, match="UNEXPECTED_SCHEMA|HISTORICAL_SCHEMA"):
            require_index_additions(before, damaged, expected)
    finally:
        engine.dispose()


_INTERRUPTED_KEY = ("index", "audit_events", "ix_audit_events_typed_source_proof_seek")
_INTERRUPTED_DEFINITION = (
    "CREATE INDEX ix_audit_events_typed_source_proof_seek ON public.audit_events "
    "USING btree (target_type, target_id, company_id, ip_docket_id, action, id)",
    False, False, True, False, False, False,
)
_HEALTHY_INDEX = (
    "audit_events", "retained_index",
    "CREATE INDEX retained_index ON public.audit_events USING btree (id)",
    True, True, True, False, False, False,
)


class _CatalogResult:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _CatalogConnection:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, statement):
        # A fixed catalog response control, with no database or transport.
        rows = self.rows if "FROM pg_index i JOIN pg_class c" in statement.text else []
        return _CatalogResult(rows)


class _CatalogEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, rows):
        self.rows = rows

    def connect(self):
        return _CatalogConnection(self.rows)


def test_interrupted_catalog_preserves_healthy_default_and_exact_full_snapshot():
    interrupted = ("audit_events", _INTERRUPTED_KEY[2], *_INTERRUPTED_DEFINITION)
    engine = _CatalogEngine([_HEALTHY_INDEX, interrupted])
    with pytest.raises(AssertionError, match="INVALID_OR_UNREADY_HISTORICAL_INDEX"):
        schema_catalog(engine)
    observed = interrupted_index_catalog(
        engine, expected_index=(_INTERRUPTED_KEY, _INTERRUPTED_DEFINITION),
    )
    assert observed == {
        ("index", "audit_events", "retained_index"): _HEALTHY_INDEX[2:],
        _INTERRUPTED_KEY: _INTERRUPTED_DEFINITION,
    }


@pytest.mark.parametrize(
    "change",
    [
        "wrong_name",
        "wrong_definition",
        "wrong_flags",
        "healthy_target",
        "missing",
        "extra_invalid",
        "descriptor_flags",
    ],
)
def test_interrupted_catalog_rejects_every_unreviewed_index_state(change):
    interrupted = ("audit_events", _INTERRUPTED_KEY[2], *_INTERRUPTED_DEFINITION)
    rows = [_HEALTHY_INDEX, interrupted]
    descriptor = (_INTERRUPTED_KEY, _INTERRUPTED_DEFINITION)
    if change == "wrong_name":
        rows[1] = ("audit_events", "unreviewed_index", *interrupted[2:])
    elif change == "wrong_definition":
        rows[1] = (
            *interrupted[:2],
            interrupted[2].replace("target_type, target_id", "target_id, target_type"),
            *interrupted[3:],
        )
    elif change == "wrong_flags":
        rows[1] = (*interrupted[:4], True, *interrupted[5:])
    elif change == "healthy_target":
        rows[1] = (*interrupted[:3], True, True, *interrupted[5:])
    elif change == "missing":
        rows.pop()
    elif change == "extra_invalid":
        rows.append(
            (
                "audit_events",
                "unreviewed_index",
                "CREATE INDEX unreviewed_index ON public.audit_events USING btree (id)",
                False,
                False,
                True,
                False,
                False,
                False,
            )
        )
    elif change == "descriptor_flags":
        descriptor = (
            _INTERRUPTED_KEY,
            (*_INTERRUPTED_DEFINITION[:2], True, *_INTERRUPTED_DEFINITION[3:]),
        )
    engine = _CatalogEngine(rows)
    with pytest.raises(AssertionError):
        interrupted_index_catalog(engine, expected_index=descriptor)
