"""Real downstream compliance/FK overlaps, not a no-op extraction substitute."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import Event
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    DocumentProcessingJob,
    DocumentProcessingStatus,
    Matter,
    MatterAttachment,
    MatterComplianceExtractionRun,
    MatterComplianceItem,
    MatterCourtOrder,
    MatterCourtSyncJob,
    MatterDeadline,
    MatterTask,
    ModelRun,
    NotificationDeliveryIntent,
    PrivateProjectionEvent,
    User,
)
from caseops_api.schemas.matters import (
    MatterAttachmentMetadataUpdateRequest,
    MatterCourtOrderCreateRequest,
    MatterCourtOrderSyncItem,
    MatterCourtOrderUpdateRequest,
    MatterCourtSyncImportRequest,
    MatterLifecycleStatusRequest,
)
from caseops_api.services import (
    compliance_extraction,
    compliance_participants,
    court_sync_jobs,
    document_processing,
    matters,
)
from caseops_api.services.assignment_memberships import lock_company_memberships_for_assignment
from caseops_api.services.document_storage import StoredDocument
from caseops_api.services.llm import LLMCompletion
from tests.test_document_finalizer_overlap_20261009_postgres import (
    _FinalizerAudit,
    _seed_finalizer,  # noqa: F401
)
from tests.test_document_finalizer_overlap_20261009_postgres import (
    finalizer_audit as _finalizer_audit_fixture,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _ip_race_context,
    _seed_membership,
)

pytestmark = pytest.mark.postgres
finalizer_audit = _finalizer_audit_fixture
_TEXT = "The parties shall comply within two weeks from today."
_MAX_PREFLIGHT_READ_RECEIPTS = 32


class _UploadPhase:
    def __init__(self, audit):
        self.audit = audit
        self.phase = "preflight"
        self.storage_complete = Event()
        self.preflight_transaction = None
        self.initial_transaction = None
        self.initial_started = None
        self.initial_duration = None
        self.initial_ended = False
        self.read_count = 0
        self.reads_omitted = 0

    def observe(self, session):
        event.listen(session, "after_transaction_create", self.created)
        event.listen(session, "after_begin", self.began)
        event.listen(session, "after_transaction_end", self.ended)

    def created(self, _session, transaction):
        if transaction.parent is None and self.initial_transaction is None:
            self.initial_transaction = transaction
            self.initial_started = monotonic()

    def began(self, _session, transaction, connection):
        if transaction is self.initial_transaction:
            self.preflight_transaction = connection.info.get("finalizer_transaction")
            self.audit.record(
                "upload_initial_transaction_started", role="mutation",
                pid=self.audit.pids.get("mutation"), transaction=self.preflight_transaction,
                duration_since_create=monotonic() - self.initial_started,
            )

    def ended(self, _session, transaction):
        if transaction is self.initial_transaction:
            self.initial_ended = True
            self.initial_duration = monotonic() - self.initial_started
            self.audit.record(
                "upload_initial_transaction_ended", role="mutation",
                pid=self.audit.pids.get("mutation"), transaction=self.preflight_transaction,
                duration=self.initial_duration,
                reads_observed=self.read_count, reads_omitted=self.reads_omitted,
            )

    def before(self, connection, _cursor, sql, _parameters, context, _many):
        # Supplement only reads omitted by the shared lock/write/election journal.
        if (
            connection.info.get("finalizer_role") != "mutation"
            or self.phase != "preflight"
            or not sql.startswith("SELECT ")
            or (" FROM " not in sql and "\nFROM " not in sql)
            or "FOR " in sql
            or "ORDER BY company_memberships.created_at ASC" in sql
        ):
            return
        self.read_count += 1
        if self.read_count > _MAX_PREFLIGHT_READ_RECEIPTS:
            self.reads_omitted += 1
            return
        context.compliance_preflight_read_ordinal = self.read_count
        self.audit.record(
            "upload_preflight_read_before", role="mutation",
            pid=self.audit.pids.get("mutation"),
            transaction=connection.info.get("finalizer_transaction"),
            ordinal=self.read_count, sql=sql,
        )
        context.compliance_preflight_read_started = monotonic()

    def after(self, connection, _cursor, sql, _parameters, context, _many):
        started = getattr(context, "compliance_preflight_read_started", None)
        if started is not None:
            self.audit.record(
                "upload_preflight_read_after", role="mutation",
                pid=self.audit.pids.get("mutation"),
                transaction=connection.info.get("finalizer_transaction"),
                ordinal=context.compliance_preflight_read_ordinal, sql=sql,
                duration=monotonic() - started,
            )


def _matches_compliance_boundary(
    *, first, path, role, sql, parameters, upload=None, upload_overlap_phase=None,
    transaction=None,
):
    if first == "worker":
        return (
            role == "worker"
            and sql.startswith("INSERT INTO audit_events")
            and isinstance(parameters, dict)
            and parameters.get("action") == "matter_compliance.extraction.completed"
        )
    if first != "mutation" or role != "mutation" or "FOR UPDATE OF matters" not in sql:
        return False
    if path != "attachment_upload":
        return True
    if upload is None or not transaction or not upload.preflight_transaction:
        return False
    if upload_overlap_phase == "preflight":
        return (
            upload.phase == "preflight" and not upload.initial_ended
            and not upload.storage_complete.is_set()
            and transaction == upload.preflight_transaction
        )
    return (
        upload_overlap_phase == "admission"
        and upload.phase == "final_admission" and upload.initial_ended
        and upload.storage_complete.is_set()
        and transaction != upload.preflight_transaction
    )


@pytest.mark.parametrize(
    "phase,storage_complete,initial_ended,transaction,preflight_transaction",
    [
        pytest.param("preflight", False, False, "initial", "initial", id="initial-preflight"),
        pytest.param("storage", False, True, "storage", "initial", id="storage-in-progress"),
        pytest.param("quota_preflight", False, True, "quota", "initial", id="advisory-quota"),
        pytest.param("final_admission", False, True, "final", "initial", id="missing-storage"),
        pytest.param("final_admission", True, False, "final", "initial", id="unreleased-initial"),
        pytest.param("final_admission", True, True, "initial", "initial", id="initial-replay"),
        pytest.param("final_admission", True, True, None, "initial", id="missing-current-token"),
        pytest.param("final_admission", True, True, "final", None, id="missing-initial-token"),
    ],
)
def test_upload_admission_boundary_rejects_incorrect_phase(
    phase, storage_complete, initial_ended, transaction, preflight_transaction,
):
    upload = _UploadPhase(None)
    upload.phase = phase
    upload.initial_ended = initial_ended
    upload.preflight_transaction = preflight_transaction
    if storage_complete:
        upload.storage_complete.set()
    assert not _matches_compliance_boundary(
        first="mutation", path="attachment_upload", role="mutation",
        sql="SELECT matters.id FROM matters FOR UPDATE OF matters", parameters=None,
        upload=upload, upload_overlap_phase="admission", transaction=transaction,
    )


@pytest.mark.parametrize(
    "first,path,role,sql,action,phase,expected",
    [
        pytest.param("worker", "create", "worker", "INSERT INTO audit_events",
                     "matter_compliance.extraction.completed", None, True, id="worker-completed"),
        pytest.param("worker", "create", "worker", "INSERT INTO audit_events",
                     "other.action", None, False, id="wrong-worker-action"),
        pytest.param("worker", "create", "mutation", "INSERT INTO audit_events",
                     "matter_compliance.extraction.completed", None, False, id="wrong-worker-role"),
        pytest.param("mutation", "create", "worker", "FOR UPDATE OF matters",
                     None, None, False, id="wrong-mutation-role"),
        pytest.param("mutation", "create", "mutation", "FOR NO KEY UPDATE OF companies",
                     None, None, False, id="wrong-mutation-lock"),
        pytest.param("mutation", "create", "mutation", "FOR UPDATE OF matters",
                     None, None, True, id="ordinary-mutation"),
        pytest.param("mutation", "attachment_upload", "mutation", "FOR UPDATE OF matters",
                     None, "preflight", True, id="explicit-preflight"),
        pytest.param("mutation", "attachment_upload", "mutation", "FOR UPDATE OF matters",
                     None, "admission", True, id="explicit-admission"),
    ],
)
def test_compliance_boundary_preserves_exact_order_role_and_sql(
    first, path, role, sql, action, phase, expected,
):
    upload = _UploadPhase(None)
    upload.preflight_transaction = "initial"
    if phase == "admission":
        upload.phase = "final_admission"
        upload.initial_ended = True
        upload.storage_complete.set()
    assert _matches_compliance_boundary(
        first=first, path=path, role=role, sql=sql, parameters={"action": action},
        upload=upload, upload_overlap_phase=phase,
        transaction="final" if phase == "admission" else "initial",
    ) is expected
    if path == "attachment_upload":
        assert not _matches_compliance_boundary(
            first=first, path=path, role=role, sql=sql, parameters=None, upload=upload,
            upload_overlap_phase="admission" if phase == "preflight" else "preflight",
            transaction="final" if phase == "admission" else "initial",
        )


def test_upload_preflight_read_receipts_are_bounded_without_private_parameters():
    receipts = []
    audit = SimpleNamespace(
        pids={"mutation": 7},
        record=lambda kind, **data: receipts.append({"event": kind, **data}),
    )
    upload = _UploadPhase(audit)
    connection = SimpleNamespace(info={
        "finalizer_role": "mutation", "finalizer_transaction": "opaque-initial",
    })
    sql = "SELECT matters.id FROM matters WHERE matters.id = %(id)s"
    parameters = {"id": "private-parameter-must-not-be-retained"}
    for _ in range(_MAX_PREFLIGHT_READ_RECEIPTS + 1):
        context = SimpleNamespace()
        upload.before(connection, None, sql, parameters, context, False)
        upload.after(connection, None, sql, parameters, context, False)
    assert upload.read_count == _MAX_PREFLIGHT_READ_RECEIPTS + 1
    assert upload.reads_omitted == 1
    assert len(receipts) == 2 * _MAX_PREFLIGHT_READ_RECEIPTS
    assert all(row["sql"] == sql and row["transaction"] == "opaque-initial" for row in receipts)
    assert all(row["duration"] >= 0 for row in receipts if row["event"].endswith("after"))
    assert parameters["id"] not in repr(receipts)
    assert all("parameters" not in row for row in receipts)


def test_upload_initial_transaction_timing_includes_creation_and_ignores_later_roots(monkeypatch):
    receipts = []
    audit = SimpleNamespace(
        pids={"mutation": 7},
        record=lambda kind, **data: receipts.append({"event": kind, **data}),
    )
    clock = iter((10.0, 11.0, 13.0))
    monkeypatch.setattr(__name__ + ".monotonic", lambda: next(clock))
    upload = _UploadPhase(audit)
    initial = SimpleNamespace(parent=None)
    connection = SimpleNamespace(info={"finalizer_transaction": "opaque-initial"})
    upload.created(None, initial)
    upload.began(None, initial, connection)
    upload.ended(None, SimpleNamespace(parent=initial))
    assert not upload.initial_ended
    upload.ended(None, initial)
    upload.phase = "final_admission"
    later = SimpleNamespace(parent=None)
    upload.created(None, later)
    upload.began(None, later, connection)
    upload.ended(None, later)
    assert upload.initial_ended and upload.preflight_transaction == "opaque-initial"
    assert [row["event"] for row in receipts] == [
        "upload_initial_transaction_started", "upload_initial_transaction_ended",
    ]
    assert receipts[0]["duration_since_create"] == 1.0
    assert receipts[1]["duration"] == 3.0
    assert all(row["transaction"] == "opaque-initial" for row in receipts)


def test_upload_phase_captures_token_after_shared_audit_label_listener():
    receipts, commands = [], []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    upload = _UploadPhase(audit)
    session = audit.session("mutation")
    upload.observe(session)
    initial = SimpleNamespace(parent=None)

    def execute(statement, _parameters=None):
        commands.append(str(statement))

    def scalar(statement):
        commands.append(str(statement))
        return 7

    connection = SimpleNamespace(info={}, execute=execute, scalar=scalar)
    try:
        session.dispatch.after_transaction_create(session, initial)
        session.dispatch.after_begin(session, initial, connection)
        token = connection.info["finalizer_transaction"]
        assert token and upload.preflight_transaction == token
        assert audit.pids["mutation"] == 7
        assert [row["event"] for row in receipts] == [
            "transaction_started", "upload_initial_transaction_started",
        ]
        session.dispatch.after_transaction_end(session, initial)
        assert [row["event"] for row in receipts[-2:]] == [
            "transaction_ended", "upload_initial_transaction_ended",
        ]
        assert all(row["transaction"] == token for row in receipts)
        assert "SET LOCAL lock_timeout = '2s'" in commands
        assert "SET LOCAL statement_timeout = '10s'" in commands
        assert session.get_transaction() is None
    finally:
        session.close()


def _seed(audit):
    fixture = _seed_finalizer(audit.engine, "matter")
    with Session(audit.engine) as session:
        session.get(MatterAttachment, fixture["attachment_id"]).document_type = "order_judgment"
        recipient = _seed_membership(session, fixture["company_id"], role="member")
        session.get(Matter, fixture["matter_id"]).assignee_membership_id = recipient
        order = MatterCourtOrder(
            matter_id=fixture["matter_id"],
            order_date=date(2026, 10, 10),
            title="Native compliance source",
            summary="Source-backed direction",
            source="manual",
            order_text=_TEXT,
        )
        session.add(order)
        session.flush()
        job = MatterCourtSyncJob(
            company_id=fixture["company_id"],
            matter_id=fixture["matter_id"],
            requested_by_membership_id=fixture["actor_id"],
            source="local-emulator",
        )
        session.add(job)
        session.flush()
        fixture.update(order_id=order.id, recipient_id=recipient, court_job_id=job.id)
        session.commit()
    audit.boundary = "compliance"
    return fixture


def _mutate(audit, fixture, path, monkeypatch, upload=None):
    if path == "court_worker":
        order = MatterCourtOrderSyncItem(
            order_date=date(2026, 10, 11),
            title="Worker order",
            summary="Local adapter only",
            order_text=_TEXT,
        )
        adapter = SimpleNamespace(
            fetch=lambda **_: SimpleNamespace(
                summary="Local adapter only",
                orders=[order],
                cause_list_entries=[],
                adapter_name="local-emulator",
            )
        )
        monkeypatch.setattr(court_sync_jobs, "get_court_sync_adapter", lambda _: adapter)
        monkeypatch.setattr(
            court_sync_jobs, "get_session_factory", lambda: lambda: audit.session("mutation")
        )
        court_sync_jobs.run_matter_court_sync_job(fixture["court_job_id"])
        with Session(audit.engine) as session:
            job = session.get(MatterCourtSyncJob, fixture["court_job_id"])
            assert job.status == "completed", job.error_message
        return
    with audit.session("mutation") as session:
        if path == "attachment_upload":
            assert upload is not None
            upload.observe(session)
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        args = dict(context=context, matter_id=fixture["matter_id"])
        if path == "create":
            matters.create_matter_court_order(
                session,
                **args,
                payload=MatterCourtOrderCreateRequest(
                    order_date=date(2026, 10, 12),
                    title="Manual overlap order",
                    summary="Native race",
                    source="manual",
                    order_text=_TEXT,
                    order_attachment_id=fixture["attachment_id"],
                ),
            )
        elif path == "update":
            matters.update_matter_court_order(
                session,
                **args,
                order_id=fixture["order_id"],
                payload=MatterCourtOrderUpdateRequest(is_interim_order=True),
            )
        elif path == "retry":
            compliance_extraction.retry_order_compliance_extraction(
                session,
                **args,
                order_id=fixture["order_id"],
            )
        elif path == "attachment_metadata":
            matters.update_matter_attachment_metadata(
                session,
                **args,
                attachment_id=fixture["attachment_id"],
                payload=MatterAttachmentMetadataUpdateRequest(
                    notice_subject="Native metadata overlap"
                ),
            )
        elif path == "attachment_upload":

            def store(**kwargs):
                assert not session.in_transaction(), "Upload storage must be detached"
                assert upload.initial_ended, "Initial upload transaction must end before storage"
                upload.phase = "storage"
                storage_started = monotonic()
                audit.record(
                    "upload_storage_entered", phase=upload.phase, in_transaction=False,
                    preflight_transaction=upload.preflight_transaction,
                )
                content = kwargs["stream"].read()
                upload.phase = "quota_preflight"
                quota_started = monotonic()
                try:
                    kwargs["before_store"](len(content))
                finally:
                    audit.record(
                        "upload_quota_preflight_returned", phase=upload.phase,
                        duration=monotonic() - quota_started,
                        in_transaction=session.in_transaction(),
                    )
                    upload.phase = "storage"
                assert not session.in_transaction()
                stored = StoredDocument(
                    storage_key="native-upload/" + fixture["attachment_id"],
                    size_bytes=len(content),
                    sha256_hex=sha256(content).hexdigest(),
                )
                upload.phase = "final_admission"
                upload.storage_complete.set()
                audit.record(
                    "upload_storage_complete", phase=upload.phase, in_transaction=False,
                    duration=monotonic() - storage_started,
                    preflight_transaction=upload.preflight_transaction,
                )
                return stored

            monkeypatch.setattr(matters, "persist_matter_attachment", store)
            monkeypatch.setattr(matters, "delete_stored_document", lambda _: None)
            matters.create_matter_attachment(
                session,
                **args,
                filename="order.txt",
                content_type="text/plain",
                stream=BytesIO(b"Local source order document"),
                document_type="order_judgment",
                linked_court_order_id=fixture["order_id"],
            )
        else:
            assert path == "manual_sync"
            matters.create_matter_court_sync_import(
                session,
                **args,
                payload=MatterCourtSyncImportRequest(
                    source="local-emulator",
                    orders=[
                        MatterCourtOrderSyncItem(
                            order_date=date(2026, 10, 13),
                            title="Imported order",
                            summary="Local import",
                            order_text=_TEXT,
                        ),
                    ],
                ),
            )


@pytest.mark.parametrize(
    "path",
    [
        "create",
        "update",
        "retry",
        "attachment_metadata",
        "attachment_upload",
        "manual_sync",
        "court_worker",
    ],
)
@pytest.mark.parametrize("first", ["worker", "mutation"])
@pytest.mark.parametrize("source", ["text", "no_source"])
def test_real_downstream_compliance_completes_in_both_lock_orders(
    finalizer_audit,
    monkeypatch,
    path,
    first,
    source,
):
    _run_downstream_overlap(
        finalizer_audit, monkeypatch, path, first, source,
        upload_overlap_phase="preflight" if path == "attachment_upload" and first == "mutation"
        else None,
    )


@pytest.mark.parametrize("source", ["text", "no_source"])
def test_upload_final_admission_completes_downstream_compliance(
    finalizer_audit, monkeypatch, source,
):
    _run_downstream_overlap(
        finalizer_audit, monkeypatch, "attachment_upload", "mutation", source,
        upload_overlap_phase="admission",
    )


def _run_downstream_overlap(audit, monkeypatch, path, first, source, *, upload_overlap_phase):
    fixture = _seed(audit)
    upload = _UploadPhase(audit) if path == "attachment_upload" else None
    selected_boundary = {}
    audit.record(
        "compliance_test_identity", test_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        path=path, first=first, upload_overlap_phase=upload_overlap_phase,
    )
    if source == "no_source":
        monkeypatch.setattr(
            document_processing,
            "parse_attachment",
            lambda *_, **__: document_processing.ParsedDocument(
                status=DocumentProcessingStatus.INDEXED, extracted_text=None, chunks=[], error=None
            ),
        )
    else:
        monkeypatch.setattr(
            document_processing,
            "parse_attachment",
            lambda *_, **__: document_processing.ParsedDocument(
                status=DocumentProcessingStatus.INDEXED,
                extracted_text=_TEXT,
                chunks=[_TEXT],
                error=None,
            ),
        )
    ready, proceed = Event(), Event()
    original = compliance_extraction.run_compliance_extraction_for_attachment

    def enter_compliance(*args, **kwargs):
        if first == "mutation":
            ready.set()
            assert proceed.wait(8), "Post-index compliance was not started"
        return original(*args, **kwargs)

    monkeypatch.setattr(
        compliance_extraction, "run_compliance_extraction_for_attachment", enter_compliance
    )

    def pause(_connection, _cursor, sql, parameters, _context, _many):
        role = _connection.info.get("finalizer_role")
        transaction = _connection.info.get("finalizer_transaction")
        boundary = _matches_compliance_boundary(
            first=first, path=path, role=role, sql=sql, parameters=parameters,
            upload=upload, upload_overlap_phase=upload_overlap_phase, transaction=transaction,
        )
        if boundary and not audit.entered.is_set():
            selected_boundary.update(
                role=role, pid=audit.pids.get(role), transaction=transaction,
                upload_overlap_phase=upload_overlap_phase,
            )
            audit.record("actual_compliance_boundary", sql=sql, **selected_boundary)
            audit.entered.set()
            started = monotonic()
            released = audit.release.wait(8)
            audit.record("compliance_pause_returned", role=role, released=released,
                         held_seconds=monotonic() - started)
            assert released
            audit.record("compliance_boundary_release_observed", **selected_boundary)

    if upload is not None:
        event.listen(audit.engine, "before_cursor_execute", upload.before)
        event.listen(audit.engine, "after_cursor_execute", upload.after)
    event.listen(audit.engine, "after_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            worker = pool.submit(audit.worker, fixture)
            futures.append(worker)
            if first == "mutation":
                assert ready.wait(8), "Real indexing commit was not reached"
            else:
                assert audit.entered.wait(8)
            mutation = pool.submit(_mutate, audit, fixture, path, monkeypatch, upload)
            futures.append(mutation)
            if first == "mutation":
                assert audit.entered.wait(8)
                assert selected_boundary["pid"] == audit.pids["mutation"]
                if upload is not None:
                    assert selected_boundary["upload_overlap_phase"] == upload_overlap_phase
                    assert _matches_compliance_boundary(
                        first=first, path=path, role="mutation", sql="FOR UPDATE OF matters",
                        parameters=None, upload=upload, upload_overlap_phase=upload_overlap_phase,
                        transaction=selected_boundary["transaction"],
                    )
                proceed.set()
            audit.await_blocker("mutation" if first == "worker" else "worker", first,
                                on_observed=audit.release.set)
            audit.record("compliance_boundary_release_requested", **selected_boundary)
            audit.record("release_compliance_after_blocker", first=first)
            worker.result(10)
            mutation.result(10)
    finally:
        proceed.set()
        audit.release.set()
        event.remove(audit.engine, "after_cursor_execute", pause)
        if upload is not None:
            event.remove(audit.engine, "before_cursor_execute", upload.before)
            event.remove(audit.engine, "after_cursor_execute", upload.after)
    assert audit.errors == []
    if upload is not None:
        assert upload.initial_ended and upload.storage_complete.is_set()
    with Session(audit.engine) as session:
        job = session.get(DocumentProcessingJob, fixture["job_id"])
        assert job.status == "completed" and job.error_message is None
        attachment = session.get(MatterAttachment, fixture["attachment_id"])
        assert attachment.processing_status == DocumentProcessingStatus.INDEXED
        runs = list(
            session.scalars(
                select(MatterComplianceExtractionRun).where(
                    MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
                    MatterComplianceExtractionRun.trigger == "attachment_processed",
                    MatterComplianceExtractionRun.attachment_id == fixture["attachment_id"],
                )
            )
        )
        expected_status = "skipped" if source == "no_source" else "completed"
        assert runs and all(run.status == expected_status for run in runs)
        if source == "no_source":
            assert all(run.skip_reason == "text_extraction_pending" for run in runs)
        assert all(run.created_by_membership_id is None for run in runs)
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.action == "matter_compliance.extraction.completed",
                    AuditEvent.target_id.in_([run.id for run in runs]),
                )
            )
        )
        assert len(audits) == len(runs)
        assert all(row.actor_membership_id == fixture["actor_id"] for row in audits)
        if source == "text" and first == "worker":
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(MatterComplianceItem)
                    .where(
                        MatterComplianceItem.attachment_id == fixture["attachment_id"],
                    )
                )
                > 0
            )
        if path == "attachment_upload":
            uploaded_runs = list(
                session.scalars(
                    select(MatterComplianceExtractionRun).where(
                        MatterComplianceExtractionRun.matter_id == fixture["matter_id"],
                        MatterComplianceExtractionRun.trigger == "attachment_processed",
                        MatterComplianceExtractionRun.attachment_id != fixture["attachment_id"],
                    )
                )
            )
            assert len(uploaded_runs) == 1
            assert uploaded_runs[0].status == "skipped"
            assert uploaded_runs[0].skip_reason == "text_extraction_pending"
            assert uploaded_runs[0].created_by_membership_id == fixture["actor_id"]


def test_upload_initial_transaction_is_observed_without_artificial_pause(
    finalizer_audit, monkeypatch,
):
    audit = finalizer_audit
    fixture = _seed(audit)
    upload = _UploadPhase(audit)
    audit.record(
        "compliance_test_identity", test_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        path="attachment_upload", upload_overlap_phase="passive_initial", artificial_pause=False,
    )
    event.listen(audit.engine, "before_cursor_execute", upload.before)
    event.listen(audit.engine, "after_cursor_execute", upload.after)
    try:
        _mutate(audit, fixture, "attachment_upload", monkeypatch, upload)
    finally:
        event.remove(audit.engine, "before_cursor_execute", upload.before)
        event.remove(audit.engine, "after_cursor_execute", upload.after)
    assert audit.errors == []
    assert not audit.entered.is_set(), "Passive upload must not enter any artificial pause"
    assert upload.initial_ended and upload.storage_complete.is_set()
    assert upload.preflight_transaction and upload.initial_duration is not None
    with Session(audit.engine) as session:
        uploaded = list(session.scalars(select(MatterAttachment).where(
            MatterAttachment.matter_id == fixture["matter_id"],
            MatterAttachment.id != fixture["attachment_id"],
        )))
        assert len(uploaded) == 1
        runs = list(session.scalars(select(MatterComplianceExtractionRun).where(
            MatterComplianceExtractionRun.attachment_id == uploaded[0].id,
            MatterComplianceExtractionRun.trigger == "attachment_processed",
        )))
        assert len(runs) == 1 and runs[0].status == "skipped"
        assert runs[0].skip_reason == "text_extraction_pending"
        assert runs[0].created_by_membership_id == fixture["actor_id"]


def _generated_count(session, fixture):
    return {
        model.__tablename__: session.scalar(
            select(func.count())
            .select_from(model)
            .where(
                model.matter_id == fixture["matter_id"],
            )
        )
        for model in (
            MatterComplianceExtractionRun,
            MatterComplianceItem,
            ModelRun,
            MatterTask,
            MatterDeadline,
            NotificationDeliveryIntent,
        )
    }


def test_disposal_wins_after_index_commit_without_discarding_index(finalizer_audit, monkeypatch):
    audit = finalizer_audit
    fixture = _seed(audit)
    original = compliance_extraction.run_compliance_extraction_for_attachment

    def enter(*args, **kwargs):
        audit.entered.set()
        assert audit.release.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(compliance_extraction, "run_compliance_extraction_for_attachment", enter)
    with audit.pool() as (pool, futures):
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert audit.entered.wait(8)
        audit.mutate(fixture, operation="dispose", source=True)
        audit.release.set()
        worker.result(10)
    with Session(audit.engine) as session:
        parent = session.get(Matter, fixture["matter_id"])
        assert parent.status == "disposed" and not parent.is_active
        attachment = session.get(MatterAttachment, fixture["attachment_id"])
        assert attachment.processing_status == "indexed" and attachment.extracted_text
        job = session.get(DocumentProcessingJob, fixture["job_id"])
        assert job.status == "completed" and job.error_message
        retained = session.scalar(
            select(PrivateProjectionEvent).where(
                PrivateProjectionEvent.idempotency_key == f"matter-document-indexed:{job.id}",
            )
        )
        assert retained is not None and retained.status == "applied"
        assert retained.actor_membership_id == fixture["actor_id"]
        assert set(_generated_count(session, fixture).values()) == {0}
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.matter_id == fixture["matter_id"],
                    AuditEvent.action == "matter_compliance.extraction.completed",
                )
            )
            == 0
        )


@pytest.mark.parametrize("revocation", ["membership", "user", "capability", "cutoff", "company"])
def test_live_authority_revocation_wins_before_persistence(finalizer_audit, revocation):
    audit = finalizer_audit
    fixture = _seed(audit)

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if (
            connection.info.get("finalizer_role") == "mutation"
            and "FOR NO KEY UPDATE OF companies" in sql
            and not audit.entered.is_set()
        ):
            audit.entered.set()
            assert audit.release.wait(8)

    def request():
        with audit.session("mutation") as session:
            context = _ip_race_context(
                session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
            )
            context.token_issued_at = (datetime.now(UTC) - timedelta(days=1)).timestamp()
            with pytest.raises(HTTPException) as rejected:
                compliance_extraction.retry_order_compliance_extraction(
                    session,
                    context=context,
                    matter_id=fixture["matter_id"],
                    order_id=fixture["order_id"],
                )
            assert rejected.value.status_code in {401, 403}
            session.rollback()

    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            contender = pool.submit(request)
            futures.append(contender)
            assert audit.entered.wait(8)
            with audit.session("revocation") as session:
                member = session.get(CompanyMembership, fixture["actor_id"])
                if revocation == "membership":
                    member.is_active = False
                elif revocation == "user":
                    session.get(User, fixture["user_id"]).is_active = False
                elif revocation == "capability":
                    member.role = "viewer"
                elif revocation == "cutoff":
                    member.sessions_valid_after = datetime.now(UTC)
                else:
                    session.get(Company, fixture["company_id"]).is_active = False
                session.commit()
            audit.release.set()
            contender.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    assert audit.errors == []
    with Session(audit.engine) as session:
        assert set(_generated_count(session, fixture).values()) == {0}


@pytest.mark.parametrize("creator", ["active", "inactive", "null"])
def test_creator_provenance_is_not_replaced_by_audit_election(finalizer_audit, creator):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        historical = _seed_membership(session, fixture["company_id"], role="member")
        if creator == "inactive":
            session.get(CompanyMembership, historical).is_active = False
        session.commit()
    actor_id = None if creator == "null" else historical
    with audit.session("worker") as session:
        parent = session.get(Matter, fixture["matter_id"])
        run, items = compliance_extraction.run_compliance_extraction_for_order(
            session,
            matter=parent,
            order=session.get(MatterCourtOrder, fixture["order_id"]),
            actor_membership_id=actor_id,
        )
        session.commit()
        assert run.created_by_membership_id == actor_id
        assert run.status == "completed" and items
        row = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "matter_compliance.extraction.completed",
            )
        )
        assert row.actor_membership_id == (actor_id if creator == "active" else fixture["actor_id"])
        intents = list(
            session.scalars(
                select(NotificationDeliveryIntent).where(
                    NotificationDeliveryIntent.matter_id == parent.id,
                )
            )
        )
        assert intents and {intent.recipient_membership_id for intent in intents} == {
            fixture["recipient_id"],
        }


@pytest.mark.parametrize("participant", ["audit", "recipient"])
def test_actual_participant_fk_is_fenced_before_parent(finalizer_audit, monkeypatch, participant):
    audit = finalizer_audit
    fixture = _seed(audit)
    monkeypatch.setattr(
        document_processing,
        "parse_attachment",
        lambda *_, **__: document_processing.ParsedDocument(
            status=DocumentProcessingStatus.INDEXED,
            extracted_text=_TEXT,
            chunks=[_TEXT],
            error=None,
        ),
    )
    target = fixture["actor_id"] if participant == "audit" else fixture["recipient_id"]
    ready, proceed = Event(), Event()
    original = compliance_extraction.run_compliance_extraction_for_attachment

    def enter(*args, **kwargs):
        ready.set()
        assert proceed.wait(8)
        return original(*args, **kwargs)

    monkeypatch.setattr(compliance_extraction, "run_compliance_extraction_for_attachment", enter)
    with audit.pool() as (pool, futures):
        worker = pool.submit(audit.worker, fixture)
        futures.append(worker)
        assert ready.wait(8), "Real indexing must commit before participant overlap"
        with audit.session("revocation") as blocker:
            lock_company_memberships_for_assignment(
                blocker,
                company_id=fixture["company_id"],
                membership_ids=[target],
            )
            proceed.set()
            audit.await_blocker("worker", "revocation")
            # The wait must be in downstream participant acquisition, not indexing.
            assert any(
                "FOR UPDATE OF company_memberships" in sql for sql in audit.statements["worker"]
            )
            with audit.session("mutation") as observer:
                parent = observer.scalar(
                    select(Matter)
                    .where(
                        Matter.id == fixture["matter_id"],
                    )
                    .with_for_update(of=Matter)
                )
                assert parent is not None
                observer.rollback()
            blocker.rollback()
        worker.result(10)
    assert audit.errors == []
    with Session(audit.engine) as session:
        assert session.get(DocumentProcessingJob, fixture["job_id"]).error_message is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(NotificationDeliveryIntent)
                .where(
                    NotificationDeliveryIntent.matter_id == fixture["matter_id"],
                    NotificationDeliveryIntent.recipient_membership_id == fixture["recipient_id"],
                    NotificationDeliveryIntent.event_type == "compliance_review_required",
                )
            )
            > 0
        )


@pytest.mark.parametrize("change", ["recipient", "assignee", "audit"])
def test_selection_change_does_not_expand_locks_behind_parent(finalizer_audit, change):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        replacement = _seed_membership(session, fixture["company_id"], role="admin")
        session.commit()

    def pause(connection, _cursor, sql, _parameters, _context, _many):
        if (
            connection.info.get("finalizer_role") == "worker"
            and "FOR UPDATE OF company_memberships" in sql
            and not audit.entered.is_set()
        ):
            audit.entered.set()
            assert audit.release.wait(8)

    def extract():
        with audit.session("worker") as session:
            with pytest.raises(compliance_extraction.ComplianceParticipantFenceError) as rejected:
                compliance_extraction.run_compliance_extraction_for_order(
                    session,
                    matter=session.get(Matter, fixture["matter_id"]),
                    order=session.get(MatterCourtOrder, fixture["order_id"]),
                )
            assert rejected.value.detail["code"] == "compliance_participants_changed"
            session.rollback()

    event.listen(audit.engine, "before_cursor_execute", pause)
    try:
        with audit.pool() as (pool, futures):
            contender = pool.submit(extract)
            futures.append(contender)
            assert audit.entered.wait(8)
            with audit.session("revocation") as session:
                if change == "assignee":
                    session.get(Matter, fixture["matter_id"]).assignee_membership_id = replacement
                else:
                    target = (
                        fixture["recipient_id"] if change == "recipient" else fixture["actor_id"]
                    )
                    session.get(CompanyMembership, target).is_active = False
                session.commit()
            audit.release.set()
            contender.result(10)
    finally:
        audit.release.set()
        event.remove(audit.engine, "before_cursor_execute", pause)
    with Session(audit.engine) as session:
        assert set(_generated_count(session, fixture).values()) == {0}
    assert audit.errors == []


@pytest.mark.parametrize("actor_kind", ["null", "historical", "inactive_historical"])
def test_prepared_model_run_keeps_creator_and_confirm_keeps_work_owner(
    finalizer_audit,
    monkeypatch,
    actor_kind,
):
    audit = finalizer_audit
    fixture = _seed(audit)
    actor_id = None if actor_kind == "null" else fixture["actor_id"]
    if actor_kind == "inactive_historical":
        with Session(audit.engine) as session:
            actor_id = _seed_membership(session, fixture["company_id"], role="member")
            historical = session.get(CompanyMembership, actor_id)
            historical.is_active = False
            session.get(User, historical.user_id).is_active = False
            session.commit()
    # Emulate only provider output; keep downstream persistence real.
    prepared = compliance_extraction._PreparedAICompliance(
        payload=compliance_extraction._AICompliancePayload(
            items=[
                compliance_extraction._AIComplianceItem(
                    description="File source-backed compliance",
                    source_snippet=_TEXT,
                    due_on=date(2026, 10, 24),
                ),
            ]
        ),
        completion=LLMCompletion(
            text="local valid structured output",
            provider="mock",
            model="mock",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        ),
        prompt_hash="a" * 64,
    )
    monkeypatch.setattr(compliance_extraction, "_prepare_ai_items", lambda *_, **__: prepared)
    with audit.session("worker") as session:
        run, items = compliance_extraction.run_compliance_extraction_for_order(
            session,
            matter=session.get(Matter, fixture["matter_id"]),
            order=session.get(MatterCourtOrder, fixture["order_id"]),
            actor_membership_id=actor_id,
        )
        session.commit()
        model = session.get(ModelRun, run.model_run_id)
        assert model is not None and model.actor_membership_id == actor_id
        item_id = next(item.id for item in items if item.due_on is not None)
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        item = compliance_extraction.update_compliance_item(
            session,
            context=context,
            matter_id=fixture["matter_id"],
            item_id=item_id,
            action="confirm",
        )
        task = session.get(MatterTask, item.generated_task_id)
        deadline = session.get(MatterDeadline, item.generated_deadline_id)
        assert (
            task.owner_membership_id == deadline.assignee_membership_id == fixture["recipient_id"]
        )
        assert (
            task.created_by_membership_id
            == deadline.created_by_membership_id
            == fixture["actor_id"]
        )
    audit.mutate(fixture, operation="dispose", source=True)
    with Session(audit.engine) as session:
        assert session.get(MatterTask, task.id).status == "cancelled"
        assert session.get(MatterDeadline, deadline.id).status == "cancelled"
        assert session.get(Matter, fixture["matter_id"]).status == "disposed"
    with audit.session("mutation") as session:
        context = _ip_race_context(
            session, company_id=fixture["company_id"], membership_id=fixture["actor_id"]
        )
        parent = session.get(Matter, fixture["matter_id"])
        matters.transition_matter_lifecycle_status(
            session,
            context=context,
            matter_id=parent.id,
            payload=MatterLifecycleStatusRequest(
                to_status="intake",
                expected_from_status="disposed",
                expected_updated_at=parent.updated_at,
                reason="Controlled reopen preserves neutralized work.",
            ),
        )
        assert session.get(MatterTask, task.id).status == "cancelled"
        assert session.get(MatterDeadline, deadline.id).status == "cancelled"
        parent = session.get(Matter, fixture["matter_id"])
        assert parent.status == "intake" and parent.lifecycle_version == 2
        matters.transition_matter_lifecycle_status(
            session,
            context=context,
            matter_id=parent.id,
            payload=MatterLifecycleStatusRequest(
                to_status="disposed",
                expected_from_status="intake",
                expected_updated_at=parent.updated_at,
                reason="Second native closure preserves neutralized work.",
            ),
        )
    with Session(audit.engine) as session:
        assert session.get(Matter, fixture["matter_id"]).lifecycle_version == 3
        assert session.get(MatterTask, task.id).status == "cancelled"
        assert session.get(MatterDeadline, deadline.id).status == "cancelled"


def test_participant_inventory_is_bounded_before_any_parent_lock(finalizer_audit):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        for _ in range(compliance_participants._MAX_PARTICIPANTS):
            _seed_membership(session, fixture["company_id"], role="admin")
        session.commit()
    with audit.session("worker") as session:
        with pytest.raises(compliance_extraction.ComplianceParticipantFenceError) as rejected:
            compliance_extraction.run_compliance_extraction_for_order(
                session,
                matter=session.get(Matter, fixture["matter_id"]),
                order=session.get(MatterCourtOrder, fixture["order_id"]),
            )
        assert rejected.value.detail["code"] == "compliance_participant_limit"
        assert not any("FOR UPDATE OF matters" in sql for sql in audit.statements["worker"])
        session.rollback()


@pytest.mark.parametrize("selection", ["member_fallback", "no_live_null", "no_live_historical"])
def test_existing_fallback_and_no_live_context_semantics_are_preserved(finalizer_audit, selection):
    audit = finalizer_audit
    fixture = _seed(audit)
    with Session(audit.engine) as session:
        session.get(CompanyMembership, fixture["actor_id"]).is_active = False
        if selection != "member_fallback":
            session.get(CompanyMembership, fixture["recipient_id"]).is_active = False
        session.commit()
    actor_id = fixture["actor_id"] if selection == "no_live_historical" else None
    with audit.session("worker") as session:
        run, _ = compliance_extraction.run_compliance_extraction_for_order(
            session,
            matter=session.get(Matter, fixture["matter_id"]),
            order=session.get(MatterCourtOrder, fixture["order_id"]),
            actor_membership_id=actor_id,
        )
        session.commit()
        assert run.status == "completed" and run.created_by_membership_id == actor_id
        row = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "matter_compliance.extraction.completed",
            )
        )
        expected = fixture["recipient_id"] if selection == "member_fallback" else actor_id
        assert row.actor_membership_id == expected


@pytest.mark.parametrize("tier", ["admin", "member"])
@pytest.mark.parametrize("creator", ["null", "inactive_historical"])
def test_equal_creation_time_election_is_stable_without_replacing_creator(
    finalizer_audit, tier, creator
):
    audit = finalizer_audit
    fixture = _seed(audit)
    tied_at = datetime(2026, 10, 10, 0, 0, tzinfo=UTC)
    with Session(audit.engine) as session:
        session.get(CompanyMembership, fixture["actor_id"]).is_active = False
        session.get(CompanyMembership, fixture["recipient_id"]).is_active = False
        candidates = [_seed_membership(session, fixture["company_id"], role=tier) for _ in range(2)]
        for member_id in candidates:
            session.get(CompanyMembership, member_id).created_at = tied_at
        session.commit()
    actor_id = None if creator == "null" else fixture["actor_id"]
    elected_id = min(candidates)
    with audit.session("worker") as session:
        for _ in range(3):
            elected = compliance_participants._select_notification_context(
                session, company_id=fixture["company_id"], actor_membership_id=actor_id
            )
            assert elected.membership.id == elected_id
        run, _ = compliance_extraction.run_compliance_extraction_for_order(
            session,
            matter=session.get(Matter, fixture["matter_id"]),
            order=session.get(MatterCourtOrder, fixture["order_id"]),
            actor_membership_id=actor_id,
        )
        assert run.status == "completed" and run.created_by_membership_id == actor_id
        session.commit()
        row = session.scalar(
            select(AuditEvent).where(
                AuditEvent.target_id == run.id,
                AuditEvent.action == "matter_compliance.extraction.completed",
            )
        )
        assert row.actor_membership_id == elected_id
    with Session(audit.engine) as session:
        elected = compliance_participants._select_notification_context(
            session, company_id=fixture["company_id"], actor_membership_id=actor_id
        )
        assert elected.membership.id == elected_id
    assert any(
        "ORDER BY company_memberships.created_at ASC, company_memberships.id ASC" in sql
        for sql in audit.statements["worker"]
    )
