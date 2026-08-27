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
from caseops_api.db.session import clear_engine_cache
from caseops_api.scripts.check_database_indexes import build_index_health_report

PREVIOUS_HEAD = "20260826_0002"
MIGRATION_HEAD = "20260827_0001"
HOT_INDEX = "ix_ip_docket_records_company_active_updated"


def _config() -> Config:
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _migration_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260827_0001_complete_foreign_key_indexes.py"
    )
    spec = importlib.util.spec_from_file_location("complete_fk_indexes_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _gaps(database_url: str) -> tuple[tuple[str, tuple[str, ...]], ...]:
    engine = create_engine(database_url, future=True)
    try:
        return tuple(
            (gap.table_name, gap.columns)
            for gap in database_foreign_key_gaps(inspect(engine))
        )
    finally:
        engine.dispose()


def _ip_docket_indexes(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return {
            str(index["name"])
            for index in inspect(engine).get_indexes("ip_docket_records")
        }
    finally:
        engine.dispose()


def _health_failures(health: dict[str, object]) -> dict[str, object]:
    failures: dict[str, object] = {}
    for key, value in health.items():
        if (
            key in {"status", "schema_revisions", "sequential_scan_warnings"}
            or not isinstance(value, list)
            or not value
        ):
            continue
        if key == "missing_declared_indexes":
            failures[key] = [
                f"{item['table_name']}.{item['index_name']}" for item in value
            ]
        else:
            failures[key] = {"count": len(value), "sample": value[:10]}
    return failures


def test_complete_foreign_key_indexes_migration_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'complete-indexes.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config()

    command.upgrade(config, PREVIOUS_HEAD)
    assert _gaps(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    assert _gaps(database_url) == ()
    assert HOT_INDEX in _ip_docket_indexes(database_url)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            health = build_index_health_report(connection)
    finally:
        engine.dispose()
    assert health["status"] == "ok", _health_failures(health)

    command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == PREVIOUS_HEAD
    assert _gaps(database_url)
    assert HOT_INDEX not in _ip_docket_indexes(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    assert _gaps(database_url) == ()
    assert HOT_INDEX in _ip_docket_indexes(database_url)


def test_postgres_downgrade_keeps_index_drops_in_migration_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = _migration_module()
    statements: list[str] = []

    class FakePreparer:
        @staticmethod
        def quote(identifier: str) -> str:
            return f'"{identifier}"'

    class FakeConnection:
        dialect = type(
            "Dialect",
            (),
            {"name": "postgresql", "identifier_preparer": FakePreparer()},
        )()

    class FakeInspector:
        @staticmethod
        def get_table_names() -> list[str]:
            return ["ip_docket_records"]

        @staticmethod
        def get_foreign_keys(_table_name: str) -> list[dict[str, object]]:
            return []

        @staticmethod
        def get_indexes(_table_name: str) -> list[dict[str, str]]:
            return [{"name": HOT_INDEX}]

    class FakeOperations:
        @staticmethod
        def get_bind() -> FakeConnection:
            return FakeConnection()

        @staticmethod
        def execute(statement: object) -> None:
            statements.append(str(statement))

        @staticmethod
        def get_context() -> None:
            raise AssertionError("PostgreSQL downgrade must not enter autocommit mode")

    monkeypatch.setattr(migration, "op", FakeOperations())
    monkeypatch.setattr(migration.sa, "inspect", lambda _connection: FakeInspector())

    migration.downgrade()

    assert statements == [
        "SET LOCAL lock_timeout = '5s'",
        f'DROP INDEX IF EXISTS "{HOT_INDEX}"',
    ]
