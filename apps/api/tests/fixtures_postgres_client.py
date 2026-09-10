from __future__ import annotations

import os
import re
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.pool import NullPool

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.session import clear_engine_cache
from caseops_api.main import create_application
from tests.test_postgres_validation import _ensure_migrations, migration_pg_engine  # noqa: F401


@contextmanager
def temporary_http_database(source_url: URL, *, template: URL | None = None):
    prefix = "caseops_http_template_" if template is None else "caseops_http_"
    database_name = prefix + uuid4().hex
    assert database_name != source_url.database
    if template is not None:
        assert re.fullmatch(r"caseops_http_template_[0-9a-f]{32}", template.database or "")
        assert template.set(database=source_url.database) == source_url
    admin = create_engine(source_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    quote = admin.dialect.identifier_preparer.quote
    created = False
    probe = None
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(
                f"CREATE DATABASE {quote(database_name)} TEMPLATE "
                f"{quote(template.database if template is not None else 'template0')}"
            )
        created = True
        probe = create_engine(source_url.set(database=database_name), poolclass=NullPool)
        yield probe
    finally:
        if probe is not None:
            probe.dispose()
        if created:
            assert re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}", database_name)
            assert database_name != source_url.database
            with admin.connect() as connection:
                connection.exec_driver_sql(f"DROP DATABASE {quote(database_name)} WITH (FORCE)")
        admin.dispose()


@pytest.fixture(scope="session")
def migrated_http_template() -> Generator[URL]:
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    assert source_url.get_backend_name() == "postgresql"
    # Never clone the shared test database: its earlier tests retain their rows.
    with temporary_http_database(source_url) as template:
        url = template.url.render_as_string(hide_password=False)
        root = Path(__file__).resolve().parents[1]
        config = Config(str(root / "alembic.ini"))
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv("CASEOPS_ENV", "local")
            patch.setenv("CASEOPS_DATABASE_URL", url)
            get_settings.cache_clear()
            clear_engine_cache()
            try:
                command.upgrade(config, "head")
            finally:
                clear_engine_cache()
                get_settings.cache_clear()
        with template.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM forum_catalog_aliases"))
            assert connection.scalar(text("SELECT count(*) FROM companies")) == 0
        template.dispose()
        admin = create_engine(source_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
        try:
            name = admin.dialect.identifier_preparer.quote(template.url.database)
            with admin.connect() as connection:
                connection.exec_driver_sql(f"ALTER DATABASE {name} ALLOW_CONNECTIONS false")
            yield template.url
        finally:
            admin.dispose()


@pytest.fixture
def http_pg_engine(migrated_http_template, monkeypatch) -> Generator[Engine]:
    source_url = make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])
    catalogue = text(
        "SELECT id, normalized_alias, is_active, verification_status "
        "FROM forum_catalog_aliases ORDER BY id"
    )
    source = create_engine(source_url, poolclass=NullPool)
    original_catalogue = None
    try:
        with source.connect() as connection:
            original_catalogue = connection.execute(catalogue).all()
            original_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        assert original_catalogue, (
            "The shared acceptance database must retain its reviewed aliases."
        )
        with temporary_http_database(source_url, template=migrated_http_template) as engine:
            url = engine.url.render_as_string(hide_password=False)
            monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
            monkeypatch.setenv("CASEOPS_TEST_POSTGRES_URL", url)
            get_settings.cache_clear()
            clear_engine_cache()
            try:
                yield engine
            finally:
                clear_engine_cache()
    finally:
        try:
            if original_catalogue is not None:
                with source.connect() as connection:
                    assert connection.execute(catalogue).all() == original_catalogue
                    assert (
                        connection.scalar(text("SELECT version_num FROM alembic_version"))
                        == original_revision
                    )
        finally:
            source.dispose()


@pytest.fixture
def isolated_postgres_client(
    http_pg_engine, monkeypatch, tmp_path,
) -> Generator[TestClient]:
    # Only HTTP fixtures reuse an immutable schema. Migration rehearsals stay fresh.
    engine = http_pg_engine
    assert engine.dialect.name == "postgresql"
    for name, value in {
        "CASEOPS_ENV": "local",
        "CASEOPS_AUTO_MIGRATE": "false",
        "CASEOPS_AUTH_SECRET": "test-secret-should-be-at-least-32-bytes",
        "CASEOPS_AUTH_RATE_LIMIT_ENABLED": "false",
        "CASEOPS_PUBLIC_APP_URL": "http://testserver",
        "CASEOPS_CORS_ORIGINS": '["http://testserver"]',
        "CASEOPS_LLM_PROVIDER": "mock",
        "CASEOPS_LLM_MODEL": "caseops-mock-1",
        "CASEOPS_LLM_API_KEY": "",
        "CASEOPS_EMBEDDING_PROVIDER": "mock",
        "CASEOPS_EMBEDDING_MODEL": "caseops-mock-embed",
        "CASEOPS_EMBEDDING_API_KEY": "",
        "CASEOPS_DOCUMENT_STORAGE_PATH": (tmp_path / "documents").as_posix(),
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    clear_engine_cache()
    with TestClient(
        create_application(),
        headers={"X-CaseOps-Automated-Test": "no-paid-providers"},
    ) as client:
        yield client
