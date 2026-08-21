"""Migration proof for the complete UJ-58 deadline-incident lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260821_0002"
MIGRATION_HEAD = "20260821_0003"
PARENT = "ip_deadline_incidents"
CHILD_TABLES = {
    "ip_deadline_incident_impacts",
    "ip_deadline_incident_actions",
    "ip_deadline_incident_notification_decisions",
    "ip_incident_kill_switches",
}
PARENT_COLUMNS = {
    "evidence_snapshot_json",
    "preservation_manifest_sha256",
    "defect_scope",
    "defect_fingerprint_sha256",
    "impact_scan_completed_at",
    "impact_scan_completed_by_membership_id",
    "root_cause",
    "preventive_action",
    "prevention_verified_at",
    "resolution_evidence_reference",
    "resolved_at",
    "resolved_by_membership_id",
    "version",
    "created_by_membership_id",
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


def test_incident_lifecycle_migration_is_additive_indexed_and_reversible_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'incident-lifecycle.db').as_posix()}"
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
        before_columns = {column["name"] for column in before.get_columns(PARENT)}
        assert CHILD_TABLES.isdisjoint(before_tables)
        assert PARENT_COLUMNS.isdisjoint(before_columns)
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables | CHILD_TABLES
        assert {column["name"] for column in schema.get_columns(PARENT)} == (
            before_columns | PARENT_COLUMNS
        )
        parent_fks = {item["name"]: item for item in schema.get_foreign_keys(PARENT)}
        assert parent_fks["fk_ip_deadline_incident_docket_company"]["options"].get(
            "ondelete"
        ) == "RESTRICT"
        for table in CHILD_TABLES:
            indexes = {
                column
                for index in schema.get_indexes(table)
                for column in index["column_names"][:1]
            }
            for foreign_key in schema.get_foreign_keys(table):
                assert foreign_key["constrained_columns"][0] in indexes
                if "incident_id" in foreign_key["constrained_columns"]:
                    assert foreign_key["options"].get("ondelete") == "RESTRICT"
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        downgraded = inspect(engine)
        assert set(downgraded.get_table_names()) == before_tables
        assert {column["name"] for column in downgraded.get_columns(PARENT)} == before_columns
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
