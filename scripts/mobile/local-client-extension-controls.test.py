"""Offline fixed-profile tests. No API, native driver, DB or provider calls."""
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch
import copy
import hashlib
import json
import os
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
source = (HERE / "local-client-extension-controls.py").read_bytes()
p = ModuleType("client_extension_controls")
exec(compile(source, str(HERE / "local-client-extension-controls.py"), "exec"), p.__dict__)

def identity(n): return "00000000-0000-4000-8000-" + format(n, "012x")
def registration():
    actor = lambda user, company, member: {"userId": identity(user), "companyId": identity(company), "membershipId": identity(member), "credentialEvidence": {"path": "/synthetic/member.json", "sha256": "e" * 64, "uid": os.getuid()}}
    matter = identity(10)
    return {"kind": "registered-native-client-extension-controls", "profile": p.PROFILE,
        "schemaVersion": 1, "registrationId": "f"*32, "observed": True, "readyForLive": True, "preparedOnly": False,
        "environment": "docker-integration", "syntheticDataOnly": True, "noPaidMarker": "no-paid-providers",
        "directDatabaseWrites": False, "nativeMutationsForwardedByControls": False,
        "sourceSha": "a" * 40, "runId": "synthetic-owned-epoch", "expiresAt": 1100,
        "baseImplementationSha256": p.BASE_SHA256, "capabilities": list(p.CAPABILITIES),
        "caseIds": list(p.CASE_IDS), "caseControlLimits": {key: 12 for key in p.CASE_IDS},
        "platform": "ios", "clientVersion": "1.2.3", "companyId": identity(1),
        "actors": {"owner": actor(2, 1, 3), "member": actor(4, 1, 5), "second-company": actor(6, 7, 8)},
        "syntheticIds": [identity(i) for i in range(1, 25)], "cameraMatterId": matter,
        "readthroughMatterId": identity(11), "revocableMatterId": identity(12), "byteSourceId": identity(13),
        "navigableMatterIds": [matter], "readthroughMatterIds": [identity(11), identity(12)], "readthroughTargets": [],
        "exactRoutes": ["GET /api/matters/" + matter, "GET /api/auth/native/compatibility", "GET /api/auth/native/sessions", "GET /api/matters/" + matter + "/workspace", "POST /api/matters/" + matter + "/attachments", "GET /api/matters/" + matter + "/attachments/" + identity(13) + "/download", "GET /api/matter-readthrough/" + identity(11) + "/recommendations", "GET /api/matter-readthrough/" + identity(12) + "/recommendations"],
        "ownerRecipes": [], "ownerExactRoutes": [], "scannerConfigurationEvidence": {"path": "/synthetic/config.json", "sha256": "b" * 64}}

class Owner:
    def __init__(self): self.closed = False; self.logins = []
    def client(self, actor): self.logins.append(actor); return actor
    def close_case(self, _case): return {"allOwnedControlsClosed": True}
    def close(self): self.closed = True
    def restoration_complete(self): return True

class Protocol(unittest.TestCase):
    def setUp(self):
        self.v = registration(); self.owner = Owner(); self.events = []; self.claims = []; self.closed = []; self.calls = []; self.number = 0
        self.response = SimpleNamespace(status_code=200, json=lambda: {}, content=b"")
        def http(actor, method, route, *body):
            self.calls.append((actor, method, route, body)); return self.response
        self.c = p.Controls(self.v, "a" * 64, "b" * 64, owner=self.owner, base=SimpleNamespace(bounded_http=http), persist=self.events.append, claim=self.claims.append, close_journal=lambda: self.closed.append(True), now=lambda: 1000)
    def call(self, capability, args=None, case="CX28-CAM-01", operation=None, **change):
        self.number += 1
        value = {"schemaVersion": 1, "capability": capability, "caseId": case, "operationId": operation or "operation-" + str(self.number), "runId": self.v["runId"], "registrationSha256": "a" * 64, "args": args or {}}
        value.update(change)
        return self.c.handle(json.dumps(value).encode(), marker="no-paid-providers", authority="b" * 64)
    def native(self, route="/api/auth/me", method="GET", data=b"{}", status=200, version=None):
        self.c.validate_native_request(method, route, native=True, body=b"", query="", authorization="PRIVATE_SYNTHETIC", cookie_present=False, request_id="0" * 16, client_version_headers=version)
        return self.c.after_native(method, route, native=True, request_id="0" * 16, sequence=len(self.c.records)+1, body=b"", query="", status=status, data=data, intercept=None)
    def test_complete_literal_registration_and_bounds(self):
        p.validate_registration(self.v, source="a" * 40, run=self.v["runId"], now=1000)
        self.assertEqual(len(p.CASE_IDS), 24); self.assertEqual(p.LIMITS["operations"], 24 * 12 + 1)
    def test_cloud_pending_foreign_extra_route_or_actor_refuses(self):
        for change in ({"readyForLive": False}, {"environment": "production"}, {"companyId": identity(22)}, {"exactRoutes": self.v["exactRoutes"] + ["DELETE /api/users/1"]}, {"ownerRecipes": [{"caller": "body"}]}):
            with self.subTest(change=tuple(change)):
                value = copy.deepcopy(self.v); value.update(change)
                with self.assertRaises(AssertionError): p.validate_registration(value, source="a" * 40, run=self.v["runId"], now=1000)
        self.assertEqual(self.calls, [])
    def test_wrong_marker_authority_capability_case_epoch_refuse_before_owner(self):
        with self.assertRaises(AssertionError): self.c.handle(b"{}", marker="ordinary", authority="b"*64)
        with self.assertRaises(AssertionError): self.c.handle(b"{}", marker="no-paid-providers", authority="wrong")
        for change in ({"capability": "rawSQL"}, {"caseId": "FILES-01"}, {"runId": "foreign"}, {"registrationSha256": "e"*64}):
            with self.assertRaises(AssertionError): self.call(change.get("capability", "readClientMetadata"), **{key: value for key, value in change.items() if key != "capability"})
        self.assertEqual(self.calls, []); self.assertEqual(self.claims, [])
    def test_replayed_operation_has_one_claim_and_no_second_read(self):
        self.call("readClientMetadata", operation="one")
        with self.assertRaises(AssertionError): self.call("readClientMetadata", operation="one")
        self.assertEqual(self.claims, ["one"])
    def test_twelve_case_calls_are_literal_bound(self):
        for _ in range(12): self.call("readClientMetadata")
        with self.assertRaises(AssertionError): self.call("readClientMetadata")
        self.assertEqual(len(self.claims), 12)
    def test_metadata_duplicates_malformed_and_oversize_refuse_before_record(self):
        for values in (["1.2.3", "1.2.3"], ["01.2.3"], ["1.2.3 "], ["1.2.3\nprivate"]):
            with self.assertRaises(AssertionError): self.native(version=values)
        self.assertEqual(self.c.records, []); self.assertEqual(self.events, [])
    def test_actual_metadata_never_retains_authorization_or_bodies(self):
        self.native(version=["1.2.3"])
        observed = self.call("readClientMetadata")["value"]
        self.assertEqual(observed["requests"][0]["clientVersion"], "1.2.3")
        self.assertNotIn("PRIVATE_SYNTHETIC", json.dumps(self.events))
        self.assertNotIn("body", json.dumps(self.c.records))
    def test_actual_token_server_identity_only_and_current_session_readback(self):
        actor = self.v["actors"]["member"]; session = identity(20)
        value = {"user": {"id": actor["userId"]}, "company": {"id": actor["companyId"]}, "membership": {"id": actor["membershipId"]}, "session_id": session, "access_token": "PRIVATE_SYNTHETIC", "refresh_token": "PRIVATE_SYNTHETIC"}
        self.native("/api/auth/native/token", "POST", json.dumps(value).encode(), version=["1.2.3"])
        self.response.json = lambda: {"sessions": [{"id": session, "revoked_at": None}]}
        identity_value = self.call("readNativeSessionIdentity")["value"]
        self.assertEqual(identity_value["sessionId"], session); self.assertNotIn("PRIVATE_SYNTHETIC", json.dumps(self.events))
        self.assertEqual(self.calls[-1][2], "/api/auth/native/sessions")
    def test_foreign_token_response_never_promotes_identity(self):
        value = {"user": {"id": identity(20)}, "company": {"id": identity(21)}, "membership": {"id": identity(22)}, "session_id": identity(23)}
        with self.assertRaises(AssertionError): self.native("/api/auth/native/token", "POST", json.dumps(value).encode())
        self.assertIsNone(self.c.last_grant); self.assertEqual(self.events, [])
    def test_cold_prompt_oracle_reports_network_facts_not_securestore_claims(self):
        checkpoint = self.call("beginColdPromptObservation")["value"]
        self.assertEqual(self.call("readPromptObservation", {"checkpoint": checkpoint})["value"]["refreshOrPrivateProfileRequests"], 0)
        self.native()
        actual = self.call("readPromptObservation", {"checkpoint": checkpoint})["value"]
        self.assertEqual(actual["successfulProfile"], 1); self.assertNotIn("nativeMarkerProofBeforeCredentialUse", actual)
    def test_attachment_list_uses_actual_workspace_contract(self):
        self.response.json = lambda: {"attachments": [{"id": identity(20)}]}
        value = self.call("readAttachments", {"matterId": self.v["cameraMatterId"]})["value"]
        self.assertEqual(value, [{"id": identity(20)}]); self.assertTrue(self.calls[-1][2].endswith("/workspace"))
    def test_upload_requires_exact_parent_hash_and_fixed_gateway_bound(self):
        route = "/api/matters/" + self.v["cameraMatterId"] + "/attachments"
        value = {"id": identity(20), "matter_id": self.v["cameraMatterId"], "sha256_hex": "a"*64, "size_bytes": 900001}
        with self.assertRaises(AssertionError): self.native(route, "POST", json.dumps(value).encode())
        self.assertIsNone(self.c.upload)
        value["size_bytes"] = 3; self.native(route, "POST", json.dumps(value).encode())
        self.assertEqual(self.c.upload["id"], identity(20)); self.assertEqual(len(self.c.dynamic_routes), 1)
    def test_owned_wall_normal_api_ack_then_exact_single_restore(self):
        value = {"id": identity(20), "matter_id": self.v["revocableMatterId"], "excluded_membership_id": self.v["actors"]["member"]["membershipId"]}
        self.response.json = lambda: value
        self.call("readthroughAccessCheckpoint", {"phase": "revoke"}, case="CX28-READ-02")
        self.assertEqual(self.calls[-1][0:2], ("owner", "POST")); self.assertEqual(self.c.wall, identity(20))
        self.response.status_code = 204
        self.call("readthroughAccessCheckpoint", {"phase": "restore"}, case="CX28-READ-02")
        self.assertEqual(self.calls[-1][0:2], ("owner", "DELETE")); self.assertTrue(self.calls[-1][2].endswith("/"+identity(20))); self.assertIsNone(self.c.wall)
        with self.assertRaises(AssertionError): self.call("readthroughAccessCheckpoint", {"phase": "restore"}, case="CX28-READ-02")
    def test_unknown_wall_post_does_not_replay_or_invent_cleanup(self):
        self.response.status_code = 502
        with self.assertRaises(AssertionError): self.call("readthroughAccessCheckpoint", {"phase": "revoke"}, case="CX28-READ-02")
        self.assertTrue(self.c.wall_uncertain)
        with self.assertRaises(AssertionError): self.call("closeCase", case="CX28-READ-02")
        with self.assertRaises(AssertionError): self.call("readthroughAccessCheckpoint", {"phase": "revoke"}, case="CX28-READ-02")
        self.assertEqual(len(self.calls), 1)
    def test_close_journal_and_owner_once_even_after_explicit_close_run(self):
        result = self.call("closeRun", case="CX28-READ-04")["value"]
        self.assertTrue(result["journalClosed"]); self.c.close(); self.assertEqual(self.closed, [True]); self.assertTrue(self.owner.closed); self.assertIsNone(self.c.authority)

class ResourceCleanup(unittest.TestCase):
    def test_close_run_owner_failure_independently_closes_journal_and_never_returns_ack(self):
        owner=Owner();closed=[];original=RuntimeError("synthetic owner close failure")
        def fail(): raise original
        owner.close=fail
        c=p.Controls(registration(),"a"*64,"b"*64,owner=owner,base=SimpleNamespace(),close_journal=lambda:closed.append(True),now=lambda:1000)
        with self.assertRaises(RuntimeError) as result:c._execute("closeRun","CX28-VERSION-04",{})
        self.assertIs(result.exception,original);self.assertEqual(closed,[True]);self.assertTrue(c.closed);self.assertIsNone(c.authority)

    def test_actual_initializer_closes_real_journal_on_owner_or_controls_constructor_failure(self):
        base=ModuleType("real_client_base");exec(compile((HERE/"local-v1-controls.py").read_bytes(),str(HERE/"local-v1-controls.py"),'exec'),base.__dict__)
        for failed in ("owner","controls"):
            with self.subTest(failed=failed),tempfile.TemporaryDirectory() as raw:
                root=Path(raw).resolve();v=registration();v.update(registrationId="f"*32,backendRevision="api",webRevision="web",implementationSha256="c"*64,authorityEvidence={"path":str(root/'authority.json'),"sha256":"d"*64,"uid":os.getuid()},expiresAt=__import__('time').time()+100)
                b=json.dumps(v).encode();env={"CASEOPS_ENV":"local","CASEOPS_MOBILE_V1_CONTROLS":"1","CASEOPS_MOBILE_V1_PROFILE":p.PROFILE,"CASEOPS_MOBILE_V1_REGISTRATION_SHA256":hashlib.sha256(b).hexdigest(),"CASEOPS_RELEASE_SHA":"a"*40}
                opened=[];actual=base.create_journal
                def journal(*args):
                    persist,close=actual(*args);opened.append((persist,close));return persist,close
                def http(_http,method,url,*args):return SimpleNamespace(status_code=200,json=lambda:{"release_sha":"a"*40,"revision":"api"if url.startswith('http://api:')else"web"})
                owner=Owner();original=RuntimeError('synthetic constructor')
                def fail(*args,**kwargs):raise original
                with patch.object(base,'bounded_http',side_effect=http),patch.object(base,'create_journal',side_effect=journal),patch.object(base,'RegisteredOwner',side_effect=fail if failed=='owner'else lambda *_args:owner),patch.object(p,'checked_json',return_value={"control_secret":"e"*64}),patch.object(p,'Controls',side_effect=fail):
                    with self.assertRaises(RuntimeError) as result:p.from_environment(root,v['runId'],environment=env,verified_implementation_sha256="c"*64,verified_registration_bytes=b,base_module=base)
                self.assertIs(result.exception,original);self.assertEqual(len(opened),1)
                with self.assertRaises(AssertionError):opened[0][0]({"synthetic":"after-close"})
                if failed=='controls':self.assertTrue(owner.closed)

class PolicyAvailability(unittest.TestCase):
    def test_one_exact_get_fault_and_restore_never_reaches_owner_or_changes_other_routes(self):
        v = registration(); c = p.Controls(v, "a"*64, "b"*64, owner=Owner(), base=SimpleNamespace(), now=lambda:1000)
        c._execute("policyAvailabilityCheckpoint", "CX28-VERSION-04", {"phase":"unavailable"})
        self.assertEqual(c.before_native("GET", "/api/auth/native/compatibility", native=True, request_id="one"), {"fault":"offline"})
        for method, route in (("POST", "/api/auth/native/compatibility"), ("GET", "/api/auth/me"), ("GET", "/api/auth/native/compatibility/")):
            self.assertIsNone(c.before_native(method, route, native=True, request_id="two"))
        with self.assertRaises(AssertionError): c._execute("policyAvailabilityCheckpoint", "CX28-VERSION-04", {"phase":"unavailable"})
        c._execute("policyAvailabilityCheckpoint", "CX28-VERSION-04", {"phase":"restored"})
        self.assertIsNone(c.before_native("GET", "/api/auth/native/compatibility", native=True, request_id="three"))
        with self.assertRaises(AssertionError): c._execute("policyAvailabilityCheckpoint", "CX28-VERSION-04", {"phase":"restored"})
    def test_cleanup_restores_only_owned_compatibility_fault_and_keeps_first_failure(self):
        events=[]; c=p.Controls(registration(), "a"*64, "b"*64, owner=Owner(), base=SimpleNamespace(), persist=events.append, now=lambda:1000)
        c._execute("policyAvailabilityCheckpoint", "CX28-VERSION-04", {"phase":"unavailable"})
        with self.assertRaises(AssertionError): c._execute("policyAvailabilityCheckpoint", "CX28-CAM-01", {"phase":"restored"})
        c._execute("closeCase", "CX28-VERSION-04", {})
        self.assertFalse(c.policy_unavailable); self.assertEqual(events,[{"type":"cx_cleanup_exact_compatibility_fault","restored":True}])

class Reader(unittest.TestCase):
    def test_same_descriptor_private_bound_and_namespace(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve(); target = root / "private.json"; data = b'{"synthetic":true}'
            target.write_bytes(data); target.chmod(0o600)
            ref = {"path": str(target), "sha256": hashlib.sha256(data).hexdigest(), "uid": os.getuid()}
            self.assertEqual(p.checked_json(ref, root, private=True), {"synthetic": True})
            target.chmod(0o644)
            with self.assertRaises(AssertionError): p.checked_json(ref, root, private=True)
    def test_late_same_inode_parent_symlink_is_refused_and_fd_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve(); root = base / "owned"; root.mkdir(); target = root / "public.json"; target.write_text('{}')
            ref = {"path": str(target), "sha256": hashlib.sha256(b'{}').hexdigest()}; original = os.read; descriptors = []
            def raced(fd, size):
                descriptors.append(fd)
                if len(descriptors) == 1: root.rename(base / 'moved'); root.symlink_to(base / 'moved', target_is_directory=True)
                return original(fd, size)
            with patch.object(p.os, 'read', side_effect=raced):
                with self.assertRaises(AssertionError): p.checked_json(ref, root)
            with self.assertRaises(OSError): os.fstat(descriptors[0])

if __name__ == '__main__': unittest.main(verbosity=2)
