"""Migration proof for IPLF-052 journal/watch evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260824_0002"
MIGRATION_HEAD = "20260824_0003"
TABLES = {
    "ip_journal_publications",
    "ip_journal_ingestion_runs",
    "ip_watch_profiles",
    "ip_watch_hits",
    "ip_watch_handoffs",
}


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str):
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return database_url, config


def test_journal_watch_migration_round_trips_when_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "watch-empty.db")
    command.upgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert TABLES.issubset(schema.get_table_names())
        assert "fk_ip_watch_hit_publication_company" in {
            row["name"] for row in schema.get_foreign_keys("ip_watch_hits")
        }
        assert "fk_ip_watch_handoff_hit_company" in {
            row["name"] for row in schema.get_foreign_keys("ip_watch_handoffs")
        }
        with engine.connect() as connection:
            triggers = set(connection.scalars(text(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                "AND tbl_name = 'ip_journal_publications'"
            )))
        assert triggers == {
            "trg_ip_journal_publications_immutable_update",
            "trg_ip_journal_publications_immutable_delete",
        }
    finally:
        engine.dispose()
    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_journal_evidence_blocks_mutation_and_destructive_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "watch-retained.db")
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(text(
                "INSERT INTO ip_journal_publications ("
                "id, company_id, provider_key, journal_number, journal_date, "
                "publication_kind, application_number, office, jurisdiction, "
                "class_numbers_json, goods_services_json, publication_scope_json, "
                "source_url, source_status, parser_version, attribution_json, "
                "raw_evidence_json, source_fingerprint, ingestion_delay_hours, created_at"
                ") VALUES ('publication-1', 'company-1', 'manual', '2248', '2026-08-21', "
                "'advertisement', 'TM-1', 'IP India', 'IN', '[9]', '{}', '{}', "
                "'https://ipindia.gov.in/journal/2248', 'available', 'manual-v1', '{}', "
                "'{}', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                "0, CURRENT_TIMESTAMP)"
            ))
        with engine.begin() as connection, pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text(
                "UPDATE ip_journal_publications SET journal_number = 'rewritten' "
                "WHERE id = 'publication-1'"
            ))
    finally:
        engine.dispose()
    with pytest.raises(RuntimeError, match="immutable journal/watch evidence"):
        command.downgrade(config, PREVIOUS_HEAD)
