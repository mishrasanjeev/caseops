"""IPLF-030B/UJ-04: retain bounded export plans in the existing CI artifact."""

import hashlib
import json
from contextlib import contextmanager
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests import test_ip_portfolio_export_projection_20261026 as projection


def _exercise_plan_evidence(tmp_path, monkeypatch, request, *, work, exceeds_bound):
    root = Path(projection.__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-validation-shards"]
    execution = next(step for step in job["steps"] if step.get("name") == "Pytest -m postgres")
    upload = next(step for step in job["steps"]
                  if step.get("name") == "Upload exact PostgreSQL collection and results")
    assert execution["working-directory"] == "apps/api"
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"

    def rendered(value):
        value = value.replace("${{ matrix.shard }}", "16")
        assert "${{" not in value
        return value

    api = tmp_path / "apps" / "api"
    evidence = api / rendered(execution["env"]["CASEOPS_FINALIZER_EVIDENCE_DIR"])
    journal = tmp_path / "different-journal-parent" / rendered(
        execution["env"]["CASEOPS_TEST_RESULT_JOURNAL"]
    )
    monkeypatch.setenv("CASEOPS_FINALIZER_EVIDENCE_DIR", str(evidence))
    monkeypatch.setenv("CASEOPS_TEST_RESULT_JOURNAL", str(journal))
    assert evidence.parent != journal.parent
    nodeid = request.node.nodeid
    digest = hashlib.sha256(nodeid.encode()).hexdigest()[:16]
    flat = evidence / f"export-projection-{digest}.jsonl"
    relative = flat.relative_to(tmp_path).as_posix()
    patterns = [rendered(line.strip()) for line in upload["with"]["path"].splitlines()]
    native_pattern = f"apps/api/{evidence.name}/*.jsonl"
    assert native_pattern in patterns
    assert fnmatchcase(relative, native_pattern)
    assert flat.parent == evidence

    record = {
        "statement": "SELECT id FROM audit_events WHERE company_id = %(company_id)s",
        "parameters": {"company_id": "synthetic-company"},
        "read_only": True,
        "limit": 1,
    }
    plan = [{
        "Plan": {
            "Node Type": "Index Scan",
            "Relation Name": "audit_events",
            "Index Name": "synthetic_read_only_index",
            "Actual Rows": work,
            "Actual Loops": 1,
            "Rows Removed by Filter": 0,
        },
        "Execution Time": 0.01,
    }]
    assert work == (21 if exceeds_bound else 20)
    calls = []

    def explain(statement, parameters):
        assert statement == (
            "EXPLAIN (ANALYZE, BUFFERS, SETTINGS, FORMAT JSON) " + record["statement"]
        )
        assert parameters == record["parameters"]
        calls.append((statement, deepcopy(parameters)))
        return SimpleNamespace(scalar_one=lambda: deepcopy(plan))

    @contextmanager
    def begin():
        yield SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"), exec_driver_sql=explain,
        )

    monkeypatch.setattr(projection, "get_engine", lambda: SimpleNamespace(begin=begin))
    measurement = {"statistics": "synthetic-fresh", "rows": 1, "elapsed_seconds": 0.001}
    arguments = {
        "directory": tmp_path / "local-fallback",
        "candidate_bound": 1,
        "nodeid": nodeid,
        "measurement": measurement,
    }
    if exceeds_bound:
        with pytest.raises(
            AssertionError, match="Provenance work exceeds the existing candidate bound",
        ):
            projection._plans([record], **arguments)
    else:
        projection._plans([record], **arguments)

    # A failed work assertion must leave the complete uploadable evidence behind.
    rows = [json.loads(line) for line in flat.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["event"] == "export_projection_measurement"
    assert rows[0]["nodeid"] == nodeid
    assert rows[0]["candidate_bound"] == 1
    assert rows[0]["measurement"] == measurement
    for key, value in record.items():
        assert rows[1][key] == value
    assert rows[1]["plan"] == plan
    assert len(calls) == 1
    assert list(evidence.glob("export-projection-*.jsonl")) == [flat]
    assert not list(journal.parent.glob("export-projection-*.jsonl"))
    aggregates = list(tmp_path.rglob("export-projection-plans.json"))
    assert len(aggregates) == 1
    aggregate = json.loads(aggregates[0].read_text(encoding="utf-8"))
    assert len(aggregate) == 1
    assert aggregate[0]["plan"] == plan
    for key, value in record.items():
        assert aggregate[0][key] == value


def test_exact_work_bound_retains_flat_ci_plan(tmp_path, monkeypatch, request):
    _exercise_plan_evidence(tmp_path, monkeypatch, request, work=20, exceeds_bound=False)


def test_exceeded_work_bound_retains_flat_ci_plan_before_failure(tmp_path, monkeypatch, request):
    _exercise_plan_evidence(tmp_path, monkeypatch, request, work=21, exceeds_bound=True)
