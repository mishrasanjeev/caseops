"""One nonbillable entitlement fixture for a fresh, isolated native V1 tenant.

This is not a product endpoint. The host must first bind normal bootstrap,
owner MFA/identity, immutable source, owned Compose/network/volume and the API
and PostgreSQL observations. The worker independently checks the exact server,
owner and empty tenant under the Company lock. It never adopts an existing row.
"""
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

UUID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z")
MARKER = "no-paid-providers"
MAX_SECONDS = 30
ENTITLEMENTS = {"ip_workspace": True, "ip_rule_governance": True}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_request(q, environment, observed):
    assert environment.get("CASEOPS_MOBILE_V1_ENTITLEMENTS_FIXTURE") == "1", "V1_ENTITLEMENTS_DISABLED"
    assert environment.get("CASEOPS_ENV") == "local" and environment.get("CASEOPS_LLM_PROVIDER") == "mock"
    assert not any(environment.get(k) for k in ("K_SERVICE", "K_CONFIGURATION", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert set(q) == {"schemaVersion", "kind", "readyForLive", "preparedOnly", "sourceSha", "runId",
                      "companyId", "companySlug", "membershipId", "userId", "subscriptionId", "noPaidMarker",
                      "productionAccessed", "automaticRetry", "startedAt", "expiresAt", "profileExpiresAt",
                      "bootstrapAcknowledgement", "ownerIdentity", "mfaAcknowledgement", "postgresIdentity"}
    assert type(q["schemaVersion"]) is int and q["schemaVersion"] == 1 and q["kind"] == "isolated-native-v1-entitlements"
    assert q["readyForLive"] is True and q["preparedOnly"] is False
    assert q["noPaidMarker"] == MARKER and q["productionAccessed"] is False and q["automaticRetry"] is False
    assert re.fullmatch(r"[a-f0-9]{40}", q["sourceSha"]) and environment.get("CASEOPS_RELEASE_SHA") == q["sourceSha"]
    assert re.fullmatch(r"v1-[a-f0-9]{24}", q["runId"])
    assert re.fullmatch(r"test-mobile-v1-[a-f0-9]{12}", q["companySlug"])
    for key in ("companyId", "membershipId", "userId", "subscriptionId"):
        assert isinstance(q[key], str) and UUID.fullmatch(q[key])
    assert len({q[key] for key in ("companyId", "membershipId", "userId", "subscriptionId")}) == 4
    assert type(q["startedAt"]) in (int, float) and type(q["expiresAt"]) in (int, float)
    assert q["startedAt"] <= observed < q["expiresAt"] <= q["startedAt"] + MAX_SECONDS
    expiry = datetime.fromisoformat(q["profileExpiresAt"])
    assert expiry.tzinfo is not None and expiry.utcoffset().total_seconds() == 0
    assert 0 < expiry.timestamp() - observed <= 14400
    for prefix in ("CASEOPS_IP_WORKSPACE", "CASEOPS_IP_RULE_GOVERNANCE"):
        assert environment.get(prefix + "_ENABLED") == "true"
        assert environment.get(prefix + "_ROLLOUT_EXPIRES_AT") == q["profileExpiresAt"]
    assert environment.get("CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS") == "test-legal,test-mobile-other," + q["companySlug"]
    for key, method, route in (("bootstrapAcknowledgement", "POST", "/api/bootstrap/company"),
                               ("ownerIdentity", "GET", "/api/auth/me"),
                               ("mfaAcknowledgement", "POST", "/api/auth/mfa/step-up")):
        ack = q[key]
        base = {"method", "route", "status", "releaseSha", "requestId"}
        actor = {"companyId", "membershipId", "userId", "companySlug", "role", "membershipActive", "userActive"}
        extra = actor | ({"companyType"} if key == "bootstrapAcknowledgement" else {"capabilities"})
        if key == "mfaAcknowledgement":
            extra = {"verified", "companyId", "membershipId", "userId"}
        assert set(ack) == base | extra, "V1_ENTITLEMENTS_EXACT_ACK_PROJECTION_REQUIRED"
        assert ack["method"] == method and ack["route"] == route and ack["status"] == 200
        assert ack["releaseSha"] == q["sourceSha"] and re.fullmatch(r"[A-Za-z0-9:_-]{1,160}", ack["requestId"])
        assert not any(name in ack for name in ("access_token", "refresh_token", "password", "totp_secret", "code", "authorization"))
    for key in ("bootstrapAcknowledgement", "ownerIdentity"):
        ack = q[key]
        assert all(ack[field] == q[field] for field in ("companyId", "membershipId", "userId", "companySlug"))
        assert ack["role"] == "owner" and ack["membershipActive"] is True and ack["userActive"] is True
    capabilities = q["ownerIdentity"]["capabilities"]
    assert isinstance(capabilities, list) and 0 < len(capabilities) <= 512
    assert all(isinstance(value, str) and re.fullmatch(r"[a-z0-9_:.-]{1,100}", value) for value in capabilities)
    assert "company:manage_users" in capabilities
    assert q["bootstrapAcknowledgement"]["companyType"] == "law_firm"
    assert all(q["mfaAcknowledgement"][key] == q[key] for key in ("companyId", "membershipId", "userId"))
    assert q["mfaAcknowledgement"]["verified"] is True
    pg = q["postgresIdentity"]
    assert set(pg) == {"observed", "readOnly", "database", "systemIdentifier", "startedAt"}
    assert pg["observed"] is True and pg["readOnly"] is True and pg["database"] == "caseops_mobile"
    assert re.fullmatch(r"[1-9][0-9]{0,24}", pg["systemIdentifier"])
    assert datetime.fromisoformat(pg["startedAt"]).tzinfo is not None
    return q["expiresAt"]


def subscription_values(q, stamp):
    return {"id": q["subscriptionId"], "company_id": q["companyId"], "billing_account_id": None,
            "plan_version_id": None, "status": "manual_active", "segment": "law_firm", "billing_interval": "month",
            "current_period_start": None, "current_period_end": None, "trial_start": None, "trial_end": None,
            "cancel_at_period_end": False, "cancelled_at": None, "grace_until": None, "provider": None,
            "provider_customer_id": None, "provider_subscription_id": None, "provider_mandate_id": None,
            "source": "mobile_v1_fixture", "externally_billable": False, "entitlement_overrides_json": dict(ENTITLEMENTS),
            "metadata_json": {"synthetic_native_v1_run_id": q["runId"], "nonbillable": True},
            "created_at": stamp, "updated_at": stamp}


def run_grant(q, *, environment=None, now=time.time, claim, persist, factory=None):
    environment = os.environ if environment is None else environment
    deadline = validate_request(q, environment, now())
    # A company can receive this fixture only once, even across different runs.
    claim("v1-entitlements-company:" + q["companyId"])
    runtime = None
    failure = None
    persist({"type": "v1_entitlements_started", "sourceSha": q["sourceSha"], "runId": q["runId"],
             "requestSha256": digest(q), "automaticRetry": False})
    try:
        assert now() < deadline, "V1_ENTITLEMENTS_DEADLINE"
        runtime = (factory or postgres_runtime)(q, environment, deadline, now)
        result = runtime.grant()
        assert now() < deadline, "V1_ENTITLEMENTS_DEADLINE"
        assert set(result) == {"committed", "subscriptionId", "businessInserts", "businessUpdates", "businessDeletes",
                              "postgresIdentity", "subscriptionSha256", "outboxBefore", "outboxAfter", "sqlStatements",
                              "postcommitReadOnlyVerified"}, "V1_ENTITLEMENTS_EXACT_RUNTIME_RESULT_REQUIRED"
        assert result["committed"] is True and result["subscriptionId"] == q["subscriptionId"]
        assert result["businessInserts"] == 1 and result["businessUpdates"] == result["businessDeletes"] == 0
        assert result["postgresIdentity"] == q["postgresIdentity"] and result["postcommitReadOnlyVerified"] is True
        assert type(result["sqlStatements"]) is int and 1 <= result["sqlStatements"] <= 32
        assert re.fullmatch(r"[a-f0-9]{64}", result["subscriptionSha256"])
        assert result["outboxBefore"] == result["outboxAfter"]
        assert set(result["outboxBefore"]) == {"rows", "sha256"}
        assert type(result["outboxBefore"]["rows"]) is int and 0 <= result["outboxBefore"]["rows"] <= 128
        assert re.fullmatch(r"[a-f0-9]{64}", result["outboxBefore"]["sha256"])
        receipt = {"kind": "actual-isolated-native-v1-entitlements", "observed": True, "sourceSha": q["sourceSha"],
                   "runId": q["runId"], "companyId": q["companyId"], "membershipId": q["membershipId"],
                   "subscriptionId": q["subscriptionId"], "entitlements": dict(ENTITLEMENTS),
                   "externallyBillable": False, "directDatabaseWrites": True, "automaticRetry": False,
                   "productionAccessed": False, "normalReadinessReadback": "pending", **result}
        persist({"type": "v1_entitlements_committed", "receiptSha256": digest(receipt), "automaticRetry": False})
        return receipt
    except Exception as error:
        failure = error
        try:
            persist({"type": "v1_entitlements_incomplete", "outcomeUnknown": True, "automaticRetry": False})
        except Exception as diagnostic:
            failure = ExceptionGroup("V1_ENTITLEMENTS_BODY_AND_DIAGNOSTIC_FAILED", [error, diagnostic])
            raise failure
        raise
    finally:
        if runtime is not None:
            try:
                runtime.close()
            except Exception as cleanup:
                if failure is not None:
                    raise ExceptionGroup("V1_ENTITLEMENTS_BODY_AND_CLEANUP_FAILED", [failure, cleanup])
                raise


def postgres_runtime(q, environment, deadline, now):
    from sqlalchemy import create_engine, event, func, insert, select, text
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session
    from caseops_api.db.models import (BillingSubscription, Company, CompanyMembership, DomainOutboxEvent,
                                      IpRuleSet, IpWorkspaceConfiguration, LegalWorkingCalendar, User)
    url = make_url(environment["CASEOPS_DATABASE_URL"])
    assert url.host == "postgres" and url.database == "caseops_mobile" and url.username == "caseops"
    engine = create_engine(url, connect_args={"connect_timeout": 1, "options": "-c statement_timeout=3000 -c lock_timeout=1000"})
    statements = 0
    inserts = 0

    def observe(_connection, _cursor, sql, _parameters, context, _many):
        nonlocal statements, inserts
        statements += 1
        assert now() < deadline and statements <= 32, "V1_ENTITLEMENTS_SQL_BOUND"
        node = context.compiled.statement if context.compiled else None
        if getattr(node, "is_insert", False):
            assert node.table.name == "billing_subscriptions" and inserts == 0, "V1_ENTITLEMENTS_SINGLE_INSERT_ONLY"
            inserts += 1
        else:
            assert not getattr(node, "is_update", False) and not getattr(node, "is_delete", False)
            assert getattr(node, "is_select", False) or sql.strip().lower() in {
                "select pg_catalog.version()", "select current_schema()", "show transaction isolation level",
                "show standard_conforming_strings", "set transaction read only"}, "V1_ENTITLEMENTS_UNREVIEWED_SQL"

    event.listen(engine, "before_cursor_execute", observe)

    def database(session, *, readonly):
        system = func.pg_control_system().table_valued("system_identifier")
        row = session.execute(select(system.c.system_identifier, func.pg_postmaster_start_time(), func.current_database(),
                                     func.current_setting("transaction_read_only"))).one()
        assert row[3] == ("on" if readonly else "off"), "V1_ENTITLEMENTS_TRANSACTION_MODE_REQUIRED"
        actual = {"observed": True, "readOnly": readonly, "database": row[2], "systemIdentifier": str(row[0]),
                  "startedAt": row[1].astimezone(UTC).isoformat()}
        assert {**actual, "readOnly": True} == q["postgresIdentity"], "V1_ENTITLEMENTS_WRONG_DATABASE"
        return actual

    def outbox(session):
        rows = session.execute(select(*DomainOutboxEvent.__table__.columns).where(
            DomainOutboxEvent.company_id == q["companyId"]).order_by(DomainOutboxEvent.id).limit(129)).all()
        assert len(rows) <= 128
        values = [list(row) for row in rows]
        assert len(canonical(values)) <= 262144
        return {"rows": len(rows), "sha256": digest(values)}

    def grant():
        stamp = datetime.fromtimestamp(now(), UTC)
        values = subscription_values(q, stamp)
        assert set(values) == set(BillingSubscription.__table__.columns.keys()), "V1_ENTITLEMENTS_MODEL_DRIFT"
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            pg = database(session, readonly=True)
        with Session(engine) as session, session.begin():
            assert session.bind.dialect.name == "postgresql"
            assert {**database(session, readonly=False), "readOnly": True} == pg
            company = session.execute(select(Company.slug, Company.tenant_key, Company.company_type,
                Company.is_active, Company.created_at).where(Company.id == q["companyId"]).with_for_update()).one()
            assert company[:4] == (q["companySlug"], q["companySlug"], "law_firm", True)
            assert company[4].tzinfo is not None and 0 <= now() - company[4].timestamp() < 300, "V1_ENTITLEMENTS_FRESH_COMPANY_REQUIRED"
            member = session.execute(select(CompanyMembership.role, CompanyMembership.is_active, User.is_active).join(
                User, User.id == CompanyMembership.user_id).where(CompanyMembership.id == q["membershipId"],
                CompanyMembership.company_id == q["companyId"], CompanyMembership.user_id == q["userId"])
                .with_for_update(of=[CompanyMembership, User])).one()
            assert member == ("owner", True, True), "V1_ENTITLEMENTS_CURRENT_OWNER_REQUIRED"
            assert session.scalar(select(BillingSubscription.id).where(
                (BillingSubscription.company_id == q["companyId"]) | (BillingSubscription.id == q["subscriptionId"])).limit(1)) is None
            for model in (IpWorkspaceConfiguration, IpRuleSet, LegalWorkingCalendar):
                assert session.scalar(select(model.id).where(model.company_id == q["companyId"]).limit(1)) is None, "V1_ENTITLEMENTS_EMPTY_GOVERNED_TENANT_REQUIRED"
            before = outbox(session)
            session.execute(insert(BillingSubscription.__table__).values(**values))
            row = session.execute(select(*BillingSubscription.__table__.columns).where(
                BillingSubscription.company_id == q["companyId"]).limit(2)).mappings().all()
            assert len(row) == 1 and dict(row[0]) == values, "V1_ENTITLEMENTS_EXACT_SINGLETON_REQUIRED"
            assert outbox(session) == before and now() < deadline
        # The insert has committed. Any later failure remains incomplete; the
        # durable company claim stays spent and neither compensation nor retry runs.
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            assert database(session, readonly=True) == pg
            rows = session.execute(select(*BillingSubscription.__table__.columns).where(
                BillingSubscription.company_id == q["companyId"]).limit(2)).mappings().all()
            assert len(rows) == 1 and dict(rows[0]) == values
            assert outbox(session) == before
        return {"committed": True, "subscriptionId": q["subscriptionId"], "businessInserts": inserts,
                "businessUpdates": 0, "businessDeletes": 0, "postgresIdentity": pg,
                "subscriptionSha256": digest(values), "outboxBefore": before, "outboxAfter": before,
                "sqlStatements": statements, "postcommitReadOnlyVerified": True}

    return type("Runtime", (), {"grant": staticmethod(grant), "close": staticmethod(engine.dispose)})()


METADATA = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")


def read_request(file, expected, root):
    assert file.parent == root and file.resolve() == file and root.resolve() == root
    assert re.fullmatch(r"[a-f0-9]{64}", expected)
    directory = root.lstat()
    assert stat.S_ISDIR(directory.st_mode) and directory.st_uid == os.getuid()
    assert stat.S_IMODE(directory.st_mode) == 0o700
    def namespace():
        result = []
        for parent in file.parents:
            value = parent.lstat()
            assert stat.S_ISDIR(value.st_mode) and not stat.S_ISLNK(value.st_mode)
            result.append((str(parent), value.st_dev, value.st_ino, value.st_uid, value.st_gid, value.st_mode))
        return result
    parents = namespace()
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        frame = lambda value: tuple(getattr(value, key) for key in METADATA)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 < before.st_size <= 65536
        assert before.st_uid == os.getuid() and stat.S_IMODE(before.st_mode) == 0o600
        assert frame(before) == frame(file.lstat())
        parts, size = [], 0
        while size <= 65536:
            block = os.read(fd, min(65536, 65537 - size))
            if not block:
                break
            parts.append(block); size += len(block)
        raw = b"".join(parts)
        assert len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == expected
        assert frame(before) == frame(os.fstat(fd)) == frame(file.lstat()) and namespace() == parents
        def unique(items):
            assert len(items) == len({key for key, _ in items}), "V1_ENTITLEMENTS_DUPLICATE_JSON_KEY"
            return dict(items)
        return json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=unique)
    finally:
        os.close(fd)


def write_new(file, value):
    raw = canonical(value) + b"\n"
    assert len(raw) <= 65536
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        os.fchmod(fd, 0o600)
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid()
        pending = memoryview(raw)
        while pending:
            count = os.write(fd, pending); assert 0 < count <= len(pending); pending = pending[count:]
        os.fsync(fd)
        after, named = os.fstat(fd), file.lstat()
        assert after.st_size == len(raw) and stat.S_IMODE(after.st_mode) == 0o600
        assert all(getattr(after, key) == getattr(named, key) for key in METADATA)
        assert all(getattr(before, key) == getattr(after, key) for key in METADATA[:6])
    finally:
        os.close(fd)
    return {"path": str(file), "sha256": hashlib.sha256(raw).hexdigest()}


def main():
    import sys
    assert os.environ.get("CASEOPS_MOBILE_V1_ENTITLEMENTS_FIXTURE") == "1", "V1_ENTITLEMENTS_DISABLED"
    assert os.environ.get("CASEOPS_ENV") == "local" and os.environ.get("CASEOPS_LLM_PROVIDER") == "mock"
    assert not any(os.environ.get(k) for k in ("K_SERVICE", "K_CONFIGURATION", "K_REVISION", "CLOUD_RUN_JOB", "GAE_ENV", "FUNCTION_TARGET"))
    assert len(sys.argv) == 4
    root = Path("/fixture-state")
    request = Path(sys.argv[1])
    assert re.fullmatch(r"v1-entitlements-request-v1-[a-f0-9]{24}\.json", request.name)
    q = read_request(request, sys.argv[2], root)
    validate_request(q, os.environ, time.time())
    assert request.name == "v1-entitlements-request-" + q["runId"] + ".json"
    output = Path(sys.argv[3])
    assert output.parent == root and output.name == "v1-entitlements-" + q["runId"] + ".json"
    journal = root / ("v1-entitlements-" + q["runId"] + ".jsonl")
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    events, size = 0, 0
    def persist(value):
        nonlocal events, size
        raw = canonical(value) + b"\n"; events += 1; size += len(raw)
        assert events <= 8 and size <= 16384
        view = memoryview(raw)
        while view:
            count = os.write(fd, view); assert 0 < count <= len(view); view = view[count:]
        os.fsync(fd)
    def claim(identity):
        assert identity == "v1-entitlements-company:" + q["companyId"]
        write_new(root / ("v1-entitlements-company-" + q["companyId"] + ".claim.json"),
                  {"requestSha256": digest(q), "runId": q["runId"], "sourceSha": q["sourceSha"], "automaticRetry": False})
    try:
        receipt = run_grant(q, claim=claim, persist=persist)
        proof = write_new(output, receipt)
        print(json.dumps({"receipt": proof, "normalReadinessReadback": "pending", "automaticRetry": False}))
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import sys
        print("V1_ENTITLEMENTS_REFUSED_OR_INCOMPLETE", file=sys.stderr)
        raise SystemExit(1)
