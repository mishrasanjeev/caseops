"""Allocation contracts beside the real PostgreSQL invalidation budget test."""

from itertools import islice
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import and_

from caseops_api.db.models import PrivateIndexProjection, PrivateSavedOutputAccess
from caseops_api.services.private_retrieval import _apply_private_invalidation


class _NarrowResult:
    def __init__(self, rows=(), *, rowcount=0):
        self.rows = iter(rows)
        self.rowcount = rowcount
        self.batch_sizes = []
        self.closed = False

    def partitions(self, size):
        assert size == 100
        while batch := list(islice(self.rows, size)):
            self.batch_sizes.append(len(batch))
            yield batch

    def close(self):
        self.closed = True


def _session(result, states=(), *, autoflush=True):
    return SimpleNamespace(
        autoflush=autoflush,
        _flushing=False,
        flush=Mock(),
        identity_map=SimpleNamespace(all_states=lambda: states),
        execute=Mock(return_value=result),
    )


def test_streamed_source_metadata_is_batched_without_an_orm_return_buffer():
    result = _NarrowResult(("matter", "same-matter") for _ in range(10_001))
    session = _session(result)
    count, sources = _apply_private_invalidation(
        session,
        model=PrivateIndexProjection,
        predicate=and_(
            PrivateIndexProjection.company_id == "tenant-a",
            PrivateIndexProjection.generation_id == "generation-a",
            PrivateIndexProjection.is_tombstoned.is_(False),
        ),
        values={"is_tombstoned": True, "content_text": "", "embedding_json": None},
        collect_sources=True,
    )
    assert (count, sources) == (10_001, {("matter", "same-matter")})
    assert result.batch_sizes == [100] * 100 + [1]
    assert result.closed
    session.flush.assert_called_once_with()
    statement = session.execute.call_args.args[0]
    assert str(statement.table.name) == "private_index_projections"
    assert statement.table is PrivateIndexProjection.__table__
    assert "parententity" not in statement.table._annotations
    assert not statement.get_execution_options().get("synchronize_session")
    assert [column.name for column in statement._returning] == ["source_type", "source_id"]
    assert {"tenant-a", "generation-a"} <= set(statement.compile().params.values())


def test_only_actual_returned_cached_rows_are_synchronized_without_attribute_reads():
    affected = PrivateSavedOutputAccess(id="affected", state="accessible")
    unchanged = PrivateSavedOutputAccess(id="prior-lock", state="locked", locked_reason="prior")
    states = [
        SimpleNamespace(class_=PrivateSavedOutputAccess, identity=(row.id,), object=row)
        for row in (affected, unchanged)
    ]
    result = _NarrowResult([("affected",)])
    session = _session(result, states)
    count, sources = _apply_private_invalidation(
        session,
        model=PrivateSavedOutputAccess,
        predicate=PrivateSavedOutputAccess.company_id == "tenant-a",
        values={"state": "locked", "locked_reason": "source_revoked"},
    )
    assert (count, sources) == (1, set())
    assert (affected.state, affected.locked_reason) == ("locked", "source_revoked")
    assert (unchanged.state, unchanged.locked_reason) == ("locked", "prior")
    assert result.closed
    assert session.execute.call_count == 1
    assert [column.name for column in session.execute.call_args.args[0]._returning] == ["id"]


def test_uncached_saved_output_invalidation_uses_rowcount_without_returning_ids():
    result = _NarrowResult(rowcount=10_000)
    session = _session(result, autoflush=False)
    assert _apply_private_invalidation(
        session,
        model=PrivateSavedOutputAccess,
        predicate=PrivateSavedOutputAccess.company_id == "tenant-a",
        values={"state": "locked"},
    ) == (10_000, set())
    assert not session.execute.call_args.args[0]._returning
    assert result.batch_sizes == []
    session.flush.assert_not_called()
    assert result.closed


def test_stream_failure_closes_result_and_propagates_without_partial_success():
    result = _NarrowResult([("missing-source-id",)])
    session = _session(result)
    with pytest.raises(IndexError):
        _apply_private_invalidation(
            session,
            model=PrivateIndexProjection,
            predicate=PrivateIndexProjection.company_id == "tenant-a",
            values={"is_tombstoned": True},
            collect_sources=True,
        )
    assert result.closed


def test_invalidation_does_not_recursively_autoflush_a_flushing_session():
    result = _NarrowResult(rowcount=0)
    session = _session(result)
    session._flushing = True
    assert _apply_private_invalidation(
        session,
        model=PrivateSavedOutputAccess,
        predicate=PrivateSavedOutputAccess.company_id == "tenant-a",
        values={"state": "locked"},
    ) == (0, set())
    session.flush.assert_not_called()
    assert result.closed
