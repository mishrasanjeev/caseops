from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from tests.retained_results import JOURNAL_ENV, OWNER_ENV, RetainedResults


def _run(tmp_path: Path, source: str, *arguments: str):
    fixture = tmp_path / "test_journal_fixture.py"
    fixture.write_text(source, encoding="utf-8")
    target = tmp_path / "results.jsonl"
    environment = dict(os.environ)
    environment.pop(OWNER_ENV, None)
    environment[JOURNAL_ENV] = str(target)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--confcutdir", str(tmp_path),
         "-p", "tests.retained_results", *arguments, str(fixture)],
        env=environment, capture_output=True, text=True, timeout=20, check=False,
    )
    return result, [json.loads(line) for line in target.read_text().splitlines()]


def test_retained_results_capture_each_failure_and_complete_collection(tmp_path):
    result, rows = _run(tmp_path, """import pytest
def test_passes():
    assert True
def test_fails():
    assert False, 'retained assertion detail'
@pytest.fixture
def broken():
    raise RuntimeError('retained setup detail')
def test_setup_error(broken):
    pass
""")
    assert result.returncode == 1, result.stdout + result.stderr
    collection = next(row for row in rows if row["event"] == "collection")
    assert len(collection["nodeids"]) == 3
    failures = [row for row in rows if row.get("outcome") == "failed"]
    assert len(failures) == 2
    assert {row["when"] for row in failures} == {"call", "setup"}
    assert "retained assertion detail" in failures[0]["longrepr"]
    assert "retained setup detail" in failures[1]["longrepr"]
    assert rows[-1] == {"event": "session_finished", "exitstatus": 1}


def test_hard_interruption_retains_prior_failure_without_claiming_completion(tmp_path):
    result, rows = _run(tmp_path, """import os
def test_first_failure():
    assert False, 'failure survives process interruption'
def test_later_interruption():
    os._exit(17)
""")
    assert result.returncode == 17, result.stdout + result.stderr
    failures = [row for row in rows if row.get("outcome") == "failed"]
    assert len(failures) == 1
    assert "failure survives process interruption" in failures[0]["longrepr"]
    assert not any(row["event"] == "session_finished" for row in rows)


def test_existing_test_evidence_is_never_overwritten(tmp_path):
    target = tmp_path / "results.jsonl"
    original = '{"event":"previous_evidence"}\n'
    target.write_text(original, encoding="utf-8")
    result, rows = _run(tmp_path, "def test_noop():\n    pass\n")
    assert result.returncode == 4, result.stdout + result.stderr
    assert "existing evidence is retained" in result.stderr
    assert target.read_text() == original
    assert rows == [{"event": "previous_evidence"}]


def test_xdist_reports_are_retained_once_by_the_controller(tmp_path):
    result, rows = _run(tmp_path, """def test_first():
    assert True
def test_second():
    assert True
""", "-n", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    collections = [row for row in rows if row["event"] == "collection"]
    assert len(collections) == 1
    assert len(collections[0]["nodeids"]) == 2
    workers = [row for row in rows if row["event"] == "worker_collection"]
    assert {row["worker"] for row in workers} == {"gw0", "gw1"}
    assert all(row["matches_collection"] for row in workers)
    assert all(row["nodeids"] == collections[0]["nodeids"] for row in workers)
    reports = [row for row in rows if row["event"] == "test_report"]
    assert len(reports) == 6
    assert {(row["nodeid"], row["when"]) for row in reports} == {
        (nodeid, phase) for nodeid in collections[0]["nodeids"]
        for phase in ("setup", "call", "teardown")
    }
    calls = [row for row in rows if row.get("when") == "call"]
    assert len(calls) == 2
    assert len({row["nodeid"] for row in calls}) == 2
    assert all(row["outcome"] == "passed" for row in calls)
    assert rows[-1] == {"event": "session_finished", "exitstatus": 0}


def test_divergent_worker_inventory_is_retained_without_overwriting_collection(tmp_path):
    target = tmp_path / "divergent.jsonl"
    journal = RetainedResults(target)
    try:
        journal.pytest_xdist_node_collection_finished(
            SimpleNamespace(gateway=SimpleNamespace(id="gw0")), ["a", "b"]
        )
        journal.pytest_xdist_node_collection_finished(
            SimpleNamespace(gateway=SimpleNamespace(id="gw1")), ["a", "c"]
        )
    finally:
        journal.stream.close()
    rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert [row for row in rows if row["event"] == "collection"] == [
        {"event": "collection", "nodeids": ["a", "b"]}
    ]
    workers = [row for row in rows if row["event"] == "worker_collection"]
    assert workers[0]["matches_collection"] is True
    assert workers[1]["matches_collection"] is False
    assert workers[1]["nodeids"] == ["a", "c"]
    assert not any(row["event"] == "session_finished" for row in rows)
