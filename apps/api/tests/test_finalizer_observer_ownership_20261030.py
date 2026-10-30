"""Stopped native diagnostics must not retain their large buffers in a cycle."""

import gc
from types import SimpleNamespace
from weakref import ref

import pytest

from tests.test_document_finalizer_overlap_20261009_postgres import (
    _FinalizerAudit,
    _PassiveOverlapTiming,
)


@pytest.mark.parametrize("capture", ["never-started", "completed", "body-failed"])
def test_detached_stopped_observer_releases_native_cells_without_collecting(capture):
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    owner = SimpleNamespace()
    timing = _PassiveOverlapTiming()
    owner.passive = timing
    observer_ref = ref(timing)
    native_cell_ref = ref(timing.gc_slots[0].mono)
    if capture != "never-started":
        try:
            with timing.capture():
                if capture == "body-failed":
                    raise ValueError("Controlled observer body failure")
        except ValueError:
            assert capture == "body-failed"
    assert not timing.enabled and timing.callback not in gc.callbacks
    del timing
    assert observer_ref() is owner.passive and native_cell_ref() is not None
    owner.passive = None
    assert observer_ref() is None, "Stopped callback must not keep its owner in a cycle."
    assert native_cell_ref() is None, "Native timing cells must leave with their owner."
    assert gc.callbacks == callbacks
    assert (gc.isenabled(), gc.get_threshold()) == policy


def test_registered_callback_keeps_observer_alive_until_stop():
    callbacks = list(gc.callbacks)
    timing = _PassiveOverlapTiming(sql_cap=1, gc_cap=4)
    observer_ref = ref(timing)
    timing.start()
    del timing
    try:
        assert observer_ref() is not None
        assert observer_ref().callback in gc.callbacks
    finally:
        observer_ref().stop()
    assert observer_ref() is None
    assert gc.callbacks == callbacks


@pytest.mark.parametrize("outcome", ["complete", "incomplete", "write-failed"])
def test_owned_flush_detaches_recorder_after_evidence_attempt(outcome):
    receipts = []

    def record(kind, **data):
        if outcome == "write-failed":
            raise OSError("Controlled evidence write failure")
        receipts.append({"event": kind, **data})

    audit = _FinalizerAudit(None, record)
    timing = _PassiveOverlapTiming(sql_cap=1, gc_cap=4)
    audit.passive = timing
    observer_ref = ref(timing)
    native_cell_ref = ref(timing.gc_slots[0].mono)
    if outcome == "incomplete":
        timing.invalid = True
    del timing
    if outcome == "complete":
        audit.flush_passive_evidence()
        assert receipts[0]["complete"]
    elif outcome == "incomplete":
        with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
            audit.flush_passive_evidence()
        assert not receipts[0]["complete"]
    else:
        with pytest.raises(OSError, match="Controlled evidence write failure"):
            audit.flush_passive_evidence()
        assert receipts == []
    assert audit.passive is None and observer_ref() is None
    assert native_cell_ref() is None


@pytest.mark.parametrize("active", ["callback", "workers"])
def test_owned_flush_never_detaches_active_capture_or_workers(active):
    audit = _FinalizerAudit(
        None, lambda *_args, **_kwargs: pytest.fail("Unexpected evidence flush")
    )
    timing = _PassiveOverlapTiming(sql_cap=1, gc_cap=4)
    audit.passive = timing
    if active == "callback":
        timing.start()
    else:
        timing.critical_pools = 1
    try:
        with pytest.raises(AssertionError, match="Passive capture is active|owned worker timing"):
            audit.flush_passive_evidence()
        assert audit.passive is timing
        assert len(timing.sql_slots) == 1 and len(timing.gc_slots) == 4
    finally:
        timing.stop()
        timing.critical_pools = 0
        audit.record = lambda *_args, **_kwargs: None
        audit.flush_passive_evidence()
