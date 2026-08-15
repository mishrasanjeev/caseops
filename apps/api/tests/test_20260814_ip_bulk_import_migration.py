"""IPLF-032A migration: additive expand, empty rollback, index inventory."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache, get_engine

PREVIOUS_HEAD = "20260814_0001"
MIGRATION_HEAD = "20260814_0002"
NEW_TABLES = {"bulk_import_jobs", "ip_import_rows"}
EXPECTED_INDEXES = {
    ("bulk_import_jobs", "ix_bulk_import_jobs_company_id"),
    ("bulk_import_jobs", "ix_bulk_import_jobs_created_by_membership_id"),
    ("bulk_import_jobs", "ix_bulk_import_jobs_company_domain"),
    ("ip_import_rows", "ix_ip_import_rows_company_id"),
    ("ip_import_rows", "ix_ip_import_rows_job_id"),
    ("ip_import_rows", "ix_ip_import_rows_created_docket_id"),
    ("ip_import_rows", "ix_ip_import_rows_job_commit"),
}
LEGACY_IMPORT_TABLES = {"matter_bulk_import_jobs", "employee_bulk_import_jobs"}
EXPECTED_TENANT_FOREIGN_KEYS = {
    "fk_bulk_import_job_creator_company": (
        "bulk_import_jobs",
        ["created_by_membership_id", "company_id"],
        "company_memberships",
        ["id", "company_id"],
    ),
    "fk_ip_import_row_created_docket_company": (
        "ip_import_rows",
        ["created_docket_id", "company_id"],
        "ip_docket_records",
        ["id", "company_id"],
    ),
}


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


def test_ip_bulk_import_expand_is_additive_and_rollback_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-import.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, PREVIOUS_HEAD)
    engine = get_engine(database_url)
    before = set(inspect(engine).get_table_names())
    assert NEW_TABLES.isdisjoint(before)
    # The legacy domain-specific import owners already exist and must survive.
    assert LEGACY_IMPORT_TABLES <= before
    engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    engine = get_engine(database_url)
    inspector = inspect(engine)
    after = set(inspector.get_table_names())
    assert NEW_TABLES <= after
    # ARCH-OPS-23: no IP-specific job table is introduced.
    assert "ip_import_jobs" not in after
    # Nothing pre-existing was dropped or renamed by the expand.
    assert before <= after
    assert LEGACY_IMPORT_TABLES <= after

    present = {
        (table, index["name"])
        for table in NEW_TABLES
        for index in inspector.get_indexes(table)
    }
    assert EXPECTED_INDEXES <= present

    foreign_keys = {
        foreign_key["name"]: (
            table,
            foreign_key["constrained_columns"],
            foreign_key["referred_table"],
            foreign_key["referred_columns"],
        )
        for table in NEW_TABLES
        for foreign_key in inspector.get_foreign_keys(table)
        if foreign_key.get("name")
    }
    assert foreign_keys.keys() >= EXPECTED_TENANT_FOREIGN_KEYS.keys()
    for name, expected in EXPECTED_TENANT_FOREIGN_KEYS.items():
        assert foreign_keys[name] == expected

    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM bulk_import_jobs")) == 0
        assert connection.scalar(text("SELECT count(*) FROM ip_import_rows")) == 0
        # The legacy Matter import owner is untouched by the expand.
        assert (
            connection.scalar(text("SELECT count(*) FROM matter_bulk_import_jobs")) == 0
        )
    engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == PREVIOUS_HEAD
    downgraded = create_engine(database_url, future=True)
    try:
        remaining = set(inspect(downgraded).get_table_names())
        assert NEW_TABLES.isdisjoint(remaining)
        # Rollback removes only what this revision added.
        assert LEGACY_IMPORT_TABLES <= remaining
        assert before <= remaining
    finally:
        downgraded.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD

    get_settings.cache_clear()
    clear_engine_cache()
