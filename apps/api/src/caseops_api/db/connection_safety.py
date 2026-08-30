"""Shared PostgreSQL connection budgets for runtime and schema changes.

Application requests and Alembic used to build their engines independently.
The request engine applied database timeouts, while the migration engine did
not.  A migration waiting on an incompatible lock could therefore consume the
entire Cloud Run job timeout even though the application itself failed closed
after a few seconds.

Keep the server-enforced timeout options in one function so migrations and
runtime sessions cannot silently drift apart.  Values are already validated as
positive integers by ``Settings``; the explicit check also protects direct
callers such as one-off maintenance commands and tests.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url


def postgres_timeout_options(
    *,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
    idle_transaction_timeout_ms: int,
) -> str:
    """Return libpq ``options`` that PostgreSQL enforces on every connection."""

    budgets = {
        "statement_timeout": statement_timeout_ms,
        "lock_timeout": lock_timeout_ms,
        "idle_in_transaction_session_timeout": idle_transaction_timeout_ms,
    }
    invalid = {name: value for name, value in budgets.items() if value < 1}
    if invalid:
        raise ValueError(f"PostgreSQL timeout budgets must be positive: {invalid}")
    return " ".join(f"-c {name}={value}" for name, value in budgets.items())


def migration_connect_args(
    database_url: str,
    *,
    connect_timeout_seconds: int,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
    idle_transaction_timeout_ms: int,
) -> dict[str, object]:
    """Build the bounded connection contract used by Alembic.

    SQLite remains available for lightweight local tests and does not accept
    libpq connection parameters.  Production PostgreSQL gets the same
    server-enforced budgets as the application engine before Alembic starts its
    transaction.
    """

    if make_url(database_url).get_backend_name() != "postgresql":
        return {}
    if connect_timeout_seconds < 1:
        raise ValueError("PostgreSQL connect timeout must be positive.")
    return {
        "connect_timeout": connect_timeout_seconds,
        "options": postgres_timeout_options(
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
            idle_transaction_timeout_ms=idle_transaction_timeout_ms,
        ),
    }
