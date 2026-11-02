"""Actual additive revision and retained downgrade refusal, without erasure."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import UniqueConstraint, inspect, select, text

from alembic import command
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import AccountDeletionRequest
from caseops_api.main import create_application
from tests.migration_index_catalog import schema_catalog
from tests.test_account_privacy_20261027 import (
    forbid_unadmitted_network as _forbid_unadmitted_network,
)
from tests.test_account_privacy_20261027 import (
    roundtrip,
    snapshot,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config

forbid_unadmitted_network = _forbid_unadmitted_network

PREVIOUS = "20261027_0003"
HEAD = "20261027_0004"
TABLE = "account_deletion_requests"


def shape(engine):
    schema = inspect(engine)
    return {
        "columns": [(c["name"], str(c["type"]), c["nullable"]) for c in schema.get_columns(TABLE)],
        "indexes": schema.get_indexes(TABLE),
        "unique": schema.get_unique_constraints(TABLE),
        "checks": schema.get_check_constraints(TABLE),
        "foreign_keys": schema.get_foreign_keys(TABLE),
    }


@pytest.mark.parametrize("kind", KINDS)
def test_exact_previous_revision_upgrade_and_empty_restore_forward_guard(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_tables = set(inspect(engine).get_table_names())
        assert TABLE not in old_tables
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | {TABLE}
        assert {c["name"] for c in schema.get_columns(TABLE)} == set(
            AccountDeletionRequest.__table__.columns.keys()
        )
        assert not database_foreign_key_gaps(schema, table_names={TABLE})
        expected_indexes = {
            "ix_account_deletion_request_routing": (
                ("submitted_from_company_id", "submitted_by_membership_id"),
                False,
            )
        }
        expected_unique = {"uq_account_deletion_request_subject": ("subject_user_id",)}
        assert {
            index.name: (tuple(column.name for column in index.expressions), index.unique)
            for index in AccountDeletionRequest.__table__.indexes
        } == expected_indexes
        assert {
            constraint.name: tuple(column.name for column in constraint.columns)
            for constraint in AccountDeletionRequest.__table__.constraints
            if isinstance(constraint, UniqueConstraint)
        } == expected_unique
        reflected_indexes = schema.get_indexes(TABLE)
        assert {
            index["name"]: (tuple(index["column_names"]), index["unique"])
            for index in reflected_indexes
            if not index.get("duplicates_constraint")
        } == expected_indexes
        assert {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in schema.get_unique_constraints(TABLE)
        } == expected_unique
        # PostgreSQL exposes the unique constraint's backing index separately;
        # verify its exact identity rather than dropping every unique index.
        assert {
            index["name"]: (
                tuple(index["column_names"]),
                index["unique"],
                index["duplicates_constraint"],
            )
            for index in reflected_indexes
            if index.get("duplicates_constraint")
        } == (
            {
                "uq_account_deletion_request_subject": (
                    ("subject_user_id",),
                    True,
                    "uq_account_deletion_request_subject",
                )
            }
            if engine.dialect.name == "postgresql"
            else {}
        )
        before = shape(engine)
        command.upgrade(config, HEAD)
        with pytest.raises(RuntimeError, match="receipts are retained evidence; restore-forward"):
            command.downgrade(config, PREVIOUS)
        assert shape(engine) == before
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            assert connection.execute(select(AccountDeletionRequest.__table__)).all() == []


@pytest.mark.parametrize("kind", KINDS)
def test_received_request_downgrade_preserves_all_rows_columns_indexes_and_revision(
    kind, tmp_path, monkeypatch, client
):
    # The client fixture supplies the canonical local/offline environment only.
    # This separate database is ACTUALLY at the dated0004 boundary: a later
    # restore-forward guard must not impersonate the account-request refusal.
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        with TestClient(create_application()) as historical:
            roundtrip(historical)
            before, before_shape, catalog = snapshot(), shape(engine), schema_catalog(engine)
            assert len(before["requests"]) == len(before["private_audits"]) == 1
            with pytest.raises(
                RuntimeError, match="receipts are retained evidence; restore-forward"
            ):
                command.downgrade(config, PREVIOUS)
            assert snapshot() == before
            assert shape(engine) == before_shape
            assert schema_catalog(engine) == catalog
            with engine.connect() as connection:
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


def test_new_migration_has_no_account_delete_or_provider_operation():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic/versions/20261027_0004_account_deletion_requests.py"
    )
    source = path.read_text()
    assert 'down_revision = "20261027_0003"' in source
    assert "DATA-GOVERNANCE-MAP: updated" in source
    assert "drop_table" not in source and "drop_column" not in source
