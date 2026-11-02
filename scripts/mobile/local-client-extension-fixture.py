"""Separate normal-API and historical-row fixture producers; never imported by the reader.

Only the retained mode writes two Recommendation rows directly. The normal
mode creates valid sibling/Matter/hearing/pack records through the APIs.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import stat
from datetime import UTC, datetime, date

UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
KINDS = ("oversize", "legacy-json")
MAX_ROWS = 1024
MAX_CAPTURE = 16 * 1024 * 1024
MAX_LIFETIME_SECONDS = 60

def canonical(value): return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
def sha(value): return hashlib.sha256(value).hexdigest()

def held_json(reference, root, *, private=False):
    if private:
        assert set(reference) == {"path", "sha256", "uid"}
        assert type(reference["uid"]) is int and reference["uid"] >= 0
    target = Path(reference["path"])
    assert target.parent == root and target.resolve() == target and root.resolve() == root
    fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
    meta = lambda s: tuple(getattr(s, key) for key in fields)
    def namespace():
        assert target.resolve() == target
        return [(str(p), meta(p.lstat())) for p in target.parents]
    parents = namespace(); before = target.lstat()
    assert stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 16384
    if private:
        assert before.st_uid == reference["uid"] == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600
    fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    data = bytearray()
    try:
        assert meta(os.fstat(fd)) == meta(before)
        while len(data) <= 16384:
            part = os.read(fd, 16385 - len(data))
            if not part: break
            data.extend(part)
        assert len(data) == before.st_size and len(data) <= 16384
        assert meta(os.fstat(fd)) == meta(before) == meta(target.lstat()) and namespace() == parents
        assert sha(data) == reference["sha256"]
        value = json.loads(data.decode("utf-8", "strict")); assert isinstance(value, dict); return value
    finally:
        if private: data[:] = b"\0" * len(data)
        os.close(fd)

def validate_request(q, environment, now):
    assert environment.get("CASEOPS_NATIVE_CLIENT_RETAINED_FIXTURE_GO") == "EXPLICIT_OWNED_SYNTHETIC_PRODUCER"
    assert environment.get("CASEOPS_ENV") == "local" and environment.get("CASEOPS_LLM_PROVIDER") == "mock"
    assert not any(environment.get(key) for key in ("K_SERVICE", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert environment.get("K_REVISION") in (None, "", q["backendRevision"]), "OWNED_LOCAL_REVISION_REQUIRED"
    assert q["kind"] == "native-client-retained-row-producer" and q["schemaVersion"] == 1
    assert q["readyForLive"] is True and q["preparedOnly"] is False
    assert q["noPaidMarker"] == "no-paid-providers" and q["productionAccessed"] is False and q["automaticRetry"] is False
    assert q["sourceSha"] == environment["CASEOPS_RELEASE_SHA"] and re.fullmatch(r"[a-f0-9]{40}", q["sourceSha"])
    assert type(q["expiresAt"]) in (int, float) and 0 < q["expiresAt"] - now <= MAX_LIFETIME_SECONDS
    for key in ("companyId", "membershipId", "userId", "matterId", "validSiblingId"):
        assert UUID.fullmatch(q[key])
    assert q["companySlug"].startswith("test-mobile-") and len(q["companySlug"]) <= 80
    assert type(q["expectedLifecycleVersion"]) is int and q["expectedLifecycleVersion"] >= 0
    assert len(q["rows"]) == 2 and tuple(row["kind"] for row in q["rows"]) == KINDS
    assert len({row["id"] for row in q["rows"]}) == 2
    assert all(set(row) == {"id", "kind"} and UUID.fullmatch(row["id"]) and row["id"] != q["validSiblingId"] for row in q["rows"])
    assert q["databaseIdentity"]["databaseName"] == "caseops_mobile"
    assert q["databaseIdentity"]["roleName"] == "caseops"
    return q

def retained_values(q):
    stamp = datetime(2026, 10, 28, tzinfo=UTC)
    result = []
    for row in q["rows"]:
        result.append({"id": row["id"], "company_id": q["companyId"], "matter_id": q["matterId"],
            "created_by_membership_id": q["membershipId"], "type": "settlement", "title": "Synthetic retained " + row["kind"],
            "rationale": "Synthetic retained source. " + "x" * 16385 if row["kind"] == "oversize" else "Synthetic retained legacy source.",
            "assumptions_json": "[" if row["kind"] == "legacy-json" else "[]", "missing_facts_json": "[]",
            "retrieved_authorities_json": "[]", "confidence": "low", "review_required": True, "status": "proposed",
            "created_at": stamp, "updated_at": stamp})
    return result

def write_new(path, value):
    data = canonical(value) + b"\n"; assert len(data) <= 1048576
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(fd, 0o600)
        opened = os.fstat(fd); assert stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_uid == os.getuid()
        pending = memoryview(data)
        while pending:
            count = os.write(fd, pending); assert 0 < count <= len(pending); pending = pending[count:]
        os.fsync(fd)
        final = os.fstat(fd); named = Path(path).lstat()
        assert final.st_size == len(data) and stat.S_IMODE(final.st_mode) == 0o600
        fields = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        assert all(getattr(final,k) == getattr(named,k) for k in fields)
        assert (final.st_dev,final.st_ino,final.st_uid,final.st_gid,final.st_mode,final.st_nlink) == (opened.st_dev,opened.st_ino,opened.st_uid,opened.st_gid,opened.st_mode,opened.st_nlink)
    finally: os.close(fd)
    return {"path": str(path), "sha256": sha(data)}

def produce(q, *, root, environment, http, owner, now):
    # Public source/settings/API+web checks happen before DB imports or private
    # actor use. The owner transport is supplied by the admitted fixture CLI.
    validate_request(q, environment, now())
    for origin, route, revision in (("http://api:8000", "/api/build", q["backendRevision"]), ("http://web:3000", "/api/release-identity", q["webRevision"])):
        response = http.get(origin + route, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}, timeout=5)
        assert response.status_code == 200 and len(response.content) <= 65536
        value = response.json(); assert value["release_sha"] == q["sourceSha"] and value["revision"] == revision
    normal = held_json(q["validSiblingEvidence"], root)
    assert normal["kind"] == "normal-api-synthetic-recommendation" and normal["observed"] is True
    assert normal["noPaidMarker"] == "no-paid-providers" and normal["llmProvider"] == "mock" and normal["sourceSha"] == q["sourceSha"]
    assert normal["companyId"] == q["companyId"] and normal["matterId"] == q["matterId"] and normal["id"] == q["validSiblingId"]
    write_new(root / (q["rows"][0]["id"] + ".retained-producer.claim.json"), {"requestIdentitySha256": sha(canonical(q)), "noReplay": True})
    actor = owner()
    response = actor.get("/api/auth/me", timeout=5)
    assert response.status_code == 200 and len(response.content) <= 65536
    current = response.json()
    assert current["company"]["id"] == q["companyId"] and current["membership"]["id"] == q["membershipId"] and current["user"]["id"] == q["userId"]
    assert current["membership"]["is_active"] is True and current["user"]["is_active"] is True
    # This is deliberately separate writer authority from the gateway reader.
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from caseops_api.db.models import Company, CompanyMembership, User, Matter, Recommendation, DomainOutboxEvent
    from caseops_api.db.session import get_session_factory
    url = make_url(environment["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile" and url.username == "caseops"
    with get_session_factory()() as session:
        assert session.bind.dialect.name == "postgresql"
        actual = session.execute(text("SELECT current_database() AS db, current_user AS role, inet_server_addr()::text AS address, inet_server_port() AS port, pg_postmaster_start_time()::text AS started")).mappings().one()
        expected = q["databaseIdentity"]
        assert dict(actual) == {"db": expected["databaseName"], "role": expected["roleName"], "address": expected["serverAddress"], "port": expected["serverPort"], "started": expected["postmasterStartedAt"]}
        session.execute(text("SET LOCAL lock_timeout = '2s'")); session.execute(text("SET LOCAL statement_timeout = '5s'"))
        company = session.scalar(select(Company).where(Company.id == q["companyId"]).with_for_update())
        member = session.scalar(select(CompanyMembership).where(CompanyMembership.id == q["membershipId"], CompanyMembership.company_id == q["companyId"]).with_for_update())
        user = session.scalar(select(User).where(User.id == q["userId"]))
        matter = session.scalar(select(Matter).where(Matter.id == q["matterId"], Matter.company_id == q["companyId"]).with_for_update())
        assert company and company.slug == q["companySlug"] and company.is_active
        assert member and member.user_id == q["userId"] and member.is_active and user and user.is_active
        assert matter and matter.is_active and matter.lifecycle_version == q["expectedLifecycleVersion"]
        sibling = session.scalar(select(Recommendation).where(Recommendation.id == q["validSiblingId"], Recommendation.company_id == q["companyId"], Recommendation.matter_id == q["matterId"]))
        assert sibling and sibling.model_run_id is not None, "ACTUAL_NORMAL_MOCK_GENERATION_REQUIRED"
        ids = [row["id"] for row in q["rows"]]
        existing_id = session.scalar(select(Recommendation.id).where(Recommendation.id.in_(ids)).limit(1))
        assert existing_id is None, "RETAINED_PRODUCER_REPLAY_REFUSED"
        def fingerprint(model, predicate):
            rows = session.execute(select(*model.__table__.columns).where(predicate).order_by(model.id).limit(MAX_ROWS + 1)).all()
            assert len(rows) <= MAX_ROWS
            data = canonical([list(row) for row in rows]); assert len(data) <= MAX_CAPTURE
            return {"rows": len(rows), "sha256": sha(data)}
        source_predicate = (Recommendation.company_id == q["companyId"]) & ~Recommendation.id.in_(ids)
        before = {"source": fingerprint(Recommendation, source_predicate), "outbox": fingerprint(DomainOutboxEvent, DomainOutboxEvent.company_id == q["companyId"])}
        for values in retained_values(q): session.add(Recommendation(**values))
        session.flush()
        after = {"source": fingerprint(Recommendation, source_predicate), "outbox": fingerprint(DomainOutboxEvent, DomainOutboxEvent.company_id == q["companyId"])}
        assert before == after; assert now() < q["expiresAt"]
        session.commit()
    # Commit ACK is retained before a readback failure; never seed again.
    receipt = {"kind": "actual-retained-native-client-extension-rows", "observed": True, "sourceSha": q["sourceSha"], "companyId": q["companyId"], "matterId": q["matterId"], "rows": q["rows"], "historicalWriter": True, "directDatabaseWrites": True, "consumerDatabaseAuthorityAdded": False, "noPaidMarker": "no-paid-providers", "before": before, "after": after, "committed": True, "automaticRetry": False, "normalReadback": "pending"}
    committed = write_new(root / (q["rows"][0]["id"] + ".retained-producer.receipt.json"), receipt)
    readbacks = []
    for identity, state in [(row["id"], "unsupported_size" if row["kind"] == "oversize" else "unsupported_legacy") for row in q["rows"]] + [(q["validSiblingId"], "available")]:
        response = actor.get("/api/matter-readthrough/" + q["matterId"] + "/recommendations/" + identity, timeout=5)
        assert response.status_code == 200 and len(response.content) <= 1048576
        value = response.json(); assert value["id"] == identity and value["read_state"] == state
        assert value["scope"]["company_id"] == q["companyId"] and value["scope"]["matter_id"] == q["matterId"]
        if state != "available": assert value["record"] is None
        readbacks.append(value)
    response = actor.get("/api/matter-readthrough/" + q["matterId"] + "/recommendations?limit=25", timeout=5)
    assert response.status_code == 200 and len(response.content) <= 1048576
    page = response.json(); assert page["scope"]["company_id"] == q["companyId"] and page["scope"]["matter_id"] == q["matterId"]
    assert {q["validSiblingId"], *(row["id"] for row in q["rows"])} <= {row["id"] for row in page["items"]}
    complete = write_new(root / (q["rows"][0]["id"] + ".retained-producer.readback.json"), {
        "kind": "actual-retained-native-client-extension-readback", "complete": True, "sourceSha": q["sourceSha"],
        "companyId": q["companyId"], "matterId": q["matterId"], "committedEvidence": committed,
        "readbacks": readbacks, "recommendationPage": page, "noPaidMarker": "no-paid-providers", "normalApiReadback": True})
    return {"committedEvidence": committed, "readbackEvidence": complete}


def produce_normal(q, *, root, environment, http, owner, now):
    """Create valid siblings using actual existing APIs, with one claim and no retry.

    Historical invalid rows have a different request kind/authority and receipt.
    No normal-path DB imports or caller-supplied arbitrary HTTP recipes exist.
    """
    assert environment.get("CASEOPS_NATIVE_CLIENT_DATASET_GO") == "EXPLICIT_OWNED_SYNTHETIC_PRODUCER"
    assert environment.get("CASEOPS_ENV") == "local" and environment.get("CASEOPS_LLM_PROVIDER") == "mock"
    assert not any(environment.get(k) for k in ("K_SERVICE", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert q["kind"] == "native-client-normal-api-producer" and q["schemaVersion"] == 1
    assert q["readyForLive"] is True and q["preparedOnly"] is False
    assert q["noPaidMarker"] == "no-paid-providers" and q["automaticRetry"] is False and q["productionAccessed"] is False
    assert re.fullmatch(r"[a-f0-9]{40}", q["sourceSha"]) and q["sourceSha"] == environment["CASEOPS_RELEASE_SHA"]
    assert environment.get("K_REVISION") in (None, "", q["backendRevision"])
    assert type(q["expiresAt"]) in (int, float) and 0 < q["expiresAt"] - now() <= 180
    for key in ("datasetId", "companyId", "membershipId", "userId", "cameraMatterId", "byteSourceId"):
        assert UUID.fullmatch(q[key])
    assert q["companySlug"].startswith("test-mobile-") and len(q["companySlug"]) <= 80
    assert q["platform"] in ("ios", "android") and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", q["hearingDate"])
    assert date.fromisoformat(q["hearingDate"]).isoformat() == q["hearingDate"]
    version = re.compile(r"(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\.(?:0|[1-9][0-9]{0,8})\Z")
    assert all(type(q[k]) is str and len(q[k]) <= 29 and version.fullmatch(q[k]) for k in ("actualBinaryVersion", "floorVersion"))
    assert tuple(map(int,q["actualBinaryVersion"].split("."))) < tuple(map(int,q["floorVersion"].split(".")))
    assert re.fullmatch(r"[a-f0-9]{64}", q["byteSourceSha256"]) and isinstance(q["byteSourceText"],str) and len(q["byteSourceText"]) <= 100000
    assert q["workflowDomain"] in (("simulator", "physical") if q["platform"] == "ios" else ("emulator", "physical"))
    assert set(q["scannerConfigurationEvidence"]) == {"path", "sha256"}
    assert re.fullmatch(r"[a-f0-9]{64}", q["scannerConfigurationEvidence"]["sha256"])
    assert len(q["retainedRows"]) == 2 and tuple(x["kind"] for x in q["retainedRows"]) == KINDS
    assert all(set(x) == {"id", "kind"} and UUID.fullmatch(x["id"]) for x in q["retainedRows"])
    assert len({x["id"] for x in q["retainedRows"]}) == 2
    for origin, route, revision in (("http://api:8000", "/api/build", q["backendRevision"]), ("http://web:3000", "/api/release-identity", q["webRevision"])):
        response = http.get(origin + route, headers={"X-CaseOps-Automated-Test": "no-paid-providers"}, timeout=5)
        assert response.status_code == 200 and len(response.content) <= 65536
        value = response.json(); assert value["release_sha"] == q["sourceSha"] and value["revision"] == revision
    second = held_json(q["secondMatterEvidence"], root)
    assert second["observed"] is True and second["sourceSha"] == q["sourceSha"] and second["noPaidMarker"] == "no-paid-providers"
    assert second["companyId"] != q["companyId"] and UUID.fullmatch(second["companyId"]) and UUID.fullmatch(second["matter"]["id"])
    write_new(root / (q["datasetId"] + ".normal-producer.claim.json"), {"requestSha256": sha(canonical(q)), "noReplay": True})
    actor = owner(); counts = {"requests": 0, "posts": 0}; acknowledgements = []
    def call(method, route, payload=None, status=200):
        assert now() < q["expiresAt"], "NORMAL_PRODUCER_DEADLINE"
        counts["requests"] += 1; assert counts["requests"] <= 40
        if method == "POST": counts["posts"] += 1
        response = actor.request(method, route, **({"json": payload} if payload is not None else {}), timeout=15)
        assert response.status_code == status and len(response.content) <= 1048576, "NORMAL_API_ACK_REQUIRED_NO_REPLAY"
        value = response.json()
        if method == "POST":
            acknowledgement = {"method": method, "route": route, "status": status, "responseSha256": sha(response.content), "ordinal": counts["posts"]}
            acknowledgements.append(write_new(root / (q["datasetId"] + ".normal-ack-" + str(counts["posts"]) + ".json"), acknowledgement))
        return value
    current = call("GET", "/api/auth/me")
    assert current["user"]["id"] == q["userId"] and current["company"]["id"] == q["companyId"] and current["membership"]["id"] == q["membershipId"]
    assert current["company"]["slug"] == q["companySlug"]
    assert current["user"]["is_active"] is True and current["membership"]["is_active"] is True
    camera = call("GET", "/api/matters/" + q["cameraMatterId"])
    assert camera["company_id"] == q["companyId"] and camera["is_active"] is True
    workspace = call("GET", "/api/matters/" + camera["id"] + "/workspace")
    byte_source = next(x for x in workspace["attachments"] if x["id"] == q["byteSourceId"])
    assert byte_source["matter_id"] == camera["id"] and byte_source["sha256_hex"] == q["byteSourceSha256"]
    def matter(kind):
        return call("POST", "/api/matters/", {"title": "Synthetic native extension " + kind, "matter_code": "CX28-" + q["datasetId"][:8] + "-" + kind.upper(), "practice_area": "Litigation", "forum_level": "advisory", "status": "intake", "assignee_membership_id": q["membershipId"]})
    main, empty, revocable = [matter(kind) for kind in ("read", "empty", "revocable")]
    for value in (main, empty, revocable): assert value["company_id"] == q["companyId"] and UUID.fullmatch(value["id"])
    def recommendation(target):
        value = call("POST", "/api/matters/" + target["id"] + "/recommendations", {"type": "next_best_action", "recommendation_context": "case_preparation"})
        assert value["matter_id"] == target["id"] and UUID.fullmatch(value["id"]) and value["options"]
        assert value["review_required"] is True
        return value
    rec, revocable_rec = recommendation(main), recommendation(revocable)
    call("POST", "/api/recommendations/" + rec["id"] + "/decisions", {"decision": "deferred", "notes": "Synthetic recorded decision for native read-only acceptance."})
    hearings, packs = [], []
    for index in range(3):
        hearing = call("POST", "/api/matters/" + main["id"] + "/hearings", {"expected_lifecycle_version": main["lifecycle_version"], "hearing_on": q["hearingDate"], "forum_name": "Synthetic local forum", "purpose": "Synthetic extension hearing " + str(index), "time_status": "time_not_published", "reminder_channels": ["in_app"], "reminder_recipient_membership_ids": []})
        assert hearing["matter_id"] == main["id"] and UUID.fullmatch(hearing["id"]); hearings.append(hearing)
        if index < 2:
            pack = call("POST", "/api/matters/" + main["id"] + "/hearings/" + hearing["id"] + "/pack", {})
            assert pack["matter_id"] == main["id"] and pack["hearing_id"] == hearing["id"] and pack["items"] and pack["review_required"] is True
            if index == 1: pack = call("POST", "/api/matters/" + main["id"] + "/hearing-packs/" + pack["id"] + "/review", {})
            assert pack["status"] == ("draft" if index == 0 else "reviewed"); packs.append(pack)
    def public_matter(m): return {"id": m["id"], "code": m["matter_code"], "identityLabel": m["matter_code"], "search": m["matter_code"], "title": m["title"]}
    expected_readbacks = []
    for route in ("/api/matter-readthrough/" + main["id"] + "/recommendations/" + rec["id"], "/api/matter-readthrough/" + main["id"] + "/recommendations/" + rec["id"] + "/options?limit=25", "/api/matter-readthrough/" + main["id"] + "/recommendations/" + rec["id"] + "/decisions?limit=25", "/api/matter-readthrough/" + main["id"] + "/hearing-packs/" + packs[0]["id"] + "/items?limit=25"):
        value = call("GET", route); assert value["scope"]["company_id"] == q["companyId"] and value["scope"]["matter_id"] == main["id"]
        expected_readbacks.append({"route": route, "value": value})
    cx = {"identity": {k: q[k] for k in ("userId", "companyId", "membershipId")}, "matter": public_matter(camera), "noPaidMarker": "no-paid-providers", "automaticRetry": False, "directDatabaseWrites": False, "nativeMutationsForwardedByControls": False, "workflowDomain": q["workflowDomain"],
        "camera": {"filename": "capture.jpg", "filenames": ["capture.jpg", "capture.jpeg", "capture.png"], "deniedMessage": "Camera access was not granted. You can still use Choose file, or enable camera access in device settings.", "privacyDisclosure": "Take a photo, then choose whether to upload it. Photos may include details such as capture location. Those details are kept when you upload. Camera access is optional; Choose file remains available.", "maxAcceptanceBytes": 900000},
        "lock": {"cancelMessage": "Local lock policy or authentication could not be confirmed. Retry, or sign out and use secure sign-in.", "missingOrInvalidatedMessage": "Local lock policy or authentication could not be confirmed. Retry, or sign out and use secure sign-in."},
        "version": {"actual": q["actualBinaryVersion"], "floor": q["floorVersion"], "byteSource": {"id": q["byteSourceId"], "matterId": camera["id"], "text": q["byteSourceText"], "sha256": q["byteSourceSha256"]}},
        "links": {"own": "caseops://open/workspaces/" + q["companyId"] + "/matters/" + main["id"], "matter": public_matter(main), "secondOwn": "caseops://open/workspaces/" + second["companyId"] + "/matters/" + second["matter"]["id"], "secondMatter": {**second["matter"], "identityLabel": second["matter"].get("identityLabel", second["matter"].get("code"))}, "foreign": "caseops://open/workspaces/" + second["companyId"] + "/matters/" + main["id"], "foreignMessage": "Sign in to the matching workspace, then open this link again.", "unsavedNote": "Synthetic unsaved extension note; never submitted.", "invalid": ["caseops://open/workspaces/invalid/matters/invalid", "caseops://auth/callback?code=synthetic", "caseops://open/workspaces/" + q["companyId"] + "/matters/" + main["id"] + "?token=synthetic", "https://synthetic.invalid/native/open/workspaces/invalid"]},
        "readthrough": {"matterId": main["id"], "matter": public_matter(main), "recommendationId": rec["id"], "recommendationIds": [rec["id"]], "unsupportedRecommendationId": q["retainedRows"][0]["id"], "legacyRecommendationId": q["retainedRows"][1]["id"], "unsupportedCaption": "Retained content unavailable in this view", "emptyMatter": public_matter(empty), "revocableMatter": public_matter(revocable), "revocableRecommendationId": revocable_rec["id"], "deniedCaption": "Matter not found.", "hearingId": hearings[0]["id"], "readyOnlyPackIds": [x["id"] for x in packs], "packStates": [{"matter": public_matter(main), "hearingId": hearings[i]["id"], **({"packId": packs[i]["id"], "status": packs[i]["status"]} if i < 2 else {"caption": "No saved hearing pack"})} for i in range(3)]}}
    cx["scannerConfigurationEvidence"] = q["scannerConfigurationEvidence"]
    receipt = {"kind": "actual-normal-api-native-client-extension-fixture", "observed": True, "sourceSha": q["sourceSha"], "companyId": q["companyId"], "membershipId": q["membershipId"], "noPaidMarker": "no-paid-providers", "directDatabaseWrites": False, "automaticRetry": False, "mutationUncertain": False, "llmProvider": "mock", "cx": cx, "acknowledgements": acknowledgements, "counts": counts, "normalReadbacks": expected_readbacks, "retainedProducerRequestedSeparately": True}
    evidence = write_new(root / (q["datasetId"] + ".normal-producer.receipt.json"), receipt)
    sibling = write_new(root / (q["datasetId"] + ".normal-sibling.json"), {"kind": "normal-api-synthetic-recommendation", "observed": True, "noPaidMarker": "no-paid-providers", "llmProvider": "mock", "sourceSha": q["sourceSha"], "companyId": q["companyId"], "matterId": main["id"], "id": rec["id"], "datasetEvidence": evidence})
    return {"datasetEvidence": evidence, "validSiblingEvidence": sibling, "validSiblingId": rec["id"], "matterId": main["id"], "expectedLifecycleVersion": main["lifecycle_version"], "retainedRows": q["retainedRows"]}

def main(request, digest):
    import time
    root = Path(os.environ.get("CASEOPS_MOBILE_STATE", "/fixture-state")).resolve()
    q = held_json({"path": request, "sha256": digest}, root)
    assert q["kind"] in ("native-client-normal-api-producer", "native-client-retained-row-producer")
    if q["kind"] == "native-client-retained-row-producer": validate_request(q, os.environ, time.time())
    import httpx
    marker = {"X-CaseOps-Automated-Test": "no-paid-providers"}
    with httpx.Client(follow_redirects=False, headers=marker, verify=True, trust_env=False) as public, httpx.Client(base_url="http://api:8000", follow_redirects=False, headers=marker, verify=True, trust_env=False) as actor:
        attempted = False
        def owner():
            nonlocal attempted
            assert not attempted; attempted = True
            credentials = held_json(q["credentialEvidence"], root, private=True)
            try:
                response = actor.post("/api/auth/login", json={key: credentials[key] for key in ("email", "password", "company_slug")}, timeout=5)
                assert response.status_code == 200 and len(response.content) <= 65536
                value = response.json(); assert value["company"]["id"] == q["companyId"] and value["membership"]["id"] == q["membershipId"] and value["user"]["id"] == q["userId"]
                actor.cookies.clear(); actor.headers["Authorization"] = "Bearer " + value["access_token"]
                import pyotp
                response = actor.post("/api/auth/mfa/step-up", json={"code": pyotp.TOTP(credentials["totp_secret"]).now(), "purpose": "step_up", "method": "totp"}, timeout=5)
                assert response.status_code == 200
                return actor
            finally: credentials.clear()
        function = produce_normal if q["kind"] == "native-client-normal-api-producer" else produce
        return function(q, root=root, environment=os.environ, http=public, owner=owner, now=time.time)

if __name__ == "__main__":
    import sys
    try:
        assert len(sys.argv) == 3
        print(json.dumps(main(sys.argv[1], sys.argv[2])))
    except Exception:
        print("NATIVE_CLIENT_RETAINED_PRODUCER_REFUSED_OR_UNKNOWN_NO_REPLAY", file=sys.stderr)
        sys.exit(1)
