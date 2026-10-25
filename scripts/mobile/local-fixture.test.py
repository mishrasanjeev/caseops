"""Gateway/bootstrap unit proof only; real Docker receipts are separate."""

import http.client
import argparse
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gateway_module = load("local_gateway", "local-gateway.py")
bootstrap_module = load("local_bootstrap", "local-bootstrap.py")


class BootstrapTests(unittest.TestCase):
    def test_local_web_derivation_preserves_canonical_security_build(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(bootstrap_module.prepare_web_dockerfile(Path(directory)))
            canonical = (bootstrap_module.REPO / "apps/web/Dockerfile").read_text(encoding="utf-8")
            rendered = path.read_text(encoding="utf-8")
            insertion = "\nARG NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=0\nENV NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=$NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE"
            self.assertEqual(rendered.replace(insertion, ""), canonical)
            self.assertLess(rendered.index(insertion), rendered.index("RUN npm run build"))

    def test_compose_does_not_inherit_foreign_provider_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "compose-secrets.json").write_text(json.dumps({"CASEOPS_MOBILE_AUTH_SECRET": "synthetic-unit-secret"}))
            with patch.dict(bootstrap_module.os.environ, {"CASEOPS_OPENAI_API_KEY": "never-inherit", "OTHER": "retained"}, clear=True):
                command, environment = bootstrap_module.compose(root, {"CASEOPS_MOBILE_PROJECT": "owned-unit-project"})
            self.assertNotIn("CASEOPS_OPENAI_API_KEY", environment)
            self.assertEqual(environment["OTHER"], "retained")
            self.assertIn("owned-unit-project", command)

    def test_active_receipt_pointer_is_authoritative_not_newest_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "receipt-active.json"
            active.write_text(json.dumps({"source": {"api": {"fingerprint": "active"}}}))
            (root / "receipt-newer-incomplete.json").write_text(json.dumps({"source": {"api": {"fingerprint": "not-serving"}}}))
            (root / "current-receipt.json").write_text(json.dumps({"receipt": str(active)}))
            self.assertEqual(bootstrap_module.active_sources(root)["api"]["fingerprint"], "active")

    def test_source_identity_retains_dirty_truth_and_fingerprint(self):
        source = {"api": {"head": "base", "fingerprint": "content", "dirty": True,
                          "changedPaths": ["M source.py"], "files": [{"path": "source.py"}]}}
        self.assertEqual(bootstrap_module.source_identity(source), {"api": {
            "head": "base", "fingerprint": "content", "dirty": True, "changedPaths": ["M source.py"],
        }})

    def test_up_refuses_to_overwrite_earlier_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            evidence = root / "failed.log"
            evidence.write_text("original failure")
            with patch.object(bootstrap_module, "run") as command:
                with self.assertRaisesRegex(AssertionError, "fresh cache"):
                    bootstrap_module.main(argparse.Namespace(action="up", cache=root))
                command.assert_not_called()
            self.assertEqual(evidence.read_text(), "original failure")

    def test_web_build_uses_explicit_flag_and_retained_stdin_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dockerfile = bootstrap_module.prepare_web_dockerfile(root)
            config = {"CASEOPS_MOBILE_WEB_DOCKERFILE": dockerfile, "CASEOPS_MOBILE_WEB_SHA": "unavailable",
                      "CASEOPS_MOBILE_API_PORT": "8443", "CASEOPS_MOBILE_WEB_PORT": "3443",
                      "CASEOPS_MOBILE_WEB_IMAGE": "owned-unit-web:local"}
            with patch.object(bootstrap_module, "run") as command:
                bootstrap_module.build_web(root, config, root / "build.log")
            arguments = command.call_args.args[0]
            self.assertEqual(arguments[:4], ["docker", "build", "--file", "-"])
            self.assertIn("NEXT_PUBLIC_CASEOPS_LOCAL_ACCEPTANCE=1", arguments)
            self.assertEqual(command.call_args.kwargs["input_text"], Path(dockerfile).read_text(encoding="utf-8"))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "gateway-routes.json").write_text(json.dumps({"routes": [
            "GET /api/build", "GET /api/matters/", "POST /api/auth/native/token",
            "GET /api/auth/native/sessions",
        ]}))
        self.gateway = gateway_module.Gateway(self.root)
        self.server = gateway_module.ThreadingHTTPServer(("127.0.0.1", 0), self.gateway.handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection_type = http.client.HTTPConnection

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.gateway.journal.close()
        self.temp.cleanup()

    def request(self, method, path, headers=None, body=None):
        with closing(self.connection_type("127.0.0.1", self.server.server_port, timeout=3)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, response.read()

    def test_native_missing_marker_denied_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("GET", "/api/matters/")
            self.assertEqual(status, 403)
            transport.assert_not_called()
        self.assertEqual(self.gateway.state["markerRejected"], 1)

    def test_unreviewed_paid_route_denied_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/case-tracking/search", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
            self.assertEqual(status, 403)
            transport.assert_not_called()
        self.assertEqual(self.gateway.state["routeRejected"], 1)

    def test_status_is_marker_protected_and_does_not_count_as_api_call(self):
        self.assertEqual(self.request("GET", "/__caseops_e2e/status")[0], 403)
        status, body = self.request("GET", "/__caseops_e2e/status", {gateway_module.MARKER_HEADER: gateway_module.MARKER})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["requests"], [])

    def test_encoded_query_auth_and_mutation_bytes_survive_once(self):
        observed = []

        class Response:
            status = 200
            def getheaders(self):
                return [("content-type", "application/json")]
            def read(self, _limit):
                return b'{"ok":true}'

        class Upstream:
            def __init__(self, *_args, **_kwargs):
                pass
            def request(self, *args, **kwargs):
                observed.append((args, kwargs))
            def getresponse(self):
                return Response()
            def close(self):
                pass

        with patch.object(gateway_module.http.client, "HTTPConnection", Upstream):
            result = self.request("POST", "/api/auth/native/token?q=a%2Fb%26c", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
                "Content-Type": "application/json",
            }, b'{"code":"synthetic"}')
        self.assertEqual(result[0], 200)
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0][0], ("POST", "/api/auth/native/token?q=a%2Fb%26c"))
        self.assertEqual(observed[0][1]["body"], b'{"code":"synthetic"}')
        self.assertEqual(observed[0][1]["headers"][gateway_module.MARKER_HEADER], gateway_module.MARKER)
        record = json.loads(Path(self.gateway.journal.name).read_text())
        self.assertNotIn("synthetic", json.dumps(record))
        self.assertNotIn("q=", json.dumps(record))

    def test_browser_preflight_is_exact_and_origin_bounded(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("OPTIONS", "/api/auth/login", {"Origin": "https://evil.example"})
            self.assertEqual(status, 403)
            transport.assert_not_called()

    def test_browser_origin_does_not_inject_a_missing_marker(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/auth/login", {"Origin": "https://10.0.2.2:3443"})
            self.assertEqual(status, 403)
            transport.assert_not_called()

    def test_body_size_guard_runs_before_transport(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            status, _ = self.request("POST", "/api/auth/native/token", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER, "Content-Length": "1048577",
            })
            self.assertEqual(status, 413)
            transport.assert_not_called()

    def test_native_redirect_is_rejected_without_following(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            transport.return_value.getresponse.return_value.status = 307
            status, body = self.request("GET", "/api/matters/", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
            })
            self.assertEqual(status, 502)
            self.assertEqual(json.loads(body)["code"], "UPSTREAM_REDIRECT_REQUIRES_REVIEW")
            transport.return_value.request.assert_called_once()

    def test_upstream_transport_error_is_not_retried(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            transport.return_value.request.side_effect = OSError("synthetic transport failure")
            status, body = self.request("POST", "/api/auth/native/token", {
                gateway_module.MARKER_HEADER: gateway_module.MARKER,
            }, b"{}")
            self.assertEqual(status, 502)
            self.assertEqual(json.loads(body)["code"], "UPSTREAM_TRANSPORT_FAILED")
            transport.return_value.request.assert_called_once()

    def test_current_session_delete_admission_is_exact_and_single_use(self):
        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER, "Authorization": "Bearer cnat_unit_only"}
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = [("content-type", "application/json")]
            response.read.return_value = json.dumps({"sessions": [
                {"id": "older", "current": False, "revoked_at": None},
                {"id": "actual-current", "current": True, "revoked_at": None},
            ]}).encode()
            self.assertEqual(self.request("GET", "/api/auth/native/sessions", headers)[0], 200)
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/older", headers)[0], 403)
            response.status = 204
            response.read.return_value = b""
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/actual-current", headers)[0], 204)
            self.assertEqual(self.request("DELETE", "/api/auth/native/sessions/actual-current", headers)[0], 403)
            self.assertEqual(transport.return_value.request.call_count, 2)

    def test_cookie_session_list_cannot_admit_native_delete(self):
        headers = {gateway_module.MARKER_HEADER: gateway_module.MARKER, "Cookie": "synthetic=unit-only",
                   "Origin": "https://10.0.2.2:3443"}
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = []
            response.read.return_value = b'{"sessions":[{"id":"browser-only","current":true,"revoked_at":null}]}'
            self.assertEqual(self.request("GET", "/api/auth/native/sessions", headers)[0], 200)
        self.assertIsNone(self.gateway.session_delete_route)

    def test_public_identity_and_preflight_do_not_forge_a_native_marker(self):
        with patch.object(gateway_module.http.client, "HTTPConnection") as transport:
            response = transport.return_value.getresponse.return_value
            response.status = 200
            response.getheaders.return_value = []
            response.read.return_value = b"{}"
            self.assertEqual(self.request("GET", "/api/build")[0], 200)
            self.assertEqual(self.request("OPTIONS", "/api/auth/login", {"Origin": "https://10.0.2.2:3443"})[0], 200)
        self.assertTrue(all("nativeMarker" not in item for item in self.gateway.state["requests"]))
        self.assertEqual(self.gateway.state["requests"][-1]["trafficClass"], "browser-preflight")


if __name__ == "__main__":
    unittest.main(verbosity=2)
