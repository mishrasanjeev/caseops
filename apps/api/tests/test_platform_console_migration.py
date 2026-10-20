"""Fresh independent console migration and retained revocation evidence."""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from caseops_api.core.security import hash_password
from caseops_api.core.settings import get_settings
from caseops_api.db.base import Base
from caseops_api.db.index_coverage import database_foreign_key_gaps
from caseops_api.db.models import User
from caseops_api.db.session import clear_engine_cache
from tests.fixtures_postgres_client import temporary_http_database

PREVIOUS = "20261019_0001"
HEAD = "20261020_0001"
TABLES = {
    "platform_report_admins",
    "platform_console_sessions",
    "platform_console_tokens",
    "platform_console_deliveries",
    "platform_report_audit_events",
}
KINDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)]


@contextmanager
def fresh_engine(kind, tmp_path):
    if kind == "postgres":
        with temporary_http_database(make_url(os.environ["CASEOPS_TEST_POSTGRES_URL"])) as engine:
            yield engine
    else:
        engine = create_engine(
            f"sqlite+pysqlite:///{(tmp_path / 'console-migration.db').as_posix()}"
        )
        try:
            yield engine
        finally:
            engine.dispose()


def migration_config(engine, monkeypatch):
    url = engine.url.render_as_string(hide_password=False)
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    clear_engine_cache()
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)
    return config


@pytest.mark.parametrize("kind", KINDS)
def test_console_fresh_upgrade_and_empty_downgrade_preserve_old_data(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        old_tables = set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            old_catalog = connection.execute(
                text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
            ).all()
        assert old_catalog
        command.upgrade(config, HEAD)
        schema = inspect(engine)
        assert set(schema.get_table_names()) == old_tables | TABLES
        assert not database_foreign_key_gaps(schema, table_names=TABLES)
        for name in TABLES:
            expected_indexes = {index.name for index in Base.metadata.tables[name].indexes}
            assert expected_indexes <= {index["name"] for index in schema.get_indexes(name)}
        with Session(engine) as session:
            user = User(
                email="retained@console.example",
                full_name="Retained",
                password_hash=hash_password("RetainedPassword123!"),
            )
            session.add(user)
            session.commit()
            user_id = user.id
        command.downgrade(config, PREVIOUS)
        assert set(inspect(engine).get_table_names()) == old_tables
        with engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT email FROM users WHERE id = :id"), {"id": user_id})
                == "retained@console.example"
            )
            assert (
                connection.execute(
                    text("SELECT id, normalized_alias FROM forum_catalog_aliases ORDER BY id")
                ).all()
                == old_catalog
            )
        command.upgrade(config, HEAD)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


@pytest.mark.parametrize("kind", KINDS)
def test_user_only_revocation_evidence_refuses_console_downgrade(kind, tmp_path, monkeypatch):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, HEAD)
        now = datetime.now(UTC)
        with Session(engine) as session:
            user = User(
                email="revoked@console.example",
                full_name="Revoked",
                password_hash=hash_password("RetainedPassword123!"),
                sessions_valid_after=now,
            )
            session.add(user)
            session.commit()
            user_id = user.id
        with pytest.raises(RuntimeError, match="User session revocation evidence"):
            command.downgrade(config, PREVIOUS)
        schema = inspect(engine)
        assert TABLES <= set(schema.get_table_names())
        assert "sessions_valid_after" in {column["name"] for column in schema.get_columns("users")}
        with Session(engine) as session:
            retained = session.scalar(select(User.sessions_valid_after).where(User.id == user_id))
            assert retained.replace(tzinfo=UTC) == now
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
            for name in TABLES:
                assert (
                    connection.scalar(
                        select(text("count(*)")).select_from(Base.metadata.tables[name])
                    )
                    == 0
                )
