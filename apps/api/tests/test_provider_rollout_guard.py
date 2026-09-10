from __future__ import annotations

import copy
import subprocess

import pytest

from tests.test_scheduler_inventory import INVENTORY_PATH
from tests.test_scheduler_inventory import scheduler_inventory as guard

SCHEDULER = "caseops-case-tracking-poll-1800-ist"
JOB = "caseops-case-tracking-poll"
IMAGE = "registry.example/api@sha256:" + "b" * 64


def execution(name="old-worker", *, done=False, running=0):
    return {
        "metadata": {"name": name, "labels": {"run.googleapis.com/job": JOB}},
        "status": {
            "runningCount": running,
            **({"completionTime": "2026-09-09T03:00:00Z"} if done else {}),
        },
    }


def wire(monkeypatch, histories):
    inventory = guard.load_inventory(INVENTORY_PATH)
    now = [0.0]
    calls = []
    histories = iter(histories)
    monkeypatch.setattr(guard.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(guard.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))

    def gcloud(arguments, *, expect_json=False, timeout=60):
        calls.append(arguments)
        assert 0 < timeout <= 30
        if arguments[:3] == ["scheduler", "jobs", "pause"]:
            return ""
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "PAUSED",
                "httpTarget": {"uri": guard.scheduler_uri("p", "r", JOB)},
            }
        assert arguments[:4] == ["run", "jobs", "executions", "list"]
        assert "--limit=1001" in arguments
        assert not any(arg.startswith("--filter") for arg in arguments)
        assert not any(arg.startswith("--sort-by") for arg in arguments)
        return next(histories)

    monkeypatch.setattr(guard, "run_gcloud", gcloud)
    return inventory, calls, now


def test_drain_does_not_miss_old_worker_behind_new_completed_execution(monkeypatch):
    inventory, calls, now = wire(
        monkeypatch,
        [
            [execution("new", done=True), execution("old", running=1)],
            [execution("new", done=True), execution("old", done=True)],
            [execution("new", done=True), execution("old", done=True)],
        ],
    )
    result = guard.quiesce(inventory, scheduler=SCHEDULER, project="p", region="r")
    assert result["drained"] and result["clean_samples"] == 2
    assert result["observed_executions"] == ["old"]
    assert now[0] == 10
    assert calls[0][:4] == ["scheduler", "jobs", "pause", SCHEDULER]
    assert not any("resume" in args or "execute" in args or "cancel" in args for args in calls)


def test_delayed_dispatch_resets_quiescence_samples(monkeypatch):
    inventory, _calls, now = wire(monkeypatch, [[], [execution()], [], []])
    assert guard.quiesce(inventory, scheduler=SCHEDULER, project="p", region="r")["drained"]
    assert now[0] == 15


def test_drain_deadline_keeps_scheduler_paused_without_cancelling_paid_work(monkeypatch):
    inventory, calls, now = wire(monkeypatch, [[execution(running=1)]] * 2)
    with pytest.raises(guard.InventoryError, match="remains paused"):
        guard.quiesce(inventory, scheduler=SCHEDULER, project="p", region="r", wait_seconds=10)
    assert now[0] == 10
    assert not any("resume" in args or "cancel" in args for args in calls)


@pytest.mark.parametrize(
    "history",
    [
        {},
        [None],
        [{}],
        [execution(), execution()],
        [{"metadata": {"name": "other", "labels": {"run.googleapis.com/job": "other"}}}],
        [{**execution(), "status": {"completionTime": "not-a-date"}}],
        [{**execution(), "status": {"runningCount": True}}],
        [{**execution(), "status": {"completionTime": "2026-09-09T03:00:00"}}],
        [execution(str(i), done=True) for i in range(1001)],
    ],
)
def test_invalid_or_truncated_execution_inventory_never_proves_drain(history):
    with pytest.raises(guard.InventoryError):
        guard._unfinished_executions(history, job_name=JOB)


def test_failed_count_is_not_completion_and_completion_with_running_task_is_not_drain():
    failed = execution()
    failed["status"]["failedCount"] = 1
    assert guard._unfinished_executions([failed], job_name=JOB) == ["old-worker"]
    assert guard._unfinished_executions([execution(done=True, running=1)], job_name=JOB)
    assert guard._unfinished_executions([execution(done=True)], job_name=JOB) == []


def test_unknown_scheduler_rejected_before_cloud_mutation(monkeypatch):
    inventory, calls, _now = wire(monkeypatch, [])
    with pytest.raises(guard.InventoryError, match="canonical"):
        guard.quiesce(inventory, scheduler="invented", project="p", region="r")
    assert calls == []


@pytest.mark.parametrize("failure", [None, "before", "after", "transport"])
def test_resume_verifies_exact_runtime_and_repauses_on_post_resume_failure(monkeypatch, failure):
    inventory = guard.load_inventory(INVENTORY_PATH)
    original = copy.deepcopy(inventory)
    calls, states = [], []

    def inspect(selected, **kwargs):
        assert kwargs["expected_image"] == IMAGE
        assert len(selected["jobs"]) == 1
        assert selected["jobs"][0]["scheduler_name"] == SCHEDULER
        state = selected["jobs"][0]["desired_state"]
        states.append(state)
        if failure == "transport" and state == "ENABLED":
            raise guard.InventoryError("control-plane deadline")
        errors = (
            ["runtime drift"]
            if (failure, state) in {("before", "PAUSED"), ("after", "ENABLED")}
            else []
        )
        return errors, {"verified": state}

    monkeypatch.setattr(guard, "inspect_live", inspect)
    monkeypatch.setattr(guard, "run_gcloud", lambda args, **_kwargs: calls.append(args))
    if failure:
        with pytest.raises(guard.InventoryError):
            guard.resume_verified(
                inventory, scheduler=SCHEDULER, project="p", region="r", image=IMAGE
            )
    else:
        assert guard.resume_verified(
            inventory, scheduler=SCHEDULER, project="p", region="r", image=IMAGE
        ) == {"verified": "ENABLED"}
    assert states == (["PAUSED"] if failure == "before" else ["PAUSED", "ENABLED"])
    commands = [args[2] for args in calls]
    assert commands == (
        [] if failure == "before" else ["resume", "pause"] if failure else ["resume"]
    )
    assert inventory == original


def test_cloud_subprocess_timeout_is_bounded_and_not_resource_absence(monkeypatch):
    monkeypatch.setattr(guard.shutil, "which", lambda _name: "gcloud")

    def timeout(args, **kwargs):
        assert kwargs["timeout"] == 60
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(guard.subprocess, "run", timeout)
    with pytest.raises(guard.InventoryError, match="deadline"):
        guard.run_job_exists("job", project="p", region="r")


def test_release_orders_provider_drain_hold_and_resume():
    script = (guard.REPO_ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    assert script.index("scheduler_inventory.py quiesce") < script.index("# Step 2")
    assert (
        "SCHEDULER_HOLD_ARGS=(--hold-scheduler-paused caseops-case-tracking-poll-1800-ist)"
        in script
    )
    assert script.index("pre-provider-scheduler-resume gate") > script.index(
        "post-route pre-certification gate"
    )
    assert script.index("scheduler_inventory.py resume") < script.index(
        "gh workflow run prod-verify.yml"
    )
