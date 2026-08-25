"""IPLF-059A migration expand, rollback, and restore-forward proof."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260825_0005"
MIGRATION_HEAD = "20260825_0006"
TABLE = "ip_foreign_associate_instructions"


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


def test_foreign_associate_migration_empty_round_trip_and_schema_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-associates.db').as_posix()}"
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
            "instruction_thread_key",
            "instruction_version",
            "row_version",
            "source_client_instruction_id",
            "target_jurisdiction",
            "outside_counsel_id",
            "assignment_id",
            "selected_document_refs_json",
            "privileged_document_refs_json",
            "estimate_cost_item_id",
            "dispatch_communication_id",
            "acknowledged_at",
            "filing_identifier",
            "filing_evidence_refs_json",
            "actual_cost_item_id",
            "spend_record_id",
            "status",
        } <= {column["name"] for column in schema.get_columns(TABLE)}
        assert "foreign_associate_instruction_id" in {
            column["name"] for column in schema.get_columns("ip_docket_events")
        }
        indexes = {index["name"] for index in schema.get_indexes(TABLE)}
        assert "ix_ip_foreign_associate_company_docket_status" in indexes
        assert "ix_ip_foreign_associate_company_response_due" in indexes
        foreign_keys = {
            foreign_key["name"]: tuple(foreign_key["constrained_columns"])
            for foreign_key in schema.get_foreign_keys(TABLE)
        }
        assert foreign_keys["fk_ip_foreign_associate_docket_company"] == (
            "docket_id",
            "company_id",
        )
        assert foreign_keys["fk_ip_foreign_associate_client_instruction_company"] == (
            "source_client_instruction_id",
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
        assert "foreign_associate_instruction_id" not in {
            column["name"] for column in schema.get_columns("ip_docket_events")
        }
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()


def test_foreign_associate_migration_refuses_populated_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-associates-populated.db').as_posix()}"
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
                        id, company_id, docket_id, instruction_thread_key,
                        instruction_version, row_version, client_authority_reference,
                        target_jurisdiction, outside_counsel_id,
                        responsible_membership_id, scope_json,
                        selected_document_refs_json, privileged_document_refs_json,
                        estimate_cost_item_id, estimate_terms_json,
                        budget_policy_reference, filing_evidence_refs_json, status,
                        created_by_membership_id, updated_by_membership_id,
                        created_at, updated_at
                    ) VALUES (
                        'instruction-1', 'company-1', 'docket-1', 'thread-1',
                        1, 1, 'client-email-1', 'US', 'counsel-1', 'member-1',
                        '{{"source_kind":"application"}}', '["doc-1"]', '[]',
                        'cost-1', '{{}}', 'budget-policy-1', '[]', 'draft',
                        'member-1', 'member-1',
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
