"""Loopback-only capture of real console-link delivery in the guarded E2E app."""

from __future__ import annotations

import json
import os
import re
from atexit import register as register_shutdown
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socket import SHUT_RDWR
from threading import Event, RLock, Thread
from time import monotonic
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

from calendar_oauth_emulator import require_test_environment
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

PREFIX = "/_e2e/platform-console"
MARKER = "no-paid-providers"


class Seed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=36, max_length=36)
    web_origin: str = Field(min_length=1, max_length=255)


class Cleanup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    web_origin: str = Field(min_length=1, max_length=255)
    manager_id: str | None = Field(default=None, min_length=36, max_length=36)


def _origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or not parsed.port
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Console fixtures require an exact loopback origin.")
    return f"http://{parsed.netloc}"


def _run(value: str) -> str:
    if len(value) != 36 or str(UUID(value)) != value:
        raise ValueError("Console fixtures require a canonical run UUID.")
    return value


class _CaptureServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = False

    def __init__(self, *args):
        self.owner_lock = RLock()
        self.sockets, self.handlers = set(), set()
        self.stopping = Event()
        super().__init__(*args)

    def get_request(self):
        request, address = super().get_request()
        try:
            request.settimeout(2)
            with self.owner_lock:
                if self.stopping.is_set():
                    raise OSError("Console capture is stopping.")
                self.sockets.add(request)
        except BaseException:
            request.close()
            raise
        return request, address

    def process_request(self, request, address):
        worker = Thread(target=self.process_request_thread, args=(request, address), daemon=False)
        with self.owner_lock:
            self._reap_handlers()
            self.handlers.add(worker)
        try:
            worker.start()
        except BaseException:
            with self.owner_lock:
                self.handlers.discard(worker)
            self.shutdown_request(request)
            raise

    def _reap_handlers(self):
        for worker in tuple(self.handlers):
            if not worker.is_alive():
                worker.join(timeout=0)
                self.handlers.remove(worker)

    def shutdown_request(self, request):
        try:
            super().shutdown_request(request)
        finally:
            with self.owner_lock:
                self.sockets.discard(request)

    def drain(self, deadline):
        with self.owner_lock:
            sockets, handlers = tuple(self.sockets), tuple(self.handlers)
        # Closing the listener does not interrupt accepted sockets' header/body reads.
        for request in sockets:
            try:
                request.shutdown(SHUT_RDWR)
            except OSError:
                # A completed peer may already have disconnected during shutdown.
                pass
            request.close()
        for worker in handlers:
            worker.join(timeout=max(0, deadline - monotonic()))
        with self.owner_lock:
            self._reap_handlers()
            if self.sockets or self.handlers:
                raise RuntimeError("Console capture handlers did not close.")


class ConsoleMailCapture:
    def __init__(self, web_origin: str):
        self.web_origin = _origin(web_origin)
        self.runs: dict[str, dict] = {}
        self.messages: list[dict] = []
        self.external_calls = 0
        self.lock = RLock()
        self.server: _CaptureServer | None = None
        self.thread: Thread | None = None
        self.capture_path = "/capture/" + uuid4().hex

    def register(self, run_id: str, web_origin: str) -> None:
        run_id = _run(run_id)
        if _origin(web_origin) != self.web_origin:
            raise ValueError("Console fixture origin mismatch.")
        with self.lock:
            if run_id in self.runs or len(self.runs) >= 32:
                raise ValueError("Console run already registered or inventory full.")
            self.runs[run_id] = {"state": "seeding", "manager_id": None}

    def admit(self, run_id: str, marker: str) -> dict:
        _run(run_id)
        if marker != MARKER:
            raise ValueError("Console fixtures require the canonical automated marker.")
        with self.lock:
            if run_id not in self.runs:
                raise ValueError("Console fixture run is not registered.")
            return dict(self.runs[run_id])

    def receive(self, payload: dict) -> None:
        if not isinstance(payload, dict) or set(payload) != {"to", "subject", "body"}:
            raise ValueError("Invalid captured message shape.")
        if any(not isinstance(value, str) for value in payload.values()):
            raise ValueError("Invalid captured message type.")
        match = re.fullmatch(
            r"(?:pra-manager|viewer|csrf)-([0-9a-f-]{36})@example\.com", payload["to"]
        )
        if match is None:
            raise ValueError(
                "Only registered synthetic recipients can receive captured mail."
            )
        run_id = _run(match.group(1))
        purpose = {
            "CaseOps reports console setup": "invite",
            "CaseOps reports password reset": "password_reset",
        }.get(payload["subject"])
        lines = payload["body"].splitlines()
        if purpose is None or len(lines) != 3:
            raise ValueError("Invalid canonical console message.")
        link = lines[1]
        parsed = urlsplit(link)
        expected_path = (
            "/platform/setup" if purpose == "invite" else "/platform/reset-password"
        )
        fragment = parse_qs(parsed.fragment, strict_parsing=True)
        tokens = fragment.get("token", [])
        if (
            f"{parsed.scheme}://{parsed.netloc}" != self.web_origin
            or parsed.path != expected_path
            or parsed.query
            or set(fragment) != {"token"}
            or len(tokens) != 1
            or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", tokens[0]) is None
        ):
            raise ValueError(
                "Captured link is not the exact local one-use fragment route."
            )
        with self.lock:
            state = self.runs.get(run_id)
            if state is None or state["state"] not in {"seeding", "ready"}:
                raise ValueError(
                    "Captured recipient has no admitted active fixture run."
                )
            if sum(row["run_id"] == run_id for row in self.messages) >= 32:
                raise ValueError("Console fixture message inventory is full.")
            self.messages.append(
                {
                    "id": str(uuid4()),
                    "run_id": run_id,
                    "recipient_email": payload["to"],
                    "purpose": purpose,
                    "link_url": link,
                    "transport": "deterministic_local",
                    "provider_call_performed": False,
                }
            )

    def ledger(self, run_id: str, marker: str) -> dict:
        self.admit(run_id, marker)
        with self.lock:
            return {
                "items": [
                    dict(row) for row in self.messages if row["run_id"] == run_id
                ],
                "external_calls": self.external_calls,
            }

    def reject_external(self, **_kwargs):
        with self.lock:
            self.external_calls += 1
        raise RuntimeError("Console E2E forbids external mail transport.")

    def start(self) -> str:
        if self.server is not None:
            raise RuntimeError("Console capture is already running.")
        capture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if self.path != capture.capture_path or not 0 < length <= 16_384:
                        raise ValueError("Invalid capture request.")
                    capture.receive(json.loads(self.rfile.read(length)))
                    status = 202
                except (ValueError, OSError):
                    status = 400
                if self.server.stopping.is_set():
                    return
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

        self.server = _CaptureServer(("127.0.0.1", 0), Handler)
        self.thread = Thread(
            target=lambda: self.server.serve_forever(poll_interval=0.05), daemon=True
        )
        try:
            self.thread.start()
        except BaseException:
            self.server.server_close()
            self.server = None
            raise
        return f"http://127.0.0.1:{self.server.server_port}{self.capture_path}"

    def stop(self) -> None:
        if self.server is not None:
            deadline = monotonic() + 3
            self.server.stopping.set()
            self.server.shutdown()
            self.server.server_close()
            self.server.drain(deadline)
            self.thread.join(timeout=max(0, deadline - monotonic()))
            if self.thread.is_alive():
                raise RuntimeError("Console capture thread did not close.")
            self.server = None


def install_platform_console_emulator(app) -> ConsoleMailCapture:
    require_test_environment()
    from caseops_api.services import platform_console as console
    from platform_report_fixtures import cleanup_console_fixture, seed_console_fixture

    capture = ConsoleMailCapture(os.environ["CASEOPS_PUBLIC_APP_URL"])
    previous = os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL")
    transport = capture.start()
    os.environ["CASEOPS_CONSOLE_TEST_MAIL_URL"] = transport
    original_sender = console._send_via_sendgrid
    blocked_sender = capture.reject_external
    console._send_via_sendgrid = blocked_sender

    def close():
        capture.stop()
        if os.environ.get("CASEOPS_CONSOLE_TEST_MAIL_URL") == transport:
            if previous is None:
                os.environ.pop("CASEOPS_CONSOLE_TEST_MAIL_URL", None)
            else:
                os.environ["CASEOPS_CONSOLE_TEST_MAIL_URL"] = previous
        if console._send_via_sendgrid is blocked_sender:
            console._send_via_sendgrid = original_sender

    register_shutdown(close)

    def marker(request: Request) -> str:
        require_test_environment()
        value = request.headers.get("X-CaseOps-Automated-Test", "")
        if value != MARKER:
            raise HTTPException(403, "Canonical automated marker required.")
        return value

    @app.post(PREFIX + "/fixtures", include_in_schema=False, status_code=201)
    def seed(payload: Seed, request: Request):
        automated = marker(request)
        try:
            capture.register(payload.run_id, payload.web_origin)
        except ValueError as exc:
            raise HTTPException(
                409, "Invalid or already registered local fixture."
            ) from exc
        try:
            result = seed_console_fixture(
                run_id=payload.run_id,
                web_origin=payload.web_origin,
                automated_marker=automated,
            )
            with capture.lock:
                capture.runs[payload.run_id].update(
                    state="ready", manager_id=result["manager"]["id"]
                )
            return result
        except Exception:
            with capture.lock:
                capture.runs[payload.run_id]["state"] = "failed"
            raise

    @app.get(PREFIX + "/mail", include_in_schema=False)
    def mail(run_id: str, request: Request):
        automated = marker(request)
        try:
            return capture.ledger(run_id, automated)
        except ValueError as exc:
            raise HTTPException(404, "No admitted local console run.") from exc

    @app.post(PREFIX + "/fixtures/{run_id}/cleanup", include_in_schema=False)
    def cleanup(run_id: str, payload: Cleanup, request: Request):
        automated = marker(request)
        try:
            with capture.lock:
                state = capture.admit(run_id, automated)
                if _origin(payload.web_origin) != capture.web_origin:
                    raise ValueError("Origin mismatch.")
                if state["state"] not in {"ready", "failed"}:
                    raise ValueError("Cleanup was already attempted.")
                if (
                    state["manager_id"] is not None
                    and payload.manager_id != state["manager_id"]
                ):
                    raise ValueError("Manager mismatch.")
                capture.runs[run_id]["state"] = "cleaning"
        except ValueError as exc:
            raise HTTPException(
                409, "Invalid local console cleanup admission."
            ) from exc
        try:
            result = cleanup_console_fixture(
                run_id=run_id,
                web_origin=payload.web_origin,
                automated_marker=automated,
                manager_id=payload.manager_id,
            )
            with capture.lock:
                capture.runs[run_id]["state"] = "cleaned"
            return result
        except Exception:
            with capture.lock:
                capture.runs[run_id]["state"] = "cleanup_failed"
            raise

    return capture
