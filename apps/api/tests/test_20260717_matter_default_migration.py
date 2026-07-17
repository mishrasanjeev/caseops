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


def _matter_status_default(database_url: str) -> str | None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(text("PRAGMA table_info(matters)")).mappings()
            status = next(row for row in rows if row["name"] == "status")
            return status["dflt_value"]
    finally:
        engine.dispose()


def test_matter_status_database_default_upgrades_and_downgrades_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "matter-default.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260715_0001")
    assert _matter_status_default(database_url) is None

    command.upgrade(config, "head")
    assert (_matter_status_default(database_url) or "").strip("'") == "active"

    command.downgrade(config, "20260715_0001")
    assert _matter_status_default(database_url) is None

    get_settings.cache_clear()
    clear_engine_cache()
