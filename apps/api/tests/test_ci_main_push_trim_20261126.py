"""Pin when the complete CI suite runs.

Pull requests, the nightly run on main and a dispatched run execute every
job. A push to main runs only the fast lint, web and build gates, because the
merged change already passed the complete suite on its pull request.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
PUSH_SKIPPED = {
    "api-test-shards",
    "api",
    "postgres-validation-shards",
    "postgres-validation",
    "web-windows",
    "e2e",
}
PUSH_GATE = "github.event_name != 'push'"


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))


def test_complete_suite_runs_on_pull_requests_nightly_and_on_demand() -> None:
    workflow = _workflow()
    triggers = workflow[True]  # PyYAML reads the bare `on` key as boolean True.
    assert triggers["push"] == {"branches": ["main"]}
    assert triggers["pull_request"] == {"branches": ["main"]}
    assert triggers["schedule"] == [{"cron": "17 20 * * *"}]
    assert "workflow_dispatch" in triggers
    # A merge to main must not cancel the nightly or a dispatched complete run.
    assert workflow["concurrency"] == {
        "group": "ci-${{ github.ref }}-${{ github.event_name }}",
        "cancel-in-progress": True,
    }


def test_only_the_heavy_suites_skip_a_push_to_main() -> None:
    jobs = _workflow()["jobs"]
    gated = {name for name, job in jobs.items() if PUSH_GATE in str(job.get("if", ""))}
    assert gated == PUSH_SKIPPED
    for name in ("api-ruff", "web"):
        assert "if" not in jobs[name], name
    # e2e-projects has no condition of its own; it skips a push to main
    # because it needs the skipped api job.
    assert "if" not in jobs["e2e-projects"]
    assert "api" in jobs["e2e-projects"]["needs"]
    # The gate is the only change: no job may skip pull requests, schedules or
    # dispatches, and the aggregators still require every shard to succeed.
    for name, job in jobs.items():
        condition = str(job.get("if", ""))
        for event in ("pull_request", "schedule", "workflow_dispatch"):
            assert event not in condition, (name, condition)
    for name in ("api", "postgres-validation", "e2e"):
        assert jobs[name]["if"] == f"{PUSH_GATE} && always() && !cancelled()"
    assert jobs["api"]["needs"] == ["api-ruff", "api-test-shards"]
    assert jobs["postgres-validation"]["needs"] == ["postgres-validation-shards"]
    assert jobs["e2e"]["needs"] == ["api", "web", "postgres-validation", "e2e-projects"]
