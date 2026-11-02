"""Stopped audit and server dependencies release only their owned resources."""

import asyncio
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from weakref import ref

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, event
from sqlalchemy.pool import NullPool

from tests import test_document_finalizer_overlap_20261009_postgres as overlap


def _registered_audit():
    # No connection, SQL, migrations, tenant records, or server is created here.
    engine = create_engine("sqlite+pysqlite://", poolclass=NullPool)
    journal = overlap._FinalizerJournal(StringIO(), Path("ownership-only.jsonl"), "ownership")
    audit = overlap._FinalizerAudit(engine, journal.record)
    audit.record("ownership_witness")
    audit.statements["worker"] = ["SELECT ownership_template"]
    audit.statement_counts["worker"] = 1
    for name, callback in audit.hooks:
        event.listen(engine, name, callback)
    return engine, audit.hooks, ref(audit), ref(journal)


def _assert_audit_roots(engine, hooks, audit_ref, journal_ref):
    assert len(hooks) == 3
    assert audit_ref().hooks is hooks
    assert all(callback.__self__ is audit_ref() for _, callback in hooks)
    assert all(event.contains(engine, name, callback) for name, callback in hooks)
    assert audit_ref().record.__self__ is journal_ref()
    assert journal_ref().records == 1


@pytest.mark.parametrize("body_error", [False, True])
def test_owned_hook_detach_releases_audit_and_journal_without_collection(body_error):
    engine, hooks, audit_ref, journal_ref = _registered_audit()
    try:
        _assert_audit_roots(engine, hooks, audit_ref, journal_ref)
        # These are independent snapshots, not another bound-method owner.
        statements = audit_ref().statements
        counts = audit_ref().statement_counts
        if body_error:
            with pytest.raises(ValueError, match="^Controlled audit body failure$"):
                try:
                    raise ValueError("Controlled audit body failure")
                finally:
                    audit_ref().detach_hooks()
        else:
            assert audit_ref().detach_hooks() is None
        assert hooks == [], "The exact rooted, audit-owned list must be emptied."
        engine.dispose()
        assert audit_ref() is None and journal_ref() is None
        assert statements == {"worker": ["SELECT ownership_template"]}
        assert counts == {"worker": 1}
    finally:
        if audit_ref() is not None:
            audit_ref().detach_hooks()
        engine.dispose()


def test_hook_detach_is_idempotent_and_leaves_unowned_listeners():
    engine, hooks, audit_ref, journal_ref = _registered_audit()
    calls = []

    def unrelated(*_args):
        calls.append("unrelated")

    event.listen(engine, "before_cursor_execute", unrelated)

    def detach_twice():
        audit = audit_ref()
        audit.detach_hooks()
        assert audit.hooks is hooks and hooks == []
        assert audit.statements == {"worker": ["SELECT ownership_template"]}
        assert audit.record.__self__ is journal_ref()
        assert audit.detach_hooks() is None

    try:
        detach_twice()
        assert event.contains(engine, "before_cursor_execute", unrelated)
        assert calls == []
        assert audit_ref() is None and journal_ref() is None
    finally:
        event.remove(engine, "before_cursor_execute", unrelated)
        engine.dispose()


@pytest.mark.parametrize("active", ["callback", "workers"])
def test_hook_detach_keeps_all_ownership_during_active_capture_or_pool(active):
    engine, hooks, audit_ref, journal_ref = _registered_audit()
    timing = overlap._PassiveOverlapTiming(sql_cap=1, gc_cap=4)
    audit_ref().passive = timing
    try:
        if active == "callback":
            with timing.capture():
                with pytest.raises(AssertionError, match="Passive capture is active"):
                    audit_ref().detach_hooks()
                _assert_audit_roots(engine, hooks, audit_ref, journal_ref)
        else:
            with audit_ref().pool():
                assert timing.critical_pools == 1
                with pytest.raises(AssertionError, match="Owned workers are still active"):
                    audit_ref().detach_hooks()
                _assert_audit_roots(engine, hooks, audit_ref, journal_ref)
            assert timing.critical_pools == 0
        audit_ref().detach_hooks()
        assert hooks == [] and audit_ref() is None and journal_ref() is None
    finally:
        timing.stop()
        if audit_ref() is not None:
            audit_ref().detach_hooks()
        engine.dispose()


def test_failed_hook_removal_preserves_rooted_ownership_until_success(monkeypatch):
    engine, hooks, audit_ref, journal_ref = _registered_audit()

    def fail_second_removal(target, name, callback):
        if name == "after_cursor_execute":
            raise RuntimeError("Controlled listener removal failure")
        event.remove(target, name, callback)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(overlap, "event", SimpleNamespace(
                contains=event.contains, remove=fail_second_removal,
            ))
            with pytest.raises(RuntimeError, match="^Controlled listener removal failure$"):
                audit_ref().detach_hooks()
        # Removal was partial, but the owned list and diagnostics were not discarded.
        assert audit_ref().hooks is hooks and len(hooks) == 3
        assert all(callback.__self__ is audit_ref() for _, callback in hooks)
        assert not event.contains(engine, *hooks[0])
        assert all(event.contains(engine, name, callback) for name, callback in hooks[1:])
        assert journal_ref().records == 1
        audit_ref().detach_hooks()
        assert hooks == [] and audit_ref() is None and journal_ref() is None
    finally:
        if audit_ref() is not None:
            audit_ref().detach_hooks()
        engine.dispose()


class _LoginAudit:
    """Only the real request dependency's session protocol; no audit hook cycle."""

    @contextmanager
    def session(self, role):
        assert role == "login"
        yield object()


def _override_audit(app):
    override = app.dependency_overrides[overlap.get_db_session]
    cells = dict(zip(override.__code__.co_freevars, override.__closure__, strict=True))
    return cells["audit"].cell_contents


class _ServerDoubles:
    """Explicit socket/thread transport doubles, never live-server acceptance."""

    def __init__(self, monkeypatch, failure=None):
        self.app = FastAPI()
        self.failure = failure
        self.events = []
        self.listener = self.server = self.thread = None
        monkeypatch.setattr(overlap, "create_application", lambda: self.app)
        monkeypatch.setattr(overlap, "socket", SimpleNamespace(socket=self.new_socket))
        monkeypatch.setattr(overlap, "uvicorn", SimpleNamespace(
            Config=self.new_config, Server=self.new_server,
        ))
        monkeypatch.setattr(overlap, "Thread", self.new_thread)

    def new_socket(self):
        if self.failure == "socket":
            raise OSError("Controlled socket failure")
        self.listener = _ListenerDouble(self)
        return self.listener

    def new_config(self, app, **kwargs):
        assert app is self.app and kwargs == {"lifespan": "off", "log_level": "error"}
        if self.failure == "config":
            raise RuntimeError("Controlled config failure")
        return app

    def new_server(self, config):
        assert config is self.app
        self.server = _ServerDouble()
        return self.server

    def new_thread(self, **kwargs):
        assert set(kwargs) == {"target", "kwargs", "daemon"}
        assert kwargs["target"].__self__ is self.server
        assert kwargs["kwargs"] == {"sockets": [self.listener]}
        assert kwargs["daemon"] is True
        self.thread = _ThreadDouble(self)
        return self.thread


class _ListenerDouble:
    def __init__(self, owner):
        self.owner = owner
        self.closed = False

    def bind(self, address):
        assert address == ("127.0.0.1", 0)
        if self.owner.failure == "bind":
            raise OSError("Controlled bind failure")

    def listen(self, backlog):
        assert backlog == 128

    def getsockname(self):
        return "127.0.0.1", 12345

    def close(self):
        assert isinstance(_override_audit(self.owner.app), _LoginAudit)
        self.closed = True
        self.owner.events.append("close")
        if self.owner.failure == "close":
            raise OSError("Controlled close failure")


class _ServerDouble:
    def __init__(self):
        self.started = False
        self.should_exit = False

    def run(self, *, sockets):
        raise AssertionError("A deterministic transport double must not run a server")


class _ThreadDouble:
    def __init__(self, owner):
        self.owner = owner
        self.ident = None
        self.alive = False

    def start(self):
        if self.owner.failure == "thread-start":
            raise RuntimeError("Controlled thread start failure")
        self.ident = 1
        self.alive = self.owner.failure != "startup-dead"
        self.owner.server.started = self.alive

    def is_alive(self):
        return self.alive

    def join(self, *, timeout):
        assert timeout == 6 and self.owner.server.should_exit
        assert not self.owner.listener.closed
        assert isinstance(_override_audit(self.owner.app), _LoginAudit)
        self.owner.events.append("join")
        self.alive = self.owner.failure in ("stuck", "join-live")
        if self.owner.failure in ("join-live", "join-stopped"):
            raise RuntimeError("Controlled join failure")


async def _request_session_roundtrip(app, audit_ref):
    dependency = app.dependency_overrides[overlap.get_db_session]()
    try:
        await anext(dependency)
        assert _override_audit(app) is audit_ref()
    finally:
        await dependency.aclose()


def _server_scope(doubles, refs, *, body_error=False):
    audit = _LoginAudit()
    refs.append(ref(audit))
    manager = overlap._real_login_server(audit)
    del audit
    with manager as origin:
        assert origin == "http://127.0.0.1:12345"
        assert _override_audit(doubles.app) is refs[0]()
        assert not doubles.listener.closed and doubles.thread.is_alive()
        asyncio.run(_request_session_roundtrip(doubles.app, refs[0]))
        if body_error:
            raise ValueError("Controlled server body failure")
    return "completed"


def _previous_override():
    return "previous"


@pytest.mark.parametrize("previous", [False, True], ids=["default", "previous"])
@pytest.mark.parametrize("body_error", [False, True])
def test_stopped_server_releases_only_its_override_and_preserves_outcome(
    monkeypatch, previous, body_error,
):
    doubles = _ServerDoubles(monkeypatch)
    unrelated_key = object()
    doubles.app.dependency_overrides[unrelated_key] = _previous_override
    if previous:
        doubles.app.dependency_overrides[overlap.get_db_session] = _previous_override
    refs = []
    if body_error:
        with pytest.raises(ValueError, match="^Controlled server body failure$"):
            _server_scope(doubles, refs, body_error=True)
    else:
        assert _server_scope(doubles, refs) == "completed"
    assert doubles.events == ["join", "close"]
    assert not doubles.thread.is_alive() and doubles.listener.closed
    assert doubles.app.dependency_overrides == {
        unrelated_key: _previous_override,
        **({overlap.get_db_session: _previous_override} if previous else {}),
    }
    assert refs[0]() is None, "A rooted stopped app must no longer own this audit."


@pytest.mark.parametrize("failure,error", [
    ("socket", OSError), ("bind", OSError), ("config", RuntimeError),
    ("thread-start", RuntimeError), ("startup-dead", AssertionError),
    ("join-stopped", RuntimeError), ("close", OSError),
])
@pytest.mark.parametrize("previous", [False, True], ids=["default", "previous"])
def test_server_setup_or_stopped_teardown_error_restores_owned_override(
    monkeypatch, failure, error, previous,
):
    doubles = _ServerDoubles(monkeypatch, failure)
    if previous:
        doubles.app.dependency_overrides[overlap.get_db_session] = _previous_override
    refs = []
    message = "Owned socket server failed to start" if failure == "startup-dead" else "Controlled"
    with pytest.raises(error, match=message):
        _server_scope(doubles, refs)
    assert doubles.app.dependency_overrides == (
        {overlap.get_db_session: _previous_override} if previous else {}
    )
    assert refs[0]() is None
    if doubles.listener is not None:
        assert doubles.listener.closed
    if doubles.thread is not None:
        assert not doubles.thread.is_alive()


@pytest.mark.parametrize("failure,error", [("stuck", AssertionError), ("join-live", RuntimeError)])
def test_unstopped_server_keeps_exact_dependency_owner(monkeypatch, failure, error):
    doubles = _ServerDoubles(monkeypatch, failure)
    refs = []
    message = "Owned socket server did not stop" if failure == "stuck" else "Controlled join"
    with pytest.raises(error, match=message):
        _server_scope(doubles, refs)
    assert doubles.listener.closed and doubles.thread.is_alive()
    assert _override_audit(doubles.app) is refs[0]()
    # Explicitly end the fake activity, then release just the witnessed bridge.
    doubles.thread.alive = False
    doubles.app.dependency_overrides.pop(overlap.get_db_session)
    assert refs[0]() is None


def test_server_cleanup_does_not_overwrite_a_replacement_dependency(monkeypatch):
    doubles = _ServerDoubles(monkeypatch)
    audit = _LoginAudit()
    audit_ref = ref(audit)
    manager = overlap._real_login_server(audit)
    del audit
    with manager:
        assert _override_audit(doubles.app) is audit_ref()
        # Replacement is injected at the last shutdown boundary, after close's ownership oracle.
        original_close = doubles.listener.close

        def replace_after_close():
            original_close()
            doubles.app.dependency_overrides[overlap.get_db_session] = _previous_override

        monkeypatch.setattr(doubles.listener, "close", replace_after_close)
    del manager
    assert doubles.app.dependency_overrides == {overlap.get_db_session: _previous_override}
    assert audit_ref() is None
