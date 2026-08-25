"""IPLF-055 migration expand, empty rollback, and restore-forward proof."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260825_0001"
MIGRATION_HEAD = "20260825_0002"
NEW_TABLES = {"report_artifacts", "portal_publications", "portal_publication_targets"}


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


def test_ip_client_portal_migration_empty_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-client-portal.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        before_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables | NEW_TABLES
        grant_columns = {column["name"] for column in schema.get_columns("matter_portal_grants")}
        assert {"company_id", "ip_docket_record_id", "expires_at", "row_version"} <= grant_columns
        instruction_columns = {
            column["name"] for column in schema.get_columns("ip_client_instructions")
        }
        assert {
            "instruction_thread_key",
            "instruction_kind",
            "source_portal_user_id",
            "source_portal_grant_id",
            "portal_publication_id",
        } <= instruction_columns
        publication_indexes = {
            tuple(index["column_names"])
            for index in schema.get_indexes("portal_publications")
        }
        assert {
            ("report_artifact_id",),
            ("document_version_id",),
            ("revoked_by_membership_id",),
        } <= publication_indexes
        instruction_indexes = {
            tuple(index["column_names"])
            for index in schema.get_indexes("ip_client_instructions")
        }
        assert ("renewal_term_id",) in instruction_indexes
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables
        assert "ip_docket_record_id" not in {
            column["name"] for column in schema.get_columns("matter_portal_grants")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
