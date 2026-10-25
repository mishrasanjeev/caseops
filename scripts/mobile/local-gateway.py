"""Task-local TLS and exact-route no-paid gateway, never a product auth server."""

import http.client
import hashlib
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
BROWSER_ROUTES = {
    "GET /api/auth/me", "POST /api/auth/login", "POST /api/auth/logout", "POST /api/auth/refresh",
    "GET /api/auth/security", "POST /api/auth/mfa/step-up",
    "POST /api/auth/native/authorize",
}
HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade", "proxy-authorization", "proxy-authenticate"}


class Gateway:
    def __init__(self, root=ROOT):
        self.root = root
        self.lock = threading.Lock()
        self.state = {"runId": os.environ.get("CASEOPS_MOBILE_RUN_ID", "local-test"),
                      "accepted": 0, "markerRejected": 0, "routeRejected": 0,
                      "lastSequence": 0, "overflow": False, "requests": [],
                      "implementationSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        self.journal = (root / f"gateway-events-{time.time_ns()}-{secrets.token_hex(3)}.jsonl").open("x", encoding="utf-8")
        self.session_delete_route = None
        self.state["sessionDeleteAdmissions"] = []

    def allowed(self):
        config = json.loads((self.root / "gateway-routes.json").read_text())
        return set(config["routes"])

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
            if len(self.state["sessionDeleteAdmissions"]) >= 24:
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
                if not web and path == "/__caseops_e2e/status":
                    if not marked:
                        return self.reply(403, {"code": "AUTOMATED_MARKER_REQUIRED"})
                    with gateway.lock:
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
                try:
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
                except (OSError, http.client.HTTPException, ValueError):
                    status = 502
                    if not response_started:
                        self.reply(502, {"code": "UPSTREAM_TRANSPORT_FAILED"})
                    self.close_connection = True
                finally:
                    upstream.close()
                    if not web:
                        with gateway.lock:
                            gateway.state["lastSequence"] += 1
                            record = {"sequence": gateway.state["lastSequence"], "method": self.command,
                                      "route": path, "status": status, "browserHandoff": browser,
                                      "requestId": request_id,
                                      "trafficClass": "browser-preflight" if preflight else "public-identity" if route == "GET /api/build" else "api"}
                            if not preflight and (marked or route != "GET /api/build"):
                                record["nativeMarker"] = marked
                            gateway.state["requests"].append(record)
                            gateway.state["accepted"] += 1
                            gateway.journal.write(json.dumps(record) + "\n")
                            gateway.journal.flush()
                            os.fsync(gateway.journal.fileno())

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
        gateway.journal.close()


if __name__ == "__main__":
    main()
