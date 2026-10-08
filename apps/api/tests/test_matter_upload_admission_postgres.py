"""A real upload quota writer must not invert primary Matter tenant admission."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from threading import Barrier, Event
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    DocumentProcessingJob,
    Matter,
    MatterAttachment,
    User,
)
from caseops_api.schemas.employees import EmployeeUpdateRequest
from caseops_api.schemas.matters import MatterLifecycleStatusRequest
from caseops_api.services import document_storage, employees, matters, virus_scan
from caseops_api.services.document_storage import StoredDocument
from tests.test_matter_writer_admission_postgres import (
    _fixture,
    _mutate,
    race,  # noqa: F401
)
from tests.test_postgres_validation import _ensure_migrations, _ip_race_context  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("mutation", ["metadata", "dispose"])
@pytest.mark.parametrize("first", ["matter", "upload"])
def test_real_upload_quota_and_primary_matter_order(pg_engine, monkeypatch, race, mutation, first):  # noqa: F811
    fixture = _fixture(pg_engine)
    stored_ids, removed = [], []

    def store(**kwargs):
        content = kwargs["stream"].read()
        kwargs["before_store"](len(content))
        stored_ids.append(kwargs["attachment_id"])
        return StoredDocument(
            storage_key=f"local-audit/{uuid4()}",
            size_bytes=len(content),
            sha256_hex=sha256(content).hexdigest(),
        )

    monkeypatch.setattr(matters, "persist_matter_attachment", store)
    monkeypatch.setattr(matters, "delete_stored_document", removed.append)
    race.pause_role = first
    company_locks = 0

    def final_admission(sql):
        nonlocal company_locks
        if "FROM companies" not in sql or "FOR " not in sql:
            return False
        company_locks += 1
        # Upload releases preflight authority and its early quota check before I/O.
        return first == "matter" or company_locks == 3

    race.predicate = final_admission

    def primary():
        with race.session("matter") as session:
            return _mutate(session, fixture, mutation)

    def upload():
        with race.session("upload") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            return matters.create_matter_attachment(
                session,
                context=context,
                matter_id=fixture.matter,
                filename="source.txt",
                content_type="text/plain",
                stream=BytesIO(b"Local upload"),
            )

    operations = {"matter": primary, "upload": upload}
    second = "upload" if first == "matter" else "matter"
    futures = {first: race.submit(first, operations[first])}
    assert race.paused.wait(10)
    futures[second] = race.submit(second, operations[second])
    race.blocked(second, first, "FROM companies")
    with race.observer.begin() as probe:
        probe.execute(
            text("SELECT id FROM company_memberships WHERE id=:id FOR UPDATE NOWAIT"),
            {"id": fixture.actor},
        )
        probe.execute(
            text("SELECT id FROM matters WHERE id=:id FOR UPDATE NOWAIT"), {"id": fixture.matter}
        )
    race.release.set()
    futures["matter"].result(15)
    rejected = first == "matter" and mutation == "dispose"
    if rejected:
        with pytest.raises(HTTPException) as error:
            futures["upload"].result(15)
        assert error.value.status_code == 409
        assert not removed
        assert not stored_ids
    else:
        result, job_id = futures["upload"].result(15)
        assert result.id in stored_ids
        assert not removed
    with Session(pg_engine) as verify:
        attachment = verify.get(MatterAttachment, stored_ids[0]) if stored_ids else None
        assert (attachment is None) == rejected
        jobs = list(
            verify.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.attachment_id.in_(stored_ids)
                )
            )
        )
        assert len(jobs) == (0 if rejected else 1)
        if not rejected:
            assert jobs[0].id == job_id
            assert attachment.uploaded_by_membership_id == fixture.actor
            assert attachment.size_bytes == len(b"Local upload")
        parent = verify.get(Matter, fixture.matter)
        if mutation == "dispose":
            assert parent.status == "disposed" and not parent.is_active
            assert all(job.status == "failed" for job in jobs)
            assert all("disposed" in job.error_message.lower() for job in jobs)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize(
    "change",
    [
        "none",
        "dispose",
        "dispose-reopen",
        "membership",
        "user",
        "company",
        "session-cutoff",
        "quota",
        "infected",
        "scanner-error",
    ],
)
def test_upload_io_releases_transaction_and_readmits_fresh_state(
    pg_engine, monkeypatch, tmp_path, autoflush, change
):
    fixture = _fixture(pg_engine)
    content = b"Scanned upload evidence"
    observed = []
    monkeypatch.setenv("CASEOPS_CLAMAV_REQUIRED", "true")
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    place = document_storage._place_local_temp_file

    with Session(pg_engine, autoflush=autoflush) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.actor)
        context.token_issued_at = (datetime.now(UTC) - timedelta(minutes=1)).timestamp()

        def scan(path):
            assert not session.in_transaction()
            assert path.read_bytes() == content
            observed.append("scan")
            if change == "infected":
                return virus_scan.ScanResult(status="infected", signature="Eicar-Test-Signature")
            if change == "scanner-error":
                return virus_scan.ScanResult(
                    status="error", signature=None, detail="isolated scanner outage"
                )
            return virus_scan.ScanResult(status="clean", signature=None)

        def store(temp, target):
            assert not session.in_transaction()
            observed.append("store")
            with Session(pg_engine) as concurrent:
                if change in {"dispose", "dispose-reopen"}:
                    disposed = _mutate(concurrent, fixture, "dispose")
                    if change == "dispose-reopen":
                        current = _ip_race_context(
                            concurrent, company_id=fixture.company, membership_id=fixture.actor
                        )
                        matters.transition_matter_lifecycle_status(
                            concurrent,
                            context=current,
                            matter_id=fixture.matter,
                            payload=MatterLifecycleStatusRequest(
                                to_status="intake", expected_from_status="disposed",
                                expected_updated_at=disposed.updated_at,
                                reason="Explicit fresh engagement after disposal",
                            ),
                        )
                elif change == "membership":
                    concurrent.get(CompanyMembership, fixture.actor).is_active = False
                    concurrent.commit()
                elif change == "user":
                    member = concurrent.get(CompanyMembership, fixture.actor)
                    concurrent.get(User, member.user_id).is_active = False
                    concurrent.commit()
                elif change == "quota":
                    concurrent.get(Company, fixture.company).storage_quota_bytes = 23
                    concurrent.commit()
                elif change == "company":
                    concurrent.get(Company, fixture.company).is_active = False
                    concurrent.commit()
                elif change == "session-cutoff":
                    concurrent.get(
                        CompanyMembership, fixture.actor
                    ).sessions_valid_after = datetime.now(UTC)
                    concurrent.commit()
                else:
                    # Neither Company, the actor nor parent stays locked during I/O.
                    for table, identity in (
                        ("companies", fixture.company),
                        ("company_memberships", fixture.actor),
                        ("matters", fixture.matter),
                    ):
                        concurrent.execute(
                            text(f"SELECT id FROM {table} WHERE id=:id FOR UPDATE NOWAIT"),
                            {"id": identity},
                        )
            return place(temp, target)

        monkeypatch.setattr(virus_scan, "scan_file_for_viruses", scan)
        monkeypatch.setattr(document_storage, "_place_local_temp_file", store)
        kwargs = dict(
            session=session,
            context=context,
            matter_id=fixture.matter,
            filename="transaction-free.txt",
            content_type="text/plain",
            stream=BytesIO(content),
        )
        if change == "none":
            uploaded, job_id = matters.create_matter_attachment(**kwargs)
        else:
            with pytest.raises(HTTPException) as error:
                matters.create_matter_attachment(**kwargs)
            expected_status = {
                "dispose": 409,
                "dispose-reopen": 409,
                "membership": 403,
                "user": 403,
                "company": 403,
                "session-cutoff": 401,
                "quota": 413,
                "infected": 400,
                "scanner-error": 503,
            }[change]
            assert error.value.status_code == expected_status
    assert observed == (["scan"] if change in {"infected", "scanner-error"} else ["scan", "store"])
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) == (1 if change == "none" else 0)
    with Session(pg_engine) as verify:
        rows = list(
            verify.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.matter_id == fixture.matter,
                    MatterAttachment.original_filename == "transaction-free.txt",
                )
            )
        )
        jobs = list(
            verify.scalars(
                select(DocumentProcessingJob).where(
                    DocumentProcessingJob.company_id == fixture.company,
                    DocumentProcessingJob.id != fixture.job,
                )
            )
        )
        assert len(rows) == len(jobs) == (1 if change == "none" else 0)
        if change == "dispose-reopen":
            parent = verify.get(Matter, fixture.matter)
            assert parent.status == "intake" and parent.is_active
            assert verify.get(DocumentProcessingJob, fixture.job).status == "failed"
    if change == "dispose-reopen":
        monkeypatch.setattr(document_storage, "_place_local_temp_file", place)
        with Session(pg_engine, autoflush=autoflush) as fresh:
            current = _ip_race_context(
                fresh, company_id=fixture.company, membership_id=fixture.actor
            )
            uploaded, job_id = matters.create_matter_attachment(
                fresh, context=current, matter_id=fixture.matter,
                filename="new-engagement.txt", content_type="text/plain", stream=BytesIO(content),
            )
            assert uploaded.id and job_id
            assert fresh.get(Matter, fixture.matter).status == "intake"
        if change == "none":
            assert rows[0].id == uploaded.id and jobs[0].id == job_id
            assert files[0].read_bytes() == content
            assert rows[0].sha256_hex == sha256(content).hexdigest()
        if change == "dispose":
            parent = verify.get(Matter, fixture.matter)
            assert parent.status == "disposed" and not parent.is_active


@pytest.mark.parametrize("autoflush", [False, True])
def test_parallel_uploads_recheck_quota_after_unlocked_storage(
    pg_engine, monkeypatch, tmp_path, autoflush
):
    fixture = _fixture(pg_engine)
    content = b"Bounded upload"
    with Session(pg_engine) as seed:
        seed.get(Company, fixture.company).storage_quota_bytes = 23 + len(content)
        seed.commit()
    barrier = Barrier(2)
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    place = document_storage._place_local_temp_file

    def store(temp, target):
        barrier.wait(timeout=10)
        return place(temp, target)

    monkeypatch.setattr(document_storage, "_place_local_temp_file", store)

    def upload(index):
        with Session(pg_engine, autoflush=autoflush) as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            try:
                row, job = matters.create_matter_attachment(
                    session,
                    context=context,
                    matter_id=fixture.matter,
                    filename=f"parallel-{index}.txt",
                    content_type="text/plain",
                    stream=BytesIO(content),
                )
                return 200, row.id, job
            except HTTPException as exc:
                assert "quota" in str(exc.detail).lower()
                return exc.status_code, None, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(upload, (1, 2)))
    assert sorted(row[0] for row in results) == [200, 413]
    with Session(pg_engine) as verify:
        rows = list(
            verify.scalars(
                select(MatterAttachment).where(
                    MatterAttachment.matter_id == fixture.matter,
                    MatterAttachment.original_filename.like("parallel-%"),
                )
            )
        )
        assert len(rows) == 1
        assert rows[0].size_bytes == len(content)
        assert rows[0].id == next(row[1] for row in results if row[0] == 200)
    files = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert len(files) == 1 and files[0].read_bytes() == content


@pytest.mark.parametrize("autoflush", [False, True])
def test_upload_quota_lock_allows_employee_audit_fk_before_actor_wait(
    pg_engine,
    monkeypatch,
    race,  # noqa: F811
):  # noqa: F811
    fixture = _fixture(pg_engine)
    employee_locked, release_employee = Event(), Event()
    lock_employee = employees._lock_employee_writer_context

    def pause_employee(*args, **kwargs):
        result = lock_employee(*args, **kwargs)
        employee_locked.set()
        assert release_employee.wait(12)
        return result

    def store(**kwargs):
        content = kwargs["stream"].read()
        kwargs["before_store"](len(content))
        return StoredDocument(
            storage_key=f"local-audit/{uuid4()}",
            size_bytes=len(content),
            sha256_hex=sha256(content).hexdigest(),
        )

    monkeypatch.setattr(employees, "_lock_employee_writer_context", pause_employee)
    monkeypatch.setattr(matters, "persist_matter_attachment", store)
    monkeypatch.setattr(matters, "delete_stored_document", lambda _: None)
    race.pause_role = "upload"
    company_locks = 0

    def final_company_lock(sql):
        nonlocal company_locks
        if "FROM companies" not in sql or "FOR " not in sql:
            return False
        company_locks += 1
        return company_locks == 3

    race.predicate = final_company_lock

    def upload():
        with race.session("upload") as session:
            return matters.create_matter_attachment(
                session,
                context=_ip_race_context(
                    session, company_id=fixture.company, membership_id=fixture.actor
                ),
                matter_id=fixture.matter,
                filename="employee-overlap.txt",
                content_type="text/plain",
                stream=BytesIO(b"Concurrent directory update"),
            )

    def employee():
        with race.session("employee") as session:
            return employees.update_employee(
                session,
                context=_ip_race_context(
                    session, company_id=fixture.company, membership_id=fixture.owner
                ),
                membership_id=fixture.actor,
                payload=EmployeeUpdateRequest(designation="Reviewed upload operator"),
            )

    upload_future = race.submit("upload", upload)
    try:
        assert race.paused.wait(10)
        employee_future = race.submit("employee", employee)
        assert employee_locked.wait(10)
        race.release.set()
        race.blocked("upload", "employee", "FROM company_memberships")
        release_employee.set()
        employee_record = employee_future.result(15)
        attachment, job_id = upload_future.result(15)
        assert employee_record.designation == "Reviewed upload operator"
        with Session(pg_engine) as verify:
            assert (
                verify.get(MatterAttachment, attachment.id).uploaded_by_membership_id
                == fixture.actor
            )
            assert verify.get(DocumentProcessingJob, job_id).attachment_id == attachment.id
    finally:
        release_employee.set()
        race.release.set()
