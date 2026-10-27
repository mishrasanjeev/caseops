from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

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

_DATABASE_JOURNAL_LOCK = threading.Lock()
_JOURNAL_META = (
    "st_dev",
    "st_ino",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
    "st_mode",
    "st_uid",
    "st_gid",
    "st_nlink",
)


def _database_ownership_journal(event, database_name, source_database, sql, connection):
    """Optional local-gate metadata only; never serializes a URL or credentials.

    The gate must EXCL-create its own empty0600 journal before launching pytest.
    Intent is durable BEFORE CREATE; ACK is recorded only AFTER the actual DBAPI
    acknowledgement. A lost ACK is not replay authority. Normal fixture cleanup
    remains independent of the journal, including when the ACK write fails.
    """
    target = os.environ.get("CASEOPS_TEST_DATABASE_OWNERSHIP_JOURNAL")
    if not target:
        return
    fd = source_fd = None
    try:
        run_id = os.environ["CASEOPS_TEST_DATABASE_OWNERSHIP_RUN_ID"]
        assert str(UUID(run_id)) == run_id
        assert event in {"create_intent", "create_ack"}
        assert re.fullmatch(r"caseops_http_(?:template_)?[0-9a-f]{32}", database_name)
        assert isinstance(source_database, str) and 0 < len(source_database) <= 63
        assert isinstance(sql, str) and 0 < len(sql) <= 1024
        backend_pid = connection.connection.driver_connection.info.backend_pid
        assert (
            isinstance(backend_pid, int) and not isinstance(backend_pid, bool) and backend_pid > 0
        )

        def meta(value):
            return tuple(getattr(value, key) for key in _JOURNAL_META)

        def named_matches(named, opened):
            fields = [key for key in _JOURNAL_META if key != "st_dev" or os.name != "nt"]
            return all(getattr(named, key) == getattr(opened, key) for key in fields)

        path, source = Path(target), Path(__file__).absolute()
        assert path.is_absolute() and path.resolve(strict=True) == path
        assert source.resolve(strict=True) == source
        parents = {p: meta(p.lstat()) for p in {*path.parents, *source.parents}}
        named, source_named = path.lstat(), source.lstat()
        assert stat.S_ISREG(named.st_mode) and named.st_nlink == 1
        assert stat.S_ISREG(source_named.st_mode) and 0 < source_named.st_size <= 65536
        if os.name != "nt":
            assert named.st_uid == os.getuid() and stat.S_IMODE(named.st_mode) == 0o600
        with _DATABASE_JOURNAL_LOCK:
            # Serialize the initial leaf observation with our own appenders.
            # An unrelated replacement after this observation is never accepted.
            named = path.lstat()
            flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            source_fd = os.open(source, os.O_RDONLY | flags)
            source_opened = os.fstat(source_fd)
            assert named_matches(source_named, source_opened)
            chunks, size = [], 0
            while size <= 65536:
                chunk = os.read(source_fd, min(65537 - size, 16384))
                if not chunk:
                    break
                size += len(chunk)
                chunks.append(chunk)
            assert size == source_opened.st_size and size <= 65536
            assert meta(source_opened) == meta(os.fstat(source_fd))
            assert named_matches(source.lstat(), source_opened)
            row = {
                "schema": 1,
                "runId": run_id,
                "event": event,
                "pid": os.getpid(),
                "backendPid": backend_pid,
                "timestampNs": str(time.time_ns()),
                "databaseName": database_name,
                "sourceDatabase": source_database,
                "canonicalCreateSqlSha256": hashlib.sha256(sql.encode()).hexdigest(),
                "fixtureSourceSha256": hashlib.sha256(b"".join(chunks)).hexdigest(),
            }
            payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            assert len(payload) <= 2048
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | flags)
            before = os.fstat(fd)
            assert named_matches(named, before) and named_matches(path.lstat(), before)
            assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1
            assert 0 <= before.st_size <= 1024**2 - len(payload)
            if os.name != "nt":
                assert before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                assert written > 0
                offset += written
            os.fsync(fd)
            after = os.fstat(fd)
            stable = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink")
            assert all(getattr(before, key) == getattr(after, key) for key in stable)
            assert after.st_size == before.st_size + len(payload)
            assert named_matches(path.lstat(), after)
            assert path.resolve(strict=True) == path and source.resolve(strict=True) == source
            assert parents == {p: meta(p.lstat()) for p in parents}
    except Exception:
        raise RuntimeError("POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID") from None
    finally:
        close_failed = False
        for opened in (fd, source_fd):
            if opened is not None:
                try:
                    os.close(opened)
                except OSError:
                    close_failed = True
        if close_failed:
            raise RuntimeError("POSTGRES_DATABASE_OWNERSHIP_JOURNAL_INVALID") from None


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
            sql = (
                f"CREATE DATABASE {quote(database_name)} TEMPLATE "
                f"{quote(template.database if template is not None else 'template0')}"
            )
            _database_ownership_journal(
                "create_intent", database_name, source_url.database, sql, connection
            )
            connection.exec_driver_sql(sql)
            created = True
            _database_ownership_journal(
                "create_ack", database_name, source_url.database, sql, connection
            )
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
    http_pg_engine,
    monkeypatch,
    tmp_path,
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
