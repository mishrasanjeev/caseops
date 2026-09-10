"""Scanner startup is concurrent with API initialization, not bypassed."""

import asyncio
from contextlib import asynccontextmanager
from threading import Event

import pytest

from caseops_api.core import startup


@pytest.fixture(autouse=True)
def scanner_config(monkeypatch):
    monkeypatch.setattr(startup, "_config_from_env", lambda: ("127.0.0.1", 3310, 60, True))


@asynccontextmanager
async def scanner_server(reply: bytes | None):
    commands = []

    async def serve(reader, writer):
        try:
            commands.append(await reader.readuntil(b"\0"))
            if reply is not None:
                writer.write(reply)
                await writer.drain()
            else:
                await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    async with server:
        yield server.sockets[0].getsockname()[1], commands


@pytest.mark.asyncio
async def test_ping_requires_exact_complete_protocol_response():
    async with scanner_server(b"PONG\0") as (port, commands):
        await startup._ping_scanner("127.0.0.1", port)
    assert commands == [b"zPING\0"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", [b"OK\0", b"PONG", b"X" * 100, b""])
async def test_ping_rejects_wrong_truncated_oversized_and_empty_response(reply):
    async with scanner_server(reply) as (port, _):
        with pytest.raises((ValueError, asyncio.IncompleteReadError, asyncio.LimitOverrunError)):
            await startup._ping_scanner("127.0.0.1", port)


@pytest.mark.asyncio
async def test_stalled_body_is_bounded_and_event_loop_remains_responsive(monkeypatch):
    monkeypatch.setattr(startup, "SCANNER_ATTEMPT_SECONDS", 0.08)
    async with scanner_server(None) as (port, _):
        pending = asyncio.create_task(startup._ping_scanner("127.0.0.1", port))
        await asyncio.sleep(0.01)
        assert not pending.done()
        with pytest.raises(TimeoutError):
            await pending


@pytest.mark.asyncio
async def test_required_missing_scanner_refuses_startup(monkeypatch):
    monkeypatch.setattr(startup, "_config_from_env", lambda: (None, 3310, 60, True))
    with pytest.raises(RuntimeError, match="not configured"):
        await startup.wait_for_required_scanner()


@pytest.mark.asyncio
async def test_optional_local_scanner_does_not_probe(monkeypatch):
    monkeypatch.setattr(startup, "_config_from_env", lambda: (None, 3310, 60, False))
    await startup.wait_for_required_scanner()


@pytest.mark.asyncio
async def test_delayed_daemon_recovers_before_serving(monkeypatch):
    calls = []

    async def ping(host, port):
        calls.append((host, port))
        if len(calls) < 3:
            raise ConnectionRefusedError

    monkeypatch.setattr(startup, "_ping_scanner", ping)
    monkeypatch.setattr(startup, "SCANNER_POLL_SECONDS", 0.001)
    await startup.wait_for_required_scanner()
    assert calls == [("127.0.0.1", 3310)] * 3


@pytest.mark.asyncio
async def test_total_deadline_bounds_all_attempts_and_hides_host(monkeypatch):
    async def ping(*_):
        await asyncio.sleep(5)

    monkeypatch.setattr(startup, "_ping_scanner", ping)
    monkeypatch.setattr(startup, "SCANNER_STARTUP_BUDGET_SECONDS", 0.02)
    with pytest.raises(RuntimeError, match="did not become ready in time") as error:
        await startup.wait_for_required_scanner()
    assert "127.0.0.1" not in str(error.value)


@pytest.mark.asyncio
async def test_cancellation_is_not_retried(monkeypatch):
    called = 0

    async def ping(*_):
        nonlocal called
        called += 1
        raise asyncio.CancelledError

    monkeypatch.setattr(startup, "_ping_scanner", ping)
    with pytest.raises(asyncio.CancelledError):
        await startup.wait_for_required_scanner()
    assert called == 1


@pytest.mark.asyncio
async def test_lifespan_does_not_yield_before_both_readiness_checks(monkeypatch):
    from threading import Event

    from caseops_api import main

    native_started = Event()
    scanner_started = Event()
    release_scanner = asyncio.Event()
    entered = False

    async def scanner():
        scanner_started.set()
        await release_scanner.wait()

    def native():
        native_started.set()
        assert scanner_started.wait(1)

    monkeypatch.setattr(startup, "wait_for_required_scanner", scanner)
    monkeypatch.setattr(main, "warm_reranker", native)
    monkeypatch.setattr(main, "warm_database_mappers", lambda: None)
    monkeypatch.setattr(main, "run_migrations", lambda: None)

    async def enter():
        nonlocal entered
        async with main.lifespan(main.app):
            entered = True

    task = asyncio.create_task(enter())
    await asyncio.wait_for(asyncio.to_thread(native_started.wait), 1)
    assert scanner_started.is_set() and not entered
    release_scanner.set()
    await asyncio.wait_for(task, 1)
    assert entered


@pytest.mark.asyncio
async def test_lifespan_scanner_failure_never_yields(monkeypatch):
    from caseops_api import main

    async def scanner():
        raise RuntimeError("scanner failed")

    monkeypatch.setattr(startup, "wait_for_required_scanner", scanner)
    monkeypatch.setattr(main, "warm_reranker", lambda: None)
    monkeypatch.setattr(main, "run_migrations", lambda: None)
    with pytest.raises(ExceptionGroup) as error:
        async with main.lifespan(main.app):
            pytest.fail("Unready application must not serve")
    assert any(str(exc) == "scanner failed" for exc in error.value.exceptions)


@pytest.mark.asyncio
async def test_total_readiness_deadline_bounds_native_without_serving(monkeypatch):
    from caseops_api import main

    release = Event()
    monkeypatch.setattr(startup, "READINESS_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr(startup, "_config_from_env", lambda: (None, 3310, 60, False))
    monkeypatch.setattr(main, "warm_reranker", release.wait)
    monkeypatch.setattr(main, "run_migrations", lambda: None)
    try:
        with pytest.raises(RuntimeError, match="readiness did not complete in time"):
            async with main.lifespan(main.app):
                pytest.fail("Timed-out native initialization must never open serving")
    finally:
        release.set()
    await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_native_error_aborts_other_readiness_check(monkeypatch):
    cancelled = asyncio.Event()

    async def scanner():
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    def native():
        raise RuntimeError("native model failed")

    monkeypatch.setattr(startup, "wait_for_required_scanner", scanner)
    with pytest.raises(ExceptionGroup) as error:
        await startup.wait_for_readiness(native)
    assert cancelled.is_set()
    assert [str(exc) for exc in error.value.exceptions] == ["native model failed"]


def test_stuck_native_warmup_does_not_hold_failed_process_open():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", """
import asyncio
from threading import Event
from caseops_api.core import startup
startup.READINESS_BUDGET_SECONDS = 0.03
startup._config_from_env = lambda: (None, 3310, 60, False)
try:
    asyncio.run(startup.wait_for_readiness(Event().wait))
except RuntimeError as exc:
    assert str(exc) == 'Application readiness did not complete in time'
    print('bounded-failed-startup')
else:
    raise AssertionError('Unready startup was accepted')
"""], capture_output=True, text=True, timeout=5, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "bounded-failed-startup"


def test_runtime_warms_orm_before_native_model_without_database_transport(monkeypatch):
    from caseops_api import main

    order = []
    result = object()
    monkeypatch.setattr(main, "warm_database_mappers", lambda: order.append("orm"))

    def native():
        order.append("native")
        return result

    monkeypatch.setattr(main, "warm_reranker", native)
    assert main.warm_runtime() is result
    assert order == ["orm", "native"]


def test_mapper_warmup_configures_all_canonical_mappers_without_sql(monkeypatch):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    from caseops_api.db.base import Base

    def reject_sql(*args, **kwargs):
        pytest.fail("Mapper warm-up cannot query tenant data")

    event.listen(Engine, "before_cursor_execute", reject_sql)
    try:
        startup.warm_database_mappers()
        assert len(Base.registry.mappers) > 300
        assert all(mapper.configured for mapper in Base.registry.mappers)
    finally:
        event.remove(Engine, "before_cursor_execute", reject_sql)


def test_application_factory_constructs_each_route_only_once(monkeypatch):
    from fastapi.routing import APIRoute

    from caseops_api.main import create_application

    original = APIRoute.__init__
    constructed = []

    def record(self, *args, **kwargs):
        original(self, *args, **kwargs)
        constructed.append(self)

    monkeypatch.setattr(APIRoute, "__init__", record)
    application = create_application()
    routes = [route for route in application.routes if isinstance(route, APIRoute)]
    assert constructed == routes
    assert len(routes) > 800
    assert all(route.path.startswith("/api/") for route in routes)
    assert len({(route.path, tuple(sorted(route.methods))) for route in routes}) == len(routes)


def test_two_applications_keep_independent_dependency_overrides_and_routes():
    from fastapi.testclient import TestClient

    from caseops_api.main import create_application

    first, second = create_application(), create_application()
    assert first.openapi() == second.openapi()
    assert first.dependency_overrides is not second.dependency_overrides
    assert first.router is not second.router
    assert first.routes[0] is not second.routes[0]
    for application in (first, second):
        client = TestClient(application)
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/ip/portfolio?limit=100").status_code == 401
        assert client.get("/api/statutes").status_code == 401
