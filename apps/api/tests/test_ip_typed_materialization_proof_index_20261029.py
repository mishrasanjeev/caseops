"""Exact0001→0002 typed source-proof index and retained lineage, on both dialects."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.models import AuditEvent, BulkImportJob, IpDocketRecord, IpImportRow
from tests.migration_index_catalog import (
    interrupted_index_catalog,
    require_index_additions,
    require_revision,
    schema_catalog,
    write_catalog,
)
from tests.test_counsel_page_migration_20261027 import _rows
from tests.test_matter_readthrough_indexes_20261028 import PRESERVED as OTHER_PRESERVED
from tests.test_matter_readthrough_indexes_20261028 import populate as populate_other
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_membership

PARENT = "20261029_0001"
HEAD = "20261029_0002"
NAME = "ix_audit_events_typed_source_proof_seek"
COLUMNS = ["target_type", "target_id", "company_id", "ip_docket_id", "action", "id"]
EXPECTED = (("audit_events", NAME, COLUMNS),)
PRESERVED = tuple(sorted(set(OTHER_PRESERVED) | {
    "bulk_import_jobs", "ip_import_rows", "ip_docket_records",
}))
PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic/versions/20261029_0002_audit_typed_source_proof_seek.py"
)
STAMP = datetime(2026, 10, 29, 1, 2, 3, 123456, tzinfo=UTC)


def module():
    spec = importlib.util.spec_from_file_location("dated_audit_typed_source_proof_index", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def apply(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"destination_rev": PARENT})
        with context.begin_transaction(), Operations.context(context):
            module().upgrade()


def populate(engine):
    populate_other(engine)
    with Session(engine) as session:
        company = _seed_company(session)
        member = _seed_membership(session, company)
        job = BulkImportJob(
            company_id=company, domain="ip_trademark", filename="retained-synthetic.csv",
            source_sha256="a" * 64, status="committed", total_rows=1,
            valid_rows=1, committed_rows=1, creator_label_snapshot="Owned offline fixture",
            created_by_membership_id=member, committed_at=STAMP,
            created_at=STAMP, updated_at=STAMP,
        )
        docket = IpDocketRecord(
            company_id=company, record_type="trademark_application",
            title="Retained synthetic source", created_by_membership_id=member,
            created_at=STAMP, updated_at=STAMP,
        )
        session.add_all([job, docket])
        session.flush()
        source = IpImportRow(
            company_id=company, job_id=job.id, row_number=1,
            raw_json={"literal": "unchanged original source"},
            normalized_json={"application_date": "2020-01-15"},
            validation_status="valid", commit_status="committed",
            created_docket_id=docket.id, created_at=STAMP, updated_at=STAMP,
        )
        session.add(source)
        session.flush()
        session.add(AuditEvent(
            company_id=company, actor_type="membership", actor_membership_id=member,
            ip_docket_id=docket.id, action="ip_docket.source_materialized",
            target_type="ip_import_row", target_id=source.id,
            metadata_json='{"literal":"retained materialization lineage"}', created_at=STAMP,
        ))
        session.commit()


def old_index_identity(engine):
    name = "ix_audit_events_source_proof_seek"
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            value = connection.scalar(text("SELECT to_regclass(:name)::oid"), {"name": name})
        else:
            value = connection.scalar(
                text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": name}
            )
    assert value is not None
    return value


def shape(engine):
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            state = module()._postgres_state(connection, "audit_events", NAME, COLUMNS)
            assert state is not None and state["indisvalid"] and state["indisready"]
            identity = connection.scalar(text("SELECT to_regclass(:name)::oid"), {"name": NAME})
        else:
            present = module()._sqlite_exists(connection, "audit_events", NAME, COLUMNS)
            assert present
            identity = connection.scalar(
                text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": NAME}
            )
    return identity


@pytest.mark.parametrize("kind", KINDS)
def test_dated_typed_source_proof_index_roundtrip_preserves_every_retained_column(
    kind, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        before = _rows(engine, PRESERVED)
        assert all(before[table] for table in PRESERVED)
        parent = schema_catalog(engine)
        require_revision(engine, PARENT)
        write_catalog(tmp_path / "source-proof-parent.json", parent, PARENT)
        original_index_identity = old_index_identity(engine)
        if engine.dialect.name == "postgresql":
            # Canonical interrupted nonunique concurrent-build control: a real
            # owned pre-existing writer makes the build time out after catalog
            # admission. Never fabricate pg_index flags or widen lock budgets.
            with engine.connect() as connection:
                audit_id = connection.scalar(
                    text("SELECT id FROM audit_events ORDER BY id LIMIT 1")
                )
            assert audit_id is not None
            original_create = module().op.create_index
            interrupted = []

            def fail_during_owned_build(name, *args, **kwargs):
                if name != NAME:
                    return original_create(name, *args, **kwargs)
                bind = module().op.get_bind()
                previous_timeout = bind.exec_driver_sql("SHOW statement_timeout").scalar_one()
                with engine.connect() as blocker:
                    blocker.execute(text(
                        "UPDATE audit_events SET actor_label = actor_label WHERE id = :id"
                    ), {"id": audit_id})
                    bind.exec_driver_sql("SET statement_timeout = '250ms'")
                    try:
                        interrupted.append(name)
                        return original_create(name, *args, **kwargs)
                    finally:
                        blocker.rollback()
                        bind.exec_driver_sql(
                            "SELECT set_config('statement_timeout', %s, false)",
                            (previous_timeout,),
                        )

            with monkeypatch.context() as patch:
                patch.setattr(module().op, "create_index", fail_during_owned_build)
                with pytest.raises(DBAPIError) as canceled:
                    command.upgrade(config, HEAD)
            assert interrupted == [NAME]
            assert canceled.value.orig.sqlstate == "57014"
            with engine.connect() as connection:
                invalid = module()._postgres_state(connection, "audit_events", NAME, COLUMNS)
            assert invalid is not None
            assert invalid["indisvalid"] is False and invalid["indisready"] is False
            require_revision(engine, PARENT)
            retained_rows = _rows(engine, PRESERVED)
            assert retained_rows == before
            retained_old_identity = old_index_identity(engine)
            assert retained_old_identity == original_index_identity
            with pytest.raises(AssertionError) as rejected_catalog:
                schema_catalog(engine)
            assert rejected_catalog.value.args == ((
                "INVALID_OR_UNREADY_HISTORICAL_INDEX", ("index", "audit_events", NAME),
            ),)
            interrupted_definition = (
                "CREATE INDEX ix_audit_events_typed_source_proof_seek ON public.audit_events "
                "USING btree (target_type, target_id, company_id, ip_docket_id, action, id)",
                False, False, True, False, False, False,
            )
            interrupted_catalog = interrupted_index_catalog(
                engine,
                expected_index=(
                    ("index", "audit_events", NAME), interrupted_definition,
                ),
            )
            require_index_additions(parent, interrupted_catalog, EXPECTED)
            write_catalog(tmp_path / "typed-proof-interrupted.json", interrupted_catalog, PARENT)
        command.upgrade(config, HEAD)
        identity = shape(engine)
        retained_old_identity = old_index_identity(engine)
        assert retained_old_identity == original_index_identity
        head = schema_catalog(engine)
        require_index_additions(parent, head, EXPECTED)
        require_revision(engine, HEAD)
        write_catalog(tmp_path / "source-proof-head.json", head, HEAD)
        apply(engine)
        repeated_identity = shape(engine)
        assert repeated_identity == identity
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == before and retained_catalog == head
        command.downgrade(config, PARENT)
        retained_old_identity = old_index_identity(engine)
        assert retained_old_identity == original_index_identity
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == before and retained_catalog == parent
        require_revision(engine, PARENT)
        command.upgrade(config, HEAD)
        shape(engine)
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == before and retained_catalog == head
        require_revision(engine, HEAD)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("conflict", ["wrong_columns", "wrong_predicate"])
def test_typed_source_proof_conflicting_index_refuses_without_mutation(
    kind, conflict, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        columns = "company_id" if conflict == "wrong_columns" else ", ".join(COLUMNS)
        predicate = "" if conflict == "wrong_columns" else " WHERE company_id IS NOT NULL"
        with engine.begin() as connection:
            connection.exec_driver_sql(
                f'CREATE INDEX "{NAME}" ON audit_events ({columns}){predicate}'
            )
        before = _rows(engine, PRESERVED)
        catalog = schema_catalog(engine)
        with pytest.raises(
            RuntimeError, match="Audit typed source-proof seek index has a conflicting shape"
        ):
            apply(engine)
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == before and retained_catalog == catalog
        require_revision(engine, PARENT)


@pytest.mark.parametrize("kind", KINDS)
def test_actual_current_head_typed_source_proof_index_and_complete_index_health(
    kind, tmp_path, monkeypatch,
):
    from caseops_api.db.index_coverage import database_foreign_key_gaps

    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        current_head = ScriptDirectory.from_config(config).get_current_head()
        assert current_head
        command.upgrade(config, "head")
        require_revision(engine, current_head)
        shape(engine)
        gaps = database_foreign_key_gaps(inspect(engine))
        assert not gaps
        current = schema_catalog(engine)
        assert current
        populate(engine)
        preserved = _rows(engine, PRESERVED)
        assert all(preserved[table] for table in PRESERVED)
        old_identity = old_index_identity(engine)
        # A conflicting invocation-owned name at current head must refuse
        # downgrade before dropping any retained index or changing any data.
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP INDEX "{NAME}"')
            connection.exec_driver_sql(f'CREATE INDEX "{NAME}" ON audit_events (company_id)')
        conflicting = schema_catalog(engine)
        with pytest.raises(RuntimeError) as refused:
            command.downgrade(config, PARENT)
        assert str(refused.value) == (
            "Mobile/audit migration merge is restore-forward; restore the reviewed backup."
        )
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == preserved and retained_catalog == conflicting
        require_revision(engine, current_head)
        retained_old_identity = old_index_identity(engine)
        assert retained_old_identity == old_identity


@pytest.mark.parametrize("kind", KINDS)
def test_dated_typed_source_proof_downgrade_conflict_preserves_revision_rows_and_catalog(
    kind, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        require_revision(engine, HEAD)
        populate(engine)
        old_identity = old_index_identity(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP INDEX "{NAME}"')
            connection.exec_driver_sql(f'CREATE INDEX "{NAME}" ON audit_events (company_id)')
        before_rows, before_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert all(before_rows[table] for table in PRESERVED)
        with pytest.raises(RuntimeError) as refused:
            command.downgrade(config, PARENT)
        assert str(refused.value) == (
            "Audit typed source-proof seek index has a conflicting shape."
        )
        retained_rows, retained_catalog = _rows(engine, PRESERVED), schema_catalog(engine)
        assert retained_rows == before_rows and retained_catalog == before_catalog
        require_revision(engine, HEAD)
        retained_old_identity = old_index_identity(engine)
        assert retained_old_identity == old_identity
