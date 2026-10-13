from __future__ import annotations

import ast
import hashlib
import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import FunctionType
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import MetaData, Table, create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, joinedload, registry, relationship, selectinload, sessionmaker

from alembic import command
from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CompanyMembership,
    DocumentProcessingJob,
    DocumentProcessingJobStatus,
    DocumentProcessingTargetType,
    MatterAttachment,
    utcnow,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services import document_jobs, document_processing
from caseops_api.services.document_jobs import (
    _mark_job_failed,
    _process_contract_attachment_job,
    _process_ip_document_version_job,
    _process_matter_attachment_job,
)
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

pytestmark = pytest.mark.postgres


# Exact function bodies from 3dbf364d9834316d181d4a52b2e9b4c7bee431b4.
# Bind their globals to the pre-upgrade mapper, never to the new claim protocol.
def _legacy_run(job_id: str) -> None:
    session_factory = get_session_factory()
    session = session_factory()
    try:
        job = session.scalar(
            select(DocumentProcessingJob)
            .options(
                joinedload(DocumentProcessingJob.requested_by_membership).joinedload(
                    CompanyMembership.user
                )
            )
            .where(DocumentProcessingJob.id == job_id)
        )
        if not job or job.status not in {
            DocumentProcessingJobStatus.QUEUED,
            DocumentProcessingJobStatus.FAILED,
        }:
            return

        job.status = DocumentProcessingJobStatus.PROCESSING
        job.attempt_count += 1
        job.started_at = utcnow()
        job.completed_at = None
        job.error_message = None
        job.processed_char_count = 0
        session.add(job)
        session.commit()

        try:
            if job.target_type == DocumentProcessingTargetType.MATTER_ATTACHMENT:
                _process_matter_attachment_job(session, job)
            elif job.target_type == DocumentProcessingTargetType.CONTRACT_ATTACHMENT:
                _process_contract_attachment_job(session, job)
            elif job.target_type == DocumentProcessingTargetType.IP_DOCUMENT_VERSION:
                _process_ip_document_version_job(session, job)
            else:
                _mark_job_failed(
                    session,
                    job,
                    error_message=f"Unsupported document processing target: {job.target_type}.",
                )
        except Exception as exc:
            session.rollback()
            failed_job = session.scalar(
                select(DocumentProcessingJob).where(DocumentProcessingJob.id == job.id)
            )
            if failed_job is not None:
                _mark_job_failed(session, failed_job, error_message=redact_provider_error(exc))
    finally:
        session.close()


def _legacy_failure(session: Session, job: DocumentProcessingJob, *, error_message: str) -> None:
    job.status = DocumentProcessingJobStatus.FAILED
    job.error_message = error_message
    job.completed_at = utcnow()
    session.add(job)
    session.commit()


def _body_hash(function) -> str:
    node = ast.parse(inspect.getsource(function)).body[0]
    return hashlib.sha256(ast.dump(
        ast.Module(body=node.body, type_ignores=[]), include_attributes=False,
    ).encode()).hexdigest()


@pytest.mark.parametrize("quiesce_before_claim", [False, True])
def test_first_release_requires_legacy_quiescence_before_recovery(
    pg_engine, monkeypatch, quiesce_before_claim,
):
    assert _body_hash(_legacy_run) == (
        "379e6d7c03eb1d1daa44e49a6ef26eeba574f2cb54d37f6d808ad6954ffba1c3"
    )
    assert _body_hash(_legacy_failure) == (
        "5ccfcd15ebfee48feac4ea7b174817b00482e850273a7cab37f5471272576b21"
    )
    name = "document_rolling_" + uuid4().hex
    url = pg_engine.url.set(database=name)
    with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
        admin.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(url)
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url.render_as_string(hide_password=False))
    get_settings.cache_clear()
    old_entered, release_old = Event(), Event()
    legacy_registry = registry()
    clock = [datetime.now(UTC)]
    try:
        command.upgrade(cfg, "20260928_0001")
        with Session(engine) as seed:
            company = _seed_company(seed)
            actor = _seed_membership(seed, company, role="admin")
            matter = _seed_matter(seed, company)
            source = MatterAttachment(matter_id=matter, uploaded_by_membership_id=actor,
                original_filename="rolling.txt", storage_key=uuid4().hex,
                content_type="text/plain", size_bytes=20, sha256_hex="a" * 64)
            seed.add(source)
            seed.flush()
            source_id = source.id
            old_id, queued_id = str(uuid4()), str(uuid4())
            for job_id in (old_id, queued_id):
                seed.execute(text(
                    "INSERT INTO document_processing_jobs "
                    "(id, company_id, requested_by_membership_id, target_type, attachment_id, "
                    "action, status, attempt_count, processed_char_count, queued_at, updated_at) "
                    "VALUES (:id, :company, :actor, 'matter_attachment', :source, "
                    "'initial_index', 'queued', 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": job_id, "company": company, "actor": actor, "source": source_id})
            seed.commit()
        table = Table("document_processing_jobs", MetaData(), autoload_with=engine)
        assert "no_paid_providers" not in table.c

        class LegacyJob:
            pass

        legacy_registry.map_imperatively(LegacyJob, table, properties={
            "requested_by_membership": relationship(CompanyMembership,
                primaryjoin=table.c.requested_by_membership_id == CompanyMembership.id,
                foreign_keys=[table.c.requested_by_membership_id]),
        })
        factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)

        def old_parser(session, job):
            # Match the old Matter processor's pre-parser reads; retain its read
            # transaction while the deterministic, non-billable callback waits.
            assert session.scalar(select(MatterAttachment).options(
                selectinload(MatterAttachment.chunks), joinedload(MatterAttachment.matter),
                joinedload(MatterAttachment.linked_court_order),
            ).where(MatterAttachment.id == job.attachment_id)) is not None
            old_entered.set()
            assert release_old.wait(20)
            raise RuntimeError("Legacy provider failure after release boundary")

        bindings = globals() | {
            "DocumentProcessingJob": LegacyJob,
            "get_session_factory": lambda: factory,
            "utcnow": lambda: clock[0],
            "_process_matter_attachment_job": old_parser,
        }
        bindings["_mark_job_failed"] = FunctionType(_legacy_failure.__code__, bindings)
        old_run = FunctionType(_legacy_run.__code__, bindings)
        monkeypatch.setattr(document_jobs, "get_session_factory", lambda: factory)
        monkeypatch.setattr(document_jobs, "utcnow", lambda: clock[0])
        monkeypatch.setattr(document_processing, "parse_attachment", lambda *_:
            document_processing.ParsedDocument("indexed", "New fenced result",
                                                ["New fenced result"], None))
        monkeypatch.setattr(document_jobs, "embed_matter_attachment_chunks", lambda *_, **__: 0)
        if not quiesce_before_claim:
            # Install only the additive policy before the old snapshot exists.
            # This branch proves that successful DDL alone is not a writer fence.
            command.upgrade(cfg, "20261010_0002")
        with ThreadPoolExecutor(max_workers=1) as pool:
            old = pool.submit(old_run, old_id)
            try:
                assert old_entered.wait(10)
                if quiesce_before_claim:
                    # CONCURRENTLY still waits for an old reader's snapshot.
                    # Keep the real migration lock budget and its partial DDL.
                    with pytest.raises(OperationalError) as interrupted:
                        command.upgrade(cfg, "20261010_0002")
                    assert interrupted.value.orig.sqlstate == "55P03"
                    assert not release_old.is_set()
                    with engine.connect() as check:
                        assert check.scalar(text("SELECT version_num FROM alembic_version")) == (
                            "20260928_0001"
                        )
                        assert check.execute(text(
                            "SELECT id, status, attempt_count, no_paid_providers "
                            "FROM document_processing_jobs ORDER BY id"
                        )).all() == sorted([
                            (old_id, "processing", 1, True),
                            (queued_id, "queued", 0, True),
                        ])
                        index_state = check.execute(text(
                            "SELECT i.indisvalid, i.indisready FROM pg_index i "
                            "JOIN pg_class c ON c.oid = i.indexrelid "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = current_schema() "
                            "AND c.relname = 'ix_document_processing_jobs_queue'"
                        )).one()
                        assert index_state.indisvalid is False
                    release_old.set()
                    old.result(10)
                    command.upgrade(cfg, "20261010_0002")
                    command.upgrade(cfg, "20261010_0002")
                    with engine.connect() as check:
                        assert check.scalar(text("SELECT version_num FROM alembic_version")) == (
                            "20261010_0002"
                        )
                        assert check.execute(text(
                            "SELECT c.relname, i.indisvalid, i.indisready FROM pg_index i "
                            "JOIN pg_class c ON c.oid = i.indexrelid "
                            "JOIN pg_namespace n ON n.oid = c.relnamespace "
                            "WHERE n.nspname = current_schema() AND c.relname IN "
                            "('ix_document_processing_jobs_queue', "
                            "'ix_document_processing_jobs_recovery') ORDER BY c.relname"
                        )).all() == [
                            ("ix_document_processing_jobs_queue", True, True),
                            ("ix_document_processing_jobs_recovery", True, True),
                        ]
                with Session(engine) as check:
                    assert check.get(DocumentProcessingJob, old_id).no_paid_providers is True
                    assert check.get(DocumentProcessingJob, queued_id).status == "queued"
                if quiesce_before_claim:
                    assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 0
                    outcomes = {}
                    assert document_jobs.drain_document_processing_jobs(
                        limit=5, outcomes=outcomes,
                    ) == 1
                    assert outcomes == {"completed": 1}
                else:
                    clock[0] += timedelta(minutes=16)
                    assert document_jobs.recover_stale_document_processing_jobs(limit=5) == 1
                    assert document_jobs.run_document_processing_job(old_id) is True
                    with Session(engine) as check:
                        assert check.get(DocumentProcessingJob, old_id).status == "completed"
                    release_old.set()
                    old.result(10)
                with Session(engine) as check:
                    receipt = check.get(DocumentProcessingJob, old_id)
                    # A green additive migration is NOT an old-worker fence.
                    # The unsafe overlap demonstrably overwrites COMPLETED.
                    assert receipt.status == "failed"
                    assert "Legacy provider failure" in receipt.error_message
                    assert receipt.attempt_count == (1 if quiesce_before_claim else 2)
                    assert receipt.no_paid_providers is True
                    queued = check.get(DocumentProcessingJob, queued_id)
                    assert queued.status == ("completed" if quiesce_before_claim else "queued")
                    assert queued.no_paid_providers is True
                    assert (
                        check.get(MatterAttachment, source_id).extracted_text == "New fenced result"
                    )
            finally:
                release_old.set()
                old.result(10)
    finally:
        release_old.set()
        legacy_registry.dispose()
        engine.dispose()
        get_settings.cache_clear()
        with pg_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as admin:
            admin.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
