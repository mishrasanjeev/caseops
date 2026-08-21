"""Migration proof for IPLF-030B personal views and export jobs."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260821_0003"
MIGRATION_HEAD = "20260821_0005"
TABLES = {"ip_portfolio_saved_views", "ip_portfolio_export_jobs"}


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


def test_portfolio_workflow_migration_is_additive_and_reversible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'portfolio-workflow.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        before_tables = set(inspect(engine).get_table_names())
        assert TABLES.isdisjoint(before_tables)
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables | TABLES
        view_uniques = {
            tuple(item["column_names"])
            for item in schema.get_unique_constraints("ip_portfolio_saved_views")
        }
        assert ("company_id", "membership_id", "name") in view_uniques
        view_indexes = {
            tuple(item["column_names"])
            for item in schema.get_indexes("ip_portfolio_saved_views")
        }
        assert ("membership_id",) in view_indexes
        assert ("team_id",) in view_indexes
        export_indexes = {
            tuple(item["column_names"])
            for item in schema.get_indexes("ip_portfolio_export_jobs")
        }
        assert ("requested_by_membership_id",) in export_indexes
        import_indexes = {
            tuple(item["column_names"])
            for item in schema.get_indexes("ip_import_rows")
        }
        assert ("reconciled_target_docket_id",) in import_indexes
        export_checks = " ".join(
            str(item["sqltext"])
            for item in schema.get_check_constraints("ip_portfolio_export_jobs")
        )
        assert "50000" in export_checks
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert set(inspect(engine).get_table_names()) == before_tables
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
