from __future__ import annotations

from collections.abc import Generator
from threading import Lock

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.core.settings import get_settings
from caseops_api.db import models
from caseops_api.db.base import Base

if models.__name__ != "caseops_api.db.models":
    raise RuntimeError("caseops_api.db.models did not import correctly")

# Cache key includes pool settings so that an env change between
# tests / processes produces a fresh engine instead of returning the
# stale one. Production use only constructs the engine once per
# process (settings are env-frozen) so this has no overhead in real
# deployments. Tests that monkeypatch CASEOPS_DB_POOL_SIZE etc. get
# a fresh engine without needing ``clear_engine_cache()``.
_EngineCacheKey = tuple[str, int, int, int]
_ENGINE_CACHE: dict[_EngineCacheKey, Engine] = {}
_SQLITE_WRITE_LOCK = Lock()
_SQLITE_WRITE_LOCK_HELD_KEY = "caseops_sqlite_write_lock_held"


class CaseOpsSession(Session):
    def _uses_sqlite_bind(self) -> bool:
        bind = self.get_bind()
        engine = getattr(bind, "engine", bind)
        return isinstance(engine, Engine) and engine.url.get_backend_name() == "sqlite"

    def _acquire_sqlite_write_lock(self) -> None:
        if self.info.get(_SQLITE_WRITE_LOCK_HELD_KEY) or not self._uses_sqlite_bind():
            return
        _SQLITE_WRITE_LOCK.acquire()
        self.info[_SQLITE_WRITE_LOCK_HELD_KEY] = True

    def _release_sqlite_write_lock(self) -> None:
        if not self.info.pop(_SQLITE_WRITE_LOCK_HELD_KEY, False):
            return
        _SQLITE_WRITE_LOCK.release()

    def flush(self, objects: object | None = None) -> None:
        if self.new or self.dirty or self.deleted:
            self._acquire_sqlite_write_lock()
        super().flush(objects)

    def commit(self) -> None:
        try:
            super().commit()
        finally:
            self._release_sqlite_write_lock()

    def rollback(self) -> None:
        try:
            super().rollback()
        finally:
            self._release_sqlite_write_lock()

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._release_sqlite_write_lock()


def _configure_sqlite_connection(dbapi_connection: object, _connection_record: object) -> None:
    cursor = dbapi_connection.cursor()
    try:
        # SQLite does not enforce declared foreign keys unless every
        # connection opts in.  Without this, local/test databases silently
        # accept cross-tenant rows that PostgreSQL rejects in production.
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    finally:
        cursor.close()


def _install_sqlite_pragmas(engine: Engine) -> None:
    event.listen(engine, "connect", _configure_sqlite_connection)


def get_engine(database_url: str | None = None) -> Engine:
    settings = get_settings()
    resolved_url = database_url or settings.database_url
    cache_key: _EngineCacheKey = (
        resolved_url,
        settings.db_pool_size,
        settings.db_max_overflow,
        settings.db_pool_timeout,
    )
    if cache_key not in _ENGINE_CACHE:
        if resolved_url.startswith("sqlite"):
            connect_args: dict[str, object] = {
                "check_same_thread": False,
                # CI Playwright uses one SQLite file behind the API server.
                # Give legitimate writes time to finish; connection PRAGMAs
                # below also enable WAL so readers don't block those writes.
                "timeout": 30,
            }
            # SQLite uses StaticPool / SingletonThreadPool depending on
            # url; explicit pool_size/max_overflow/pool_timeout don't
            # apply (and SQLAlchemy will raise if passed). Keep SQLite
            # kwargs minimal — every pool tuning knob in this file is
            # for the Postgres-backed engines only.
            engine_kwargs: dict[str, object] = {"future": True}
        else:
            # TCP keepalive on the Postgres socket. Without these, a long-
            # running ingest or Layer-2 extraction that idles between
            # statements gets its connection silently dropped by Cloud
            # SQL's proxy / the workstation's NAT / Windows' socket
            # timer, and the NEXT UPDATE fails with
            # "Software caused connection abort (0x00002745/10053)".
            # Observed on 2026-04-20 across SC 2021 sweep + refresh-v2 +
            # Layer 2. These four kwargs map directly to libpq
            # connection parameters so psycopg forwards them to the
            # server without surprise.
            connect_args = {
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 5,
            }
            # pool_pre_ping costs one lightweight SELECT 1 per checkout
            # but turns an already-dead pooled connection into a clean
            # reconnect instead of a crash. pool_recycle caps connection
            # age so we never hang onto a TCP socket Cloud SQL has
            # quietly closed under us.
            #
            # 2026-04-29: pool_recycle dropped 1800 → 300 after a
            # multi-hour false-positive watchdog reset loop. The corpus
            # ingest script does long OCR work between DB statements
            # (RapidOCR can take 30-60s per HC PDF). Even with
            # pool_pre_ping firing on checkout, the connection can be
            # silently closed between checkout and the next statement
            # if it's held longer than Cloud SQL's idle timeout. 300s
            # (5min) recycle is well under any reasonable idle-timeout
            # threshold and the ~3ms cost of reconnecting is negligible
            # vs the cost of a failed insert + retry.
            #
            # 2026-05-04: pool_size / max_overflow / pool_timeout
            # surfaced as env-tunable settings. Defaults still match
            # SQLAlchemy's own (5 / 10 / 30) so Cloud Run instance
            # multiplication doesn't pin Cloud SQL. The ingest VM
            # overrides these via env before launching concurrent
            # backfill workers — PR #9's independent audit-row session
            # means each Layer-2 call needs 2 connections at peak, so
            # the rule of thumb is pool_size + max_overflow >=
            # 2 * concurrency + buffer.
            engine_kwargs = {
                "future": True,
                "pool_pre_ping": True,
                "pool_recycle": 300,
                "pool_size": settings.db_pool_size,
                "max_overflow": settings.db_max_overflow,
                "pool_timeout": settings.db_pool_timeout,
            }
        engine = create_engine(resolved_url, connect_args=connect_args, **engine_kwargs)
        if resolved_url.startswith("sqlite") and isinstance(engine, Engine):
            _install_sqlite_pragmas(engine)
        _ENGINE_CACHE[cache_key] = engine
    return _ENGINE_CACHE[cache_key]


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(database_url),
        class_=CaseOpsSession,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session]:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def create_database_schema() -> None:
    Base.metadata.create_all(bind=get_engine())


def clear_engine_cache() -> None:
    for engine in _ENGINE_CACHE.values():
        engine.dispose()
    _ENGINE_CACHE.clear()
