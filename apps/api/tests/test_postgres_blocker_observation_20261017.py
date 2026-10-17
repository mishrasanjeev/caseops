"""The final actual wait snapshot must be evaluated without another query."""

from __future__ import annotations

import pytest

from tests import test_document_finalizer_overlap_20261009_postgres as overlap


def _observe(monkeypatch, *, ticks, snapshots):
    times = iter(ticks)
    pending = iter(snapshots)
    reads, sleeps, records, callbacks = [], [], [], []
    audit = overlap._FinalizerAudit(
        None, lambda kind, **data: records.append((kind, data)),
    )
    audit.pids.update(mutation=458, revocation=457)

    def monotonic():
        return next(times)

    def snapshot():
        rows = next(pending)
        reads.append(rows)
        return rows

    def sleep(seconds):
        assert seconds == 0.01
        sleeps.append(seconds)

    monkeypatch.setattr(overlap, "monotonic", monotonic)
    monkeypatch.setattr(overlap, "sleep", sleep)
    monkeypatch.setattr(audit, "snapshot", snapshot)
    return audit, reads, sleeps, records, callbacks


def _assert_positive(audit, reads, sleeps, records, callbacks, expected_rows, queries):
    returned = audit.await_blocker(
        "mutation", "revocation", on_observed=lambda: callbacks.append("observed"),
    )
    assert returned is expected_rows
    assert len(reads) == queries
    assert sleeps == [0.01] * (queries - 1)
    assert callbacks == ["observed"]
    assert len(records) == 1
    kind, detail = records[0]
    assert kind == "directed_blocker"
    assert detail["waiter"] == "mutation" and detail["holder"] == "revocation"
    assert detail["activity"] is expected_rows
    assert detail["release_signaled"] is False


@pytest.mark.parametrize("observed_at", [1.5, 1.622])
def test_actual_edge_in_deadline_tail_is_observed(monkeypatch, observed_at):
    absent = [{"pid": 458, "blockers": []}]
    actual = [{"pid": 458, "blockers": [457]}]
    fixture = _observe(
        monkeypatch, ticks=[0.0, 0.0, observed_at], snapshots=[absent, actual],
    )
    _assert_positive(*fixture, actual, 2)


def test_under_budget_actual_edge_needs_one_query(monkeypatch):
    actual = [{"pid": 458, "blockers": [457]}]
    fixture = _observe(monkeypatch, ticks=[0.0, 1.49], snapshots=[actual])
    _assert_positive(*fixture, actual, 1)


@pytest.mark.parametrize("rows", [
    [{"pid": 458, "blockers": [456]}, {"pid": 999, "blockers": [457]}],
    [],
], ids=["wrong-directed-edge", "absent-waiter"])
def test_expired_wrong_or_absent_edge_reuses_exact_final_snapshot(monkeypatch, rows):
    audit, reads, sleeps, records, callbacks = _observe(
        monkeypatch, ticks=[0.0, 1.5], snapshots=[rows],
    )
    with pytest.raises(AssertionError, match="Actual mutation -> revocation PostgreSQL wait"):
        audit.await_blocker(
            "mutation", "revocation", on_observed=lambda: callbacks.append("observed"),
        )
    assert reads == [rows] and reads[0] is rows
    assert sleeps == [] and callbacks == []
    assert len(records) == 1
    assert records[0][0] == "blocker_not_observed"
    assert records[0][1]["activity"] is rows


def test_under_budget_negative_polls_then_reuses_expired_absence(monkeypatch):
    wrong = [{"pid": 458, "blockers": [456]}]
    absent = [{"pid": 458, "blockers": []}]
    audit, reads, sleeps, records, callbacks = _observe(
        monkeypatch, ticks=[0.0, 0.25, 1.5], snapshots=[wrong, absent],
    )
    with pytest.raises(AssertionError, match="Actual mutation -> revocation PostgreSQL wait"):
        audit.await_blocker(
            "mutation", "revocation", on_observed=lambda: callbacks.append("observed"),
        )
    assert reads == [wrong, absent]
    assert sleeps == [0.01] and callbacks == []
    assert len(records) == 1
    assert records[0][0] == "blocker_not_observed"
    assert records[0][1]["activity"] is absent
