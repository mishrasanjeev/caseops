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
        connect_args = {"check_same_thread": False} if resolved_url.startswith("sqlite") else {}
        _ENGINE_CACHE[resolved_url] = create_engine(
            resolved_url,
            future=True,
            connect_args=connect_args,
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
