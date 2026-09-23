from __future__ import annotations

import copy
import json
import subprocess
from urllib import parse as urllib_parse

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
        if arguments == ["auth", "print-access-token"]:
            return "test-access-token"
        if arguments[:3] == ["scheduler", "jobs", "pause"]:
            return ""
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "PAUSED",
                "httpTarget": {"uri": guard.scheduler_uri("p", "r", JOB)},
            }
        raise AssertionError(arguments)

    def list_executions(**kwargs):
        calls.append(["run-api", "executions", "list", kwargs["job_name"]])
        assert kwargs == {
            "job_name": JOB,
            "project": "p",
            "region": "r",
            "access_token": "test-access-token",
            "timeout": kwargs["timeout"],
        }
        assert 0 < kwargs["timeout"] <= 180
        return next(histories)

    monkeypatch.setattr(guard, "run_gcloud", gcloud)
    monkeypatch.setattr(guard, "_list_job_executions_v2", list_executions)
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
    assert calls[0] == ["auth", "print-access-token"]
    assert calls[1][:4] == ["scheduler", "jobs", "pause", SCHEDULER]
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
        [
            execution(str(i), done=True)
            for i in range(guard.EXECUTION_DRAIN_SCAN_SENTINEL)
        ],
    ],
)
def test_invalid_or_truncated_execution_inventory_never_proves_drain(history):
    with pytest.raises(guard.InventoryError):
        guard._unfinished_executions(history, job_name=JOB)


def test_observed_production_execution_history_stays_below_drain_sentinel():
    retained = [execution(str(i), done=True) for i in range(1768)]

    assert guard._unfinished_executions(retained, job_name=JOB) == []


def test_execution_api_pages_complete_inventory_without_gcloud_history_scan(
    monkeypatch,
):
    requested_urls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def execution_v2(name, *, done):
        payload = {
            "name": f"projects/p/locations/r/jobs/{JOB}/executions/{name}",
            "job": JOB,
            "createTime": "2026-09-23T00:00:00Z",
        }
        if done:
            payload["completionTime"] = "2026-09-23T00:01:00Z"
        else:
            payload["runningCount"] = 1
        return payload

    def urlopen(request, *, timeout):
        requested_urls.append(request.full_url)
        assert request.get_header("Authorization") == "Bearer token"
        assert 0 < timeout <= 30
        query = urllib_parse.parse_qs(urllib_parse.urlparse(request.full_url).query)
        if "pageToken" not in query:
            return Response(
                {
                    "executions": [execution_v2("new", done=True)],
                    "nextPageToken": "next-token",
                }
            )
        assert query["pageToken"] == ["next-token"]
        return Response({"executions": [execution_v2("old", done=False)]})

    monkeypatch.setattr(guard.urllib_request, "urlopen", urlopen)
    rows = guard._list_job_executions_v2(
        job_name=JOB,
        project="p",
        region="r",
        access_token="token",
        timeout=30,
    )

    assert guard._unfinished_executions(rows, job_name=JOB) == ["old"]
    assert len(requested_urls) == 2
    first_query = urllib_parse.parse_qs(urllib_parse.urlparse(requested_urls[0]).query)
    assert first_query["pageSize"] == [str(guard.EXECUTION_API_PAGE_SIZE)]
    assert "nextPageToken" in first_query["fields"][0]


def test_execution_api_rejects_repeated_page_token(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"executions": [], "nextPageToken": "repeat"}'

    monkeypatch.setattr(
        guard.urllib_request,
        "urlopen",
        lambda _request, *, timeout: Response(),
    )
    with pytest.raises(guard.InventoryError, match="page token"):
        guard._list_job_executions_v2(
            job_name=JOB,
            project="p",
            region="r",
            access_token="token",
            timeout=30,
        )


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
