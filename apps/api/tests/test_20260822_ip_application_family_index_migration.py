"""Migration proof for the IPLF-033B mark-family query index."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260821_0005"
MIGRATION_HEAD = "20260822_0001"
INDEX_NAME = "ix_tm_applications_company_asset"


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


def _index_columns(database_url: str) -> dict[str, tuple[str, ...]]:
    engine = create_engine(database_url, future=True)
    try:
        return {
            str(index["name"]): tuple(index["column_names"])
            for index in inspect(engine).get_indexes("trademark_applications")
        }
    finally:
        engine.dispose()


def test_application_family_index_is_additive_and_reversible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'family-index.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    assert INDEX_NAME not in _index_columns(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    assert _index_columns(database_url)[INDEX_NAME] == ("company_id", "asset_id")
    assert _head(database_url) == MIGRATION_HEAD

    command.downgrade(config, PREVIOUS_HEAD)
    assert INDEX_NAME not in _index_columns(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    assert _index_columns(database_url)[INDEX_NAME] == ("company_id", "asset_id")
    get_settings.cache_clear()
    clear_engine_cache()
