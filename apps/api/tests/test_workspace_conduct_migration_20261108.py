"""The additive conduct receipt migration preserves data on downgrade refusal."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    User,
    WorkspaceConductAcceptance,
    WorkspaceConductReport,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config

PREVIOUS = "20261106_0002"
HEAD = "20261108_0001"
TABLE = "workspace_conduct_acceptances"


def _shape(schema, table=TABLE):
    return (
        [{**column, "type": str(column["type"])} for column in schema.get_columns(table)],
        schema.get_foreign_keys(table),
        schema.get_indexes(table),
    )


@pytest.mark.parametrize("kind", KINDS)
def test_additive_acceptance_migration_and_retained_downgrade_guard(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_tables = set(inspect(engine).get_table_names())
        assert TABLE not in old_tables
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | {TABLE}
        assert schema.get_pk_constraint(TABLE)["constrained_columns"] == [
            "company_id", "membership_id", "version",
        ]
        assert not database_foreign_key_gaps(schema, table_names={TABLE})
        before = _shape(schema)
        with Session(engine) as session:
            company = Company(
                name="Synthetic migration tenant", slug="conduct-migration",
                tenant_key="conduct-migration", company_type="law_firm",
            )
            user = User(
                full_name="Synthetic migration actor", email="migration@example.com",
                password_hash="test-fixture-unused",
            )
            membership = CompanyMembership(company=company, user=user, role="member")
            session.add(membership)
            session.flush()
            session.add(WorkspaceConductAcceptance(
                company_id=company.id, membership_id=membership.id, version="2026-11-08",
                accepted_at=datetime(2026, 11, 8, tzinfo=UTC),
            ))
            session.commit()
        with engine.connect() as connection:
            original = connection.execute(select(WorkspaceConductAcceptance.__table__)).all()
        assert len(original) == 1
        with pytest.raises(RuntimeError, match="receipts are retained evidence; restore-forward"):
            command.downgrade(config, PREVIOUS)
        assert _shape(inspect(engine)) == before
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            retained = connection.execute(select(WorkspaceConductAcceptance.__table__)).all()
            assert retained == original


@pytest.mark.parametrize("kind", KINDS)
def test_additive_report_migration_restricts_cross_tenant_keys_and_preserves_receipts(
    kind, tmp_path, monkeypatch,
):
    report_table = "workspace_conduct_reports"
    report_revision = "20261108_0002"
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        old_tables = set(inspect(engine).get_table_names())
        assert report_table not in old_tables
        command.upgrade(config, report_revision)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | {report_table}
        assert not database_foreign_key_gaps(schema, table_names={report_table})
        before = _shape(schema, report_table)
        report = WorkspaceConductReport.__table__
        with Session(engine) as session:
            if kind == "sqlite":
                session.execute(text("PRAGMA foreign_keys=ON"))
                assert session.scalar(text("PRAGMA foreign_keys")) == 1
            memberships = []
            for name in ("one", "two"):
                company = Company(
                    name=f"Synthetic migration tenant {name}", slug=f"conduct-report-{name}",
                    tenant_key=f"conduct-report-{name}", company_type="law_firm",
                )
                user = User(
                    full_name="Synthetic migration actor", email=f"migration-{name}@example.com",
                    password_hash="test-fixture-unused",
                )
                membership = CompanyMembership(company=company, user=user, role="member")
                memberships.append(membership)
                session.add(membership)
            session.flush()
            first, other = memberships
            fields = {
                "company_id": first.company_id,
                "reporter_membership_id": first.id,
                "operation_id": str(uuid4()),
                "target_kind": "file",
                "target_membership_id": first.id,
                "source_kind": "file",
                "source_matter_id": str(uuid4()),
                "source_item_id": str(uuid4()),
                "reason": "other",
                "routing": "workspace",
                "received_at": datetime(2026, 11, 8, tzinfo=UTC),
            }
            session.execute(report.insert().values(**fields, id=str(uuid4())))
            for overrides in (
                {},
                {"target_membership_id": other.id, "operation_id": str(uuid4())},
                {"reporter_membership_id": other.id, "operation_id": str(uuid4())},
                {"target_kind": "user", "target_membership_id": None, "operation_id": str(uuid4())},
            ):
                with pytest.raises(IntegrityError), session.begin_nested():
                    session.execute(report.insert().values(**(fields | overrides), id=str(uuid4())))
            session.commit()
        with engine.connect() as connection:
            original = connection.execute(select(report)).all()
        assert len(original) == 1
        with pytest.raises(RuntimeError, match="reports are retained evidence; restore-forward"):
            command.downgrade(config, HEAD)
        assert _shape(inspect(engine), report_table) == before
        with engine.connect() as connection:
            current = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert current == report_revision
            assert connection.execute(select(report)).all() == original


@pytest.mark.parametrize("kind", KINDS)
def test_native_document_privacy_migration_preserves_existing_and_old_writer_rows(
    kind, tmp_path, monkeypatch,
):
    previous, current = "20261108_0002", "20261108_0003"
    name = "matter_attachments"
    flag = "native_local_processing_only"
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, previous)
        legacy = Table(name, MetaData(), autoload_with=engine)
        assert flag not in legacy.c
        with Session(engine) as session:
            company = Company(
                name="Synthetic privacy migration", slug="native-file-privacy",
                tenant_key="native-file-privacy", company_type="law_firm",
            )
            session.add(company)
            session.flush()
            matter = Matter(
                company_id=company.id, title="Synthetic privacy migration",
                matter_code="NATIVE-FILE-PRIVACY", status="intake",
                practice_area="Commercial advisory", forum_level="advisory",
            )
            session.add(matter)
            session.flush()
            matter_id = matter.id
            session.commit()
        base = {
            "matter_id": matter_id,
            "original_filename": "synthetic.txt",
            "content_type": "text/plain",
            "size_bytes": 9,
            "sha256_hex": "1" * 64,
            "processing_status": "pending",
            "extracted_char_count": 0,
            "notice_currency": "INR",
            "notice_reply_required": False,
            "notice_reply_sent": False,
            "notice_document_role": "notice",
            "created_at": datetime(2026, 11, 8, tzinfo=UTC),
        }

        def create(table, label, **values):
            key = str(uuid4())
            with engine.begin() as conn:
                conn.execute(table.insert().values(
                    **base, id=key, storage_key=f"synthetic-{label}", **values,
                ))
            return key

        original_id = create(legacy, "before")
        with engine.connect() as conn:
            original = dict(conn.execute(select(legacy)).mappings().one())
        command.upgrade(config, current)
        schema = inspect(engine)
        observed = Table(name, MetaData(), autoload_with=engine)
        assert set(observed.c.keys()) == set(legacy.c.keys()) | {flag}
        schema_before = _shape(schema, name)
        old_writer_id = create(legacy, "old-writer-after-upgrade")
        protected_id = create(observed, "native", native_local_processing_only=True)
        with engine.connect() as conn:
            records = {
                row["id"]: dict(row) for row in conn.execute(select(observed)).mappings()
            }
        assert records[original_id] == {**original, flag: False}
        assert records[old_writer_id][flag] is False
        assert records[protected_id][flag] is True
        with pytest.raises(RuntimeError, match="removing native attachment provenance"):
            command.downgrade(config, previous)
        assert _shape(inspect(engine), name) == schema_before
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == current
            assert {
                row["id"]: dict(row) for row in conn.execute(select(observed)).mappings()
            } == records
