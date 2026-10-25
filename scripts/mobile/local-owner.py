"""Bounded fixture-only SQL owner commands using canonical product services."""

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
from urllib.request import urlopen

ROOT = Path("/fixture-state")
OPERATIONS = {"disposeMatter", "readMatterState", "revokeMatterAccess", "readNoteState"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_hashed(name, expected):
    assert re.fullmatch(r"[a-zA-Z0-9_.-]+\.json", name) and "/" not in name
    path = ROOT / name
    assert digest(path) == expected, "Owner binding evidence changed"
    return json.loads(path.read_text(encoding="utf-8"))


def expired(_signal, _frame):
    raise TimeoutError("OWNER_CONTROL_DEADLINE")


def main():
    raw = sys.stdin.buffer.read(4097)
    assert len(raw) <= 4096, "Owner request bound"
    request = json.loads(raw)
    for key in ("targetId", "runId", "requestId"):
        assert re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", request[key]), "Invalid owner identity"
    assert request["operation"] in OPERATIONS and request["marker"] == "no-paid-providers"
    assert re.fullmatch(r"[a-f0-9]{40}", request["backendSha"])
    remaining = (request["deadlineMs"] - time.time() * 1000) / 1000
    assert 0 < remaining <= 9, "Expired owner command"
    signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    binding = load_hashed(request["bindingFile"], request["bindingSha256"])
    extension = load_hashed(binding["extensionFile"], binding["extensionSha256"])
    assert binding["backendSha"] == request["backendSha"]
    assert digest(Path(__file__)) == binding["pythonSha256"], "Owner implementation changed"
    target_kind = "lifecycleMatter" if request["operation"] in ("disposeMatter", "readMatterState") else "accessMatter"
    assert extension[target_kind]["id"] == request["targetId"], "Unowned fixture target"
    assert binding["syntheticDataOnly"] and binding["environment"] == "docker-integration"
    assert os.environ.get("CASEOPS_ENV") == "local"
    # Independent SQL budgets remain below both the child and harness deadlines.
    os.environ.update({"CASEOPS_DB_CONNECT_TIMEOUT_SECONDS": "1", "CASEOPS_DB_STATEMENT_TIMEOUT_MS": "1200",
                       "CASEOPS_DB_LOCK_TIMEOUT_MS": "800", "CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS": "3000"})
    from sqlalchemy import select, text
    from sqlalchemy.engine import make_url
    from caseops_api.db.models import Company, CompanyMembership, Matter, MatterNote, MembershipRole
    from caseops_api.db.session import get_session_factory
    from caseops_api.schemas.matters import MatterLifecycleStatusRequest
    from caseops_api.services.identity import get_session_context
    from caseops_api.services.matter_access import can_access, remove_access_grant
    from caseops_api.services.matters import transition_matter_lifecycle_status

    url = make_url(os.environ["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile", "Non-fixture database refused"
    with urlopen("http://127.0.0.1:8000/api/build", timeout=0.7) as response:
        build = json.load(response)
    assert build["release_sha"] == request["backendSha"] and build["revision"] == binding["backendRevision"]
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
        owner_context = get_session_context(session, owner.id)
        if request["operation"] == "disposeMatter":
            assert target.status in ("intake", "active", "on_hold") and target.is_active, "Fresh operational target required; never reopen"
            transition_matter_lifecycle_status(session, context=owner_context, matter_id=target.id,
                payload=MatterLifecycleStatusRequest(to_status="disposed", expected_from_status=target.status,
                    expected_updated_at=target.updated_at, reason="Dedicated native stale-editor acceptance command"))
        elif request["operation"] == "revokeMatterAccess":
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
    evidence = {"kind": "docker-owner-control", **{key: request[key] for key in (
        "operation", "targetId", "runId", "backendSha", "requestId")},
        "backendRevision": build["revision"], "project": binding["project"],
        "apiContainerId": binding["apiContainerId"], "apiImage": binding["apiImage"],
        "extensionSha256": binding["extensionSha256"], "transport": "canonical-product-services-real-postgresql",
        "sqlStatementTimeoutMs": 1200, "sqlLockTimeoutMs": 800, "hardDeadlineMs": request["deadlineMs"],
        "result": result}
    payload = json.dumps(evidence).encode()
    assert len(payload) <= 65536
    filename = f"owner-evidence-{request['requestId']}.json"
    with (ROOT / filename).open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({"evidenceFile": filename, "result": result}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"failed": "owner-control", "errorType": type(error).__name__}), file=sys.stderr)
        sys.exit(1)
