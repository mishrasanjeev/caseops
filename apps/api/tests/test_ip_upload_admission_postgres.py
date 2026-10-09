"""IP uploads publish only after transaction-free scan/storage and fresh admission."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from threading import Barrier, Event, local

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    DocumentProcessingJob,
    IpDocketRecord,
    IpDocument,
    IpDocumentLink,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    MatterAccessGrant,
    PrivateProjectionEvent,
    User,
)
from caseops_api.schemas.employees import EmployeeUpdateRequest
from caseops_api.schemas.ip_documents import (
    IpDocumentLinkTarget,
    IpDocumentNewVersionMetadata,
    IpDocumentUploadMetadata,
)
from caseops_api.services import (
    document_storage,
    employees,
    ip_document_workflow,
    matters,
    storage_governance,
    virus_scan,
)
from caseops_api.services.ip_lifecycle import transition_ip_docket_lifecycle
from tests.test_ip_document_workflow_postgres import _seed_document_source
from tests.test_ip_private_authority_admission_postgres import _transition
from tests.test_matter_writer_admission_postgres import race  # noqa: F401
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


def _upload(session, fixture, operation, content=b"Fresh scanned evidence", *, context=None):
    context = context or _ip_race_context(
        session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
    )
    context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()
    arguments = dict(
        session=session,
        context=context,
        filename="evidence.txt",
        content_type="text/plain",
        stream=BytesIO(content),
    )
    if operation == "upload":
        return ip_document_workflow.upload_ip_document(
            **arguments,
            metadata=IpDocumentUploadMetadata(
                taxonomy_key="document-lock-evidence",
                links=[
                    IpDocumentLinkTarget(
                        target_type="docket", target_id=str(fixture["family"].docket_id)
                    )
                ],
            ),
        )
    return ip_document_workflow.upload_ip_document_version(
        **arguments,
        document_id=fixture["document_id"],
        metadata=IpDocumentNewVersionMetadata(expected_current_version=1),
    )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
@pytest.mark.parametrize("boundary", ["scan", "store"])
def test_ip_upload_io_has_no_transaction(
    pg_engine, monkeypatch, tmp_path, autoflush, operation, boundary
):
    fixture = _seed_document_source(pg_engine)
    observed = []
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    place = document_storage._place_local_temp_file
    with Session(pg_engine, autoflush=autoflush) as session:

        def scan(path):
            if boundary == "scan":
                assert not session.in_transaction(), "scan retained the upload transaction"
            observed.append("scan")
            return virus_scan.ScanResult(status="clean", signature=None)

        def store(temp, target):
            if boundary == "store":
                assert not session.in_transaction(), "store retained the upload transaction"
            observed.append("store")
            return place(temp, target)

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        uploaded, job_id = _upload(session, fixture, operation)
        assert uploaded.outcome == "created" and job_id
    assert observed == ["scan", "store"]
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 1


def _local_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "membership",
        "user",
        "company",
        "session-cutoff",
        "capability",
        "access",
        "close",
        "close-reopen",
        "quota",
        "infected",
        "scanner-error",
        "store-error",
    ],
)
def test_ip_upload_readmits_live_state_and_compensates(
    pg_engine, monkeypatch, tmp_path, autoflush, operation, change
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    observed, removed = [], []
    content = b"Fresh scanned evidence"
    place, delete = document_storage._place_local_temp_file, document_storage.delete_stored_document
    with Session(pg_engine, autoflush=autoflush) as session:

        def scan(path):
            assert not session.in_transaction()
            assert path.read_bytes() == content
            observed.append("scan")
            status = {"infected": "infected", "scanner-error": "error"}.get(change, "clean")
            return virus_scan.ScanResult(status=status, signature=None)

        def store(temp, target):
            assert not session.in_transaction()
            observed.append("store")
            with Session(pg_engine) as concurrent:
                concurrent.execute(text("SET LOCAL lock_timeout = '1s'"))
                if change == "membership":
                    concurrent.get(CompanyMembership, fixture["actor_id"]).is_active = False
                elif change == "user":
                    member = concurrent.get(CompanyMembership, fixture["actor_id"])
                    concurrent.get(User, member.user_id).is_active = False
                elif change == "company":
                    concurrent.get(Company, fixture["company_id"]).is_active = False
                elif change == "session-cutoff":
                    concurrent.get(
                        CompanyMembership, fixture["actor_id"]
                    ).sessions_valid_after = datetime.now(UTC)
                elif change == "capability":
                    concurrent.get(CompanyMembership, fixture["actor_id"]).role = "viewer"
                elif change == "access":
                    grant = concurrent.scalars(
                        select(MatterAccessGrant).where(
                            MatterAccessGrant.ip_docket_id == str(fixture["family"].docket_id),
                            MatterAccessGrant.membership_id == fixture["actor_id"],
                        )
                    ).one()
                    grant.revoked_at = datetime.now(UTC)
                elif change in {"close", "close-reopen"}:
                    context = _ip_race_context(
                        concurrent,
                        company_id=fixture["company_id"],
                        membership_id=fixture["actor_id"],
                    )
                    transition_ip_docket_lifecycle(
                        concurrent,
                        context=context,
                        docket_id=str(fixture["family"].docket_id),
                        payload=_transition(0, "closed"),
                    )
                    if change == "close-reopen":
                        transition_ip_docket_lifecycle(
                            concurrent,
                            context=context,
                            docket_id=str(fixture["family"].docket_id),
                            payload=_transition(1, "ready"),
                        )
                elif change == "quota":
                    concurrent.get(Company, fixture["company_id"]).storage_quota_bytes = 1
                else:
                    for model, identity in (
                        (Company, fixture["company_id"]),
                        (CompanyMembership, fixture["actor_id"]),
                        (IpDocketRecord, str(fixture["family"].docket_id)),
                        (IpDocument, fixture["document_id"]),
                        (IpDocumentVersion, fixture["version_id"]),
                    ):
                        assert (
                            concurrent.scalar(
                                select(model.id)
                                .where(model.id == identity)
                                .with_for_update(nowait=True)
                            )
                            == identity
                        )
                concurrent.commit()
            if change == "store-error":
                raise OSError("isolated object-store outage")
            return place(temp, target)

        def discard(key):
            assert not session.in_transaction()
            removed.append(key)
            delete(key)

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        monkeypatch.setattr(ip_document_workflow, "delete_stored_document", discard)
        if change == "none":
            uploaded, job_id = _upload(session, fixture, operation, content)
        elif change == "store-error":
            with pytest.raises(OSError, match="object-store outage"):
                _upload(session, fixture, operation, content)
        else:
            with pytest.raises(HTTPException) as rejected:
                _upload(session, fixture, operation, content)
            assert (
                rejected.value.status_code
                == {
                    "membership": 403,
                    "user": 403,
                    "company": 403,
                    "capability": 403,
                    "session-cutoff": 401,
                    "access": 404,
                    "close": 404,
                    "close-reopen": 409,
                    "quota": 413,
                    "infected": 400,
                    "scanner-error": 503,
                }[change]
            )
    assert observed == (["scan"] if change in {"infected", "scanner-error"} else ["scan", "store"])
    assert len(removed) == (
        0 if change in {"none", "infected", "scanner-error", "store-error"} else 1
    )
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) == (1 if change == "none" else 0)
    with Session(pg_engine) as verify:
        versions = list(
            verify.scalars(
                select(IpDocumentVersion).where(
                    IpDocumentVersion.company_id == fixture["company_id"],
                    IpDocumentVersion.id != fixture["version_id"],
                )
            )
        )
        jobs = list(
            verify.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.company_id == fixture["company_id"],
                )
            )
        )
        assert len(versions) == len(jobs) == (1 if change == "none" else 0)
        original = verify.get(IpDocumentVersion, fixture["version_id"])
        assert original.sha256_hex == fixture["content_hash"]
        assert original.state == (
            "superseded" if change == "none" and operation == "version" else "draft"
        )
        assert verify.get(IpDocument, fixture["document_id"]).current_version == (
            2 if change == "none" and operation == "version" else 1
        )
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture["company_id"],
                    PrivateProjectionEvent.reason_code == "ip_document_version_superseded",
                )
            )
        )
        assert len(events) == (1 if change == "none" and operation == "version" else 0)
        if events:
            assert events[0].actor_membership_id == fixture["actor_id"]
        if change == "none":
            assert versions[0].uploaded_by_membership_id == fixture["actor_id"]
            assert versions[0].sha256_hex == sha256(content).hexdigest()
            assert jobs[0].id == job_id and files[0].read_bytes() == content
            assert uploaded.document.versions[0].id == versions[0].id


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
@pytest.mark.parametrize("pending", ["new", "dirty", "deleted"])
def test_ip_upload_never_commits_or_discards_pending_caller_writes(
    pg_engine, monkeypatch, autoflush, operation, pending
):
    fixture = _seed_document_source(pg_engine)
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        if pending == "new":
            row = IpDocumentTaxonomyEntry(
                company_id=fixture["company_id"],
                key="pending",
                label="Pending",
                updated_by_membership_id=fixture["actor_id"],
            )
            session.add(row)
        else:
            row = session.get(IpDocument, fixture["document_id"])
            if pending == "dirty":
                row.title = "Pending caller edit"
            else:
                session.delete(row)
        monkeypatch.setattr(
            ip_document_workflow,
            "persist_workspace_attachment",
            lambda **_: pytest.fail("Storage must not run for pending caller writes"),
        )
        with pytest.raises(RuntimeError, match="without pending writes"):
            _upload(session, fixture, operation, context=context)
        assert row in getattr(session, pending)
        assert session.in_transaction()
    with Session(pg_engine) as verify:
        assert verify.get(IpDocument, fixture["document_id"]).title == "Pinned inventor evidence"
        assert (
            verify.scalar(
                select(IpDocumentTaxonomyEntry.id).where(
                    IpDocumentTaxonomyEntry.company_id == fixture["company_id"],
                    IpDocumentTaxonomyEntry.key == "pending",
                )
            )
            is None
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
@pytest.mark.parametrize(
    "prior", ["insert", "update", "core-dml", "row-lock", "savepoint-rollback", "nested"]
)
def test_ip_upload_rejects_flushed_outer_transactions_without_rollback(
    pg_engine, monkeypatch, autoflush, operation, prior
):
    fixture = _seed_document_source(pg_engine)
    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        assert session.scalar(select(func.pg_current_xact_id_if_assigned())) is None
        row = session.get(IpDocument, fixture["document_id"])
        if prior == "insert":
            session.add(
                IpDocumentTaxonomyEntry(
                    company_id=fixture["company_id"],
                    key="outer-flushed",
                    label="Outer flushed",
                    updated_by_membership_id=fixture["actor_id"],
                )
            )
            session.flush()
        elif prior == "update":
            row.title = "Outer flushed title"
            session.flush()
        elif prior == "core-dml":
            session.execute(
                text("UPDATE ip_documents SET title=:title WHERE id=:id"),
                {"title": "Outer flushed title", "id": row.id},
            )
        elif prior == "row-lock":
            session.scalar(select(IpDocument.id).where(IpDocument.id == row.id).with_for_update())
        elif prior == "savepoint-rollback":
            with session.begin_nested() as savepoint:
                row.title = "Rolled back savepoint"
                session.flush()
                savepoint.rollback()
        else:
            session.begin_nested()
        assert not session.new and not session.dirty and not session.deleted
        xid = session.scalar(select(func.pg_current_xact_id_if_assigned()))
        if prior != "nested":
            assert xid is not None
        monkeypatch.setattr(
            ip_document_workflow,
            "persist_workspace_attachment",
            lambda **_: pytest.fail("Storage must not run with a prior write or lock"),
        )
        with pytest.raises(RuntimeError, match="request-owned read-only transaction"):
            _upload(session, fixture, operation, context=context)
        assert session.in_transaction()
        assert session.in_nested_transaction() == (prior == "nested")
        assert session.scalar(select(func.pg_current_xact_id_if_assigned())) == xid
        title = session.scalar(
            select(IpDocument.title).where(IpDocument.id == fixture["document_id"])
        )
        assert title == (
            "Outer flushed title" if prior in {"update", "core-dml"} else "Pinned inventor evidence"
        )
        assert session.scalar(
            select(func.count())
            .select_from(IpDocumentTaxonomyEntry)
            .where(
                IpDocumentTaxonomyEntry.company_id == fixture["company_id"],
                IpDocumentTaxonomyEntry.key == "outer-flushed",
            )
        ) == (1 if prior == "insert" else 0)
        with Session(pg_engine) as observer:
            assert (
                observer.get(IpDocument, fixture["document_id"]).title == "Pinned inventor evidence"
            )
            assert (
                observer.scalar(
                    select(func.count())
                    .select_from(IpDocumentTaxonomyEntry)
                    .where(
                        IpDocumentTaxonomyEntry.company_id == fixture["company_id"],
                        IpDocumentTaxonomyEntry.key == "outer-flushed",
                    )
                )
                == 0
            )
            if prior == "row-lock":
                from sqlalchemy.exc import OperationalError

                with pytest.raises(OperationalError) as blocked:
                    observer.scalar(
                        select(IpDocument.id)
                        .where(IpDocument.id == fixture["document_id"])
                        .with_for_update(nowait=True)
                    )
                assert blocked.value.orig.sqlstate == "55P03"


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("prior", ["auth-select", "core-dml", "explicit-begin"])
def test_ip_upload_sqlite_guard_uses_actual_legacy_transaction_state(tmp_path, autoflush, prior):
    import sqlite3

    from caseops_api.db.session import CaseOpsSession, get_engine

    engine = get_engine(f"sqlite:///{tmp_path / 'guard.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE guard_evidence (value TEXT NOT NULL)")
            connection.exec_driver_sql("INSERT INTO guard_evidence VALUES ('original')")
        with CaseOpsSession(engine, autoflush=autoflush) as session:
            assert session.scalar(text("SELECT value FROM guard_evidence")) == "original"
            connection = session.connection().connection.driver_connection
            assert connection.autocommit == sqlite3.LEGACY_TRANSACTION_CONTROL
            assert connection.isolation_level == "" and not connection.in_transaction
            if prior == "auth-select":
                ip_document_workflow._require_clean_upload_session(session)
                assert session.in_transaction() and not connection.in_transaction
            else:
                session.execute(
                    text(
                        "UPDATE guard_evidence SET value='uncommitted'"
                        if prior == "core-dml"
                        else "BEGIN"
                    )
                )
                with pytest.raises(RuntimeError, match="request-owned read-only transaction"):
                    ip_document_workflow._require_clean_upload_session(session)
                assert session.in_transaction() and connection.in_transaction
                assert session.scalar(text("SELECT value FROM guard_evidence")) == (
                    "uncommitted" if prior == "core-dml" else "original"
                )
                with engine.connect() as observer:
                    assert observer.scalar(text("SELECT value FROM guard_evidence")) == "original"
    finally:
        engine.dispose()


def test_ip_upload_http_auth_read_transaction_remains_accepted(
    isolated_postgres_client, monkeypatch
):
    from tests.test_ip_document_workflow import (
        test_ip_document_end_to_end_version_processing_and_approval_lock,
    )

    guard = ip_document_workflow._require_clean_upload_session
    observed = []

    def read_only_auth(session):
        assert session.in_transaction()
        assert session.scalar(select(func.pg_current_xact_id_if_assigned())) is None
        observed.append(True)
        guard(session)

    monkeypatch.setattr(ip_document_workflow, "_require_clean_upload_session", read_only_auth)
    test_ip_document_end_to_end_version_processing_and_approval_lock(isolated_postgres_client)
    assert len(observed) >= 2


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_cleanup_failure_preserves_authorization_rejection(
    pg_engine, monkeypatch, tmp_path, caplog, autoflush, operation
):
    fixture = _seed_document_source(pg_engine)
    # Alembic's fileConfig disables existing application loggers in this harness.
    monkeypatch.setattr(ip_document_workflow.logger, "disabled", False)
    caplog.set_level("ERROR", logger=ip_document_workflow.__name__)
    _local_storage(monkeypatch, tmp_path)
    place = document_storage._place_local_temp_file
    removed = []
    with Session(pg_engine, autoflush=autoflush) as session:

        def store(temp, target):
            assert not session.in_transaction()
            with Session(pg_engine) as concurrent:
                concurrent.get(Company, fixture["company_id"]).is_active = False
                concurrent.commit()
            return place(temp, target)

        def discard(_key):
            assert not session.in_transaction()
            removed.append(_key)
            raise OSError("isolated compensation outage")

        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        monkeypatch.setattr(ip_document_workflow, "delete_stored_document", discard)
        with pytest.raises(HTTPException) as rejected:
            _upload(session, fixture, operation)
        assert rejected.value.status_code == 403
        assert not session.in_transaction()
    assert len(removed) == 1
    assert "Could not remove unpublished IP upload" in caplog.text
    with Session(pg_engine) as observer:
        assert (
            observer.scalar(
                select(func.count())
                .select_from(IpDocumentVersion)
                .where(IpDocumentVersion.company_id == fixture["company_id"])
            )
            == 1
        )
        assert observer.get(IpDocument, fixture["document_id"]).current_version == 1


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("scenario", ["quota", "naming", "duplicate", "version"])
def test_parallel_ip_uploads_reconcile_post_io_state(
    pg_engine, monkeypatch, tmp_path, autoflush, scenario
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    barrier, local_session = Barrier(2), local()
    place = document_storage._place_local_temp_file
    content = b"Parallel immutable upload 0"
    if scenario == "quota":
        with Session(pg_engine) as seed:
            used = seed.get(IpDocumentVersion, fixture["version_id"]).size_bytes
            seed.get(Company, fixture["company_id"]).storage_quota_bytes = used + len(content)
            seed.commit()

    def store(temp, target):
        assert not local_session.session.in_transaction()
        barrier.wait(timeout=10)
        return place(temp, target)

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def run(index):
        with Session(pg_engine, autoflush=autoflush) as session:
            local_session.session = session
            try:
                return _upload(
                    session,
                    fixture,
                    "version" if scenario == "version" else "upload",
                    content if scenario == "duplicate" else content[:-1] + str(index).encode(),
                )
            except HTTPException as exc:
                return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, (0, 1)))
    errors = [result for result in results if isinstance(result, HTTPException)]
    successes = [result for result in results if not isinstance(result, HTTPException)]
    assert [error.status_code for error in errors] == (
        {"quota": [413], "version": [409]}.get(scenario, [])
    )
    if scenario == "duplicate":
        assert sorted(result.outcome for result, _ in successes) == ["created", "duplicate_found"]
    else:
        assert all(result.outcome == "created" for result, _ in successes)
    count = 2 if scenario == "naming" else 1
    with Session(pg_engine) as verify:
        versions = list(
            verify.scalars(
                select(IpDocumentVersion).where(
                    IpDocumentVersion.company_id == fixture["company_id"],
                    IpDocumentVersion.id != fixture["version_id"],
                )
            )
        )
        assert len(versions) == count
        assert len({row.display_name.casefold() for row in versions}) == count
        assert (
            verify.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.company_id == fixture["company_id"],
                )
            )
            == count
        )
        if scenario == "version":
            assert errors[0].detail["code"] == "ip_document_version_conflict"
            assert verify.get(IpDocument, fixture["document_id"]).current_version == 2
            assert verify.get(IpDocumentVersion, fixture["version_id"]).state == "superseded"
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == count


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_company_fk_compatibility_before_actor_and_parent(
    pg_engine,
    monkeypatch,
    tmp_path,
    race,  # noqa: F811
    operation,
):
    fixture = _seed_document_source(pg_engine)
    with Session(pg_engine) as seed:
        owner = _seed_membership(seed, fixture["company_id"], role="owner")
        seed.commit()
    _local_storage(monkeypatch, tmp_path)
    employee_locked, release_employee = Event(), Event()
    lock_employee = employees._lock_employee_writer_context

    def pause_employee(*args, **kwargs):
        result = lock_employee(*args, **kwargs)
        employee_locked.set()
        assert release_employee.wait(12)
        return result

    monkeypatch.setattr(employees, "_lock_employee_writer_context", pause_employee)
    race.pause_role = "upload"
    company_locks = 0

    def final_admission(sql):
        nonlocal company_locks
        if "FROM companies" not in sql or "FOR " not in sql:
            return False
        company_locks += 1
        return company_locks == 2

    race.predicate = final_admission

    def upload():
        with race.session("upload") as session:
            return _upload(session, fixture, operation)

    def employee():
        with race.session("employee") as session:
            return employees.update_employee(
                session,
                context=_ip_race_context(
                    session, company_id=fixture["company_id"], membership_id=owner
                ),
                membership_id=fixture["actor_id"],
                payload=EmployeeUpdateRequest(designation="IP upload operator"),
            )

    upload_future = race.submit("upload", upload)
    try:
        assert race.paused.wait(10)
        employee_future = race.submit("employee", employee)
        assert employee_locked.wait(10)
        race.release.set()
        race.blocked("upload", "employee", "FROM company_memberships")
        with Session(race.observer) as probe:
            for model, identity in (
                (IpDocketRecord, str(fixture["family"].docket_id)),
                (IpDocument, fixture["document_id"]),
                (IpDocumentVersion, fixture["version_id"]),
            ):
                assert (
                    probe.scalar(
                        select(model.id).where(model.id == identity).with_for_update(nowait=True)
                    )
                    == identity
                )
        release_employee.set()
        assert employee_future.result(15).designation == "IP upload operator"
        result, job = upload_future.result(15)
        assert result.outcome == "created" and job
        locks = [sql for sql in race.sql["upload"] if "FROM companies" in sql and "FOR " in sql]
        assert locks and all("FOR NO KEY UPDATE" in sql for sql in locks)
    finally:
        release_employee.set()
        race.release.set()


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_rechecks_quota_consumed_by_real_matter_upload(
    pg_engine, monkeypatch, tmp_path, autoflush, operation
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    content = b"Fresh scanned evidence"
    with Session(pg_engine) as seed:
        matter_id = _seed_matter(seed, fixture["company_id"])
        retained = seed.get(IpDocumentVersion, fixture["version_id"]).size_bytes
        seed.get(Company, fixture["company_id"]).storage_quota_bytes = retained + len(content)
        seed.commit()
    place = document_storage._place_local_temp_file
    accepted = []
    with Session(pg_engine, autoflush=autoflush) as session:

        def store(temp, target):
            assert not session.in_transaction()
            if temp.read_bytes() == content:
                with Session(pg_engine) as competitor:
                    context = _ip_race_context(
                        competitor,
                        company_id=fixture["company_id"],
                        membership_id=fixture["actor_id"],
                    )
                    attachment, job = matters.create_matter_attachment(
                        competitor,
                        context=context,
                        matter_id=matter_id,
                        filename="competitor.txt",
                        content_type="text/plain",
                        stream=BytesIO(b"M" * len(content)),
                    )
                    accepted.append((attachment.id, job))
            return place(temp, target)

        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        with pytest.raises(HTTPException) as rejected:
            _upload(session, fixture, operation, content)
        assert rejected.value.status_code == 413
    assert len(accepted) == 1
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) == 1 and files[0].read_bytes() == b"M" * len(content)
    with Session(pg_engine) as verify:
        assert (
            verify.scalar(
                select(func.count())
                .select_from(IpDocumentVersion)
                .where(IpDocumentVersion.company_id == fixture["company_id"])
            )
            == 1
        )
        assert verify.get(IpDocumentVersion, fixture["version_id"]).state == "draft"
        assert verify.get(IpDocument, fixture["document_id"]).current_version == 1


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_quota_preflight_rejects_before_scan_and_store(
    pg_engine, monkeypatch, tmp_path, autoflush, operation
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    with Session(pg_engine) as seed:
        seed.get(Company, fixture["company_id"]).storage_quota_bytes = 1
        seed.commit()
    monkeypatch.setattr(virus_scan, "scan_file_for_viruses", lambda _: pytest.fail("Scan ran"))
    monkeypatch.setattr(
        document_storage, "_place_local_temp_file", lambda *_: pytest.fail("Store ran")
    )
    with Session(pg_engine, autoflush=autoflush) as session:
        with pytest.raises(HTTPException) as rejected:
            _upload(session, fixture, operation)
        assert rejected.value.status_code == 413
        assert not session.in_transaction()
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_committed_object_survives_response_serialization_error(
    pg_engine, monkeypatch, tmp_path, autoflush, operation
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)

    def fail_response(*args, **kwargs):
        raise RuntimeError("response serialization failed")

    monkeypatch.setattr(ip_document_workflow, "_serialize_document", fail_response)
    with Session(pg_engine, autoflush=autoflush) as session:
        with pytest.raises(RuntimeError, match="response serialization failed"):
            _upload(session, fixture, operation)
    with Session(pg_engine) as verify:
        row = verify.scalars(
            select(IpDocumentVersion).where(
                IpDocumentVersion.company_id == fixture["company_id"],
                IpDocumentVersion.id != fixture["version_id"],
            )
        ).one()
        assert (
            document_storage.resolve_storage_path(row.storage_key).read_bytes()
            == b"Fresh scanned evidence"
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.company_id == fixture["company_id"],
                )
            )
            == 1
        )


@pytest.mark.parametrize("autoflush", [False, True])
def test_ip_upload_preserves_terminal_historical_bytes_and_controlled_reopen(
    pg_engine, monkeypatch, tmp_path, autoflush
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    content = b"Fresh scanned evidence"
    with Session(pg_engine, autoflush=autoflush) as session:
        uploaded, _ = _upload(session, fixture, "upload", content)
        document_id = uploaded.document.id
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=str(fixture["family"].docket_id),
            payload=_transition(0, "closed"),
        )
        historical = ip_document_workflow.get_ip_document_version_for_download(
            session,
            context=context,
            document_id=document_id,
            version_number=1,
        )
        assert document_storage.resolve_storage_path(historical.storage_key).read_bytes() == content
        assert historical.sha256_hex == sha256(content).hexdigest()
        current_fixture = {**fixture, "document_id": document_id}
        for operation in ("upload", "version"):
            with pytest.raises(HTTPException) as rejected:
                _upload(session, current_fixture, operation, b"Terminal attempt")
            assert rejected.value.status_code == 404
            session.rollback()
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=str(fixture["family"].docket_id),
            payload=_transition(1, "ready"),
        )
        revised, _ = _upload(session, current_fixture, "version", b"Reopened evidence")
        assert revised.document.current_version == 2
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=str(fixture["family"].docket_id),
            payload=_transition(2, "closed"),
        )
        historical = ip_document_workflow.get_ip_document_version_for_download(
            session,
            context=context,
            document_id=document_id,
            version_number=1,
        )
        assert historical.state == "superseded"
        assert document_storage.resolve_storage_path(historical.storage_key).read_bytes() == content
        assert session.get(IpDocketRecord, str(fixture["family"].docket_id)).lifecycle_version == 3


def test_ip_upload_large_history_naming_http_on_postgres(isolated_postgres_client):
    from tests.test_ip_document_workflow import (
        test_all_naming_paths_remain_bounded_after_more_than_500_historical_versions,
    )

    test_all_naming_paths_remain_bounded_after_more_than_500_historical_versions(
        isolated_postgres_client
    )


@pytest.mark.parametrize("autoflush", [False, True])
def test_ip_quota_counts_retained_versions_once_in_every_state_and_tenant(pg_engine, autoflush):
    fixture = _seed_document_source(pg_engine)
    other = _seed_document_source(pg_engine)
    with Session(pg_engine, autoflush=autoflush) as session:
        original = session.get(IpDocumentVersion, fixture["version_id"])
        expected = original.size_bytes
        document = session.get(IpDocument, fixture["document_id"])
        document.current_version = 9
        document.is_privileged = True
        states = (
            "draft",
            "review",
            "approved",
            "filed",
            "served",
            "accepted",
            "rejected",
            "superseded",
        )
        for number, state in enumerate(states, 2):
            size = number * 17
            expected += size
            session.add(
                IpDocumentVersion(
                    company_id=fixture["company_id"],
                    document_id=document.id,
                    version=number,
                    original_filename=f"retained-{number}.txt",
                    display_name=f"retained-{number}.txt",
                    storage_key=f"accounting/{document.id}/{number}",
                    content_type="text/plain",
                    size_bytes=size,
                    sha256_hex="a" * 64,
                    state=state,
                    processing_status=("pending", "failed", "indexed")[number % 3],
                    uploaded_by_membership_id=fixture["actor_id"],
                    locked_at=datetime.now(UTC) if state in {"approved", "filed"} else None,
                    locked_by_membership_id=fixture["actor_id"]
                    if state in {"approved", "filed"}
                    else None,
                )
            )
        # Links are references, never a second storage allocation.
        session.add(
            IpDocumentLink(
                company_id=fixture["company_id"],
                document_id=document.id,
                version_id=original.id,
                target_type="docket",
                target_id=fixture["target_id"],
                docket_id=fixture["target_id"],
                created_by_membership_id=fixture["actor_id"],
            )
        )
        session.commit()
        assert storage_governance._used_bytes(session, company_id=fixture["company_id"]) == expected
        assert storage_governance._used_bytes(session, company_id=other["company_id"]) == (
            session.get(IpDocumentVersion, other["version_id"]).size_bytes
        )
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        transition_ip_docket_lifecycle(
            session,
            context=context,
            docket_id=str(fixture["family"].docket_id),
            payload=_transition(0, "closed"),
        )
        grant = session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.ip_docket_id == str(fixture["family"].docket_id),
                MatterAccessGrant.membership_id == fixture["actor_id"],
            )
        ).one()
        grant.revoked_at = datetime.now(UTC)
        session.get(Company, fixture["company_id"]).storage_quota_bytes = expected + 7
        session.commit()
        policy = storage_governance.get_storage_upload_policy(
            session, company_id=fixture["company_id"]
        )
        summary = storage_governance.get_firm_storage_summary(
            session, company_id=fixture["company_id"], context=context
        )
        assert policy.used_bytes == summary.used_bytes == expected
        assert policy.remaining_bytes == summary.remaining_bytes == 7
        assert not summary.largest_files and not summary.usage_by_matter
        storage_governance.assert_storage_quota_allows_upload(
            session, company_id=fixture["company_id"], matter_id=None, incoming_size_bytes=7
        )
        with pytest.raises(storage_governance.StorageQuotaExceeded) as rejected:
            storage_governance.assert_storage_quota_allows_upload(
                session, company_id=fixture["company_id"], matter_id=None, incoming_size_bytes=8
            )
        assert rejected.value.used_bytes == expected and rejected.value.remaining_bytes == 7


@pytest.mark.parametrize("autoflush", [False, True])
def test_ip_quota_real_upload_versions_and_duplicate_reuse_have_exact_totals(
    pg_engine, monkeypatch, tmp_path, autoflush
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    first, second = b"Original retained bytes", b"Revised retained bytes"
    with Session(pg_engine, autoflush=autoflush) as session:
        baseline = session.get(IpDocumentVersion, fixture["version_id"]).size_bytes
        created, _ = _upload(session, fixture, "upload", first)
        assert storage_governance._used_bytes(
            session, company_id=fixture["company_id"]
        ) == baseline + len(first)
        revised, _ = _upload(session, fixture, "version", second)
        assert revised.document.current_version == 2
        assert session.get(IpDocumentVersion, fixture["version_id"]).state == "superseded"
        expected = baseline + len(first) + len(second)
        assert storage_governance._used_bytes(session, company_id=fixture["company_id"]) == expected
        for operation in ("upload", "version"):
            duplicate, job = _upload(
                session, {**fixture, "document_id": created.document.id}, operation, first
            )
            assert duplicate.outcome == "duplicate_found" and job is None
            assert (
                storage_governance._used_bytes(session, company_id=fixture["company_id"])
                == expected
            )
            assert session.get(IpDocument, created.document.id).current_version == 1
    assert len([path for path in tmp_path.rglob("*") if path.is_file()]) == 2


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("operation", ["upload", "version"])
def test_ip_upload_uncertain_commit_never_deletes_published_bytes(
    pg_engine, monkeypatch, tmp_path, autoflush, operation
):
    fixture = _seed_document_source(pg_engine)
    _local_storage(monkeypatch, tmp_path)
    with Session(pg_engine, autoflush=autoflush) as session:
        commit = session.commit

        def commit_without_acknowledgement():
            commit()
            raise OSError("commit acknowledgement lost")

        monkeypatch.setattr(session, "commit", commit_without_acknowledgement)
        with pytest.raises(OSError, match="commit acknowledgement lost"):
            _upload(session, fixture, operation)
    with Session(pg_engine) as verify:
        version = verify.scalars(
            select(IpDocumentVersion).where(
                IpDocumentVersion.company_id == fixture["company_id"],
                IpDocumentVersion.id != fixture["version_id"],
            )
        ).one()
        assert (
            document_storage.resolve_storage_path(version.storage_key).read_bytes()
            == b"Fresh scanned evidence"
        )
        assert (
            verify.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.company_id == fixture["company_id"],
                )
            )
            == 1
        )
