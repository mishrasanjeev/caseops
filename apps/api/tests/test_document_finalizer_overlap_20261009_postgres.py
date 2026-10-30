"""Actual finalizer/identity overlap: local susceptibility, not Cloud Run CPU proof.

CASEOPS_FINALIZER_AUTH_BASELINE=strong replays only the former auth lock option
in this process. It intentionally makes the same login acceptance fail; no
runtime file, live service, provider, or transaction fence is replaced.
"""

from __future__ import annotations

import builtins
import ctypes
import dis
import gc
import json
import os
import secrets
import socket
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
from time import monotonic, monotonic_ns, sleep, time_ns
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import uvicorn
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import DBAPIError
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
    court_sync_jobs,
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


class _Timespec(ctypes.Structure):
    _fields_ = [("seconds", ctypes.c_long), ("nanoseconds", ctypes.c_long)]


class _GcTimingSlot:
    __slots__ = ("phase", "generation", "mono", "utc", "mono_pointer", "utc_pointer", "next")

    def __init__(self, cell_type):
        self.phase = self.generation = self.next = None
        self.mono, self.utc = cell_type(), cell_type()
        self.mono_pointer, self.utc_pointer = ctypes.byref(self.mono), ctypes.byref(self.utc)


class _PassiveOverlapTiming:
    """Bounded metadata only; callbacks never write evidence or take a Python lock."""

    ACTORS = frozenset(("worker", "login", "mutation", "revocation", "auth"))
    # Includes setup SELECTs for the existing 500-recipient native fixture.
    # This bounds evidence retention, not the workflow's asserted query budget.
    SQL_CAP = 16384
    # CI exhausted 512 phase cells during the existing repeated 501-row negative
    # fixture. Bound metadata separately from GC policy and keep overflow fatal.
    GC_CAP = 4096
    TEMPLATE_CAP = 65536

    def __init__(self, *, sql_cap=SQL_CAP, gc_cap=GC_CAP):
        assert 0 < sql_cap <= self.SQL_CAP and 0 < gc_cap <= self.GC_CAP
        self.sql_slots = [{} for _ in range(sql_cap)]
        self.available_sql = deque(self.sql_slots)
        self.sql_overflow = self.gc_overflow = self.invalid = False
        self.enabled = False
        self.critical_pools = 0
        # PyDLL retains the GIL; native clocks fill cells allocated before registration.
        # No Python timestamp objects, record containers or counters are built in GC.
        if os.name == "nt":
            library = ctypes.PyDLL("kernel32", use_last_error=True)
            self.mono_clock = library.QueryPerformanceCounter
            self.utc_clock = library.GetSystemTimePreciseAsFileTime
            for clock in (self.mono_clock, self.utc_clock):
                clock.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
                clock.restype = None
            frequency = ctypes.c_longlong()
            get_frequency = library.QueryPerformanceFrequency
            get_frequency.argtypes = [ctypes.POINTER(ctypes.c_longlong)]
            get_frequency.restype = ctypes.c_int
            assert get_frequency(ctypes.byref(frequency)) and frequency.value > 0
            self.frequency = frequency.value
            cell_type = ctypes.c_longlong
        else:
            clock = ctypes.PyDLL(None).clock_gettime
            clock.argtypes = [ctypes.c_int, ctypes.POINTER(_Timespec)]
            clock.restype = None
            self.mono_clock = partial(clock, ctypes.c_int(time.CLOCK_MONOTONIC))
            self.utc_clock = partial(clock, ctypes.c_int(time.CLOCK_REALTIME))
            cell_type = _Timespec
        self.gc_slots = [_GcTimingSlot(cell_type) for _ in range(gc_cap)]
        for previous, following in zip(self.gc_slots, self.gc_slots[1:], strict=False):
            previous.next = following
        self.next_gc = self.gc_slots[0]
        self.mono_clock(self.next_gc.mono_pointer)
        self.utc_clock(self.next_gc.utc_pointer)
        assert self._gc_ns(self.next_gc)[0] > 0 and self._gc_ns(self.next_gc)[1] > 0

    @property
    def callback(self):
        # The registered bound method owns us only until stop removes it.
        return self._gc_callback

    def _gc_callback(self, phase, info):
        if not self.enabled:
            return
        slot = self.next_gc
        if slot is None:
            self.gc_overflow = True
            return
        # Local completion cannot clear an independent SQL-recorder invalid mark.
        recording_complete = False
        try:
            self.next_gc = slot.next
            slot.phase = phase
            slot.generation = info["generation"]
            self.mono_clock(slot.mono_pointer)
            self.utc_clock(slot.utc_pointer)
            recording_complete = True
        except Exception:
            return
        finally:
            if not recording_complete:
                self.invalid = True

    def start(self):
        assert not self.enabled and self.callback not in gc.callbacks
        self.enabled = True
        gc.callbacks.append(self.callback)

    def stop(self):
        self.enabled = False
        if self.callback in gc.callbacks:
            gc.callbacks.remove(self.callback)

    @contextmanager
    def capture(self):
        try:
            self.start()
            yield self
        finally:
            self.stop()

    def begin_select(self, actor, statement, context):
        if not self.enabled or not statement.lstrip()[:6].upper().startswith(("SELECT", "WITH")):
            return
        if context is None or len(statement) > self.TEMPLATE_CAP:
            self.invalid = True
            return
        digest = sha256(statement.encode("utf-8")).hexdigest()
        try:
            sample = self.available_sql.popleft()
        except IndexError:
            self.sql_overflow = True
            return
        sample.update(actor=actor if actor in self.ACTORS else "unlabelled",
                      template_sha256=digest, utc_started_ns=time_ns(),
                      mono_started_ns=monotonic_ns(), outcome="incomplete")
        context.finalizer_passive_select = sample

    def end_select(self, context, *, error=False):
        sample = getattr(context, "finalizer_passive_select", None)
        if sample is not None:
            sample.update(mono_finished_ns=monotonic_ns(), utc_finished_ns=time_ns(),
                          outcome="error" if error else "ok")
            context.finalizer_passive_select = None

    def _gc_ns(self, slot):
        if os.name == "nt":
            return (slot.mono.value * 1_000_000_000 // self.frequency,
                    (slot.utc.value - 116444736000000000) * 100)
        assert 0 <= slot.mono.nanoseconds < 1_000_000_000
        assert 0 <= slot.utc.nanoseconds < 1_000_000_000
        return (slot.mono.seconds * 1_000_000_000 + slot.mono.nanoseconds,
                slot.utc.seconds * 1_000_000_000 + slot.utc.nanoseconds)

    def flush(self, record):
        assert not self.enabled and self.callback not in gc.callbacks, "Passive capture is active"
        assert not self.critical_pools, "Passive evidence cannot flush during owned worker timing"
        samples = [row for row in self.sql_slots if row]
        incomplete = sum(row["outcome"] == "incomplete" for row in samples)
        gc_events, started = [], None
        complete = False
        for slot in self.gc_slots:
            if slot.phase is None:
                break
            mono, utc = self._gc_ns(slot)
            if slot.phase == "start" and started is None and slot.generation in (0, 1, 2):
                started = (mono, utc, slot.generation)
            elif (slot.phase == "stop" and started is not None
                  and slot.generation == started[2] and mono >= started[0]):
                gc_events.append({"generation": slot.generation,
                                  "mono_started_ns": started[0], "mono_finished_ns": mono,
                                  "utc_started_ns": started[1], "utc_finished_ns": utc,
                                  "duration_ns": mono - started[0]})
                started = None
            else:
                self.invalid = True
        complete = not (self.invalid or self.sql_overflow or self.gc_overflow
                        or incomplete or started is not None)
        record("passive_timing_summary", complete=complete, select_count=len(samples),
               gc_count=len(gc_events), sql_cap=len(self.sql_slots),
               gc_phase_cap=len(self.gc_slots),
               sql_overflow=self.sql_overflow, gc_overflow=self.gc_overflow,
               invalid=self.invalid, incomplete_selects=incomplete, unpaired_gc=started is not None,
               flushed_after_workers=True, gc_scope="process-wide; no actor/thread attribution",
               clock_limits="Native cells; no zero CPython/ctypes internal-allocation claim",
               select_scope="Leading SELECT/WITH on fixture engine; cleanup reads excluded",
               duration_scope="Engine event interval; may include later before-event listeners")
        for row in samples:
            output = dict(row)
            if row["outcome"] != "incomplete":
                output["duration_ns"] = row["mono_finished_ns"] - row["mono_started_ns"]
            record("passive_select_timing", **output)
        for row in gc_events:
            record("passive_gc_timing", **row)
        assert complete, "Passive timing evidence is incomplete"


class _FinalizerAudit:
    def __init__(self, engine, record):
        self.engine, self.record = engine, record
        self.entered, self.release = Event(), Event()
        self.auth_body_complete = Event()
        self.require_auth_before_writer = False
        self.boundary = "applied"
        self.pids, self.errors, self.statements = {}, [], {}
        self.statement_counts = {}
        self.passive = None
        self.all_pids = set()
        self.instance = f"finalizer-{uuid4().hex[:12]}"
        self.names = {role: f"{self.instance}-{role}"
                      for role in ("worker", "login", "mutation", "revocation", "auth")}
        self.factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.hooks = [("before_cursor_execute", self.before),
                      ("after_cursor_execute", self.after), ("handle_error", self.error)]

    def flush_passive_evidence(self):
        timing = self.passive
        assert timing is not None
        assert not timing.enabled and timing.callback not in gc.callbacks, (
            "Passive capture is active"
        )
        assert not timing.critical_pools, "Passive evidence cannot flush during owned worker timing"
        try:
            timing.flush(self.record)
        finally:
            self.passive = None

    def session(self, role):
        session = self.factory()
        session.info["finalizer_role"] = role

        def label(_session, _transaction, connection):
            connection.info["finalizer_role"] = role
            connection.info["finalizer_transaction"] = uuid4().hex
            _session.info["finalizer_transaction"] = connection.info["finalizer_transaction"]
            connection.execute(text("SELECT set_config('application_name', :name, true)"),
                               {"name": self.names[role]})
            connection.execute(text("SET LOCAL lock_timeout = '2s'"))
            connection.execute(text("SET LOCAL statement_timeout = '10s'"))
            pid = connection.scalar(text("SELECT pg_backend_pid()"))
            self.pids[role] = pid
            self.all_pids.add(pid)
            self.record("transaction_started", role=role, pid=pid, instance=self.instance,
                        transaction=connection.info["finalizer_transaction"])

        def ended(_session, transaction):
            if transaction.parent is None:
                self.record("transaction_ended", role=role, pid=self.pids.get(role),
                            transaction=_session.info.pop("finalizer_transaction", None))

        event.listen(session, "after_begin", label)
        event.listen(session, "after_transaction_end", ended)
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
            if _context is not None:
                _context.finalizer_sql_started = monotonic()
            # Only statement templates: never parameters, document text or auth bodies.
            self.record("sql_before", role=role, pid=self.pids.get(role), sql=sql,
                        transaction=connection.info.get("finalizer_transaction"))
        if self.passive is not None:
            self.passive.begin_select(role, sql, _context)

    def after(self, connection, _cursor, sql, parameters, _context, _many):
        if self.passive is not None:
            self.passive.end_select(_context)
        role = connection.info.get("finalizer_role")
        started = getattr(_context, "finalizer_sql_started", None)
        if role in self.names and started is not None:
            self.record("sql_after", role=role, pid=self.pids.get(role), sql=sql,
                        transaction=connection.info.get("finalizer_transaction"),
                        duration=monotonic() - started)
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
        passive = getattr(self, "passive", None)
        if passive is not None:
            passive.end_select(getattr(context, "execution_context", None), error=True)
        original = context.original_exception
        connection = getattr(context, "connection", None)
        role = connection.info.get("finalizer_role") if connection is not None else None
        row = {"sqlstate": getattr(original, "sqlstate", None),
               "native_message": getattr(getattr(original, "diag", None), "message_primary", None),
               "sql": context.statement, "role": role, "pid": self.pids.get(role)}
        self.errors.append(row)
        self.record("native_database_error", **row)

    def snapshot(self):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            rows = observer.execute(text(
                "SELECT pid, application_name, state, backend_xid, xact_start, "
                "wait_event_type, wait_event, pg_blocking_pids(pid) AS blockers "
                "FROM pg_stat_activity WHERE application_name LIKE :prefix"
            ), {"prefix": self.instance + "-%"}).mappings().all()
            return [dict(row) for row in rows]

    def await_blocker(self, waiter, holder, *, on_observed=None):
        deadline = monotonic() + 1.5
        while True:
            expired = monotonic() >= deadline
            rows = self.snapshot()
            match = next((row for row in rows if row["pid"] == self.pids.get(waiter)), None)
            if match and self.pids.get(holder) in match["blockers"]:
                observed_at = datetime.now(UTC).isoformat()
                if on_observed is not None:
                    on_observed()
                # Evidence output must not delay the caller's verified release.
                self.record("directed_blocker", waiter=waiter, holder=holder, activity=rows,
                            observed_at=observed_at, release_signaled=self.release.is_set())
                return rows
            if expired:
                self.record("blocker_not_observed", activity=rows)
                raise AssertionError(
                    f"Actual {waiter} -> {holder} PostgreSQL wait was not observed"
                )
            sleep(0.01)

    def retained_locks(self):
        with self.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as observer:
            return [dict(row) for row in observer.execute(text(
                "SELECT pid, locktype, mode, granted FROM pg_locks WHERE pid = ANY(:pids)"
            ), {"pids": sorted(self.all_pids)}).mappings()]

    def worker(self, fixture):
        document_jobs.run_document_processing_job(fixture["job_id"])
        self.record("worker_returned", completed_at=datetime.now(UTC).isoformat())

    def mutate(self, fixture, operation="metadata", *, source=False):
        if self.require_auth_before_writer:
            assert self.auth_body_complete.is_set(), (
                "Bounded writer must start after the independent auth transport completes"
            )
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
        observer_error = None
        if self.passive is not None:
            self.passive.critical_pools += 1
        try:
            yield pool, futures
        except BaseException as error:
            observer_error = error
            raise
        finally:
            self.release.set()
            try:
                try:
                    _, pending = wait(futures, timeout=12)
                finally:
                    try:
                        pool.shutdown(wait=True, cancel_futures=True)
                    finally:
                        if self.passive is not None:
                            self.passive.critical_pools -= 1
                assert len(futures) <= 64, "Contender evidence inventory exceeds its bound"
                self.record(
                    "contenders_completed", pending=len(pending),
                    observer_failed=observer_error is not None,
                    future_outcomes=[_finalizer_future_outcome(future, index)
                                     for index, future in enumerate(futures)],
                )
                assert not pending, "Owned contender did not terminate"
            except BaseException:
                if observer_error is None:
                    raise
                # Cleanup evidence must not replace the original failed oracle.
                try:
                    self.record("contender_cleanup_failed", observer_failed=True)
                except BaseException:
                    pass


def _finalizer_future_outcome(future, index):
    row = {"index": index}
    if future.cancelled():
        return {**row, "status": "cancelled"}
    if not future.done():
        return {**row, "status": "pending"}
    error = future.exception()
    if error is None:
        return {**row, "status": "completed"}
    row.update(status="error", error_kind="exception" if isinstance(error, Exception) else
               "base_exception")
    if isinstance(error, DBAPIError):
        code = getattr(error.orig, "sqlstate", None)
        valid = isinstance(code, str) and len(code) == 5 and all(
            character in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for character in code
        )
        row.update(error_kind="database_error", sqlstate=code if valid else None)
    return row


class _FinalizerJournal:
    RECORD_CAP = 65536
    BYTE_CAP = 64 * 1024 * 1024

    def __init__(self, stream, path, nodeid):
        self.stream, self.path, self.nodeid = stream, path, nodeid
        self.lock = Lock()
        self.digest = sha256()
        self.records = self.bytes = 0
        self.completed = False
        self.record_cap, self.byte_cap = self.RECORD_CAP, self.BYTE_CAP
        self.incomplete_reasons = set()

    def _write(self, kind, data):
        try:
            line = json.dumps({"event": kind, "time": datetime.now(UTC).isoformat(),
                               **data}, default=str) + "\n"
        except BaseException:
            self.incomplete_reasons.add("serialization_error")
            raise
        encoded = line.encode("utf-8")
        if self.records >= self.record_cap:
            self.incomplete_reasons.add("record_cap")
            raise AssertionError("Native evidence record cap exceeded")
        if self.bytes + len(encoded) > self.byte_cap:
            self.incomplete_reasons.add("byte_cap")
            raise AssertionError("Native evidence byte cap exceeded")
        try:
            written = self.stream.write(line)
            if written != len(line):
                raise OSError("Native evidence short write")
            self.stream.flush()
        except BaseException:
            self.incomplete_reasons.add("io_error")
            raise
        self.digest.update(encoded)
        self.records += 1
        self.bytes += len(encoded)

    def record(self, kind, **data):
        with self.lock:
            assert not self.completed, "Native evidence is already completed"
            assert "io_error" not in self.incomplete_reasons, "Native evidence is incomplete"
            if kind == "contender_cleanup_failed":
                self.incomplete_reasons.add(kind)
            self._write(kind, data)

    def complete(self):
        with self.lock:
            assert not self.completed, "Native evidence is already completed"
            try:
                # A failed I/O operation may have partially written unaccounted bytes.
                assert "io_error" not in self.incomplete_reasons, "Native evidence is incomplete"
                complete = not self.incomplete_reasons
                self._write(
                    "native_evidence_complete" if complete else "native_evidence_incomplete",
                    {
                        "nodeid": self.nodeid, "evidence_path": str(self.path),
                        "payload_sha256": self.digest.hexdigest(), "payload_records": self.records,
                        "payload_bytes": self.bytes, "complete": complete,
                        "incomplete_reasons": sorted(self.incomplete_reasons),
                        "record_cap": self.record_cap, "byte_cap": self.byte_cap,
                    },
                )
                assert complete, "Native evidence is incomplete"
            finally:
                self.completed = True


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
    connection = SimpleNamespace(info={"finalizer_role": "worker",
                                       "finalizer_transaction": "receipt-only-transaction"})
    statement = (
        "SELECT company_memberships.id FROM company_memberships "
        "WHERE company_memberships.company_id = %(company_id)s "
        "ORDER BY company_memberships.created_at ASC, company_memberships.id ASC LIMIT %(limit)s"
    )
    private_parameter = secrets.token_urlsafe(32)
    audit.before(connection, None, statement, {"company_id": private_parameter}, None, False)
    assert audit.statements["worker"] == [statement]
    assert receipts == [{"event": "sql_before", "role": "worker", "pid": 123, "sql": statement,
                         "transaction": "receipt-only-transaction"}]
    assert private_parameter not in json.dumps(receipts)
    audit.before(connection, None, "SELECT %(value)s", {"value": private_parameter}, None, False)
    assert audit.statement_counts["worker"] == 2
    assert audit.statements["worker"] == [statement] and len(receipts) == 1


def test_auth_overlap_guard_rejects_starting_a_bounded_writer_before_http_completion():
    receipts = []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    audit.require_auth_before_writer = True
    with pytest.raises(AssertionError, match="independent auth transport completes"):
        audit.mutate({})
    assert receipts == [] and audit.statement_counts == {}


def test_finalizer_sql_duration_receipt_omits_private_parameters():
    receipts = []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    connection = SimpleNamespace(info={"finalizer_role": "mutation",
                                       "finalizer_transaction": "receipt-only-transaction"})
    context = SimpleNamespace()
    statement = "SELECT matters.id FROM matters FOR UPDATE OF matters"
    audit.pids["mutation"] = 123
    parameters = {"private": "must-not-be-retained"}
    audit.before(connection, None, statement, parameters, context, False)
    audit.after(connection, None, statement, parameters, context, False)
    assert [row["event"] for row in receipts] == ["sql_before", "sql_after"]
    assert receipts[-1]["duration"] >= 0
    assert receipts[-1]["transaction"] == "receipt-only-transaction"
    assert "must-not-be-retained" not in json.dumps(receipts)


@pytest.mark.parametrize("legacy_order", [False, True], ids=["release_first", "legacy_negative"])
def test_verified_blocker_release_is_independent_of_observer_receipt_delay(legacy_order):
    receipts = []
    receipt_entered, finish_receipt = Event(), Event()

    def record(kind, **data):
        receipts.append({"event": kind, **data})
        receipt_entered.set()
        assert finish_receipt.wait(8), "Delayed observer was not cleaned up"

    audit = _FinalizerAudit(None, record)
    audit.pids.update(worker=1, mutation=2)
    activity = [{"pid": 1, "blockers": [2]}]
    audit.snapshot = lambda: activity

    def controller():
        if legacy_order:
            observed_activity = audit.await_blocker("worker", "mutation")
            audit.release.set()
            return observed_activity
        else:
            return audit.await_blocker("worker", "mutation", on_observed=audit.release.set)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(controller)
        try:
            assert receipt_entered.wait(1.5), "Verified fake blocker was not observed"
            assert audit.release.is_set() is (not legacy_order)
            assert not future.done(), "Observer delay was not actually in flight"
        finally:
            finish_receipt.set()
            observed_activity = future.result(timeout=8)
    assert audit.release.is_set()
    assert observed_activity is activity
    assert len(receipts) == 1 and receipts[0]["event"] == "directed_blocker"
    assert receipts[0]["activity"] == activity
    assert receipts[0]["waiter"] == "worker" and receipts[0]["holder"] == "mutation"
    assert receipts[0]["release_signaled"] is (not legacy_order)
    assert datetime.fromisoformat(receipts[0]["observed_at"]).tzinfo is not None


def test_blocker_release_callback_never_runs_without_a_verified_native_edge(monkeypatch):
    receipts, callbacks = [], []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    audit.pids.update(worker=1, mutation=2)
    audit.snapshot = lambda: [{"pid": 1, "blockers": [3]}]
    clock = iter((10.0, 10.0, 12.0))
    monkeypatch.setattr(__name__ + ".monotonic", lambda: next(clock))
    monkeypatch.setattr(__name__ + ".sleep", lambda _: None)

    def release():
        callbacks.append("unverified release")
        audit.release.set()

    with pytest.raises(
        AssertionError, match="Actual worker -> mutation PostgreSQL wait was not observed",
    ):
        audit.await_blocker("worker", "mutation", on_observed=release)
    assert callbacks == [] and not audit.release.is_set()
    assert [row["event"] for row in receipts] == ["blocker_not_observed"]


def test_passive_select_timing_keeps_only_hash_actor_clocks_and_outcome():
    receipts = []
    audit = _FinalizerAudit(None, lambda kind, **data: receipts.append({"event": kind, **data}))
    audit.passive = _PassiveOverlapTiming(sql_cap=4)
    connection = SimpleNamespace(info={"finalizer_role": "mutation"})
    context = SimpleNamespace()
    sql = "SELECT %(secret)s AS private_source_body"
    with audit.passive.capture():
        audit.before(connection, None, sql, {"secret": "raw-auth-token"}, context, False)
        assert receipts == [], "No passive receipt writes in the DBAPI critical interval"
        audit.after(connection, None, sql, {}, context, False)
        audit.passive.begin_select("private-actor-name", "WITH t AS (SELECT 1) SELECT * FROM t",
                                   context)
        audit.passive.end_select(context, error=True)
        audit.passive.begin_select("worker", "UPDATE fake SET x=1", context)
        assert receipts == []
    audit.passive.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    rows = [row for row in receipts if row["event"] == "passive_select_timing"]
    assert len(rows) == 2
    assert rows[0]["template_sha256"] == sha256(sql.encode()).hexdigest()
    assert [(row["actor"], row["outcome"]) for row in rows] == [
        ("mutation", "ok"), ("unlabelled", "error"),
    ]
    assert all(row["duration_ns"] >= 0 and row["utc_started_ns"] > 0
               and row["utc_finished_ns"] >= row["utc_started_ns"] for row in rows)
    assert set(rows[0]) == {"event", "actor", "template_sha256", "utc_started_ns",
                            "utc_finished_ns", "mono_started_ns", "mono_finished_ns",
                            "duration_ns", "outcome"}
    assert not any(value in json.dumps(receipts) for value in
                   (sql, "raw-auth-token", "private-actor-name", "private_source_body"))


@pytest.mark.parametrize("defect", ["sql-overflow", "oversize", "missing-context", "unfinished"])
def test_passive_select_timing_bounds_fail_closed_without_raw_streams(defect):
    receipts = []
    timing = _PassiveOverlapTiming(sql_cap=1)
    context = SimpleNamespace()
    with timing.capture():
        timing.begin_select("worker", "SELECT 1", context)
        if defect != "unfinished":
            timing.end_select(context)
        if defect == "sql-overflow":
            timing.begin_select("worker", "SELECT private_second", context)
        elif defect == "oversize":
            timing.begin_select("worker", "SELECT " + "x" * timing.TEMPLATE_CAP, context)
        elif defect == "missing-context":
            timing.begin_select("worker", "SELECT private_third", None)
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    summary = receipts[0]
    assert not summary["complete"] and summary["select_count"] == 1
    assert len(timing.sql_slots) == 1 and len(timing.available_sql) == 0
    assert "private_second" not in json.dumps(receipts)
    assert "private_third" not in json.dumps(receipts)
    assert timing.callback not in gc.callbacks


@pytest.mark.parametrize("body_error", [False, True])
def test_passive_gc_native_clocks_cleanup_and_deferred_flush(body_error):
    timing = _PassiveOverlapTiming()
    original_callbacks = list(gc.callbacks)
    receipts = []
    try:
        with timing.capture():
            assert gc.callbacks == original_callbacks + [timing.callback]
            gc.collect(0)
            assert receipts == []
            timing.critical_pools = 1
            with pytest.raises(AssertionError, match="Passive capture is active"):
                timing.flush(
                    lambda *_args, **_kwargs: pytest.fail("Must not flush during collection"),
                )
            timing.critical_pools = 0
            if body_error:
                raise ValueError("safe fake body failure")
    except ValueError as error:
        assert body_error and str(error) == "safe fake body failure"
    assert gc.callbacks == original_callbacks
    assert not timing.enabled
    timing.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    rows = [row for row in receipts if row["event"] == "passive_gc_timing"]
    assert rows and any(row["generation"] == 0 for row in rows)
    assert all(row["duration_ns"] >= 0 and row["utc_started_ns"] > 0
               and row["utc_finished_ns"] >= row["utc_started_ns"] for row in rows)
    assert receipts[0]["complete"] and receipts[0]["flushed_after_workers"]


def test_passive_gc_retains_large_fixture_window_without_changing_gc_policy():
    timing = _PassiveOverlapTiming()
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    receipts = []
    # Exact native-clock callback, with deterministic metadata rather than a GC replay.
    # Do not register it: ambient collection must not alter this known phase inventory.
    timing.enabled = True
    try:
        for _ in range(300):
            timing.callback("start", {"generation": 0})
            timing.callback("stop", {"generation": 0})
        assert receipts == []
    finally:
        timing.enabled = False
    timing.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    summary = receipts[0]
    assert summary["complete"] and not summary["gc_overflow"]
    assert summary["gc_count"] == 300
    rows = [row for row in receipts if row["event"] == "passive_gc_timing"]
    assert len(rows) == 300
    assert all(row["duration_ns"] >= 0 and row["utc_started_ns"] > 0 for row in rows)
    assert all(left["mono_finished_ns"] <= right["mono_started_ns"]
               for left, right in zip(rows, rows[1:], strict=False))
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy


def test_passive_gc_default_capacity_still_fails_closed_at_its_finite_bound():
    timing = _PassiveOverlapTiming()
    cap = len(timing.gc_slots)
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    receipts = []
    timing.enabled = True
    try:
        for _ in range(cap // 2 + 1):
            timing.callback("start", {"generation": 0})
            timing.callback("stop", {"generation": 0})
        assert receipts == []
    finally:
        timing.enabled = False
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    summary = receipts[0]
    assert not summary["complete"] and summary["gc_overflow"]
    assert not summary["unpaired_gc"] and not summary["invalid"]
    assert summary["gc_phase_cap"] == cap == timing.GC_CAP
    assert summary["gc_count"] == cap // 2
    assert len(receipts) == cap // 2 + 1 and timing.next_gc is None
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy


@pytest.mark.parametrize("defect", ["overflow", "unpaired", "clock-error"])
def test_passive_gc_bounds_and_callback_failure_are_incomplete(defect):
    timing = _PassiveOverlapTiming(gc_cap=1)
    receipts = []
    original_callbacks = list(gc.callbacks)
    # Invoke the exact registered callback with reviewed fake metadata, not a GC replay.
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        with timing.capture():
            if defect == "clock-error":
                def failed_clock(_pointer):
                    raise RuntimeError("safe fake clock failure")

                timing.mono_clock = failed_clock
            timing.callback("start", {"generation": 0})
            if defect == "overflow":
                timing.callback("stop", {"generation": 0})
            assert receipts == []
    finally:
        if was_enabled:
            gc.enable()
    assert gc.callbacks == original_callbacks
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: receipts.append({"event": kind, **data}))
    assert not receipts[0]["complete"] and receipts[0]["unpaired_gc"]
    assert receipts[0]["gc_overflow"] is (defect == "overflow")
    assert receipts[0]["invalid"] is (defect == "clock-error")
    assert "safe fake clock failure" not in json.dumps(receipts)


def test_passive_gc_callback_has_no_record_allocation_io_or_lock_calls():
    callback = _PassiveOverlapTiming._gc_callback
    instructions = list(dis.get_instructions(callback))
    assert not any(item.opname.startswith("BUILD_") or item.opname == "BINARY_OP"
                   for item in instructions)
    assert set(callback.__code__.co_names) == {
        "enabled", "next_gc", "gc_overflow", "next", "phase", "generation",
        "mono_clock", "mono_pointer", "utc_clock", "utc_pointer", "Exception", "invalid",
    }
    assert callback.__globals__.get("Exception", builtins.Exception) is builtins.Exception


def test_passive_flush_rejects_owned_worker_window_even_after_gc_is_removed():
    timing = _PassiveOverlapTiming()
    timing.critical_pools = 1
    with pytest.raises(AssertionError, match="cannot flush during owned worker timing"):
        timing.flush(
            lambda *_args, **_kwargs: pytest.fail("Must not flush before owned workers finish"),
        )
    assert timing.callback not in gc.callbacks


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
    with evidence_path.open("x", encoding="utf-8", newline="\n") as stream:
        journal = _FinalizerJournal(stream, evidence_path, request.node.nodeid)
        record = journal.record

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
               node_source_sha256=sha256(Path(request.node.path).read_bytes()).hexdigest(),
               court_sync_jobs_sha256=sha256(Path(court_sync_jobs.__file__).read_bytes()).hexdigest(),
               evidence_path=str(evidence_path),
               limitation="Local overlap, not Cloud Run CPU attribution")
        audit.passive = _PassiveOverlapTiming()
        audit.passive.start()
        try:
            yield audit
        finally:
            audit.release.set()
            audit.passive.stop()
            for name, callback in audit.hooks:
                event.remove(engine, name, callback)
            try:
                remaining = audit.snapshot()
                locks = audit.retained_locks()
                record("cleanup", activity=remaining, locks=locks,
                       all_backend_ids=sorted(audit.all_pids), errors=audit.errors)
            finally:
                engine.dispose()
                try:
                    audit.flush_passive_evidence()
                finally:
                    journal.complete()
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
    audit.auth_body_complete.set()
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
        # Both contenders overlap the same held finalizer. Auth's five-second
        # transport allowance must not consume the writer's two-second SQL wait.
        audit.require_auth_before_writer = True
        writer = pool.submit(audit.mutate, fixture, mutation)
        futures.append(writer)
        def release_held_finalizer():
            assert not writer.done()
            audit.release.set()

        observed_activity = audit.await_blocker(
            "mutation", "worker", on_observed=release_held_finalizer,
        )
        audit.record("release_finalizer_after_response", activity=observed_activity)
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
