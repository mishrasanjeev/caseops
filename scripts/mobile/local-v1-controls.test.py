"""Synthetic protocol/FS controls only. No API, provider, DB or native actions."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("v1_controls_unit", Path(__file__).with_name("local-v1-controls.py"))
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)
U = lambda number: f"00000000-0000-4000-8000-{number:012d}"
ROUTE = f"/api/matters/{U(1)}/tasks"


def registration():
    return {"schemaVersion": 1, "kind": "registered-v1-qa-controls", "environment": "docker-integration",
            "readyForLive": True, "preparedOnly": False, "observed": True,
            "syntheticDataOnly": True, "noPaidMarker": M.MARKER, "directDatabaseWrites": False,
            "nativeMutationsForwardedByControls": False, "sourceSha": "a" * 40, "runId": "synthetic-run",
            "companyId": U(2), "registrationId": "c" * 32, "expiresAt": 1100,
            "capabilities": list(M.CAPABILITIES), "caseControlLimits": dict(M.CASE_LIMITS), "syntheticIds": [U(1), U(2), U(3), U(40)],
            "exactRoutes": [f"POST {ROUTE}", f"GET {ROUTE}", "GET /api/contracts/", f"PATCH /api/recipient-inbox/{U(40)}"],
            "inboxNotifications": [{"id": U(40), "companyId": U(2), "recipientMembershipId": U(6), "target": {"kind": "matter", "id": U(1)}, "deliveryEvidence": {"path": "/synthetic/inbox.json", "sha256": "f" * 64}}],
            "authorityEvidence": {"path": "/synthetic/authority.json", "sha256": "e" * 64, "uid": os.getuid()}, "ownerExactRoutes": [], "ownerRecipes": [], "actors": {name: {"companyId": U(2 if name != "second-company" else 8), "membershipId": U(index + 5), "credentialEvidence": {"path": f"/synthetic/{name}.json", "sha256": "e" * 64, "uid": os.getuid()}} for index, name in enumerate(("owner", "member", "second-company"))}}


class Owner:
    def __init__(self):
        self.calls = []
    def __call__(self, capability, case, args):
        self.calls.append((capability, case, args))
        return {"value": {"id": U(1)}}
    def close_case(self, _case):
        return {"allOwnedControlsClosed": True}
    def close(self):
        pass
    def restoration_complete(self):
        return True


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.owner, self.events, self.claims = Owner(), [], []
        self.manager = M.V1Controls(registration(), "b" * 64, "d" * 64, owner=self.owner,
            now=lambda: 1000, persist=self.events.append, claim=self.claims.append)
        self.sequence = 0
    def call(self, capability, args=None, case="WORK-01", **kwargs):
        self.sequence += 1
        request = {"schemaVersion": 1, "capability": capability, "args": args or {}, "caseId": case,
                   "runId": "synthetic-run", "operationId": f"synthetic-run:{case}:{self.sequence}", "registrationSha256": "b" * 64}
        return self.manager.handle(json.dumps(request).encode(), marker=kwargs.get("marker", M.MARKER), authority=kwargs.get("authority", "d" * 64))

    def test_default_disabled_has_no_private_or_transport_work(self):
        with patch.object(M, "checked_json") as read:
            self.assertIsNone(M.from_environment(Path("/not-read"), "unused", environment={}))
            read.assert_not_called()

    def test_actual_owned_private_reference_composes_registration_and_normal_login(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); target = root / 'member.json'
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(descriptor, b'{"email":"synthetic@example.invalid","password":"synthetic-only","company_slug":"synthetic"}')
                actual_uid = os.fstat(descriptor).st_uid
            finally:
                os.close(descriptor)
            value = registration()
            for actor in value['actors'].values():
                actor['credentialEvidence'] = {'path': str(target), 'sha256': M.sha(target.read_bytes()), 'uid': actual_uid}
            M.validate_registration(value, source='a' * 40, run='synthetic-run', now=1000)
            binding = value['actors']['member']; calls = []; closed = []
            class Client:
                def __init__(self):
                    self.headers = {}; self.cookies = SimpleNamespace(clear=lambda: None)
                def stream(self, method, route, **kwargs):
                    calls.append((method, route, sorted(kwargs['json'])))
                    body = M.canonical({'company': {'id': binding['companyId']}, 'membership': {'id': binding['membershipId'], 'role': 'member'}, 'capabilities': ['matters:write'], 'access_token': 'synthetic-only'})
                    class Response:
                        status_code = 200; headers = {}
                        def __enter__(self): return self
                        def __exit__(self, *_): pass
                        def iter_raw(self): yield body
                    return Response()
                def close(self): closed.append(True)
            owner = M.RegisteredOwner(value, root, factory=Client)
            self.assertIs(owner.client('member'), owner.client('member'))
            self.assertEqual(calls, [('POST', '/api/auth/login', ['company_slug', 'email', 'password'])])
            owner.close(); self.assertEqual(closed, [True])

    def test_missing_untyped_or_wrong_private_uid_refuses_before_private_bytes_or_http(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve(); target = root / 'member.json'
            target.write_bytes(b'{"email":"synthetic@example.invalid"}'); target.chmod(0o600)
            actual_uid = target.lstat().st_uid
            for missing in (True, False):
                value = registration()
                for actor in value['actors'].values():
                    actor['credentialEvidence'] = {'path': str(target), 'sha256': M.sha(target.read_bytes()), **({} if missing else {'uid': True})}
                with patch.object(M.os, 'open') as opened, self.assertRaises(AssertionError):
                    M.validate_registration(value, source='a' * 40, run='synthetic-run', now=1000)
                opened.assert_not_called()
            value = registration()
            for actor in value['actors'].values():
                actor['credentialEvidence'] = {'path': str(target), 'sha256': M.sha(target.read_bytes()), 'uid': actual_uid + 1}
            M.validate_registration(value, source='a' * 40, run='synthetic-run', now=1000)
            factory = Mock()
            with patch.object(M.os, 'read') as read, patch.object(M.os, 'close', wraps=os.close) as close, self.assertRaises(AssertionError):
                M.RegisteredOwner(value, root, factory=factory).client('member')
            read.assert_not_called(); factory.assert_not_called(); self.assertEqual(close.call_count, 1)

    def test_cloud_nonlocal_and_unknown_flags_refuse_before_file_read(self):
        for changes in ({"CASEOPS_MOBILE_V1_CONTROLS": "true"}, {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "production"},
                        {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "K_SERVICE": "cloud"}):
            with patch.object(M, "checked_json") as read, self.assertRaises(AssertionError):
                M.from_environment(Path("/not-read"), "unused", environment=changes)
            read.assert_not_called()

    def test_verified_registration_buffer_is_checked_before_any_named_or_private_read(self):
        value = registration()
        value["implementationSha256"] = "c" * 64
        raw = json.dumps(value).encode()
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "CASEOPS_RELEASE_SHA": "a" * 40,
               "CASEOPS_MOBILE_V1_REGISTRATION": "/not-read/registration.json", "CASEOPS_MOBILE_V1_REGISTRATION_SHA256": M.sha(raw)}
        with patch.object(M, "checked_json") as named, patch.object(M.time, "time", return_value=1000), self.assertRaisesRegex(AssertionError, "IMPLEMENTATION_CHANGED"):
            M.from_environment(Path("/not-read"), "synthetic-run", environment=env,
                verified_implementation_sha256="d" * 64, verified_registration_bytes=raw)
        named.assert_not_called()

    def test_replaced_registration_bytes_cannot_reach_private_read_or_runtime(self):
        env = {"CASEOPS_MOBILE_V1_CONTROLS": "1", "CASEOPS_ENV": "local", "CASEOPS_RELEASE_SHA": "a" * 40,
               "CASEOPS_MOBILE_V1_REGISTRATION": "/not-read/registration.json", "CASEOPS_MOBILE_V1_REGISTRATION_SHA256": "f" * 64}
        with patch.object(M, "checked_json") as named, self.assertRaisesRegex(AssertionError, "VERIFIED_REGISTRATION_BYTES"):
            M.from_environment(Path("/not-read"), "synthetic-run", environment=env,
                verified_implementation_sha256="d" * 64, verified_registration_bytes=b"{}")
        named.assert_not_called()

    def test_registration_exact_source_run_expiry_ids_and_routes(self):
        self.assertEqual(M.validate_registration(registration(), source="a" * 40, run="synthetic-run", now=1000)["companyId"], U(2))
        for key, value in (("sourceSha", "e" * 40), ("expiresAt", 1000), ("syntheticIds", [U(1), U(1)]),
                           ("exactRoutes", ["GET /api/matters/*"]), ("registrationId", "../escape"),
                           ("ownerExactRoutes", ["POST /api/auth/native/token"])):
            changed = registration(); changed[key] = value
            with self.assertRaises(AssertionError):
                M.validate_registration(changed, source="a" * 40, run="synthetic-run", now=1000)

    def test_authority_and_marker_refusal_precede_owner_and_claim(self):
        for override in ({"marker": ""}, {"authority": "x" * 64}):
            with self.assertRaises(AssertionError):
                self.call("readWorkspace", {"matterId": U(1)}, **override)
        self.assertEqual(self.owner.calls, [])
        self.assertEqual(self.claims, [])

    def test_operation_claim_precedes_owner_and_replay_is_refused(self):
        self.call("readWorkspace", {"matterId": U(1)})
        self.assertEqual(len(self.claims), 1)
        self.sequence = 0
        with self.assertRaises(AssertionError):
            self.call("readWorkspace", {"matterId": U(1)})
        self.assertEqual(len(self.owner.calls), 1)

    def test_malformed_request_has_fixed_json_error_and_no_owner(self):
        with self.assertRaisesRegex(ValueError, "^V1_CONTROL_JSON_REQUIRED$"):
            self.manager.handle(b"{SYNTHETIC_PRIVATE_NOT_REFLECTED", marker=M.MARKER, authority="d" * 64)
        self.assertEqual(self.owner.calls, [])

    def test_case_and_finite_operation_limits_cannot_grow(self):
        for _ in range(M.CASE_LIMITS["WORK-01"]):
            self.call("readWorkspace", {"matterId": U(1)})
        with self.assertRaises(AssertionError):
            self.call("readWorkspace", {"matterId": U(1)})
        self.assertEqual(len(self.owner.calls), M.CASE_LIMITS["WORK-01"])

    def test_registration_reserves_four_identity_slots_before_any_owner_or_private_work(self):
        self.assertEqual(M.NATIVE_CREATIONS, (("WORK-01", "task"), ("WORK-03", "hearing"), ("WORK-04", "follow-up-task"), ("WORK-06", "unknown-save-task")))
        value = registration(); value["syntheticIds"] = [U(index) for index in range(1, 93)]
        self.assertEqual(len(M.validate_registration(value, source="a" * 40, run="synthetic-run", now=1000)["syntheticIds"]), 92)
        value["syntheticIds"].append(U(93))
        with self.assertRaisesRegex(AssertionError, "V1_FOUR_NATIVE_IDENTITIES_MUST_BE_RESERVED"):
            M.validate_registration(value, source="a" * 40, run="synthetic-run", now=1000)
        self.assertEqual(self.owner.calls, [])

    def test_four_new_success_ack_identities_fit96_and_fifth_refuses_without_replaying_or_rewriting_ack(self):
        value = registration(); value["syntheticIds"] = [U(index) for index in range(1, 93)]
        manager = M.V1Controls(value, "b" * 64, "d" * 64, owner=self.owner, now=lambda: 1000, persist=self.events.append, claim=self.claims.append)
        for index in range(4):
            response = json.dumps({"id": U(1000 + index), "matter_id": U(1), "updated_at": "2026-10-27T00:00:00+00:00"}).encode()
            unchanged = bytes(response)
            self.assertFalse(manager.after_native("POST", ROUTE, native=True, request_id=f"native-{index}", sequence=index,
                body=b'{"title":"Synthetic owned creation","expected_lifecycle_version":0}', query="", status=200, data=response, intercept=None))
            self.assertEqual(response, unchanged)
        self.assertEqual(len(manager.known_ids), 96)
        self.assertEqual(len(manager.records), 4)
        with self.assertRaises(AssertionError):
            manager.after_native("POST", ROUTE, native=True, request_id="fifth-unexpected", sequence=4,
                body=b'{"title":"Unexpected creation","expected_lifecycle_version":0}', query="", status=200,
                data=json.dumps({"id": U(1004), "matter_id": U(1), "updated_at": "2026-10-27T00:00:00+00:00"}).encode(), intercept=None)
        self.assertEqual(len(manager.known_ids), 96)
        self.assertEqual(len(manager.records), 4)
        self.assertNotIn(U(1004), manager.known_ids)
        self.assertEqual(self.owner.calls, [])

    def test_native_barrier_reaches_before_single_forward_and_releases_once(self):
        arm = self.call("armWorkBarrier", {"method": "POST", "route": ROUTE, "point": "before-upstream-mutation", "maxUses": 1})
        result, failure = [], []
        entered, released = threading.Event(), threading.Event()
        class Latch:
            def wait(self, timeout): entered.set(); return released.wait(timeout)
            def set(self): released.set()
        self.manager.arms[arm["id"]]["event"] = Latch()
        def native():
            try:
                result.append(self.manager.before_native("POST", ROUTE, native=True, request_id="synthetic-request"))
            except Exception as error:
                failure.append(type(error).__name__)
        thread = threading.Thread(target=native)
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.manager.arms[arm["id"]]["reached"])
            self.assertEqual(self.manager.arms[arm["id"]]["requestsForwarded"], 0)
            self.call("releaseWorkBarrier", {"id": arm["id"]})
        finally:
            self.manager.arms[arm["id"]]["event"].set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failure, [])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["arm"]["requestsForwarded"], 1)
        with self.assertRaises(AssertionError):
            self.call("releaseWorkBarrier", {"id": arm["id"]})
        with self.assertRaises(AssertionError):
            self.manager.before_native("POST", ROUTE, native=True, request_id="not-replayed")

    def test_barrier_expiry_or_cleanup_never_forwards_the_native_request(self):
        arm = self.call("armWorkBarrier", {"method": "POST", "route": ROUTE, "point": "before-upstream-mutation"})
        self.manager.arms[arm["id"]]["expiresAt"] = 1000
        with self.assertRaises(AssertionError):
            self.manager.before_native("POST", ROUTE, native=True, request_id="expired")
        self.assertEqual(self.manager.arms[arm["id"]]["requestsForwarded"], 0)

    def test_unknown_response_requires_actual_200_ack_and_keeps_exact_body_facts(self):
        arm = self.call("armUnknownResponse", {"method": "POST", "route": ROUTE, "mode": "drop-after-successful-upstream-ack"})
        intercept = self.manager.before_native("POST", ROUTE, native=True, request_id="one-request")
        body, response = {"title": "Synthetic native task", "expected_lifecycle_version": 0}, {"id": U(4), "matter_id": U(1), "updated_at": "2026-10-27T00:00:00+00:00"}
        self.assertFalse(self.manager.should_withhold(intercept, 500))
        self.assertTrue(self.manager.should_withhold(intercept, 200))
        withheld = self.manager.after_native("POST", ROUTE, native=True, request_id="one-request", sequence=7,
            body=json.dumps(body).encode(), query="", status=200, data=json.dumps(response).encode(), intercept=intercept)
        self.assertTrue(withheld)
        self.assertEqual(self.manager.records[0]["bodyObservation"], {"keys": sorted(body), "canonicalSha256": M.sha(M.canonical(body))})
        self.assertEqual(self.manager.records[0]["responseObservation"]["id"], U(4))
        self.assertEqual(self.manager.arms[arm["id"]]["requestsForwarded"], 1)
        self.assertIn(U(4), self.manager.known_ids)
        self.assertNotIn(U(4), self.manager.registration["syntheticIds"])
        with self.assertRaises(AssertionError):
            self.manager.before_native("POST", ROUTE, native=True, request_id="second-request")

    def test_source_fault_is_exact_get_and_one_use_without_owner_mutation(self):
        for mode in ("missing", "offline", "malformed"):
            self.call("armSourceFault", {"route": ROUTE, "mode": mode}, case=f"SOURCE-0{1 + len(self.manager.arms)}")
            intercept = self.manager.before_native("GET", ROUTE, native=True, request_id=mode)
            self.assertEqual(intercept["fault"], mode)
            with self.assertRaises(AssertionError):
                self.manager.before_native("GET", ROUTE, native=True, request_id="again")
            intercept["arm"]["closed"] = True
        self.assertEqual(self.owner.calls, [])

    def test_unrelated_and_browser_routes_are_never_intercepted(self):
        self.assertIsNone(self.manager.before_native("POST", ROUTE, native=False, request_id="browser"))
        self.assertIsNone(self.manager.before_native("POST", "/api/unknown", native=True, request_id="unowned"))

    def test_unavailable_notification_observer_refuses_instead_of_fake_zero(self):
        with self.assertRaisesRegex(AssertionError, "V1_READONLY_OBSERVER_UNAVAILABLE"):
            self.call("readNotificationState", {"hearingId": U(1)})
        self.assertEqual(self.owner.calls, [])

    def test_notification_observation_is_scoped_to_known_hearing_only(self):
        seen = []
        self.manager.observer = lambda identity: seen.append(identity) or {"outboxCount": 2, "providerAttempts": 1, "readOnly": True}
        result = self.call("readNotificationState", {"hearingId": U(1)})
        self.assertEqual(result["outboxCount"], 2)
        self.assertEqual(seen, [U(1)])
        with self.assertRaises(AssertionError):
            self.call("readNotificationState", {"hearingId": U(99)})

    def test_cursor_observation_retains_only_exact_hash(self):
        self.manager.after_native("GET", "/api/contracts/", native=True, request_id="page", sequence=2,
            body=b"", query="limit=25&cursor=synthetic%2Bcursor", status=200, data=b"{}", intercept=None)
        row = self.manager.records[0]
        self.assertEqual(row["queryObservation"], {"cursorSha256": M.sha(b"synthetic+cursor")})
        self.assertNotIn("synthetic+cursor", json.dumps(row))

    def test_public_and_private_files_use_same_descriptor_and_fixed_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); target = root / "public.json"; target.write_bytes(b'{"synthetic":true}')
            reference = {"path": str(target), "sha256": M.sha(target.read_bytes())}
            self.assertEqual(M.checked_json(reference, root), {"synthetic": True})
            target.write_bytes(b"{PRIVATE_MALFORMED_INPUT")
            reference["sha256"] = M.sha(target.read_bytes())
            with self.assertRaisesRegex(ValueError, "^V1_CONTROL_JSON_REQUIRED$"):
                M.checked_json(reference, root)
            target.unlink(); target.symlink_to(root / "not-read")
            with self.assertRaises(OSError):
                M.checked_json(reference, root)

    def test_safe_response_recipe_uses_only_previous_own_properties(self):
        self.assertEqual(M.resolve_recipe({"id": {"response": "0.id"}}, [{"id": U(1)}]), {"id": U(1)})
        for value in ("1.id", "0.__proto__", "0.missing", "0.id[0]"):
            with self.assertRaises(AssertionError):
                M.resolve_recipe({"response": value}, [{"id": U(1)}])

    def test_wall_restore_selects_one_actual_subject_record_and_never_an_array_position(self):
        response = {"panel": {"walls": [{"id": U(10), "subject_id": U(4), "subject_type": "membership"},
                                        {"id": U(11), "subject_id": U(3), "subject_type": "membership"}]}}
        selector = {"select": {"response": "0.panel.walls", "where": {"subject_id": U(3), "subject_type": "membership"}, "field": "id"}}
        self.assertEqual(M.resolve_recipe(selector, [response]), U(11))
        response["panel"]["walls"].reverse()
        self.assertEqual(M.resolve_recipe(selector, [response]), U(11))
        for rows in ([], [response["panel"]["walls"][0]] * 2, [{"id": U(12), "subject_id": U(99)}], [{}] * 101):
            with self.assertRaises(AssertionError):
                M.resolve_recipe(selector, [{"panel": {"walls": rows}}])

    def test_actor_registration_keeps_viewer_company_and_private_mapping_distinct(self):
        for change in (lambda value: value["actors"]["second-company"].update(companyId=U(2)),
                       lambda value: value["actors"]["member"].update(membershipId=value["actors"]["owner"]["membershipId"]),
                       lambda value: value["actors"]["member"]["credentialEvidence"].update(path="relative.json")):
            value = registration(); change(value)
            with self.assertRaises(AssertionError):
                M.validate_registration(value, source="a" * 40, run="synthetic-run", now=1000)

    def test_current_viewer_and_denied_workspace_are_actual_actor_reads(self):
        value = registration(); calls = []
        owner = M.RegisteredOwner(value, Path("/not-read"), factory=lambda: None)
        actor = value["actors"]["second-company"]
        current = {"company": {"id": actor["companyId"]}, "membership": {"id": actor["membershipId"], "role": "viewer", "is_active": True},
                   "user": {"is_active": True}, "capabilities": ["matters:read"]}
        owner.client = lambda identity: calls.append(identity) or object()
        from types import SimpleNamespace
        responses = [SimpleNamespace(status_code=200, json=lambda: current), SimpleNamespace(status_code=403)]
        with patch.object(M, "bounded_http", side_effect=responses) as http:
            result = owner("readCurrentActor", "WORK-07", {"actor": "second-company"})
            self.assertEqual(result["value"]["role"], "viewer")
            self.assertNotIn("matters:write", result["value"]["capabilities"])
            self.assertEqual(owner("readWorkspace", "WORK-08", {"actor": "member", "matterId": U(1)}), {"status": 403})
        self.assertEqual(calls, ["second-company", "member"])
        self.assertEqual([call.args[1:] for call in http.call_args_list], [("GET", "/api/auth/me"), ("GET", f"/api/matters/{U(1)}/workspace")])

    def test_viewer_normal_login_rejects_writer_authority_without_retry(self):
        from types import SimpleNamespace
        value = registration(); actor = value["actors"]["second-company"]; closed = []
        class Client:
            headers = {}
            cookies = SimpleNamespace(clear=lambda: None)
            def close(self): closed.append(True)
        owner = M.RegisteredOwner(value, Path("/not-read"), factory=Client)
        response = SimpleNamespace(status_code=200, json=lambda: {"company": {"id": actor["companyId"]},
            "membership": {"id": actor["membershipId"], "role": "viewer"}, "capabilities": ["matters:write"], "access_token": "synthetic-only"})
        with patch.object(M, "checked_json", return_value={"email": "synthetic@example.invalid", "password": "synthetic-only", "company_slug": "synthetic"}), patch.object(M, "bounded_http", return_value=response) as http:
            with self.assertRaisesRegex(RuntimeError, "^V1_OWNER_AUTHENTICATION_INCOMPLETE_NO_RETRY$"):
                owner.client("second-company")
            with self.assertRaisesRegex(AssertionError, "V1_OWNER_AUTHENTICATION_NOT_REPLAYABLE"):
                owner.client("second-company")
        self.assertEqual(http.call_count, 1); self.assertEqual(closed, [True])

    def test_registered_owner_recipe_is_single_attempt_and_cleanup_is_separate(self):
        value = registration()
        value["ownerExactRoutes"] = [f"PATCH {ROUTE}/{U(3)}"]
        value["ownerRecipes"] = [{"id": "mutate", "caseId": "WORK-05", "capability": "changeChild", "argumentsSha256": M.sha(M.canonical({"id": U(3)})),
            "requests": [{"method": "PATCH", "route": f"{ROUTE}/{U(3)}", "body": {"title": "Synthetic change"}, "expectedStatuses": [200]}], "result": {"completed": True}}]
        owner = M.RegisteredOwner(value, Path("/not-read"), factory=lambda: None); calls = []
        class Response:
            status_code, content = 200, b"{}"
            headers = {}
            def json(self): return {}
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def iter_raw(self): yield b"{}"
        class Client:
            def stream(self, *args, **kwargs): calls.append((args, kwargs)); return Response()
        owner.client = lambda _actor: Client()
        self.assertEqual(owner("changeChild", "WORK-05", {"id": U(3)}), {"completed": True})
        with self.assertRaisesRegex(AssertionError, "V1_OWNER_RECIPE_REPLAY_REFUSED"):
            owner("changeChild", "WORK-05", {"id": U(3)})
        self.assertEqual(len(calls), 1)
        self.assertEqual(owner.close_case("WORK-05"), {"allOwnedControlsClosed": True})

    def test_old_path_append_follows_symlink_but_new_journal_refuses_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); victim = root / "kept.json"; victim.write_bytes(b"original")
            target = root / ("v1-control-events-" + "a" * 32 + ".jsonl"); target.symlink_to(victim)
            # Retained counterexample to the former pathname append operation.
            with target.open("a") as output:
                output.write("old-append")
            self.assertEqual(victim.read_bytes(), b"originalold-append")
            victim.write_bytes(b"original")
            with self.assertRaises(OSError):
                M.create_journal(root, "a" * 32)
            self.assertEqual(victim.read_bytes(), b"original")

    def test_held_journal_checks_replacement_and_closes_the_owned_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); descriptors = []; original_open = M.os.open
            def opened(*args, **kwargs):
                descriptor = original_open(*args, **kwargs); descriptors.append(descriptor); return descriptor
            with patch.object(M.os, "open", side_effect=opened):
                persist, close = M.create_journal(root, "b" * 32)
            persist({"type": "synthetic"})
            target = root / ("v1-control-events-" + "b" * 32 + ".jsonl")
            target.rename(root / "kept-original.jsonl"); target.write_bytes(b"replacement")
            try:
                with self.assertRaises(AssertionError): persist({"type": "not-written"})
            finally:
                close()
            self.assertEqual(target.read_bytes(), b"replacement")
            with self.assertRaises(OSError): os.fstat(descriptors[0])

    def test_owner_http_consumption_is_bounded_and_response_always_closed(self):
        closed, calls = [], []
        class Response:
            headers, status_code = {}, 200
            def __enter__(self): return self
            def __exit__(self, *_args): closed.append(True)
            def iter_raw(self):
                yield b"x" * (M.LIMITS["responseBytes"] + 1)
                raise AssertionError("must not consume another chunk")
        class Client:
            def stream(self, *args, **kwargs): calls.append((args, kwargs)); return Response()
        with self.assertRaisesRegex(AssertionError, "V1_OWNER_RESPONSE_BOUND"):
            M.bounded_http(Client(), "GET", "/api/build")
        self.assertEqual(len(calls), 1); self.assertEqual(closed, [True])
        self.assertEqual(calls[0][1]["headers"]["X-CaseOps-Automated-Test"], M.MARKER)

    def test_owner_http_parse_failure_never_reflects_response_content(self):
        class Response:
            headers, status_code = {}, 200
            def __enter__(self): return self
            def __exit__(self, *_args): pass
            def iter_raw(self): yield b"{SYNTHETIC_PRIVATE_NOT_FOR_ERRORS"
        class Client:
            def stream(self, *_args, **_kwargs): return Response()
        with self.assertRaisesRegex(ValueError, "^V1_OWNER_RESPONSE_JSON_REQUIRED$"):
            M.bounded_http(Client(), "GET", "/api/build")

    def test_final_cleanup_releases_authority_and_journal_without_replaying_policy(self):
        closed = []
        self.manager.close_journal = lambda: closed.append(True)
        self.owner.restoration_complete = lambda: False
        result = self.call("closeRunControls", case="INBOX-01")
        self.assertFalse(result["allOwnedControlsClosed"])
        self.assertTrue(result["authorityCleared"])
        self.assertTrue(self.manager.closed)
        self.assertEqual(self.manager.authority, "")
        self.assertEqual(closed, [True])
        self.assertEqual(self.owner.calls, [])

    def test_inbox_observer_keeps_exact_native_actor_body_and_success_response(self):
        route = f"/api/recipient-inbox/{U(40)}"
        body = {"status": "read", "expected_status": "unread"}
        value = {"id": U(40), "status": "read", "target": {"kind": "matter", "id": U(1)}}
        self.assertFalse(self.manager.after_native("PATCH", route, native=True, request_id="inbox-one", sequence=1,
            body=json.dumps(body).encode(), query="", status=200, data=json.dumps(value).encode(), intercept=None))
        observed = self.manager.records[0]
        self.assertEqual(observed["bodyObservation"], {"keys": ["expected_status", "status"], "canonicalSha256": M.sha(M.canonical(body))})
        self.assertEqual(observed["responseObservation"], value)
        self.assertEqual(self.owner.calls, [])

    def test_inbox_observer_rejects_extra_dto_fields_wrong_recipient_and_wrong_response(self):
        route = f"/api/recipient-inbox/{U(40)}"
        body = {"status": "read", "expected_status": "unread"}
        response = {"id": U(40), "status": "read", "target": {"kind": "matter", "id": U(1)}}
        for changed_body, changed_response in (({**body, "title": "unreviewed"}, response),
                                               ({**body, "status": "unknown"}, response),
                                               (body, {**response, "id": U(99)}),
                                               (body, {**response, "target": {"kind": "matter", "id": U(99)}})):
            with self.assertRaises(AssertionError):
                self.manager.after_native("PATCH", route, native=True, request_id="rejected", sequence=2,
                    body=json.dumps(changed_body).encode(), query="", status=200, data=json.dumps(changed_response).encode(), intercept=None)
        value = registration(); value["inboxNotifications"][0]["recipientMembershipId"] = U(99)
        with self.assertRaises(AssertionError): M.validate_registration(value, source="a" * 40, run="synthetic-run", now=1000)

    def test_owner_cannot_receive_inbox_status_mutation_authority(self):
        value = registration(); value["ownerExactRoutes"] = [f"PATCH /api/recipient-inbox/{U(40)}"]
        with self.assertRaisesRegex(AssertionError, "INBOX_STATUS_WRITES_BELONG_TO_NATIVE_ACTOR_ONLY"):
            M.validate_registration(value, source="a" * 40, run="synthetic-run", now=1000)
        with self.assertRaises(AssertionError):
            self.call("closeRunControls", case="WORK-08")

    def test_concurrent_control_refuses_before_claim_or_owner_call(self):
        self.manager.dispatch_lock.acquire()
        try:
            with self.assertRaisesRegex(AssertionError, "V1_SERIAL_CONTROL_REQUIRED"):
                self.call("readWorkspace", {"matterId": U(1)})
        finally:
            self.manager.dispatch_lock.release()
        self.assertEqual(self.claims, [])
        self.assertEqual(self.owner.calls, [])


if __name__ == "__main__":
    unittest.main()
