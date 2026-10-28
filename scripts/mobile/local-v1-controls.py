"""Disabled-by-default, exact synthetic-run gateway controls. Never product routes.

The owner adapter performs only registered normal HTTP operations. A separately
attested observer may issue finite typed read-only SQL; unavailable means refusal.
No native mutation is constructed, retried or sent by this manager.
"""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

PATH = "/__caseops_e2e/v1-control"
MARKER = "no-paid-providers"
CAPABILITIES = (
    "readSource", "readWorkspace", "readCurrentActor", "readNotificationState", "readObligations", "readCounsel", "readInbox", "readNativeRequest",
    "applyIpPolicy", "armSourceFault", "armWorkBarrier", "releaseWorkBarrier",
    "changeMatterLifecycle", "changeChild", "changeMatterAccess", "armUnknownResponse",
    "readControlReceipt", "closeCaseControls", "closeRunControls",
)
LIMITS = {"operations": 264, "nativeRecords": 500, "controlsPerCase": 24,
          "argumentBytes": 16384, "responseBytes": 1048576, "holdSeconds": 20,
          "armSeconds": 60, "lifetimeSeconds": 1800, "bodyBytes": 65536, "ownerRequests": 6,
          "finalCleanupOperations": 1, "journalBytes": 8388608}
WORK_FIELDS = frozenset(("title", "description", "due_on", "status", "priority", "hearing_on", "forum_name",
    "judge_name", "purpose", "outcome_note", "time_status", "hearing_time", "session_label", "timezone",
    "create_follow_up", "reminder_channels", "reminder_recipient_membership_ids", "notification_critical",
    "expected_lifecycle_version", "expected_updated_at", "expected_record_version"))
UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
NATIVE_CREATIONS = (("WORK-01", "task"), ("WORK-03", "hearing"),
                    ("WORK-04", "follow-up-task"), ("WORK-06", "unknown-save-task"))
CASE_LIMITS = {
    "SOURCE-01": 14, "SOURCE-02": 14, "SOURCE-03": 14, "SOURCE-04": 20, "SOURCE-05": 14, "SOURCE-06": 14, "SOURCE-07": 14,
    "WORK-01": 14, "WORK-02": 14, "WORK-03": 14, "WORK-04": 14, "WORK-05": 20, "WORK-06": 14, "WORK-07": 14, "WORK-08": 18,
    "COUNSEL-01": 14, "INBOX-01": 14,
}
assert sum(CASE_LIMITS.values()) + 1 <= LIMITS["operations"]
CASE = re.compile(r"(?:SOURCE-0[1-7]|WORK-0[1-8]|COUNSEL-01|INBOX-01)\Z")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def checked_json(reference, root, *, private=False):
    """Use retained bounded bytes from one opened, finally-closed descriptor."""
    if private:
        private_reference(reference)
    target = Path(reference["path"])
    assert target.is_absolute() and target.parent == root and target.name == str(target.relative_to(root))
    maximum = 16384 if private else 1048576
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before, named = os.fstat(descriptor), target.lstat()
        fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        identity = lambda value: tuple(getattr(value, key) for key in fields)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= maximum
        assert not stat.S_ISLNK(named.st_mode) and identity(before) == identity(named)
        if private:
            assert before.st_uid == reference["uid"] and stat.S_IMODE(before.st_mode) in (0o400, 0o600)
        parts, size = [], 0
        while size <= maximum:
            part = os.read(descriptor, min(65536, maximum + 1 - size))
            if not part:
                break
            parts.append(part)
            size += len(part)
        data = b"".join(parts)
        assert len(data) <= maximum and len(data) == before.st_size
        assert identity(before) == identity(os.fstat(descriptor)) == identity(target.lstat())
        assert sha(data) == reference["sha256"]
        try:
            value = json.loads(data.decode("utf-8", "strict"))
        except (ValueError, UnicodeError):
            raise ValueError("V1_CONTROL_JSON_REQUIRED") from None
        assert isinstance(value, dict)
        return value
    finally:
        os.close(descriptor)


def private_reference(reference):
    """The producer retains the owner from the actual verified descriptor."""
    assert isinstance(reference, dict) and set(reference) == {"path", "sha256", "uid"}
    assert isinstance(reference["path"], str) and Path(reference["path"]).is_absolute()
    assert isinstance(reference["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", reference["sha256"])
    assert type(reference["uid"]) is int and reference["uid"] >= 0
    return reference


def create_journal(root, identity):
    assert re.fullmatch(r"[a-f0-9]{16,64}", identity)
    target = root / f"v1-control-events-{identity}.jsonl"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        expected = os.fstat(descriptor)
    except BaseException:
        os.close(descriptor)
        raise
    count, closed = 0, False
    def metadata(value):
        return tuple(getattr(value, key) for key in ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))
    def persist(record):
        nonlocal expected, count
        assert not closed and count < 2 * (LIMITS["operations"] + LIMITS["finalCleanupOperations"]) + LIMITS["nativeRecords"]
        assert metadata(expected) == metadata(os.fstat(descriptor)) == metadata(target.lstat())
        data = canonical(record) + b"\n"
        assert len(data) <= LIMITS["responseBytes"]
        assert expected.st_size + len(data) <= LIMITS["journalBytes"], "V1_CONTROL_JOURNAL_BYTE_BOUND"
        pending = memoryview(data)
        while pending:
            written = os.write(descriptor, pending)
            assert written > 0
            pending = pending[written:]
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        assert final.st_size == expected.st_size + len(data) and metadata(final) == metadata(target.lstat())
        expected, count = final, count + 1
    def close():
        nonlocal closed
        if not closed:
            closed = True
            os.close(descriptor)
    return persist, close


def bounded_http(http, method, route, body=None):
    """One normal request, finite read time and retained bytes; no redirect/retry."""
    started, chunks, size = time.monotonic(), [], 0
    with http.stream(method, route, json=body, timeout=4,
                     headers={"Accept-Encoding": "identity", "X-CaseOps-Automated-Test": MARKER}) as response:
        assert response.headers.get("content-encoding", "identity") == "identity"
        for chunk in response.iter_raw():
            assert time.monotonic() - started < 4, "V1_OWNER_RESPONSE_DEADLINE"
            size += len(chunk)
            assert size <= LIMITS["responseBytes"], "V1_OWNER_RESPONSE_BOUND"
            chunks.append(chunk)
        data, status = b"".join(chunks), response.status_code
    try:
        value = json.loads(data.decode("utf-8", "strict")) if data else None
    except (ValueError, UnicodeError):
        raise ValueError("V1_OWNER_RESPONSE_JSON_REQUIRED") from None
    return SimpleNamespace(status_code=status, content=data, json=lambda: value)


def validate_registration(value, *, source, run, now):
    assert type(value["schemaVersion"]) is int and value["schemaVersion"] == 1 and value["kind"] == "registered-v1-qa-controls"
    assert value["readyForLive"] is True and value["preparedOnly"] is False and value["observed"] is True
    assert value["environment"] == "docker-integration" and value["syntheticDataOnly"] is True
    assert value["noPaidMarker"] == MARKER and value["directDatabaseWrites"] is False
    assert value["nativeMutationsForwardedByControls"] is False
    assert value["sourceSha"] == source and value["runId"] == run
    assert 0 < value["expiresAt"] - now <= LIMITS["lifetimeSeconds"]
    assert tuple(value["capabilities"]) == CAPABILITIES
    assert value["caseControlLimits"] == CASE_LIMITS
    assert re.fullmatch(r"[a-f0-9]{16,64}", value["registrationId"])
    assert UUID.fullmatch(value["companyId"])
    ids = value["syntheticIds"]
    assert 1 <= len(ids) <= 96 - len(NATIVE_CREATIONS), "V1_FOUR_NATIVE_IDENTITIES_MUST_BE_RESERVED"
    assert len(ids) == len(set(ids)) and all(UUID.fullmatch(item) for item in ids)
    routes = value["exactRoutes"]
    assert 1 <= len(routes) <= 160 and len(routes) == len(set(routes))
    for route in routes:
        assert re.fullmatch(r"(?:GET|POST|PATCH|DELETE) /api/[a-z0-9_/-]{1,300}", route)
        assert not any(character in route for character in "*?{}")
        for item in re.findall(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", route):
            assert item in ids
    assert isinstance(value["ownerRecipes"], list) and len(value["ownerRecipes"]) <= 48
    actors = value["actors"]
    assert set(actors) == {"owner", "member", "second-company"}
    for actor in actors.values():
        assert UUID.fullmatch(actor["companyId"]) and UUID.fullmatch(actor["membershipId"])
        private_reference(actor["credentialEvidence"])
    private_reference(value["authorityEvidence"])
    assert actors["owner"]["companyId"] == actors["member"]["companyId"] == value["companyId"]
    assert actors["second-company"]["companyId"] != value["companyId"]
    assert len({item["membershipId"] for item in actors.values()}) == 3
    notes = value["inboxNotifications"]
    assert isinstance(notes, list) and len(notes) == 1
    for note in notes:
        assert note["id"] in ids and note["recipientMembershipId"] == actors["member"]["membershipId"]
        assert note["companyId"] == value["companyId"] and note["target"]["kind"] == "matter" and note["target"]["id"] in ids
        assert set(note["deliveryEvidence"]) == {"path", "sha256"} and re.fullmatch(r"[a-f0-9]{64}", note["deliveryEvidence"]["sha256"])
    for route in value["ownerExactRoutes"]:
        assert re.fullmatch(r"(?:GET|POST|PUT|PATCH|DELETE) /api/[a-z0-9_/-]{1,300}", route)
        identifiers = re.findall(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", route)
        assert all(item in ids for item in identifiers)
        assert identifiers or route in ("GET /api/ip/readiness", "GET /api/ip/workspace/configuration", "PUT /api/ip/workspace/configuration")
        assert "/api/recipient-inbox" not in route, "INBOX_STATUS_WRITES_BELONG_TO_NATIVE_ACTOR_ONLY"
    return value


class V1Controls:
    def __init__(self, registration, registration_sha, authority, *, owner, observer=None,
                 now=time.time, persist=lambda _event: None, claim=None, close_journal=lambda: None):
        self.registration, self.registration_sha = registration, registration_sha
        self.authority, self.owner, self.observer = authority, owner, observer
        self.now, self.persist, self.claim = now, persist, claim
        self.close_journal = close_journal
        self.lock = threading.RLock()
        self.dispatch_lock = threading.Lock()
        self.operations, self.counts, self.arms, self.records = set(), {}, {}, []
        self.policy_receipts = {}
        self.sequence = 0
        self.known_ids = set(registration["syntheticIds"])
        self.closed = False

    def live(self):
        assert not self.closed, "V1_CONTROLS_CLOSED"
        assert self.now() < self.registration["expiresAt"], "V1_CONTROL_EXPIRED"

    def reply(self, request, **facts):
        return {"observed": True, "sourceSha": self.registration["sourceSha"],
                "runId": self.registration["runId"], "operationId": request["operationId"],
                "caseId": request["caseId"], "capability": request["capability"],
                "noPaidMarker": MARKER, "directDatabaseWrites": False,
                "nativeMutationsForwardedByControls": False, **facts}

    def handle(self, raw, *, marker, authority):
        assert marker == MARKER and isinstance(authority, str) and hmac.compare_digest(authority, self.authority)
        acquired = self.dispatch_lock.acquire(blocking=False)
        assert acquired, "V1_SERIAL_CONTROL_REQUIRED"
        try:
            return self._handle(raw, marker=marker, authority=authority)
        finally:
            self.dispatch_lock.release()

    def _handle(self, raw, *, marker, authority):
        assert marker == MARKER and isinstance(authority, str) and hmac.compare_digest(authority, self.authority)
        assert isinstance(raw, bytes) and len(raw) <= LIMITS["argumentBytes"]
        try:
            request = json.loads(raw.decode("utf-8", "strict"))
        except (ValueError, UnicodeError):
            raise ValueError("V1_CONTROL_JSON_REQUIRED") from None
        assert set(request) == {"schemaVersion", "capability", "caseId", "operationId", "runId", "registrationSha256", "args"}
        capability, case, args = request["capability"], request["caseId"], request["args"]
        assert type(request["schemaVersion"]) is int and request["schemaVersion"] == 1 and capability in CAPABILITIES and CASE.fullmatch(case)
        assert request["runId"] == self.registration["runId"] and request["registrationSha256"] == self.registration_sha
        assert isinstance(args, dict) and not re.search(r'"(?:password|secret|token|authorization|cookie)"\s*:', json.dumps(args), re.I)
        assert re.fullmatch(re.escape(request["runId"] + ":" + case + ":") + r"[1-9][0-9]{0,3}", request["operationId"])
        with self.lock:
            self.live()
            assert request["operationId"] not in self.operations
            if capability != "closeRunControls":
                assert len(self.operations) < LIMITS["operations"]
                assert self.counts.get(case, 0) < min(LIMITS["controlsPerCase"], CASE_LIMITS[case])
            else:
                assert case == "INBOX-01" and len(self.operations) <= LIMITS["operations"]
            if self.claim:
                self.claim(request["operationId"])
            self.operations.add(request["operationId"])
            self.counts[case] = self.counts.get(case, 0) + 1
        self.persist({"type": "v1_control_started", "operationId": request["operationId"], "caseId": case, "capability": capability})
        if capability == "readNativeRequest":
            assert type(args["afterSequence"]) is int and args["afterSequence"] >= 0
            self.route(args["method"], args["route"])
            with self.lock:
                facts = {"requests": [dict(row) for row in self.records if row["sequence"] > args["afterSequence"] and row["method"] == args["method"] and row["route"] == args["route"]]}
        elif capability in ("armWorkBarrier", "armUnknownResponse", "armSourceFault"):
            facts = self.arm(case, capability, args)
        elif capability in ("readControlReceipt", "releaseWorkBarrier"):
            with self.lock:
                arm = self.arms.get(args["id"], self.policy_receipts.get(args["id"]))
                assert arm is not None, "EXACT_OWNED_V1_RECEIPT_REQUIRED"
                assert arm["caseId"] == case
                if capability == "releaseWorkBarrier":
                    assert arm["kind"] == "armWorkBarrier" and arm["reached"] and not arm["released"]
                    arm["released"] = True
                    arm["event"].set()
                facts = self.public_arm(arm)
        elif capability == "closeCaseControls":
            with self.lock:
                for arm in self.arms.values():
                    if arm["caseId"] == case:
                        arm["closed"] = True
                        arm["event"].set()
                for receipt in self.policy_receipts.values():
                    if receipt["caseId"] == case:
                        receipt["closed"] = True
            facts = self.owner.close_case(case)
            assert facts["allOwnedControlsClosed"] is True
        elif capability == "readNotificationState":
            assert self.observer is not None, "V1_READONLY_OBSERVER_UNAVAILABLE"
            assert args["hearingId"] in self.known_ids
            facts = self.observer(args["hearingId"])
        elif capability == "closeRunControls":
            # This final cleanup never retries an uncertain policy operation.
            # Unrestored policy is reported, while authority/resources close.
            restored = self.owner.restoration_complete()
            facts = {"allOwnedControlsClosed": restored, "normalApiPolicyRestorationVerified": restored,
                     "authorityCleared": True, "journalClosed": True}
        else:
            # The adapter accepts only pre-registered normal-API recipes or exact
            # current source/workspace reads. It cannot enqueue a native command.
            facts = self.owner(capability, case, args)
            if capability == "applyIpPolicy" and "nativeReadRoute" in facts:
                facts = dict(facts)
                route, statuses = facts.pop("nativeReadRoute"), facts.pop("nativeReadStatuses")
                self.route("GET", route)
                assert isinstance(statuses, list) and statuses and all(type(item) is int and 200 <= item <= 599 for item in statuses)
                assert re.fullmatch(r"[a-f0-9-]{16,64}", facts["id"])
                with self.lock:
                    assert facts["id"] not in self.policy_receipts and facts["id"] not in self.arms
                    self.policy_receipts[facts["id"]] = {"id": facts["id"], "caseId": case, "route": route, "statuses": statuses,
                        "consumed": False, "nativeMutationCount": 0, "closed": False}
        result = self.reply(request, **facts)
        assert len(canonical(result)) <= LIMITS["responseBytes"]
        self.persist({"type": "v1_control_completed", "operationId": request["operationId"], "caseId": case, "capability": capability})
        if capability == "closeRunControls":
            self.close()
        return result

    def route(self, method, route):
        assert f"{method} {route}" in self.registration["exactRoutes"], "UNREGISTERED_V1_ROUTE"

    def arm(self, case, kind, args):
        method, route = args.get("method", "GET"), args["route"]
        self.route(method, route)
        assert type(args.get("maxUses", 1)) is int and args.get("maxUses", 1) == 1
        if kind == "armWorkBarrier":
            assert method in ("POST", "PATCH") and args["point"] == "before-upstream-mutation"
        elif kind == "armUnknownResponse":
            assert method in ("POST", "PATCH") and args["mode"] == "drop-after-successful-upstream-ack"
        else:
            assert method == "GET" and args["mode"] in ("missing", "offline", "malformed")
        with self.lock:
            assert not any(arm["caseId"] == case and arm["method"] == method and arm["route"] == route and not arm["closed"] for arm in self.arms.values())
            identity = sha(f"{case}:{kind}:{len(self.arms)}".encode())[:32]
            arm = {"id": identity, "caseId": case, "kind": kind, "method": method, "route": route,
                   "mode": args.get("mode"), "event": threading.Event(), "reached": False,
                   "released": False, "consumed": False, "closed": False, "requestsForwarded": 0,
                   "nativeMutationCount": 0, "nativeMutationCommitted": False,
                   "expiresAt": min(self.registration["expiresAt"], self.now() + LIMITS["armSeconds"])}
            self.arms[identity] = arm
            return self.public_arm(arm)

    @staticmethod
    def public_arm(arm):
        return {key: value for key, value in arm.items() if key not in ("event", "expiresAt", "method", "route", "kind", "mode", "caseId", "statuses")}

    def before_native(self, method, route, *, native, request_id):
        if self.closed or not native or f"{method} {route}" not in self.registration["exactRoutes"]:
            return None
        with self.lock:
            self.live()
            matches = [arm for arm in self.arms.values() if arm["method"] == method and arm["route"] == route and not arm["closed"]]
            assert len(matches) <= 1, "AMBIGUOUS_V1_INTERCEPT"
            if not matches:
                return None
            arm = matches[0]
            assert not arm["consumed"] and self.now() < arm["expiresAt"], "V1_NATIVE_REQUEST_REPLAY_REFUSED"
            arm["consumed"] = True
            arm["reached"] = True
            arm["requestId"] = request_id
        if arm["kind"] == "armWorkBarrier":
            hold = min(LIMITS["holdSeconds"], self.registration["expiresAt"] - self.now())
            released = arm["event"].wait(max(0, hold))
            assert released, "V1_BARRIER_DEADLINE"
            assert arm["released"] and not arm["closed"], "V1_BARRIER_NOT_RELEASED"
        if arm["kind"] == "armSourceFault":
            return {"arm": arm, "fault": arm["mode"]}
        with self.lock:
            arm["requestsForwarded"] += 1
        return {"arm": arm}

    def after_native(self, method, route, *, native, request_id, sequence, body, query, status, data, intercept):
        if self.closed or not native or f"{method} {route}" not in self.registration["exactRoutes"]:
            return False
        assert len(body) <= LIMITS["bodyBytes"]
        row = {"sequence": sequence, "method": method, "route": route, "status": status, "requestId": request_id}
        inbox = method == "PATCH" and re.fullmatch(r"/api/recipient-inbox/[a-f0-9-]{36}", route)
        work = re.fullmatch(r"/api/matters/[a-f0-9-]{36}/(?:tasks|hearings)(?:/[a-f0-9-]{36})?", route)
        if method in ("POST", "PATCH"):
            value = json.loads(body)
            assert isinstance(value, dict) and not any(re.search(r"password|token|secret|authorization|cookie", key, re.I) for key in value)
            if inbox:
                assert set(value) == {"status", "expected_status"}, "V1_REVIEWED_INBOX_DTO_KEYS_REQUIRED"
                assert all(item in ("unread", "read", "dismissed") for item in value.values())
                matches = [item for item in self.registration["inboxNotifications"] if item["id"] == route.rsplit("/", 1)[1]]
                assert len(matches) == 1 and matches[0]["recipientMembershipId"] == self.registration["actors"]["member"]["membershipId"]
            else:
                assert work and set(value) <= WORK_FIELDS, "V1_REVIEWED_WORK_DTO_KEYS_REQUIRED"
            row["bodyObservation"] = {"keys": sorted(value), "canonicalSha256": sha(canonical(value))}
        if method == "GET" and route == "/api/contracts/":
            cursor = parse_qs(query, strict_parsing=True).get("cursor", [])
            assert len(cursor) <= 1
            row["queryObservation"] = {"cursorSha256": sha(cursor[0].encode()) if cursor else None}
        if method in ("POST", "PATCH") and status == 200:
            value = json.loads(data)
            assert UUID.fullmatch(value["id"])
            if inbox:
                expected = matches[0]
                assert value["id"] == expected["id"] and value["target"] == expected["target"]
                assert value["status"] == json.loads(body)["status"]
                row["responseObservation"] = {"id": value["id"], "status": value["status"], "target": value["target"]}
            else:
                assert UUID.fullmatch(value["matter_id"]) and value["matter_id"] in self.registration["syntheticIds"]
                version = value.get("record_version", value.get("updated_at"))
                row["responseObservation"] = {"id": value["id"], "matter_id": value["matter_id"], "version": version}
            with self.lock:
                if value["id"] not in self.known_ids:
                    assert len(self.known_ids) < 96
                    self.known_ids.add(value["id"])
        arm = intercept and intercept.get("arm")
        withheld = False
        if arm:
            with self.lock:
                arm["upstreamStatus"] = status
                arm["nativeMutationCommitted"] = method in ("POST", "PATCH") and status == 200
                arm["nativeMutationCount"] = int(arm["nativeMutationCommitted"])
                if arm["kind"] == "armUnknownResponse":
                    assert status == 200 and row.get("responseObservation"), "V1_SUCCESSFUL_ACK_REQUIRED_BEFORE_DROP"
                    arm["acknowledgedId"] = row["responseObservation"]["id"]
                    arm["clientResponseWithheld"] = True
                    withheld = True
        with self.lock:
            assert len(self.records) < LIMITS["nativeRecords"], "V1_NATIVE_EVIDENCE_BOUND"
            for receipt in self.policy_receipts.values():
                if not receipt["closed"]:
                    if method == "GET" and route == receipt["route"] and status in receipt["statuses"]:
                        receipt["consumed"] = True
                    elif method in ("POST", "PATCH", "DELETE") and not route.startswith("/api/auth/"):
                        receipt["nativeMutationCount"] += 1
            self.records.append(row)
        self.persist({"type": "v1_native_request_observed", **row})
        return withheld

    @staticmethod
    def should_withhold(intercept, status):
        return bool(intercept and intercept["arm"]["kind"] == "armUnknownResponse" and status == 200)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for arm in self.arms.values():
                arm["closed"] = True
                arm["event"].set()
        try:
            self.owner.close()
        finally:
            self.authority = ""
            self.close_journal()


class RegisteredOwner:
    """Normal HTTP only. The registration supplies reviewed exact policy recipes.

    Authentication uses each synthetic actor's own credentials through the real
    login API. It never mints a token or changes a membership in the database.
    """
    def __init__(self, registration, root, *, factory=None):
        self.registration, self.root = registration, root
        self.clients = {}
        self.failed_actors, self.attempted_recipes = set(), set()
        self.claim = None
        self.pending_cleanup = {}
        if factory is None:
            import httpx
            factory = lambda: httpx.Client(base_url="http://api:8000", timeout=4, follow_redirects=False,
                                           headers={"X-CaseOps-Automated-Test": MARKER})
        self.factory = factory

    def client(self, actor):
        assert actor in ("owner", "member", "second-company")
        assert actor not in self.failed_actors, "V1_OWNER_AUTHENTICATION_NOT_REPLAYABLE"
        if actor not in self.clients:
            binding = self.registration["actors"][actor]
            credentials = checked_json(binding["credentialEvidence"], self.root, private=True)
            http = self.factory()
            try:
                response = bounded_http(http, "POST", "/api/auth/login", {key: credentials[key] for key in ("email", "password", "company_slug")})
                assert response.status_code == 200, "V1_OWNER_NORMAL_LOGIN_REQUIRED"
                value = response.json()
                assert value["company"]["id"] == binding["companyId"] and value["membership"]["id"] == binding["membershipId"]
                expected_role = {"owner": "owner", "member": "member", "second-company": "viewer"}[actor]
                assert value["membership"]["role"] == expected_role
                assert ("matters:write" in value["capabilities"]) is (actor != "second-company")
                http.cookies.clear()
                http.headers["Authorization"] = "Bearer " + value["access_token"]
                if credentials.get("totp_secret"):
                    import pyotp
                    factor = pyotp.TOTP(credentials["totp_secret"]).now()
                    stepped = bounded_http(http, "POST", "/api/auth/mfa/step-up", {"code": factor, "purpose": "step_up", "method": "totp"})
                    assert stepped.status_code == 200, "V1_OWNER_NORMAL_MFA_REQUIRED"
                self.clients[actor] = http
            except Exception:
                self.failed_actors.add(actor)
                http.close()
                raise RuntimeError("V1_OWNER_AUTHENTICATION_INCOMPLETE_NO_RETRY") from None
            finally:
                credentials.clear()
        return self.clients[actor]

    def __call__(self, capability, case, args):
        if capability in ("readObligations", "readCounsel", "readInbox"):
            actor = args.get("actor", "member")
            if capability == "readObligations":
                identity = args["contractId"]; assert identity in self.registration["syntheticIds"]
                params = {"limit": 10}
                if args.get("after") is not None:
                    assert UUID.fullmatch(args["after"]) and args["after"] in self.registration["syntheticIds"]
                    params["after"] = args["after"]
                route = f"/api/contracts/{identity}/obligations?" + urlencode(params)
            elif capability == "readCounsel":
                identity = args["matterId"]; assert identity in self.registration["syntheticIds"]
                params = {"assignment_limit": 10, "spend_limit": 25}
                for key, public in (("assignmentAfter", "assignment_after"), ("spendAfter", "spend_after")):
                    if args.get(key) is not None:
                        assert UUID.fullmatch(args[key]) and args[key] in self.registration["syntheticIds"]
                        params[public] = args[key]
                route = f"/api/outside-counsel/matters/{identity}/context?" + urlencode(params)
            else:
                assert args["view"] in ("active", "dismissed")
                params = {"view": args["view"], "limit": 25}
                if args.get("cursor") is not None:
                    assert isinstance(args["cursor"], str) and 0 < len(args["cursor"]) <= 4000
                    params["cursor"] = args["cursor"]
                route = "/api/recipient-inbox?" + urlencode(params)
            response = bounded_http(self.client(actor), "GET", route); assert response.status_code == 200
            value = response.json()
            if capability == "readObligations":
                assert value["company_id"] == self.registration["actors"][actor]["companyId"] and value["contract_id"] == identity
            elif capability == "readCounsel":
                assert value["matter_id"] == identity
                assert all(item["company_id"] == self.registration["actors"][actor]["companyId"] for item in value["assignments"] + value["spend_records"])
            else:
                assert value["scope"] == "delivered_hearing_and_ip_renewal"
            return {"status": 200, "value": value}
        if capability == "readCurrentActor":
            actor = args.get("actor", "member")
            response = bounded_http(self.client(actor), "GET", "/api/auth/me")
            assert response.status_code == 200
            value, expected = response.json(), self.registration["actors"][actor]
            assert value["company"]["id"] == expected["companyId"] and value["membership"]["id"] == expected["membershipId"]
            assert value["membership"]["is_active"] is True and value["user"]["is_active"] is True
            assert isinstance(value["capabilities"], list) and len(value["capabilities"]) <= 200 and all(isinstance(item, str) for item in value["capabilities"])
            return {"value": {"companyId": value["company"]["id"], "membershipId": value["membership"]["id"],
                    "role": value["membership"]["role"], "capabilities": sorted(value["capabilities"])}}
        if capability == "readSource":
            assert args["id"] in self.registration["syntheticIds"]
            assert args["kind"] in ("contract", "ip_docket")
            route = f"/api/contracts/{args['id']}" if args["kind"] == "contract" else f"/api/ip/dockets/{args['id']}/summary"
            response = bounded_http(self.client(args.get("actor", "member")), "GET", route)
            assert response.status_code in (200, 403, 404)
            return {"status": response.status_code, **({"value": response.json()} if response.status_code == 200 else {})}
        if capability == "readWorkspace":
            assert args["matterId"] in self.registration["syntheticIds"]
            actor = args.get("actor", "member")
            response = bounded_http(self.client(actor), "GET", f"/api/matters/{args['matterId']}/workspace")
            assert response.status_code in (200, 403, 404)
            if response.status_code != 200:
                return {"status": response.status_code}
            value = response.json()
            assert value["matter"]["id"] == args["matterId"] and value["matter"]["company_id"] == self.registration["actors"][actor]["companyId"]
            return {"status": 200, "value": value}
        recipes = [item for item in self.registration["ownerRecipes"] if item["capability"] == capability
                   and item["caseId"] == case and item["argumentsSha256"] == sha(canonical(args))]
        assert len(recipes) == 1, "EXACT_REGISTERED_OWNER_RECIPE_REQUIRED"
        return self.run_recipe(recipes[0], case)

    def run_recipe(self, recipe, case):
        capability = recipe["capability"]
        identity = f"owner:{case}:{capability}:{recipe['argumentsSha256']}"
        assert identity not in self.attempted_recipes, "V1_OWNER_RECIPE_REPLAY_REFUSED"
        if self.claim:
            self.claim(identity)
        self.attempted_recipes.add(identity)
        assert 0 < len(recipe["requests"]) <= LIMITS["ownerRequests"]
        if recipe.get("cleanupRecipeId"):
            self.pending_cleanup.setdefault(case, set()).add(recipe["cleanupRecipeId"])
        responses = []
        for item in recipe["requests"]:
            method, route = item["method"], item["route"]
            assert f"{method} {route}" in self.registration["ownerExactRoutes"]
            assert re.fullmatch(r"(?:GET|POST|PUT|PATCH|DELETE)", method) and route.startswith("/api/") and not any(x in route for x in "?*{}")
            # A body is a reviewed immutable recipe, optionally filled by an
            # earlier acknowledged response. No submitted path or code is run.
            body = resolve_recipe(item.get("body"), responses)
            response = bounded_http(self.client("owner"), method, route, body)
            assert response.status_code in item["expectedStatuses"], "V1_OWNER_API_OUTCOME_UNVERIFIED_NO_REPLAY"
            responses.append(response.json() if response.content else None)
        self.pending_cleanup.setdefault(case, set()).discard(recipe["id"])
        return resolve_recipe(recipe["result"], responses)

    def close_case(self, case):
        for identity in list(self.pending_cleanup.get(case, ())):
            recipes = [item for item in self.registration["ownerRecipes"] if item["id"] == identity and item["caseId"] == case]
            assert len(recipes) == 1, "V1_OWNED_RESTORATION_RECIPE_REQUIRED"
            self.run_recipe(recipes[0], case)
        assert not self.pending_cleanup.get(case), "V1_OWNED_POLICY_CLEANUP_UNCERTAIN"
        return {"allOwnedControlsClosed": True}

    def restoration_complete(self):
        return not any(self.pending_cleanup.values())

    def close(self):
        failure = None
        for client in self.clients.values():
            try:
                client.close()
            except Exception as error:
                failure = failure or error
        self.clients.clear()
        if failure:
            raise failure


def resolve_recipe(value, responses):
    if isinstance(value, list):
        return [resolve_recipe(item, responses) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"select"}:
        spec = value["select"]
        assert isinstance(spec, dict) and set(spec) == {"response", "where", "field"}
        rows = resolve_recipe({"response": spec["response"]}, responses)
        assert isinstance(rows, list) and len(rows) <= 100, "V1_BOUNDED_RESPONSE_RECORDS_REQUIRED"
        where = spec["where"]
        assert isinstance(where, dict) and 0 < len(where) <= 4
        assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) and key not in ("__proto__", "constructor", "prototype")
                   and isinstance(item, (str, bool, int)) for key, item in where.items())
        assert all(isinstance(row, dict) for row in rows)
        matches = [row for row in rows if all(key in row and type(row[key]) is type(item) and row[key] == item for key, item in where.items())]
        assert len(matches) == 1, "V1_EXACT_UNIQUE_RESPONSE_RECORD_REQUIRED"
        field = spec["field"]
        assert isinstance(field, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field) and field not in ("__proto__", "constructor", "prototype")
        assert field in matches[0]
        return matches[0][field]
    if set(value) == {"response"}:
        parts = value["response"].split(".")
        assert re.fullmatch(r"[0-5]", parts[0]) and int(parts[0]) < len(responses)
        result = responses[int(parts[0])]
        for part in parts[1:]:
            assert re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", part) and part not in ("__proto__", "constructor", "prototype")
            assert isinstance(result, dict) and part in result
            result = result[part]
        return result
    return {key: resolve_recipe(item, responses) for key, item in value.items()}


def require_readonly_statement(statement):
    from sqlalchemy.sql import visitors
    from sqlalchemy.sql.dml import Delete, Insert, Update
    from sqlalchemy.sql.elements import TextClause
    from sqlalchemy.sql.selectable import SelectBase, TextualSelect
    assert isinstance(statement, SelectBase), "V1_TYPED_READONLY_SELECT_REQUIRED"
    assert not any(isinstance(child, (Insert, Update, Delete, TextClause, TextualSelect))
                   for child in visitors.iterate(statement)), "V1_TYPED_READONLY_SELECT_REQUIRED"


def readonly_notification_observer(registration):
    """Build a finite observer; unavailable or drifted PG identity is fatal.

    Only typed SELECT trees are admitted, including legitimate typed WITH.
    Nested DML and opaque textual nodes are rejected structurally. No settings,
    reminders, outbox state, scheduler or provider is changed by this observer.
    """
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.engine import make_url
    from caseops_api.db.models import HearingReminder, MatterHearing, NotificationDeliveryIntent

    expected = registration["postgresEvidence"]
    assert expected["observed"] is True and expected["readOnly"] is True
    url = make_url(os.environ["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile"

    def observe(hearing_id):
        engine = create_engine(url, connect_args={"connect_timeout": 1, "options": "-c statement_timeout=1200 -c lock_timeout=800"})
        statements = []
        stage = "initializing"
        def before(_connection, _cursor, sql, _parameters, context, _many):
            assert len(statements) < 12, "V1_READONLY_SQL_BOUND"
            node = context.compiled.statement if context.compiled else None
            if stage == "initializing" and node is None:
                assert sql.strip().lower() in ("select pg_catalog.version()", "select current_schema()", "show transaction isolation level", "show standard_conforming_strings")
            elif stage == "readonly-setup":
                assert sql == "SET TRANSACTION READ ONLY"
            else:
                require_readonly_statement(node)
            statements.append(sha(sql.encode()))
        event.listen(engine, "before_cursor_execute", before)
        try:
            with engine.connect() as connection:
                stage = "readonly-setup"
                with connection.begin():
                    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                    stage = "observing"
                    identity = connection.execute(select(func.current_database(), func.pg_postmaster_start_time())).one()
                    assert identity[0] == expected["database"] and identity[1].isoformat() == expected["startedAt"]
                    control = func.pg_control_system().table_valued("system_identifier")
                    system_id = connection.execute(select(control.c.system_identifier)).scalar_one()
                    assert str(system_id) == expected["systemIdentifier"]
                    target = connection.execute(select(MatterHearing.id).where(MatterHearing.id == hearing_id,
                        MatterHearing.company_id == registration["companyId"]).limit(1)).scalar_one()
                    assert target == hearing_id
                    reminders = connection.execute(select(HearingReminder.id).where(HearingReminder.hearing_id == hearing_id,
                        HearingReminder.company_id == registration["companyId"]).limit(101)).all()
                    intents = connection.execute(select(NotificationDeliveryIntent.id, NotificationDeliveryIntent.attempts).where(
                        NotificationDeliveryIntent.company_id == registration["companyId"],
                        NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
                        NotificationDeliveryIntent.schedule_source_id == hearing_id).limit(101)).all()
                    assert len(reminders) <= 100 and len(intents) <= 100
                    return {"outboxCount": len(reminders) + len(intents), "providerAttempts": sum(row.attempts for row in intents),
                            "observerAvailable": True, "readOnly": True, "statements": len(statements), "providerCalls": 0}
        finally:
            engine.dispose()
    return observe


def from_environment(root, run_id, *, environment=None, factory=None, verified_implementation_sha256=None, verified_registration_bytes=None):
    env = os.environ if environment is None else environment
    if env.get("CASEOPS_MOBILE_V1_CONTROLS", "0") == "0":
        return None
    assert env.get("CASEOPS_MOBILE_V1_CONTROLS") == "1", "V1_EXPLICIT_ENABLE_REQUIRED"
    assert env.get("CASEOPS_ENV") == "local" and not any(env.get(key) for key in ("K_SERVICE", "CLOUD_RUN_JOB", "GAE_ENV"))
    assert re.fullmatch(r"[a-f0-9]{40}", env.get("CASEOPS_RELEASE_SHA", ""))
    reference = {"path": env["CASEOPS_MOBILE_V1_REGISTRATION"], "sha256": env["CASEOPS_MOBILE_V1_REGISTRATION_SHA256"]}
    if verified_registration_bytes is None:
        value = checked_json(reference, root)
    else:
        assert isinstance(verified_registration_bytes, bytes) and 0 < len(verified_registration_bytes) <= 262144
        assert sha(verified_registration_bytes) == reference["sha256"], "V1_VERIFIED_REGISTRATION_BYTES_REQUIRED"
        value = json.loads(verified_registration_bytes.decode("utf-8", "strict"))
    validate_registration(value, source=env["CASEOPS_RELEASE_SHA"], run=run_id, now=time.time())
    assert re.fullmatch(r"[a-f0-9]{64}", verified_implementation_sha256 or ""), "V1_VERIFIED_RUNTIME_SOURCE_REQUIRED"
    assert value["implementationSha256"] == verified_implementation_sha256, "V1_CONTROL_IMPLEMENTATION_CHANGED"
    # Verify actual API AND web identities before opening any actor/authority file.
    import httpx
    with httpx.Client(timeout=3, follow_redirects=False, headers={"X-CaseOps-Automated-Test": MARKER}) as http:
        for origin, route, revision in (("http://api:8000", "/api/build", "backendRevision"),
                                        ("http://web:3000", "/api/release-identity", "webRevision")):
            response = bounded_http(http, "GET", origin + route)
            assert response.status_code == 200
            serving = response.json()
            assert serving["release_sha"] == value["sourceSha"] and serving["revision"] == value[revision]
    secret = checked_json(value["authorityEvidence"], root, private=True)["control_secret"]
    assert re.fullmatch(r"[a-f0-9]{64}", secret)
    owner = RegisteredOwner(value, root) if factory is None else factory(value, root)
    observer = readonly_notification_observer(value)
    persist, close_journal = create_journal(root, value["registrationId"])
    def claim(identity):
        with (root / f"v1-control-attempt-{sha(identity.encode())}.json").open("x", encoding="utf-8") as output:
            output.write(json.dumps({"operationId": identity, "automaticRetry": False}))
    owner.claim = claim
    try:
        return V1Controls(value, reference["sha256"], secret, owner=owner, observer=observer, persist=persist, claim=claim, close_journal=close_journal)
    except BaseException as error:
        try:
            owner.close()
        except BaseException:
            error.add_note("V1_OWNER_CLEANUP_UNVERIFIED_DURING_SETUP")
        try:
            close_journal()
        except BaseException:
            error.add_note("V1_JOURNAL_CLEANUP_UNVERIFIED_DURING_SETUP")
        raise
