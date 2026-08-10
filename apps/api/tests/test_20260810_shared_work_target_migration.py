from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

TARGET_TABLES = {
    "matter_tasks",
    "matter_hearings",
    "hearing_reminders",
    "matter_next_hearing_history",
    "matter_next_hearing_suggestions",
    "matter_deadlines",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
    finally:
        engine.dispose()


def test_shared_work_expand_backfill_switch_downgrade_reupgrade(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'shared-work.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, "20260809_0001")
    assert _head(database_url) == "20260809_0001"

    command.upgrade(config, "20260810_0001")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            columns = {column["name"]: column for column in inspector.get_columns(table_name)}
            assert "ip_docket_id" in columns
            assert columns["matter_id"]["nullable"] is True
        assert "ip_docket_id" in {
            column["name"]
            for column in inspector.get_columns("notification_delivery_intents")
        }
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0001"

    command.upgrade(config, "20260810_0003")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            checks = {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            assert any(name and name.endswith("exactly_one_target") for name in checks)
    finally:
        engine.dispose()
    assert _head(database_url) == "20260810_0003"

    command.downgrade(config, "20260809_0001")
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        for table_name in TARGET_TABLES:
            assert "ip_docket_id" not in {
                column["name"] for column in inspector.get_columns(table_name)
            }
    finally:
        engine.dispose()
    assert _head(database_url) == "20260809_0001"

    command.upgrade(config, "20260810_0003")
    assert _head(database_url) == "20260810_0003"
