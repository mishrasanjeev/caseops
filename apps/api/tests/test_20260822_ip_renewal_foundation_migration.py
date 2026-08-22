"""Migration proof for the IPLF-037A renewal foundation."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260822_0001"
MIGRATION_HEAD = "20260822_0002"
TABLES = {"ip_renewal_terms", "ip_client_instructions"}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _tables(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _foreign_key_targets(database_url: str, table_name: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return {
            str(foreign_key["referred_table"])
            for foreign_key in inspect(engine).get_foreign_keys(table_name)
        }
    finally:
        engine.dispose()


def test_ip_renewal_foundation_is_additive_tenant_scoped_and_reversible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'renewals.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    assert TABLES.isdisjoint(_tables(database_url))

    command.upgrade(config, MIGRATION_HEAD)
    assert TABLES.issubset(_tables(database_url))
    assert _head(database_url) == MIGRATION_HEAD
    assert {
        "ip_docket_records",
        "ip_docket_events",
        "ip_deadlines",
        "ip_cost_items",
        "ip_documents",
        "company_memberships",
    }.issubset(_foreign_key_targets(database_url, "ip_renewal_terms"))
    assert {
        "ip_docket_records",
        "ip_renewal_terms",
        "ip_docket_events",
        "communications",
        "company_memberships",
    }.issubset(_foreign_key_targets(database_url, "ip_client_instructions"))

    command.downgrade(config, PREVIOUS_HEAD)
    assert TABLES.isdisjoint(_tables(database_url))

    command.upgrade(config, MIGRATION_HEAD)
    assert TABLES.issubset(_tables(database_url))
    get_settings.cache_clear()
    clear_engine_cache()
