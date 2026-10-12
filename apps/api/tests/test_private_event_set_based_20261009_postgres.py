"""Projection invalidation strips private bytes without loading them into Python."""

import gc
import json
import marshal
import os
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import get_ident
from time import monotonic, monotonic_ns
from uuid import uuid4

import pytest
from sqlalchemy import event, func, insert, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    AssistantSession,
    AssistantTurn,
    PrivateIndexGeneration,
    PrivateIndexProjection,
    PrivateIndexProjectionScope,
    PrivateSavedOutputAccess,
)
from caseops_api.services.private_retrieval import (
    create_shadow_private_generation,
    ensure_active_private_generation,
    propagate_private_projection_change,
)
from tests.test_postgres_validation import (
    _ensure_migrations,  # noqa: F401
    _seed_company,
    _seed_matter,
    _seed_membership,
)

pytestmark = pytest.mark.postgres

_TIMING_DETAIL_LIMIT = 2048
_SQL_TIMING_ATTRIBUTE = "_caseops_private_event_passive_sql"


class _PassiveEventTiming:
    """Observe cursor/GC intervals without queries, parameters, holds or forced GC."""

    def __init__(self, nodeid, directory):
        self.nodeid = nodeid
        self.directory = directory
        self.run_id = uuid4().hex
        self.test_thread = get_ident()
        self.phase = "observer_setup"
        self.epoch_ns = monotonic_ns()
        self.started_at = datetime.now(UTC).isoformat()
        self.sql = []
        self.collections = []
        self.gc_started = {}
        self.sql_count = self.sql_duration_ns = self.sql_errors = 0
        self.gc_count = self.gc_duration_ns = 0
        self.sql_overflow = self.gc_overflow = self.unmatched_gc_stops = 0
        self.critical_start_ns = self.critical_end_ns = None
        self.critical_seconds = self.commit_start_ns = self.commit_end_ns = None
        self.critical_completed = self.critical_bound_passed = False
        self.commit_completed = False
        self.critical_session_closed = False
        self.sql_assertions_passed = self.body_completed = False
        self.source_identity = self._source_identity()

    @staticmethod
    def _source_identity():
        function = propagate_private_projection_change
        source = Path(function.__code__.co_filename)
        return {
            "test_file_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "function_module": function.__module__,
            "function_name": function.__qualname__,
            "function_file_sha256": sha256(source.read_bytes()).hexdigest(),
            "loaded_function_code_sha256": sha256(marshal.dumps(function.__code__)).hexdigest(),
        }

    def begin_critical(self, started):
        self.critical_start_ns = round(started * 1_000_000_000)
        self.phase = "critical.propagation"

    def end_critical(self, seconds, *, completed):
        self.critical_seconds = seconds
        self.critical_end_ns = self.critical_start_ns + round(seconds * 1_000_000_000)
        self.critical_completed = completed
        self.phase = "after_critical"

    def before(self, _connection, _cursor, _sql, _parameters, context, _many):
        setattr(context, _SQL_TIMING_ATTRIBUTE, (monotonic_ns(), self.phase, bool(_many)))

    def after(self, _connection, _cursor, sql, _parameters, context, many):
        self._finish_sql(context, sql, many)

    def error(self, error_context):
        context = error_context.execution_context
        if context is not None:
            code = getattr(error_context.original_exception, "sqlstate", None)
            self._finish_sql(context, error_context.statement, False, failed=True, sqlstate=code)

    def _finish_sql(self, context, sql, _many, *, failed=False, sqlstate=None):
        ended = monotonic_ns()
        started = getattr(context, _SQL_TIMING_ATTRIBUTE, None)
        if started is None:
            return
        delattr(context, _SQL_TIMING_ATTRIBUTE)
        duration = ended - started[0]
        self.sql_count += 1
        self.sql_duration_ns += duration
        self.sql_errors += int(failed)
        if len(self.sql) < _TIMING_DETAIL_LIMIT:
            self.sql.append({
                "started_ns": started[0] - self.epoch_ns,
                "ended_ns": ended - self.epoch_ns,
                "duration_ns": duration,
                "current_task_phase": started[1],
                "on_test_thread": get_ident() == self.test_thread,
                "template_sha256": sha256(sql.encode("utf-8")).hexdigest() if sql else None,
                "executemany": started[2], "failed": failed,
                "sqlstate": sqlstate if isinstance(sqlstate, str) and len(sqlstate) == 5 else None,
            })
        else:
            self.sql_overflow += 1

    def collect(self, action, info):
        now = monotonic_ns()
        generation = info["generation"]
        key = (get_ident(), generation)
        if action == "start":
            self.gc_started[key] = (now, self.phase)
        elif action == "stop":
            started = self.gc_started.pop(key, None)
            if started is None:
                self.unmatched_gc_stops += 1
                return
            duration = now - started[0]
            self.gc_count += 1
            self.gc_duration_ns += duration
            if len(self.collections) < _TIMING_DETAIL_LIMIT:
                self.collections.append({
                    "started_ns": started[0] - self.epoch_ns,
                    "ended_ns": now - self.epoch_ns, "duration_ns": duration,
                    "current_task_phase": started[1], "end_task_phase": self.phase,
                    "on_test_thread": get_ident() == self.test_thread,
                    "generation": generation, "collected": info["collected"],
                    "uncollectable": info["uncollectable"],
                })
            else:
                self.gc_overflow += 1

    def write_snapshot(self, stage):
        receipt = {
            "event": "private_event_passive_timing", "stage": stage,
            "nodeid": self.nodeid, "run_id": self.run_id,
            "started_at_utc": self.started_at, "source_identity": self.source_identity,
            "epoch_monotonic_ns": self.epoch_ns,
            "critical": {
                "started_ns": (self.critical_start_ns - self.epoch_ns
                               if self.critical_start_ns is not None else None),
                "ended_ns": (self.critical_end_ns - self.epoch_ns
                             if self.critical_end_ns is not None else None),
                "seconds": self.critical_seconds, "interval_completed": self.critical_completed,
                "bound_seconds": 5, "bound_passed": self.critical_bound_passed,
                "session_closed_before_receipt": self.critical_session_closed,
                "commit_started_ns": (self.commit_start_ns - self.epoch_ns
                                      if self.commit_start_ns is not None else None),
                "commit_ended_ns": (self.commit_end_ns - self.epoch_ns
                                    if self.commit_end_ns is not None else None),
                "commit_completed": self.commit_completed,
            },
            "sql": tuple(self.sql), "gc": tuple(self.collections),
            "summary": {
                "sql_count": self.sql_count, "sql_duration_ns": self.sql_duration_ns,
                "sql_errors": self.sql_errors, "sql_detail_overflow": self.sql_overflow,
                "gc_count": self.gc_count, "gc_duration_ns": self.gc_duration_ns,
                "gc_detail_overflow": self.gc_overflow,
                "gc_unmatched_stops": self.unmatched_gc_stops,
                "gc_unfinished_intervals": len(self.gc_started),
            },
            "statement_assertions_completed": self.sql_assertions_passed,
            "test_body_reached_end": self.body_completed,
            "observer_detached_final_snapshot": stage == "test_function_finished",
            "scope": "Cursor execute and process GC observations; not server waits or CPU cause",
        }
        identity = sha256(self.nodeid.encode("utf-8")).hexdigest()[:20]
        path = self.directory / f"{identity}-{uuid4().hex}.jsonl"
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, separators=(",", ":")) + "\n")
        return path


@pytest.fixture
def _private_event_timing(pg_engine, request, tmp_path, record_testsuite_property):
    directory = Path(os.environ.get("CASEOPS_FINALIZER_EVIDENCE_DIR", str(tmp_path)))
    directory.mkdir(parents=True, exist_ok=True)
    timing = _PassiveEventTiming(request.node.nodeid, directory)
    listeners = (
        ("before_cursor_execute", timing.before),
        ("after_cursor_execute", timing.after),
        ("handle_error", timing.error),
    )
    attached = []
    gc_attached = False
    try:
        for name, callback in listeners:
            event.listen(pg_engine, name, callback)
            attached.append((name, callback))
        gc.callbacks.append(timing.collect)
        gc_attached = True
        yield timing
    finally:
        for name, callback in reversed(attached):
            event.remove(pg_engine, name, callback)
        if gc_attached:
            gc.callbacks.remove(timing.collect)
        path = timing.write_snapshot("test_function_finished")
        record_testsuite_property("private_event_passive_timing_path", str(path))


def _projection(company_id, generation_id, source_id, ordinal=0, source_type="matter"):
    content = "Private bytes must not be hydrated by a lifecycle write. " * 100
    now = datetime.now(UTC)
    return {
        "id": str(uuid4()),
        "company_id": company_id,
        "generation_id": generation_id,
        "source_type": source_type,
        "source_id": source_id,
        "source_version": "1",
        "chunk_ordinal": ordinal,
        "label": "Bounded invalidation regression",
        "content_text": content,
        "content_sha256": sha256(content.encode()).hexdigest(),
        "access_policy_generation": 1,
        "tombstone_generation": 0,
        "embedding_dimensions": 3,
        "embedding_json": "[1.0, 0.0, 0.0]",
        "is_tombstoned": False,
        "created_at": now,
        "updated_at": now,
    }


def test_large_event_uses_one_set_update_without_private_byte_hydration(
    pg_engine, record_testsuite_property, _private_event_timing,
):
    timing = _private_event_timing
    timing.phase = "seed"
    with Session(pg_engine) as seed:
        company_id = _seed_company(seed)
        actor_id = _seed_membership(seed, company_id, role="admin")
        matter_id = _seed_matter(seed, company_id)
        untouched_id = _seed_matter(seed, company_id)
        generation = ensure_active_private_generation(seed, company_id=company_id)
        shadow = create_shadow_private_generation(seed, company_id=company_id)
        retired = PrivateIndexGeneration(
            company_id=company_id,
            generation_number=3,
            state="retired",
        )
        seed.add(retired)
        seed.flush()
        other_company = _seed_company(seed)
        other_generation = ensure_active_private_generation(seed, company_id=other_company)
        rows = [_projection(company_id, generation.id, matter_id, n) for n in range(10_000)]
        child = _projection(company_id, generation.id, str(uuid4()), source_type="matter_document")
        rows.append(child)
        untouched = [
            _projection(company_id, generation.id, untouched_id),
            _projection(company_id, shadow.id, matter_id),
            _projection(company_id, retired.id, matter_id),
            _projection(other_company, other_generation.id, matter_id),
        ]
        seed.execute(insert(PrivateIndexProjection), rows + untouched)
        seed.add(
            PrivateIndexProjectionScope(
                company_id=company_id,
                projection_id=child["id"],
                scope_type="matter",
                scope_id=matter_id,
                matter_id=matter_id,
            )
        )
        assistant = AssistantSession(
            company_id=company_id, created_by_membership_id=actor_id,
            title="Retained output history", policy_version=1,
            retention_expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        seed.add(assistant)
        seed.flush()
        turns = [
            {"id": str(uuid4()), "company_id": company_id, "session_id": assistant.id,
             "sequence": n + 1, "role": "assistant", "status": "completed",
             "created_by_membership_id": actor_id}
            for n in range(10_002)
        ]
        seed.execute(insert(AssistantTurn), turns)
        outputs = [
            {"id": str(uuid4()), "company_id": company_id, "assistant_turn_id": turn["id"],
             "generation_id": generation.id if n % 2 == 0 else retired.id,
             "source_type": "matter", "source_id": matter_id, "source_version": "1",
             "access_policy_generation": 1, "tombstone_generation": 0, "state": "accessible"}
            for n, turn in enumerate(turns[:10_000])
        ]
        untouched_output = {**outputs[0], "id": str(uuid4()),
                            "assistant_turn_id": turns[-2]["id"], "source_id": untouched_id}
        prior_locked_at = datetime.now(UTC)
        prior_locked_output = {**outputs[1], "id": str(uuid4()),
                               "assistant_turn_id": turns[-1]["id"], "state": "locked",
                               "locked_at": prior_locked_at, "locked_reason": "prior_closure"}
        seed.execute(insert(PrivateSavedOutputAccess), outputs)
        seed.execute(insert(PrivateSavedOutputAccess), [untouched_output])
        seed.execute(insert(PrivateSavedOutputAccess), [prior_locked_output])
        seed.commit()
        generation_id, shadow_id = generation.id, shadow.id
        initial_shadow_epoch = shadow.tombstone_generation

    statements = []

    def capture(_connection, _cursor, sql, _parameters, _context, many):
        statements.append((sql, many))

    with Session(pg_engine) as session:
        # Prove identity-map synchronization as well as fresh-session persistence.
        timing.phase = "cache_prime"
        cached = session.get(PrivateIndexProjection, rows[0]["id"])
        event.listen(pg_engine, "before_cursor_execute", capture)
        try:
            started = monotonic()
            timing.begin_critical(started)
            result = propagate_private_projection_change(
                session,
                company_id=company_id,
                actor_membership_id=actor_id,
                idempotency_key="set-based-large-event",
                event_type="revoked",
                target_type="matter",
                target_id=matter_id,
                target_version="1",
                reason_code="source_revoked",
            )
            timing.phase = "critical.result_assertions"
            assert result.affected_projection_count == 10_001
            assert result.affected_saved_output_count == 10_000
            assert result.status == "applied"
            assert cached.is_tombstoned and cached.content_text == ""
            assert cached.embedding_json is None
            timing.phase = "critical.commit"
            timing.commit_start_ns = monotonic_ns()
            session.commit()
            timing.commit_end_ns = monotonic_ns()
            timing.commit_completed = True
            critical_seconds = monotonic() - started
            timing.end_critical(critical_seconds, completed=True)
            record_testsuite_property("private_event_commit_seconds", critical_seconds)
            record_testsuite_property("retained_saved_output_count", len(outputs))
            assert critical_seconds < 5, "Positive invalidation must finish inside the lock budget."
            timing.critical_bound_passed = True
            result_id = result.id
        finally:
            if timing.commit_start_ns is not None and timing.commit_end_ns is None:
                timing.commit_end_ns = monotonic_ns()
            if timing.critical_start_ns is not None and timing.critical_end_ns is None:
                timing.end_critical(monotonic() - started, completed=False)
            event.remove(pg_engine, "before_cursor_execute", capture)
            timing.phase = "critical_cleanup"
            try:
                session.close()
                timing.critical_session_closed = True
            finally:
                timing.phase = "after_critical_receipt"
                path = timing.write_snapshot("critical_session_cleanup_finished")
                record_testsuite_property("private_event_critical_timing_path", str(path))

    timing.phase = "statement_assertions"
    projection_updates = [
        sql for sql, many in statements if sql.startswith("UPDATE private_index_projections")
    ]
    wide_reads = [
        sql
        for sql, many in statements
        if sql.startswith("SELECT") and "private_index_projections.content_text" in sql
    ]
    assert not wide_reads, "Invalidation must not load retained content or embeddings."
    assert len(projection_updates) == 1
    assert not any(
        many for sql, many in statements if sql.startswith("UPDATE private_index_projections")
    )
    assert len(statements) <= 18, "SQL work must not scale with projection count."

    timing.sql_assertions_passed = True
    timing.phase = "verification"
    with Session(pg_engine) as check:
        invalidated = check.scalar(
            select(func.count())
            .select_from(PrivateIndexProjection)
            .where(
                PrivateIndexProjection.company_id == company_id,
                PrivateIndexProjection.generation_id == generation_id,
                PrivateIndexProjection.is_tombstoned.is_(True),
                PrivateIndexProjection.content_text == "",
                PrivateIndexProjection.embedding_json.is_(None),
            )
        )
        assert invalidated == 10_001
        assert check.scalar(
            select(func.count()).select_from(PrivateSavedOutputAccess).where(
                PrivateSavedOutputAccess.company_id == company_id,
                PrivateSavedOutputAccess.state == "locked",
                PrivateSavedOutputAccess.locked_reason == "source_revoked",
            )
        ) == 10_000
        assert check.get(PrivateSavedOutputAccess, untouched_output["id"]).state == "accessible"
        retained_lock = check.get(PrivateSavedOutputAccess, prior_locked_output["id"])
        assert retained_lock.locked_reason == "prior_closure"
        assert retained_lock.locked_at == prior_locked_at
        assert all(
            not check.get(PrivateIndexProjection, row["id"]).is_tombstoned for row in untouched
        )
        assert (
            check.get(PrivateIndexGeneration, shadow_id).tombstone_generation > initial_shadow_epoch
        )
        timing.phase = "replay"
        replay = propagate_private_projection_change(
            check,
            company_id=company_id,
            actor_membership_id=actor_id,
            idempotency_key="set-based-large-event",
            event_type="revoked",
            target_type="matter",
            target_id=matter_id,
            target_version="1",
            reason_code="source_revoked",
        )
        assert replay.id == result_id
        assert replay.affected_projection_count == 10_001
        assert replay.affected_saved_output_count == 10_000
    timing.body_completed = True
    timing.phase = "test_body_finished"
