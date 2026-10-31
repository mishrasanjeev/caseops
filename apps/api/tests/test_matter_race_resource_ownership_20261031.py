"""Owned Matter race hooks release only after their workers have stopped.

No connections, SQL, migrations or HTTP: the observation transport is doubled;
actual SQLAlchemy listeners and owned executors exercise resource ownership.
"""

from io import StringIO
from threading import Event
from types import SimpleNamespace
from weakref import ref

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests import test_matter_writer_admission_postgres as admission

_HOOK_NAMES = ("before_cursor_execute", "after_cursor_execute", "handle_error", "commit")


def _forbid_connect(*_args, **_kwargs):
    raise AssertionError("Ownership-only unit candidate must not connect")


class _CloseObserver:
    """Explicit PostgreSQL observation double for pure close-path cases only."""

    def __init__(self):
        self.snapshots = self.disposals = 0

    def connect(self, *_args, **_kwargs):
        raise AssertionError("Ownership-only close must not connect")

    def snapshot(self):
        self.snapshots += 1
        return {"activity": [], "locks": []}

    def dispose(self):
        self.disposals += 1


def _registered_race(*, close_only=False):
    engine = create_engine("sqlite+pysqlite://", poolclass=NullPool)
    event.listen(engine, "do_connect", _forbid_connect)
    evidence = StringIO()
    race = admission._Race(engine, evidence, autoflush=False)
    event.listen(race.observer, "do_connect", _forbid_connect)
    if close_only:
        # __init__ really created this observer; dispose it without connecting.
        race.observer.dispose()
        race.observer = _CloseObserver()
        race.snapshot = race.observer.snapshot
    race.record("ownership_witness")
    race.sql["worker"] = ["ownership_template_not_executed"]
    race.pids["worker"] = 12345
    race.names["worker"] = "matter-ownership-unit"
    future = race.submit("worker", lambda: "owned-result")
    result = future.result(timeout=5)
    assert result == "owned-result"
    return SimpleNamespace(
        engine=engine, hooks=race.hooks, race_ref=ref(race), evidence_ref=ref(evidence),
        pool=race.pool, observer=race.observer, future_count=1,
        diagnostics=(race.sql, race.futures, race.pids, race.names),
    )


def _assert_diagnostics(owned):
    sql, futures, pids, names = owned.diagnostics
    assert sql == {"worker": ["ownership_template_not_executed"]}
    assert len(futures) == owned.future_count and futures[0].done()
    result = futures[0].result(timeout=5)
    assert result == "owned-result"
    assert pids == {"worker": 12345} and names == {"worker": "matter-ownership-unit"}
    race = owned.race_ref()
    if race is not None:
        assert race.sql is sql and race.futures is futures
        assert race.pids is pids and race.names is names
        assert race.evidence is owned.evidence_ref()
        assert '"event": "ownership_witness"' in race.evidence.getvalue()


def _assert_owned(owned, *, registered=True):
    assert owned.race_ref().hooks is owned.hooks
    assert tuple(name for name, _ in owned.hooks) == _HOOK_NAMES
    assert all(callback.__self__ is owned.race_ref() for _, callback in owned.hooks)
    if registered:
        assert all(event.contains(owned.engine, name, callback) for name, callback in owned.hooks)
    _assert_diagnostics(owned)


def _assert_released(owned):
    assert owned.hooks == [], "The exact rooted bound-hook list must be emptied by the harness."
    assert owned.race_ref() is None and owned.evidence_ref() is None
    _assert_diagnostics(owned)
    assert all(future.done() for future in owned.diagnostics[1])
    with pytest.raises(RuntimeError, match="cannot schedule new futures after shutdown"):
        owned.pool.submit(lambda: None)


def _stop_owned_workers(owned):
    # Arrange only direct-detach tests. Real close must establish its own flag.
    assert owned.race_ref().workers_stopped is False
    assert all(future.done() for future in owned.diagnostics[1])
    owned.pool.shutdown(wait=True, cancel_futures=True)
    owned.race_ref().workers_stopped = True


def _cleanup(owned):
    # Failure hygiene only: never clear hooks, futures, SQL, or other evidence.
    if owned.race_ref() is not None:
        owned.race_ref().release.set()
    try:
        owned.pool.shutdown(wait=True, cancel_futures=True)
        for name, callback in owned.hooks:
            if event.contains(owned.engine, name, callback):
                event.remove(owned.engine, name, callback)
    finally:
        try:
            owned.observer.dispose()
        finally:
            owned.engine.dispose()


def _body_then_close(owned, *, body_error):
    try:
        if body_error:
            raise ValueError("Controlled matter race body failure")
    finally:
        owned.race_ref().close()


def _check_real_close(*, body_error):
    owned = _registered_race(close_only=True)
    try:
        _assert_owned(owned)
        if body_error:
            with pytest.raises(ValueError, match="^Controlled matter race body failure$"):
                _body_then_close(owned, body_error=True)
        else:
            _body_then_close(owned, body_error=False)
        # On immutable998A, close returns and this exact-list assertion exposes
        # retained bound callbacks before any proposed API is consulted.
        _assert_released(owned)
        assert owned.observer.snapshots == 1 and owned.observer.disposals == 1
    finally:
        _cleanup(owned)


def test_real_close_releases_exact_rooted_hooks_without_collection():
    _check_real_close(body_error=False)


def test_real_close_after_body_error_releases_exact_rooted_hooks_without_collection():
    _check_real_close(body_error=True)


def test_detach_is_idempotent_and_preserves_an_unowned_listener():
    owned = _registered_race()
    calls = []

    def unrelated(*_args):
        calls.append("unrelated")

    def detach_twice():
        race = owned.race_ref()
        result = race.detach_hooks()
        assert result is None
        assert race.hooks is owned.hooks and owned.hooks == []
        _assert_diagnostics(owned)
        result = race.detach_hooks()
        assert result is None

    event.listen(owned.engine, "before_cursor_execute", unrelated)
    try:
        _assert_owned(owned)
        _stop_owned_workers(owned)
        detach_twice()
        assert event.contains(owned.engine, "before_cursor_execute", unrelated)
        assert calls == []
        _assert_released(owned)
    finally:
        event.remove(owned.engine, "before_cursor_execute", unrelated)
        _cleanup(owned)


def test_retained_closed_session_does_not_own_the_stopped_race(monkeypatch):
    owned = _registered_race()
    session = None
    try:
        # Only registration ownership is exercised, not the PostgreSQL SET protocol.
        with monkeypatch.context() as patch:
            patch.setattr(Session, "connection", lambda *_args, **_kwargs: None)
            session = owned.race_ref().session("worker")
        session.close()
        assert len(session.dispatch.after_begin) == 1
        _stop_owned_workers(owned)
        owned.race_ref().detach_hooks()
        _assert_released(owned)
        with pytest.raises(AssertionError, match="Owned race is no longer available"):
            session.dispatch.after_begin(session, SimpleNamespace(nested=False), None)
    finally:
        if session is not None:
            session.close()
        _cleanup(owned)


def test_detach_refuses_idle_unstopped_pool_and_active_owned_worker():
    owned = _registered_race()
    started, release = Event(), owned.race_ref().release
    future = None

    def work():
        started.set()
        released = release.wait(5)
        assert released, "Ownership-only worker was not released"
        return "active-result"

    try:
        assert owned.race_ref().workers_stopped is False
        with pytest.raises(AssertionError, match="Owned workers are still active"):
            owned.race_ref().detach_hooks()
        _assert_owned(owned)
        future = owned.race_ref().submit("held-worker", work)
        owned.future_count = 2
        entered = started.wait(5)
        assert entered and not future.done()
        with pytest.raises(AssertionError, match="Owned workers are still active"):
            owned.race_ref().detach_hooks()
        assert owned.race_ref().workers_stopped is False
        _assert_owned(owned)
        release.set()
        result = future.result(timeout=5)
        assert result == "active-result"
        _stop_owned_workers(owned)
        owned.race_ref().detach_hooks()
        _assert_released(owned)
    finally:
        release.set()
        try:
            if future is not None:
                future.result(timeout=5)
        finally:
            _cleanup(owned)


def test_detach_refuses_enabled_passive_capture_after_real_pool_shutdown():
    owned = _registered_race()
    # Only enabled-state metadata is doubled; no GC callback is installed.
    passive = SimpleNamespace(enabled=True, critical_pools=0, callback=_forbid_connect)
    try:
        _stop_owned_workers(owned)
        owned.race_ref().passive = passive
        with pytest.raises(AssertionError, match="Passive capture is active"):
            owned.race_ref().detach_hooks()
        assert owned.race_ref().workers_stopped is True
        _assert_owned(owned)
        passive.enabled = False
        owned.race_ref().detach_hooks()
        _assert_released(owned)
    finally:
        passive.enabled = False
        _cleanup(owned)


def test_partial_removal_keeps_exact_owned_list_and_diagnostics_until_retry(monkeypatch):
    owned = _registered_race()
    removals = []

    def fail_second_removal(target, name, callback):
        removals.append(name)
        if name == "after_cursor_execute":
            raise RuntimeError("Controlled matter listener removal failure")
        event.remove(target, name, callback)

    try:
        _stop_owned_workers(owned)
        with monkeypatch.context() as patch:
            patch.setattr(admission, "event", SimpleNamespace(
                contains=event.contains, remove=fail_second_removal,
            ))
            with pytest.raises(RuntimeError, match="^Controlled matter listener removal failure$"):
                owned.race_ref().detach_hooks()
        assert removals == list(_HOOK_NAMES[:2])
        _assert_owned(owned, registered=False)
        assert not event.contains(owned.engine, *owned.hooks[0])
        assert all(
            event.contains(owned.engine, name, callback) for name, callback in owned.hooks[1:]
        )
        assert owned.race_ref().workers_stopped is True
        result = owned.race_ref().detach_hooks()
        assert result is None
        _assert_released(owned)
    finally:
        _cleanup(owned)


@pytest.mark.parametrize("shutdown_error", [False, True], ids=["drained", "shutdown-error-retry"])
def test_close_publishes_stopped_only_after_shutdown_returns(monkeypatch, shutdown_error):
    owned = _registered_race(close_only=True)
    real_shutdown = owned.pool.shutdown
    shutdowns = []

    def shutdown(*, wait, cancel_futures):
        assert wait is True and cancel_futures is True
        assert owned.race_ref().workers_stopped is False
        if shutdown_error and not shutdowns:
            shutdowns.append("failed")
            raise RuntimeError("Controlled owned pool shutdown failure")
        real_shutdown(wait=wait, cancel_futures=cancel_futures)
        assert owned.race_ref().workers_stopped is False
        shutdowns.append("stopped")

    def remove(target, name, callback):
        assert shutdowns[-1] == "stopped"
        assert owned.race_ref().workers_stopped is True
        assert target is owned.engine and callback.__self__ is owned.race_ref()
        event.remove(target, name, callback)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(owned.pool, "shutdown", shutdown)
            patch.setattr(
                admission, "event", SimpleNamespace(contains=event.contains, remove=remove)
            )
            if shutdown_error:
                with pytest.raises(RuntimeError, match="^Controlled owned pool shutdown failure$"):
                    owned.race_ref().close()
                assert owned.race_ref().workers_stopped is False
                _assert_owned(owned)
                assert owned.observer.snapshots == 0 and owned.observer.disposals == 0
            result = owned.race_ref().close()
            assert result is None
        _assert_released(owned)
        assert shutdowns == (["failed", "stopped"] if shutdown_error else ["stopped"])
        assert owned.observer.snapshots == 1 and owned.observer.disposals == 1
    finally:
        _cleanup(owned)


