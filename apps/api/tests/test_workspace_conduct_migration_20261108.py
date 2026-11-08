"""The additive conduct receipt migration preserves data on downgrade refusal."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import (
    Company,
    CompanyMembership,
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
