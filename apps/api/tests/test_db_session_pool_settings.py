"""Coverage for env-configurable SQLAlchemy pool sizing in
``apps/api/src/caseops_api/db/session.py``.

Anchor: 2026-05-04 c=16 attempt on the ingest VM exhausted the
default 15-connection pool (``pool_size=5 + max_overflow=10``)
because PR #9's independent audit-row session doubles per-call
connection demand. 32 ``QueuePool limit ... timed out`` failures
in 20 min, throughput regressed from 0.32/s to 0.25/s.

The fix surfaces three new env-tunable settings:

    CASEOPS_DB_POOL_SIZE      default 5
    CASEOPS_DB_MAX_OVERFLOW   default 10
    CASEOPS_DB_POOL_TIMEOUT   default 30

Defaults are intentionally conservative — Cloud Run's per-instance
multiplication of connections against Cloud SQL means a global
default bump would risk pinning the upstream. Operators bump these
on the ingest VM only.

These tests pin:

- non-SQLite engines receive the configured pool kwargs verbatim
- SQLite engines do NOT get pool kwargs (SQLAlchemy raises if
  they're passed against the SingletonThreadPool default for
  ``sqlite:///`` URLs)
- the engine cache key includes pool settings so an env change
  between calls produces a fresh engine without ``clear_engine_cache``
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from caseops_api.core.settings import get_settings
from caseops_api.db.base import Base
from caseops_api.db.models import Company, CompanyType
from caseops_api.db.session import (
    _ENGINE_CACHE,
    clear_engine_cache,
    get_db_session,
    get_engine,
    get_session_factory,
)


class _FakeEngine:
    """Stub for ``create_engine`` patches.

    ``clear_engine_cache`` calls ``.dispose()`` on every cached
    engine, so the test stub must provide that method even though it
    no-ops. Plain ``object()`` raises AttributeError during fixture
    teardown."""

    def dispose(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _isolate_engine_cache():
    """Each test starts with an empty cache and a fresh settings
    cache so monkeypatch.setenv changes actually take effect."""
    clear_engine_cache()
    get_settings.cache_clear()
    yield
    clear_engine_cache()
    get_settings.cache_clear()


# ---------- non-SQLite (Postgres): kwargs flow through -----------


def test_postgres_engine_uses_configured_pool_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql+psycopg://x:y@h:5432/d")
    monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "24")
    monkeypatch.setenv("CASEOPS_DB_MAX_OVERFLOW", "24")
    monkeypatch.setenv("CASEOPS_DB_POOL_TIMEOUT", "45")

    captured: dict = {}

    def _fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        # Return a sentinel; the code path doesn't introspect it
        # before the cache assignment, and we never actually
        # connect.
        return _FakeEngine()

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        get_engine()

    kwargs = captured["kwargs"]
    assert kwargs["pool_size"] == 24
    assert kwargs["max_overflow"] == 24
    assert kwargs["pool_timeout"] == 45
    # Existing keepalive / pre-ping / recycle still applied.
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_recycle"] == 300


def test_postgres_engine_defaults_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without any env override the defaults match SQLAlchemy's own
    so Cloud Run instance multiplication doesn't pin Cloud SQL."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql+psycopg://x:y@h:5432/d")
    monkeypatch.delenv("CASEOPS_DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("CASEOPS_DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("CASEOPS_DB_POOL_TIMEOUT", raising=False)

    captured: dict = {}

    def _fake_create_engine(url, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeEngine()

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        get_engine()

    kwargs = captured["kwargs"]
    assert kwargs["pool_size"] == 5
    assert kwargs["max_overflow"] == 10
    assert kwargs["pool_timeout"] == 30


def test_postgres_engine_passes_keepalive_connect_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression fence: existing keepalive tuning must not regress
    when the pool kwargs land. Both blocks live in the same
    ``engine_kwargs`` setup."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql+psycopg://x:y@h:5432/d")

    captured: dict = {}

    def _fake_create_engine(url, *, connect_args=None, **kwargs):
        captured["connect_args"] = connect_args
        return _FakeEngine()

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        get_engine()

    ca = captured["connect_args"]
    assert ca == {
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }


# ---------- SQLite: pool kwargs MUST NOT be passed ----------------


def test_sqlite_engine_does_not_receive_pool_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLAlchemy raises ``TypeError: Invalid argument(s) 'pool_size',
    'max_overflow' sent to create_engine()`` when ``pool_size`` / etc.
    are passed against the SingletonThreadPool default that
    ``sqlite:///`` resolves to. Even if the user sets the env
    overrides, SQLite engines must ignore them."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "sqlite:///./test.db")
    monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "24")
    monkeypatch.setenv("CASEOPS_DB_MAX_OVERFLOW", "24")
    monkeypatch.setenv("CASEOPS_DB_POOL_TIMEOUT", "45")

    captured: dict = {}

    def _fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _FakeEngine()

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        get_engine()

    kwargs = captured["kwargs"]
    # The exact keys SQLAlchemy chokes on for SQLite.
    assert "pool_size" not in kwargs
    assert "max_overflow" not in kwargs
    assert "pool_timeout" not in kwargs
    # SQLite-specific kwargs still applied.
    assert kwargs.get("future") is True


def test_sqlite_engine_uses_check_same_thread_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression fence: SQLite block must keep
    ``check_same_thread=False`` so test-thread fixtures keep working."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "sqlite:///./test.db")

    captured: dict = {}

    def _fake_create_engine(url, *, connect_args=None, **kwargs):
        captured["connect_args"] = connect_args
        return _FakeEngine()

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        get_engine()

    assert captured["connect_args"] == {
        "check_same_thread": False,
        "timeout": 30,
    }


def test_sqlite_engine_enables_wal_and_busy_timeout(tmp_path) -> None:
    """Playwright CI runs the API and web app against one SQLite file.

    WAL keeps long-lived read requests from blocking a following bootstrap
    write; busy_timeout gives genuine write/write contention a bounded wait.
    """
    db_path = tmp_path / "caseops-e2e.db"

    engine = get_engine(f"sqlite:///{db_path.as_posix()}")

    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() >= 30_000
        assert connection.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


def test_sqlite_session_serializes_write_until_commit(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "caseops-e2e.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    events: list[str] = []

    class _FakeLock:
        def acquire(self) -> None:
            events.append("acquire")

        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr("caseops_api.db.session._SQLITE_WRITE_LOCK", _FakeLock())

    session = get_session_factory(database_url)()
    try:
        session.add(
            Company(
                name="E2E Lock Test",
                slug="e2e-lock-test",
                company_type=CompanyType.LAW_FIRM,
                tenant_key="e2e-lock-test",
            )
        )
        session.flush()
        assert events == ["acquire"]

        session.commit()
        assert events == ["acquire", "release"]
    finally:
        session.close()


def test_request_session_finalizer_releases_sqlite_writer_on_event_loop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prevent the async-route/worker-finalizer SQLite deadlock from returning."""

    db_path = tmp_path / "caseops-request-finalizer.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database_url)
    get_settings.cache_clear()
    engine = get_engine(database_url)
    Base.metadata.create_all(bind=engine)
    events: list[str] = []

    class _FakeLock:
        def acquire(self) -> None:
            events.append("acquire")

        def release(self) -> None:
            events.append("release")

    monkeypatch.setattr("caseops_api.db.session._SQLITE_WRITE_LOCK", _FakeLock())

    async def _exercise_dependency() -> None:
        dependency = get_db_session()
        session = await anext(dependency)
        session.add(
            Company(
                name="E2E Request Finalizer",
                slug="e2e-request-finalizer",
                company_type=CompanyType.LAW_FIRM,
                tenant_key="e2e-request-finalizer",
            )
        )
        session.flush()
        assert events == ["acquire"]
        await dependency.aclose()

    assert inspect.isasyncgenfunction(get_db_session)
    asyncio.run(_exercise_dependency())
    assert events == ["acquire", "release"]


# ---------- engine cache invalidation on pool-setting change ------


def test_engine_cache_returns_fresh_engine_when_pool_size_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing ``CASEOPS_DB_POOL_SIZE`` between two ``get_engine()``
    calls produces a NEW engine — the cache key includes pool
    settings so a stale engine isn't returned. Without this,
    monkeypatch in tests would silently reuse the prior engine."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql+psycopg://x:y@h:5432/d")

    created: list[object] = []

    def _fake_create_engine(url, **kwargs):
        created.append(_FakeEngine())
        return created[-1]

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "5")
        get_settings.cache_clear()
        e1 = get_engine()

        monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "24")
        get_settings.cache_clear()
        e2 = get_engine()

    assert len(created) == 2
    assert e1 is not e2
    # Both engines are still in the cache (cache key differs by
    # pool_size so they don't collide).
    assert len(_ENGINE_CACHE) == 2


def test_engine_cache_returns_same_engine_for_identical_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Calling ``get_engine()`` twice with no env change returns the
    SAME engine. Cache hit is what makes the function cheap."""
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql+psycopg://x:y@h:5432/d")
    monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "8")

    created: list[object] = []

    def _fake_create_engine(url, **kwargs):
        created.append(_FakeEngine())
        return created[-1]

    with patch("caseops_api.db.session.create_engine", _fake_create_engine):
        e1 = get_engine()
        e2 = get_engine()

    assert len(created) == 1
    assert e1 is e2


# ---------- Settings field shape ----------------------------------


def test_settings_field_defaults_match_sqlalchemy_defaults() -> None:
    """Pin the conservative defaults so a future ``Field(default=...)``
    edit can't silently raise the global pool. Cloud Run instances
    fan out — a global bump multiplies connections by instance count
    against Cloud SQL's max_connections."""
    settings = get_settings()
    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 10
    assert settings.db_pool_timeout == 30


def test_settings_field_accepts_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "24")
    monkeypatch.setenv("CASEOPS_DB_MAX_OVERFLOW", "24")
    monkeypatch.setenv("CASEOPS_DB_POOL_TIMEOUT", "45")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.db_pool_size == 24
    assert settings.db_max_overflow == 24
    assert settings.db_pool_timeout == 45


def test_settings_pool_size_rejects_zero_or_negative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pool size of 0 would deadlock instantly under any concurrent
    workload. Pin via ``ge=1`` constraint."""
    monkeypatch.setenv("CASEOPS_DB_POOL_SIZE", "0")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
