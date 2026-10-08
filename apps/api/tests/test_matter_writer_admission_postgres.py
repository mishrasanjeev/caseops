"""Real-service tenant admission, worker finalization and revocation races."""

from __future__ import annotations

import csv
import io
import json
import os
from concurrent.futures import ThreadPoolExecutor, wait
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, local
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    CompanyMembership,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingTargetType,
    IpDocument,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    Matter,
    MatterAttachment,
    MatterAttachmentChunk,
    PrivateProjectionEvent,
)
from caseops_api.schemas.companies import CompanyUserUpdateRequest
from caseops_api.schemas.employees import EmployeeOffboardingRequest
from caseops_api.schemas.intake import IntakeRequestCreateRequest, IntakeRequestPromoteRequest
from caseops_api.schemas.matters import (
    MatterCreateRequest,
    MatterLifecycleStatusRequest,
    MatterNoteCreateRequest,
    MatterUpdateRequest,
)
from caseops_api.services import (
    document_jobs,
    document_processing,
    embeddings,
    employees,
    identity,
    intake,
    matter_bulk_updates,
    matter_imports,
    matters,
)
from caseops_api.services.private_retrieval import ensure_active_private_generation
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


class _Race:
    def __init__(self, engine, evidence, autoflush):
        self.engine, self.evidence, self.autoflush = engine, evidence, autoflush
        self.observer = create_engine(engine.url, poolclass=NullPool)
        self.local, self.lock = local(), Lock()
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.futures, self.pids, self.sql, self.names = [], {}, {}, {}
        self.paused, self.release = Event(), Event()
        self.pause_role, self.predicate, self.after = None, None, True
        self.hooks = [
            ("before_cursor_execute", self.before_sql),
            ("after_cursor_execute", self.after_sql),
            ("handle_error", self.error),
            ("commit", self.commit),
        ]
        for name, callback in self.hooks:
            event.listen(engine, name, callback)

    def record(self, kind, **data):
        with self.lock:
            self.evidence.write(json.dumps({"event": kind, **data}, default=str) + "\n")
            self.evidence.flush()

    def session(self, role):
        session = Session(self.engine, autoflush=self.autoflush, expire_on_commit=False)
        self.names.setdefault(role, f"matter-admission-{uuid4().hex}")

        def label_transaction(session, transaction, connection):
            if transaction.nested:
                return
            connection.execute(text("SET LOCAL statement_timeout = '15s'"))
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            connection.execute(text("SET LOCAL deadlock_timeout = '1s'"))
            connection.execute(
                text("SELECT set_config('application_name', :name, true)"),
                {"name": self.names[role]},
            )
            self.pids[role] = connection.scalar(text("SELECT pg_backend_pid()"))
            self.record("transaction_backend", role=role, pid=self.pids[role])

        # NullPool HTTP fixtures replace the backend after every commit.
        event.listen(session, "after_begin", label_transaction)
        session.connection()
        return session

    def before_sql(self, conn, cursor, statement, parameters, context, many):
        role = getattr(self.local, "role", None)
        if role:
            self.sql.setdefault(role, []).append(statement)
            if "FOR " in statement or statement.startswith(
                ("INSERT", "UPDATE", "SAVEPOINT", "ROLLBACK")
            ):
                self.record("sql_before", role=role, statement=statement, parameters=parameters)
        self.maybe_pause(role, statement, after=False)

    def commit(self, conn):
        role = getattr(self.local, "role", None)
        if role:
            self.sql.setdefault(role, []).append("COMMIT")
            self.record("commit", role=role)

    def after_sql(self, conn, cursor, statement, parameters, context, many):
        role = getattr(self.local, "role", None)
        if role and "FOR " in statement:
            self.record("sql_lock_acquired", role=role, statement=statement)
        self.maybe_pause(role, statement, after=True)

    def maybe_pause(self, role, statement, *, after):
        if (
            role == self.pause_role
            and self.predicate
            and self.after == after
            and not self.paused.is_set()
            and self.predicate(statement)
        ):
            self.paused.set()
            assert self.release.wait(12), "Scheduled service boundary was not released"

    def error(self, context):
        exc = context.original_exception
        self.record(
            "database_error",
            role=getattr(self.local, "role", None),
            sqlstate=getattr(exc, "sqlstate", None),
            message=str(exc),
            statement=context.statement,
        )

    def submit(self, role, operation):
        def invoke():
            self.local.role = role
            try:
                return operation()
            finally:
                self.local.role = None

        future = self.pool.submit(invoke)
        self.futures.append(future)
        return future

    def snapshot(self):
        with self.observer.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT pid, application_name, xact_start, state, query, "
                        "wait_event_type, pg_blocking_pids(pid) AS blockers "
                        "FROM pg_stat_activity WHERE application_name = ANY(:names)"
                    ),
                    {"names": list(self.names.values())},
                )
                .mappings()
                .all()
            )
            locks = (
                conn.execute(
                    text(
                        "SELECT pid, locktype, relation::regclass::text AS relation, "
                        "mode, granted, "
                        "transactionid, page, tuple FROM pg_locks WHERE pid = ANY(:pids)"
                    ),
                    {"pids": list(self.pids.values())},
                )
                .mappings()
                .all()
            )
        return {"activity": [dict(row) for row in rows], "locks": [dict(row) for row in locks]}

    def blocked(self, waiter, holder, fragment):
        deadline = monotonic() + 5
        while monotonic() < deadline:
            snapshot = self.snapshot()
            rows = {row["pid"]: row for row in snapshot["activity"]}
            row = rows.get(self.pids.get(waiter), {})
            if self.pids.get(holder) in row.get("blockers", []):
                self.record("one_way_wait", waiter=waiter, holder=holder, **snapshot)
                if fragment is not None:
                    assert fragment in row["query"], row
                assert self.pids[waiter] not in rows[self.pids[holder]]["blockers"]
                return row
            sleep(0.02)
        self.record("wait_timeout", **self.snapshot())
        raise AssertionError(f"No {waiter} -> {holder} wait on {fragment}")

    def close(self):
        self.release.set()
        _, pending = wait(self.futures, timeout=18)
        if pending:
            with self.observer.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                for pid in self.pids.values():
                    conn.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
            _, pending = wait(self.futures, timeout=5)
        self.pool.shutdown(wait=True, cancel_futures=True)
        for name, callback in self.hooks:
            event.remove(self.engine, name, callback)
        snapshot = self.snapshot()
        self.observer.dispose()
        self.record("cleanup", pending=len(pending), **snapshot)
        assert not pending
        assert not any(row["xact_start"] for row in snapshot["activity"])


@pytest.fixture
def race(pg_engine, request, tmp_path_factory, autoflush):
    configured_directory = os.environ.get("CASEOPS_ACTOR_AUDIT_DIR")
    directory = (
        Path(configured_directory)
        if configured_directory
        else tmp_path_factory.mktemp("caseops-race-evidence")
    )
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (sha256(request.node.nodeid.encode()).hexdigest()[:20] + ".jsonl")
    with path.open("x", encoding="utf-8") as evidence:
        harness = _Race(pg_engine, evidence, autoflush)
        harness.record("test", nodeid=request.node.nodeid)
        try:
            yield harness
        finally:
            harness.close()


def _fixture(engine, source="matter", *, active=True):
    with Session(engine) as seed:
        company = _seed_company(seed)
        actor = _seed_membership(seed, company, role="admin")
        owner = _seed_membership(seed, company, role="owner")
        matter = _seed_matter(seed, company)
        attachment = MatterAttachment(
            matter_id=matter,
            uploaded_by_membership_id=actor,
            original_filename="admission.txt",
            storage_key=f"admission/{uuid4()}",
            content_type="text/plain",
            size_bytes=23,
            sha256_hex="a" * 64,
            document_type="other",
        )
        seed.add(attachment)
        seed.flush()
        target_id = attachment.id
        target_type = DocumentProcessingTargetType.MATTER_ATTACHMENT
        if source == "ip":
            taxonomy = IpDocumentTaxonomyEntry(
                company_id=company,
                key="admission",
                label="Admission",
                updated_by_membership_id=actor,
            )
            seed.add(taxonomy)
            seed.flush()
            document = IpDocument(
                company_id=company,
                taxonomy_entry_id=taxonomy.id,
                title="IP worker historical source",
                created_by_membership_id=actor,
            )
            seed.add(document)
            seed.flush()
            version = IpDocumentVersion(
                company_id=company,
                document_id=document.id,
                version=1,
                original_filename="ip-source.txt",
                display_name="ip-source.txt",
                storage_key=f"admission/{uuid4()}",
                content_type="text/plain",
                size_bytes=23,
                sha256_hex="b" * 64,
                uploaded_by_membership_id=actor,
            )
            seed.add(version)
            seed.flush()
            target_id = version.id
            target_type = DocumentProcessingTargetType.IP_DOCUMENT_VERSION
        job = DocumentProcessingJob(
            company_id=company,
            requested_by_membership_id=actor,
            target_type=target_type,
            attachment_id=target_id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        seed.add(job)
        if active:
            ensure_active_private_generation(seed, company_id=company)
        seed.commit()
        return SimpleNamespace(
            company=company,
            actor=actor,
            owner=owner,
            matter=matter,
            attachment=attachment.id,
            job=job.id,
            target_id=target_id,
            updated=seed.get(Matter, matter).updated_at,
        )


def _mutate(session, fixture, mutation, *, context=None):
    context = context or _ip_race_context(
        session, company_id=fixture.company, membership_id=fixture.actor
    )
    if mutation == "create":
        return matters.create_matter(
            session,
            context=context,
            payload=MatterCreateRequest(
                title="Admitted creation",
                matter_code=f"NEW-{uuid4().hex[:10]}",
                practice_area="Civil",
                forum_level="high_court",
            ),
        )
    if mutation == "metadata":
        return matters.update_matter(
            session,
            context=context,
            matter_id=fixture.matter,
            payload=MatterUpdateRequest(
                title="Admitted metadata", expected_updated_at=fixture.updated
            ),
        )
    return matters.transition_matter_lifecycle_status(
        session,
        context=context,
        matter_id=fixture.matter,
        payload=MatterLifecycleStatusRequest(
            to_status="disposed",
            expected_from_status="active",
            expected_updated_at=fixture.updated,
            reason="Admission race lifecycle proof.",
        ),
    )


def _provider(monkeypatch, race, fixture, *, fail=False):
    def parse(*args):
        assert not any("FOR NO KEY UPDATE" in sql for sql in race.sql.get("worker", []))
        return document_processing.ParsedDocument(
            status="indexed", extracted_text="Local text", chunks=["Local text"], error=None
        )

    def embed(chunks):
        assert not any("FOR NO KEY UPDATE" in sql for sql in race.sql.get("worker", []))
        race.record("provider_without_company_fence", chunks=chunks)
        if fail:
            raise embeddings.EmbeddingProviderError("Local deterministic provider outage")
        return SimpleNamespace(vectors=[[0.01] * 1024], model="local-fixture", dimensions=1024)

    monkeypatch.setattr(document_processing, "parse_attachment", parse)
    monkeypatch.setattr(embeddings, "build_provider", lambda: SimpleNamespace(embed=embed))
    monkeypatch.setattr(
        document_jobs, "get_session_factory", lambda: lambda: race.session("worker")
    )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "matter"])
@pytest.mark.parametrize("mutation", ["metadata", "dispose"])
def test_matter_worker_private_event_serializes(pg_engine, monkeypatch, race, first, mutation):
    fixture = _fixture(pg_engine)
    _provider(monkeypatch, race, fixture)
    race.pause_role = first
    race.predicate = lambda sql: "FROM companies" in sql and "FOR NO KEY UPDATE" in sql

    def matter_write():
        with race.session("matter") as session:
            return _mutate(session, fixture, mutation).status

    operations = {
        "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
        "matter": matter_write,
    }
    second = "matter" if first == "worker" else "worker"
    first_future = race.submit(first, operations[first])
    assert race.paused.wait(10)
    second_future = race.submit(second, operations[second])
    race.blocked(second, first, "FROM companies")
    race.release.set()
    first_future.result(timeout=15)
    second_future.result(timeout=15)
    with Session(pg_engine) as verify:
        matter = verify.get(Matter, fixture.matter)
        job = verify.get(DocumentProcessingJob, fixture.job)
        attachment = verify.get(MatterAttachment, fixture.attachment)
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        worker_events = [row for row in events if row.target_id == fixture.attachment]
        rejected = first == "matter" and mutation == "dispose"
        assert job.status == ("failed" if rejected else "completed")
        assert matter.status == ("disposed" if mutation == "dispose" else "active")
        assert matter.is_active == (mutation != "dispose")
        assert matter.lifecycle_version == (1 if mutation == "dispose" else 0)
        assert len(worker_events) == (0 if rejected else 1)
        assert all(row.actor_membership_id == fixture.actor for row in events)
        chunks = list(
            verify.scalars(
                select(MatterAttachmentChunk).where(
                    MatterAttachmentChunk.attachment_id == fixture.attachment
                )
            )
        )
        assert len(chunks) == (0 if rejected else 1)
        assert attachment.extracted_text == (None if rejected else "Local text")
        race.record(
            "persistence",
            job=job.status,
            matter=matter.status,
            actors=[row.actor_membership_id for row in events],
            chunks=len(chunks),
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["admin", "matter"])
@pytest.mark.parametrize("revocation", ["membership", "user-disablement", "role"])
@pytest.mark.parametrize("mutation", ["create", "metadata", "dispose"])
def test_live_admin_revocation_serializes(pg_engine, race, first, revocation, mutation):
    fixture = _fixture(pg_engine)
    if revocation == "membership":
        with Session(pg_engine) as seed:
            actor = seed.get(CompanyMembership, fixture.actor)
            other_company = _seed_company(seed)
            seed.add(
                CompanyMembership(
                    company_id=other_company, user_id=actor.user_id, role="member", is_active=True
                )
            )
            seed.commit()
    race.pause_role = first
    # Admin still uses the existing Membership/User fence; this test must not
    # substitute a manual lock for its real deactivation service.
    race.predicate = lambda sql: "FROM users" in sql and "FOR UPDATE" in sql
    loaded = Event()

    def matter_write():
        with race.session("matter") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            assert context.membership.is_active and context.user.is_active
            loaded.set()
            try:
                _mutate(session, fixture, mutation, context=context)
                return 200
            except HTTPException as exc:
                assert exc.status_code == 403, exc.detail
                session.rollback()
                return exc.status_code

    def revoke():
        with race.session("admin") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.owner
            )
            return identity.update_company_user(
                session,
                context=context,
                membership_id=fixture.actor,
                payload=(
                    CompanyUserUpdateRequest(role="viewer")
                    if revocation == "role"
                    else CompanyUserUpdateRequest(is_active=False)
                ),
            )

    if first == "admin":
        admin_future = race.submit("admin", revoke)
        assert race.paused.wait(10)
        matter_future = race.submit("matter", matter_write)
        assert loaded.wait(5)
        race.blocked("matter", "admin", "FROM company_memberships")
    else:
        matter_future = race.submit("matter", matter_write)
        assert race.paused.wait(10)
        admin_future = race.submit("admin", revoke)
        race.blocked("admin", "matter", "FROM company_memberships")
    race.release.set()
    assert matter_future.result(timeout=15) == (403 if first == "admin" else 200)
    admin_future.result(timeout=15)
    with Session(pg_engine) as verify:
        actor = verify.get(CompanyMembership, fixture.actor)
        assert actor.is_active == (revocation == "role")
        assert actor.user.is_active == (revocation != "user-disablement")
        if revocation == "role":
            assert actor.role == "viewer"
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        assert len(events) == (0 if first == "admin" else 1)
        assert all(row.actor_membership_id == fixture.actor for row in events)
        race.record(
            "revocation_persistence",
            membership_active=actor.is_active,
            user_active=actor.user.is_active,
            events=len(events),
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("provider_failure", [False, True])
@pytest.mark.parametrize("source", ["matter", "ip"])
def test_matter_worker_retains_revoked_historical_actor(
    pg_engine,
    monkeypatch,
    race,
    provider_failure,
    source,
):
    fixture = _fixture(pg_engine, source)
    with Session(pg_engine) as session:
        context = _ip_race_context(session, company_id=fixture.company, membership_id=fixture.owner)
        identity.update_company_user(
            session,
            context=context,
            membership_id=fixture.actor,
            payload=CompanyUserUpdateRequest(is_active=False),
        )
    _provider(monkeypatch, race, fixture, fail=provider_failure)
    race.submit("worker", lambda: document_jobs.run_document_processing_job(fixture.job)).result(15)
    with Session(pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        assert len(events) == 1
        assert events[0].actor_membership_id == fixture.actor
        assert not verify.get(CompanyMembership, fixture.actor).is_active


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "outer"])
@pytest.mark.parametrize("workflow", ["create", "bulk-preview", "bulk-apply", "import", "intake"])
def test_outer_matter_writers_enter_before_actor_or_savepoint(
    pg_engine,
    monkeypatch,
    race,
    first,
    workflow,
):
    fixture = _fixture(pg_engine)
    _provider(monkeypatch, race, fixture)
    with Session(pg_engine) as seed:
        other_matter = _seed_matter(seed, fixture.company)
        seed.commit()
        codes = [seed.get(Matter, key).matter_code for key in (fixture.matter, other_matter)]
        context = _ip_race_context(seed, company_id=fixture.company, membership_id=fixture.actor)
        manifest = io.StringIO()
        writer = csv.DictWriter(manifest, fieldnames=matter_bulk_updates.HEADERS)
        writer.writeheader()
        for code in codes:
            writer.writerow({"Matter Code": code, "Matter Title": "Outer admitted update"})
        content = manifest.getvalue().encode()
        preview = matter_bulk_updates.preview_matter_bulk_update(
            seed, context=context, content=content, filename="outer.csv"
        )
        assert preview.summary.changed_rows == 2
        token = preview.preview_token
        seed.rollback()
        import_preview = matter_imports.preview_matter_import(
            seed,
            context=context,
            filename="new.csv",
            content_type="text/csv",
            content=(
                b"Matter Title,Matter Code,Practice Area,Matter Status,Client Name,Forum\n"
                b"First imported matter,IMPORT-1,Civil,active,Import Client,high_court\n"
                b"Second imported matter,IMPORT-2,Civil,active,Import Client,high_court\n"
            ),
        )
        assert import_preview.valid_rows == 2, import_preview
        job_id = import_preview.id
        intake_row = intake.create_intake_request(
            seed,
            context=context,
            payload=IntakeRequestCreateRequest(
                title="Intake admission",
                requester_name="Local user",
                description="Local retained intake description.",
            ),
        )
        intake_id = intake_row.id
        seed.commit()

    def outer_write():
        with race.session("outer") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            if workflow == "create":
                return _mutate(session, fixture, "create", context=context)
            if workflow == "import":
                result = matter_imports.commit_matter_import(
                    session, context=context, job_id=job_id
                )
                assert len(result.created_matter_ids) == 2
                return result
            if workflow == "intake":
                result = intake.promote_intake_request(
                    session,
                    context=context,
                    request_id=intake_id,
                    payload=IntakeRequestPromoteRequest(matter_code="INTAKE-ADMISSION"),
                )
                assert result.linked_matter_id
                session.commit()
                return result
            if workflow == "bulk-preview":
                result = matter_bulk_updates.preview_matter_bulk_update(
                    session, context=context, content=content, filename="outer.csv"
                )
                assert result.summary.changed_rows == 2
                return result
            result = matter_bulk_updates.apply_matter_bulk_update(
                session, context=context, content=content, filename="outer.csv", preview_token=token
            )
            assert result.applied_rows == 2
            return result

    race.pause_role = first
    race.after = first == "outer"
    race.predicate = (
        (lambda sql: "FROM companies" in sql and "FOR NO KEY UPDATE" in sql)
        if first == "outer"
        else (lambda sql: sql.startswith("INSERT INTO private_projection_events"))
    )
    operations = {
        "outer": outer_write,
        "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
    }
    second = "outer" if first == "worker" else "worker"
    a = race.submit(first, operations[first])
    assert race.paused.wait(10)
    b = race.submit(second, operations[second])
    race.blocked(second, first, "FROM companies")
    with race.observer.begin() as probe:
        probe.execute(
            text("SELECT id FROM company_memberships WHERE id=:id FOR KEY SHARE NOWAIT"),
            {"id": fixture.actor},
        )
    race.release.set()
    a.result(15)
    b.result(15)
    admitted = False
    admissions, commits = 0, 0
    for sql in race.sql["outer"]:
        if sql == "COMMIT":
            admitted = False
            commits += 1
        elif "FROM companies" in sql and "FOR NO KEY UPDATE" in sql:
            admitted = True
            admissions += 1
        elif ("FROM company_memberships" in sql and "FOR UPDATE" in sql) or sql.startswith(
            "SAVEPOINT"
        ):
            assert admitted, sql
    if workflow == "import":
        assert commits >= 4 and admissions >= 5
    with Session(pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        for key in (fixture.matter, other_matter):
            assert verify.get(Matter, key).title == (
                "Outer admitted update" if workflow == "bulk-apply" else "Test Matter"
            )
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        assert (
            len(events)
            == {
                "create": 2,
                "bulk-preview": 1,
                "bulk-apply": 3,
                "import": 3,
                "intake": 2,
            }[workflow]
        )
        assert all(row.actor_membership_id == fixture.actor for row in events)


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("mutation", ["metadata", "dispose"])
@pytest.mark.parametrize("rejection", ["stale", "cross-tenant"])
def test_matter_admission_keeps_stale_and_tenant_checks(pg_engine, race, mutation, rejection):
    fixture = _fixture(pg_engine)
    with Session(pg_engine) as seed:
        if rejection == "stale":
            seed.get(Matter, fixture.matter).title = "Newer persisted title"
        else:
            fixture.matter = _seed_matter(seed, _seed_company(seed))
        seed.commit()
        original = seed.get(Matter, fixture.matter)
        retained = (original.title, original.status, original.is_active, original.lifecycle_version)
    with race.session("matter") as session:
        with pytest.raises(HTTPException) as error:
            _mutate(session, fixture, mutation)
        assert error.value.status_code == (409 if rejection == "stale" else 404)
        session.rollback()
    with Session(pg_engine) as verify:
        row = verify.get(Matter, fixture.matter)
        assert (row.title, row.status, row.is_active, row.lifecycle_version) == retained
        assert not list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "note"])
def test_matter_worker_historical_actor_precedes_parent(pg_engine, monkeypatch, race, first):
    fixture = _fixture(pg_engine)
    _provider(monkeypatch, race, fixture)
    race.pause_role = first
    race.after = first == "note"
    race.predicate = (
        (lambda sql: "FROM users" in sql and "FOR UPDATE" in sql)
        if first == "note"
        else (lambda sql: sql.startswith("INSERT INTO private_projection_events"))
    )

    def note_write():
        with race.session("note") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.actor
            )
            return matters.create_matter_note(
                session,
                context=context,
                matter_id=fixture.matter,
                payload=MatterNoteCreateRequest(body="Local note"),
            )

    operations = {
        "note": note_write,
        "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
    }
    second = "note" if first == "worker" else "worker"
    a = race.submit(first, operations[first])
    assert race.paused.wait(10)
    b = race.submit(second, operations[second])
    waiting = race.blocked(second, first, None)
    race.release.set()
    if first == "worker" and "FROM matters" in waiting["query"]:
        # Retain the exact pre-repair reverse edge rather than guessing a cycle.
        deadline = monotonic() + 0.9
        while monotonic() < deadline:
            snapshot = race.snapshot()
            rows = {row["pid"]: row for row in snapshot["activity"]}
            if race.pids["note"] in rows.get(race.pids["worker"], {}).get(
                "blockers", []
            ) and race.pids["worker"] in rows.get(race.pids["note"], {}).get("blockers", []):
                race.record("historical_actor_parent_cycle", **snapshot)
                break
            sleep(0.01)
    a.result(15)
    b.result(15)
    assert "FROM company_memberships" in waiting["query"], waiting
    with Session(pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        event_row = verify.scalar(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.company_id == fixture.company
            )
        )
        assert event_row.actor_membership_id == fixture.actor


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "offboarding"])
@pytest.mark.parametrize("source", ["matter", "ip"])
def test_matter_worker_serializes_real_offboarding_parent_locks(
    pg_engine,
    monkeypatch,
    race,
    first,
    source,
):
    fixture = _fixture(pg_engine, source)
    with Session(pg_engine) as seed:
        seed.get(Matter, fixture.matter).assignee_membership_id = fixture.actor
        seed.commit()
    _provider(monkeypatch, race, fixture)
    race.pause_role = first
    race.after = first == "offboarding"
    race.predicate = (
        (lambda sql: "FROM users" in sql and "FOR UPDATE" in sql)
        if first == "offboarding"
        else (lambda sql: sql.startswith("INSERT INTO private_projection_events"))
    )

    def offboard():
        with race.session("offboarding") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.owner
            )
            return employees.commit_employee_offboarding(
                session,
                context=context,
                membership_id=fixture.actor,
                payload=EmployeeOffboardingRequest(reassign_to_membership_id=fixture.owner),
            )

    operations = {
        "offboarding": offboard,
        "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
    }
    second = "offboarding" if first == "worker" else "worker"
    a = race.submit(first, operations[first])
    assert race.paused.wait(10)
    b = race.submit(second, operations[second])
    race.blocked(second, first, "FROM company_memberships")
    race.release.set()
    a.result(15)
    b.result(15)
    assert any("FROM matters" in sql and "FOR UPDATE" in sql for sql in race.sql["offboarding"])
    with Session(pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        assert not verify.get(CompanyMembership, fixture.actor).is_active
        assert verify.get(Matter, fixture.matter).assignee_membership_id == fixture.owner
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        assert len(events) == 1 and events[0].actor_membership_id == fixture.actor


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("active", [False, True])
def test_matter_worker_missing_legacy_actor_is_explicit(pg_engine, monkeypatch, race, active):
    fixture = _fixture(pg_engine, active=active)
    with Session(pg_engine) as seed:
        assert not hasattr(Matter, "created_by_membership_id")
        seed.get(DocumentProcessingJob, fixture.job).requested_by_membership_id = None
        seed.get(MatterAttachment, fixture.attachment).uploaded_by_membership_id = None
        seed.commit()
    _provider(monkeypatch, race, fixture)
    race.submit("worker", lambda: document_jobs.run_document_processing_job(fixture.job)).result(15)
    with Session(pg_engine) as verify:
        job = verify.get(DocumentProcessingJob, fixture.job)
        assert job.status == ("failed" if active else "completed")
        if active:
            assert "provenance" in job.error_message.lower()
        attachment = verify.get(MatterAttachment, fixture.attachment)
        assert attachment.extracted_text == (None if active else "Local text")
        assert not list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )


@pytest.mark.parametrize("autoflush", [False, True])
def test_matter_worker_rejects_cross_tenant_event_actor(pg_engine, monkeypatch, race):
    fixture = _fixture(pg_engine)
    with Session(pg_engine) as seed:
        foreign_actor = _seed_membership(seed, _seed_company(seed), role="admin")
        seed.get(DocumentProcessingJob, fixture.job).requested_by_membership_id = foreign_actor
        seed.commit()
    _provider(monkeypatch, race, fixture)
    race.submit("worker", lambda: document_jobs.run_document_processing_job(fixture.job)).result(15)
    with Session(pg_engine) as verify:
        job = verify.get(DocumentProcessingJob, fixture.job)
        assert job.status == "failed"
        assert "does not belong to the company" in job.error_message
        assert verify.get(MatterAttachment, fixture.attachment).extracted_text is None
        assert not list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )


@pytest.mark.parametrize("autoflush", [False, True])
@pytest.mark.parametrize("first", ["worker", "offboarding"])
@pytest.mark.parametrize("active", [False, True])
@pytest.mark.parametrize("retained", ["matter-uploader", "ip-requester", "ip-locker"])
def test_worker_retained_membership_fks_precede_source(
    pg_engine, monkeypatch, race, first, active, retained
):
    source = "matter" if retained == "matter-uploader" else "ip"
    fixture = _fixture(pg_engine, source, active=active)
    with Session(pg_engine) as seed:
        historical_actor = _seed_membership(seed, fixture.company, role="member")
        seed.get(Matter, fixture.matter).assignee_membership_id = historical_actor
        if retained == "matter-uploader":
            seed.get(
                MatterAttachment, fixture.attachment
            ).uploaded_by_membership_id = historical_actor
        elif retained == "ip-requester":
            seed.get(
                DocumentProcessingJob, fixture.job
            ).requested_by_membership_id = historical_actor
        else:
            seed.get(
                IpDocumentVersion, fixture.target_id
            ).locked_by_membership_id = historical_actor
            seed.get(
                DocumentProcessingJob, fixture.job
            ).requested_by_membership_id = _seed_membership(seed, fixture.company, role="member")
        seed.commit()
    _provider(monkeypatch, race, fixture)
    source_table = "matter_attachments" if source == "matter" else "ip_document_versions"
    race.pause_role = first
    race.after = first == "offboarding"
    race.predicate = (
        (lambda sql: "FROM users" in sql and "FOR UPDATE" in sql)
        if first == "offboarding"
        else (lambda sql: sql.startswith(f"UPDATE {source_table} "))
    )

    def offboard():
        with race.session("offboarding") as session:
            context = _ip_race_context(
                session, company_id=fixture.company, membership_id=fixture.owner
            )
            return employees.commit_employee_offboarding(
                session,
                context=context,
                membership_id=historical_actor,
                payload=EmployeeOffboardingRequest(reassign_to_membership_id=fixture.owner),
            )

    operations = {
        "offboarding": offboard,
        "worker": lambda: document_jobs.run_document_processing_job(fixture.job),
    }
    second = "offboarding" if first == "worker" else "worker"
    a = race.submit(first, operations[first])
    assert race.paused.wait(10)
    b = race.submit(second, operations[second])
    race.blocked(second, first, "FROM company_memberships")
    race.release.set()
    a.result(15)
    b.result(15)
    sql = race.sql["worker"]
    source_write = next(
        i for i, query in enumerate(sql) if query.startswith(f"UPDATE {source_table} ")
    )
    provenance_locks = [
        i
        for i, query in enumerate(sql)
        if "FROM company_memberships" in query and "FOR KEY SHARE" in query
    ]
    assert provenance_locks and max(provenance_locks) < source_write
    assert all("ORDER BY company_memberships.id" in sql[i] for i in provenance_locks)
    if source == "matter":
        parent_lock = next(
            i for i, query in enumerate(sql) if "FROM matters" in query and "FOR SHARE" in query
        )
        assert max(provenance_locks) < parent_lock
    # The real worker claims then finalizes the job in separate transactions.
    # Record the actual flush inventory, without injecting extra dirty writes.
    job_updates = [query for query in sql if query.startswith("UPDATE document_processing_jobs ")]
    source_updates = [query for query in sql if query.startswith(f"UPDATE {source_table} ")]
    assert len(job_updates) == 2 and len(source_updates) == 1
    race.record(
        "retained_fk_flush_inventory",
        job_updates=job_updates,
        source_updates=source_updates,
        foreign_keys={
            model.__tablename__: [
                sorted(
                    (element.parent.name, element.target_fullname)
                    for element in constraint.elements
                )
                for constraint in model.__table__.foreign_key_constraints
            ]
            for model in (
                DocumentProcessingJob,
                MatterAttachment,
                MatterAttachmentChunk,
                IpDocumentVersion,
            )
        },
    )
    with Session(pg_engine) as verify:
        assert verify.get(DocumentProcessingJob, fixture.job).status == "completed"
        assert not verify.get(CompanyMembership, historical_actor).is_active
        assert verify.get(Matter, fixture.matter).assignee_membership_id == fixture.owner
        events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == fixture.company
                )
            )
        )
        assert len(events) == int(active)
        assert all(row.actor_membership_id == fixture.actor for row in events)
