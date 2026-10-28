"""Default-off, exact native client extension read/oracle profile.

Normal HTTP uses the descriptor-compiled base owner, never direct database
writes, generated legal content, a native credential injection or Docker access.
Host-only camera/sensor/policy checkpoints are deliberately not RPC capabilities.
"""
import hashlib
import hmac
import json
import os
import stat
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlencode

PROFILE = "native-client-extensions-v1"
BASE_SHA256 = "a03af49be43afd3618688c64e0f7ac7938b8fa3e5e30b05bff00aeeb629ec4fc"
CASE_IDS = (
    "CX28-CAM-01", "CX28-CAM-02", "CX28-CAM-03", "CX28-CAM-04", "CX28-CAM-05", "CX28-CAM-06",
    "CX28-LOCK-01", "CX28-LOCK-02", "CX28-LOCK-03", "CX28-LOCK-04", "CX28-LOCK-05",
    "CX28-LINK-01", "CX28-LINK-02", "CX28-LINK-03", "CX28-LINK-04", "CX28-LINK-05",
    "CX28-READ-01", "CX28-READ-02", "CX28-READ-03", "CX28-READ-04",
    "CX28-VERSION-01", "CX28-VERSION-02", "CX28-VERSION-03", "CX28-VERSION-04",
)
CAPABILITIES = ("readAttachments", "readAttachmentBytes", "readNativeSessionIdentity", "readCompatibility", "readClientMetadata", "policyAvailabilityCheckpoint",
                "beginColdPromptObservation", "readPromptObservation", "readReadthrough", "readthroughAccessCheckpoint", "closeCase", "closeRun")
LIMITS = {"operations": 289, "caseOperations": 12, "http": 400, "nativeRecords": 500,
          "lifetime": 3600, "argumentBytes": 16384, "responseBytes": 1048576}
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
VERSION = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z")

def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
def sha(value): return hashlib.sha256(value).hexdigest()

def checked_json(reference, root, *, private=False):
    target = Path(reference["path"])
    assert target.is_absolute() and target.parent == root and target.resolve() == target
    fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    identity = lambda value: tuple(getattr(value, key) for key in fields)
    def namespace():
        assert target.resolve() == target
        result = []
        for ancestor in target.parents:
            item = ancestor.lstat(); assert stat.S_ISDIR(item.st_mode) and not stat.S_ISLNK(item.st_mode)
            result.append((str(ancestor), identity(item)))
        return result
    before_namespace = namespace(); named = target.lstat(); maximum = 16384 if private else 1048576
    assert stat.S_ISREG(named.st_mode) and named.st_nlink == 1 and 0 < named.st_size <= maximum
    if private:
        assert named.st_uid == reference["uid"] == os.getuid() and stat.S_IMODE(named.st_mode) in (0o400, 0o600)
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        assert identity(os.fstat(fd)) == identity(named)
        data = bytearray()
        while len(data) <= maximum:
            part = os.read(fd, min(65536, maximum + 1 - len(data)))
            if not part: break
            data.extend(part)
        assert len(data) <= maximum and len(data) == named.st_size
        assert identity(os.fstat(fd)) == identity(named) == identity(target.lstat())
        assert namespace() == before_namespace and sha(data) == reference["sha256"]
        value = json.loads(data.decode("utf-8", "strict")); assert isinstance(value, dict)
        return value
    finally: os.close(fd)

def validate_registration(v, *, source, run, now):
    assert v["kind"] == "registered-native-client-extension-controls" and v["profile"] == PROFILE
    assert type(v["schemaVersion"]) is int and v["schemaVersion"] == 1
    assert v["observed"] is True and v["readyForLive"] is True and v["preparedOnly"] is False
    assert v["environment"] == "docker-integration" and v["syntheticDataOnly"] is True
    assert v["noPaidMarker"] == "no-paid-providers" and v["directDatabaseWrites"] is False
    assert v["nativeMutationsForwardedByControls"] is False
    assert v["sourceSha"] == source and v["runId"] == run
    assert isinstance(v["registrationId"],str) and re.fullmatch(r"[a-f0-9]{16,64}",v["registrationId"]), "CX_JOURNAL_ID_REQUIRED"
    assert type(v["expiresAt"]) in (int, float) and 0 < v["expiresAt"] - now <= LIMITS["lifetime"]
    assert v["baseImplementationSha256"] == BASE_SHA256 and tuple(v["capabilities"]) == CAPABILITIES
    assert v["caseIds"] == list(CASE_IDS) and v["caseControlLimits"] == {key: 12 for key in CASE_IDS}
    assert v["platform"] in ("ios", "android") and VERSION.fullmatch(v["clientVersion"]) and len(v["clientVersion"]) <= 29
    assert set(v["actors"]) == {"owner", "member", "second-company"}
    ids = v["syntheticIds"]
    assert isinstance(ids, list) and 0 < len(ids) <= 128 and len(ids) == len(set(ids)) and all(UUID.fullmatch(x) for x in ids)
    for actor in v["actors"].values():
        assert all(actor[k] in ids for k in ("companyId", "membershipId", "userId"))
        assert set(actor["credentialEvidence"]) == {"path", "sha256", "uid"}
    assert v["actors"]["owner"]["companyId"] == v["actors"]["member"]["companyId"] == v["companyId"]
    assert v["actors"]["second-company"]["companyId"] != v["companyId"]
    assert len({actor["userId"] for actor in v["actors"].values()}) == 3
    assert v["byteSourceId"] in ids
    assert v["cameraMatterId"] in ids and v["readthroughMatterId"] in ids and v["revocableMatterId"] in ids
    expected = {"GET /api/auth/native/compatibility", "GET /api/auth/native/sessions",
                "GET /api/matters/" + v["cameraMatterId"] + "/workspace",
                "GET /api/matters/" + v["cameraMatterId"] + "/attachments/" + v["byteSourceId"] + "/download",
                "POST /api/matters/" + v["cameraMatterId"] + "/attachments"}
    assert len(v["navigableMatterIds"]) <= 8 and len(set(v["navigableMatterIds"])) == len(v["navigableMatterIds"])
    for matter in v["navigableMatterIds"]:
        assert matter in ids
        expected.update(("GET /api/matters/" + matter, "GET /api/matters/" + matter + "/workspace"))
    for matter in v["readthroughMatterIds"]:
        assert matter in ids
        expected.add("GET /api/matter-readthrough/" + matter + "/recommendations")
    for target in v["readthroughTargets"]:
        assert target["matterId"] in v["readthroughMatterIds"]
        assert target["kind"] in ("recommendation", "options", "decisions", "latestPack", "pack", "packItems")
        assert target["id"] in ids
        base = "/api/matter-readthrough/" + target["matterId"]
        if target["kind"] in ("recommendation", "options", "decisions"):
            suffix = "/recommendations/" + target["id"] + ("/" + target["kind"] if target["kind"] != "recommendation" else "")
        elif target["kind"] == "latestPack": suffix = "/hearings/" + target["id"] + "/pack"
        else: suffix = "/hearing-packs/" + target["id"] + ("/items" if target["kind"] == "packItems" else "")
        expected.add("GET " + base + suffix)
    assert set(v["exactRoutes"]) == expected and len(v["exactRoutes"]) == len(expected)
    # Revocation/restore is an independently acknowledged normal-API owner
    # checkpoint. This gateway never accepts caller-supplied mutation recipes.
    assert v["ownerRecipes"] == [] and v["ownerExactRoutes"] == []
    assert set(v["scannerConfigurationEvidence"]) == {"path", "sha256"}
    assert re.fullmatch(r"[a-f0-9]{64}", v["scannerConfigurationEvidence"]["sha256"])
    if v.get("priorNativeIdentity") is not None:
        assert set(v["priorNativeIdentity"]) == {"userId", "companyId", "membershipId", "sessionId"}
        assert all(UUID.fullmatch(x) for x in v["priorNativeIdentity"].values())
        assert all(v["priorNativeIdentity"][k] == v["actors"]["member"][k] for k in ("userId", "companyId", "membershipId"))
    return v

class Controls:
    def __init__(self, registration, registration_sha, authority, *, owner, base, persist=lambda row: None,
                 claim=lambda identity: None, close_journal=lambda: None, now=time.time):
        self.registration, self.registration_sha, self.authority = registration, registration_sha, authority
        self.owner, self.base, self.persist, self.claim, self.close_journal, self.now = owner, base, persist, claim, close_journal, now
        self.closed = False; self.lock = threading.RLock(); self.operations = set(); self.counts = {}
        self.records = []; self.metadata = {}; self.last_grant = registration.get("priorNativeIdentity"); self.upload = None; self.final_cleanup = False
        self.dynamic_routes = set()
        self.policy_unavailable = False; self.policy_unavailable_attempted = False; self.policy_restored_attempted = False
        self.wall = None; self.wall_uncertain = False; self.wall_attempted = False; self.restore_attempted = False

    def live(self): assert not self.closed and self.now() < self.registration["expiresAt"], "CX_CONTROL_CLOSED_OR_EXPIRED"
    def before_native(self, method, route, *, native, request_id):
        self.live()
        if self.policy_unavailable and method == "GET" and route == "/api/auth/native/compatibility":
            return {"fault": "offline"}
        return None
    @staticmethod
    def should_withhold(_intercept, _status): return False
    def validate_native_request(self, *args, **kwargs):
        with self.lock: return self._validate_native_request(*args, **kwargs)

    def _validate_native_request(self, method, route, *, native, body, query, authorization, cookie_present, client_version_headers=None, request_id=None):
        self.live()
        values = client_version_headers or []
        assert isinstance(values, list) and len(values) <= 1, "CX_DUPLICATE_CLIENT_METADATA"
        if values: assert len(values[0]) <= 29 and VERSION.fullmatch(values[0]), "CX_INVALID_CLIENT_METADATA"
        # Gateway request_id is attached by before/after; only the safe exact
        # version string is retained. Bodies, cookies and credentials are not.
        assert isinstance(request_id, str) and re.fullmatch(r"[a-f0-9]{16}", request_id)
        assert request_id not in self.metadata and len(self.metadata) < LIMITS["nativeRecords"]
        self.metadata[request_id] = values[0] if values else None

    def after_native(self, *args, **kwargs):
        with self.lock: return self._after_native(*args, **kwargs)

    def _after_native(self, method, route, *, native, request_id, sequence, body, query, status, data, intercept):
        self.live(); assert len(self.records) < LIMITS["nativeRecords"]
        version = self.metadata.pop(request_id, None)
        principal = None; upload = None
        record = {"method": method, "route": route, "status": status, "sequence": sequence,
                  "clientVersion": version, "transport": "multipart" if method == "POST" and route.endswith("/attachments") else "bytes" if route.endswith("/download") else "json"}
        if method == "POST" and route in ("/api/auth/native/token", "/api/auth/native/refresh") and status == 200:
            value = json.loads(data)
            principal = {"userId": value["user"]["id"], "companyId": value["company"]["id"], "membershipId": value["membership"]["id"], "sessionId": value["session_id"]}
            assert all(UUID.fullmatch(x) for x in principal.values())
            assert any(all(principal[key] == actor[field] for key, field in (("userId", "userId"), ("companyId", "companyId"), ("membershipId", "membershipId"))) for actor in self.registration["actors"].values())
        if method == "POST" and route == "/api/matters/" + self.registration["cameraMatterId"] + "/attachments" and status == 200:
            assert self.upload is None, "CX_ONE_CAMERA_UPLOAD_ONLY"
            value = json.loads(data); assert UUID.fullmatch(value["id"]) and value["matter_id"] == self.registration["cameraMatterId"]
            assert re.fullmatch(r"[a-f0-9]{64}", value["sha256_hex"]) and type(value["size_bytes"]) is int and 0 < value["size_bytes"] <= 900000
            upload = {"id": value["id"], "matter_id": value["matter_id"], "sha256_hex": value["sha256_hex"], "size_bytes": value["size_bytes"]}
        self.persist({"type": "cx_native_observation", **record, "grantIdentity": principal, "uploadIdentity": upload})
        self.records.append(record)
        if principal is not None: self.last_grant = principal
        if upload is not None:
            self.upload = upload
            self.dynamic_routes.add("GET /api/matters/" + upload["matter_id"] + "/attachments/" + upload["id"] + "/download")
        return False

    def handle(self, raw, *, marker, authority):
        assert marker == "no-paid-providers" and hmac.compare_digest(authority, self.authority)
        assert self.lock.acquire(blocking=False), "CX_SERIAL_CONTROL_REQUIRED"
        try:
            self.live(); assert isinstance(raw, bytes) and len(raw) <= LIMITS["argumentBytes"]
            q = json.loads(raw)
            assert set(q) == {"schemaVersion", "capability", "caseId", "operationId", "runId", "registrationSha256", "args"}
            assert q["schemaVersion"] == 1 and q["runId"] == self.registration["runId"] and q["registrationSha256"] == self.registration_sha
            case, cap, args = q["caseId"], q["capability"], q["args"]
            assert case in CASE_IDS and cap in CAPABILITIES and isinstance(args, dict)
            assert q["operationId"] not in self.operations and len(self.operations) < LIMITS["operations"]
            if cap != "closeRun":
                self.counts[case] = self.counts.get(case, 0) + 1; assert self.counts[case] <= LIMITS["caseOperations"]
            self.claim(q["operationId"]); self.operations.add(q["operationId"])
            value = self._execute(cap, case, args)
            result = {"observed": True, "capability": cap, "caseId": case, "operationId": q["operationId"], "sourceSha": self.registration["sourceSha"],
                      "runId": q["runId"], "noPaidMarker": marker, "directDatabaseWrites": False, "nativeMutationsForwardedByControls": False, "value": value}
            assert len(canonical(result)) <= LIMITS["responseBytes"]
            self.persist({"type": "cx_control_result", "operationId": q["operationId"], "caseId": case, "capability": cap, "resultSha256": sha(canonical(result))})
            if cap == "closeRun":
                self.authority = None
                self.closed = True
                self.close_journal()
            return result
        finally: self.lock.release()

    def _get(self, route, *, actor="member"):
        response = self.base.bounded_http(self.owner.client(actor), "GET", route)
        assert response.status_code == 200, "CX_CURRENT_NORMAL_API_READ_REQUIRED"
        return response

    def _execute(self, cap, case, args):
        if cap == "policyAvailabilityCheckpoint":
            assert case == "CX28-VERSION-04" and set(args) == {"phase"}
            phase = args["phase"]
            if phase == "unavailable":
                assert not self.policy_unavailable_attempted
                self.policy_unavailable_attempted = True; self.policy_unavailable = True
            else:
                assert phase == "restored" and self.policy_unavailable and not self.policy_restored_attempted
                self.policy_restored_attempted = True; self.policy_unavailable = False
            return {"observed": True, "phase": phase, "exactCompatibilityGetOnly": True, "upstreamForwarded": False}
        if cap == "closeCase":
            assert not args
            if case == "CX28-READ-02" and self.wall is not None: self._restore_wall()
            assert not self.wall_uncertain, "CX_WALL_OUTCOME_UNKNOWN_NO_REPLAY"
            if case == "CX28-VERSION-04" and self.policy_unavailable:
                self.persist({"type": "cx_cleanup_exact_compatibility_fault", "restored": True})
                self.policy_unavailable = False
            return self.owner.close_case(case)
        if cap == "closeRun":
            assert not args and not self.final_cleanup; self.final_cleanup = True
            assert self.wall is None and not self.wall_uncertain
            assert self.owner.restoration_complete()
            try: self.owner.close()
            except BaseException as error:
                self.closed = True; self.authority = None
                try: self.close_journal()
                except BaseException: error.add_note("CX_JOURNAL_CLEANUP_UNVERIFIED")
                raise
            return {"allOwnedControlsClosed": True, "authorityCleared": True, "journalClosed": True}
        if cap == "readAttachments":
            assert set(args) == {"matterId"} and args["matterId"] == self.registration["cameraMatterId"]
            return self._get("/api/matters/" + args["matterId"] + "/workspace").json()["attachments"]
        if cap == "readAttachmentBytes":
            assert self.upload is not None and args == {"matterId": self.upload["matter_id"], "id": self.upload["id"]}
            response = self._get("/api/matters/" + args["matterId"] + "/attachments/" + args["id"] + "/download")
            assert sha(response.content) == self.upload["sha256_hex"] and len(response.content) == self.upload["size_bytes"]
            return {"sha256": sha(response.content), "sizeBytes": len(response.content), "acceptedUnderScannerConfiguration": self.registration["scannerConfigurationEvidence"]}
        if cap == "readNativeSessionIdentity":
            assert args in ({}, {"requireActive": False}) and self.last_grant is not None
            if args: assert case == "CX28-VERSION-04"
            sessions = self._get("/api/auth/native/sessions").json()["sessions"]
            listed = any(item["id"] == self.last_grant["sessionId"] and item["revoked_at"] is None for item in sessions)
            if not args: assert listed
            return {"observed": True, **self.last_grant, **({"activeSessionListed": listed} if args else {})}
        if cap == "readCompatibility":
            assert not args
            return {"value": self._get("/api/auth/native/compatibility?" + urlencode({"platform": self.registration["platform"], "client_version": self.registration["clientVersion"]})).json()}
        if cap == "readClientMetadata":
            assert not args
            return {"actualBinaryVersion": self.registration["clientVersion"], "requests": [r for r in self.records if r["clientVersion"] is not None]}
        if cap == "beginColdPromptObservation":
            assert not args; return {"runId": self.registration["runId"], "sequence": len(self.records)}
        if cap == "readPromptObservation":
            assert set(args) == {"checkpoint"}; checkpoint = args["checkpoint"]
            assert checkpoint["runId"] == self.registration["runId"] and type(checkpoint["sequence"]) is int and 0 <= checkpoint["sequence"] <= len(self.records)
            rows = self.records[checkpoint["sequence"]:]
            return {"refreshOrPrivateProfileRequests": sum(r["route"] in ("/api/auth/native/refresh", "/api/auth/me") for r in rows),
                    "successfulRefresh": sum(r["route"] == "/api/auth/native/refresh" and r["status"] == 200 for r in rows),
                    "successfulProfile": sum(r["route"] == "/api/auth/me" and r["status"] == 200 for r in rows)}
        if cap == "readthroughAccessCheckpoint":
            assert case == "CX28-READ-02" and set(args) == {"phase"} and args["phase"] in ("revoke", "restore")
            if args["phase"] == "restore":
                self._restore_wall()
                return {"observed": True, "phase": "restore", "normalApiAcknowledged": True}
            assert not self.wall_attempted and not self.wall_uncertain and self.wall is None
            self.wall_attempted = True; self.wall_uncertain = True
            route = "/api/matters/" + self.registration["revocableMatterId"] + "/access/walls"
            response = self.base.bounded_http(self.owner.client("owner"), "POST", route,
                {"excluded_membership_id": self.registration["actors"]["member"]["membershipId"], "reason": "Synthetic native readthrough access boundary"})
            assert response.status_code == 200, "CX_WALL_ACK_UNKNOWN_NO_REPLAY"
            value = response.json(); assert UUID.fullmatch(value["id"])
            assert value["matter_id"] == self.registration["revocableMatterId"] and value["excluded_membership_id"] == self.registration["actors"]["member"]["membershipId"]
            self.persist({"type": "cx_owned_wall_ack", "id": value["id"], "matterId": value["matter_id"]})
            self.wall = value["id"]; self.wall_uncertain = False
            return {"observed": True, "phase": "revoke", "normalApiAcknowledged": True}
        assert cap == "readReadthrough" and args["matterId"] in self.registration["readthroughMatterIds"]
        kind, matter = args["kind"], args["matterId"]
        assert set(args) <= {"kind", "matterId", "id", "hearingId", "cursor"}
        base = "/api/matter-readthrough/" + matter
        if kind == "recommendations": route = base + "/recommendations"
        else:
            target_id = args.get("hearingId") if kind == "latestPack" else args.get("id")
            assert {"kind": kind, "matterId": matter, "id": target_id} in self.registration["readthroughTargets"]
            if kind in ("recommendation", "options", "decisions"):
                route = base + "/recommendations/" + target_id + ("/" + kind if kind != "recommendation" else "")
            elif kind == "latestPack": route = base + "/hearings/" + target_id + "/pack"
            else: route = base + "/hearing-packs/" + target_id + ("/items" if kind == "packItems" else "")
        if kind in ("recommendations", "options", "decisions", "packItems"):
            params = {"limit": 25}
            if args.get("cursor") is not None:
                assert isinstance(args["cursor"], str) and 0 < len(args["cursor"]) <= 4000; params["cursor"] = args["cursor"]
            route += "?" + urlencode(params)
        return self._get(route).json()

    def _restore_wall(self):
        assert self.wall is not None and not self.wall_uncertain and not self.restore_attempted
        self.restore_attempted = True; self.wall_uncertain = True
        route = "/api/matters/" + self.registration["revocableMatterId"] + "/access/walls/" + self.wall
        response = self.base.bounded_http(self.owner.client("owner"), "DELETE", route)
        assert response.status_code == 204, "CX_WALL_RESTORE_UNKNOWN_NO_REPLAY"
        self.persist({"type": "cx_owned_wall_restore_ack", "id": self.wall})
        self.wall = None; self.wall_uncertain = False

    def close(self):
        if not self.closed:
            self.closed = True
            try: self.owner.close()
            finally: self.authority = None; self.close_journal()

def from_environment(root, run_id, *, environment=None, verified_implementation_sha256=None, verified_registration_bytes=None, base_module=None, **_unused):
    env = environment or {}
    assert env.get("CASEOPS_ENV") == "local" and env.get("CASEOPS_MOBILE_V1_CONTROLS") == "1" and env.get("CASEOPS_MOBILE_V1_PROFILE") == PROFILE
    assert not any(env.get(k) for k in ("K_SERVICE", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert base_module is not None
    v = json.loads(verified_registration_bytes)
    assert sha(verified_registration_bytes) == env["CASEOPS_MOBILE_V1_REGISTRATION_SHA256"]
    validate_registration(v, source=env["CASEOPS_RELEASE_SHA"], run=run_id, now=time.time())
    assert v["implementationSha256"] == verified_implementation_sha256
    calls = {"count": 0}; original = base_module.bounded_http
    def charged(*args, **kwargs):
        calls["count"] += 1; assert calls["count"] <= LIMITS["http"], "CX_ALL_HTTP_BOUND"
        return original(*args, **kwargs)
    base_module.bounded_http = charged
    import httpx
    with httpx.Client(timeout=3, follow_redirects=False, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}) as http:
        for origin, route, key in (("http://api:8000", "/api/build", "backendRevision"), ("http://web:3000", "/api/release-identity", "webRevision")):
            r = charged(http, "GET", origin + route)
            assert r.status_code == 200 and r.json()["release_sha"] == v["sourceSha"] and r.json()["revision"] == v[key]
    base_module.checked_json = checked_json
    if v.get("priorNativeIdentity") is not None:
        prior = checked_json(v["priorNativeIdentityEvidence"], root)
        assert prior["kind"] == "actual-native-session-identity" and prior["observed"] is True
        assert prior["sourceSha"] == v["sourceSha"] and prior["binaryHash"] == v["binaryHash"]
        assert prior["identity"] == v["priorNativeIdentity"] and prior["runId"] != run_id
    authority = base_module.checked_json(v["authorityEvidence"], root, private=True)["control_secret"]
    assert re.fullmatch(r"[a-f0-9]{64}", authority)
    persist, close_journal = base_module.create_journal(root, v["registrationId"])
    owner = None
    try:
        owner = base_module.RegisteredOwner(v, root)
    except BaseException as error:
        try: close_journal()
        except BaseException: error.add_note("CX_JOURNAL_CLEANUP_UNVERIFIED_DURING_OWNER_SETUP")
        raise
    def claim(identity):
        target = root / ("cx-operation-" + sha(identity.encode()) + ".json")
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            pending = memoryview(canonical({"operationIdSha256": sha(identity.encode()), "noReplay": True}))
            while pending:
                count = os.write(fd, pending); assert count > 0; pending = pending[count:]
            os.fsync(fd)
        finally: os.close(fd)
    try:
        return Controls(v, env["CASEOPS_MOBILE_V1_REGISTRATION_SHA256"], authority, owner=owner, base=base_module,
                        persist=persist, claim=claim, close_journal=close_journal)
    except BaseException as error:
        try: owner.close()
        except BaseException: error.add_note("CX_OWNER_CLEANUP_UNVERIFIED")
        try: close_journal()
        except BaseException: error.add_note("CX_JOURNAL_CLEANUP_UNVERIFIED")
        raise
