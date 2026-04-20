from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from caseops_api.core.settings import get_settings
from caseops_api.db import models  # noqa: F401
from caseops_api.db.base import Base

_ENGINE_CACHE: dict[str, Engine] = {}


def get_engine(database_url: str | None = None) -> Engine:
    resolved_url = database_url or get_settings().database_url
    if resolved_url not in _ENGINE_CACHE:
        if resolved_url.startswith("sqlite"):
            connect_args: dict[str, object] = {"check_same_thread": False}
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
            engine_kwargs = {
                "future": True,
                "pool_pre_ping": True,
                "pool_recycle": 1800,
            }
        _ENGINE_CACHE[resolved_url] = create_engine(
            resolved_url, connect_args=connect_args, **engine_kwargs
        )
    return _ENGINE_CACHE[resolved_url]


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(database_url), autoflush=False, expire_on_commit=False)


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
