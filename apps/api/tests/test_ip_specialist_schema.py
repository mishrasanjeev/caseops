from sqlalchemy import CheckConstraint, create_engine, inspect

from caseops_api.db import ip_specialist_models as models
from caseops_api.db.index_coverage import database_foreign_key_gaps

MODELS = (
    models.IpSpecialistRecord,
    models.IpSpecialistVersion,
    models.IpSpecialistObservation,
    models.IpSpecialistWorkflow,
    models.IpSpecialistWorkflowVersion,
    models.IpSpecialistWorkflowSource,
    models.IpSpecialistObligationLink,
    models.IpSpecialistObligationEvent,
)


def assert_schema(inspector):
    names = {model.__tablename__ for model in MODELS}
    assert database_foreign_key_gaps(inspector, table_names=names) == ()
    for model in MODELS:
        table = model.__table__
        actual = {column["name"]: column for column in inspector.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys()), table.name
        for column in table.columns:
            assert actual[column.name]["nullable"] == column.nullable, (table.name, column.name)
        indexes = {
            index["name"]: tuple(index["column_names"])
            for index in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            assert indexes[index.name] == tuple(column.name for column in index.columns)
        expected_fks = {
            (
                tuple(column.name for column in fk.columns),
                tuple(element.target_fullname for element in fk.elements),
            )
            for fk in table.foreign_key_constraints
        }
        actual_fks = {
            (
                tuple(fk["constrained_columns"]),
                tuple(f"{fk['referred_table']}.{column}" for column in fk["referred_columns"]),
            )
            for fk in inspector.get_foreign_keys(table.name)
        }
        assert actual_fks == expected_fks, table.name
        expected_checks = {
            constraint.name
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        checks = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints(table.name)
        }
        assert set(checks) == expected_checks, table.name
        if table.name == "ip_specialist_workflows":
            assert "layout_application" in checks["ck_specialist_workflow_kind"]


def test_all_eight_specialist_tables_match_the_migrated_schema(_migrated_template_db):
    engine = create_engine(f"sqlite+pysqlite:///{_migrated_template_db.as_posix()}")
    try:
        assert_schema(inspect(engine))
    finally:
        engine.dispose()
