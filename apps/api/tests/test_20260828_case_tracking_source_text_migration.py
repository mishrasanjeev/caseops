from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import build_index_health_report

PREVIOUS_HEAD = "20260828_0001"
MIGRATION_HEAD = "20260828_0002"
CURRENT_HEAD = "20260830_0003"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260828_0002_case_tracking_source_text.py"
    )
    spec = importlib.util.spec_from_file_location("case_tracking_source_text", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_case_tracking_source_text_migration_round_trip_and_index_health(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'source-text.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config()

    command.upgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        columns = {
            str(column["name"])
            for column in inspector.get_columns("tracked_case_updates")
        }
        assert {
            "source_text",
            "source_text_sha256",
            "source_text_truncated",
        } <= columns
        constraints = {
            str(row["name"])
            for row in inspector.get_check_constraints("tracked_case_updates")
        }
        assert "ck_tracked_case_update_source_text_hash" in constraints
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                MIGRATION_HEAD
            )
    finally:
        engine.dispose()

    command.upgrade(config, CURRENT_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            health = build_index_health_report(connection)
            assert health["status"] == "ok", health
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                CURRENT_HEAD
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        columns = {
            str(column["name"])
            for column in inspect(engine).get_columns("tracked_case_updates")
        }
        assert "source_text" not in columns
    finally:
        engine.dispose()

    command.upgrade(config, CURRENT_HEAD)


def test_case_tracking_source_text_downgrade_refuses_retained_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _module()

    class ScalarResult:
        @staticmethod
        def scalar_one() -> int:
            return 1

    class FakeConnection:
        dialect = type("Dialect", (), {"name": "sqlite"})()

        @staticmethod
        def execute(_statement: object) -> ScalarResult:
            return ScalarResult()

    class FakeOperations:
        @staticmethod
        def get_bind() -> FakeConnection:
            return FakeConnection()

    monkeypatch.setattr(migration, "op", FakeOperations())
    with pytest.raises(RuntimeError, match="provider source text exists"):
        migration.downgrade()
