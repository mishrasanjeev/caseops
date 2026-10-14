"""Pure controls for native journal retention and sanitized contender evidence."""

import ctypes
import gc
import io
import json
import sys
from concurrent.futures import Future
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy.exc import DBAPIError

from tests import test_document_finalizer_overlap_20261009_postgres as native


class _PrivateValue:
    def __repr__(self):
        raise AssertionError("Future payload must not be inspected")

    def __str__(self):
        raise AssertionError("Future payload must not be inspected")


class _PrivateError(Exception):
    def __str__(self):
        raise AssertionError("Exception message must not be inspected")


class _ObserverInterruption(BaseException):
    """Nonstandard control-flow fault; direct observer calls must propagate it."""


_INTERRUPTIONS = (KeyboardInterrupt, SystemExit, GeneratorExit, _ObserverInterruption)


@pytest.mark.parametrize("error_type", (RuntimeError, *_INTERRUPTIONS))
@pytest.mark.parametrize("stage", ("next_slot", "phase", "generation", "mono", "utc"))
def test_gc_callback_recording_failure_is_invalid_before_exit_and_preserves_interrupts(
    monkeypatch, error_type, stage,
):
    timing = native._PassiveOverlapTiming(gc_cap=2)
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    failure = error_type("FAKE_OBSERVER_FAILURE")
    first = timing.next_gc
    info = {"generation": 0}
    latches = []

    def fail(_value):
        latches.append(timing.invalid)
        with pytest.raises(AssertionError, match="Passive capture is active"):
            timing.flush(lambda *_args, **_kwargs: pytest.fail("Must not flush incomplete capture"))
        raise failure

    class FaultySlot:
        @property
        def next(self):
            if stage == "next_slot":
                fail(None)
            return first.next

        @property
        def phase(self):
            return first.phase

        @phase.setter
        def phase(self, value):
            fail(value)

    class FaultyInfo:
        def __getitem__(self, key):
            assert key == "generation"
            fail(key)

    if stage in {"next_slot", "phase"}:
        timing.next_gc = FaultySlot()
    elif stage == "generation":
        info = FaultyInfo()
    else:
        monkeypatch.setattr(timing, f"{stage}_clock", fail)
    gc.disable()
    try:
        if issubclass(error_type, Exception):
            with timing.capture():
                timing.callback("start", info)
        else:
            with pytest.raises(error_type) as caught:
                with timing.capture():
                    timing.callback("start", info)
            assert caught.value is failure
        assert latches == [False]
        assert timing.invalid is True
    finally:
        if policy[0]:
            gc.enable()
    assert not timing.enabled and timing.callback not in gc.callbacks
    records = []
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: records.append({"event": kind, **data}))
    assert records[0]["invalid"] and not records[0]["complete"]
    assert "FAKE_OBSERVER_FAILURE" not in json.dumps(records)
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy


@pytest.mark.parametrize("prior_invalid", (False, True))
def test_gc_callback_success_preserves_exact_native_clock_bytes_and_sticky_invalid(prior_invalid):
    timing = native._PassiveOverlapTiming(gc_cap=2)
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    expected = []
    calls = []
    latches = []
    # Prepare all payload bytes before invoking the allocation-bounded callback.
    for index, slot in enumerate(timing.gc_slots):
        mono = type(slot.mono)()
        utc = type(slot.utc)()
        if sys.platform == "win32":
            mono.value = (7 + index) * timing.frequency
            utc.value = 116444736000000000 + (1750000000 + index) * 10000000
        else:
            mono.seconds, mono.nanoseconds = 7 + index, 123
            utc.seconds, utc.nanoseconds = 1750000000 + index, 456
        expected.append((bytes(mono), bytes(utc)))

    def mono_clock(pointer):
        latches.append(timing.invalid)
        calls.append("mono")
        payload = expected[len(calls) // 2][0]
        ctypes.memmove(pointer, payload, len(payload))

    def utc_clock(pointer):
        latches.append(timing.invalid)
        payload = expected[len(calls) // 2][1]
        calls.append("utc")
        ctypes.memmove(pointer, payload, len(payload))

    timing.mono_clock, timing.utc_clock = mono_clock, utc_clock
    timing.invalid = prior_invalid
    timing.enabled = True
    try:
        timing.callback("start", {"generation": 0})
        assert timing.invalid is prior_invalid
        timing.callback("stop", {"generation": 0})
        assert timing.invalid is prior_invalid
    finally:
        timing.enabled = False
    assert calls == ["mono", "utc", "mono", "utc"]
    assert latches == [prior_invalid, prior_invalid, prior_invalid, prior_invalid]
    assert [(bytes(slot.mono), bytes(slot.utc)) for slot in timing.gc_slots] == expected
    assert [slot.phase for slot in timing.gc_slots] == ["start", "stop"]
    assert all(slot.generation == 0 for slot in timing.gc_slots) and timing.next_gc is None
    records = []
    if prior_invalid:
        with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
            timing.flush(lambda kind, **data: records.append({"event": kind, **data}))
    else:
        timing.flush(lambda kind, **data: records.append({"event": kind, **data}))
    assert records[0]["complete"] is (not prior_invalid)
    assert records[0]["invalid"] is prior_invalid
    assert records[1]["duration_ns"] == 1000000000
    assert records[1]["utc_finished_ns"] - records[1]["utc_started_ns"] == 1000000000
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy


@pytest.mark.parametrize("error_type", _INTERRUPTIONS)
def test_gc_callback_interrupt_is_ignored_by_cpython_but_latched_and_removed(
    monkeypatch, error_type,
):
    timing = native._PassiveOverlapTiming(gc_cap=2)
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    hook = sys.unraisablehook
    observed = []
    failure = error_type("FAKE_GC_INTERRUPTION")

    def fail_clock(_pointer):
        raise failure

    def retain_unraisable(args):
        if args.object is timing.callback:
            observed.append((args.exc_type, args.exc_value))
        else:
            hook(args)

    timing.mono_clock = fail_clock
    gc.disable()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(sys, "unraisablehook", retain_unraisable)
            with timing.capture():
                assert gc.callbacks == callbacks + [timing.callback]
                gc.collect(0)
                assert timing.invalid is True
    finally:
        if policy[0]:
            gc.enable()
    assert observed == [(error_type, failure), (error_type, failure)]
    assert sys.unraisablehook is hook
    assert not timing.enabled and timing.callback not in gc.callbacks
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy
    records = []
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: records.append({"event": kind, **data}))
    assert records[0]["invalid"] and not records[0]["complete"]
    assert "FAKE_GC_INTERRUPTION" not in json.dumps(records)


def test_gc_success_does_not_clear_independent_sql_invalid_mark_at_clock_boundary(monkeypatch):
    timing = native._PassiveOverlapTiming(gc_cap=2)
    callbacks = list(gc.callbacks)
    policy = (gc.isenabled(), gc.get_threshold())
    clock = timing.utc_clock

    def clock_with_invalid_sql_context(pointer):
        clock(pointer)
        # Deterministic interleaving of the existing SQL-recorder failure path.
        timing.begin_select("worker", "SELECT 1", None)

    monkeypatch.setattr(timing, "utc_clock", clock_with_invalid_sql_context)
    timing.enabled = True
    try:
        timing.callback("start", {"generation": 0})
        timing.callback("stop", {"generation": 0})
    finally:
        timing.enabled = False
    assert timing.invalid is True
    records = []
    with pytest.raises(AssertionError, match="Passive timing evidence is incomplete"):
        timing.flush(lambda kind, **data: records.append({"event": kind, **data}))
    assert records[0]["invalid"] and not records[0]["complete"]
    assert gc.callbacks == callbacks and (gc.isenabled(), gc.get_threshold()) == policy


@pytest.mark.parametrize("state", ["completed", "error", "cancelled", "pending"])
def test_future_outcomes_do_not_inspect_private_values_or_messages(state):
    future = Future()
    if state == "completed":
        future.set_result(_PrivateValue())
    elif state == "error":
        future.set_exception(_PrivateError("FAKE_TOKEN FAKE_SQL_PARAMETER"))
    elif state == "cancelled":
        future.cancel()
    outcome = native._finalizer_future_outcome(future, 2)
    assert outcome["index"] == 2 and outcome["status"] == state
    assert set(outcome) <= {"index", "status", "error_kind", "sqlstate"}
    assert "FAKE_" not in json.dumps(outcome)


@pytest.mark.parametrize("sqlstate,expected", [
    ("55P03", "55P03"), ("23505", "23505"), (None, None),
    ("secret", None), ("55P03 FAKE_TOKEN", None), (True, None),
])
def test_database_future_metadata_never_retains_sql_parameters_or_credentials(sqlstate, expected):
    future = Future()
    original = SimpleNamespace(sqlstate=sqlstate)
    future.set_exception(DBAPIError("FAKE_PRIVATE_SQL", {"password": "FAKE_PASSWORD"}, original))
    outcome = native._finalizer_future_outcome(future, 0)
    assert outcome == {
        "index": 0, "status": "error", "error_kind": "database_error", "sqlstate": expected,
    }
    assert "FAKE_" not in json.dumps(outcome)


def test_pool_failure_retains_original_exception_and_sanitized_future_outcomes():
    records = []
    audit = native._FinalizerAudit(
        None, lambda kind, **data: records.append({"event": kind, **data}),
    )
    audit.passive = SimpleNamespace(critical_pools=0)
    original = AssertionError("FAKE_OBSERVER_PRIVATE_MESSAGE")

    def contender():
        assert audit.release.wait(8)
        raise _PrivateError("FAKE_PROVIDER_CREDENTIAL")

    observed_error = None
    try:
        with audit.pool() as (pool, futures):
            futures.append(pool.submit(contender))
            raise original
    except AssertionError as error:
        observed_error = error
    assert observed_error is original
    assert audit.release.is_set() and audit.passive.critical_pools == 0
    completed = next(row for row in records if row["event"] == "contenders_completed")
    assert completed["observer_failed"] is True and completed["pending"] == 0
    assert completed["future_outcomes"] == [
        {"index": 0, "status": "error", "error_kind": "exception"},
    ]
    assert "FAKE_" not in json.dumps(records)


def test_pool_success_does_not_serialize_completed_results():
    records = []
    audit = native._FinalizerAudit(
        None, lambda kind, **data: records.append({"event": kind, **data}),
    )
    with audit.pool() as (pool, futures):
        futures.append(pool.submit(_PrivateValue))
    assert records[-1]["future_outcomes"] == [{"index": 0, "status": "completed"}]
    assert records[-1]["observer_failed"] is False


@pytest.mark.parametrize("body_failure", [False, True])
def test_pool_cleanup_record_failure_cannot_replace_original_observer_error(body_failure):
    def broken_record(*_args, **_kwargs):
        raise RuntimeError("FAKE_RECEIPT_FAILURE")

    audit = native._FinalizerAudit(None, broken_record)
    original = AssertionError("FAKE_ORIGINAL_OBSERVER_FAILURE")
    expected = AssertionError if body_failure else RuntimeError
    observed_error = None
    try:
        with audit.pool():
            if body_failure:
                raise original
    except expected as error:
        observed_error = error
    else:
        pytest.fail("The observer or cleanup failure must propagate")
    if body_failure:
        assert observed_error is original
    assert audit.release.is_set()


@pytest.mark.parametrize("body_failure", [False, True])
def test_pool_keeps_full_wait_and_shutdown_deadlines_and_reports_pending(monkeypatch, body_failure):
    operations = []
    records = []
    future = Future()

    class Pool:
        def __init__(self, *, max_workers):
            assert max_workers == 3

        def shutdown(self, *, wait, cancel_futures):
            operations.append(("shutdown", wait, cancel_futures))

    def wait(futures, *, timeout):
        operations.append(("wait", timeout))
        assert futures == [future]
        return set(), {future}

    monkeypatch.setattr(native, "ThreadPoolExecutor", Pool)
    monkeypatch.setattr(native, "wait", wait)
    audit = native._FinalizerAudit(
        None, lambda kind, **data: records.append({"event": kind, **data}),
    )
    audit.passive = SimpleNamespace(critical_pools=0)
    original = AssertionError("FAKE_ORIGINAL_OBSERVER_FAILURE")
    observed_error = None
    try:
        with audit.pool() as (_pool, futures):
            futures.append(future)
            if body_failure:
                raise original
    except AssertionError as error:
        observed_error = error
    else:
        pytest.fail("The observer or pending-contender failure must propagate")
    assert operations == [("wait", 12), ("shutdown", True, True)]
    completed = next(row for row in records if row["event"] == "contenders_completed")
    assert completed["pending"] == 1
    assert completed["future_outcomes"] == [{"index": 0, "status": "pending"}]
    assert audit.passive.critical_pools == 0
    if body_failure:
        assert observed_error is original


def test_native_journal_footer_hashes_original_prefix_and_binds_full_node_path(tmp_path):
    stream = io.StringIO()
    nodeid = "tests/native.py::test_exact_case[text-worker-court_worker]"
    path = native._finalizer_evidence_path(tmp_path, nodeid)
    journal = native._FinalizerJournal(stream, path, nodeid)
    journal.record("source_identity", nodeid=nodeid, test_sha256="a" * 64)
    prefix = stream.getvalue().encode()
    journal.complete()
    records = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert records[-1]["event"] == "native_evidence_complete"
    assert records[-1]["payload_sha256"] == sha256(prefix).hexdigest()
    assert records[-1]["payload_bytes"] == len(prefix) and records[-1]["payload_records"] == 1
    assert records[-1]["nodeid"] == nodeid and records[-1]["evidence_path"] == str(path)
    assert path.name.startswith(sha256(nodeid.encode()).hexdigest()[:20])
    with pytest.raises(AssertionError, match="already completed"):
        journal.record("late_private_event")
    with pytest.raises(AssertionError, match="already completed"):
        journal.complete()


def test_native_journal_real_file_digest_matches_exact_bytes(tmp_path):
    path = tmp_path / "native.jsonl"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        journal = native._FinalizerJournal(stream, path, "tests/native.py::test_identity")
        journal.record("source_identity", node_source_sha256="b" * 64)
        journal.complete()
    prefix, final = path.read_bytes().rsplit(b"\n", 2)[:2]
    footer = json.loads(final)
    assert sha256(prefix + b"\n").hexdigest() == footer["payload_sha256"]


def test_journal_record_cap_rejects_before_write_and_never_accepts_overflow(tmp_path):
    stream = io.StringIO()
    journal = native._FinalizerJournal(stream, tmp_path / "native.jsonl", "tests/native.py::case")
    journal.record_cap = 2
    journal.byte_cap = 4096
    journal.record("first")
    journal.record("second")
    prefix = stream.getvalue()
    with pytest.raises(AssertionError, match="record cap"):
        journal.record("FAKE_EXCLUDED_RECORD")
    assert stream.getvalue() == prefix
    with pytest.raises(AssertionError):
        journal.complete()
    assert "native_evidence_complete" not in stream.getvalue()
    assert journal.records <= journal.record_cap and journal.bytes <= journal.byte_cap


def test_journal_serialized_byte_cap_rejects_before_write_and_retains_incomplete_footer(tmp_path):
    stream = io.StringIO()
    journal = native._FinalizerJournal(stream, tmp_path / "native.jsonl", "tests/native.py::case")
    journal.record_cap = 8
    journal.byte_cap = 4096
    journal.record("source_identity")
    prefix = stream.getvalue().encode()
    with pytest.raises(AssertionError, match="byte cap"):
        journal.record("oversized", fake_unicode="\u00e9" * 1000)
    assert stream.getvalue().encode() == prefix
    with pytest.raises(AssertionError, match="incomplete"):
        journal.complete()
    footer = json.loads(stream.getvalue().splitlines()[-1])
    assert footer["event"] == "native_evidence_incomplete" and not footer["complete"]
    assert footer["incomplete_reasons"] == ["byte_cap"]
    assert footer["payload_sha256"] == sha256(prefix).hexdigest()
    assert journal.bytes <= journal.byte_cap
    assert "native_evidence_complete" not in stream.getvalue()


def test_journal_closing_footer_obeys_caps_at_exact_record_boundary(tmp_path):
    stream = io.StringIO()
    journal = native._FinalizerJournal(stream, tmp_path / "native.jsonl", "tests/native.py::case")
    journal.record_cap = 2
    journal.byte_cap = 4096
    journal.record("source_identity")
    journal.complete()
    footer = json.loads(stream.getvalue().splitlines()[-1])
    assert footer["complete"] and footer["incomplete_reasons"] == []
    assert journal.records == journal.record_cap == 2
    assert journal.bytes == len(stream.getvalue().encode()) <= journal.byte_cap


def test_journal_io_failure_cannot_emit_accepted_footer_or_expose_error_message(tmp_path):
    class BrokenStream:
        def write(self, _line):
            raise OSError("FAKE_IO_CREDENTIAL")

    journal = native._FinalizerJournal(
        BrokenStream(), tmp_path / "native.jsonl", "tests/native.py::case",
    )
    with pytest.raises(OSError):
        journal.record("source_identity")
    with pytest.raises(AssertionError, match="incomplete"):
        journal.complete()
    assert journal.completed and "FAKE_" not in json.dumps(sorted(journal.incomplete_reasons))


def test_cleanup_evidence_failure_makes_footer_incomplete_without_replacing_original(tmp_path):
    stream = io.StringIO()
    journal = native._FinalizerJournal(stream, tmp_path / "native.jsonl", "tests/native.py::case")

    def record(kind, **data):
        if kind == "contenders_completed":
            raise RuntimeError("FAKE_RECORD_PRIVATE_MESSAGE")
        journal.record(kind, **data)

    audit = native._FinalizerAudit(None, record)
    original = AssertionError("FAKE_ORIGINAL_PRIVATE_MESSAGE")
    observed_error = None
    try:
        with audit.pool():
            raise original
    except AssertionError as error:
        observed_error = error
    assert observed_error is original
    with pytest.raises(AssertionError, match="incomplete"):
        journal.complete()
    footer = json.loads(stream.getvalue().splitlines()[-1])
    assert footer["event"] == "native_evidence_incomplete" and not footer["complete"]
    assert footer["incomplete_reasons"] == ["contender_cleanup_failed"]
    assert "FAKE_" not in stream.getvalue()


@pytest.mark.parametrize("probe", [
    test_pool_failure_retains_original_exception_and_sanitized_future_outcomes,
    test_cleanup_evidence_failure_makes_footer_incomplete_without_replacing_original,
], ids=["pool-original", "cleanup-original"])
def test_original_error_identity_assertion_rejects_suppressed_body(monkeypatch, tmp_path, probe):
    @contextmanager
    def suppress_body(_audit):
        try:
            yield SimpleNamespace(submit=lambda _callback: Future()), []
        except AssertionError:
            pass

    monkeypatch.setattr(native._FinalizerAudit, "pool", suppress_body)
    arguments = [tmp_path] if probe is (
        test_cleanup_evidence_failure_makes_footer_incomplete_without_replacing_original
    ) else []
    with pytest.raises(AssertionError, match="assert None is"):
        probe(*arguments)


def test_ci_retains_exact_per_shard_native_journals_without_weakening_invocation():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text())
    steps = workflow["jobs"]["postgres-validation-shards"]["steps"]
    test = next(step for step in steps if step.get("name") == "Pytest -m postgres")
    upload = next(step for step in steps if step.get("name") == (
        "Upload exact PostgreSQL collection and results"
    ))
    directory = "postgres-shard-${{ matrix.shard }}-native"
    assert test["env"]["CASEOPS_FINALIZER_EVIDENCE_DIR"] == directory
    assert test["run"] == "uv run python -m pytest -q -m postgres"
    assert upload["if"] == "always()"
    assert f"apps/api/{directory}/*.jsonl" in upload["with"]["path"].splitlines()
    assert upload["with"]["if-no-files-found"] == "error"
