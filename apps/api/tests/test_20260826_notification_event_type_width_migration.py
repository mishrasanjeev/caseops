from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _event_type_lengths(database_url: str) -> dict[str, int | None]:
    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        return {
            table_name: next(
                column["type"].length
                for column in inspector.get_columns(table_name)
                if column["name"] == "event_type"
            )
            for table_name in (
                "notification_rules",
                "in_app_notifications",
                "notification_delivery_intents",
                "notification_delivery_events",
            )
        }
    finally:
        engine.dispose()


def test_notification_event_type_width_upgrade_and_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'width.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config()
    command.upgrade(config, "20260825_0006")
    assert set(_event_type_lengths(database_url).values()) == {40}

    command.upgrade(config, "20260826_0001")
    assert set(_event_type_lengths(database_url).values()) == {80}

    command.downgrade(config, "20260825_0006")
    assert set(_event_type_lengths(database_url).values()) == {40}
