"""Migration proof for the IPLF-040A opposition foundation."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260822_0002"
MIGRATION_HEAD = "20260823_0001"
NEW_COLUMNS = {
    "origin_kind",
    "stage_template_version",
    "source_pending_identifier_allocation",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _engine(database_url: str):
    return create_engine(database_url, future=True)


def _head(database_url: str) -> str:
    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def _columns(database_url: str) -> set[str]:
    engine = _engine(database_url)
    try:
        return {str(row["name"]) for row in inspect(engine).get_columns("ip_proceedings")}
    finally:
        engine.dispose()


def _configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str):
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / name).as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    return database_url, _config(project_root)


def test_opposition_foundation_is_constrained_append_only_and_reversible_when_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "opposition-empty.db")
    command.upgrade(config, PREVIOUS_HEAD)
    assert NEW_COLUMNS.isdisjoint(_columns(database_url))
    engine = _engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(
                text(
                    "INSERT INTO ip_proceedings ("
                    "id, company_id, docket_id, proceeding_kind, side, office, "
                    "jurisdiction, stage, version, created_at, updated_at"
                    ") VALUES ("
                    "'legacy-opponent', 'company-1', 'docket-1', 'opposition', "
                    "'opponent', 'IP India', 'IN', 'draft', 1, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert NEW_COLUMNS.issubset(_columns(database_url))
    assert _head(database_url) == MIGRATION_HEAD

    engine = _engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT stage_template_version FROM ip_proceedings "
                    "WHERE id = 'legacy-opponent'"
                )
            ) == "opposition-opponent-v1"
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
        with engine.begin() as connection, pytest.raises(DBAPIError):
            connection.execute(
                text(
                    "UPDATE ip_proceedings "
                    "SET stage_template_version = 'opposition-applicant-v1' "
                    "WHERE id = 'legacy-opponent'"
                )
            )
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    assert NEW_COLUMNS.isdisjoint(_columns(database_url))
    command.upgrade(config, MIGRATION_HEAD)
    get_settings.cache_clear()
    clear_engine_cache()


def test_opposition_event_evidence_blocks_mutation_and_destructive_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "opposition-retained.db")
    command.upgrade(config, MIGRATION_HEAD)
    engine = _engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=OFF"))
            connection.execute(
                text(
                    "INSERT INTO ip_proceedings ("
                    "id, company_id, docket_id, proceeding_kind, side, office, "
                    "jurisdiction, stage, origin_kind, stage_template_version, "
                    "source_pending_identifier_allocation, version, created_at, updated_at"
                    ") VALUES ("
                    "'proceeding-1', 'company-1', 'docket-1', 'opposition', "
                    "'applicant', 'IP India', 'IN', 'draft', 'manual_intake', "
                    "'opposition-applicant-v1', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
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
                    "'event-1', 'company-1', 'docket-1', 1, 'proceeding-1', "
                    "'lifecycle_transition', 'manual', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, "
                    "'membership-1', 'membership-1', 'Retained opposition evidence', "
                    "'[]', '[]', '[]', 'confirmed', "
                    "'{\"opposition_stage_transition\": true}', CURRENT_TIMESTAMP)"
                )
            )
        with engine.begin() as connection, pytest.raises(
            DBAPIError, match="append-only"
        ):
            connection.execute(
                text("UPDATE ip_docket_events SET reason = 'changed' WHERE id = 'event-1'")
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="retained opposition stage evidence"):
        command.downgrade(config, PREVIOUS_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()
