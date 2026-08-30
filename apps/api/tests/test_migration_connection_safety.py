"""Unit contract for the database-enforced Alembic time budgets."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy
from alembic.config import Config
from sqlalchemy import create_engine

from alembic import command
from caseops_api.core.settings import get_settings
from caseops_api.db.connection_safety import migration_connect_args

API_ROOT = Path(__file__).resolve().parents[1]


def test_postgres_migration_connect_args_are_server_enforced() -> None:
    args = migration_connect_args(
        "postgresql+psycopg://caseops@example.invalid/caseops",
        connect_timeout_seconds=7,
        statement_timeout_ms=60_000,
        lock_timeout_ms=5_000,
        idle_transaction_timeout_ms=60_000,
    )

    assert args == {
        "connect_timeout": 7,
        "options": (
            "-c statement_timeout=60000 -c lock_timeout=5000 "
            "-c idle_in_transaction_session_timeout=60000"
        ),
    }


def test_sqlite_migration_connection_does_not_receive_libpq_options() -> None:
    assert (
        migration_connect_args(
            "sqlite:///./caseops.db",
            connect_timeout_seconds=7,
            statement_timeout_ms=60_000,
            lock_timeout_ms=5_000,
            idle_transaction_timeout_ms=60_000,
        )
        == {}
    )


def test_postgres_migration_preserves_url_options_and_enforces_budgets_last() -> None:
    args = migration_connect_args(
        (
            "postgresql+psycopg://caseops@example.invalid/caseops"
            "?options=-c+search_path=tenant_schema+-c+statement_timeout=0"
        ),
        connect_timeout_seconds=7,
        statement_timeout_ms=60_000,
        lock_timeout_ms=5_000,
        idle_transaction_timeout_ms=60_000,
    )

    assert args["options"] == (
        "-c search_path=tenant_schema -c statement_timeout=0 "
        "-c statement_timeout=60000 -c lock_timeout=5000 "
        "-c idle_in_transaction_session_timeout=60000"
    )


def test_alembic_online_env_passes_dedicated_args_to_engine_from_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Execute Alembic's real env.py and capture its engine wiring.

    The returned engine is deliberately SQLite so the test needs no external
    database. The configured URL remains PostgreSQL, which proves env.py calls
    the production argument builder and forwards its result to
    ``engine_from_config``. Removing that keyword makes this regression fail.
    """

    monkeypatch.setenv(
        "CASEOPS_DATABASE_URL",
        (
            "postgresql+psycopg://caseops@example.invalid/caseops"
            "?options=-c+search_path=tenant_schema+-c+statement_timeout=0"
        ),
    )
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_CONNECT_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_STATEMENT_TIMEOUT_MS", "765432")
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS", "4321")
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_IDLE_TRANSACTION_TIMEOUT_MS", "65432")
    get_settings.cache_clear()

    captured: dict[str, object] = {}

    def capturing_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        **kwargs,
    ):
        captured["url"] = configuration[f"{prefix}url"]
        captured.update(kwargs)
        return create_engine(f"sqlite:///{tmp_path / 'alembic-wire.db'}", future=True)

    monkeypatch.setattr(sqlalchemy, "engine_from_config", capturing_engine_from_config)
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))

    command.current(config)

    assert str(captured["url"]).startswith("postgresql+psycopg://")
    assert captured["connect_args"] == {
        "connect_timeout": 9,
        "options": (
            "-c search_path=tenant_schema -c statement_timeout=0 "
            "-c statement_timeout=765432 -c lock_timeout=4321 "
            "-c idle_in_transaction_session_timeout=65432"
        ),
    }


def test_migration_timeout_settings_are_independent_from_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_DB_STATEMENT_TIMEOUT_MS", "70000")
    monkeypatch.setenv("CASEOPS_MIGRATION_DB_STATEMENT_TIMEOUT_MS", "800000")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.db_statement_timeout_ms == 70_000
    assert settings.migration_db_connect_timeout_seconds == 10
    assert settings.migration_db_statement_timeout_ms == 800_000
    assert settings.migration_db_lock_timeout_ms == 5_000
    assert settings.migration_db_idle_transaction_timeout_ms == 60_000


@pytest.mark.parametrize(
    ("field", "values"),
    [
        (
            "connect_timeout_seconds",
            {
                "connect_timeout_seconds": 0,
                "statement_timeout_ms": 1,
                "lock_timeout_ms": 1,
                "idle_transaction_timeout_ms": 1,
            },
        ),
        (
            "statement_timeout_ms",
            {
                "connect_timeout_seconds": 1,
                "statement_timeout_ms": 0,
                "lock_timeout_ms": 1,
                "idle_transaction_timeout_ms": 1,
            },
        ),
        (
            "lock_timeout_ms",
            {
                "connect_timeout_seconds": 1,
                "statement_timeout_ms": 1,
                "lock_timeout_ms": 0,
                "idle_transaction_timeout_ms": 1,
            },
        ),
        (
            "idle_transaction_timeout_ms",
            {
                "connect_timeout_seconds": 1,
                "statement_timeout_ms": 1,
                "lock_timeout_ms": 1,
                "idle_transaction_timeout_ms": 0,
            },
        ),
    ],
)
def test_postgres_migration_connect_args_reject_unbounded_values(
    field: str,
    values: dict[str, int],
) -> None:
    with pytest.raises(ValueError, match="timeout"):
        migration_connect_args(
            "postgresql+psycopg://caseops@example.invalid/caseops",
            **values,
        )

    assert field in values
