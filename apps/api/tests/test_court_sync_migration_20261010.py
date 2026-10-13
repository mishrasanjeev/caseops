"""Independent upgrade/downgrade rehearsal; no application database cloning."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.settings import get_settings
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership


def _rehearse(engine, monkeypatch, record):
    api = Path(__file__).resolve().parents[1]
    config = Config(str(api / "alembic.ini"))
    config.set_main_option("script_location", str(api / "alembic"))
    monkeypatch.setenv("CASEOPS_DATABASE_URL", engine.url.render_as_string(hide_password=False))
    monkeypatch.setenv("CASEOPS_ENV", "local")
    get_settings.cache_clear()
    command.upgrade(config, "20261010_0001")
    before = inspect(engine)
    assert "no_paid_providers" not in {
        column["name"] for column in before.get_columns("matter_court_sync_jobs")
    }

    def document_columns():
        return [
            (column["name"], str(column["type"]), column["nullable"], column["default"])
            for column in inspect(engine).get_columns("document_processing_jobs")
        ]

    documents = document_columns()
    assert "no_paid_providers" in {column[0] for column in documents}
    with Session(engine) as session:
        company = _seed_company(session)
        actor = _seed_membership(session, company)
        matter = _seed_matter(session, company)
        job_id = str(uuid4())
        session.execute(
            text(
                "INSERT INTO matter_court_sync_jobs "
                "(id, company_id, matter_id, requested_by_membership_id, source, source_reference, "
                "status, imported_cause_list_count, imported_order_count, queued_at, updated_at) "
                "VALUES (:id, :company, :matter, :actor, 'local-emulator', 'legacy-source', "
                "'queued', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": job_id, "company": company, "matter": matter, "actor": actor},
        )
        session.commit()
    command.upgrade(config, "20261010_0002")
    column = next(
        column
        for column in inspect(engine).get_columns("matter_court_sync_jobs")
        if column["name"] == "no_paid_providers"
    )
    assert column["nullable"] is False
    assert column["default"] is not None
    index_columns = {
        index["name"]: index["column_names"]
        for index in inspect(engine).get_indexes("matter_court_sync_jobs")
    }
    assert index_columns["ix_matter_court_sync_jobs_queue"] == [
        "status",
        "queued_at",
        "updated_at",
        "id",
    ]
    assert index_columns["ix_matter_court_sync_jobs_recovery"] == ["status", "started_at", "id"]
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT no_paid_providers, requested_by_membership_id, source_reference "
                "FROM matter_court_sync_jobs WHERE id = :id"
            ),
            {"id": job_id},
        ).one()
        assert bool(row[0]) is True and tuple(row[1:]) == (actor, "legacy-source")
        human_job_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO matter_court_sync_jobs "
                "(id, company_id, matter_id, requested_by_membership_id, source, source_reference, "
                "status, imported_cause_list_count, imported_order_count, queued_at, updated_at, "
                "no_paid_providers) VALUES (:id, :company, :matter, :actor, 'local-emulator', "
                "'human-source', 'queued', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, false)"
            ),
            {"id": human_job_id, "company": company, "matter": matter, "actor": actor},
        )
    with engine.connect() as connection:
        receipts = connection.execute(
            text("SELECT * FROM matter_court_sync_jobs ORDER BY id")
        ).all()
    indexes_before = inspect(engine).get_indexes("matter_court_sync_jobs")
    record(
        "court_migration_upgrade",
        column_nullable=column["nullable"],
        server_default=str(column["default"]),
        retained_actor=actor,
        retained_source="legacy-source",
        legacy_marker=True,
    )
    with pytest.raises(RuntimeError, match="restore-forward"):
        command.downgrade(config, "20261010_0001")
    assert "no_paid_providers" in {
        column["name"] for column in inspect(engine).get_columns("matter_court_sync_jobs")
    }
    assert documents == document_columns()
    assert inspect(engine).get_indexes("matter_court_sync_jobs") == indexes_before
    command.upgrade(config, "20261010_0002")
    with engine.connect() as connection:
        assert (
            bool(
                connection.scalar(
                    text("SELECT no_paid_providers FROM matter_court_sync_jobs WHERE id = :id"),
                    {"id": job_id},
                )
            )
            is True
        )
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261010_0002"
        assert connection.execute(
            text("SELECT * FROM matter_court_sync_jobs ORDER BY id")
        ).all() == receipts
        assert connection.scalar(
            text("SELECT no_paid_providers FROM matter_court_sync_jobs WHERE id = :id"),
            {"id": human_job_id},
        ) in (False, 0)
    record(
        "court_migration_restore_forward_refusal",
        default_blocked=True,
        explicit_human_false_retained=True,
        receipts_and_indexes_retained=True,
        document_schema_unchanged=True,
        head="20261010_0002",
    )


def test_court_marker_migration_sqlite_independent(tmp_path, monkeypatch):
    engine = create_engine("sqlite+pysqlite:///" + (tmp_path / "migration.db").as_posix())
    try:
        _rehearse(engine, monkeypatch, lambda *_args, **_kwargs: None)
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_court_marker_migration_postgres_independent(pg_engine, monkeypatch, record_property):
    database = "court_migration_" + uuid4().hex
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{database}"'))
    engine = create_engine(pg_engine.url.set(database=database))
    receipts = []
    try:
        _rehearse(
            engine,
            monkeypatch,
            lambda kind, **data: receipts.append({"event": kind, **data}),
        )
    finally:
        engine.dispose()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
            assert not admin.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database}
            )
        record_property("owned_migration_database", database)
        record_property("owned_migration_database_dropped", "true")
        for item in receipts:
            record_property(item["event"], str(item))
