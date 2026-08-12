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

    command.upgrade(config, "20260812_0001")
    assert _head(database_url) == "20260812_0001"
    assert TABLES <= _table_names(database_url)
    engine = create_engine(database_url, future=True)
    try:
        schema = inspect(engine)
        outbox_columns = {
            column["name"] for column in schema.get_columns("domain_outbox_events")
        }
        assert {
            "expected_consumers_json",
            "dead_letter_resolution",
            "dead_letter_resolved_at",
        } <= outbox_columns
        idempotency_indexes = {
            index["name"] for index in schema.get_indexes("api_idempotency_records")
        }
        assert {
            "ix_api_idempotency_actor_membership",
            "ix_api_idempotency_actor_company",
        } <= idempotency_indexes
        for table in TABLES:
            company_foreign_keys = [
                foreign_key
                for foreign_key in schema.get_foreign_keys(table)
                if foreign_key["referred_table"] == "companies"
            ]
            assert company_foreign_keys
            assert all(
                foreign_key["options"].get("ondelete") == "RESTRICT"
                for foreign_key in company_foreign_keys
            )
        with engine.connect() as connection:
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'trigger' AND name LIKE 'trg_%_immutable'"
                    )
                ).all()
            )
        assert triggers == {
            "trg_api_idempotency_identity_immutable",
            "trg_domain_outbox_envelope_immutable",
        }
    finally:
        engine.dispose()

    # An empty rehearsal database can exercise the structural downgrade and
    # re-upgrade path without losing durable evidence.
    command.downgrade(config, "20260811_0005")
    assert TABLES.isdisjoint(_table_names(database_url))
    command.upgrade(config, "20260812_0001")

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
