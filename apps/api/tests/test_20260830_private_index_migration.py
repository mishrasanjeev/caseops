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

PREVIOUS_HEAD = "20260830_0001"
MIGRATION_HEAD = "20260830_0002"
TABLES = {
    "private_index_generations",
    "private_index_projections",
    "private_index_projection_scopes",
    "private_projection_events",
    "private_saved_output_access",
}


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
        / "20260830_0002_private_index_foundation.py"
    )
    spec = importlib.util.spec_from_file_location("private_index_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_private_index_migration_round_trip_and_index_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'private-index.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _config()
    command.upgrade(config, PREVIOUS_HEAD)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        assert database_foreign_key_gaps(inspector, table_names=TABLES) == ()
        generation_indexes = {
            str(index["name"])
            for index in inspector.get_indexes("private_index_generations")
        }
        assert "uq_private_index_generation_one_active" in generation_indexes
        projection_indexes = {
            str(index["name"])
            for index in inspector.get_indexes("private_index_projections")
        }
        assert {
            "ix_private_projection_prefilter",
            "ix_private_projection_generation_policy",
        } <= projection_indexes
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == MIGRATION_HEAD
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert not TABLES.intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)


def test_private_index_downgrade_refuses_retained_security_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    with pytest.raises(RuntimeError, match="private projection"):
        migration.downgrade()
    assert dropped == []
