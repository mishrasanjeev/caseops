"""Real IP producers and Matter writers serialize before actor/source locks.

SQL hooks pause real statements; they never replace services, locks, events,
or commits. The original 16-case deadlock evidence is retained separately.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, wait
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, local
from time import monotonic, sleep
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from caseops_api.db.models import (
    DocumentProcessingAction,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingStatus,
    DocumentProcessingTargetType,
    IpDocument,
    IpDocumentTaxonomyEntry,
    IpDocumentVersion,
    IpPatentFamilyVersion,
    Matter,
    PrivateIndexGeneration,
    PrivateProjectionEvent,
)
from caseops_api.schemas.ip_patents import PatentFamilyCorrectionRequest
from caseops_api.schemas.matters import MatterLifecycleStatusRequest, MatterUpdateRequest
from caseops_api.services import document_jobs, document_processing, ip_patent_families, matters
from caseops_api.services.private_retrieval import ensure_active_private_generation
from tests.test_ip_patent_postgres import _seed
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("autoflush", [False, True], ids=["production", "autoflush"])
@pytest.mark.parametrize("same_actor", [True, False], ids=["same-actor", "different-actor"])
@pytest.mark.parametrize("mutation", ["metadata", "dispose"])
@pytest.mark.parametrize("producer", ["index-worker", "patent-correction"])
@pytest.mark.parametrize("first", ["producer", "matter"])
def test_private_event_actor_overlap(
    pg_engine, monkeypatch, tmp_path, request, autoflush, same_actor, mutation, producer, first
):
    evidence_dir = Path(os.environ.get("CASEOPS_ACTOR_AUDIT_DIR", str(tmp_path)))
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"{request.node.callspec.id}.jsonl"
    evidence_lock = Lock()
    with evidence_path.open("x", encoding="utf-8") as evidence:

        def record(kind, **data):
            with evidence_lock:
                evidence.write(json.dumps({"event": kind, **data}, default=str) + "\n")
                evidence.flush()

        _overlap(pg_engine, monkeypatch, autoflush, same_actor, mutation, producer, first, record)


def _overlap(engine, monkeypatch, autoflush, same_actor, mutation, producer, first, record):
    company_id, actor_id, family = _seed(engine)
    content = "Immutable local actor-lock audit source. No provider transport is used."
    content_hash = sha256(content.encode()).hexdigest()
    with Session(engine) as seed:
        matter_actor = actor_id if same_actor else _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        matter = seed.get(Matter, matter_id)
        initial_matter = (matter.title, matter.status, matter.is_active, matter.lifecycle_version)
        expected_updated_at = matter.updated_at
        taxonomy = IpDocumentTaxonomyEntry(
            company_id=company_id,
            key="actor-audit",
            label="Actor audit",
            updated_by_membership_id=actor_id,
        )
        seed.add(taxonomy)
        seed.flush()
        document = IpDocument(
            company_id=company_id,
            taxonomy_entry_id=taxonomy.id,
            title="Actor provenance source",
            created_by_membership_id=actor_id,
        )
        seed.add(document)
        seed.flush()
        version = IpDocumentVersion(
            company_id=company_id,
            document_id=document.id,
            version=1,
            original_filename="actor-audit.txt",
            display_name="actor-audit.txt",
            storage_key=f"actor-audit/{uuid4()}.txt",
            content_type="text/plain",
            size_bytes=len(content),
            sha256_hex=content_hash,
            uploaded_by_membership_id=actor_id,
        )
        seed.add(version)
        seed.flush()
        job = DocumentProcessingJob(
            company_id=company_id,
            requested_by_membership_id=actor_id,
            target_type=DocumentProcessingTargetType.IP_DOCUMENT_VERSION,
            attachment_id=version.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        seed.add(job)
        generation = ensure_active_private_generation(seed, company_id=company_id)
        seed.commit()
        job_id, version_id, document_id = job.id, version.id, document.id
        initial_processing = version.processing_status
        initial_epoch = generation.tombstone_generation
        generation_id = generation.id
        initial_events = set(
            seed.scalars(
                select(PrivateProjectionEvent.id).where(
                    PrivateProjectionEvent.company_id == company_id
                )
            )
        )
        constraints = (
            seed.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
                    "WHERE conrelid = 'private_projection_events'::regclass AND contype = 'f'"
                )
            )
            .mappings()
            .all()
        )
        record(
            "fixture",
            company_id=company_id,
            actor_id=actor_id,
            matter_actor=matter_actor,
            matter_id=matter_id,
            job_id=job_id,
            version_id=version_id,
            document_id=document_id,
            generation_id=generation_id,
            constraints=[dict(row) for row in constraints],
            producer=producer,
            mutation=mutation,
            autoflush=autoflush,
            first=first,
            source_file=document_jobs.__file__,
            source_sha256=sha256(Path(document_jobs.__file__).read_bytes()).hexdigest(),
            server_version=seed.scalar(text("SELECT version()")),
        )

    first_paused, resume_first = Event(), Event()
    thread = local()
    pids = {}
    statements = {"producer": [], "matter": []}
    errors = []
    names = {role: f"actor-audit-{role}-{uuid4().hex[:10]}" for role in statements}
    factory = sessionmaker(bind=engine, autoflush=autoflush, expire_on_commit=False)
    # Never borrow a contender's labelled pooled backend for the cleanup probe.
    observer_engine = create_engine(engine.url, poolclass=NullPool)

    def new_session(role):
        session = factory()
        session.execute(text("SET statement_timeout = '20s'"))
        session.execute(text("SET lock_timeout = '15s'"))
        # Let the producer report its exact FK/explicit-actor failure context.
        session.execute(
            text(
                "SET deadlock_timeout = '2s'"
                if role == "producer"
                else "SET deadlock_timeout = '5s'"
            )
        )
        session.execute(
            text("SELECT set_config('application_name', :name, false)"), {"name": names[role]}
        )
        pids[role] = session.scalar(text("SELECT pg_backend_pid()"))
        return session

    def capture_before(conn, cursor, statement, parameters, context, many):
        role = getattr(thread, "role", None)
        if role not in statements:
            return
        significant = "FOR " in statement or statement.startswith(("INSERT", "UPDATE"))
        if significant:
            statements[role].append(statement)
            record(
                "sql_before",
                role=role,
                pid=pids.get(role),
                statement=statement,
                parameters=parameters,
            )
        pause_here = (
            statement.startswith("INSERT INTO private_projection_events")
            if producer == "index-worker"
            else "FROM company_memberships" in statement and "FOR UPDATE" in statement
        )
        if first == role == "producer" and pause_here and not first_paused.is_set():
            first_paused.set()
            assert resume_first.wait(15), "Producer boundary was never released"

    def capture_after(conn, cursor, statement, parameters, context, many):
        role = getattr(thread, "role", None)
        if role in statements and "FOR " in statement:
            record("sql_lock_acquired", role=role, pid=pids.get(role), statement=statement)
        if (
            first == role == "matter"
            and "FROM companies" in statement
            and "FOR NO KEY UPDATE" in statement
            and not first_paused.is_set()
        ):
            first_paused.set()
            assert resume_first.wait(15), "Matter boundary was never released"

    def capture_error(context):
        original = context.original_exception
        diag = getattr(original, "diag", None)
        error = {
            "role": getattr(thread, "role", None),
            "sqlstate": getattr(original, "sqlstate", None),
            "statement": context.statement,
            "message": str(original),
            "detail": getattr(diag, "message_detail", None),
            "context": getattr(diag, "context", None),
        }
        errors.append(error)
        record("database_error", **error)

    def snapshot():
        with observer_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            rows = (
                observer.execute(
                    text(
                        "SELECT pid, application_name, state, xact_start, backend_xid, "
                        "wait_event_type, wait_event, query, pg_blocking_pids(pid) AS blockers "
                        "FROM pg_stat_activity WHERE application_name IN (:producer, :matter)"
                    ),
                    names,
                )
                .mappings()
                .all()
            )
            locks = (
                observer.execute(
                    text(
                        "SELECT pid, locktype, relation::regclass::text AS relation, page, tuple, "
                        "transactionid, virtualxid, mode, granted FROM pg_locks "
                        "WHERE pid IN (SELECT pid FROM pg_stat_activity "
                        "WHERE application_name IN (:producer, :matter)) ORDER BY pid, locktype"
                    ),
                    names,
                )
                .mappings()
                .all()
            )
        return {"activity": [dict(row) for row in rows], "locks": [dict(row) for row in locks]}

    def await_graph():
        deadline = monotonic() + 4
        last = None
        while monotonic() < deadline:
            last = snapshot()
            by_pid = {row["pid"]: row for row in last["activity"]}
            second = "matter" if first == "producer" else "producer"
            waiter = by_pid.get(pids.get(second), {})
            if pids.get(first) in waiter.get("blockers", []):
                record("waiting_company", first=first, second=second, **last)
                assert "FROM companies" in waiter["query"]
                assert "FOR NO KEY UPDATE" in waiter["query"]
                # A waiter must not retain the actor or Matter row while it
                # waits for tenant admission. NOWAIT probes prove absence.
                with observer_engine.begin() as probe:
                    probe.execute(
                        text(
                            "SELECT id FROM company_memberships WHERE id = :id FOR KEY SHARE NOWAIT"
                        ),
                        {"id": matter_actor},
                    )
                    probe.execute(
                        text("SELECT id FROM matters WHERE id = :id FOR UPDATE NOWAIT"),
                        {"id": matter_id},
                    )
                record("waiter_has_no_actor_or_matter_lock")
                return
            sleep(0.02)
        record("graph_timeout", **(last or {}))
        raise AssertionError("Required one-way Company wait not observed")

    def parse_source(key, content_type):
        assert content_type == "text/plain"
        return document_processing.ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=content,
            chunks=[content],
            error=None,
        )

    def produce():
        thread.role = "producer"
        try:
            if producer == "index-worker":
                document_jobs.run_document_processing_job(job_id)
            else:
                with new_session("producer") as session:
                    context = _ip_race_context(
                        session, company_id=company_id, membership_id=actor_id
                    )
                    ip_patent_families.correct_patent_family(
                        session,
                        context=context,
                        family_id=str(family.id),
                        payload=PatentFamilyCorrectionRequest(
                            expected_version=family.version,
                            expected_lifecycle_version=family.lifecycle_version,
                            facts=family.facts,
                            reason="Retain source provenance during actor overlap.",
                        ),
                    )
            return "returned"
        except DBAPIError as exc:
            return getattr(exc.orig, "sqlstate", None)
        finally:
            thread.role = None

    def mutate():
        thread.role = "matter"
        try:
            with new_session("matter") as session:
                context = _ip_race_context(
                    session, company_id=company_id, membership_id=matter_actor
                )
                if mutation == "metadata":
                    matters.update_matter(
                        session,
                        context=context,
                        matter_id=matter_id,
                        payload=MatterUpdateRequest(
                            title="Changed by real Matter service",
                            expected_updated_at=expected_updated_at,
                        ),
                    )
                else:
                    matters.transition_matter_lifecycle_status(
                        session,
                        context=context,
                        matter_id=matter_id,
                        payload=MatterLifecycleStatusRequest(
                            to_status="disposed",
                            expected_from_status="active",
                            expected_updated_at=expected_updated_at,
                            reason="Dispose in deterministic actor lock overlap.",
                        ),
                    )
                return "returned"
        except DBAPIError as exc:
            return getattr(exc.orig, "sqlstate", None)
        finally:
            thread.role = None

    monkeypatch.setattr(
        document_jobs, "get_session_factory", lambda: lambda: new_session("producer")
    )
    monkeypatch.setattr(document_processing, "parse_attachment", parse_source)
    hooks = [
        ("before_cursor_execute", capture_before),
        ("after_cursor_execute", capture_after),
        ("handle_error", capture_error),
    ]
    for name, callback in hooks:
        event.listen(engine, name, callback)
    pool = ThreadPoolExecutor(max_workers=2)
    futures = []
    try:
        operations = {"producer": produce, "matter": mutate}
        second = "matter" if first == "producer" else "producer"
        by_role = {first: pool.submit(operations[first])}
        futures.append(by_role[first])
        assert first_paused.wait(15), "First service never reached its Company boundary"
        by_role[second] = pool.submit(operations[second])
        futures.append(by_role[second])
        await_graph()
        resume_first.set()
        outcomes = [by_role[role].result(timeout=20) for role in ("producer", "matter")]
        record("outcomes", producer=outcomes[0], matter=outcomes[1], errors=errors)
    finally:
        resume_first.set()
        _, pending = wait(futures, timeout=22)
        if pending:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as cleanup:
                for pid in pids.values():
                    cleanup.execute(text("SELECT pg_cancel_backend(:pid)"), {"pid": pid})
            _, pending = wait(futures, timeout=5)
        pool.shutdown(wait=True, cancel_futures=True)
        for name, callback in hooks:
            event.remove(engine, name, callback)
        cleanup_state = snapshot()
        observer_engine.dispose()
        record("cleanup", pending_futures=len(pending), **cleanup_state)
        assert not pending
        assert not any(row["xact_start"] for row in cleanup_state["activity"])

    with Session(engine) as verify:
        matter = verify.get(Matter, matter_id)
        matter_state = (matter.title, matter.status, matter.is_active, matter.lifecycle_version)
        retained_job = verify.get(DocumentProcessingJob, job_id)
        retained_version = verify.get(IpDocumentVersion, version_id)
        family_versions = list(
            verify.scalars(
                select(IpPatentFamilyVersion).where(
                    IpPatentFamilyVersion.family_id == str(family.id)
                )
            )
        )
        new_events = list(
            verify.scalars(
                select(PrivateProjectionEvent).where(
                    PrivateProjectionEvent.company_id == company_id,
                    PrivateProjectionEvent.id.not_in(initial_events),
                )
            )
        )
        record(
            "persistence",
            matter_state=matter_state,
            initial_matter=initial_matter,
            job_status=retained_job.status,
            job_error=retained_job.error_message,
            attempt_count=retained_job.attempt_count,
            processing_status=retained_version.processing_status,
            family_versions=len(family_versions),
            new_events=[
                {
                    "id": row.id,
                    "actor": row.actor_membership_id,
                    "target": row.target_id,
                    "status": row.status,
                }
                for row in new_events
            ],
        )
        assert all(row.actor_membership_id in {actor_id, matter_actor} for row in new_events)
        assert all(row.status == "applied" for row in new_events)
        assert verify.get(PrivateIndexGeneration, generation_id).tombstone_generation == (
            initial_epoch + len(new_events)
        )
        assert retained_version.sha256_hex == content_hash
        assert retained_version.uploaded_by_membership_id == actor_id
        if outcomes[1] == "40P01":
            assert matter_state == initial_matter
            assert not any(row.target_id == matter_id for row in new_events)
        elif mutation == "metadata":
            assert matter.title == "Changed by real Matter service"
            assert (matter.status, matter.is_active, matter.lifecycle_version) == initial_matter[1:]
        else:
            assert matter.status == "disposed" and not matter.is_active
            assert matter.lifecycle_version == initial_matter[3] + 1
        producer_failed = any(row["role"] == "producer" for row in errors)
        if producer == "index-worker":
            assert retained_job.attempt_count == 1
            if producer_failed:
                assert retained_job.status == DocumentProcessingJobStatus.FAILED
                assert retained_version.processing_status == initial_processing
                assert not any(row.target_id == document_id for row in new_events)
            else:
                assert retained_job.status == DocumentProcessingJobStatus.COMPLETED
                assert retained_version.extracted_text == content
                assert any(row.target_id == document_id for row in new_events)
        else:
            assert len(family_versions) == (1 if producer_failed else 2)

    assert errors == [], f"Real services failed; exact graph retained: {errors}"
    assert outcomes == ["returned", "returned"]
