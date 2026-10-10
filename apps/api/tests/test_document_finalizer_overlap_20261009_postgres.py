"""Actual finalizer/identity overlap: local susceptibility, not Cloud Run CPU proof.

CASEOPS_FINALIZER_AUTH_BASELINE=strong replays only the former auth lock option
in this process. It intentionally makes the same login acceptance fail; no
runtime file, live service, provider, or transaction fence is replaced.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from caseops_api.core.security import hash_password
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AssistantSession,
    AssistantTurn,
    Company,
    CompanyMembership,
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    IpDocument,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    Matter,
    MatterAttachment,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateProjectionEvent,
    PrivateSavedOutputAccess,
    User,
)
from caseops_api.db.session import get_db_session
from caseops_api.main import create_application
from caseops_api.schemas.matters import MatterLifecycleStatusRequest, MatterUpdateRequest
from caseops_api.services import (
    document_jobs,
    document_processing,
    identity,
    matters,
    private_retrieval,
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
_SOURCE = "Deterministic local source; no external scanner, storage or model transport."
_PASSWORD = "FinalizerLocal20261009!"


def _seed_saved_source(session, company_id, actor_id, generation, source_type, source_id):
    assistant = AssistantSession(
        company_id=company_id, created_by_membership_id=actor_id,
        title="Finalizer retained output", policy_version=1,
        retention_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    session.add(assistant)
    session.flush()
    turn = AssistantTurn(
        company_id=company_id, session_id=assistant.id, sequence=1,
        role="assistant", status="completed", created_by_membership_id=actor_id,
    )
    session.add(turn)
    session.flush()
    row = PrivateSavedOutputAccess(
        company_id=company_id, assistant_turn_id=turn.id, generation_id=generation.id,
        source_type=source_type, source_id=source_id, source_version="1",
        source_sha256=sha256(_SOURCE.encode()).hexdigest(),
        access_policy_generation=generation.access_policy_generation,
        tombstone_generation=generation.tombstone_generation, state="accessible",
    )
    session.add(row)
    session.flush()
    return row.id


def _seed_projection(session, company_id, generation, source_type, source_id):
    row = PrivateIndexProjection(
        company_id=company_id, generation_id=generation.id,
        source_type=source_type, source_id=source_id, source_version="1",
        chunk_ordinal=0, label="Finalizer retained projection", content_text=_SOURCE,
        content_sha256=sha256(_SOURCE.encode()).hexdigest(),
        access_policy_generation=generation.access_policy_generation,
        tombstone_generation=generation.tombstone_generation,
        embedding_dimensions=3, embedding_json="[1.0,0.0,0.0]", is_tombstoned=False,
    )
    session.add(row)
    session.flush()
    return row.id


def _seed_finalizer(engine, target):
    with Session(engine, expire_on_commit=False) as session:
        company_id = _seed_company(session)
        actor_id = _seed_membership(session, company_id, role="admin")
        actor = session.get(CompanyMembership, actor_id)
        user = session.get(User, actor.user_id)
        user.password_hash = hash_password(_PASSWORD)
        matter_id = _seed_matter(session, company_id)
        unrelated_id = _seed_matter(session, company_id)
        initial_versions = {
            row_id: session.get(Matter, row_id).lifecycle_version
            for row_id in (matter_id, unrelated_id)
        }
        assert set(initial_versions.values()) == {0}, "Establish the legacy fixture state"
        initial_updated_at = session.get(Matter, unrelated_id).updated_at
        source_hash = sha256(_SOURCE.encode()).hexdigest()
        if target == "matter":
            attachment = MatterAttachment(
                matter_id=matter_id, uploaded_by_membership_id=actor_id,
                original_filename="finalizer.txt", storage_key=f"finalizer/{uuid4()}.txt",
                content_type="text/plain", size_bytes=len(_SOURCE), sha256_hex=source_hash,
            )
            session.add(attachment)
            session.flush()
            source_type, source_id = "matter_document", attachment.id
            target_type = DocumentProcessingTargetType.MATTER_ATTACHMENT
        else:
            taxonomy = IpDocumentTaxonomyEntry(
                company_id=company_id, key="finalizer", label="Finalizer source",
                updated_by_membership_id=actor_id,
            )
            session.add(taxonomy)
            session.flush()
            document = IpDocument(
                company_id=company_id, taxonomy_entry_id=taxonomy.id,
                title="Finalizer IP source", created_by_membership_id=actor_id,
            )
            session.add(document)
            session.flush()
            attachment = IpDocumentVersion(
                company_id=company_id, document_id=document.id, version=1,
                original_filename="finalizer.txt", display_name="finalizer.txt",
                storage_key=f"finalizer/{uuid4()}.txt", content_type="text/plain",
                size_bytes=len(_SOURCE), sha256_hex=source_hash,
                uploaded_by_membership_id=actor_id,
            )
            session.add(attachment)
            session.flush()
            source_type, source_id = "ip_document", document.id
            target_type = DocumentProcessingTargetType.IP_DOCUMENT_VERSION
        job = DocumentProcessingJob(
            company_id=company_id, requested_by_membership_id=actor_id,
            target_type=target_type, attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        session.add(job)
        active = ensure_active_private_generation(session, company_id=company_id)
        retired = PrivateIndexGeneration(
            company_id=company_id, generation_number=2, state="retired",
        )
        shadow = PrivateIndexGeneration(
            company_id=company_id, generation_number=3, state="building",
        )
        session.add_all([retired, shadow])
        session.flush()
        active_projection = _seed_projection(session, company_id, active, source_type, source_id)
        retired_projection = _seed_projection(session, company_id, retired, source_type, source_id)
        if target == "matter":
            session.add(PrivateIndexProjectionScope(
                company_id=company_id, projection_id=active_projection,
                scope_type="matter", scope_id=matter_id, matter_id=matter_id,
            ))
        outputs = [_seed_saved_source(session, company_id, actor_id, generation,
                                      source_type, source_id) for generation in (active, retired)]
        other_company = _seed_company(session)
        other_actor = _seed_membership(session, other_company, role="admin")
        other_generation = ensure_active_private_generation(session, company_id=other_company)
        other_projection = _seed_projection(session, other_company, other_generation,
                                            source_type, source_id)
        other_output = _seed_saved_source(session, other_company, other_actor, other_generation,
                                         source_type, source_id)
        session.commit()
        return {
            "company_id": company_id, "actor_id": actor_id, "user_id": user.id,
            "slug": session.get(Company, company_id).slug, "email": user.email,
            "matter_id": matter_id, "unrelated_id": unrelated_id,
            "initial_versions": initial_versions,
            "unrelated_updated_at": initial_updated_at, "job_id": job.id,
            "attachment_id": attachment.id, "source_type": source_type,
            "source_id": source_id, "generation_id": active.id,
            "shadow_id": shadow.id, "initial_epoch": active.tombstone_generation,
            "active_projection": active_projection, "retired_projection": retired_projection,
            "outputs": outputs, "other_projection": other_projection,
            "other_output": other_output, "target": target,
        }


class _FinalizerAudit:
    def __init__(self, engine, record):
        self.engine, self.record = engine, record
        self.entered, self.release = Event(), Event()
        self.boundary = "applied"
        self.pids, self.errors, self.statements = {}, [], {}
        self.statement_counts = {}
        self.all_pids = set()
        self.instance = f"finalizer-{uuid4().hex[:12]}"
        self.names = {role: f"{self.instance}-{role}"
                      for role in ("worker", "login", "mutation", "revocation", "auth")}
        self.factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.hooks = [("before_cursor_execute", self.before),
                      ("after_cursor_execute", self.after), ("handle_error", self.error)]

    def session(self, role):
        session = self.factory()
        session.info["finalizer_role"] = role

        def label(_session, _transaction, connection):
            connection.info["finalizer_role"] = role
            connection.execute(text("SELECT set_config('application_name', :name, true)"),
                               {"name": self.names[role]})
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            self.pids[role] = pid
            self.all_pids.add(pid)
            self.record("transaction_started", role=role, pid=pid, instance=self.instance)

        event.listen(session, "after_begin", label)
        event.listen(session, "after_commit", lambda _session: self.record(
            "transaction_committed", role=role, pid=self.pids.get(role)))
        return session

    def before(self, connection, _cursor, sql, _parameters, _context, _many):
        role = connection.info.get("finalizer_role")
        if role in self.names:
            self.statement_counts[role] = self.statement_counts.get(role, 0) + 1
        election = (
            sql.startswith("SELECT ")
            and "ORDER BY company_memberships.created_at ASC" in sql
        )
        if role in self.names and (
            election or "FOR " in sql or sql.startswith(("INSERT", "UPDATE"))
        ):
            self.statements.setdefault(role, []).append(sql)
            # Only statement templates: never parameters, document text or auth bodies.
            self.record("sql_before", role=role, pid=self.pids.get(role), sql=sql)

    def after(self, connection, _cursor, sql, parameters, _context, _many):
        role = connection.info.get("finalizer_role")
        if role == "worker" and self.boundary == "applied" and (
            sql.startswith("UPDATE private_projection_events")
            and isinstance(parameters, dict) and parameters.get("status") == "applied"
            and not self.entered.is_set()
        ):
            self.record("actual_private_event_applied_sql", pid=self.pids[role], sql=sql)
            self.entered.set()
            started = monotonic()
            released = self.release.wait(8)
            self.record("finalizer_pause_returned", role=role, released=released,
                        held_seconds=monotonic() - started)
            assert released, "Actual finalizer SQL boundary was not released"

    def error(self, context):
        original = context.original_exception
        row = {"sqlstate": getattr(original, "sqlstate", None),
               "native_message": getattr(getattr(original, "diag", None), "message_primary", None),
               "sql": context.statement}
        self.errors.append(row)
        role = context.connection.info.get("finalizer_role")
        self.record("native_database_error", role=role, pid=self.pids.get(role), **row)

    def snapshot(self):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            rows = observer.execute(text(
                "SELECT pid, application_name, state, backend_xid, xact_start, "
                "wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers "
                "FROM pg_stat_activity WHERE application_name LIKE :prefix"
            ), {"prefix": self.instance + "-%"}).mappings().all()
            return [dict(row) for row in rows]

    def await_blocker(self, waiter, holder):
        deadline = monotonic() + 1.5
        while monotonic() < deadline:
            rows = self.snapshot()
            match = next((row for row in rows if row["pid"] == self.pids.get(waiter)), None)
            if match and self.pids.get(holder) in match["blockers"]:
                self.record("directed_blocker", waiter=waiter, holder=holder, activity=rows)
                return
            sleep(0.01)
        self.record("blocker_not_observed", activity=self.snapshot())
        raise AssertionError(f"Actual {waiter} -> {holder} PostgreSQL wait was not observed")

    def retained_locks(self):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            return [dict(row) for row in observer.execute(text(
                "SELECT pid, locktype, mode, granted FROM pg_locks WHERE pid = ANY(:pids)"
            ), {"pids": sorted(self.all_pids)}).mappings()]

    def worker(self, fixture):
        document_jobs.run_document_processing_job(fixture["job_id"])
        self.record("worker_returned", completed_at=datetime.now(UTC).isoformat())

    def mutate(self, fixture, operation="metadata", *, source=False):
        with self.session("mutation") as session:
            context = _ip_race_context(session, company_id=fixture["company_id"],
                                       membership_id=fixture["actor_id"])
            matter_id = fixture["matter_id"] if source else fixture["unrelated_id"]
            row = session.get(Matter, matter_id)
            if operation == "metadata":
                matters.update_matter(session, context=context, matter_id=matter_id,
                                      payload=MatterUpdateRequest(
                                          title="Unrelated finalizer overlap mutation",
                                          expected_updated_at=row.updated_at))
            else:
                matters.transition_matter_lifecycle_status(
                    session, context=context, matter_id=matter_id,
                    payload=MatterLifecycleStatusRequest(
                        to_status="disposed", expected_from_status="active",
                        expected_updated_at=row.updated_at,
                        reason="Deterministic finalizer lifecycle winner."))
        self.record("mutation_committed", operation=operation,
                    completed_at=datetime.now(UTC).isoformat())

    @contextmanager
    def pool(self):
        pool = ThreadPoolExecutor(max_workers=3)
        futures = []
        try:
            yield pool, futures
        finally:
            self.release.set()
            _, pending = wait(futures, timeout=12)
            pool.shutdown(wait=True, cancel_futures=True)
            self.record("contenders_completed", pending=len(pending))
            assert not pending, "Owned contender did not terminate"


def _finalizer_evidence_path(directory: Path, nodeid: str) -> Path:
    identity_hash = sha256(nodeid.encode("utf-8")).hexdigest()[:20]
    return directory / f"{identity_hash}-{uuid4().hex}.jsonl"


def test_finalizer_journal_names_are_bounded_unique_and_retain_full_identity(tmp_path):
    directory = tmp_path / ("native-" + "n" * 42) / ("transactions-" + "t" * 24)
    directory.mkdir(parents=True)
    nodeid = "tests/native.py::test_" + "long_test_identity_" * 40 + "[retained-source]"
    paths = [_finalizer_evidence_path(directory, nodeid) for _ in range(2)]
    assert paths[0] != paths[1]
    for path in paths:
        assert len(path.name) == 59
        assert path.name.startswith(sha256(nodeid.encode()).hexdigest()[:20] + "-")
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps({"nodeid": nodeid, "evidence_path": str(path)}) + "\n")
        receipt = json.loads(path.read_text(encoding="utf-8"))
        assert receipt["nodeid"] == nodeid and receipt["evidence_path"] == str(path)


def test_finalizer_election_receipt_keeps_sql_template_not_parameters():
    receipts = []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    audit.pids["worker"] = 123
    connection = SimpleNamespace(info={"finalizer_role": "worker"})
    statement = (
        "SELECT company_memberships.id FROM company_memberships "
        "WHERE company_memberships.company_id = %(company_id)s "
        "ORDER BY company_memberships.created_at ASC, company_memberships.id ASC LIMIT %(limit)s"
    )
    private_parameter = secrets.token_urlsafe(32)
    audit.before(connection, None, statement, {"company_id": private_parameter}, None, False)
    assert audit.statements["worker"] == [statement]
    assert receipts == [{"event": "sql_before", "role": "worker", "pid": 123, "sql": statement}]
    assert private_parameter not in json.dumps(receipts)
    audit.before(connection, None, "SELECT %(value)s", {"value": private_parameter}, None, False)
    assert audit.statement_counts["worker"] == 2
    assert audit.statements["worker"] == [statement] and len(receipts) == 1


@pytest.fixture
def finalizer_audit(pg_engine, monkeypatch, tmp_path, request):
    monkeypatch.setenv("CASEOPS_ENV", "local")
    monkeypatch.setenv(
        "CASEOPS_DATABASE_URL", pg_engine.url.render_as_string(hide_password=False),
    )
    monkeypatch.setenv("CASEOPS_AUTO_MIGRATE", "false")
    monkeypatch.setenv("CASEOPS_AUTH_SECRET", secrets.token_urlsafe(32))
    monkeypatch.setenv("CASEOPS_AUTH_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("CASEOPS_EMBEDDING_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_OTEL_ENABLED", "false")
    get_settings.cache_clear()
    if os.environ.get("CASEOPS_FINALIZER_AUTH_BASELINE") == "strong":
        original = identity.lock_company_memberships_for_assignment

        def former_auth_option(session, **kwargs):
            kwargs["no_key_update"] = False
            return original(session, **kwargs)

        monkeypatch.setattr(identity, "lock_company_memberships_for_assignment", former_auth_option)
    directory = Path(os.environ.get("CASEOPS_FINALIZER_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    evidence_path = _finalizer_evidence_path(directory, request.node.nodeid)
    lock = Lock()
    with evidence_path.open("x", encoding="utf-8") as stream:
        def record(kind, **data):
            with lock:
                stream.write(json.dumps({"event": kind, "time": datetime.now(UTC).isoformat(),
                                         **data}, default=str) + "\n")
                stream.flush()

        # NullPool prevents another contender borrowing a labelled committed backend.
        engine = create_engine(pg_engine.url, poolclass=NullPool)
        audit = _FinalizerAudit(engine, record)

        def parse_source(_key, content_type):
            assert content_type == "text/plain"
            if audit.boundary == "parse":
                audit.entered.set()
                assert audit.release.wait(8), "Pre-persistence parse boundary was not released"
            return document_processing.ParsedDocument(
                status=DocumentProcessingStatus.INDEXED, extracted_text=_SOURCE,
                chunks=[_SOURCE], error=None)

        monkeypatch.setattr(document_processing, "parse_attachment", parse_source)
        monkeypatch.setattr(
            document_jobs, "get_session_factory", lambda: lambda: audit.session("worker"),
        )
        for name, callback in audit.hooks:
            event.listen(engine, name, callback)
        record("source_identity", baseline=os.environ.get("CASEOPS_FINALIZER_AUTH_BASELINE"),
               nodeid=request.node.nodeid, test_name=request.node.name,
               document_jobs_sha256=sha256(Path(document_jobs.__file__).read_bytes()).hexdigest(),
               identity_sha256=sha256(Path(identity.__file__).read_bytes()).hexdigest(),
               private_retrieval_sha256=sha256(
                   Path(private_retrieval.__file__).read_bytes()).hexdigest(),
               matters_sha256=sha256(Path(matters.__file__).read_bytes()).hexdigest(),
               test_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
               evidence_path=str(evidence_path),
               limitation="Local overlap, not Cloud Run CPU attribution")
        try:
            yield audit
        finally:
            audit.release.set()
            for name, callback in audit.hooks:
                event.remove(engine, name, callback)
            remaining = audit.snapshot()
            locks = audit.retained_locks()
            record("cleanup", activity=remaining, locks=locks,
                   all_backend_ids=sorted(audit.all_pids), errors=audit.errors)
            engine.dispose()
            assert not remaining, "Owned labelled PostgreSQL transaction leaked"
            assert not locks, "Owned PostgreSQL backend locks leaked"


@contextmanager
def _real_login_server(audit):
    app = create_application()

    async def request_session():
        with audit.session("login") as session:
            yield session

    app.dependency_overrides[get_db_session] = request_session
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="error"))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = monotonic() + 6
        while not server.started and thread.is_alive() and monotonic() < deadline:
            sleep(0.01)
        assert server.started, "Owned socket server failed to start"
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(timeout=6)
        listener.close()
        assert not thread.is_alive(), "Owned socket server did not stop"


def _login(client, origin, fixture, audit):
    started = monotonic()
    response = client.post(origin + "/api/auth/login", json={
        "company_slug": fixture["slug"], "email": fixture["email"], "password": _PASSWORD,
    })
    # Body consumed before returning. Never persist body/cookies/password/token.
    audit.record("http_body_complete", status=response.status_code,
                 request_id=response.headers.get("x-request-id"),
                 duration=monotonic() - started, completed_at=datetime.now(UTC).isoformat())
    return response


def _verify_committed(audit, fixture, *, event_count):
    with Session(audit.engine) as check:
        job = check.get(DocumentProcessingJob, fixture["job_id"])
        assert job.status == DocumentProcessingJobStatus.COMPLETED
        assert job.attempt_count == 1 and job.error_message is None
        model = MatterAttachment if fixture["target"] == "matter" else IpDocumentVersion
        attachment = check.get(model, fixture["attachment_id"])
        assert attachment.processing_status == DocumentProcessingStatus.INDEXED
        assert attachment.extracted_text == _SOURCE
        assert attachment.uploaded_by_membership_id == fixture["actor_id"]
        events = list(check.scalars(select(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture["company_id"])))
        assert len(events) == event_count
        assert all(row.status == "applied" and row.actor_membership_id == fixture["actor_id"]
                   for row in events)
        source_event = next(row for row in events if row.target_id == fixture["source_id"])
        assert source_event.affected_projection_count == 1
        assert source_event.affected_saved_output_count == 2
        active = check.get(PrivateIndexProjection, fixture["active_projection"])
        assert active.is_tombstoned and active.content_text == "" and active.embedding_json is None
        retired = check.get(PrivateIndexProjection, fixture["retired_projection"])
        assert retired.content_text == _SOURCE
        assert all(check.get(PrivateSavedOutputAccess, item).state == "locked"
                   for item in fixture["outputs"])
        assert not check.get(PrivateIndexProjection, fixture["other_projection"]).is_tombstoned
        assert check.get(PrivateSavedOutputAccess, fixture["other_output"]).state == "accessible"
        assert check.get(PrivateIndexGeneration, fixture["generation_id"]).tombstone_generation == (
            fixture["initial_epoch"] + event_count)
        assert check.get(PrivateIndexGeneration, fixture["shadow_id"]).tombstone_generation == (
            fixture["initial_epoch"] + event_count)
        audit.record("commit_verified", job_id=job.id, event_count=len(events),
                     positive_projections=1, locked_active_and_retired_outputs=2)
    # Completed-job replay must not create another invalidation or reopen anything.
    audit.worker(fixture)
    with Session(audit.engine) as check:
        assert check.scalar(select(func.count()).select_from(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture["company_id"])) == event_count
        assert check.get(DocumentProcessingJob, fixture["job_id"]).attempt_count == 1


@pytest.mark.parametrize("target", ["matter", "ip"])
@pytest.mark.parametrize("mutation", ["metadata", "dispose"])
def test_actual_finalizer_allows_same_uploader_login_and_releases_company_writer(
    finalizer_audit, target, mutation,
):
    audit = finalizer_audit
    fixture = _seed_finalizer(audit.engine, target)
    started = monotonic()
    with (
        _real_login_server(audit) as origin,
        httpx.Client(
            headers={"X-CaseOps-Automated-Test": "no-paid-providers"}, timeout=5,
        ) as client,
        audit.pool() as (pool, futures),
    ):
        audit.record("http_client_preflight_complete", duration=monotonic() - started,
                     worker_started=False)
        preflight = _login(client, origin, fixture, audit)
        assert preflight.status_code == 200
        assert preflight.json()["membership"]["id"] == fixture["actor_id"]
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert audit.entered.wait(5), "Actual applied-event SQL was not reached"
        assert any("FOR KEY SHARE" in sql and "company_memberships" in sql
                   for sql in audit.statements["worker"])
        login = pool.submit(_login, client, origin, fixture, audit)
        futures.append(login)
        if os.environ.get("CASEOPS_FINALIZER_AUTH_BASELINE") == "strong":
            audit.await_blocker("login", "worker")
        response = login.result(timeout=5)
        assert response.status_code == 200, (
            "Same-uploader real HTTP login blocked by historical provenance"
        )
        assert response.json()["membership"]["id"] == fixture["actor_id"]
        assert not worker.done(), "Auth completed only after finalization released its locks"
        assert any("FOR NO KEY UPDATE" in sql and "company_memberships" in sql
                   for sql in audit.statements["login"])
        # Start the 2s-budget Company contender only after the paused-worker
        # login proof; password hashing must not consume its lock-wait budget.
        writer = pool.submit(audit.mutate, fixture, mutation)
        futures.append(writer)
        audit.await_blocker("mutation", "worker")
        assert not writer.done()
        audit.record("release_finalizer_after_response", activity=audit.snapshot())
        audit.release.set()
        worker.result(timeout=5)
        writer.result(timeout=5)
    _verify_committed(audit, fixture, event_count=2)
    with Session(audit.engine) as check:
        unrelated = check.get(Matter, fixture["unrelated_id"])
        if mutation == "metadata":
            assert unrelated.title == "Unrelated finalizer overlap mutation"
            assert unrelated.status == "active" and unrelated.is_active
        else:
            assert unrelated.status == "disposed" and not unrelated.is_active
            assert unrelated.lifecycle_version == fixture["initial_versions"][unrelated.id] + 1
    assert audit.errors == []


@pytest.mark.parametrize("target", ["matter", "ip"])
def test_auth_first_still_allows_actual_finalizer_to_commit(finalizer_audit, target):
    audit = finalizer_audit
    fixture = _seed_finalizer(audit.engine, target)
    with audit.session("auth") as auth, audit.pool() as (pool, futures):
        minted = identity.issue_auth_session_under_fence(
            auth, company_id=fixture["company_id"], membership_id=fixture["actor_id"])
        assert minted.membership.id == fixture["actor_id"]
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert audit.entered.wait(5), "Finalizer could not take historical provenance after auth"
        audit.release.set()
        worker.result(timeout=5)
        assert auth.in_transaction(), "Test released auth before proving the reverse lock order"
        auth.commit()
    _verify_committed(audit, fixture, event_count=1)
    assert audit.errors == []


@pytest.mark.parametrize("revocation", ["deactivated", "cutoff"])
def test_identity_revocation_wins_without_erasing_finalizer_provenance(finalizer_audit, revocation):
    audit = finalizer_audit
    fixture = _seed_finalizer(audit.engine, "matter")
    with audit.pool() as (pool, futures):
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert audit.entered.wait(5)
        with audit.session("revocation") as revoke:
            row = revoke.scalar(select(CompanyMembership).where(
                CompanyMembership.id == fixture["actor_id"]).with_for_update(key_share=True))
            if revocation == "deactivated":
                row.is_active = False
            else:
                row.sessions_valid_after = datetime.now(UTC)
            revoke.commit()
        with audit.session("auth") as auth:
            with pytest.raises(HTTPException) as denied:
                identity.issue_auth_session_under_fence(
                    auth, company_id=fixture["company_id"], membership_id=fixture["actor_id"],
                    source_token_issued_at=0.0)
            assert denied.value.status_code == (403 if revocation == "deactivated" else 401)
            audit.record("revocation_rejected_mint", revocation=revocation,
                         status=denied.value.status_code)
        audit.release.set()
        worker.result(timeout=5)
    _verify_committed(audit, fixture, event_count=1)
    assert audit.errors == []


def test_disposal_before_persistence_wins_over_real_document_finalizer(finalizer_audit):
    audit = finalizer_audit
    fixture = _seed_finalizer(audit.engine, "matter")
    audit.boundary = "parse"
    with audit.pool() as (pool, futures):
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert audit.entered.wait(5)
        audit.mutate(fixture, "dispose", source=True)
        audit.release.set()
        worker.result(timeout=5)
    with Session(audit.engine) as check:
        matter = check.get(Matter, fixture["matter_id"])
        assert matter.status == "disposed" and not matter.is_active
        assert matter.lifecycle_version == fixture["initial_versions"][matter.id] + 1
        job = check.get(DocumentProcessingJob, fixture["job_id"])
        assert job.status == DocumentProcessingJobStatus.FAILED
        assert "disposed" in job.error_message.lower()
        attachment = check.get(MatterAttachment, fixture["attachment_id"])
        assert attachment.processing_status == DocumentProcessingStatus.PENDING
        assert attachment.extracted_text is None and attachment.chunks == []
        events = list(check.scalars(select(PrivateProjectionEvent).where(
            PrivateProjectionEvent.company_id == fixture["company_id"])))
        assert len(events) == 1 and events[0].target_id == fixture["matter_id"]
        assert events[0].status == "applied"
        assert all(check.get(PrivateSavedOutputAccess, item).state == "locked"
                   for item in fixture["outputs"])
        audit.record("disposal_winner_verified", lifecycle_version=matter.lifecycle_version,
                     job_status=job.status, private_events=len(events), generated_chunks=0)
    assert audit.errors == []
