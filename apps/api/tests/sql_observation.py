"""Structural classification for test-only SQL read observations."""

from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect
from sqlalchemy.sql.visitors import Visitable

_MAX_UNIQUE_NODES = 20_000
_MAX_RAW_EDGES = 100_000


def is_read_only_select(statement):
    if statement is None or not getattr(statement, "is_select", False):
        return False

    def children(node):
        if not isinstance(node, Visitable) or not callable(getattr(node, "get_children", None)):
            raise TypeError("SQL read observation requires traversable SQLAlchemy nodes")
        return iter(node.get_children())

    if getattr(statement, "is_dml", False) or isinstance(statement, (TextClause, TextualSelect)):
        return False

    # Retain the objects, not only ids: lazily produced children may otherwise
    # disappear and have their identities reused. Each frontier frame owns one
    # unique node, so the node cap also bounds frontier size and depth.
    seen = {id(statement): statement}
    active = {id(statement)}
    frontier = [(id(statement), children(statement))]
    edges = 0
    while frontier:
        node_id, iterator = frontier[-1]
        try:
            node = next(iterator)
        except StopIteration:
            active.remove(node_id)
            frontier.pop()
            continue
        edges += 1
        if edges > _MAX_RAW_EDGES:
            raise AssertionError("SQL read observation exceeded raw-edge limit")
        if not isinstance(node, Visitable) or not callable(getattr(node, "get_children", None)):
            raise TypeError("SQL read observation requires traversable SQLAlchemy nodes")
        node_id = id(node)
        if node_id in active:
            raise AssertionError("SQL read observation encountered a cyclic graph")
        if node_id in seen:
            continue
        if len(seen) >= _MAX_UNIQUE_NODES:
            raise AssertionError("SQL read observation exceeded unique-node limit")
        seen[node_id] = node
        if getattr(node, "is_dml", False) or isinstance(node, (TextClause, TextualSelect)):
            return False
        active.add(node_id)
        frontier.append((node_id, children(node)))
    return True
