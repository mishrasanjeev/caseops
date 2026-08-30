"""Unit contract for the database-enforced Alembic time budgets."""

from __future__ import annotations

import pytest

from caseops_api.db.connection_safety import migration_connect_args


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
