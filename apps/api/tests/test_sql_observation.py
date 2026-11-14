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
from sqlalchemy.sql.elements import ClauseElement
from sqlalchemy.sql.visitors import InternalTraversal

from caseops_api.db.models import IpDocketRecord, TrademarkApplication
from tests import sql_observation
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


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["pg", "sqlite"])
@pytest.mark.parametrize("kind", ["plain", "opaque", "writable"])
def test_orm_projection_retains_internal_entity_traversal_and_write_rejection(dialect, kind):
    statement = (
        select(TrademarkApplication, IpDocketRecord)
        .join(IpDocketRecord, IpDocketRecord.id == TrademarkApplication.docket_id)
        .with_only_columns(
            TrademarkApplication.id, TrademarkApplication.updated_at, maintain_column_froms=True
        )
    )
    if kind == "opaque":
        statement = statement.where(text("1 = 1"))
    elif kind == "writable":
        target = table("never_executed_orm_projection", column("id", Integer))
        statement = statement.add_cte(delete(target).returning(target.c.id).cte("writable_orm"))
    compiled = statement.compile(dialect=dialect).statement
    nodes, _edges = _inventory(compiled)
    assert any(not isinstance(node, ClauseElement) for node in nodes.values())
    assert is_read_only_select(compiled) is (kind == "plain")


def _shared_cte(depth=12):
    shared = select(literal(1).label("id")).cte("shared_0")
    for index in range(depth):
        shared = union_all(select(shared.c.id), select(shared.c.id)).cte(f"shared_{index + 1}")
    return select(shared.c.id)


def _inventory(statement):
    nodes = {}
    pending = [statement]
    edges = 0
    while pending:
        node = pending.pop()
        if id(node) in nodes:
            continue
        nodes[id(node)] = node
        children = list(node.get_children())
        edges += len(children)
        pending.extend(children)
        assert len(nodes) < 1_000 and edges < 5_000, "unexpected proof-fixture growth"
    return nodes, edges


def _count_children(monkeypatch, nodes, max_calls=2_000):
    calls = []
    for kind in {type(node) for node in nodes.values()}:
        original = kind.get_children

        def counted(self, _original=original, **kwargs):
            calls.append(id(self))
            if len(calls) > max_calls:
                raise AssertionError(
                    f"bounded proof: repeated get_children work exceeded {max_calls}"
                )
            return _original(self, **kwargs)

        monkeypatch.setattr(kind, "get_children", counted)
    return calls


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["pg", "sqlite"])
def test_real_compiled_shared_cte_traverses_each_identity_once(
    monkeypatch, dialect, record_property
):
    statement = _shared_cte().compile(dialect=dialect).statement
    nodes, edges = _inventory(statement)
    assert len(nodes) < 150 and edges < 250
    calls = _count_children(monkeypatch, nodes)
    assert is_read_only_select(statement)
    assert len(calls) == len(nodes)
    assert set(calls) == set(nodes)
    record_property("unique_nodes", len(nodes))
    record_property("raw_edges", edges)
    record_property("get_children_calls", len(calls))


class _GraphNode(ClauseElement):
    """Use SQLAlchemy's real generated get_children for adversarial graphs."""

    is_select = True
    _traverse_internals = [("edges", InternalTraversal.dp_clauseelement_list)]

    def __init__(self, edges=()):
        self.edges = list(edges)


def _chain(size, tail=None):
    node = _GraphNode() if tail is None else tail
    for _ in range(size - 1):
        node = _GraphNode([node])
    return node


def test_default_observation_limits_are_explicit():
    assert sql_observation._MAX_UNIQUE_NODES == 20_000
    assert sql_observation._MAX_RAW_EDGES == 100_000


@pytest.mark.parametrize("dialect", [postgresql.dialect(), sqlite.dialect()], ids=["pg", "sqlite"])
def test_recursive_cte_is_a_supported_finite_clause_graph(dialect):
    seed = select(literal(1).label("id")).cte("recursive_read", recursive=True)
    recursive = seed.union_all(select(seed.c.id + 1).where(seed.c.id < 3))
    assert is_read_only_select(select(recursive.c.id).compile(dialect=dialect).statement)


def test_real_duplicate_edges_are_expanded_only_once(monkeypatch):
    value = literal(1)
    statement = select(*([value] * 1_000))
    nodes, edges = _inventory(statement)
    assert len(nodes) == 2 and edges == 1_000
    calls = _count_children(monkeypatch, nodes)
    assert is_read_only_select(statement)
    assert len(calls) == 2


@pytest.mark.parametrize("extra", [0, 1], ids=["at-limit", "over-limit"])
def test_deep_unique_node_and_frontier_limit(monkeypatch, extra):
    limit = sql_observation._MAX_UNIQUE_NODES
    statement = _chain(limit + extra)
    calls = _count_children(monkeypatch, {id(statement): statement}, max_calls=limit)
    if extra:
        with pytest.raises(AssertionError, match="unique-node limit"):
            is_read_only_select(statement)
    else:
        assert is_read_only_select(statement)
    assert len(calls) == limit


@pytest.mark.parametrize("extra", [0, 1], ids=["at-limit", "over-limit"])
def test_duplicate_raw_edges_are_charged_before_deduplication(monkeypatch, extra):
    limit = sql_observation._MAX_RAW_EDGES
    leaf = _GraphNode()
    statement = _GraphNode([leaf] * (limit + extra))
    calls = _count_children(monkeypatch, {id(statement): statement})
    if extra:
        with pytest.raises(AssertionError, match="raw-edge limit"):
            is_read_only_select(statement)
    else:
        assert is_read_only_select(statement)
    assert len(calls) == 2


@pytest.mark.parametrize("size,over_limit", [(420, False), (450, True)], ids=["below", "above"])
def test_dense_dag_is_bounded_by_raw_edges_not_unique_nodes(monkeypatch, size, over_limit):
    nodes = [_GraphNode() for _ in range(size)]
    for index, node in enumerate(nodes):
        node.edges = nodes[index + 1 :]
    assert size < sql_observation._MAX_UNIQUE_NODES
    calls = _count_children(monkeypatch, {id(node): node for node in nodes})
    if over_limit:
        with pytest.raises(AssertionError, match="raw-edge limit"):
            is_read_only_select(nodes[0])
    else:
        assert is_read_only_select(nodes[0])
    assert len(calls) == size


@pytest.mark.parametrize("size", [1, 2, 200], ids=["self", "pair", "deep"])
def test_cyclic_graph_is_not_silently_accepted(monkeypatch, size):
    nodes = [_GraphNode() for _ in range(size)]
    for index, node in enumerate(nodes):
        node.edges = [nodes[(index + 1) % size]]
    calls = _count_children(monkeypatch, {id(node): node for node in nodes})
    with pytest.raises(AssertionError, match="cyclic graph"):
        is_read_only_select(nodes[0])
    assert len(calls) == size


NEGATIVES = [(name, statement) for name, statement, expected in CASES if not expected]


@pytest.mark.parametrize("_name,negative", NEGATIVES, ids=[row[0] for row in NEGATIVES])
def test_late_nested_dml_and_text_remain_rejected(monkeypatch, _name, negative):
    shared = _shared_cte()
    prefix_nodes, _ = _inventory(shared)
    statement = _GraphNode([shared, shared, negative])
    nodes, _ = _inventory(statement)
    calls = _count_children(monkeypatch, nodes)
    assert is_read_only_select(statement) is False
    assert set(prefix_nodes) <= set(calls)
    assert len(calls) == len(set(calls))


@pytest.mark.parametrize("_name,negative", NEGATIVES, ids=[row[0] for row in NEGATIVES])
@pytest.mark.parametrize("bound", ["nodes", "edges"])
def test_unexamined_late_negatives_beyond_bounds_never_false_accept(bound, _name, negative):
    if bound == "nodes":
        statement = _chain(sql_observation._MAX_UNIQUE_NODES + 1, tail=negative)
        message = "unique-node limit"
    else:
        leaf = _GraphNode()
        statement = _GraphNode([leaf] * sql_observation._MAX_RAW_EDGES + [negative])
        message = "raw-edge limit"
    with pytest.raises(AssertionError, match=message):
        is_read_only_select(statement)


@pytest.mark.parametrize(
    "unsupported", [None, object(), "SELECT 1"], ids=["none", "object", "string"]
)
def test_unsupported_children_cannot_prove_read_only(unsupported):
    with pytest.raises(TypeError, match="traversable SQLAlchemy"):
        is_read_only_select(_GraphNode([unsupported]))


def test_select_looking_non_clause_root_is_not_accepted():
    class Unsupported:
        is_select = True

        def get_children(self):
            return ()

    with pytest.raises(TypeError, match="traversable SQLAlchemy"):
        is_read_only_select(Unsupported())


def test_traversal_failure_is_not_swallowed():
    class Broken(_GraphNode):
        def get_children(self, **kwargs):
            raise RuntimeError("unsupported traversal")

    with pytest.raises(RuntimeError, match="unsupported traversal"):
        is_read_only_select(Broken())


def test_infinite_duplicate_child_iterator_stops_at_raw_edge_limit():
    leaf = _GraphNode()
    consumed = 0

    class Infinite(_GraphNode):
        def get_children(self, **kwargs):
            nonlocal consumed
            while True:
                consumed += 1
                yield leaf

    with pytest.raises(AssertionError, match="raw-edge limit"):
        is_read_only_select(Infinite())
    assert consumed == sql_observation._MAX_RAW_EDGES + 1


def test_seen_nodes_keep_strong_references_for_lazy_children():
    import weakref

    retained = weakref.WeakSet()

    class Lazy(_GraphNode):
        def get_children(self, **kwargs):
            for index in range(500):
                assert len(retained) == index
                node = _GraphNode()
                retained.add(node)
                yield node

    assert is_read_only_select(Lazy())


def test_identity_deduplication_does_not_call_sql_equality_or_hash():
    class IdentityOnly(_GraphNode):
        def __eq__(self, other):
            raise AssertionError("SQL equality must not be invoked")

        def __hash__(self):
            raise AssertionError("SQL hash must not be invoked")

    left, right = IdentityOnly(), IdentityOnly()
    assert is_read_only_select(_GraphNode([left, right, left, right]))
