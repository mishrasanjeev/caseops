"""Task-local TLS and exact-route no-paid gateway, never a product auth server."""

import http.client
import hashlib
import stat
from types import ModuleType
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import ssl
import threading
import time
import secrets
from urllib.parse import urlsplit

ROOT = Path(os.environ.get("CASEOPS_MOBILE_STATE", "/fixture-state"))
MARKER_HEADER = "X-CaseOps-Automated-Test"
MARKER = "no-paid-providers"
# Covers 23 core journeys plus their account/restore checks without dropping evidence.
MAX_SESSION_ADMISSION_EVENTS = 64
BROWSER_ROUTES = {
    "GET /api/auth/me", "POST /api/auth/login", "POST /api/auth/logout", "POST /api/auth/refresh",
    "GET /api/auth/security", "POST /api/auth/mfa/step-up",
    "POST /api/auth/native/authorize",
}
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authorization", "proxy-authenticate"}


_SOURCE_METADATA = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def source_named_identity_equal(descriptor, named, platform_name=os.name):
    # Windows may expose a different device ID through lstat and fstat. This
    # exception is only cross-API: both full descriptor observations and both
    # full named observations must still remain identical in runtime_source_bytes.
    keys = tuple(key for key in _SOURCE_METADATA if platform_name != "nt" or key != "st_dev")
    return all(getattr(descriptor, key) == getattr(named, key) for key in keys)


def runtime_source_bytes(path, expected=None):
    """Hash and consume exactly one held, bounded, canonical source descriptor."""
    path = Path(path)
    assert path.is_absolute() and path.resolve() == path, "V1_RUNTIME_CANONICAL_SOURCE_REQUIRED"
    metadata = lambda value: tuple(getattr(value, key) for key in _SOURCE_METADATA)
    def ancestors():
        result = []
        for parent in reversed(path.parents):
            value = parent.lstat()
            assert stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode)
            result.append((str(parent), metadata(value)))
        return result
    namespace = ancestors()
    named = path.lstat()
    assert stat.S_ISREG(named.st_mode) and not stat.S_ISLNK(named.st_mode)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        before = os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(named.st_mode)
        assert before.st_nlink == 1 and 0 < before.st_size <= 262144
        assert source_named_identity_equal(before, named)
        chunks, size = [], 0
        while size <= before.st_size:
            block = os.read(descriptor, min(65536, before.st_size + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        after, final = os.fstat(descriptor), path.lstat()
        assert size == before.st_size and metadata(before) == metadata(after)
        assert metadata(named) == metadata(final) and not stat.S_ISLNK(final.st_mode)
        assert source_named_identity_equal(after, final)
        assert path.resolve() == path and ancestors() == namespace, "V1_RUNTIME_NAMESPACE_CHANGED"
        body = b"".join(chunks)
        if expected is not None:
            assert re.fullmatch(r"[a-f0-9]{64}", expected) and hashlib.sha256(body).hexdigest() == expected, "V1_RUNTIME_SOURCE_HASH_REQUIRED"
        return body
    finally:
        os.close(descriptor)


def verified_v1_controls(root, run_id, environment=None):
    env = dict(os.environ if environment is None else environment)
    enabled = env.get("CASEOPS_MOBILE_V1_CONTROLS", "0")
    if enabled == "0":
        return None, None
    assert enabled == "1" and env.get("CASEOPS_ENV") == "local", "V1_EXPLICIT_LOCAL_ENABLE_REQUIRED"
    assert not any(env.get(key) for key in ("K_SERVICE", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    expected = env.get("CASEOPS_MOBILE_V1_IMPLEMENTATION_SHA256", "")
    assert re.fullmatch(r"[a-f0-9]{64}", expected), "V1_RUNTIME_SOURCE_PIN_REQUIRED"
    profile = env.get("CASEOPS_MOBILE_V1_PROFILE", "source-work-v3")
    assert profile in ("source-work-v3", "queue-privacy-v1"), "EXACT_LITERAL_CONTROL_PROFILE_REQUIRED"
    implementation = Path(__file__).resolve().with_name("local-v1-controls.py" if profile == "source-work-v3" else "local-queue-privacy-controls.py")
    held = runtime_source_bytes(implementation, expected)
    registration_path = Path(env["CASEOPS_MOBILE_V1_REGISTRATION"])
    assert Path(root).resolve() in registration_path.parents, "V1_RUNTIME_REGISTRATION_ROOT_REQUIRED"
    registration_bytes = runtime_source_bytes(registration_path, env["CASEOPS_MOBILE_V1_REGISTRATION_SHA256"])
    registration = json.loads(registration_bytes.decode("utf-8", "strict"))
    assert isinstance(registration, dict) and registration.get("implementationSha256") == expected, "V1_RUNTIME_REGISTRATION_PIN_REQUIRED"
    module = ModuleType("caseops_local_v1_controls")
    module.__file__ = str(implementation)
    exec(compile(held, str(implementation), "exec"), module.__dict__)
    extra = {}
    if profile == "queue-privacy-v1":
        base_path = Path(__file__).resolve().with_name("local-v1-controls.py")
        base_bytes = runtime_source_bytes(base_path, "e762d80f89ead187e4255402f2320582f390a63dff629a07b0ef235db6fcdad2")
        base = ModuleType("caseops_queue_privacy_verified_helpers")
        base.__file__ = str(base_path)
        exec(compile(base_bytes, str(base_path), "exec"), base.__dict__)
        extra["base_module"] = base
    return module.from_environment(root, run_id, environment=env, verified_implementation_sha256=expected,
                                   verified_registration_bytes=registration_bytes, **extra), expected


class Gateway:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.Lock()
        self.state = {"runId": os.environ.get("CASEOPS_MOBILE_RUN_ID", "local-test"),
                      "accepted": 0, "markerRejected": 0, "routeRejected": 0,
                      "lastSequence": 0, "overflow": False, "requests": [],
                      "implementationSha256": hashlib.sha256(runtime_source_bytes(Path(__file__).resolve())).hexdigest()}
        self.journal = (root / f"gateway-events-{time.time_ns()}-{secrets.token_hex(3)}.jsonl").open("x", encoding="utf-8")
        self.session_delete_route = None
        self.state["sessionDeleteAdmissions"] = []
        try:
            self.v1, implementation_sha = verified_v1_controls(root, self.state["runId"])
        except BaseException:
            self.journal.close()
            raise
        self.state["v1ControlsEnabled"] = self.v1 is not None
        if self.v1:
            self.state["v1ControlsImplementationSha256"] = implementation_sha
            self.state["v1RegistrationSha256"] = self.v1.registration_sha
            if self.v1.registration.get("profile") == "queue-privacy-v1":
                self.state["v1ControlProfile"] = "queue-privacy-v1"

    def allowed(self):
        config = json.loads((self.root / "gateway-routes.json").read_text())
        return set(config["routes"]) | (set(self.v1.registration["exactRoutes"]) if self.v1 and not self.v1.closed else set())

    def admit_current_session(self, data, request_id):
        try:
            rows = json.loads(data)["sessions"]
            assert isinstance(rows, list) and len(rows) <= 50
            ids = [row["id"] for row in rows]
            assert len(set(ids)) == len(ids) and all(re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", value) for value in ids)
            current = [row["id"] for row in rows if row.get("current") is True and row.get("revoked_at") is None]
            assert len(current) == 1
        except (ValueError, KeyError, TypeError, AssertionError):
            with self.lock:
                self.session_delete_route = None
            return
        with self.lock:
            if len(self.state["sessionDeleteAdmissions"]) >= MAX_SESSION_ADMISSION_EVENTS:
                self.session_delete_route = None
                self.state["overflow"] = True
                return
            self.session_delete_route = f"DELETE /api/auth/native/sessions/{current[0]}"
            event = {"type": "session-delete-admitted", "route": self.session_delete_route, "sourceRequestId": request_id}
            self.state["sessionDeleteAdmissions"].append(event)
            self.journal.write(json.dumps(event) + "\n")
            self.journal.flush()
            os.fsync(self.journal.fileno())

    def handler(self, web=False):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):
                pass

            def reply(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)
                self.close_connection = True

            def handle_request(self):
                path = urlsplit(self.path).path
                if self.path.startswith("//") or path.startswith("//"):
                    return self.reply(400, {"code": "ORIGIN_FORM_REQUIRED"})
                marked = self.headers.get(MARKER_HEADER) == MARKER
                if not web and path == "/__caseops_e2e/v1-control":
                    if not marked or self.command != "POST" or not gateway.v1 or self.path != path:
                        return self.reply(403, {"code": "V1_CONTROLS_NOT_ADMITTED"})
                    try:
                        size = int(self.headers.get("Content-Length", "0"))
                        assert 0 < size <= 16384 and not self.headers.get("Transfer-Encoding")
                        self.connection.settimeout(5)
                        raw = self.rfile.read(size)
                        assert len(raw) == size
                        result = gateway.v1.handle(raw, marker=self.headers.get(MARKER_HEADER), authority=self.headers.get("X-CaseOps-V1-Control"))
                    except Exception:
                        return self.reply(409, {"code": "V1_CONTROL_REFUSED_OR_UNKNOWN_NO_REPLAY"})
                    return self.reply(200, result)
                if not web and path == "/__caseops_e2e/status":
                    if not marked:
                        return self.reply(403, {"code": "AUTOMATED_MARKER_REQUIRED"})
                    with gateway.lock:
                        gateway.state["v1ControlsEnabled"] = bool(gateway.v1 and not gateway.v1.closed)
                        gateway.state["v1ControlRunClosed"] = bool(gateway.v1 and gateway.v1.closed)
                        return self.reply(200, gateway.state)
                route = f"{self.command} {path}"
                request_id = secrets.token_hex(8)
                native_bearer = self.headers.get("Authorization", "").startswith("Bearer cnat_") and not self.headers.get("Cookie")
                # Browser handoff has cookie/CSRF authority, never native bearer authority.
                browser_origin = self.headers.get("Origin", "")
                local_origins = {
                    f"https://{host}:{os.environ.get('CASEOPS_MOBILE_WEB_PORT', '3443')}"
                    for host in ("10.0.2.2", "127.0.0.1", "localhost")
                }
                browser_route = route in BROWSER_ROUTES or (
                    self.command == "OPTIONS" and any(
                        item.split(" ", 1)[1] == path for item in BROWSER_ROUTES
                    )
                )
                browser = browser_route and (
                    browser_origin in local_origins or
                    (self.command == "GET" and bool(self.headers.get("Cookie")))
                ) and not self.headers.get("Authorization")
                preflight = browser and self.command == "OPTIONS"
                if not web and not marked and not preflight and route != "GET /api/build":
                    with gateway.lock:
                        gateway.state["markerRejected"] += 1
                    return self.reply(403, {"code": "AUTOMATED_MARKER_REQUIRED"})
                admitted = route in gateway.allowed()
                if not web and self.command == "DELETE" and native_bearer:
                    with gateway.lock:
                        if route == gateway.session_delete_route:
                            admitted = True
                            gateway.session_delete_route = None
                if not web and not admitted and not browser:
                    with gateway.lock:
                        gateway.state["routeRejected"] += 1
                    return self.reply(403, {"code": "ROUTE_NOT_ADMITTED"})
                if web and path.startswith("/api/") and route != "GET /api/release-identity":
                    return self.reply(403, {"code": "USE_REVIEWED_API_ORIGIN"})
                with gateway.lock:
                    if len(gateway.state["requests"]) >= 500:
                        gateway.state["overflow"] = True
                        return self.reply(503, {"code": "REQUEST_EVIDENCE_BOUND"})
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > 1048576 or self.headers.get("Transfer-Encoding"):
                        return self.reply(413, {"code": "BOUNDED_BODY_REQUIRED"})
                    self.connection.settimeout(20)
                    body = self.rfile.read(length)
                    if len(body) != length:
                        return self.reply(400, {"code": "INCOMPLETE_BODY"})
                except (ValueError, TimeoutError):
                    return self.reply(400, {"code": "INVALID_BODY"})
                headers = {key: value for key, value in self.headers.items() if key.lower() not in HOP}
                headers["Connection"] = "close"
                headers["X-Forwarded-Proto"] = "https"
                upstream = http.client.HTTPConnection("web" if web else "api", 3000 if web else 8000, timeout=15)
                status = 502
                response_started = False
                intercept = None
                data = b""
                recorded = False

                def record_request():
                    nonlocal recorded
                    if web or recorded:
                        return
                    with gateway.lock:
                        gateway.state["lastSequence"] += 1
                        record = {"sequence": gateway.state["lastSequence"], "method": self.command,
                                  "route": path, "status": status, "browserHandoff": browser,
                                  "requestId": request_id,
                                  "trafficClass": "browser-preflight" if preflight else "public-identity" if route == "GET /api/build" else "api"}
                        if gateway.v1:
                            try:
                                gateway.v1.after_native(self.command, path, native=native_bearer,
                                    request_id=request_id, sequence=record["sequence"], body=body,
                                    query=urlsplit(self.path).query, status=status, data=data, intercept=intercept)
                            except Exception:
                                gateway.state["overflow"] = True
                        if not preflight and (marked or route != "GET /api/build"):
                            record["nativeMarker"] = marked
                        gateway.state["requests"].append(record)
                        gateway.state["accepted"] += 1
                        gateway.journal.write(json.dumps(record) + "\n")
                        gateway.journal.flush()
                        os.fsync(gateway.journal.fileno())
                        recorded = True
                try:
                    if gateway.v1:
                        if hasattr(gateway.v1, "validate_native_request"):
                            gateway.v1.validate_native_request(self.command, path, native=native_bearer, body=body,
                                query=urlsplit(self.path).query, authorization=self.headers.get("Authorization"),
                                cookie_present=self.headers.get("Cookie") is not None)
                        intercept = gateway.v1.before_native(self.command, path, native=native_bearer, request_id=request_id)
                        if intercept and intercept.get("fault"):
                            fault = intercept["fault"]
                            response_started = True
                            if fault == "offline":
                                self.close_connection = True
                                return
                            status = 404 if fault == "missing" else 200
                            data = b'{}'
                            record_request()
                            return self.reply(status, {})
                    upstream.request(self.command, self.path, body=body, headers=headers)
                    response = upstream.getresponse()
                    status = response.status
                    # No native redirect following; browser product navigation remains real.
                    if not web and not browser and 300 <= status < 400:
                        return self.reply(502, {"code": "UPSTREAM_REDIRECT_REQUIRES_REVIEW"})
                    data = response.read(8 * 1024 * 1024 + 1)
                    if len(data) > 8 * 1024 * 1024:
                        raise ValueError("Response bound exceeded")
                    if route == "GET /api/auth/native/sessions" and native_bearer and status == 200:
                        gateway.admit_current_session(data, request_id)
                    if gateway.v1:
                        # Make the actual ACK/body facts durable before the app
                        # can render a positive outcome or observe response loss.
                        record_request()
                    if gateway.v1 and gateway.v1.should_withhold(intercept, status):
                        response_started = True
                        self.close_connection = True
                        return
                    response_started = True
                    self.send_response(status)
                    for key, value in response.getheaders():
                        if key.lower() not in HOP and key.lower() != "content-length":
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                    self.close_connection = True
                except (OSError, http.client.HTTPException, ValueError, AssertionError):
                    status = 502
                    if not response_started:
                        self.reply(502, {"code": "UPSTREAM_TRANSPORT_FAILED"})
                    self.close_connection = True
                finally:
                    upstream.close()
                    record_request()

            do_GET = handle_request
            do_POST = handle_request
            do_PATCH = handle_request
            do_DELETE = handle_request
            do_OPTIONS = handle_request

        return Handler


def main():
    gateway = Gateway()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(ROOT / "tls/server.crt", ROOT / "tls/server.key")
    servers = []
    for port, web in ((8443, False), (3443, True)):
        server = ThreadingHTTPServer(("0.0.0.0", port), gateway.handler(web))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print(json.dumps({"ready": True, "runId": gateway.state["runId"], "tls": True}), flush=True)
    try:
        threading.Event().wait()
    finally:
        for server in servers:
            server.shutdown()
        try:
            if gateway.v1:
                gateway.v1.close()
        finally:
            gateway.journal.close()


if __name__ == "__main__":
    main()
