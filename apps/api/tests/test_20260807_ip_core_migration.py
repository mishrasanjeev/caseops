from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

IP_CORE_TABLES = {
    "ip_assets",
    "trademark_applications",
    "trademark_application_scopes",
    "trademark_representations",
    "ip_proceedings",
    "ip_identifiers",
    "ip_parties_and_roles",
    "ip_relationships",
}


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        client_uniques = {
            str(constraint["name"])
            for constraint in inspector.get_unique_constraints("clients")
            if constraint.get("name")
        }
        identifier_indexes = {
            str(index["name"])
            for index in inspector.get_indexes("ip_identifiers")
            if index.get("name")
        } if "ip_identifiers" in table_names else set()
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return table_names, client_uniques, identifier_indexes, head
    finally:
        engine.dispose()


def test_ip_core_migration_upgrades_downgrades_and_reupgrades(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "ip-core-records.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260804_0004")
    tables, client_uniques, _, head = _schema(database_url)
    assert not IP_CORE_TABLES.intersection(tables)
    assert "uq_clients_id_company" not in client_uniques
    assert head == "20260804_0004"

    command.upgrade(config, "head")
    tables, client_uniques, identifier_indexes, head = _schema(database_url)
    assert IP_CORE_TABLES.issubset(tables)
    assert "uq_clients_id_company" in client_uniques
    assert "ix_ip_identifiers_company_search" in identifier_indexes
    assert head == "20260807_0001"

    command.downgrade(config, "20260804_0004")
    tables, client_uniques, _, head = _schema(database_url)
    assert not IP_CORE_TABLES.intersection(tables)
    assert "uq_clients_id_company" not in client_uniques
    assert head == "20260804_0004"

    command.upgrade(config, "head")
    tables, client_uniques, identifier_indexes, head = _schema(database_url)
    assert IP_CORE_TABLES.issubset(tables)
    assert "uq_clients_id_company" in client_uniques
    assert "ix_ip_identifiers_company_search" in identifier_indexes
    assert head == "20260807_0001"

    get_settings.cache_clear()
    clear_engine_cache()
