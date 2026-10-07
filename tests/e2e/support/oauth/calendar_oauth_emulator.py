"""Offline OAuth provider used only by the browser acceptance entrypoint."""

from __future__ import annotations

import json
import os
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Mapping
from urllib.parse import parse_qs, urlencode, urlsplit

CLIENT_ID = "caseops-calendar-browser-emulator"
CLIENT_SECRET = "offline-calendar-browser-fixture-secret"
MODE = "calendar-20261008"
PREFIX = "/_e2e/calendar-oauth"
CALLBACK = "/api/calendar/connections/google-calendar/callback"
REQUIRED_SCOPES = frozenset(
    {"openid", "email", "https://www.googleapis.com/auth/calendar.events"}
)
GOOGLE_ENDPOINTS = {
    "https://oauth2.googleapis.com/token": "/token",
    "https://www.googleapis.com/oauth2/v3/userinfo": "/userinfo",
}


def loopback_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or not parsed.port
    ):
        raise ValueError("OAuth emulator requires an explicit HTTP loopback origin.")
    return f"{parsed.scheme}://{parsed.netloc}"


def require_test_environment(env: Mapping[str, str] | None = None) -> None:
    env = os.environ if env is None else env
    if env.get("CASEOPS_ENV") != "e2e" or env.get("CASEOPS_E2E_OAUTH_EMULATOR") != MODE:
        raise RuntimeError(
            "OAuth emulator is restricted to the explicit e2e entrypoint."
        )
    if any(
        env.get(key)
        for key in (
            "K_SERVICE",
            "K_REVISION",
            "K_CONFIGURATION",
            "CLOUD_RUN_JOB",
            "GOOGLE_CLOUD_PROJECT",
        )
    ):
        raise RuntimeError("OAuth emulator cannot run in a cloud deployment.")
    loopback_origin(env.get("CASEOPS_PUBLIC_APP_URL", ""))
    database = urlsplit(env.get("CASEOPS_DATABASE_URL", ""))
    if database.scheme == "sqlite+pysqlite" and database.path:
        return
    if (
        database.scheme == "postgresql+psycopg"
        and database.hostname in {"localhost", "127.0.0.1", "postgres"}
        and database.path == "/caseops"
    ):
        return
    raise RuntimeError("OAuth emulator requires an isolated local acceptance database.")


@dataclass
class Attempt:
    state: str
    redirect_uri: str
    scopes: list[str]
    identity: str = field(default_factory=lambda: uuid.uuid4().hex)
    code: str = field(default_factory=lambda: "offline-code-" + uuid.uuid4().hex)
    outcome: str | None = None
    token_calls: int = 0
    userinfo_calls: int = 0
    waiting: bool = False
    release: threading.Event = field(default_factory=threading.Event)

    @property
    def callback_url(self) -> str:
        params = (
            {"error": "access_denied", "state": self.state}
            if self.outcome == "decline"
            else {"code": self.code, "state": self.state}
        )
        return self.redirect_uri + "?" + urlencode(params)


class CalendarOAuthEmulator:
    def __init__(self) -> None:
        self.attempts: dict[str, Attempt] = {}
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None

    def authorize(self, params: Mapping[str, str]) -> Attempt:
        redirect = params.get("redirect_uri", "")
        loopback_origin(redirect)
        parsed = urlsplit(redirect)
        if parsed.path != CALLBACK or parsed.query or parsed.fragment:
            raise ValueError("Only the exact local Calendar callback is allowed.")
        if (
            params.get("client_id") != CLIENT_ID
            or params.get("response_type") != "code"
            or not params.get("state")
        ):
            raise ValueError("Only explicit offline Calendar credentials are allowed.")
        attempt = Attempt(
            state=params["state"],
            redirect_uri=redirect,
            scopes=params.get("scope", "").split(),
        )
        with self.lock:
            if len(self.attempts) >= 1000:
                raise ValueError("OAuth emulator inventory limit reached.")
            self.attempts[attempt.identity] = attempt
        return attempt

    def consent(self, identity: str, outcome: str) -> str:
        if outcome not in {"success", "identity_failure", "hold", "decline"}:
            raise ValueError("Unknown deterministic provider scenario.")
        with self.lock:
            attempt = self.attempts[identity]
            if attempt.outcome is not None:
                raise ValueError("This consent was already submitted.")
            attempt.outcome = outcome
            return attempt.callback_url

    def evidence(self, identity: str) -> dict[str, object]:
        with self.lock:
            attempt = self.attempts[identity]
            return {
                "scopes": attempt.scopes,
                "token_calls": attempt.token_calls,
                "userinfo_calls": attempt.userinfo_calls,
                "waiting": attempt.waiting,
            }

    def token(self, params: Mapping[str, str]) -> tuple[int, dict[str, object]]:
        if (
            params.get("client_id") != CLIENT_ID
            or params.get("client_secret") != CLIENT_SECRET
        ):
            return 401, {"error": "invalid_client"}
        with self.lock:
            attempt = next(
                (
                    item
                    for item in self.attempts.values()
                    if item.code == params.get("code")
                ),
                None,
            )
            if attempt is None or attempt.outcome is None:
                return 400, {"error": "invalid_grant"}
            attempt.token_calls += 1
            if (
                attempt.outcome == "decline"
                or attempt.token_calls != 1
                or params.get("grant_type") != "authorization_code"
                or params.get("redirect_uri") != attempt.redirect_uri
            ):
                return 400, {"error": "invalid_grant"}
            attempt.waiting = attempt.outcome == "hold"
        if attempt.waiting:
            released = attempt.release.wait(12)
            with self.lock:
                attempt.waiting = False
            if not released:
                return 503, {"error": "offline_hold_not_released"}
        return 200, {
            "access_token": "offline-access-" + attempt.identity,
            "refresh_token": "offline-refresh-" + attempt.identity,
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": " ".join(attempt.scopes),
        }

    def userinfo(self, authorization: str) -> tuple[int, dict[str, object]]:
        identity = authorization.removeprefix("Bearer offline-access-")
        with self.lock:
            attempt = self.attempts.get(identity)
            if attempt is None:
                return 401, {"error": "invalid_token"}
            attempt.userinfo_calls += 1
            if attempt.outcome == "identity_failure" or not REQUIRED_SCOPES.issubset(
                attempt.scopes
            ):
                return 401, {"error": "insufficient_scope"}
        return 200, {
            "sub": "offline-calendar-subject",
            "email": "calendar-emulator@example.test",
            "email_verified": True,
        }

    def start(self) -> str:
        emulator = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def respond(self, status: int, body: dict[str, object]) -> None:
                payload = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if self.path != "/token" or not 0 < length < 16_384:
                    self.respond(400, {"error": "invalid_request"})
                    return
                params = {
                    key: values[0]
                    for key, values in parse_qs(
                        self.rfile.read(length).decode()
                    ).items()
                }
                self.respond(*emulator.token(params))

            def do_GET(self) -> None:
                if self.path != "/userinfo":
                    self.respond(404, {"error": "not_found"})
                    return
                self.respond(*emulator.userinfo(self.headers.get("Authorization", "")))

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def stop(self) -> None:
        for attempt in self.attempts.values():
            attempt.release.set()
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()


def redirected_google_url(url: str, transport_origin: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.hostname and (
        parsed.hostname == "google.com"
        or parsed.hostname.endswith(".google.com")
        or parsed.hostname == "googleapis.com"
        or parsed.hostname.endswith(".googleapis.com")
    ):
        endpoint = GOOGLE_ENDPOINTS.get(url)
        if endpoint is None:
            raise RuntimeError(
                "The offline OAuth harness blocks all other Google transport."
            )
        return transport_origin + endpoint
    return None
