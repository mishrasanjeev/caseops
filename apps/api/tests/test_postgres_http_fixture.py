from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from alembic import command
from tests.fixtures_historical_migrations import historical_database
from tests.fixtures_postgres_client import dated_protocol_template, temporary_http_database
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
        "alias_rows": "SELECT * FROM forum_catalog_aliases ORDER BY id",
        "alias_semantics": """SELECT forum_catalog_entry_id, alias, normalized_alias,
            alias_type, source_name, source_url, verification_status, is_active,
            record_version, created_by_platform_admin_id, reviewed_by_platform_admin_id,
            updated_by_platform_admin_id, reviewed_at IS NOT NULL,
            created_at <= updated_at FROM forum_catalog_aliases
            ORDER BY forum_catalog_entry_id, normalized_alias""",
        "functions": """SELECT p.proname, pg_get_function_identity_arguments(p.oid),
            pg_get_functiondef(p.oid) FROM pg_proc p
            JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.prokind='f'
            ORDER BY p.proname, pg_get_function_identity_arguments(p.oid)""",
    }
    with engine.connect() as connection:
        return {name: connection.execute(text(sql)).all() for name, sql in queries.items()}


@pytest.mark.parametrize(
    "revision", ["head", "base", "20261010_0003", "20260928_0001; DROP DATABASE caseops"],
)
def test_dated_protocol_template_refuses_unreviewed_boundary_before_database_io(revision):
    with pytest.raises(AssertionError):
        with dated_protocol_template(revision):
            pytest.fail("An unreviewed historical boundary was admitted")


@pytest.mark.parametrize(
    ("fixture_name", "revision"),
    [
        ("document_protocol_template", "20260928_0001"),
        ("compliance_tail_template", "20261010_0002"),
    ],
)
def test_dated_protocol_templates_match_fresh_history_and_isolate_failed_clones(
    pg_engine, request, monkeypatch, fixture_name, revision,
):
    template = request.getfixturevalue(fixture_name)
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    original = _schema_signature(pg_engine)
    with historical_database(pg_engine, revision) as (fresh, _config):
        fresh_signature = _schema_signature(fresh)
        assert fresh_signature["revision"] == [(revision,)]
        with fresh.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM companies")) == 0

    def unexpected_upgrade(*args, **kwargs):
        raise AssertionError("A dated clone replayed migration history")

    monkeypatch.setattr(command, "upgrade", unexpected_upgrade)
    failed_name = None
    with pytest.raises(RuntimeError, match="deliberate dated clone interruption"):
        with temporary_http_database(source_url, template=template) as first:
            failed_name = first.url.database
            expected = _schema_signature(first)
            # The historical migration independently generates alias UUIDs and
            # timestamps. Compare its complete semantic catalogue across fresh
            # migrations; retain every native ID and timestamp in exact clone
            # comparisons below, including the recovery after interruption.
            assert {
                key: value for key, value in expected.items()
                if key not in {"aliases", "alias_rows"}
            } == {
                key: value for key, value in fresh_signature.items()
                if key not in {"aliases", "alias_rows"}
            }
            assert len(expected["alias_rows"]) == len(fresh_signature["alias_rows"]) > 0
            with first.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE dated_clone_probe (id integer)")
                connection.exec_driver_sql("INSERT INTO dated_clone_probe VALUES (1)")
            with temporary_http_database(source_url, template=template) as second:
                assert first.url.database != second.url.database
                assert _schema_signature(second) == expected
                with second.connect() as connection:
                    assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
                    assert (
                        connection.scalar(text("SELECT to_regclass('dated_clone_probe')")) is None
                    )
            with first.connect() as connection:
                assert connection.scalar(text("SELECT id FROM dated_clone_probe")) == 1
            raise RuntimeError("deliberate dated clone interruption")
    assert failed_name is not None
    with pg_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM pg_database WHERE datname=:name"),
            {"name": failed_name},
        ) == 0
        assert connection.scalar(
            text("SELECT datallowconn FROM pg_database WHERE datname=:name"),
            {"name": template.database},
        ) is False
    blocked = create_engine(template, poolclass=NullPool)
    try:
        with pytest.raises(OperationalError, match="not currently accepting connections"):
            with blocked.connect():
                pytest.fail("The historical template accepted a connection")
    finally:
        blocked.dispose()
    with temporary_http_database(source_url, template=template) as recovered:
        assert _schema_signature(recovered) == expected
    assert _schema_signature(pg_engine) == original


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
    created_names: list[str | None] = []

    def interrupt_clone() -> None:
        with temporary_http_database(source_url, template=migrated_http_template) as failed:
            created_names.append(failed.url.database)
            with failed.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE failed_fixture_probe (id integer)")
            raise RuntimeError("deliberate fixture interruption")

    with pytest.raises(RuntimeError, match="deliberate fixture interruption"):
        interrupt_clone()
    assert len(created_names) == 1
    created_name = created_names[0]
    assert created_name
    with pg_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM pg_database WHERE datname=:name"), {"name": created_name},
        ) == 0
        assert connection.scalar(
            text("SELECT datallowconn FROM pg_database WHERE datname=:name"),
            {"name": migrated_http_template.database},
        ) is False
    blocked_template = create_engine(migrated_http_template, poolclass=NullPool)

    def connect_to_template() -> None:
        with blocked_template.connect():
            pytest.fail("The immutable template accepted a connection")

    try:
        with pytest.raises(OperationalError, match="not currently accepting connections"):
            connect_to_template()
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
