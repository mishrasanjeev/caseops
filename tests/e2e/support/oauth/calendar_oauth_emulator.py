"""Offline OAuth provider used only by the browser acceptance entrypoint."""

from __future__ import annotations

import json
import os
import threading
import time
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
OUTLOOK_CALLBACK = "/api/calendar/connections/outlook/callback"
OUTLOOK_SCOPES = frozenset({"offline_access", "User.Read", "Calendars.ReadWrite"})
REQUIRED_SCOPES = frozenset(
    {"openid", "email", "https://www.googleapis.com/auth/calendar.events"}
)
GOOGLE_ENDPOINTS = {
    "https://oauth2.googleapis.com/token": "/token",
    "https://www.googleapis.com/oauth2/v3/userinfo": "/userinfo",
    "https://login.microsoftonline.com/organizations/oauth2/v2.0/token": "/outlook/token",
    "https://graph.microsoft.com/v1.0/me": "/outlook/userinfo",
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
    provider: str = "google"
    refresh_calls: int = 0
    events: dict[str, dict[str, object]] = field(default_factory=dict)
    event_calls: list[str] = field(default_factory=list)

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
        self.access_tokens: dict[str, str] = {}
        self.access_deadlines: dict[str, float] = {}
        self.refresh_tokens: dict[str, str] = {}

    def authorize(self, params: Mapping[str, str], *, provider: str = "google") -> Attempt:
        redirect = params.get("redirect_uri", "")
        loopback_origin(redirect)
        parsed = urlsplit(redirect)
        if provider not in {"google", "outlook"}:
            raise ValueError("Unknown offline calendar provider.")
        callback = CALLBACK if provider == "google" else OUTLOOK_CALLBACK
        if parsed.path != callback or parsed.query or parsed.fragment:
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
            provider=provider,
        )
        with self.lock:
            if len(self.attempts) >= 1000:
                raise ValueError("OAuth emulator inventory limit reached.")
            self.attempts[attempt.identity] = attempt
        return attempt

    def consent(self, identity: str, outcome: str) -> str:
        if outcome not in {"success", "identity_failure", "hold", "decline", "short_lived", "revoked_refresh"}:
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
                "refresh_calls": attempt.refresh_calls,
                "event_calls": list(attempt.event_calls),
                "events": [
                    {"id": key, "start": value.get("start"), "end": value.get("end")}
                    for key, value in attempt.events.items()
                ],
            }

    def token(self, params: Mapping[str, str], *, provider: str = "google") -> tuple[int, dict[str, object]]:
        if (
            params.get("client_id") != CLIENT_ID
            or params.get("client_secret") != CLIENT_SECRET
        ):
            return 401, {"error": "invalid_client"}
        with self.lock:
            if params.get("grant_type") == "refresh_token":
                token = params.get("refresh_token", "")
                attempt_id = self.refresh_tokens.get(token)
                attempt = self.attempts.get(attempt_id or "")
                if attempt is None or attempt.provider != provider:
                    return 400, {"error": "invalid_grant"}
                self.refresh_tokens.pop(token)
                attempt.refresh_calls += 1
                if attempt.outcome == "revoked_refresh":
                    return 400, {"error": "invalid_grant"}
                return 200, self._tokens(attempt, refreshed=True)
            attempt = next(
                (
                    item
                    for item in self.attempts.values()
                    if item.code == params.get("code")
                ),
                None,
            )
            if attempt is None or attempt.outcome is None or attempt.provider != provider:
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
        with self.lock:
            return 200, self._tokens(attempt, refreshed=False)

    def _tokens(self, attempt: Attempt, *, refreshed: bool) -> dict[str, object]:
        suffix = f"-{attempt.refresh_calls}" if refreshed else ""
        access = "offline-access-" + attempt.identity + suffix
        refresh = "offline-refresh-" + attempt.identity + suffix
        self.access_tokens[access] = attempt.identity
        lifetime = (
            1 if not refreshed and attempt.outcome in {"short_lived", "revoked_refresh"}
            else 3600
        )
        self.access_deadlines[access] = time.monotonic() + lifetime
        self.refresh_tokens[refresh] = attempt.identity
        return {
            "access_token": access,
            "refresh_token": refresh,
            "token_type": "Bearer",
            "expires_in": lifetime,
            "scope": " ".join(attempt.scopes),
        }

    def userinfo(self, authorization: str) -> tuple[int, dict[str, object]]:
        with self.lock:
            identity = self.access_tokens.get(authorization.removeprefix("Bearer "), "")
            attempt = self.attempts.get(identity)
            if attempt is None:
                return 401, {"error": "invalid_token"}
            attempt.userinfo_calls += 1
            required = REQUIRED_SCOPES if attempt.provider == "google" else OUTLOOK_SCOPES
            if attempt.outcome == "identity_failure" or not required.issubset(
                attempt.scopes
            ):
                return 401, {"error": "insufficient_scope"}
        if attempt.provider == "outlook":
            return 200, {"id": "offline-outlook-subject", "mail": "calendar-emulator@example.test"}
        return 200, {
            "sub": "offline-calendar-subject",
            "email": "calendar-emulator@example.test",
            "email_verified": True,
        }

    def event(self, method: str, path: str, authorization: str, body: dict[str, object]):
        with self.lock:
            access = authorization.removeprefix("Bearer ")
            identity = self.access_tokens.get(access, "")
            attempt = self.attempts.get(identity)
            if attempt is None or self.access_deadlines.get(access, 0) <= time.monotonic():
                return 401, {"error": "invalid_token"}
            parts = path.strip("/").split("/")
            if len(parts) not in {2, 3}:
                return 404, {"error": "not_found"}
            provider, resource, *event_id = parts
            if provider != attempt.provider or resource != "events" or len(event_id) > 1:
                return 403, {"error": "invalid_scope"}
            required = REQUIRED_SCOPES if provider == "google" else OUTLOOK_SCOPES
            if not required.issubset(attempt.scopes):
                return 403, {"error": "insufficient_scope"}
            attempt.event_calls.append(method)
            key = event_id[0] if event_id else ""
            if method == "POST" and not key:
                if len(attempt.events) >= 100:
                    return 429, {"error": "offline_event_bound"}
                key = "offline-event-" + uuid.uuid4().hex
                attempt.events[key] = {**body, "id": key}
                return 200, dict(attempt.events[key])
            if key not in attempt.events:
                return 404, {"error": "not_found"}
            if method == "GET":
                return 200, dict(attempt.events[key])
            if method == "PATCH":
                attempt.events[key].update(body)
                return 200, dict(attempt.events[key])
            if method == "DELETE":
                del attempt.events[key]
                return 204, {}
            return 405, {"error": "unsupported_method"}

    def start(self) -> str:
        emulator = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:
                pass

            def respond(self, status: int, body: dict[str, object]) -> None:
                payload = b"" if status == 204 else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 16_384:
                    self.respond(400, {"error": "invalid_request"})
                    return
                raw = self.rfile.read(length).decode()
                if self.path.startswith(("/google/events", "/outlook/events")):
                    try:
                        body = json.loads(raw)
                        if not isinstance(body, dict):
                            raise ValueError("object required")
                    except ValueError:
                        self.respond(400, {"error": "invalid_json"})
                        return
                    self.respond(*emulator.event("POST", self.path, self.headers.get("Authorization", ""), body))
                    return
                if self.path not in {"/token", "/outlook/token"}:
                    self.respond(404, {"error": "not_found"})
                    return
                params = {
                    key: values[0]
                    for key, values in parse_qs(
                        raw
                    ).items()
                }
                self.respond(*emulator.token(params, provider="outlook" if self.path.startswith("/outlook/") else "google"))

            def do_GET(self) -> None:
                if self.path.startswith(("/google/events/", "/outlook/events/")):
                    self.respond(*emulator.event("GET", urlsplit(self.path).path, self.headers.get("Authorization", ""), {}))
                    return
                if self.path not in {"/userinfo", "/outlook/userinfo"}:
                    self.respond(404, {"error": "not_found"})
                    return
                self.respond(*emulator.userinfo(self.headers.get("Authorization", "")))

            def do_PATCH(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 16_384:
                    self.respond(400, {"error": "invalid_request"})
                    return
                try:
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("object required")
                except ValueError:
                    self.respond(400, {"error": "invalid_json"})
                    return
                self.respond(*emulator.event("PATCH", urlsplit(self.path).path, self.headers.get("Authorization", ""), body))

            def do_DELETE(self) -> None:
                self.respond(*emulator.event("DELETE", urlsplit(self.path).path, self.headers.get("Authorization", ""), {}))

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
        or parsed.hostname in {"login.microsoftonline.com", "graph.microsoft.com"}
    ):
        endpoint = GOOGLE_ENDPOINTS.get(url)
        for remote, local in (
            ("https://www.googleapis.com/calendar/v3/calendars/primary/events", "/google/events"),
            ("https://graph.microsoft.com/v1.0/me/events", "/outlook/events"),
        ):
            clean = parsed._replace(query="").geturl()
            if clean == remote or clean.startswith(remote + "/"):
                if parsed.fragment or parsed.username or parsed.password:
                    raise RuntimeError("Invalid offline calendar event URL.")
                if parsed.query and not (local.startswith("/outlook/") and set(parse_qs(parsed.query)) == {"$select"}):
                    raise RuntimeError("Unexpected offline calendar query.")
                endpoint = local + clean[len(remote):]
        if endpoint is None:
            raise RuntimeError(
                "The offline OAuth harness blocks all other Google transport."
            )
        return transport_origin + endpoint
    return None
