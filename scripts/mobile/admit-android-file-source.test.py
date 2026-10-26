"""Exact source admission boundaries; mocks cannot certify a native upload."""

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import types
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("android_source_admission", Path(__file__).with_name("admit-android-file-source.py"))
admission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admission)
generator = admission.generator


class Admissions(unittest.TestCase):
    def setUp(self):
        fixture_spec = importlib.util.spec_from_file_location("android_generator_tests", Path(__file__).with_name("prepare-android-files-fixture.test.py"))
        support = importlib.util.module_from_spec(fixture_spec)
        fixture_spec.loader.exec_module(support)
        support.Fixtures.setUp(self)
        self.receipt_path = self.receipt
        self.api = self.core["containers"][0]
        self.core.update({"gatewayRunId": "unit-gateway", "gatewayImplementationSha256": "b" * 64,
                          "credentialsFile": str(self.cache / "credentials.json"), "publicCA": str(self.cache / "tls/ca.crt")})
        self.write_inputs()
        (self.cache / "tls").mkdir()
        (self.cache / "tls/ca.crt").write_bytes(b"synthetic-unit-ca-no-TLS-claim")
        result = generator.prepare(self.cache, self.receipt_path, self.root / "assets")
        self.manifest_ref = result["manifest"]
        self.manifest = json.loads(Path(result["manifest"]["path"]).read_text())
        self.asset = self.manifest["assets"][0]
        self.expected = {"attachmentId": "55555555-5555-4555-8555-555555555555", "filename": self.asset["filename"],
                         "sha256": self.asset["sha256"], "sizeBytes": self.asset["sizeBytes"], "acknowledgementRequestId": "c" * 16}
        self.ack = {"sequence": 1, "method": "POST", "route": f"/api/matters/{self.seed['matter']['id']}/attachments", "status": 200,
                    "nativeMarker": True, "browserHandoff": False, "requestId": "c" * 16}
        self.status = {"runId": self.core["gatewayRunId"], "implementationSha256": self.core["gatewayImplementationSha256"],
                       "overflow": False, "markerRejected": 0, "routeRejected": 0, "lastSequence": 1, "requests": [self.ack]}
        self.source = {"id": self.expected["attachmentId"], "matter_id": self.seed["matter"]["id"],
                       "original_filename": self.asset["filename"], "sha256_hex": self.asset["sha256"],
                       "size_bytes": self.asset["sizeBytes"], "content_type": self.asset["mimeType"]}
        self.workspace = {"matter": self.seed["matter"], "attachments": [self.source]}

    def write_inputs(self):
        for path, body in ((self.cache / "config.json", self.config), (self.cache / "seed.json", self.seed), (self.receipt, self.core)):
            path.write_text(json.dumps(body))

    def write(self, path, body):
        path.write_text(json.dumps(body))

    def args(self, **changes):
        values = {"cache": self.cache, "receipt": self.receipt_path, "manifest": Path(self.manifest_ref["path"]),
                  "manifest_sha256": self.manifest_ref["sha256"], "asset_id": "txt", "attachment_id": self.expected["attachmentId"],
                  "sha256": self.expected["sha256"], "size_bytes": self.expected["sizeBytes"], "filename": self.expected["filename"],
                  "ack_request_id": self.expected["acknowledgementRequestId"], "output": self.root / "admission.json"}
        return argparse.Namespace(**{**values, **changes})

    def test_host_binds_real_public_files_without_reading_owner_credentials(self):
        (self.cache / "credentials.json").write_bytes(b"not valid JSON: must never read this on host")
        request, current = admission.host_request(self.args())
        self.assertEqual(request["expected"], self.expected)
        self.assertEqual(request["api"], self.api)
        self.assertEqual(request["manifest"], self.manifest_ref)
        self.assertEqual(current, self.core)
        self.assertNotIn("not valid JSON", json.dumps(request))

    def test_host_request_keeps_original_config_snapshot_after_live_gateway_config_changes(self):
        before, _ = admission.host_request(self.args())
        self.config["CASEOPS_MOBILE_GATEWAY_RUN_ID"] = "new-ledger-after-assets"
        self.write_inputs()
        after, _ = admission.host_request(self.args())
        self.assertEqual(after["manifest"], before["manifest"])
        self.assertEqual(after["expected"], before["expected"])
        reference = self.manifest["configEvidence"]
        original, _ = admission.read_json(reference["path"], reference["sha256"])
        self.assertNotIn("CASEOPS_MOBILE_GATEWAY_RUN_ID", original)

    def test_changed_missing_or_mutable_config_snapshot_refuses_actual_host_admission_before_docker(self):
        snapshot = Path(self.manifest["configEvidence"]["path"])
        original = snapshot.read_bytes()
        with patch.object(admission, "inspect_api") as inspect, patch.object(admission, "checked_run") as docker:
            snapshot.write_bytes(b'{"changed":"configuration-snapshot"}')
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                admission.admit(self.args())
            snapshot.unlink()
            with self.assertRaises(FileNotFoundError):
                admission.admit(self.args())
            snapshot.write_bytes(original)
            changed = {**self.manifest, "configEvidence": {"path": str(self.cache / "config.json"),
                       "sha256": hashlib.sha256((self.cache / "config.json").read_bytes()).hexdigest()}}
            manifest_path = self.root / "mutable-config-manifest.json"
            self.write(manifest_path, changed)
            with self.assertRaisesRegex(ValueError, "immutable configuration snapshot"):
                admission.admit(self.args(manifest=manifest_path, manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest()))
        inspect.assert_not_called()
        docker.assert_not_called()
        self.assertFalse(self.args().output.exists())
        self.assertFalse(self.args().output.with_name(self.args().output.name + ".attempt.json").exists())

    def test_fresh_gateway_receipt_allowed_only_with_unchanged_base_image_and_backend(self):
        current = copy.deepcopy(self.core)
        current["gatewayRunId"] = "fresh-files-gateway"
        fresh = self.cache / "receipt-files-unit.json"
        self.write(fresh, current)
        request, observed = admission.host_request(self.args(receipt=fresh))
        self.assertEqual(observed["gatewayRunId"], "fresh-files-gateway")
        self.assertEqual(request["originalReceiptFile"], self.receipt_path.name)
        for key, value in (("backendSha", "d" * 40), ("backendRevision", "different-api")):
            changed = {**current, key: value}
            self.write(fresh, changed)
            with self.assertRaises(ValueError):
                admission.host_request(self.args(receipt=fresh))
        changed = copy.deepcopy(current)
        changed["containers"][0]["image"] = "sha256:" + "d" * 64
        self.write(fresh, changed)
        with self.assertRaises(ValueError):
            admission.host_request(self.args(receipt=fresh))

    def test_manifest_tamper_asset_tamper_and_negative_assets_fail_before_docker(self):
        with self.assertRaises(ValueError):
            admission.host_request(self.args(manifest_sha256="0" * 64))
        with self.assertRaises(ValueError):
            admission.host_request(self.args(asset_id="eicar"))
        with self.assertRaises(ValueError):
            admission.host_request(self.args(asset_id="unsupported"))
        Path(self.asset["path"]).write_bytes(b"changed")
        with patch.object(admission, "checked_run") as docker, self.assertRaises(ValueError):
            admission.admit(self.args())
        docker.assert_not_called()
        self.assertFalse(self.args().output.exists())

    def test_ack_requires_exact_unique_contiguous_native_post_200_from_same_run(self):
        self.assertEqual(admission.validate_acknowledgement(self.status, self.core, self.seed["matter"]["id"], "c" * 16), self.ack)
        for changes in ({"status": 201}, {"status": 400}, {"nativeMarker": False}, {"browserHandoff": True},
                        {"method": "GET"}, {"route": "/api/matters/foreign/attachments"}, {"sequence": 2}):
            status = copy.deepcopy(self.status)
            status["requests"][0].update(changes)
            with self.assertRaises(ValueError):
                admission.validate_acknowledgement(status, self.core, self.seed["matter"]["id"], "c" * 16)
        for changes in ({"runId": "foreign"}, {"overflow": True}, {"markerRejected": 1}, {"routeRejected": 1},
                        {"lastSequence": 2}, {"requests": []}, {"requests": [self.ack, {**self.ack, "sequence": 2}], "lastSequence": 2}):
            with self.assertRaises(ValueError):
                admission.validate_acknowledgement({**self.status, **changes}, self.core, self.seed["matter"]["id"], "c" * 16)

    def test_native_expectations_never_reuse_seed_or_substitute_filename_hash_size(self):
        for changes in ({"attachmentId": self.seed["sourceId"]}, {"attachmentId": "not-a-uuid"},
                        {"filename": "other.txt"}, {"sha256": "d" * 64}, {"sizeBytes": 1}, {"acknowledgementRequestId": "invented"}):
            with self.assertRaises(ValueError):
                admission.validate_manifest(self.manifest, self.core, self.core, self.seed, "txt", {**self.expected, **changes})

    def test_persisted_workspace_requires_exact_one_parent_name_hash_size_type(self):
        self.assertEqual(admission.validate_workspace(self.workspace, self.seed, self.asset, self.expected), self.source)
        for key, value in (("matter_id", "foreign"), ("original_filename", "wrong.txt"), ("sha256_hex", "e" * 64),
                           ("size_bytes", self.asset["sizeBytes"] + 1), ("size_bytes", True), ("content_type", "application/pdf")):
            workspace = copy.deepcopy(self.workspace)
            workspace["attachments"][0][key] = value
            with self.assertRaises(ValueError):
                admission.validate_workspace(workspace, self.seed, self.asset, self.expected)
        for attachments in ([], [self.source, self.source]):
            with self.assertRaises(ValueError):
                admission.validate_workspace({**self.workspace, "attachments": attachments}, self.seed, self.asset, self.expected)
        with self.assertRaises(ValueError):
            admission.validate_workspace({**self.workspace, "attachments": [self.source, {**self.source, "id": "66666666-6666-4666-8666-666666666666"}]},
                                         self.seed, self.asset, self.expected)
        with self.assertRaises(ValueError):
            admission.validate_workspace({**self.workspace, "matter": {"id": "foreign"}}, self.seed, self.asset, self.expected)

    def test_route_admission_preserves_whole_inventory_and_rejects_replay_wildcards(self):
        route = f"GET /api/matters/{self.seed['matter']['id']}/attachments/{self.source['id']}/download"
        prior = {"routes": ["GET /api/build", "GET /api/health"]}
        result = admission.add_exact_route(prior, route)
        self.assertEqual(set(result["routes"]), {*prior["routes"], route})
        self.assertEqual(prior["routes"], ["GET /api/build", "GET /api/health"])
        for routes in ([route], ["GET /api/*"], ["GET /api/build", "GET /api/build"]):
            with self.assertRaises(ValueError):
                admission.add_exact_route({"routes": routes}, route)

    def integration(self, bad_workspace=False, bad_bytes=False):
        request, _ = admission.host_request(self.args())
        request["sourceSnapshot"], request["helperSources"] = admission.snapshot_sources(self.cache, request)
        credentials = self.cache / "credentials.json"
        generator.new_file(credentials, b'{"email":"synthetic@example.com","password":"unit-only","company_slug":"test-legal"}')
        self.write(self.cache / "gateway-routes.json", {"routes": ["GET /api/build"]})
        actions = []
        workspace = copy.deepcopy(self.workspace)
        if bad_workspace:
            workspace["attachments"][0]["sha256_hex"] = "d" * 64
        class Client:
            headers = {"Authorization": "unit-only-never-output"}
            def __enter__(inner): return inner
            def __exit__(inner, *_): pass
            def get(inner, path):
                actions.append(path)
                return {"release_sha": self.core["backendSha"], "revision": self.core["backendRevision"]} if path == "/api/build" else workspace
        def login(_http, _credentials):
            actions.append("protected-login")
            return {"company": {"id": self.seed["companyId"]}, "membership": {"id": self.seed["membershipId"], "role": "owner"}}
        fixture = types.SimpleNamespace(ROOT=self.cache, client=Client, expect=lambda response: response, login=login)
        engine = types.ModuleType("sqlalchemy.engine")
        engine.make_url = lambda _value: types.SimpleNamespace(host="postgres", database="caseops_mobile")
        calls = []
        content = Path(self.asset["path"]).read_bytes()
        def tls(_root, _receipt, _ca, path, authorization=None, byte_range=None, maximum=None):
            calls.append((path, byte_range))
            if path == "/__caseops_e2e/status":
                return 200, json.dumps(self.status).encode(), {}
            self.assertEqual(authorization, "unit-only-never-output")
            headers = {"cache-control": "private, no-store", "content-range": f"bytes 0-15/{len(content)}"}
            return (206, content[:16], headers) if byte_range else (200, b"wrong" if bad_bytes else content, headers)
        with patch.dict(os.environ, {"CASEOPS_ENV": "local", "CASEOPS_DATABASE_URL": "unit-only"}), \
             patch.dict("sys.modules", {"sqlalchemy": types.ModuleType("sqlalchemy"), "sqlalchemy.engine": engine}), \
             patch.object(admission, "load_fixture", return_value=fixture), patch.object(admission, "tls_get", side_effect=tls):
            result = admission.container_admit(request, self.cache)
        return result, actions, calls

    def test_complete_flow_has_exact_bytes_range_and_immutable_route_snapshots_no_db_writes(self):
        result, actions, calls = self.integration()
        evidence = json.loads((self.cache / result["receiptFile"]).read_text())
        self.assertEqual(actions, ["/api/build", "protected-login", f"/api/matters/{self.seed['matter']['id']}/workspace"])
        self.assertEqual([row[1] for row in calls], [None, None, "bytes=0-15"])
        self.assertEqual(evidence["observations"][0]["sha256"], self.asset["sha256"])
        self.assertEqual(evidence["observations"][0]["sizeBytes"], self.asset["sizeBytes"])
        self.assertTrue(evidence["strictTLS"])
        self.assertFalse(evidence["directDatabaseWrites"])
        self.assertTrue(evidence["ownerAuthenticationUsesNormalAPI"])
        self.assertFalse(evidence["attachmentsCreated"])
        self.assertNotIn("unit-only-never-output", json.dumps(evidence))
        for key in ("routesBefore", "routesAfter"):
            reference = evidence[key]
            self.assertEqual(hashlib.sha256((self.cache / reference["file"]).read_bytes()).hexdigest(), reference["sha256"])
        before = json.loads((self.cache / evidence["routesBefore"]["file"]).read_text())
        after = json.loads((self.cache / evidence["routesAfter"]["file"]).read_text())
        self.assertEqual(set(after["routes"]) - set(before["routes"]), {result["route"]})
        self.assertNotIn("/preview", result["route"])

    def test_wrong_actual_workspace_never_mutates_routes_and_preserves_failed_claim(self):
        with self.assertRaises(ValueError):
            self.integration(bad_workspace=True)
        self.assertEqual(json.loads((self.cache / "gateway-routes.json").read_text()), {"routes": ["GET /api/build"]})
        self.assertEqual(len(list(self.cache.glob("android-file-source-attempt-*.json"))), 1)
        self.assertEqual(list(self.cache.glob("android-file-source-*.routes-after.json")), [])

    def test_wrong_actual_download_bytes_fail_after_retaining_before_after_and_attempt(self):
        with self.assertRaises(ValueError):
            self.integration(bad_bytes=True)
        self.assertEqual(len(list(self.cache.glob("android-file-source-attempt-*.json"))), 1)
        self.assertEqual(len(list(self.cache.glob("android-file-source-*.routes-before.json"))), 1)
        self.assertEqual(len(list(self.cache.glob("android-file-source-*.routes-after.json"))), 1)
        self.assertEqual(list(self.cache.glob("android-file-source-????????????????.json")), [])

    def test_container_rejects_nonlocal_environment_before_login(self):
        request, _ = admission.host_request(self.args())
        with patch.dict(os.environ, {"CASEOPS_ENV": "production"}), patch.object(admission, "load_fixture") as loader:
            with self.assertRaises(ValueError):
                admission.container_admit(request, self.cache)
        loader.assert_not_called()

    def test_existing_or_symlink_output_refuses_before_any_docker_or_attempt(self):
        args = self.args()
        args.output.write_bytes(b"retained-prior-evidence")
        with patch.object(admission, "inspect_api") as inspect, patch.object(admission, "checked_run") as docker:
            with self.assertRaisesRegex(ValueError, "Fresh evidence output"):
                admission.admit(args)
        inspect.assert_not_called()
        docker.assert_not_called()
        self.assertEqual(args.output.read_bytes(), b"retained-prior-evidence")
        self.assertFalse(args.output.with_name(args.output.name + ".attempt.json").exists())
        link = self.root / "symlink-output.json"
        link.symlink_to(self.root / "nonexistent-output.json")
        with patch.object(admission, "inspect_api") as inspect, patch.object(admission, "checked_run") as docker:
            with self.assertRaisesRegex(ValueError, "symlink"):
                admission.admit(self.args(output=link))
        inspect.assert_not_called()
        docker.assert_not_called()
        self.assertFalse((self.root / "nonexistent-output.json").exists())

    def test_helper_snapshot_is_exact_complete_and_preserves_canonical_mounted_sources(self):
        request, _ = admission.host_request(self.args())
        name, sources = admission.snapshot_sources(self.cache, request)
        self.assertRegex(name, r"^android-admission-source-[a-f0-9]{16}$")
        self.assertEqual(set(sources), {"admit-android-file-source.py", "prepare-android-files-fixture.py",
                                       "prepare-ios-files-fixture.py", "local-fixture.py"})
        for filename, digest in sources.items():
            staged = self.cache / name / filename
            self.assertEqual(hashlib.sha256(staged.read_bytes()).hexdigest(), digest)
            self.assertEqual(staged.read_bytes(), (admission.HERE / filename).read_bytes())
            self.assertEqual(staged.stat().st_mode & 0o777, 0o400)
        self.assertFalse((self.cache / "credentials.json").exists())

    def test_snapshot_traversal_missing_helper_or_changed_bytes_refuse_before_login(self):
        request, _ = admission.host_request(self.args())
        name, sources = admission.snapshot_sources(self.cache, request)
        request.update(sourceSnapshot=name, helperSources=sources)
        with patch.dict(os.environ, {"CASEOPS_ENV": "local"}), patch.object(admission, "load_fixture") as loader:
            for bad_name in ("../" + name, "/fixture-state/" + name, "android-admission-source-not-hex"):
                with self.subTest(name=bad_name), self.assertRaises(ValueError):
                    admission.container_admit({**request, "sourceSnapshot": bad_name}, self.cache)
            incomplete = {key: value for key, value in sources.items() if key != "local-fixture.py"}
            with self.assertRaisesRegex(ValueError, "source closure"):
                admission.container_admit({**request, "helperSources": incomplete}, self.cache)
            changed = self.cache / name / "local-fixture.py"
            changed.chmod(0o600)
            changed.write_bytes(b"raise RuntimeError('never execute changed source')")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                admission.container_admit(request, self.cache)
        loader.assert_not_called()

    def test_android_policy_does_not_accept_an_ios_manifest_or_seed_relabel(self):
        for changes in ({"platform": "ios"}, {"kind": "ios-files-synthetic-fixtures"},
                        {"source": {**self.manifest["source"], "attachmentId": "66666666-6666-4666-8666-666666666666"}},
                        {"apiOrigin": "https://127.0.0.1:8453"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                admission.validate_manifest({**self.manifest, **changes}, self.core, self.core, self.seed, "txt", self.expected)

    def test_actual_snapshotted_cli_loads_closed_sources_and_refuses_nonlocal_before_any_auth(self):
        request, _ = admission.host_request(self.args())
        name, sources = admission.snapshot_sources(self.cache, request)
        request.update(sourceSnapshot=name, helperSources=sources)
        result = subprocess.run([os.sys.executable, "-B", str(self.cache / name / "admit-android-file-source.py"), "_container"],
                                input=json.dumps(request), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env={**os.environ, "CASEOPS_ENV": "production"}, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(result.stderr), {"sourceRouteAdmitted": False, "error": "ValueError",
                         "reason": "Only the local fixture API may admit sources"})
        self.assertFalse((self.cache / "credentials.json").exists())
        self.assertFalse((self.cache / "gateway-routes.json").exists())

    def test_container_tls_uses_fixed_compose_listener_and_public_dynamic_host_without_verification_bypass(self):
        events = []
        raw, secured = object(), object()
        class Context:
            def wrap_socket(inner, connection, *, server_hostname):
                self.assertIs(connection, raw)
                events.append(("verified-hostname", server_hostname))
                return secured
        class Response:
            status = 206
            def read(inner, bound):
                self.assertEqual(bound, 17)
                return b"public-synthetic"
            def getheaders(inner):
                return [("Cache-Control", "private, no-store")]
        class Connection:
            def __init__(inner, host, port, timeout):
                events.append(("http", host, port, timeout))
            def request(inner, method, path, *, headers):
                self.assertIs(inner.sock, secured)
                events.append(("request", method, path, headers))
            def getresponse(inner):
                return Response()
            def close(inner):
                events.append(("closed",))
        with patch.object(admission.ssl, "create_default_context", return_value=Context()) as context, \
             patch.object(admission.socket, "create_connection", return_value=raw) as connect, \
             patch.object(admission.http.client, "HTTPConnection", Connection):
            result = admission.tls_get(self.cache, self.core, b"synthetic-ca", "/public-test-path", byte_range="bytes=0-15", maximum=16)
        context.assert_called_once_with(cadata="synthetic-ca")
        connect.assert_called_once_with(("gateway", 8443), timeout=3)
        self.assertEqual(result, (206, b"public-synthetic", {"cache-control": "private, no-store"}))
        self.assertEqual(events[0], ("verified-hostname", "localhost"))
        self.assertEqual(events[1], ("http", "localhost", 8443, 3))
        self.assertEqual(events[2], ("request", "GET", "/public-test-path", {
                         "X-CaseOps-Automated-Test": "no-paid-providers", "Host": "localhost:8453", "Range": "bytes=0-15"}))
        self.assertEqual(events[-1], ("closed",))


if __name__ == "__main__":
    unittest.main()
