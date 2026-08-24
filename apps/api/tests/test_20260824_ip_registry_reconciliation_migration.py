"""Migration proof for IPLF-051 registry reconciliation evidence."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260824_0001"
MIGRATION_HEAD = "20260824_0002"
TABLES = {
    "ip_registry_links",
    "ip_registry_sync_attempts",
    "ip_registry_snapshots",
    "ip_registry_diffs",
    "ip_tracked_case_links",
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


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def test_registry_reconciliation_migration_round_trips_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "registry-empty.db")
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
        tracked_case_uniques = {
            tuple(row["column_names"])
            for row in schema.get_unique_constraints("tracked_cases")
        }
        assert ("id", "company_id") in tracked_case_uniques
        assert "change_kind" in {
            column["name"] for column in schema.get_columns("ip_registry_diffs")
        }
        snapshot_fk_names = {
            row["name"] for row in schema.get_foreign_keys("ip_registry_snapshots")
        }
        attempt_fk_names = {
            row["name"] for row in schema.get_foreign_keys("ip_registry_sync_attempts")
        }
        diff_fk_names = {
            row["name"] for row in schema.get_foreign_keys("ip_registry_diffs")
        }
        assert "fk_ip_registry_snapshot_supersedes_company" in snapshot_fk_names
        assert "fk_ip_registry_attempt_replay_company" in attempt_fk_names
        assert "fk_ip_registry_diff_event_company" in diff_fk_names
        snapshot_uniques = {
            tuple(row["column_names"])
            for row in schema.get_unique_constraints("ip_registry_snapshots")
        }
        assert ("company_id", "supersedes_snapshot_id") in snapshot_uniques
        with engine.connect() as connection:
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master WHERE type = 'trigger' "
                        "AND tbl_name = 'ip_registry_snapshots'"
                    )
                )
            )
        assert triggers == {
            "trg_ip_registry_snapshots_immutable_update",
            "trg_ip_registry_snapshots_immutable_delete",
        }
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert TABLES.isdisjoint(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD


def test_registry_snapshot_blocks_mutation_and_destructive_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "registry-retained.db")
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(
                text(
                    "INSERT INTO ip_registry_links ("
                    "id, company_id, docket_id, application_id, provider_key, office, "
                    "jurisdiction, identifier_kind, raw_identifier, normalized_identifier, "
                    "source_url, match_status, match_confidence, match_evidence_json, "
                    "accepted_state_json, capability_version, freshness_status, version, "
                    "created_by_membership_id, created_at, updated_at) VALUES ("
                    "'link-1', 'company-1', 'docket-1', 'application-1', "
                    "'ipindia-registry', 'IP India', 'IN', 'application', 'TM-1', 'tm1', "
                    "'https://ipindia.gov.in/registry/TM-1', 'confirmed', 1, '{}', '{}', "
                    "'manual-evidence-v1', 'current', 1, 'membership-1', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ip_registry_sync_attempts ("
                    "id, company_id, link_id, provider_key, operation_kind, idempotency_key, "
                    "correlation_id, status, response_class, external_call, attempts, "
                    "cost_minor, currency, metadata_json, requested_by_membership_id, "
                    "started_at, completed_at, created_at) VALUES ("
                    "'attempt-1', 'company-1', 'link-1', 'ipindia-registry', "
                    "'manual_snapshot', 'registry-migration-fixture', "
                    "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                    "'succeeded', 'success', 0, 1, 0, 'INR', '{}', 'membership-1', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ip_registry_snapshots ("
                    "id, company_id, link_id, attempt_id, source_url, source_retrieved_at, "
                    "parser_version, schema_version, attribution_json, raw_sha256, "
                    "normalized_sha256, raw_json, normalized_json, created_at) VALUES ("
                    "'snapshot-1', 'company-1', 'link-1', 'attempt-1', "
                    "'https://ipindia.gov.in/registry/TM-1', CURRENT_TIMESTAMP, "
                    "'migration-fixture-v1', 1, '{}', "
                    "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', "
                    "'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc', "
                    "'{}', '{}', CURRENT_TIMESTAMP)"
                )
            )
        with engine.begin() as connection, pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE ip_registry_snapshots SET parser_version = 'rewritten' "
                    "WHERE id = 'snapshot-1'"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="immutable IP registry or court-reference evidence"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
