"""IPLF-057A migration expand, rollback, and restore-forward proof."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260825_0002"
MIGRATION_HEAD = "20260825_0003"
TABLE = "trademark_international_registrations"


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


def test_madrid_migration_empty_round_trip_and_schema_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-madrid.db').as_posix()}"
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
            "record_kind",
            "direction",
            "parent_registration_id",
            "basic_application_id",
            "ir_number",
            "wipo_reference",
            "designated_member_code",
            "wipo_status",
            "national_status",
            "source_reference",
            "source_retrieved_at",
            "version",
        } <= {column["name"] for column in schema.get_columns(TABLE)}
        indexes = {index["name"]: index for index in schema.get_indexes(TABLE)}
        assert indexes["uq_tm_international_company_ir_number"]["unique"] == 1
        assert indexes["uq_tm_international_designation_member"]["unique"] == 1
        foreign_keys = {
            foreign_key["name"]: tuple(foreign_key["constrained_columns"])
            for foreign_key in schema.get_foreign_keys(TABLE)
        }
        assert foreign_keys["fk_tm_international_docket_company"] == (
            "docket_id",
            "company_id",
        )
        assert foreign_keys["fk_tm_international_parent_company"] == (
            "parent_registration_id",
            "company_id",
        )
        assert _head(database_url) == MIGRATION_HEAD
    finally:
        engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert set(inspect(engine).get_table_names()) == before_tables
    finally:
        engine.dispose()

    command.upgrade(config, MIGRATION_HEAD)
    assert _head(database_url) == MIGRATION_HEAD
    get_settings.cache_clear()
    clear_engine_cache()


def test_madrid_migration_refuses_destructive_populated_downgrade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'ip-madrid-populated.db').as_posix()}"
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
                        id, company_id, docket_id, record_kind, direction,
                        wipo_reference, holder_name, mark_name, classes_json,
                        goods_services_json, priority_claims_json, source_url,
                        source_reference, source_retrieved_at, version,
                        created_by_membership_id, updated_by_membership_id,
                        created_at, updated_at
                    ) VALUES (
                        'madrid-1', 'company-1', 'docket-1',
                        'international_registration', 'inbound', 'WIPO-1',
                        'Holder', 'ASTER', '[]', '{{}}', '[]',
                        'https://www.wipo.int/madrid/1', 'WIPO-1',
                        '2026-08-25 06:30:00', 1, 'member-1', 'member-1',
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
