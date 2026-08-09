from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

IP_DOCUMENT_TABLES = {
    "ip_document_taxonomy_entries",
    "ip_document_taxonomy_aliases",
    "ip_documents",
    "ip_document_versions",
    "ip_document_links",
}


def _alembic_config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _schema(database_url: str) -> tuple[set[str], set[str], set[str], str]:
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        link_checks = (
            {
                str(constraint["name"])
                for constraint in inspector.get_check_constraints("ip_document_links")
                if constraint.get("name")
            }
            if "ip_document_links" in tables
            else set()
        )
        version_uniques = (
            {
                str(constraint["name"])
                for constraint in inspector.get_unique_constraints("ip_document_versions")
                if constraint.get("name")
            }
            if "ip_document_versions" in tables
            else set()
        )
        with engine.connect() as connection:
            head = str(
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            )
        return tables, link_checks, version_uniques, head
    finally:
        engine.dispose()


def test_ip_document_foundation_migration_upgrade_downgrade_reupgrade(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "ip-document-foundation.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _alembic_config(project_root)

    command.upgrade(config, "20260807_0005")
    tables, _, _, head = _schema(database_url)
    assert not IP_DOCUMENT_TABLES.intersection(tables)
    assert head == "20260807_0005"

    command.upgrade(config, "20260809_0001")
    tables, link_checks, version_uniques, head = _schema(database_url)
    assert IP_DOCUMENT_TABLES.issubset(tables)
    assert "ck_ip_document_link_exactly_one_target" in link_checks
    assert "ck_ip_document_link_target_consistent" in link_checks
    assert {
        "uq_ip_document_version_number",
        "uq_ip_document_version_storage_key",
        "uq_ip_document_version_id_company_document",
    }.issubset(version_uniques)
    assert head == "20260809_0001"

    command.downgrade(config, "20260807_0005")
    tables, _, _, head = _schema(database_url)
    assert not IP_DOCUMENT_TABLES.intersection(tables)
    assert head == "20260807_0005"

    command.upgrade(config, "20260809_0001")
    tables, link_checks, version_uniques, head = _schema(database_url)
    assert IP_DOCUMENT_TABLES.issubset(tables)
    assert "ck_ip_document_link_exactly_one_target" in link_checks
    assert "ck_ip_document_link_target_consistent" in link_checks
    assert "uq_ip_document_version_number" in version_uniques
    assert head == "20260809_0001"

    get_settings.cache_clear()
    clear_engine_cache()
