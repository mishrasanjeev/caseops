"""Scalar document snapshots against retained, tenant-scoped PostgreSQL receipts."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, event, func, inspect, select
from sqlalchemy.orm import Session, defer, raiseload

from caseops_api.db.models import (
    CompanyMembership,
    Contract,
    DocumentProcessingJob,
    IpDocumentVersion,
    Matter,
    MatterAttachment,
    User,
    utcnow,
)
from caseops_api.services import contracts, document_jobs, matters
from tests.test_document_worker_claims_20261010_postgres import (
    _activity_source,
    _parsed,
    _worker,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
TARGETS = ("matter", "contract", "ip")
CONTENT = "Controlled synthetic scalar snapshot evidence."
HISTORY_PER_SOURCE = 512
BATCH_SIZE = 16


def _source(engine, target):
    fixture = _activity_source(
        engine,
        "ip-targetless" if target == "ip" else target,
        active=False,
    )
    with Session(engine) as session:
        source = session.get(fixture.model, fixture.source)
        job = session.get(DocumentProcessingJob, fixture.job)
        assert source is not None and source.processing_status == "pending"
        assert source.extracted_char_count == 0 and source.extracted_text is None
        assert (job.company_id, job.attachment_id, job.status, job.attempt_count) == (
            fixture.company,
            source.id,
            "queued",
            0,
        )
        assert job.no_paid_providers is True
        if target == "matter":
            assert session.get(Matter, source.matter_id).company_id == fixture.company
        elif target == "contract":
            assert session.get(Contract, source.contract_id).company_id == fixture.company
        else:
            assert source.company_id == fixture.company
        fixture.target_type = job.target_type
    return fixture


def _read(session, fixture):
    return document_jobs.load_latest_processing_jobs(
        session,
        target_type=fixture.target_type,
        attachment_ids=[fixture.source],
    )


def _cached_source(session, fixture, source_id=None):
    return session.get(
        fixture.model,
        source_id or fixture.source,
        options=[defer(fixture.model.extracted_text, raiseload=True), raiseload("*")],
    )


def _clone_sources(session, fixture, count):
    source = session.get(fixture.model, fixture.source)
    result = []
    for offset in range(1, count + 1):
        fields = {
            "uploaded_by_membership_id": fixture.actor,
            "original_filename": f"scalar-{uuid4().hex}.txt",
            "storage_key": f"scalar-snapshot/{uuid4().hex}",
            "content_type": "text/plain",
            "size_bytes": source.size_bytes,
            "sha256_hex": source.sha256_hex,
        }
        if fixture.model is MatterAttachment:
            fields["matter_id"] = source.matter_id
        elif fixture.model is IpDocumentVersion:
            fields.update(
                company_id=fixture.company,
                document_id=source.document_id,
                version=source.version + offset,
                display_name=fields["original_filename"],
            )
        else:
            fields["contract_id"] = source.contract_id
        clone = fixture.model(**fields)
        session.add(clone)
        session.flush()
        assert clone.processing_status == "pending" and clone.extracted_char_count == 0
        result.append(clone.id)
    return result


def _complete(monkeypatch, engine, fixture):
    def parse(*_):
        assert all(not session.in_transaction() for session in sessions)
        return _parsed(CONTENT)

    sessions = _worker(monkeypatch, engine, parse)
    assert document_jobs.run_document_processing_job(fixture.job) is True
    with Session(engine) as check:
        job = check.get(DocumentProcessingJob, fixture.job)
        source = check.get(fixture.model, fixture.source)
        assert (job.status, job.attempt_count, job.processed_char_count) == (
            "completed",
            1,
            len(CONTENT),
        ), job.error_message
        assert job.no_paid_providers is True
        assert source.processing_status == "indexed" and source.extracted_text == CONTENT
        assert source.extracted_char_count == len(CONTENT) and source.processed_at is not None
        return {
            "processing_status": source.processing_status,
            "sha256_hex": source.sha256_hex,
            "extracted_char_count": source.extracted_char_count,
            "extraction_error": source.extraction_error,
            "processed_at": source.processed_at,
        } | (
            {"ocr_quality_score": source.ocr_quality_score}
            if fixture.model is IpDocumentVersion
            else {}
        )


def _receipt(fixture, source_id, *, queued_at, job_id=None, **overrides):
    # Historical receipts are inserted once, not forged through guarded UPDATEs.
    return {
        "id": job_id or str(uuid4()),
        "company_id": fixture.company,
        "requested_by_membership_id": fixture.actor,
        "target_type": fixture.target_type,
        "attachment_id": source_id,
        "action": "reindex",
        "status": "failed",
        "attempt_count": 1,
        "no_paid_providers": True,
        "processed_char_count": 0,
        "error_message": "Retained synthetic parser failure.",
        "queued_at": queued_at,
        "started_at": queued_at + timedelta(seconds=1),
        "completed_at": queued_at + timedelta(seconds=2),
        "updated_at": queued_at + timedelta(seconds=2),
    } | overrides


@contextmanager
def _observe(session):
    statements, materialized = [], []
    connection = session.connection()

    def sql(_conn, _cursor, statement, parameters, _context, _many):
        statements.append({"statement": statement, "parameters": deepcopy(parameters)})

    def loaded(_session, instance):
        materialized.append(type(instance).__name__)

    event.listen(connection, "before_cursor_execute", sql)
    event.listen(session, "loaded_as_persistent", loaded)
    try:
        yield statements, materialized
    finally:
        event.remove(session, "loaded_as_persistent", loaded)
        event.remove(connection, "before_cursor_execute", sql)


def _assert_scalar_read(statements, materialized):
    assert len(statements) == 1
    statement = statements[0]["statement"].lower()
    assert statement.lstrip().startswith("select ")
    assert "extracted_text" not in statement and "attachment_chunks" not in statement
    assert materialized == [], materialized


@pytest.mark.parametrize("target", TARGETS)
def test_cached_job_requester_and_source_are_read_as_fresh_scalars(pg_engine, monkeypatch, target):
    fixture = _source(pg_engine, target)
    with Session(pg_engine, expire_on_commit=False) as reader:
        source = _cached_source(reader, fixture)
        cached_job = reader.get(DocumentProcessingJob, fixture.job)
        cached_member = reader.get(CompanyMembership, fixture.actor)
        cached_user = cached_member.user
        old_name = cached_user.full_name
        assert cached_job.status == "queued" and source.processing_status == "pending"
        fresh = _complete(monkeypatch, pg_engine, fixture)
        with Session(pg_engine) as writer:
            writer.get(User, cached_user.id).full_name = "Fresh synthetic requester label"
            writer.commit()
        identities = set(reader.identity_map)
        with _observe(reader) as (statements, materialized):
            result = _read(reader, fixture)[fixture.source]
        _assert_scalar_read(statements, materialized)
        assert result.id == fixture.job and result.status == "completed"
        assert result.processed_char_count == len(CONTENT) and result.attempt_count == 1
        assert result.error_message is None and result.completed_at is not None
        assert result.requested_by_name == "Fresh synthetic requester label"
        assert cached_user.full_name == old_name and cached_job.status == "queued"
        assert set(reader.identity_map) == identities
        assert "extracted_text" in inspect(source).unloaded
        for field, expected in fresh.items():
            assert getattr(source, field) == expected


@pytest.mark.parametrize("target", TARGETS)
def test_existing_source_without_job_is_refreshed_not_treated_as_missing(
    pg_engine,
    monkeypatch,
    target,
):
    fixture = _source(pg_engine, target)
    with Session(pg_engine) as reader:
        source = _cached_source(reader, fixture)
        cached_job = reader.get(DocumentProcessingJob, fixture.job)
        fresh = _complete(monkeypatch, pg_engine, fixture)
        with Session(pg_engine) as writer:
            writer.execute(
                delete(DocumentProcessingJob).where(
                    DocumentProcessingJob.id == fixture.job,
                )
            )
            writer.commit()
        with _observe(reader) as (statements, materialized):
            result = _read(reader, fixture)
        _assert_scalar_read(statements, materialized)
        assert result == {} and result.get(fixture.source) is None
        assert cached_job.status == "queued"
        assert "extracted_text" in inspect(source).unloaded
        for field, expected in fresh.items():
            assert getattr(source, field) == expected


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("missing", ["unknown", "deleted"])
def test_missing_source_409_leaves_entire_cached_batch_unchanged(
    pg_engine,
    monkeypatch,
    target,
    missing,
):
    fixture = _source(pg_engine, target)
    with Session(pg_engine) as seed:
        missing_id = _clone_sources(seed, fixture, 1)[0]
        seed.commit()
    with Session(pg_engine, autoflush=True) as reader:
        source = _cached_source(reader, fixture)
        missing_source = _cached_source(reader, fixture, missing_id)
        source.original_filename = "Pending unrelated client metadata.txt"
        before_history = inspect(source).attrs.original_filename.history
        fresh = _complete(monkeypatch, pg_engine, fixture)
        with Session(pg_engine) as writer:
            writer.execute(delete(fixture.model).where(fixture.model.id == missing_id))
            writer.commit()
        requested_missing = missing_id if missing == "deleted" else str(uuid4())
        with _observe(reader) as (statements, materialized):
            with pytest.raises(HTTPException) as rejected:
                document_jobs.load_latest_processing_jobs(
                    reader,
                    target_type=fixture.target_type,
                    attachment_ids=[fixture.source, requested_missing],
                )
        assert rejected.value.status_code == 409 and "Reload" in rejected.value.detail
        _assert_scalar_read(statements, materialized)
        assert source.processing_status == "pending" and source.extracted_char_count == 0
        assert missing_source.processing_status == "pending"
        assert inspect(source).attrs.original_filename.history == before_history
        assert reader.is_modified(source) and fresh["processing_status"] == "indexed"
        with Session(pg_engine) as observer:
            assert observer.get(fixture.model, fixture.source).original_filename != (
                "Pending unrelated client metadata.txt"
            )


@pytest.mark.parametrize("target", TARGETS)
def test_deleted_requester_keeps_nullable_receipt_without_cached_name(pg_engine, target):
    fixture = _source(pg_engine, target)
    with Session(pg_engine) as seed:
        requester = _seed_membership(seed, fixture.company)
        latest = _receipt(
            fixture,
            fixture.source,
            queued_at=utcnow() + timedelta(days=1),
            requested_by_membership_id=requester,
        )
        seed.execute(DocumentProcessingJob.__table__.insert(), [latest])
        seed.commit()
    with Session(pg_engine) as reader:
        _cached_source(reader, fixture)
        old_job = reader.get(DocumentProcessingJob, latest["id"])
        assert old_job.requested_by_membership.user.full_name
        with Session(pg_engine) as writer:
            writer.execute(delete(CompanyMembership).where(CompanyMembership.id == requester))
            writer.commit()
        with _observe(reader) as (statements, materialized):
            result = _read(reader, fixture)[fixture.source]
        _assert_scalar_read(statements, materialized)
        assert result.id == latest["id"] and result.status == "failed"
        assert result.requested_by_membership_id is None and result.requested_by_name is None
        assert result.error_message == latest["error_message"] and result.processed_char_count == 0
        assert old_job.requested_by_membership_id == requester


@pytest.mark.parametrize("target", TARGETS)
def test_latest_receipt_is_bound_to_parent_company_and_source_kind(pg_engine, target):
    fixture = _source(pg_engine, target)
    with Session(pg_engine) as reader:
        assert _read(reader, fixture)[fixture.source].id == fixture.job
    with Session(pg_engine) as seed:
        foreign_company = _seed_company(seed)
        newer = utcnow() + timedelta(days=2)
        wrong_type = "contract_attachment" if target != "contract" else "matter_attachment"
        misleading = [
            _receipt(
                fixture,
                fixture.source,
                queued_at=newer,
                company_id=foreign_company,
                requested_by_membership_id=None,
            ),
            _receipt(fixture, fixture.source, queued_at=newer, target_type=wrong_type),
        ]
        seed.execute(DocumentProcessingJob.__table__.insert(), misleading)
        seed.commit()
        assert (
            seed.scalar(
                select(func.count())
                .select_from(DocumentProcessingJob)
                .where(
                    DocumentProcessingJob.id.in_([row["id"] for row in misleading]),
                )
            )
            == 2
        )
    with Session(pg_engine) as reader:
        with _observe(reader) as (statements, materialized):
            result = _read(reader, fixture)[fixture.source]
        _assert_scalar_read(statements, materialized)
        assert (result.id, result.company_id, result.target_type) == (
            fixture.job,
            fixture.company,
            fixture.target_type,
        )
        assert result.requested_by_membership_id == fixture.actor


def test_empty_and_unsupported_source_kinds_have_explicit_no_sql_contract(pg_engine):
    with Session(pg_engine) as session, _observe(session) as (statements, materialized):
        for kind in ("matter_attachment", "contract_attachment", "ip_document_version", "unknown"):
            assert (
                document_jobs.load_latest_processing_jobs(
                    session,
                    target_type=kind,
                    attachment_ids=[],
                )
                == {}
            )
        with pytest.raises(ValueError, match="Unsupported document processing source type"):
            document_jobs.load_latest_processing_jobs(
                session,
                target_type="unknown",
                attachment_ids=[str(uuid4())],
            )
    assert statements == [] and materialized == []


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("autoflush", [True, False])
def test_dirty_processing_rejects_whole_batch_without_flushing_or_clobbering(
    pg_engine,
    monkeypatch,
    target,
    autoflush,
):
    fixture = _source(pg_engine, target)
    with Session(pg_engine) as seed:
        other_id = _clone_sources(seed, fixture, 1)[0]
        seed.commit()
    with Session(pg_engine, autoflush=autoflush) as reader:
        options = [defer(fixture.model.extracted_text, raiseload=True)]
        source = reader.get(fixture.model, fixture.source, options=options)
        other = reader.get(fixture.model, other_id, options=options)
        relationship_history = None
        if target != "ip":
            assert other.uploaded_by_membership.id == fixture.actor
            other.uploaded_by_membership = None
            relationship_history = inspect(other).attrs.uploaded_by_membership.history
        source.original_filename = "Uncommitted metadata must remain local.txt"
        metadata_history = inspect(source).attrs.original_filename.history
        fresh = _complete(monkeypatch, pg_engine, fixture)
        fields = {
            "processing_status": "failed",
            "sha256_hex": "c" * 64,
            "extracted_char_count": 7,
            "extraction_error": "Pending caller extraction detail",
            "processed_at": utcnow(),
        }
        if target == "ip":
            fields["ocr_quality_score"] = 0.1
        for field, pending in fields.items():
            original = getattr(other, field)
            setattr(other, field, pending)
            dirty_history = inspect(other).attrs[field].history
            assert dirty_history.has_changes()
            with _observe(reader) as (statements, materialized):
                with pytest.raises(HTTPException) as rejected:
                    document_jobs.load_latest_processing_jobs(
                        reader,
                        target_type=fixture.target_type,
                        attachment_ids=[fixture.source, other_id],
                    )
            assert rejected.value.status_code == 409
            assert statements == [] and materialized == []
            assert inspect(other).attrs[field].history == dirty_history
            assert inspect(source).attrs.original_filename.history == metadata_history
            assert source.processing_status == "pending" and source.extracted_char_count == 0
            if target != "ip":
                assert inspect(other).attrs.uploaded_by_membership.history == relationship_history
            setattr(other, field, original)
            assert not inspect(other).attrs[field].history.has_changes()
        with _observe(reader) as (statements, materialized):
            jobs = document_jobs.load_latest_processing_jobs(
                reader,
                target_type=fixture.target_type,
                attachment_ids=[fixture.source, other_id],
            )
        _assert_scalar_read(statements, materialized)
        assert set(jobs) == {fixture.source} and jobs[fixture.source].status == "completed"
        for field, expected in fresh.items():
            assert getattr(source, field) == expected
        assert inspect(source).attrs.original_filename.history == metadata_history
        if target != "ip":
            service = matters if target == "matter" else contracts
            with _observe(reader) as (statements, materialized):
                records = service._attachment_record_map(reader, [source, other])
            assert records[0].original_filename == "Uncommitted metadata must remain local.txt"
            assert records[0].latest_job.id == fixture.job and records[1].latest_job is None
            assert all(
                row["statement"].lstrip().lower().startswith("select ") for row in statements
            )
            assert "DocumentProcessingJob" not in materialized
            assert inspect(other).attrs.uploaded_by_membership.history == relationship_history
        assert inspect(source).attrs.original_filename.history == metadata_history
        assert "extracted_text" in inspect(source).unloaded
        with Session(pg_engine) as observer:
            persisted = observer.get(fixture.model, fixture.source)
            assert persisted.original_filename != "Uncommitted metadata must remain local.txt"
            assert observer.get(fixture.model, other_id).uploaded_by_membership_id == fixture.actor


@pytest.mark.parametrize("target", TARGETS)
def test_latest_receipt_timestamp_ties_use_final_id_deterministically(pg_engine, target):
    fixture = _source(pg_engine, target)
    when = utcnow() + timedelta(days=1)
    updated = when + timedelta(minutes=1)
    low, expected_id, higher_but_older = sorted(str(uuid4()) for _ in range(3))
    receipts = [
        _receipt(fixture, fixture.source, queued_at=when, job_id=low, updated_at=updated),
        _receipt(fixture, fixture.source, queued_at=when, job_id=expected_id, updated_at=updated),
        _receipt(
            fixture,
            fixture.source,
            queued_at=when,
            job_id=higher_but_older,
            updated_at=updated - timedelta(seconds=1),
        ),
        _receipt(
            fixture,
            fixture.source,
            queued_at=when - timedelta(seconds=1),
            updated_at=when + timedelta(days=1),
        ),
    ]
    with Session(pg_engine) as seed:
        seed.execute(DocumentProcessingJob.__table__.insert(), receipts)
        seed.commit()
    with Session(pg_engine) as reader:
        result = _read(reader, fixture)[fixture.source]
        assert result.id == expected_id and result.status == "failed"
        assert result.queued_at == when and result.updated_at == updated
        assert result.started_at == when + timedelta(seconds=1)
        assert result.completed_at == when + timedelta(seconds=2)
        assert result.error_message == "Retained synthetic parser failure."
        assert result.action == "reindex" and result.attempt_count == 1


def _plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from _plan_nodes(child)


def _save(directory, filename, value):
    with (directory / filename).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, default=str)
        stream.write("\n")


@pytest.mark.parametrize("target", TARGETS)
def test_retained_history_batch_has_bounded_scalar_plan_and_materialization(
    pg_engine,
    target,
    tmp_path,
    request,
    record_property,
):
    fixture = _source(pg_engine, target)
    when = utcnow() + timedelta(days=1)
    with Session(pg_engine) as seed:
        ids = [fixture.source, *_clone_sources(seed, fixture, BATCH_SIZE - 1)]
        receipts, expected = [], {}
        for source_id in ids:
            for index in range(HISTORY_PER_SOURCE):
                receipt = _receipt(
                    fixture,
                    source_id,
                    queued_at=when + timedelta(seconds=index * 3),
                )
                receipts.append(receipt)
            expected[source_id] = receipts[-1]["id"]
        seed.execute(DocumentProcessingJob.__table__.insert(), receipts)
        seed.commit()
        retained_count = seed.scalar(
            select(func.count())
            .select_from(DocumentProcessingJob)
            .where(
                DocumentProcessingJob.company_id == fixture.company,
                DocumentProcessingJob.target_type == fixture.target_type,
                DocumentProcessingJob.attachment_id.in_(ids),
            )
        )
        assert retained_count == BATCH_SIZE * HISTORY_PER_SOURCE + 1
    journal = os.environ.get("CASEOPS_TEST_RESULT_JOURNAL")
    key = sha256(request.node.nodeid.encode()).hexdigest()[:16]
    directory = (Path(journal).parent if journal else tmp_path) / "document-processing-snapshots"
    directory = directory / f"{target}-{key}"
    directory.mkdir(parents=True, exist_ok=False)
    with Session(pg_engine) as reader:
        sources = reader.scalars(
            select(fixture.model)
            .where(fixture.model.id.in_(ids))
            .options(
                defer(fixture.model.extracted_text, raiseload=True),
                raiseload("*"),
            )
        ).all()
        assert len(sources) == BATCH_SIZE
        identities = set(reader.identity_map)
        with _observe(reader) as (statements, materialized):
            started = perf_counter()
            jobs = document_jobs.load_latest_processing_jobs(
                reader,
                target_type=fixture.target_type,
                attachment_ids=ids,
            )
            elapsed = perf_counter() - started
        _save(directory, "observed-sql.json", statements)
        _assert_scalar_read(statements, materialized)
        assert {source_id: job.id for source_id, job in jobs.items()} == expected
        assert set(reader.identity_map) == identities
        assert all("extracted_text" in inspect(source).unloaded for source in sources)
        measured = statements[0]
        plan = (
            reader.connection()
            .exec_driver_sql(
                "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + measured["statement"],
                measured["parameters"],
            )
            .scalar_one()
        )
        _save(directory, "plan.json", plan)
        root = plan[0]
        scans = [
            node
            for node in _plan_nodes(root["Plan"])
            if node.get("Relation Name") == "document_processing_jobs"
        ]
        examined = sum(
            (
                node.get("Actual Rows", 0)
                + node.get("Rows Removed by Filter", 0)
                + node.get("Rows Removed by Index Recheck", 0)
            )
            * node.get("Actual Loops", 1)
            for node in scans
        )
        buffers = root["Plan"].get("Shared Hit Blocks", 0) + root["Plan"].get(
            "Shared Read Blocks", 0
        )
        summary = {
            "target": target,
            "source_count": BATCH_SIZE,
            "history_per_source": HISTORY_PER_SOURCE,
            "retained_receipts": retained_count,
            "query_count": len(statements),
            "orm_loads": materialized,
            "returned_dtos": len(jobs),
            "sql_bytes": len(measured["statement"].encode()),
            "call_seconds": elapsed,
            "planning_ms": root.get("Planning Time"),
            "execution_ms": root.get("Execution Time"),
            "jit": root.get("JIT"),
            "root_actual_rows": root["Plan"].get("Actual Rows"),
            "root_actual_loops": root["Plan"].get("Actual Loops"),
            "job_scan_rows_examined": examined,
            "shared_buffers": buffers,
            "qualification": "Synthetic isolated test data; 16 sources/512 receipts each. "
            "Not a production-cardinality or HTTP latency certification.",
        }
        _save(directory, "measurement-summary.json", summary)
        record_property("document_processing_snapshot_plan", json.dumps(summary))
        record_property("document_processing_snapshot_artifact", str(directory))
        assert scans and examined > 0
        assert root["Plan"].get("Actual Rows") == BATCH_SIZE
        assert root["Plan"].get("Actual Loops") == 1
        assert examined <= 2 * (retained_count + BATCH_SIZE * 4), summary
        assert buffers <= retained_count * 8 + BATCH_SIZE * 64, summary
        assert summary["sql_bytes"] <= 16_384, summary
        assert elapsed < 10 and root["Execution Time"] < 10_000, summary
