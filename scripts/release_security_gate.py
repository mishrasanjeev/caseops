#!/usr/bin/env python3
"""Read-only, fail-closed Security admission for an exact canonical main SHA."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime

REPOSITORY = "mishrasanjeev/caseops"
WORKFLOW_PATH = ".github/workflows/security.yml"
REQUIRED_JOBS = (
    "npm audit (high+critical)",
    "pip-audit (high+critical)",
    "Secret scan (gitleaks)",
    "License allow-list",
    "OpenAPI -> generated client clean diff (QG-API-012, P1-010)",
    "Cloud Run manifests use secret refs (QG-OPS-006)",
    "JS workspace production lock policy",
    "Native Cloud Build web upload context",
)
TOTAL_SECONDS = 60
OUTPUT_LIMIT = 4 * 1024 * 1024


class GateError(RuntimeError):
    """Only fixed, non-sensitive diagnostic codes cross the CLI boundary."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise GateError(code)


def _object(value: object) -> dict:
    _require(isinstance(value, dict), "invalid_metadata_object")
    return value


def _integer(value: object) -> int:
    _require(type(value) is int and value > 0, "invalid_metadata_integer")
    return value


def _timestamp(value: object, now: datetime) -> datetime:
    _require(isinstance(value, str), "invalid_metadata_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise GateError("invalid_metadata_timestamp") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
             "invalid_metadata_timestamp")
    _require(parsed <= now, "future_metadata_timestamp")
    return parsed


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_metadata_key")
        result[key] = value
    return result


def _invalid_constant(_value: str) -> None:
    raise GateError("invalid_metadata_json")


def _gh_json(endpoint: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    _require(remaining > 0, "security_deadline_exceeded")
    executable = shutil.which("gh")
    _require(executable is not None, "github_cli_unavailable")
    try:
        result = subprocess.run(
            [executable, "api", "--hostname", "github.com", "--method", "GET",
             "-H", "Accept: application/vnd.github+json",
             "-H", "X-GitHub-Api-Version: 2022-11-28", endpoint],
            capture_output=True, timeout=min(10, remaining), check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GateError("github_metadata_unavailable") from exc
    _require(result.returncode == 0, "github_metadata_unavailable")
    _require(len(result.stdout) <= OUTPUT_LIMIT and len(result.stderr) <= OUTPUT_LIMIT,
             "github_metadata_exceeded_bound")
    try:
        return _object(json.loads(result.stdout, object_pairs_hook=_unique_object,
                                  parse_constant=_invalid_constant))
    except (ValueError, UnicodeError) as exc:
        raise GateError("invalid_metadata_json") from exc


def _inventory(payload: dict, key: str) -> list[dict]:
    rows = payload.get(key)
    total = payload.get("total_count")
    _require(isinstance(rows, list) and type(total) is int and 0 < total <= 100
             and total == len(rows), "incomplete_metadata_inventory")
    return [_object(row) for row in rows]


def _selected_runs(payload: dict, sha: str, workflow_id: int, now: datetime) -> list[dict]:
    rows = _inventory(payload, "workflow_runs")
    ids = set()
    for row in rows:
        identity = _integer(row.get("id"))
        _require(identity not in ids, "duplicate_security_run")
        ids.add(identity)
        _integer(row.get("run_number"))
        _integer(row.get("run_attempt"))
        _integer(row.get("workflow_id"))
        _require(row.get("workflow_id") == workflow_id and row.get("name") == "Security"
                 and row.get("path") == WORKFLOW_PATH and row.get("head_sha") == sha
                 and row.get("head_branch") == "main", "foreign_security_run")
        for key in ("repository", "head_repository"):
            _require(_object(row.get(key)).get("full_name") == REPOSITORY,
                     "foreign_security_repository")
        _require(row.get("event") in {"push", "schedule", "workflow_dispatch"},
                 "unsupported_security_event")
        created = _timestamp(row.get("created_at"), now)
        _require(_timestamp(row.get("updated_at"), now) >= created,
                 "invalid_security_run_timeline")
    pushes = [row for row in rows if row["event"] == "push"]
    _require(bool(pushes), "canonical_push_security_missing")

    def created_order(row: dict) -> tuple[datetime, int]:
        return _timestamp(row["created_at"], now), row["id"]

    def updated_order(row: dict) -> tuple[datetime, int]:
        return _timestamp(row["updated_at"], now), row["id"]

    # Check the latest execution AND latest observation (including an old rerun).
    # An older run completing late cannot hide a newer queued/failed execution.
    selected = {row["id"]: row for row in (
        max(pushes, key=created_order), max(rows, key=created_order), max(rows, key=updated_order),
    )}
    for row in selected.values():
        _require(row.get("status") == "completed" and row.get("conclusion") == "success",
                 "latest_security_not_successful")
    return sorted(selected.values(), key=lambda row: row["id"])


def _jobs(payload: dict, run: dict, now: datetime) -> None:
    jobs = _inventory(payload, "jobs")
    _require(len(jobs) == len(REQUIRED_JOBS), "security_job_inventory_mismatch")
    ids, names = set(), set()
    for job in jobs:
        identity = _integer(job.get("id"))
        name = job.get("name")
        _require(isinstance(name, str) and identity not in ids and name not in names,
                 "duplicate_security_job")
        ids.add(identity)
        names.add(name)
        _integer(job.get("run_id"))
        _integer(job.get("run_attempt"))
        _require(job.get("run_id") == run["id"] and job.get("run_attempt") == run["run_attempt"]
                 and job.get("head_sha") == run["head_sha"] and job.get("head_branch") == "main"
                 and job.get("workflow_name") == "Security", "foreign_security_job")
        _require(job.get("status") == "completed" and job.get("conclusion") == "success",
                 "security_job_not_successful")
        started = _timestamp(job.get("started_at"), now)
        completed = _timestamp(job.get("completed_at"), now)
        _require(_timestamp(run["created_at"], now) <= started <= completed
                 <= _timestamp(run["updated_at"], now), "invalid_security_job_timeline")
        steps = job.get("steps")
        _require(isinstance(steps, list) and bool(steps), "security_steps_missing")
        for step in steps:
            step = _object(step)
            _require(step.get("status") == "completed"
                     and step.get("conclusion") in {"success", "skipped"},
                     "security_step_not_successful")
    _require(names == set(REQUIRED_JOBS), "security_job_inventory_mismatch")


def verify_security(sha: str) -> dict:
    _require(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) is not None,
             "invalid_release_sha")
    deadline = time.monotonic() + TOTAL_SECONDS
    now = datetime.now(UTC)
    prefix = f"repos/{REPOSITORY}/actions"
    workflow = _gh_json(f"{prefix}/workflows/security.yml", deadline)
    workflow_id = _integer(workflow.get("id"))
    _require(workflow.get("name") == "Security" and workflow.get("path") == WORKFLOW_PATH
             and workflow.get("state") == "active", "invalid_security_workflow")
    # No event filter: a newer failed schedule/manual run must block an older green push.
    endpoint = f"{prefix}/workflows/security.yml/runs?branch=main&head_sha={sha}&per_page=100"
    runs = _selected_runs(_gh_json(endpoint, deadline), sha, workflow_id, now)
    for run in runs:
        jobs = _gh_json(
            f"{prefix}/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100", deadline,
        )
        _jobs(jobs, run, now)
    refreshed = _selected_runs(_gh_json(endpoint, deadline), sha, workflow_id, datetime.now(UTC))
    fields = ("id", "run_attempt", "updated_at")
    _require([[run[field] for field in fields] for run in runs]
             == [[run[field] for field in fields] for run in refreshed], "security_run_changed")
    return {"sha": sha, "workflow_id": workflow_id,
            "runs": [{"id": run["id"], "attempt": run["run_attempt"],
                      "event": run["event"], "successful_jobs": len(REQUIRED_JOBS)} for run in runs]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--phase", choices=("pre-cloud", "post-build"), required=True)
    args = parser.parse_args(argv)
    try:
        receipt = verify_security(args.sha)
    except GateError as exc:
        print(json.dumps({"error": str(exc), "phase": args.phase}), file=sys.stderr)
        return 1
    print(json.dumps({"phase": args.phase, **receipt}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
