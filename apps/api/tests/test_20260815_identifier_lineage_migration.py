"""Additive migration proof for duplicate-identifier forward lineage."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260815_0004"
MIGRATION_HEAD = "20260815_0005"
TABLE = "ip_identifiers"
COLUMN = "superseded_by_identifier_id"
INDEX = "ix_ip_identifiers_superseded_by_identifier_id"
FOREIGN_KEY = "fk_ip_identifier_superseded_by_company"
BACKWARD_FOREIGN_KEY = "fk_ip_identifier_supersedes_company"
CHECK = "ck_ip_identifier_superseded_by_not_self"


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


def test_identifier_lineage_migration_is_additive_tenant_safe_and_reversible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'identifier-lineage.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        before = inspect(engine)
        before_tables = set(before.get_table_names())
        before_columns = {column["name"] for column in before.get_columns(TABLE)}
        assert COLUMN not in before_columns
        assert _head(database_url) == PREVIOUS_HEAD
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables
        assert {column["name"] for column in schema.get_columns(TABLE)} == (
            before_columns | {COLUMN}
        )
        assert INDEX in {index["name"] for index in schema.get_indexes(TABLE)}

        foreign_key = next(
            item for item in schema.get_foreign_keys(TABLE) if item["name"] == FOREIGN_KEY
        )
        assert foreign_key["constrained_columns"] == [COLUMN, "company_id"]
        assert foreign_key["referred_table"] == TABLE
        assert foreign_key["referred_columns"] == ["id", "company_id"]
        assert foreign_key["options"].get("ondelete") == "RESTRICT"
        backward_foreign_key = next(
            item
            for item in schema.get_foreign_keys(TABLE)
            if item["name"] == BACKWARD_FOREIGN_KEY
        )
        assert backward_foreign_key["constrained_columns"] == [
            "supersedes_identifier_id",
            "company_id",
        ]
        assert backward_foreign_key["referred_table"] == TABLE
        assert backward_foreign_key["referred_columns"] == ["id", "company_id"]
        assert backward_foreign_key["options"].get("ondelete") == "RESTRICT"
        assert CHECK in {
            item["name"]
            for item in schema.get_check_constraints(TABLE)
            if item.get("name")
        }
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        downgraded = inspect(engine)
        assert set(downgraded.get_table_names()) == before_tables
        assert {column["name"] for column in downgraded.get_columns(TABLE)} == before_columns
        assert INDEX not in {index["name"] for index in downgraded.get_indexes(TABLE)}
        assert _head(database_url) == PREVIOUS_HEAD
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()
