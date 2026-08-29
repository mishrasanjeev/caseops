from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.index_coverage import database_foreign_key_gaps

PREVIOUS_HEAD = "20260828_0002"
MIGRATION_HEAD = "20260829_0001"
TABLE = "assistant_action_previews"


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
        / "20260829_0001_assistant_action_boundary.py"
    )
    spec = importlib.util.spec_from_file_location("assistant_action_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_assistant_action_migration_round_trip_and_index_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'assistant-actions.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert TABLE in inspector.get_table_names()
        columns = {str(column["name"]) for column in inspector.get_columns(TABLE)}
        assert {
            "payload_sha256",
            "preview_token_sha256",
            "session_version",
            "policy_version",
            "status",
            "result_id",
            "confirmed_at",
        } <= columns
        assert database_foreign_key_gaps(inspector, table_names={TABLE}) == ()
        with engine.connect() as connection:
            current_head = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert current_head == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert TABLE not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)


def test_assistant_action_downgrade_refuses_retained_evidence(monkeypatch) -> None:
    migration = _module()
    dropped: list[str] = []

    class FakeDialect:
        name = "sqlite"

    class FakeConnection:
        dialect = FakeDialect()

        @staticmethod
        def scalar(_statement):
            return 1

    class FakeOperations:
        @staticmethod
        def get_bind():
            return FakeConnection()

        @staticmethod
        def drop_table(table_name: str) -> None:
            dropped.append(table_name)

    monkeypatch.setattr(migration, "op", FakeOperations())
    with pytest.raises(RuntimeError, match="retained preview or confirmation evidence"):
        migration.downgrade()
    assert dropped == []
