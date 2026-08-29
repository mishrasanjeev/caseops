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

PREVIOUS_HEAD = "20260829_0001"
MIGRATION_HEAD = "20260830_0001"
TABLE = "ai_feedback_items"


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
        / "20260830_0001_ai_feedback_queue.py"
    )
    spec = importlib.util.spec_from_file_location("ai_feedback_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ai_feedback_migration_round_trip_and_index_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ai-feedback.db').as_posix()}"
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
            "submission_key",
            "surface",
            "target_type",
            "target_id",
            "target_version",
            "feedback_type",
            "priority",
            "status",
            "review_notes",
            "updated_at",
        } <= columns
        assert database_foreign_key_gaps(inspector, table_names={TABLE}) == ()
        index_names = {str(index["name"]) for index in inspector.get_indexes(TABLE)}
        assert {
            "ix_ai_feedback_company_status_created",
            "ix_ai_feedback_company_surface_created",
            "ix_ai_feedback_company_category_status",
        } <= index_names
        with engine.connect() as connection:
            current_head = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
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


def test_ai_feedback_downgrade_refuses_retained_evidence(monkeypatch) -> None:
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
    with pytest.raises(RuntimeError, match="retained AI feedback evidence"):
        migration.downgrade()
    assert dropped == []
