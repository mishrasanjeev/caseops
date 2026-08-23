"""Migration proof for IPLF-044 governed IP and Matter links."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

PREVIOUS_HEAD = "20260823_0002"
MIGRATION_HEAD = "20260823_0003"


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


def _seed_operational_pointer(database_url: str) -> tuple[str, str, str]:
    company_id = str(uuid4())
    matter_id = str(uuid4())
    docket_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, timezone, is_active, "
                    "team_scoping_enabled, created_at) VALUES "
                    "(:id, 'IP link fixture', :slug, 'law_firm', :id, 'Asia/Kolkata', "
                    "true, false, CURRENT_TIMESTAMP)"
                ),
                {"id": company_id, "slug": f"ip-link-{company_id[:8]}"},
            )
            connection.execute(
                text(
                    "INSERT INTO matters "
                    "(id, company_id, title, matter_code, status, practice_area, "
                    "forum_level, is_active, lifecycle_version, restricted_access, "
                    "created_at, updated_at) VALUES "
                    "(:id, :company_id, 'IP litigation', 'IP-LINK-001', 'active', "
                    "'Intellectual Property', 'tribunal', true, 0, false, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"id": matter_id, "company_id": company_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ip_docket_records "
                    "(id, company_id, matter_id, record_type, title, status, is_active, "
                    "lifecycle_version, archived_by_matter_disposal, restricted, "
                    "access_policy_version, current_version, created_at, updated_at) "
                    "VALUES (:id, :company_id, :matter_id, 'trademark', 'CASEOPS', "
                    "'ready', true, 0, false, false, 0, 1, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                ),
                {"id": docket_id, "company_id": company_id, "matter_id": matter_id},
            )
    finally:
        engine.dispose()
    return company_id, matter_id, docket_id


def test_ip_matter_link_migration_backfills_and_round_trips_when_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "ip-matter-links.db")
    command.upgrade(config, PREVIOUS_HEAD)
    company_id, matter_id, docket_id = _seed_operational_pointer(database_url)

    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        assert "ip_matter_links" in schema.get_table_names()
        assert "retirement_reason" in {
            row["name"] for row in schema.get_columns("ip_matter_links")
        }
        indexes = {
            row["name"]: tuple(row["column_names"])
            for row in schema.get_indexes("ip_matter_links")
        }
        assert indexes["uq_ip_matter_links_active_role"] == (
            "company_id",
            "docket_id",
            "matter_id",
            "relation_role",
        )
        assert indexes["uq_ip_matter_links_active_operational"] == (
            "company_id",
            "docket_id",
        )
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT company_id, docket_id, matter_id, relation_role, source, "
                    "retired_at FROM ip_matter_links"
                )
            ).mappings().one()
            assert dict(row) == {
                "company_id": company_id,
                "docket_id": docket_id,
                "matter_id": matter_id,
                "relation_role": "operational",
                "source": "migration",
                "retired_at": None,
            }
    finally:
        engine.dispose()

    with pytest.raises(IntegrityError):
        engine = create_engine(database_url, future=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE ip_matter_links SET retired_at = CURRENT_TIMESTAMP "
                        "WHERE docket_id = :docket_id"
                    ),
                    {"docket_id": docket_id},
                )
        finally:
            engine.dispose()

    command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert "ip_matter_links" not in inspect(engine).get_table_names()
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT matter_id FROM ip_docket_records WHERE id = :id"),
                {"id": docket_id},
            ) == matter_id
    finally:
        engine.dispose()
    command.upgrade(config, MIGRATION_HEAD)


def test_ip_matter_link_migration_refuses_to_destroy_governed_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url, config = _configure(tmp_path, monkeypatch, "ip-matter-links-retained.db")
    command.upgrade(config, PREVIOUS_HEAD)
    company_id, matter_id, docket_id = _seed_operational_pointer(database_url)
    command.upgrade(config, MIGRATION_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ip_matter_links "
                    "(id, company_id, docket_id, matter_id, relation_role, "
                    "effective_from, source, reason, created_at, updated_at) VALUES "
                    "(:id, :company_id, :docket_id, :matter_id, 'advisory', "
                    "CURRENT_TIMESTAMP, 'manual', 'Retained advisory history', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": str(uuid4()),
                    "company_id": company_id,
                    "docket_id": docket_id,
                    "matter_id": matter_id,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="retained governed IP Matter-link history"):
        command.downgrade(config, PREVIOUS_HEAD)
    engine = create_engine(database_url, future=True)
    try:
        assert "ip_matter_links" in inspect(engine).get_table_names()
    finally:
        engine.dispose()
