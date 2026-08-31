from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.index_coverage import database_foreign_key_gaps

PREVIOUS_HEAD = "20260830_0002"
MIGRATION_HEAD = "20260831_0001"
CHECKPOINT_TABLE = "tenant_data_disposition_checkpoints"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_private_disposition_migration_round_trip_and_indexes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'disposition.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert CHECKPOINT_TABLE in inspector.get_table_names()
        event_columns = {
            str(column["name"]) for column in inspector.get_columns("private_projection_events")
        }
        assert {"attempt_count", "last_attempt_at", "next_attempt_at"} <= event_columns
        event_indexes = {
            str(index["name"]) for index in inspector.get_indexes("private_projection_events")
        }
        assert {
            "ix_private_projection_event_due",
            "ix_private_projection_event_maintenance",
        } <= event_indexes
        generation_indexes = {
            str(index["name"])
            for index in inspector.get_indexes("private_index_generations")
        }
        assert "ix_private_index_generation_maintenance" in generation_indexes
        checkpoint_indexes = {
            str(index["name"]) for index in inspector.get_indexes(CHECKPOINT_TABLE)
        }
        assert {
            "ix_data_disposition_checkpoint_company_status",
            "ix_data_disposition_checkpoint_operation",
            "ix_fk_data_disposition_checkpoint_private_event",
        } <= checkpoint_indexes
        assert (
            database_foreign_key_gaps(
                inspector,
                table_names={CHECKPOINT_TABLE},
            )
            == ()
        )
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version")) == MIGRATION_HEAD
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert CHECKPOINT_TABLE not in inspector.get_table_names()
        event_columns = {
            str(column["name"]) for column in inspector.get_columns("private_projection_events")
        }
        assert not {"attempt_count", "last_attempt_at", "next_attempt_at"} & event_columns
        generation_indexes = {
            str(index["name"])
            for index in inspector.get_indexes("private_index_generations")
        }
        assert "ix_private_index_generation_maintenance" not in generation_indexes
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
