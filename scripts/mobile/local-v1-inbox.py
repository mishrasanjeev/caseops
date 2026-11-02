"""One explicitly enabled isolated in_app fixture; never a public API/worker.

The hearing is created by the normal HTTP producer. This console adapter only
waits for its actual due intent and invokes the existing canonical delivery and
legacy projector once. No receipt row or notification body is fabricated here.
"""
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
SOURCE = re.compile(r"[a-f0-9]{40}\Z")
LIMITS = {"phaseSeconds": 90, "observerStatements": 20, "polls": 4, "intervalSeconds": 15,
          "workerExecutions": 1, "publicBytes": 262144}
MARKER = "no-paid-providers"
METADATA = ("st_dev", "st_ino", "st_uid", "st_gid", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def ancestor_metadata(path):
    result = []
    for parent in reversed(path.parents):
        value = os.lstat(parent)
        assert stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode), "V1_INBOX_CANONICAL_NAMESPACE_REQUIRED"
        result.append((str(parent), tuple(getattr(value, key) for key in METADATA)))
    return result


def public_bytes(reference, root):
    path = Path(reference["path"])
    assert path.is_absolute() and path == path.resolve() and root in path.parents
    ancestors = ancestor_metadata(path)
    assert any(name == str(root) for name, _metadata in ancestors), "V1_INBOX_OWNED_ROOT_REQUIRED"
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before, named = os.fstat(descriptor), os.lstat(path)
        keys = METADATA
        assert stat.S_ISREG(before.st_mode) and not stat.S_ISLNK(named.st_mode)
        assert all(getattr(before, key) == getattr(named, key) for key in keys)
        assert 0 < before.st_size <= LIMITS["publicBytes"]
        chunks, size = [], 0
        while size <= LIMITS["publicBytes"]:
            block = os.read(descriptor, min(65536, LIMITS["publicBytes"] + 1 - size))
            if not block:
                break
            chunks.append(block)
            size += len(block)
        after, final = os.fstat(descriptor), os.lstat(path)
        assert size == before.st_size and size <= LIMITS["publicBytes"]
        assert not stat.S_ISLNK(final.st_mode) and all(getattr(before, key) == getattr(after, key) == getattr(final, key) for key in keys)
        data = b"".join(chunks)
        assert hashlib.sha256(data).hexdigest() == reference["sha256"]
        assert path.resolve() == path and ancestor_metadata(path) == ancestors, "V1_INBOX_CANONICAL_NAMESPACE_REQUIRED"
        return data
    finally:
        os.close(descriptor)


def public_json(reference, root):
    try:
        return json.loads(public_bytes(reference, root).decode("utf-8", "strict"))
    except (ValueError, UnicodeError):
        raise ValueError("V1_INBOX_PUBLIC_JSON_REQUIRED") from None


def validate_request(request, environment, now):
    # Fail before file, database, API or import work when not explicitly enabled.
    assert environment.get("CASEOPS_MOBILE_V1_INBOX_FIXTURE") == "1", "V1_INBOX_DISABLED"
    assert environment.get("CASEOPS_ENV") == "local"
    assert not any(environment.get(key) for key in ("K_SERVICE", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert request["readyForLive"] is True and request["preparedOnly"] is False
    assert request["environment"] == "docker-integration" and request["syntheticDataOnly"] is True
    assert request["noPaidMarker"] == MARKER and request["manualReceiptInsertion"] is False
    assert SOURCE.fullmatch(request["sourceSha"]) and environment.get("CASEOPS_RELEASE_SHA") == request["sourceSha"]
    assert re.fullmatch(r"v1-[a-f0-9-]{16,80}", request["runId"])
    for key in ("companyId", "membershipId", "matterId", "hearingId"):
        assert UUID.fullmatch(request[key])
    assert type(request["phaseStartedMilliseconds"]) is int
    started = request["phaseStartedMilliseconds"] / 1000
    assert 0 <= now() - started < LIMITS["phaseSeconds"], "V1_INBOX_SHARED_PHASE_DEADLINE"
    hearing = request["hearingAcknowledgement"]
    assert hearing["method"] == "POST" and hearing["status"] == 200
    assert hearing["route"] == f"/api/matters/{request['matterId']}/hearings"
    assert hearing["value"]["id"] == request["hearingId"] and hearing["value"]["matter_id"] == request["matterId"]
    body = hearing["body"]
    assert body["reminder_channels"] == ["in_app"] and body["reminder_offsets_hours"] == [1]
    assert body["reminder_recipient_membership_ids"] == [request["membershipId"]]
    assert body["notification_critical"] is False and body["timezone"] == "UTC" and body["time_status"] == "exact"
    assert body["hearing_on"] == hearing["value"]["hearing_on"] and body["hearing_time"] == hearing["value"]["hearing_time"]
    assert hearing["value"]["reminder_policy"]["channels"] == ["in_app"]
    assert hearing["value"]["reminder_policy"]["critical"] is False
    scheduled = datetime.fromisoformat(body["hearing_on"] + "T" + body["hearing_time"]).replace(tzinfo=UTC) - timedelta(hours=1)
    assert started < scheduled.timestamp() <= started + 70
    return started + LIMITS["phaseSeconds"], scheduled


def run_inbox_worker(request, *, environment=None, factory=None, claim=None, persist=None, now=time.time, sleep=time.sleep):
    environment = os.environ if environment is None else environment
    deadline, scheduled = validate_request(request, environment, now)
    assert callable(claim) and callable(persist)
    claim("inbox-console:" + request["runId"])
    observed, worker_started = 0, False
    def charged():
        nonlocal observed
        assert now() < deadline, "V1_INBOX_SHARED_PHASE_DEADLINE"
        observed += 1
        assert observed <= LIMITS["observerStatements"], "V1_INBOX_OBSERVER_BOUND"
        persist({"type": "v1_inbox_observer_charged", "sequence": observed})
    runtime, failed = None, False
    try:
        runtime = (factory or postgres_runtime)(request, charged, deadline)
        snapshot = None
        for index in range(LIMITS["polls"]):
            assert now() < deadline, "V1_INBOX_SHARED_PHASE_DEADLINE"
            snapshot = runtime.observe(False)
            assert snapshot["companyId"] == request["companyId"] and snapshot["membershipId"] == request["membershipId"]
            assert snapshot["hearingId"] == request["hearingId"] and snapshot["channel"] == "in_app"
            assert snapshot["scheduledFor"] == scheduled.isoformat()
            assert snapshot["status"] == "queued" and snapshot["notificationId"] is None and snapshot["attempts"] == 0
            if now() >= scheduled.timestamp():
                break
            assert index + 1 < LIMITS["polls"], "V1_INBOX_DUE_NOT_OBSERVED"
            # observe() closes its read-only transaction before any wait.
            sleep(min(LIMITS["intervalSeconds"], scheduled.timestamp() - now(), deadline - now()))
        assert snapshot is not None and now() >= scheduled.timestamp(), "V1_INBOX_DUE_NOT_OBSERVED"
        claim("inbox-canonical-worker:" + request["runId"])
        worker_started = True
        persist({"type": "v1_inbox_worker_started", "intentId": snapshot["intentId"], "automaticRetry": False})
        result = runtime.deliver(snapshot["intentId"])
        assert result["delivered"] is True and result["externalCalls"] == 0
        current = runtime.observe(True)
        for key in ("intentId", "companyId", "membershipId", "hearingId", "channel", "scheduledFor"):
            assert current[key] == snapshot[key]
        assert current["status"] == "delivered"
        assert current["attempts"] == 1
        assert current["notificationCompanyId"] == request["companyId"] and current["notificationMembershipId"] == request["membershipId"] and current["notificationMatterId"] == request["matterId"]
        assert UUID.fullmatch(current["notificationId"]) and current["deliveredAt"] is not None
        assert now() < deadline, "V1_INBOX_SHARED_PHASE_DEADLINE"
        receipt = {"schemaVersion": 1, "kind": "actual-canonical-in-app-worker", "observed": True, "sourceSha": request["sourceSha"],
                   "runId": request["runId"], "companyId": request["companyId"], "membershipId": request["membershipId"],
                   "matterId": request["matterId"], "hearingId": request["hearingId"], "intentId": current["intentId"],
                   "notificationId": current["notificationId"], "observerStatements": observed, "workerExecutions": 1,
                   "externalCalls": 0, "manualReceiptInsertion": False, "automaticRetry": False, "mutationUncertain": False}
    except Exception:
        failed = True
        persist({"type": "v1_inbox_worker_failed", "observed": False, "workerStarted": worker_started,
                 "mutationUncertain": worker_started, "observerStatements": observed, "automaticRetry": False})
        raise RuntimeError("V1_INBOX_WORKER_INCOMPLETE_NO_REPLAY") from None
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception:
                persist({"type": "v1_inbox_cleanup_failed", "observed": False, "workerStarted": worker_started, "automaticRetry": False})
                if not failed:
                    raise RuntimeError("V1_INBOX_CLEANUP_UNVERIFIED_NO_REPLAY") from None
    persist({"type": "v1_inbox_worker_completed", **receipt})
    return receipt


def inbox_intent_statement(request):
    from sqlalchemy import select
    from caseops_api.db.models import InAppNotification, NotificationDeliveryIntent
    return select(NotificationDeliveryIntent.id, NotificationDeliveryIntent.company_id,
        NotificationDeliveryIntent.recipient_membership_id, NotificationDeliveryIntent.schedule_source_id,
        NotificationDeliveryIntent.channel, NotificationDeliveryIntent.scheduled_for, NotificationDeliveryIntent.status,
        NotificationDeliveryIntent.in_app_notification_id, NotificationDeliveryIntent.delivered_at, NotificationDeliveryIntent.attempts,
        InAppNotification.company_id, InAppNotification.recipient_membership_id, InAppNotification.matter_id).outerjoin(
        InAppNotification, InAppNotification.id == NotificationDeliveryIntent.in_app_notification_id).where(
        NotificationDeliveryIntent.company_id == request["companyId"], NotificationDeliveryIntent.schedule_source_type == "matter_hearing",
        NotificationDeliveryIntent.schedule_source_id == request["hearingId"], NotificationDeliveryIntent.recipient_membership_id == request["membershipId"],
        NotificationDeliveryIntent.channel == "in_app").limit(2)


def postgres_runtime(request, charged, deadline):
    from sqlalchemy import create_engine, event, func, select
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from caseops_api.core.automated_test_context import paid_providers_blocked_for_request, reset_automated_test_request, set_automated_test_request
    from caseops_api.core.settings import get_settings
    from caseops_api.services.notification_delivery import process_notification_delivery_intent, project_linked_hearing_reminder_intent
    from types import ModuleType
    module_path = Path(__file__).with_name("local-v1-controls.py")
    assert request["managerEvidence"]["path"] == str(module_path)
    held_manager = public_bytes(request["managerEvidence"], module_path.parent)
    controls = ModuleType("v1_inbox_readonly_guard")
    controls.__file__ = str(module_path)
    exec(compile(held_manager, str(module_path), "exec"), controls.__dict__)
    url = make_url(os.environ["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile"
    assert get_settings().notification_external_delivery_enabled is False
    expected = request["postgresIdentity"]
    assert expected["observed"] is True and expected["readOnly"] is True and expected["database"] == "caseops_mobile"
    engine = create_engine(url, connect_args={"connect_timeout": 1, "options": "-c statement_timeout=1200 -c lock_timeout=800"})
    mode = "initializing"
    def before(_connection, _cursor, sql, _parameters, context, _many):
        if mode == "worker":
            assert time.time() < deadline
            return
        charged()
        node = context.compiled.statement if context.compiled else None
        if mode == "initializing" and node is None:
            assert sql.strip().lower() in ("select pg_catalog.version()", "select current_schema()", "show transaction isolation level", "show standard_conforming_strings")
        elif mode == "readonly-setup":
            assert sql == "SET TRANSACTION READ ONLY"
        else:
            controls.require_readonly_statement(node)
    event.listen(engine, "before_cursor_execute", before)
    def observe(after):
        nonlocal mode
        with engine.connect() as connection:
            mode = "readonly-setup"
            with connection.begin():
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                mode = "read"
                system = func.pg_control_system().table_valued("system_identifier")
                identity = connection.execute(select(system.c.system_identifier, func.pg_postmaster_start_time(), func.current_database())).one()
                assert str(identity[0]) == expected["systemIdentifier"] and identity[1].astimezone(UTC).isoformat() == expected["startedAt"] and identity[2] == expected["database"]
                item = connection.execute(inbox_intent_statement(request)).all()
                assert len(item) == 1
                row = item[0]
                return {"intentId": row[0], "companyId": row[1], "membershipId": row[2], "hearingId": row[3], "channel": row[4],
                        "scheduledFor": row[5].astimezone(UTC).isoformat(), "status": row[6], "notificationId": row[7], "deliveredAt": row[8].astimezone(UTC).isoformat() if row[8] else None,
                        "attempts": row[9], "notificationCompanyId": row[10], "notificationMembershipId": row[11], "notificationMatterId": row[12]}
    def deliver(identity):
        nonlocal mode
        mode = "worker"
        token = set_automated_test_request(MARKER)
        try:
            assert paid_providers_blocked_for_request() is True
            with Session(engine) as session:
                result = process_notification_delivery_intent(session, intent_id=identity, company_id=request["companyId"])
                assert result.delivered is True and result.external_calls == 0
                project_linked_hearing_reminder_intent(session, intent_id=identity)
                session.commit()
                return {"delivered": result.delivered, "externalCalls": result.external_calls}
        finally:
            reset_automated_test_request(token)
            mode = "read"
    return type("Runtime", (), {"observe": staticmethod(observe), "deliver": staticmethod(deliver), "close": staticmethod(engine.dispose)})()


def main():
    import sys
    # The operator supplies an already source/installed/API+web-admitted request.
    # This switch is still checked before even opening its public descriptor.
    assert os.environ.get("CASEOPS_MOBILE_V1_INBOX_FIXTURE") == "1", "V1_INBOX_DISABLED"
    assert len(sys.argv) == 4
    root = Path("/fixture-state")
    request_path = Path(sys.argv[1])
    assert request_path.parent == root and re.fullmatch(r"v1-inbox-worker-request-v1-[a-f0-9-]{16,80}\.json", request_path.name)
    request = public_json({"path": sys.argv[1], "sha256": sys.argv[2]}, root)
    validate_request(request, os.environ, time.time)
    output = Path(sys.argv[3])
    assert output.parent == root and output.name == "v1-inbox-worker-" + request["runId"] + ".json"
    journal_path = root / ("v1-inbox-worker-" + request["runId"] + ".jsonl")
    journal = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    written = 0
    def claim(identity):
        name = "v1-inbox-claim-" + hashlib.sha256(identity.encode()).hexdigest() + ".json"
        descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            body, offset = json.dumps({"identity": identity}).encode(), 0
            while offset < len(body):
                count = os.write(descriptor, body[offset:])
                assert count > 0
                offset += count
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    def persist(value):
        nonlocal written
        body = (json.dumps(value, sort_keys=True) + "\n").encode()
        assert written + len(body) <= 65536
        before, named = os.fstat(journal), os.lstat(journal_path)
        assert stat.S_ISREG(named.st_mode) and not stat.S_ISLNK(named.st_mode)
        assert (before.st_dev, before.st_ino, before.st_nlink) == (named.st_dev, named.st_ino, 1)
        offset = 0
        while offset < len(body):
            count = os.write(journal, body[offset:])
            assert count > 0
            offset += count
        written += len(body)
        os.fsync(journal)
    receipt = None
    try:
        receipt = run_inbox_worker(request, claim=claim, persist=persist)
    finally:
        os.close(journal)
    # Exclusive publication happens only after runtime and held journal close.
    with output.open("xb") as stream:
        os.fchmod(stream.fileno(), 0o600)
        stream.write((json.dumps(receipt, sort_keys=True) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import sys
        print("V1_INBOX_FIXTURE_REFUSED_OR_UNKNOWN_NO_REPLAY", file=sys.stderr)
        raise SystemExit(1) from None
