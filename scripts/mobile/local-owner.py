"""Bounded fixture-only SQL owner commands using canonical product services."""

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
from urllib.request import urlopen

ROOT = Path("/fixture-state")
OPERATIONS = {"disposeMatter", "readMatterState", "revokeMatterAccess", "readNoteState"}
MAX_COMMANDS = 16
MAX_REQUEST_BYTES = 4096
MAX_RESPONSE_BYTES = 65536
WORKER_LIFETIME_SECONDS = 1200


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hashed(name, expected):
    assert re.fullmatch(r"[a-zA-Z0-9_.-]+\.json", name) and "/" not in name
    path = ROOT / name
    assert digest(path) == expected, "Owner binding evidence changed"
    return json.loads(path.read_text(encoding="utf-8"))


def expired(_signal, _frame):
    raise TimeoutError("OWNER_CONTROL_DEADLINE")


def run_operation(request, worker=None):
    for key in ("targetId", "runId", "requestId"):
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request[key]), "Invalid owner identity"
    assert request["operation"] in OPERATIONS and request["marker"] == "no-paid-providers"
    assert re.fullmatch(r"[a-f0-9]{40}", request["backendSha"])
    remaining = (request["deadlineMs"] - time.time() * 1000) / 1000
    assert 0 < remaining <= 8, "Expired owner command"
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    started = time.monotonic()
    progress_path = ROOT / f"owner-progress-{request['requestId']}.jsonl"
    stage_count = 0

    def checkpoint(stage):
        nonlocal stage_count
        assert stage_count < 10, "Owner progress bound"
        with progress_path.open("x" if stage_count == 0 else "a", encoding="utf-8") as progress:
            progress.write(json.dumps({"stage": stage, "elapsedMs": round((time.monotonic() - started) * 1000),
                                      "operation": request["operation"], "requestId": request["requestId"]}) + "\n")
            progress.flush()
            os.fsync(progress.fileno())
        stage_count += 1

    checkpoint("request-validated")
    binding = load_hashed(request["bindingFile"], request["bindingSha256"])
    extension = load_hashed(binding["extensionFile"], binding["extensionSha256"])
    assert binding["backendSha"] == request["backendSha"]
    assert digest(Path(__file__)) == binding["pythonSha256"], "Owner implementation changed"
    if worker:
        assert request["workerId"] == worker["workerId"] and request["readySha256"] == worker["readySha256"]
        assert request["bindingFile"] == worker["bindingFile"] and request["bindingSha256"] == worker["bindingSha256"]
        assert digest(ROOT / worker["readyFile"]) == worker["readySha256"], "Owner readiness evidence changed"
    target_kind = "lifecycleMatter" if request["operation"] in ("disposeMatter", "readMatterState") else "accessMatter"
    assert extension[target_kind]["id"] == request["targetId"], "Unowned fixture target"
    assert binding["syntheticDataOnly"] and binding["environment"] == "docker-integration"
    assert os.environ.get("CASEOPS_ENV") == "local"
    checkpoint("binding-validated")
    # Independent SQL budgets remain below both the child and harness deadlines.
    os.environ.update({"CASEOPS_DB_CONNECT_TIMEOUT_SECONDS": "1", "CASEOPS_DB_STATEMENT_TIMEOUT_MS": "1200",
                       "CASEOPS_DB_LOCK_TIMEOUT_MS": "800", "CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS": "3000"})
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from caseops_api.db.models import Company, CompanyMembership, Matter, MatterNote, MembershipRole
    from caseops_api.db.session import get_session_factory
    checkpoint("read-imports-ready")

    url = make_url(os.environ["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile", "Non-fixture database refused"
    with urlopen("http://127.0.0.1:8000/api/build", timeout=0.7) as response:
        build = json.load(response)
    assert build["release_sha"] == request["backendSha"] and build["revision"] == binding["backendRevision"]
    checkpoint("serving-build-verified")
    mutation = request["operation"] in ("disposeMatter", "revokeMatterAccess")
    if mutation:
        # A failed/uncertain invocation is never replayed, even if it emitted no receipt.
        claim_id = hashlib.sha256(f"{request['runId']}:{request['operation']}:{request['targetId']}".encode()).hexdigest()
        with (ROOT / f"owner-attempt-{claim_id}.json").open("x", encoding="utf-8") as claim:
            json.dump({key: request[key] for key in ("runId", "operation", "targetId", "requestId", "backendSha")}, claim)
            claim.flush()
            os.fsync(claim.fileno())
    with get_session_factory()() as session:
        session.execute(text("SET LOCAL statement_timeout = '1200ms'"))
        session.execute(text("SET LOCAL lock_timeout = '800ms'"))
        checkpoint("database-budget-set")
        company = session.scalar(select(Company).where(Company.id == extension["companyId"]).limit(1))
        assert company and company.slug == "test-legal"
        owner = session.scalar(select(CompanyMembership).where(
            CompanyMembership.id == extension["ownerMembershipId"], CompanyMembership.company_id == company.id,
        ).limit(1))
        member = session.scalar(select(CompanyMembership).where(
            CompanyMembership.id == extension["membershipId"], CompanyMembership.company_id == company.id,
        ).limit(1))
        assert owner and owner.role == MembershipRole.OWNER and owner.is_active
        assert member and member.role != MembershipRole.OWNER and member.is_active
        target = session.scalar(select(Matter).where(Matter.id == request["targetId"], Matter.company_id == company.id).limit(1))
        assert target and target.matter_code == extension[target_kind]["identityLabel"]
        checkpoint("owner-member-target-verified")
        if mutation:
            from caseops_api.services.identity import get_session_context

            owner_context = get_session_context(session, owner.id)
        else:
            # Match the owner context's activity checks without loading mutation services.
            assert company.is_active and owner.user.is_active, "Owner session is no longer active"
        if request["operation"] == "disposeMatter":
            from caseops_api.schemas.matters import MatterLifecycleStatusRequest
            from caseops_api.services.matters import transition_matter_lifecycle_status

            assert target.status in ("intake", "active", "on_hold") and target.is_active, "Fresh operational target required; never reopen"
            transition_matter_lifecycle_status(session, context=owner_context, matter_id=target.id,
                payload=MatterLifecycleStatusRequest(to_status="disposed", expected_from_status=target.status,
                    expected_updated_at=target.updated_at, reason="Dedicated native stale-editor acceptance command"))
        elif request["operation"] == "revokeMatterAccess":
            from caseops_api.services.matter_access import can_access, remove_access_grant

            member_context = get_session_context(session, member.id)
            assert can_access(session, context=member_context, matter=target), "Already-revoked fixture cannot be reused"
            assert target.restricted_access and target.assignee_membership_id != member.id
            remove_access_grant(session, context=owner_context, matter_id=target.id, grant_id=extension["accessGrantId"])
        session.expire_all()
        target = session.scalar(select(Matter).where(Matter.id == request["targetId"], Matter.company_id == company.id).limit(1))
        note_ids = list(session.scalars(select(MatterNote.id).where(MatterNote.matter_id == target.id).order_by(MatterNote.id).limit(101)))
        assert len(note_ids) <= 100, "Fixture note-state bound exceeded"
        result = {"status": str(target.status).lower(), "isActive": target.is_active,
                  "lifecycleVersion": target.lifecycle_version, "noteIds": note_ids}
        if request["operation"] == "revokeMatterAccess":
            member_context = get_session_context(session, extension["membershipId"])
            result = {"accessAllowed": can_access(session, context=member_context, matter=target)}
            assert result["accessAllowed"] is False
        session.rollback()
    checkpoint("operation-complete")
    evidence = {"kind": "docker-owner-control", **{key: request[key] for key in (
        "operation", "targetId", "runId", "backendSha", "requestId")},
        "backendRevision": build["revision"], "project": binding["project"],
        "apiContainerId": binding["apiContainerId"], "apiImage": binding["apiImage"],
        "extensionSha256": binding["extensionSha256"], "transport": "canonical-product-services-real-postgresql",
        "sqlStatementTimeoutMs": 1200, "sqlLockTimeoutMs": 800, "hardDeadlineMs": request["deadlineMs"],
        "result": result}
    if worker:
        evidence.update({"workerId": worker["workerId"], "workerCommand": worker["commandCount"],
                         "workerReadyEvidence": {"file": worker["readyFile"], "sha256": worker["readySha256"]}})
    payload = json.dumps(evidence).encode()
    assert len(payload) <= 65536
    filename = f"owner-evidence-{request['requestId']}.json"
    with (ROOT / filename).open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    return {"evidenceFile": filename, "result": result}


def bounded_line(stream):
    raw = stream.readline(MAX_REQUEST_BYTES + 1)
    if not raw:
        return None
    assert len(raw) <= MAX_REQUEST_BYTES and raw.endswith(b"\n"), "Owner worker request bound"
    value = json.loads(raw)
    assert isinstance(value, dict), "Owner worker object required"
    return value


def emit_line(value, output):
    raw = json.dumps(value).encode()
    assert len(raw) + 1 <= MAX_RESPONSE_BYTES, "Owner worker response bound"
    output.write(raw.decode() + "\n")
    output.flush()


def prepare_worker(request):
    assert request["type"] == "prepare" and request["marker"] == "no-paid-providers"
    for key in ("workerId", "requestId"):
        assert re.fullmatch(r"[a-f0-9]{24}", request[key]), "Invalid worker identity"
    remaining = (request["deadlineMs"] - time.time() * 1000) / 1000
    assert 0 < remaining <= 30, "Expired owner readiness"
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    binding = load_hashed(request["bindingFile"], request["bindingSha256"])
    load_hashed(binding["extensionFile"], binding["extensionSha256"])
    assert binding["backendSha"] == request["backendSha"]
    assert binding["environment"] == "docker-integration" and binding["syntheticDataOnly"]
    assert re.fullmatch(r"[a-f0-9]{64}", binding["apiContainerId"])
    assert binding["apiContainerId"] == request["apiContainerId"]
    assert binding["apiImage"] == request["apiImage"] and binding["project"] == request["project"]
    assert digest(Path(__file__)) == binding["pythonSha256"], "Owner implementation changed"
    assert os.environ.get("CASEOPS_ENV") == "local"
    started = time.monotonic()
    progress_path = ROOT / f"owner-worker-progress-{request['workerId']}.jsonl"
    with progress_path.open("x", encoding="utf-8") as progress:
        def checkpoint(stage):
            progress.write(json.dumps({"stage": stage, "workerId": request["workerId"],
                                      "elapsedMs": round((time.monotonic() - started) * 1000)}) + "\n")
            progress.flush()
            os.fsync(progress.fileno())

        checkpoint("binding-validated")
        os.environ.update({"CASEOPS_DB_CONNECT_TIMEOUT_SECONDS": "1", "CASEOPS_DB_STATEMENT_TIMEOUT_MS": "1200",
                           "CASEOPS_DB_LOCK_TIMEOUT_MS": "800", "CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS": "3000"})
        from sqlalchemy import select, text
        from sqlalchemy.engine import make_url
        from sqlalchemy.orm import configure_mappers
        from caseops_api.db.models import Company, CompanyMembership, Matter, MatterNote, MembershipRole
        from caseops_api.db.session import get_session_factory
        from caseops_api.schemas.matters import MatterLifecycleStatusRequest
        from caseops_api.services.identity import get_session_context
        from caseops_api.services.matter_access import can_access, remove_access_grant
        from caseops_api.services.matters import transition_matter_lifecycle_status

        # Resolve every command dependency before readiness, without retaining a DB session.
        assert all(callable(value) for value in (get_session_factory, MatterLifecycleStatusRequest,
                   get_session_context, can_access, remove_access_grant, transition_matter_lifecycle_status))
        url = make_url(os.environ["CASEOPS_DATABASE_URL"])
        assert url.host == "postgres" and url.database == "caseops_mobile", "Non-fixture database refused"
        configure_mappers()
        with get_session_factory()() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            session.execute(text("SET LOCAL statement_timeout = '1200ms'"))
            session.execute(text("SET LOCAL lock_timeout = '800ms'"))
            session.execute(text("SELECT 1"))
            session.rollback()
        checkpoint("canonical-imports-ready")
        with urlopen("http://127.0.0.1:8000/api/build", timeout=0.7) as response:
            build = json.load(response)
        assert build["release_sha"] == binding["backendSha"] and build["revision"] == binding["backendRevision"]
        assert digest(Path(__file__)) == binding["pythonSha256"], "Owner implementation changed during readiness"
        checkpoint("serving-build-verified")
        proof = {"kind": "docker-owner-worker-ready", "workerId": request["workerId"],
                 "readyId": secrets.token_hex(12), "requestId": request["requestId"],
                 "bindingFile": request["bindingFile"], "bindingSha256": request["bindingSha256"],
                 **{key: binding[key] for key in ("backendSha", "backendRevision", "apiContainerId", "apiImage",
                                                 "project", "pythonSha256", "moduleSha256", "extensionSha256")},
                 "maxCommands": MAX_COMMANDS, "maxRequestBytes": MAX_REQUEST_BYTES,
                 "maxResponseBytes": MAX_RESPONSE_BYTES, "idleSeconds": WORKER_LIFETIME_SECONDS,
                 "lifetimeSeconds": WORKER_LIFETIME_SECONDS, "operationDeadlineMs": 8000,
                 "canonicalMutationImportsPreloaded": True, "databaseSessionRetained": False}
        ready_file = f"owner-ready-{request['workerId']}.json"
        with (ROOT / ready_file).open("xb") as ready:
            ready.write(json.dumps(proof).encode())
            ready.flush()
            os.fsync(ready.fileno())
        checkpoint("ready-proof-persisted")
    return {**proof, "readyFile": ready_file, "readySha256": digest(ROOT / ready_file), "commandCount": 0}


def worker_main(stream=None, output=None):
    stream = stream or sys.stdin.buffer
    output = output or sys.stdout
    started = time.monotonic()
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 30)
    startup = bounded_line(stream)
    assert startup is not None, "Owner worker disconnected before readiness"
    worker = prepare_worker(startup)
    expires = started + WORKER_LIFETIME_SECONDS
    emit_line({"type": "ready", "requestId": startup["requestId"], "workerId": worker["workerId"],
               "readyFile": worker["readyFile"], "readySha256": worker["readySha256"]}, output)
    try:
        while True:
            remaining = expires - time.monotonic()
            assert remaining > 0, "Owner worker lifetime expired"
            signal.setitimer(signal.ITIMER_REAL, min(WORKER_LIFETIME_SECONDS, remaining))
            request = bounded_line(stream)
            if request is None:
                return
            assert request.get("workerId") == worker["workerId"]
            assert request.get("readySha256") == worker["readySha256"]
            assert re.fullmatch(r"[a-f0-9]{24}", request.get("requestId", ""))
            if request.get("type") == "close":
                emit_line({"type": "closed", "workerId": worker["workerId"],
                           "readySha256": worker["readySha256"], "requestId": request["requestId"]}, output)
                return
            assert request.get("type") == "control" and request.get("operation") in OPERATIONS, "Unknown worker operation"
            assert worker["commandCount"] < MAX_COMMANDS, "Owner worker command bound"
            remaining = expires - time.monotonic()
            assert 0 < request["deadlineMs"] - time.time() * 1000 <= 8000
            assert 0 < remaining and request["deadlineMs"] / 1000 <= time.time() + remaining, "Operation exceeds worker lifetime"
            worker["commandCount"] += 1
            response = run_operation(request, worker)
            emit_line({"type": "result", "workerId": worker["workerId"], "requestId": request["requestId"],
                       "readySha256": worker["readySha256"], "commandIndex": worker["commandCount"], **response}, output)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


def main():
    raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    assert len(raw) <= MAX_REQUEST_BYTES, "Owner request bound"
    try:
        print(json.dumps(run_operation(json.loads(raw))), flush=True)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--worker"]:
            worker_main()
        else:
            assert not sys.argv[1:], "Unknown owner mode"
            main()
    except Exception as error:
        print(json.dumps({"failed": "owner-control", "errorType": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
