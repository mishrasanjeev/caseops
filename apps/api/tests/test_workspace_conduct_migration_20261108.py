"""The additive conduct receipt migration preserves data on downgrade refusal."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import Company, CompanyMembership, User, WorkspaceConductAcceptance
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config

PREVIOUS = "20261106_0002"
HEAD = "20261108_0001"
TABLE = "workspace_conduct_acceptances"


def _shape(schema):
    return (
        [{**column, "type": str(column["type"])} for column in schema.get_columns(TABLE)],
        schema.get_foreign_keys(TABLE),
        schema.get_indexes(TABLE),
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
