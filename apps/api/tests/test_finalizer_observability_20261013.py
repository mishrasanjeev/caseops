"""Pure controls for native journal retention and sanitized contender evidence."""

import io
import json
from concurrent.futures import Future
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

    with pytest.raises(AssertionError) as caught, audit.pool() as (pool, futures):
        futures.append(pool.submit(contender))
        raise original
    assert caught.value is original
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
        futures.append(pool.submit(lambda: _PrivateValue()))
    assert records[-1]["future_outcomes"] == [{"index": 0, "status": "completed"}]
    assert records[-1]["observer_failed"] is False


@pytest.mark.parametrize("body_failure", [False, True])
def test_pool_cleanup_record_failure_cannot_replace_original_observer_error(body_failure):
    def broken_record(*_args, **_kwargs):
        raise RuntimeError("FAKE_RECEIPT_FAILURE")

    audit = native._FinalizerAudit(None, broken_record)
    original = AssertionError("FAKE_ORIGINAL_OBSERVER_FAILURE")
    expected = AssertionError if body_failure else RuntimeError
    with pytest.raises(expected) as caught, audit.pool():
        if body_failure:
            raise original
    if body_failure:
        assert caught.value is original
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
    with pytest.raises(AssertionError) as caught, audit.pool() as (_pool, futures):
        futures.append(future)
        if body_failure:
            raise original
    assert operations == [("wait", 12), ("shutdown", True, True)]
    completed = next(row for row in records if row["event"] == "contenders_completed")
    assert completed["pending"] == 1
    assert completed["future_outcomes"] == [{"index": 0, "status": "pending"}]
    assert audit.passive.critical_pools == 0
    if body_failure:
        assert caught.value is original


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
    with pytest.raises(AssertionError) as caught, audit.pool():
        raise original
    assert caught.value is original
    with pytest.raises(AssertionError, match="incomplete"):
        journal.complete()
    footer = json.loads(stream.getvalue().splitlines()[-1])
    assert footer["event"] == "native_evidence_incomplete" and not footer["complete"]
    assert footer["incomplete_reasons"] == ["contender_cleanup_failed"]
    assert "FAKE_" not in stream.getvalue()


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
