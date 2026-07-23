from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _matter_columns(database_url: str) -> dict[str, dict[str, object]]:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return {
                str(row["name"]): dict(row)
                for row in connection.execute(
                    text("PRAGMA table_info(matters)")
                ).mappings()
            }
    finally:
        engine.dispose()


def test_court_forum_number_migration_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "court-forum-number.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260717_0002")
    assert "court_forum_number" not in _matter_columns(database_url)

    command.upgrade(config, "head")
    upgraded = _matter_columns(database_url)["court_forum_number"]
    assert str(upgraded["type"]).upper() == "VARCHAR(120)"
    assert upgraded["notnull"] == 0

    command.downgrade(config, "20260717_0002")
    assert "court_forum_number" not in _matter_columns(database_url)

    command.upgrade(config, "head")
    assert "court_forum_number" in _matter_columns(database_url)

    get_settings.cache_clear()
    clear_engine_cache()
