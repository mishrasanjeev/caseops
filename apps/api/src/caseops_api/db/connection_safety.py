"""Shared PostgreSQL connection-budget construction.

Application requests and Alembic used to build their engines independently.
The request engine applied database timeouts, while the migration engine did
not.  A migration waiting on an incompatible lock could therefore consume the
entire Cloud Run job timeout even though the application itself failed closed
after a few seconds.

Keep the server-enforced option construction in one function while allowing
runtime and migration callers to select independent budgets.  Values are
already validated as positive integers by ``Settings``; the explicit check
also protects direct callers such as one-off maintenance commands and tests.
"""

from __future__ import annotations

from sqlalchemy.engine import make_url


def postgres_timeout_options(
    *,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
    idle_transaction_timeout_ms: int,
    existing_options: str | None = None,
) -> str:
    """Return libpq ``options`` with the owned timeout GUCs enforced last.

    SQLAlchemy passes URL-query parameters and ``connect_args`` to the driver,
    but a duplicate ``options`` key in ``connect_args`` replaces the URL value.
    Preserve the URL value verbatim, then append the owned timeout GUCs so
    PostgreSQL's left-to-right option processing gives the configured budgets
    final authority.  This retains settings such as ``search_path`` or
    ``application_name`` without allowing URL-supplied timeout values to
    disable the fail-closed budgets.
    """

    budgets = {
        "statement_timeout": statement_timeout_ms,
        "lock_timeout": lock_timeout_ms,
        "idle_in_transaction_session_timeout": idle_transaction_timeout_ms,
    }
    invalid = {name: value for name, value in budgets.items() if value < 1}
    if invalid:
        raise ValueError(f"PostgreSQL timeout budgets must be positive: {invalid}")
    enforced = " ".join(f"-c {name}={value}" for name, value in budgets.items())
    preserved = (existing_options or "").strip()
    return f"{preserved} {enforced}" if preserved else enforced


def postgres_url_options(database_url: str) -> str | None:
    """Return the URL-supplied libpq options without losing repeated values."""

    value = make_url(database_url).query.get("options")
    if value is None:
        return None
    if isinstance(value, tuple):
        return " ".join(part.strip() for part in value if part.strip()) or None
    return value.strip() or None


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
    libpq connection parameters.  PostgreSQL gets migration-specific,
    server-enforced budgets before Alembic starts its transaction.  Any
    non-timeout libpq options supplied in the database URL remain intact.
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
            existing_options=postgres_url_options(database_url),
        ),
    }
