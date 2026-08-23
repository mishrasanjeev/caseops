"""Migration proof for the IPLF-040B opposition workspace."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260823_0001"
MIGRATION_HEAD = "20260823_0002"


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


def _party_columns(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return {
            str(row["name"])
            for row in inspect(engine).get_columns("ip_parties_and_roles")
        }
    finally:
        engine.dispose()


def test_workspace_migration_is_reversible_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "workspace-empty.db")
    command.upgrade(config, PREVIOUS_HEAD)
    assert "proceeding_id" not in _party_columns(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    assert "proceeding_id" in _party_columns(database_url)
    engine = create_engine(database_url, future=True)
    try:
        inspector = inspect(engine)
        assert "ix_ip_parties_company_proceeding" in {
            row["name"] for row in inspector.get_indexes("ip_parties_and_roles")
        }
        foreign_keys = inspector.get_foreign_keys("ip_parties_and_roles")
        assert any(
            row["referred_table"] == "ip_proceedings"
            and row["constrained_columns"] == ["proceeding_id", "company_id"]
            for row in foreign_keys
        )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    assert "proceeding_id" not in _party_columns(database_url)
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            trigger_names = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND tbl_name = 'ip_docket_events'"
                    )
                )
            )
        assert {
            "trg_ip_docket_events_append_only_update",
            "trg_ip_docket_events_append_only_delete",
        }.issubset(trigger_names)
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)
    get_settings.cache_clear()
    clear_engine_cache()


def test_workspace_evidence_is_append_only_and_blocks_destructive_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "workspace-retained.db")
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(
                text(
                    "INSERT INTO ip_parties_and_roles ("
                    "id, company_id, docket_id, proceeding_id, party_name, role_kind, "
                    "effective_from, source, created_at"
                    ") VALUES ("
                    "'party-1', 'company-1', 'docket-1', 'proceeding-1', "
                    "'Retained Opponent', 'opponent', '2026-08-23', 'notice', "
                    "CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO ip_docket_events ("
                    "id, company_id, docket_id, sequence, proceeding_id, event_kind, "
                    "source, effective_at, entered_at, responsible_membership_id, "
                    "entered_by_membership_id, reason, evidence_refs_json, document_refs_json, "
                    "resulting_deadline_refs_json, candidate_status, payload_json, created_at"
                    ") VALUES ("
                    "'profile-1', 'company-1', 'docket-1', 1, 'proceeding-1', "
                    "'opposition_profile', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "'membership-1', 'membership-1', 'Retained workspace evidence', "
                    "'[]', '[]', '[]', 'confirmed', "
                    "'{\"opposition_profile_revision\": true}', CURRENT_TIMESTAMP)"
                )
            )
        with engine.begin() as connection, pytest.raises(DBAPIError, match="append-only"):
            connection.execute(
                text(
                    "UPDATE ip_docket_events SET reason = 'changed' "
                    "WHERE id = 'profile-1'"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="retained opposition workspace evidence"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
