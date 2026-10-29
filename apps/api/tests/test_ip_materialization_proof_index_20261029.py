"""Exact0008→0001 source-proof index and retained lineage, on both dialects."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from caseops_api.db.models import AuditEvent, BulkImportJob, IpDocketRecord, IpImportRow
from tests.migration_index_catalog import (
    require_index_additions, require_revision, schema_catalog, write_catalog,
)
from tests.test_counsel_page_migration_20261027 import _rows
from tests.test_matter_readthrough_indexes_20261028 import PRESERVED as OTHER_PRESERVED
from tests.test_matter_readthrough_indexes_20261028 import populate as populate_other
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_membership

PARENT = "20261027_0008"
HEAD = "20261029_0001"
NAME = "ix_audit_events_source_proof_seek"
COLUMNS = ["company_id", "target_id", "ip_docket_id", "action", "target_type", "id"]
EXPECTED = (("audit_events", NAME, COLUMNS),)
PRESERVED = tuple(sorted(set(OTHER_PRESERVED) | {
    "bulk_import_jobs", "ip_import_rows", "ip_docket_records",
}))
PATH = Path(__file__).resolve().parents[1] / "alembic/versions/20261029_0001_audit_source_proof_seek.py"
STAMP = datetime(2026, 10, 29, 1, 2, 3, 123456, tzinfo=UTC)


def module():
    spec = importlib.util.spec_from_file_location("dated_audit_source_proof_index", PATH)
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
def test_dated_source_proof_index_roundtrip_preserves_every_retained_column(
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
        command.upgrade(config, HEAD)
        identity = shape(engine)
        head = schema_catalog(engine)
        require_index_additions(parent, head, EXPECTED)
        require_revision(engine, HEAD)
        write_catalog(tmp_path / "source-proof-head.json", head, HEAD)
        apply(engine)
        assert shape(engine) == identity
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == head
        command.downgrade(config, PARENT)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == parent
        require_revision(engine, PARENT)
        command.upgrade(config, HEAD)
        shape(engine)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == head
        require_revision(engine, HEAD)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("conflict", ["wrong_columns", "wrong_predicate"])
def test_source_proof_conflicting_index_refuses_without_mutation(
    kind, conflict, tmp_path, monkeypatch,
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PARENT)
        populate(engine)
        columns = "company_id" if conflict == "wrong_columns" else ", ".join(COLUMNS)
        predicate = "" if conflict == "wrong_columns" else " WHERE company_id IS NOT NULL"
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE INDEX "{NAME}" ON audit_events ({columns}){predicate}')
        before = _rows(engine, PRESERVED)
        catalog = schema_catalog(engine)
        with pytest.raises(RuntimeError, match="Audit source-proof seek index has a conflicting shape"):
            apply(engine)
        assert _rows(engine, PRESERVED) == before and schema_catalog(engine) == catalog
        require_revision(engine, PARENT)


@pytest.mark.parametrize("kind", KINDS)
def test_actual_current_head_source_proof_index_and_complete_index_health(
    kind, tmp_path, monkeypatch,
):
    from caseops_api.db.index_coverage import database_foreign_key_gaps

    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, "head")
        shape(engine)
        assert not database_foreign_key_gaps(inspect(engine))
        current = schema_catalog(engine)
        assert current
