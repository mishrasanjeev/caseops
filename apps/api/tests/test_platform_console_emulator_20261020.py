from __future__ import annotations

import importlib
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, RLock, current_thread, get_ident
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

HARNESS = Path(__file__).resolve().parents[3] / "tests/e2e/support/oauth"
WEB = "http://127.0.0.1:3100"


@pytest.fixture
def harness(monkeypatch):
    monkeypatch.syspath_prepend(str(HARNESS))
    return importlib.import_module("platform_console_emulator")


@pytest.mark.parametrize(
    "change",
    [
        {"CASEOPS_ENV": "production"},
        {"CASEOPS_ENV": "local"},
        {"CASEOPS_E2E_OAUTH_EMULATOR": ""},
        {"K_SERVICE": "api"},
        {"K_REVISION": "revision"},
        {"K_CONFIGURATION": "config"},
        {"CLOUD_RUN_JOB": "job"},
        {"GOOGLE_CLOUD_PROJECT": "project"},
        {"CASEOPS_PUBLIC_APP_URL": "https://caseops.ai"},
        {"CASEOPS_DATABASE_URL": "postgresql+psycopg://u:p@production/caseops"},
    ],
)
def test_console_capture_rejects_remote_runtime_before_app_or_transport(
    harness, monkeypatch, change
):
    environment = {
        "CASEOPS_ENV": "e2e",
        "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB,
        "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
        **change,
    }
    for key in (
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    app = Mock()
    started = Mock(side_effect=AssertionError("Transport must not start."))
    monkeypatch.setattr(harness.ConsoleMailCapture, "start", started)
    with pytest.raises((RuntimeError, ValueError)):
        harness.install_platform_console_emulator(app)
    started.assert_not_called()
    app.post.assert_not_called()
    app.get.assert_not_called()


def message(run, *, origin=WEB):
    return {
        "to": f"pra-manager-{run}@example.com",
        "subject": "CaseOps reports console setup",
        "body": (
            f"Use this one-time link within 30 minutes:\n{origin}/platform/setup#token={'a' * 43}\n"
            "Ignore it if you did not expect this request."
        ),
    }


def test_console_capture_real_loopback_transport_and_inventory_fences(harness):
    capture = harness.ConsoleMailCapture(WEB)
    first, second = str(uuid4()), str(uuid4())
    capture.register(first, WEB)
    capture.register(second, WEB)
    target = capture.start()
    thread = capture.thread
    try:
        with httpx.Client(trust_env=False, timeout=3) as client:
            assert client.post(target, json=message(first)).status_code == 202
            assert client.post(target, json=message(second)).status_code == 202
            assert (
                client.post(target, json=message(first, origin="https://caseops.ai")).status_code
                == 400
            )
            assert (
                client.post(
                    target, json={**message(first), "to": "real@outside.example"}
                ).status_code
                == 400
            )
            assert client.post(target, content=b"x" * 16_385).status_code == 400
            assert client.post(target + "/other", json=message(first)).status_code == 400
        ledger = capture.ledger(first, harness.MARKER)
        assert len(ledger["items"]) == 1
        assert ledger["external_calls"] == 0
        assert ledger["items"][0]["run_id"] == first
        assert ledger["items"][0]["provider_call_performed"] is False
        assert len(capture.ledger(second, harness.MARKER)["items"]) == 1
        with pytest.raises(ValueError):
            capture.ledger(first, "not-the-marker")
        with pytest.raises(ValueError):
            capture.register(first, WEB)
        with pytest.raises(ValueError):
            capture.receive(message(str(uuid4())))
        for _ in range(31):
            capture.receive(message(first))
        with pytest.raises(ValueError):
            capture.receive(message(first))
        with pytest.raises(RuntimeError):
            capture.reject_external(to_email="must-not-send@example.com")
        assert capture.ledger(first, harness.MARKER)["external_calls"] == 1
    finally:
        capture.stop()
    assert not thread.is_alive()
    capture.stop()


@pytest.mark.parametrize(
    "origin",
    [
        "https://caseops.ai",
        "http://127.0.0.1:3100/path",
        "http://127.0.0.1:3100?x=1",
        "http://user@127.0.0.1:3100",
        "http://localhost",
        "http://127.0.0.1:3100#fragment",
    ],
)
def test_console_capture_requires_exact_origin(harness, origin):
    with pytest.raises(ValueError):
        harness.ConsoleMailCapture(origin)


def test_fixture_routes_register_before_seed_and_admit_only_one_exact_cleanup(harness, monkeypatch):
    for key in (
        "K_SERVICE",
        "K_REVISION",
        "K_CONFIGURATION",
        "CLOUD_RUN_JOB",
        "GOOGLE_CLOUD_PROJECT",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "CASEOPS_ENV": "e2e",
        "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB,
        "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
    }.items():
        monkeypatch.setenv(key, value)
    fixtures = importlib.import_module("platform_report_fixtures")
    manager = str(uuid4())
    runs = []
    cleanups = []
    closers = []
    monkeypatch.setattr(harness, "register_shutdown", closers.append)

    def seed(**kwargs):
        runs.append(kwargs)
        capture.receive(message(kwargs["run_id"]))
        return {"manager": {"id": manager}}

    def cleanup(**kwargs):
        cleanups.append(kwargs)
        return {"status": "revoked", "manager_id": manager}

    monkeypatch.setattr(fixtures, "seed_console_fixture", seed)
    monkeypatch.setattr(fixtures, "cleanup_console_fixture", cleanup)
    app = FastAPI()
    from caseops_api.core.csrf import CSRFMiddleware
    from caseops_api.core.request_context import RequestContextMiddleware

    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RequestContextMiddleware)
    original = os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL")
    capture = harness.install_platform_console_emulator(app)
    run = str(uuid4())
    body = {"run_id": run, "web_origin": WEB}
    csrf = {
        "Cookie": "caseops_csrf=isolated-fixture-nonce",
        "X-CSRF-Token": "isolated-fixture-nonce",
    }
    headers = {**csrf, "X-CaseOps-Automated-Test": harness.MARKER}
    try:
        with TestClient(app) as client:
            assert client.post(harness.PREFIX + "/fixtures", json=body).status_code == 403
            assert not runs and not capture.runs
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=csrf).status_code
                == 403
            )
            assert (
                client.post(
                    harness.PREFIX + "/fixtures",
                    json=body,
                    headers={"X-CaseOps-Automated-Test": harness.MARKER},
                ).status_code
                == 403
            )
            assert not runs and not capture.runs
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=headers).status_code
                == 201
            )
            assert len(runs) == 1
            assert (
                client.post(harness.PREFIX + "/fixtures", json=body, headers=headers).status_code
                == 409
            )
            ledger = client.get(harness.PREFIX + "/mail", params={"run_id": run}, headers=headers)
            assert ledger.status_code == 200 and len(ledger.json()["items"]) == 1
            path = harness.PREFIX + f"/fixtures/{run}/cleanup"
            assert (
                client.post(
                    path, json={"web_origin": WEB, "manager_id": str(uuid4())}, headers=headers
                ).status_code
                == 409
            )
            assert not cleanups
            admitted = {"web_origin": WEB, "manager_id": manager}
            assert client.post(path, json=admitted, headers=headers).status_code == 200
            assert len(cleanups) == 1
            assert client.post(path, json=admitted, headers=headers).status_code == 409
            assert len(cleanups) == 1
            assert (
                client.get(
                    harness.PREFIX + "/mail", params={"run_id": str(uuid4())}, headers=headers
                ).status_code
                == 404
            )
    finally:
        closers[0]()
    assert os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL") == original


@pytest.mark.parametrize("phase", ["headers", "body"])
def test_capture_stop_closes_partial_requests_and_joins_handlers(harness, monkeypatch, phase):
    capture = harness.ConsoleMailCapture(WEB)
    capture.start()
    server, serving_thread = capture.server, capture.thread
    entered, handlers = Event(), []
    method = "parse_request" if phase == "headers" else "do_POST"
    original = getattr(server.RequestHandlerClass, method)

    def pause_point(handler):
        handlers.append((handler.connection, current_thread()))
        entered.set()
        return original(handler)

    monkeypatch.setattr(server.RequestHandlerClass, method, pause_point)
    peer = socket.create_connection(server.server_address, timeout=3)
    prefix = f"POST {capture.capture_path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
    partial = "X-Partial:" if phase == "headers" else "Content-Length: 128\r\n\r\n{"
    try:
        peer.sendall((prefix + partial).encode("ascii"))
        assert entered.wait(3), "The actual partial-request parsing boundary was not reached."
        capture.stop()
        assert not serving_thread.is_alive()
        assert len(handlers) == 1
        connection, worker = handlers[0]
        assert not worker.is_alive(), "Capture stop returned with an owned handler still running."
        assert not worker.daemon
        assert connection.gettimeout() == 2
        assert not server.sockets and not server.handlers
        assert not capture.messages and capture.external_calls == 0
        try:
            assert peer.recv(1) == b""
        except (ConnectionAbortedError, ConnectionResetError):
            # Windows may report a reset instead of EOF after forced socket shutdown.
            pass
        capture.stop()
    finally:
        try:
            peer.shutdown(socket.SHUT_RDWR)
        except OSError:
            # The capture may already have closed this deliberately incomplete peer.
            pass
        peer.close()
        for _connection, worker in handlers:
            worker.join(timeout=3)
            assert not worker.is_alive(), "Partial-request regression leaked its handler."
        capture.stop()


def test_cleanup_admission_is_atomic_for_two_actual_contenders(harness, monkeypatch):
    for key in ("K_SERVICE", "K_REVISION", "K_CONFIGURATION", "CLOUD_RUN_JOB",
                "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(key, raising=False)
    for key, value in {
        "CASEOPS_ENV": "e2e", "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
        "CASEOPS_PUBLIC_APP_URL": WEB, "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///isolated.db",
    }.items():
        monkeypatch.setenv(key, value)
    fixtures = importlib.import_module("platform_report_fixtures")
    manager, run, closers, calls = str(uuid4()), str(uuid4()), [], []
    monkeypatch.setattr(harness, "register_shutdown", closers.append)
    monkeypatch.setattr(
        fixtures, "cleanup_console_fixture",
        lambda **kwargs: calls.append(kwargs) or {"status": "revoked", "manager_id": manager},
    )
    app = FastAPI()
    capture = harness.install_platform_console_emulator(app)
    capture.register(run, WEB)
    capture.runs[run].update(state="ready", manager_id=manager)
    endpoint = next(route.endpoint for route in app.routes
                    if route.path == harness.PREFIX + "/fixtures/{run_id}/cleanup")
    first_read, release_first, second_attempt, second_read = (Event() for _ in range(4))
    identities, first_owns_lock = {}, []
    raw_lock, depths = RLock(), {}

    class ObservedLock:
        def __enter__(self):
            identity = get_ident()
            if identity == identities.get("second"):
                second_attempt.set()
            raw_lock.acquire()
            depths[identity] = depths.get(identity, 0) + 1

        def __exit__(self, *_args):
            identity = get_ident()
            depths[identity] -= 1
            raw_lock.release()

    capture.lock = ObservedLock()
    original_admit = capture.admit

    def observed_admit(*args):
        state = original_admit(*args)
        if get_ident() == identities["first"]:
            first_owns_lock.append(bool(depths.get(get_ident(), 0)))
            first_read.set()
            assert release_first.wait(3), "Cleanup admission boundary was not released."
        else:
            second_read.set()
        return state

    monkeypatch.setattr(capture, "admit", observed_admit)

    def invoke(role):
        identities[role] = get_ident()
        request = Request({"type": "http", "headers": [
            (b"x-caseops-automated-test", harness.MARKER.encode("ascii")),
        ]})
        try:
            endpoint(run, harness.Cleanup(web_origin=WEB, manager_id=manager), request)
            return 200
        except HTTPException as error:
            return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                first = pool.submit(invoke, "first")
                assert first_read.wait(3)
                second = pool.submit(invoke, "second")
                assert second_attempt.wait(3)
                # The old unlocked snapshot must be duplicated before release;
                # an atomic claim instead holds the second contender at its lock.
                if not first_owns_lock[0]:
                    assert second_read.wait(3)
                else:
                    assert not second_read.is_set()
                release_first.set()
                assert sorted([first.result(timeout=3), second.result(timeout=3)]) == [200, 409]
                assert first_owns_lock == [True]
                assert len(calls) == 1
                assert calls[0] == {"run_id": run, "web_origin": WEB,
                                    "automated_marker": harness.MARKER, "manager_id": manager}
                assert capture.runs[run]["state"] == "cleaned"
            finally:
                release_first.set()
    finally:
        closers[0]()
