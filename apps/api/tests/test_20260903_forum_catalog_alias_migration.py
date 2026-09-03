from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.models import ForumCatalogEntry

PREVIOUS_HEAD = "20260901_0001"
MIGRATION_HEAD = "20260903_0001"
DWARKA_ENTRY_ID = "consumer:dcdrc:delhi:dwarka"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def test_forum_alias_migration_round_trip_and_seed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'forum-aliases.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)

    engine = create_engine(database_url, future=True)
    try:
        assert "aliases_json" not in {
            str(column["name"])
            for column in inspect(engine).get_columns("forum_catalog_entries")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert "aliases_json" in {
            str(column["name"])
            for column in inspect(engine).get_columns("forum_catalog_entries")
        }
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                MIGRATION_HEAD
            )
            assert connection.scalar(
                text(
                    "SELECT aliases_json FROM forum_catalog_entries "
                    "WHERE id = :entry_id"
                ),
                {"entry_id": DWARKA_ENTRY_ID},
            ) == '["Dwarka_SWCF"]'
            assert connection.scalar(
                text(
                    "SELECT count(*) FROM forum_catalog_entries "
                    "WHERE id <> :entry_id AND aliases_json <> '[]'"
                ),
                {"entry_id": DWARKA_ENTRY_ID},
            ) == 0
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert "aliases_json" not in {
            str(column["name"])
            for column in inspect(engine).get_columns("forum_catalog_entries")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)


def test_forum_alias_model_tracks_migrated_column() -> None:
    assert "aliases_json" in ForumCatalogEntry.__table__.c

