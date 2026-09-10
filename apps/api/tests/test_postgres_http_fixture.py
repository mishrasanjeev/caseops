from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command
from tests.fixtures_postgres_client import temporary_http_database
from tests.test_auth_company import bootstrap_company
from tests.test_postgres_validation import _seed_company

pytestmark = pytest.mark.postgres


def _schema_signature(engine):
    queries = {
        "revision": "SELECT version_num FROM alembic_version",
        "columns": """SELECT table_name, column_name, data_type, udt_name,
            is_nullable, column_default FROM information_schema.columns
            WHERE table_schema='public' ORDER BY table_name, ordinal_position""",
        "indexes": """SELECT tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname='public' ORDER BY tablename, indexname""",
        "constraints": """SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
            ORDER BY c.relname, k.conname""",
        "triggers": """SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND NOT t.tgisinternal
            ORDER BY c.relname, t.tgname""",
        "aliases": """SELECT id, normalized_alias, is_active, verification_status
            FROM forum_catalog_aliases ORDER BY id""",
    }
    with engine.connect() as connection:
        return {name: connection.execute(text(sql)).all() for name, sql in queries.items()}


def test_http_clones_preserve_schema_and_never_replay_migrations(
    pg_engine, migrated_http_template, monkeypatch,
):
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    with Session(pg_engine) as session:
        retained_company = _seed_company(session)
        session.commit()

    def unexpected_upgrade(*args, **kwargs):
        raise AssertionError("An HTTP clone replayed the full migration history")

    monkeypatch.setattr(command, "upgrade", unexpected_upgrade)
    with temporary_http_database(source_url, template=migrated_http_template) as first:
        expected = _schema_signature(first)
        assert len({row[0] for row in expected["columns"]}) >= 317
        assert expected["indexes"] and expected["triggers"] and expected["aliases"]
        with Session(first) as session:
            own_company = _seed_company(session)
            session.commit()
        with first.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE clone_only_probe (id integer PRIMARY KEY)")
        with temporary_http_database(source_url, template=migrated_http_template) as second:
            assert _schema_signature(second) == expected
            with second.connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
                assert connection.scalar(text("SELECT to_regclass('clone_only_probe')")) is None
            assert first.url.database != second.url.database
        with first.connect() as connection:
            assert connection.scalar(text("SELECT id FROM companies")) == own_company
    with pg_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT id FROM companies WHERE id=:id"), {"id": retained_company},
        ) == retained_company


def test_http_clone_cleanup_preserves_template_after_failure(pg_engine, migrated_http_template):
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    created_name = None
    with pytest.raises(RuntimeError, match="deliberate fixture interruption"):
        with temporary_http_database(source_url, template=migrated_http_template) as failed:
            created_name = failed.url.database
            with failed.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE failed_fixture_probe (id integer)")
            raise RuntimeError("deliberate fixture interruption")
    with pg_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM pg_database WHERE datname=:name"), {"name": created_name},
        ) == 0
        assert connection.scalar(
            text("SELECT datallowconn FROM pg_database WHERE datname=:name"),
            {"name": migrated_http_template.database},
        ) is False
    blocked_template = create_engine(migrated_http_template, poolclass=NullPool)
    try:
        with pytest.raises(OperationalError, match="not currently accepting connections"):
            with blocked_template.connect():
                raise AssertionError("The immutable template accepted a connection")
    finally:
        blocked_template.dispose()
    with temporary_http_database(source_url, template=migrated_http_template) as recovered:
        with recovered.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('failed_fixture_probe')")) is None


@pytest.mark.parametrize("_iteration", [1, 2])
def test_http_fixture_bootstrap_has_independent_persisted_tenant(
    isolated_postgres_client, http_pg_engine, _iteration,
):
    with http_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
    payload = bootstrap_company(isolated_postgres_client)
    with http_pg_engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 1
        assert connection.scalar(text("SELECT id FROM companies")) == payload["company"]["id"]
