"""Opt-in UTC statement time, including cached SQLite executions.

PostgreSQL owns statement_timestamp(), distinct from transaction now(). SQLite
has no microsecond statement clock. Its compiler uses ONE immutable named bind
whose callable is evaluated when SQLAlchemy constructs execution parameters.
The value is never cached; all occurrences/rows use that execution's one value.
No global authentication clock, UDF, engine hook or additional SQL is involved.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime, bindparam
from sqlalchemy.exc import CompileError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sqlite_clock_value() -> datetime:
    value = _utc_now()
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("A UTC statement clock is required.")
    # SQLite's canonical DateTime storage is UTC without an offset. Preserve all
    # six fractional digits; neither CURRENT_TIMESTAMP nor strftime is used.
    return value.astimezone(UTC).replace(tzinfo=None)


# Reusing this *expression*, never a timestamp value, makes compiler.bind_names
# contain exactly one clock bind even when independent/ClauseAdapter clock nodes
# occur multiple times. construct_params evaluates the callable once per execute.
_SQLITE_CLOCK = bindparam(
    "_caseops_statement_utc",
    callable_=_sqlite_clock_value,
    type_=DateTime(timezone=True),
)


class StatementUtc(FunctionElement[datetime]):
    type = DateTime(timezone=True)
    name = "caseops_statement_utc"
    inherit_cache = True

    def __init__(self):
        super().__init__()


@compiles(StatementUtc)
def _unsupported_clock(_element, _compiler, **_kw):
    raise CompileError("UTC statement time supports only PostgreSQL and SQLite.")


@compiles(StatementUtc, "postgresql")
def _postgres_clock(_element, _compiler, **_kw):
    return "statement_timestamp()"


@compiles(StatementUtc, "sqlite")
def _sqlite_clock(_element, compiler, **kw):
    return compiler.process(_SQLITE_CLOCK, **kw)
