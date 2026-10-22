from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.test_deploy_prod_hardening import _security_gate_payloads

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "release_security_gate", ROOT / "scripts/release_security_gate.py",
)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHA = "abcdef1234567890abcdef1234567890abcdef12"


@pytest.fixture
def metadata(monkeypatch):
    data = _security_gate_payloads()
    data["calls"] = []

    def get(endpoint, deadline):
        assert deadline > time.monotonic()
        data["calls"].append(endpoint)
        if "/attempts/" in endpoint:
            jobs = copy.deepcopy(data["jobs"])
            run_id = int(endpoint.split("/runs/", 1)[1].split("/", 1)[0])
            if run_id != 101:
                run = next(row for row in data["runs"]["workflow_runs"] if row["id"] == run_id)
                for job in jobs["jobs"]:
                    job["run_id"] = run_id
                    job["id"] += run_id
                    job["started_at"] = run["created_at"]
                    job["completed_at"] = run["updated_at"]
            return jobs
        if "/runs?" in endpoint:
            return copy.deepcopy(data["runs"])
        assert endpoint.endswith("/actions/workflows/security.yml")
        return copy.deepcopy(data["workflow"])

    monkeypatch.setattr(gate, "_gh_json", get)
    return data


def _new_run(data, event="schedule"):
    row = copy.deepcopy(data["runs"]["workflow_runs"][0])
    row.update(id=102, run_number=21, event=event, created_at="2026-10-02T00:00:00Z",
               updated_at="2026-10-02T00:02:00Z")
    data["runs"]["workflow_runs"].insert(0, row)
    data["runs"]["total_count"] += 1
    return row


def test_exact_main_push_all_eight_jobs_are_bound(metadata):
    assert gate.verify_security(SHA)["runs"] == [
        {"id": 101, "attempt": 1, "event": "push", "successful_jobs": 8},
    ]
    assert len(metadata["calls"]) == 4
    assert "/runs/101/attempts/1/jobs?per_page=100" in metadata["calls"][2]
    assert "event=" not in metadata["calls"][1]


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch", "push"])
@pytest.mark.parametrize("status,conclusion", [
    ("queued", None), ("in_progress", None), ("completed", "failure"),
    ("completed", "cancelled"), ("completed", "skipped"), ("completed", "neutral"),
])
def test_new_execution_cannot_hide_behind_green_push(metadata, event, status, conclusion):
    _new_run(metadata, event).update(status=status, conclusion=conclusion)
    with pytest.raises(gate.GateError, match="latest_security_not_successful"):
        gate.verify_security(SHA)


@pytest.mark.parametrize("event", ["schedule", "workflow_dispatch"])
def test_new_successful_manual_or_scheduled_run_and_push_both_require_jobs(metadata, event):
    _new_run(metadata, event)
    receipt = gate.verify_security(SHA)
    assert [row["id"] for row in receipt["runs"]] == [101, 102]
    assert sum("/attempts/" in endpoint for endpoint in metadata["calls"]) == 2


def test_late_old_success_does_not_hide_new_queued_execution(metadata):
    _new_run(metadata).update(status="queued", conclusion=None)
    metadata["runs"]["workflow_runs"][1]["updated_at"] = "2026-10-03T00:00:00Z"
    with pytest.raises(gate.GateError, match="latest_security_not_successful"):
        gate.verify_security(SHA)


def test_rerun_of_older_execution_is_also_fresh_failure(metadata):
    _new_run(metadata, "push")
    metadata["runs"]["workflow_runs"][1].update(
        run_attempt=2, updated_at="2026-10-03T00:00:00Z", conclusion="failure",
    )
    with pytest.raises(gate.GateError, match="latest_security_not_successful"):
        gate.verify_security(SHA)


@pytest.mark.parametrize("field,value", [
    ("head_sha", "b" * 40), ("head_branch", "feature"), ("workflow_id", 501),
    ("name", "Other"), ("path", ".github/workflows/other.yml"),
    ("event", "pull_request"), ("run_attempt", True), ("id", False),
    ("created_at", "2099-01-01T00:00:00Z"), ("updated_at", None),
    ("created_at", "2026-10-01T00:00:00"), ("updated_at", "2026-09-01T00:00:00Z"),
    ("repository", {"full_name": "foreign/repo"}), ("head_repository", None),
])
def test_run_identity_and_timestamps_fail_closed(metadata, field, value):
    metadata["runs"]["workflow_runs"][0][field] = value
    with pytest.raises(gate.GateError):
        gate.verify_security(SHA)


@pytest.mark.parametrize("field,value", [
    ("id", True), ("name", "Other"), ("state", "disabled_manually"),
    ("path", ".github/workflows/other.yml"),
])
def test_workflow_identity_is_required(metadata, field, value):
    metadata["workflow"][field] = value
    with pytest.raises(gate.GateError):
        gate.verify_security(SHA)


def test_schedule_without_canonical_push_cannot_authorize_deployment(metadata):
    metadata["runs"]["workflow_runs"][0]["event"] = "schedule"
    with pytest.raises(gate.GateError, match="canonical_push_security_missing"):
        gate.verify_security(SHA)


@pytest.mark.parametrize("inventory", ["runs", "jobs"])
@pytest.mark.parametrize("total", [0, 101, True, None, 99])
def test_empty_or_paginated_or_malformed_inventory_cannot_authorize(metadata, inventory, total):
    metadata[inventory]["total_count"] = total
    with pytest.raises(gate.GateError, match="incomplete_metadata_inventory"):
        gate.verify_security(SHA)


@pytest.mark.parametrize("damage", [
    "missing", "extra", "duplicate-id", "duplicate-name", "unknown-name",
])
def test_required_job_inventory_is_exact(metadata, damage):
    rows = metadata["jobs"]["jobs"]
    if damage == "missing":
        rows.pop()
    elif damage == "extra":
        rows.append(copy.deepcopy(rows[0]))
    elif damage == "duplicate-id":
        rows[1]["id"] = rows[0]["id"]
    elif damage == "duplicate-name":
        rows[1]["name"] = rows[0]["name"]
    else:
        rows[1]["name"] = "Unreviewed replacement"
    metadata["jobs"]["total_count"] = len(rows)
    with pytest.raises(gate.GateError):
        gate.verify_security(SHA)


@pytest.mark.parametrize("field,value", [
    ("run_id", 102), ("run_attempt", 2), ("run_attempt", True),
    ("head_sha", "b" * 40), ("head_branch", "feature"), ("workflow_name", "Other"),
    ("status", "in_progress"), ("conclusion", "failure"), ("conclusion", "skipped"),
    ("conclusion", "neutral"), ("conclusion", "timed_out"),
    ("started_at", "2026-09-01T00:00:00Z"), ("completed_at", "2099-01-01T00:00:00Z"),
    ("completed_at", "2026-10-01T00:03:00Z"), ("steps", []),
    ("steps", [{"status": "completed", "conclusion": "failure"}]),
    ("steps", [{"status": "in_progress", "conclusion": None}]),
])
def test_each_machine_job_binds_actual_attempt_and_success(metadata, field, value):
    metadata["jobs"]["jobs"][0][field] = value
    with pytest.raises(gate.GateError):
        gate.verify_security(SHA)


def test_legitimate_skipped_step_is_not_a_skipped_required_job(metadata):
    metadata["jobs"]["jobs"][0]["steps"].append({"status": "completed", "conclusion": "skipped"})
    gate.verify_security(SHA)


@pytest.mark.parametrize("change", ["new-failure", "new-queued", "rerun", "updated"])
def test_final_read_rejects_security_change_during_admission(metadata, monkeypatch, change):
    get = gate._gh_json
    reads = 0

    def changing(endpoint, deadline):
        nonlocal reads
        if "/runs?" in endpoint:
            reads += 1
            if reads == 2:
                if change.startswith("new"):
                    row = _new_run(metadata)
                    row.update(status="queued" if change == "new-queued" else "completed",
                               conclusion=None if change == "new-queued" else "failure")
                elif change == "rerun":
                    metadata["runs"]["workflow_runs"][0]["run_attempt"] = 2
                else:
                    metadata["runs"]["workflow_runs"][0]["updated_at"] = "2026-10-01T00:03:00Z"
        return get(endpoint, deadline)

    monkeypatch.setattr(gate, "_gh_json", changing)
    with pytest.raises(gate.GateError):
        gate.verify_security(SHA)


@pytest.mark.parametrize("body", [b"{", b'[]', b'{"a":1,"a":2}', b'{"x":NaN}', b'\xff'])
def test_transport_rejects_malformed_json_without_echo(monkeypatch, body):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "/fake/gh")
    monkeypatch.setattr(gate.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout=body, stderr=b"PRIVATE RAW STDERR",
    ))
    with pytest.raises(gate.GateError) as caught:
        gate._gh_json("fixed-endpoint", time.monotonic() + 20)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("failure", [
    "missing", "exit", "timeout", "oserror", "oversize", "deadline",
])
def test_transport_failure_is_bounded_fail_closed(monkeypatch, failure):
    monkeypatch.setattr(gate.shutil, "which", lambda _: (
        None if failure == "missing" else "/fake/gh"
    ))

    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("gh", 1, output=b"PRIVATE")
        if failure == "oserror":
            raise OSError("PRIVATE")
        output = b"x" * (gate.OUTPUT_LIMIT + 1) if failure == "oversize" else b"{}"
        return SimpleNamespace(returncode=1 if failure == "exit" else 0,
                               stdout=output, stderr=b"PRIVATE")

    monkeypatch.setattr(gate.subprocess, "run", run)
    with pytest.raises(gate.GateError) as caught:
        gate._gh_json("fixed-endpoint", time.monotonic() + (-1 if failure == "deadline" else 20))
    assert "PRIVATE" not in str(caught.value)


def test_transport_is_explicit_readonly_github_and_bounded(monkeypatch):
    monkeypatch.setattr(gate.shutil, "which", lambda _: "/fake/gh")
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"{}", stderr=b"")

    monkeypatch.setattr(gate.subprocess, "run", run)
    assert gate._gh_json("fixed-endpoint", time.monotonic() + 20) == {}
    argv, kwargs = seen[0]
    assert argv[:7] == ["/fake/gh", "api", "--hostname", "github.com", "--method", "GET", "-H"]
    assert argv[-1] == "fixed-endpoint"
    assert 0 < kwargs["timeout"] <= 10 and kwargs["check"] is False
    assert "shell" not in kwargs


@pytest.mark.parametrize("sha", ["", "a" * 7, "A" * 40, "x" * 40])
def test_cli_invalid_sha_fails_without_metadata(metadata, capsys, sha):
    assert gate.main(["--sha", sha, "--phase", "pre-cloud"]) == 1
    assert not metadata["calls"]
    assert json.loads(capsys.readouterr().err)["error"] == "invalid_release_sha"


def test_release_owned_helper_exists_and_required_inventory_matches_policy():
    policy = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"))
    assert set(gate.REQUIRED_JOBS) == {job["name"] for job in policy["jobs"].values()}
    source = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    assert (ROOT / "scripts/release_security_gate.py").is_file()
    dirty = source.split("DIRTY_BUILD_CONTEXT=", 1)[1].split("if [[", 1)[0]
    assert '"scripts/release_security_gate.py"' in dirty
    assert '".github/workflows/security.yml"' in dirty
    assert source.count('release_security_gate.py --sha "${HEAD_SHA}" --phase ') == 2
