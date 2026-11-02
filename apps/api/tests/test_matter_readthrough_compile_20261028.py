"""Real packed parent/anchor compilation retains statement-local CTE identity.

These pure compiler tests open no engine connection and issue no SQL. The
retained failed PostgreSQL HTTP reverse-source case is separate runtime proof.
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import and_, column, select, tuple_
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg
from sqlalchemy.sql import visitors
from sqlalchemy.sql.selectable import CTE

from caseops_api.db.models import HearingPackItem, Recommendation
from caseops_api.db.session import _proven_read_statement
from caseops_api.services import matter_readthrough as reads
from caseops_api.services import matter_readthrough_pages as pages
from tests.sql_observation import is_read_only_select


def context(role="owner"):
    return SimpleNamespace(
        company=SimpleNamespace(id="compile-company"),
        user=SimpleNamespace(id="compile-user"),
        membership=SimpleNamespace(id="compile-member", role=role),
    )


def session():
    return SimpleNamespace(
        get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    )


def scope():
    return SimpleNamespace(matter_id="compile-matter", matter_lifecycle_version=1)


def item_statement(role="owner"):
    current = session()
    return select(
        HearingPackItem.id,
        HearingPackItem.rank,
        HearingPackItem.created_at,
        *reads._prefix(current, HearingPackItem.body),
    ).where(
        HearingPackItem.pack_id == "compile-pack",
        reads._pack_exists(
            current,
            context(role),
            scope(),
            "compile-pack",
        ),
    )


def ctes(expression):
    return {id(node): node for node in visitors.iterate(expression) if isinstance(node, CTE)}


def test_parent_predicate_rebinds_foreign_key_without_cloning_unrelated_cte_definitions():
    statement = item_statement()
    expression = and_(*statement._where_criteria)
    original = ctes(expression)
    assert original
    target = column("decoded_pack_id")
    transformed = pages._adapt(expression, HearingPackItem, {"pack_id": target})
    retained = ctes(transformed)
    assert set(retained) == set(original)
    assert all(retained[key] is original[key] for key in original)
    assert any(node is target for node in visitors.iterate(transformed))
    assert not any(
        getattr(node, "table", None) is HearingPackItem.__table__
        and getattr(node, "key", None) == "pack_id"
        for node in visitors.iterate(transformed)
    )


def test_unrelated_live_matter_policy_is_reused_without_rewriting_authority():
    expression = reads._matter_exists(session(), context("viewer"), scope())
    transformed = pages._adapt(expression, HearingPackItem, {"pack_id": column("decoded_pack")})
    assert transformed is expression


def constructed_reads(statement):
    current = session()
    common = dict(
        company_id="compile-company",
        matter_id="compile-matter",
        layout="rank",
        parent_id="compile-pack",
        key=HearingPackItem.rank,
        ascending=True,
    )
    yield pages.page_statement(current, statement, HearingPackItem, limit=25, **common)
    yield pages.point_statement(
        current,
        statement.with_only_columns(
            HearingPackItem.id,
            HearingPackItem.rank,
            maintain_column_froms=True,
        ),
        HearingPackItem,
        identity="compile-target",
        anchor_key=-2,
        **common,
    )
    yield pages.page_statement(
        current,
        statement.where(
            tuple_(HearingPackItem.rank, HearingPackItem.id) > tuple_(-2, "compile-target")
        ),
        HearingPackItem,
        limit=25,
        after=(-2, "compile-target"),
        **common,
    )


def test_engine_compiler_first_anchor_and_continuation_with_retained_parent_paths():
    # The engine compilation entry (including cache-key generation) exposed the
    # real failure; a single standalone str(Select) compilation had passed.
    dialect, cache = PGDialect_psycopg(), {}
    retained = []
    for _ in range(8):
        statement = item_statement()
        for query in constructed_reads(statement):
            compiled, _binds, _status = query._compile_w_cache(
                dialect,
                compiled_cache=cache,
                column_keys=[],
            )
            assert compiled.string
            retained.append(query)
    assert len(retained) == 24
    # Recompile the same retained trees after independent constructions.
    for query in retained:
        compiled, _binds, _status = query._compile_w_cache(
            dialect,
            compiled_cache=cache,
            column_keys=[],
        )
        assert compiled.string


@pytest.mark.parametrize("role", ["owner", "viewer"])
def test_full_parent_read_compilation_preserves_typed_readonly_guard(role):
    for query in constructed_reads(item_statement(role)):
        assert is_read_only_select(query) and _proven_read_statement(query)
        compiled = query.compile(dialect=PGDialect_psycopg())
        assert compiled.string
    # Native timestamp anchors keep microsecond precision in their bind value;
    # this is a compiler contract, not a database timestamp/clock acceptance.
    stamp = datetime(2026, 1, 1, microsecond=123456, tzinfo=UTC)
    statement = reads._recommendation_statement(
        session(), context(role), scope()
    ).with_only_columns(
        Recommendation.id,
        Recommendation.created_at,
        maintain_column_froms=True,
    )
    query = pages.point_statement(
        session(),
        statement,
        Recommendation,
        company_id="compile-company",
        matter_id="compile-matter",
        identity="compile-rec",
        layout="chron",
        key=Recommendation.created_at,
        ascending=False,
        anchor_key=stamp,
    )
    assert is_read_only_select(query) and _proven_read_statement(query)
    compiled = query.compile(dialect=PGDialect_psycopg())
    timestamps = [value for value in compiled.params.values() if isinstance(value, datetime)]
    assert timestamps and all(
        value == stamp and value.microsecond == 123456 for value in timestamps
    )


def test_materialized_anonymous_cte_retains_name_origin_through_session_engine_compile(
    monkeypatch,
):
    # SQLAlchemy's generative prefix copies an anonymous name. Its originating
    # object must remain alive while any returned tree retains that name: a
    # later real CTE allocation can otherwise reuse its numeric identity.
    import gc
    import weakref

    from sqlalchemy import create_engine
    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session

    origins = []
    original_init = CTE._init

    def observe_init(cte, *args, **kwargs):
        original_init(cte, *args, **kwargs)
        origins.append((str(cte.name), weakref.ref(cte)))

    monkeypatch.setattr(CTE, "_init", observe_init)
    queries = list(constructed_reads(item_statement()))
    names = {str(cte.name) for query in queries for cte in ctes(query).values()}
    retained_origins = [(name, origin) for name, origin in origins if name in names]
    assert retained_origins and len(retained_origins) == len(names)
    gc.collect()
    assert all(origin() is not None for _name, origin in retained_origins)

    class CompiledBoundary(Exception):
        pass

    class NoDatabase:
        is_valid = True

        def __init__(self):
            self.info = {}

        def cursor(self, *_args, **_kwargs):
            raise AssertionError("Compiler contract must never create a database cursor")

        def rollback(self):
            pass

        def close(self):
            pass

    def no_connect():
        raise AssertionError("Compiler contract must never connect to a database")

    engine = create_engine("postgresql+psycopg://", creator=no_connect)
    connection = Connection(engine, connection=NoDatabase(), _allow_revalidate=False)
    compiled = []

    def stop_after_real_compile(_dialect, _constructor, statement, *args, **kwargs):
        compiled.append(statement)
        raise CompiledBoundary

    # Session.execute and Connection._execute_clauseelement run their real
    # pinned ORM/compiler/cache path. Stop only at execution-context creation,
    # strictly after compilation and before any driver cursor or database I/O.
    monkeypatch.setattr(connection, "_execute_context", stop_after_real_compile)
    try:
        with Session(bind=connection) as current:
            for query in queries:
                assert is_read_only_select(query) and _proven_read_statement(query)
                with pytest.raises(CompiledBoundary):
                    current.execute(query)
        assert len(compiled) == len(queries) == 3
        assert all(origin() is not None for _name, origin in retained_origins)
    finally:
        connection.close()
        engine.dispose()
