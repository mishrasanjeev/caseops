"""Structural classification for test-only SQL read observations."""

from sqlalchemy.sql import visitors
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import TextualSelect


def is_read_only_select(statement):
    return bool(
        statement is not None
        and getattr(statement, "is_select", False)
        and not any(
            getattr(node, "is_dml", False) or isinstance(node, (TextClause, TextualSelect))
            for node in visitors.iterate(statement)
        )
    )
