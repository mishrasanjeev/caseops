from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _state(database_url: str) -> tuple[set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        columns = {
            str(row["name"]) for row in inspector.get_columns("trademark_applications")
        }
        checks = {
            str(row["name"])
            for row in inspector.get_check_constraints("trademark_applications")
            if row.get("name")
        }
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return columns, checks, head
    finally:
        engine.dispose()


def test_application_lifecycle_migration_round_trip(tmp_path: Path, monkeypatch) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'application-life.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, "20260807_0003")
    columns, _, head = _state(database_url)
    assert "is_active" not in columns
    assert head == "20260807_0003"

    command.upgrade(config, "20260807_0004")
    columns, checks, head = _state(database_url)
    assert {"is_active", "lifecycle_version"}.issubset(columns)
    assert {
        "ck_tm_application_phase_active_consistent",
        "ck_tm_application_lifecycle_version_nonnegative",
    }.issubset(checks)
    assert head == "20260807_0004"

    command.downgrade(config, "20260807_0003")
    columns, _, head = _state(database_url)
    assert "is_active" not in columns
    assert head == "20260807_0003"

    command.upgrade(config, "20260807_0004")
    columns, checks, head = _state(database_url)
    assert {"is_active", "lifecycle_version"}.issubset(columns)
    assert "ck_tm_application_phase_active_consistent" in checks
    assert head == "20260807_0004"

    get_settings.cache_clear()
    clear_engine_cache()
