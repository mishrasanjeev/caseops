from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

WORKSPACE_TABLES = {
    "ip_workspace_configurations",
    "ip_workspace_test_results",
}


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        indexes = (
            {
                str(index["name"])
                for index in inspector.get_indexes("ip_workspace_test_results")
                if index.get("name")
            }
            if "ip_workspace_test_results" in tables
            else set()
        )
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return tables, indexes, head
    finally:
        engine.dispose()


def test_ip_workspace_migration_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "ip-workspace.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260807_0001")
    tables, _, head = _schema(database_url)
    assert not WORKSPACE_TABLES.intersection(tables)
    assert head == "20260807_0001"

    command.upgrade(config, "head")
    tables, indexes, head = _schema(database_url)
    assert WORKSPACE_TABLES.issubset(tables)
    assert "ix_ip_workspace_tests_company_config" in indexes
    assert head == "20260807_0002"

    command.downgrade(config, "20260807_0001")
    tables, _, head = _schema(database_url)
    assert not WORKSPACE_TABLES.intersection(tables)
    assert head == "20260807_0001"

    command.upgrade(config, "head")
    tables, indexes, head = _schema(database_url)
    assert WORKSPACE_TABLES.issubset(tables)
    assert "ix_ip_workspace_tests_company_config" in indexes
    assert head == "20260807_0002"

    get_settings.cache_clear()
    clear_engine_cache()
