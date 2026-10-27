"""Fresh, independent portfolio lease migration rehearsals; never clone app rows."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from alembic import command, op
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_postgres_validation import _seed_company, _seed_membership

PARENT = "20261022_0001"
HEAD = "20261026_0001"
TABLE = "ip_portfolio_export_jobs"
NEW_COLUMNS = {"dispatch_protocol_version", "worker_claim_token", "worker_claim_expires_at"}
INDEXES = {
    "ix_ip_portfolio_exports_requester_status": [
        "company_id", "requested_by_membership_id", "status", "id",
    ],
    "ix_ip_portfolio_exports_queue": ["dispatch_protocol_version", "status", "created_at", "id"],
    "ix_ip_portfolio_exports_recovery": [
        "dispatch_protocol_version", "status", "worker_claim_expires_at", "created_at", "id",
    ],
}


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def fresh_migration_engine(request, tmp_path):
    if request.param == "postgres":
        source = request.getfixturevalue("pg_engine")
        # template=None creates from template0, not even the HTTP test template.
        with temporary_http_database(source.url) as engine:
            yield engine
    else:
        engine = create_engine(
            "sqlite+pysqlite:///" + (tmp_path / "worker-migration.db").as_posix()
        )
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture
def migration(fresh_migration_engine, monkeypatch):
    engine = fresh_migration_engine
    monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("CASEOPS_ENV", "local")
    get_settings.cache_clear()
    clear_engine_cache()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    try:
        command.upgrade(config, PARENT)
        assert NEW_COLUMNS.isdisjoint(
            column["name"] for column in inspect(engine).get_columns(TABLE)
        )
        with Session(engine) as session:
            company_id = _seed_company(session)
            membership_id = _seed_membership(session, company_id)
            session.commit()
        yield engine, config, company_id, membership_id
    finally:
        clear_engine_cache()
        get_settings.cache_clear()


def _old_insert(engine, company_id, membership_id, *, status="pending"):
    identity = str(uuid4())
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO ip_portfolio_export_jobs "
            "(id, company_id, requested_by_membership_id, status, format, filters_json, "
            "columns_json, row_limit, storage_key, row_count, size_bytes, error, "
            "started_at, completed_at, created_at) "
            "VALUES (:id, :company, :member, :status, 'csv', '{}', '[\"mark\"]', 50000, "
            ":storage, :rows, :size, :error, :started, :completed, :created)"
        ), {
            "id": identity, "company": company_id, "member": membership_id, "status": status,
            "storage": "retained/legacy.csv" if status == "completed" else None,
            "rows": 51 if status == "completed" else None,
            "size": 1280 if status == "completed" else None,
            "error": "retained original failure" if status == "failed" else None,
            "started": datetime(2026, 10, 23, tzinfo=UTC) if status != "pending" else None,
            "completed": (
                datetime(2026, 10, 24, tzinfo=UTC) if status in {"completed", "failed"} else None
            ),
            "created": datetime(2026, 10, 22, tzinfo=UTC),
        })
    return identity


def _rows(engine, *, old_only=False):
    columns = (
        "id, company_id, requested_by_membership_id, status, format, filters_json, columns_json, "
        "row_limit, storage_key, row_count, size_bytes, error, started_at, completed_at, created_at"
        if old_only else "*"
    )
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT {columns} FROM {TABLE} ORDER BY id")).all()


def _assert_shape(engine):
    schema = inspect(engine)
    columns = {column["name"]: column for column in schema.get_columns(TABLE)}
    assert NEW_COLUMNS.issubset(columns)
    assert columns["dispatch_protocol_version"]["nullable"] is False
    assert str(columns["dispatch_protocol_version"]["default"]).strip("'() ") == "0"
    assert columns["worker_claim_token"]["type"].length == 36
    assert columns["worker_claim_token"]["nullable"]
    assert columns["worker_claim_expires_at"]["nullable"]
    if engine.dialect.name == "postgresql":
        assert columns["worker_claim_expires_at"]["type"].timezone
    checks = {check["name"] for check in schema.get_check_constraints(TABLE)}
    assert "ck_ip_portfolio_export_dispatch_protocol" in checks
    assert "ck_ip_portfolio_export_claim_state" in checks
    actual_indexes = {index["name"]: index for index in schema.get_indexes(TABLE)}
    for name, expected in INDEXES.items():
        assert actual_indexes[name]["column_names"] == expected
        assert not actual_indexes[name]["unique"]
        if engine.dialect.name == "postgresql":
            with engine.connect() as connection:
                assert connection.execute(text(
                    "SELECT i.indisvalid, i.indisready FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
                ), {"name": name}).one() == (True, True)


def test_additive_upgrade_preserves_legacy_and_old_writer_defaults(migration):
    engine, config, company_id, membership_id = migration
    legacy = [_old_insert(engine, company_id, membership_id, status=status)
              for status in ("pending", "running", "completed", "failed")]
    before = _rows(engine, old_only=True)
    command.upgrade(config, HEAD)
    _assert_shape(engine)
    assert _rows(engine, old_only=True) == before
    old_after = _old_insert(engine, company_id, membership_id)
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, dispatch_protocol_version, worker_claim_token, worker_claim_expires_at "
            "FROM ip_portfolio_export_jobs ORDER BY id"
        )).all()
        assert rows == [(identity, 0, None, None) for identity in sorted([*legacy, old_after])]
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(
            "UPDATE ip_portfolio_export_jobs SET dispatch_protocol_version = 2 WHERE id = :id"
        ), {"id": old_after})
    receipts = _rows(engine)
    command.upgrade(config, HEAD)
    assert _rows(engine) == receipts


def test_downgrade_refuses_before_losing_populated_protocol_or_claim(migration):
    engine, config, company_id, membership_id = migration
    identity = _old_insert(engine, company_id, membership_id, status="running")
    command.upgrade(config, HEAD)
    token = str(uuid4())
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE ip_portfolio_export_jobs SET dispatch_protocol_version = 1, "
            "status = 'running', "
            "worker_claim_token = :token, worker_claim_expires_at = :expires WHERE id = :id"
        ), {"token": token, "expires": datetime.now(UTC) + timedelta(seconds=300), "id": identity})
    before = _rows(engine)
    indexes = inspect(engine).get_indexes(TABLE)
    with pytest.raises(RuntimeError, match="restore-forward"):
        command.downgrade(config, PARENT)
    assert _rows(engine) == before and inspect(engine).get_indexes(TABLE) == indexes
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    command.upgrade(config, HEAD)
    assert _rows(engine) == before


@pytest.mark.postgres
@pytest.mark.parametrize("fresh_migration_engine", ["postgres"], indirect=True)
def test_interrupted_concurrent_build_replays_without_resetting_claims(migration, monkeypatch):
    engine, config, company_id, membership_id = migration
    assert engine.dialect.name == "postgresql"
    identity = _old_insert(engine, company_id, membership_id)
    original = op.create_index
    interrupted = []

    def fail_during_real_build(name, *args, **kwargs):
        if name != "ix_ip_portfolio_exports_queue":
            return original(name, *args, **kwargs)
        with engine.connect() as blocker:
            blocker.execute(text(
                "UPDATE ip_portfolio_export_jobs SET error = error WHERE id = :id"
            ), {"id": identity})
            # The real non-unique build waits on this pre-existing writer. Its
            # cancellation leaves the invalid/not-ready index in PostgreSQL.
            op.get_bind().exec_driver_sql("SET statement_timeout = '250ms'")
            try:
                interrupted.append(name)
                return original(name, *args, **kwargs)
            finally:
                blocker.rollback()

    with monkeypatch.context() as patch:
        patch.setattr(op, "create_index", fail_during_real_build)
        with pytest.raises(DBAPIError):
            command.upgrade(config, HEAD)
    assert interrupted == ["ix_ip_portfolio_exports_queue"]
    assert NEW_COLUMNS.issubset(column["name"] for column in inspect(engine).get_columns(TABLE))
    token = str(uuid4())
    with engine.begin() as connection:
        assert connection.execute(text(
            "SELECT i.indisvalid, i.indisready FROM pg_index i "
            "JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = 'ix_ip_portfolio_exports_queue'"
        )).one() != (True, True)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == PARENT
        connection.execute(text(
            "UPDATE ip_portfolio_export_jobs SET dispatch_protocol_version = 1, "
            "status = 'running', "
            "worker_claim_token = :token, worker_claim_expires_at = :expires WHERE id = :id"
        ), {"token": token, "expires": datetime.now(UTC) + timedelta(seconds=300), "id": identity})
    before = _rows(engine)
    command.upgrade(config, HEAD)
    _assert_shape(engine)
    assert _rows(engine) == before
    command.upgrade(config, HEAD)
    assert _rows(engine) == before
