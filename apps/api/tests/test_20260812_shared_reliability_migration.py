from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache

TABLES = {
    "api_idempotency_records",
    "domain_outbox_events",
    "domain_consumer_effects",
}


def _config(project_root: Path) -> Config:
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    return config


def _table_names(database_url: str) -> set[str]:
    engine = create_engine(database_url, future=True)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _head(database_url: str) -> str:
    engine = create_engine(database_url, future=True)
    try:
        with engine.connect() as connection:
            return str(connection.scalar(text("SELECT version_num FROM alembic_version")))
    finally:
        engine.dispose()


def test_shared_reliability_migration_empty_rollback_and_populated_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    database_path = tmp_path / "shared-reliability.db"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    clear_engine_cache()
    config = _config(project_root)

    command.upgrade(config, "20260811_0005")
    assert TABLES.isdisjoint(_table_names(database_url))

    command.upgrade(config, "head")
    assert _head(database_url) == "20260812_0001"
    assert TABLES <= _table_names(database_url)

    # An empty rehearsal database can exercise the structural downgrade and
    # re-upgrade path without losing durable evidence.
    command.downgrade(config, "20260811_0005")
    assert TABLES.isdisjoint(_table_names(database_url))
    command.upgrade(config, "head")

    now = datetime.now(UTC)
    company_id = str(uuid4())
    record_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, is_active, "
                    "timezone, created_at) VALUES "
                    "(:id, 'Reliability migration fixture', :slug, 'law_firm', "
                    ":tenant_key, true, 'Asia/Kolkata', :created_at)"
                ),
                {
                    "id": company_id,
                    "slug": f"reliability-{company_id[:8]}",
                    "tenant_key": company_id,
                    "created_at": now,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO api_idempotency_records "
                    "(id, company_id, actor_scope, http_method, operation, "
                    "idempotency_key, request_hash, state, claim_token, "
                    "claim_generation, claim_expires_at, expires_at, created_at, "
                    "updated_at) VALUES "
                    "(:id, :company_id, 'system:migration-fixture', 'POST', "
                    "'fixture.operation', 'fixture-key', :request_hash, "
                    "'processing', 'fixture-claim', 1, :claim_expires_at, "
                    ":expires_at, :created_at, :created_at)"
                ),
                {
                    "id": record_id,
                    "company_id": company_id,
                    "request_hash": "a" * 64,
                    "claim_expires_at": now + timedelta(minutes=5),
                    "expires_at": now + timedelta(days=7),
                    "created_at": now,
                },
            )
    finally:
        engine.dispose()

    with pytest.raises(RuntimeError, match="roll application code forward"):
        command.downgrade(config, "20260811_0005")
    assert _head(database_url) == "20260812_0001"
    assert TABLES <= _table_names(database_url)

    get_settings.cache_clear()
    clear_engine_cache()
