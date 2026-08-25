"""IPLF-058A migration expand, rollback, and restore-forward proof."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260825_0004"
MIGRATION_HEAD = "20260825_0005"
TABLE = "ip_post_registration_recordals"


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


def test_recordal_migration_empty_round_trip_and_schema_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-recordals.db').as_posix()}"
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
        assert set(schema.get_table_names()) == before_tables | {TABLE}
        assert {
            "docket_id",
            "recordal_type",
            "legal_basis",
            "form_code",
            "parties_json",
            "executed_on",
            "effective_on",
            "affected_registration_refs_json",
            "scope_json",
            "supporting_instrument_refs_json",
            "registry_snapshot_id",
            "status",
            "version",
        } <= {column["name"] for column in schema.get_columns(TABLE)}
        title_columns = {
            column["name"] for column in schema.get_columns("ip_title_interests")
        }
        assert {
            "party_role",
            "executed_on",
            "source_recordal_id",
            "scope_json",
            "registry_recorded_on",
            "version",
            "updated_at",
        } <= title_columns
        assert "recordal_id" in {
            column["name"] for column in schema.get_columns("ip_docket_events")
        }
        indexes = {index["name"] for index in schema.get_indexes(TABLE)}
        assert "ix_ip_recordals_company_docket_status" in indexes
        assert "ix_ip_recordals_company_type_status" in indexes
        foreign_keys = {
            foreign_key["name"]: tuple(foreign_key["constrained_columns"])
            for foreign_key in schema.get_foreign_keys(TABLE)
        }
        assert foreign_keys["fk_ip_recordal_docket_company"] == (
            "docket_id",
            "company_id",
        )
        assert foreign_keys["fk_ip_recordal_registry_snapshot_company"] == (
            "registry_snapshot_id",
            "company_id",
        )
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert set(schema.get_table_names()) == before_tables
        assert "recordal_id" not in {
            column["name"] for column in schema.get_columns("ip_docket_events")
        }
        assert "source_recordal_id" not in {
            column["name"] for column in schema.get_columns("ip_title_interests")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()


def test_recordal_migration_refuses_destructive_populated_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-recordals-populated.db').as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)
    command.upgrade(config, MIGRATION_HEAD)

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"""
                    INSERT INTO {TABLE} (
                        id, company_id, docket_id, recordal_type, legal_basis,
                        form_code, parties_json, affected_registration_refs_json,
                        affected_classes_json, scope_json,
                        supporting_instrument_refs_json, fee_cost_item_refs_json,
                        filing_evidence_refs_json, acceptance_evidence_refs_json,
                        status, version, created_by_membership_id,
                        updated_by_membership_id, created_at, updated_at
                    ) VALUES (
                        'recordal-1', 'company-1', 'docket-1', 'name_change',
                        'Trade Marks Act, 1999', 'TM-P', '[]', '["TM-1"]',
                        '[]', '{{"scope_kind":"whole_right"}}', '["doc-1"]',
                        '[]', '[]', '[]', 'draft', 1, 'member-1', 'member-1',
                        '2026-08-25 06:30:00', '2026-08-25 06:30:00'
                    )
                    """
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="Restore-forward required"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
