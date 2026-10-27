"""Real DDL negative controls for a historical whole-catalog comparison."""

import pytest
from sqlalchemy import create_engine

from tests.migration_index_catalog import require_index_additions, schema_catalog


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
