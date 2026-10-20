"""Read-only observations accept CTE reads, never their writable/opaque siblings."""

import pytest
from sqlalchemy import (
    Integer,
    column,
    delete,
    insert,
    literal,
    select,
    table,
    text,
    union_all,
    update,
)
from sqlalchemy.dialects import postgresql, sqlite

from tests.sql_observation import is_read_only_select


def _statements():
    target = table("never_executed", column("id", Integer))
    plain = select(literal(1).label("id"))
    readable = plain.cte("readable")
    materialized = plain.cte("materialized").prefix_with("MATERIALIZED", dialect="postgresql")
    yield "plain", plain, True
    yield "cte", select(readable.c.id), True
    yield "materialized", select(materialized.c.id), True
    yield "union", union_all(plain, select(literal(2))), True
    mutations = [
        insert(target).values(id=1).returning(target.c.id),
        update(target).values(id=2).returning(target.c.id),
        delete(target).returning(target.c.id),
    ]
    for mutation in mutations:
        name = type(mutation).__name__.lower()
        yield name, mutation, False
        wrapped = select(literal(1)).add_cte(mutation.cte(f"writable_{name}"))
        assert wrapped.is_select
        yield f"cte_{name}", wrapped, False
    yield "text", text("WITH readable AS (SELECT 1) SELECT * FROM readable"), False
    opaque = text("SELECT 1 AS id").columns(id=Integer)
    yield "textual_select", opaque, False
    yield "wrapped_textual_select", select(opaque.cte("opaque").c.id), False
    yield "textual_predicate", plain.where(text("1 = 1")), False


CASES = list(_statements())


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["pg", "sqlite"])
@pytest.mark.parametrize("_name,statement,expected", CASES, ids=[row[0] for row in CASES])
def test_structured_read_only_observation(dialect, _name, statement, expected):
    compiled = statement.compile(dialect=dialect)
    assert compiled.statement is statement
    assert is_read_only_select(compiled.statement) is expected


def test_uncompiled_statement_is_not_assumed_read_only():
    assert not is_read_only_select(None)
