from __future__ import annotations

import copy
import socket
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_scheduler_inventory import INVENTORY_PATH
from tests.test_scheduler_inventory import scheduler_inventory as guard

SCHEDULER = guard.PRIVATE_PROJECTION_SCHEDULER
JOB = "caseops-private-projection-maintenance"
SHA = "a" * 40
IMAGE = "registry.example/caseops-api@sha256:" + "b" * 64
SERVICE_TAG_IMAGE = "registry.example/caseops-api:release-tag"
API_REVISION = "caseops-api-test-revision"
RUN_ID = 12345
NAMES = (f"{JOB}-second", f"{JOB}-first", f"{JOB}-historical-blocked")
REQUIRED_JOBS = (
    "Resolve exact production release",
    "Prod Playwright (tester)",
    "Prod Playwright (legacy)",
    "Prod Playwright (supporting)",
    "Prod Playwright (patent-statute)",
    "Record exact-release evidence",
)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def evidence(monkeypatch):
    now = datetime.now(UTC)
    qa_end = now - timedelta(minutes=15)
    first_start = now - timedelta(minutes=12)
    first_end = now - timedelta(minutes=11)
    second_start = now - timedelta(minutes=10)
    second_end = now - timedelta(minutes=9)
    times = {
        NAMES[0]: (second_start, second_end),
        NAMES[1]: (first_start, first_end),
        NAMES[2]: (now - timedelta(minutes=20), now - timedelta(minutes=19)),
    }
    state = {
        "qa_end": qa_end,
        "active": False,
        "latest": True,
        "qa_sha": SHA,
        "qa_conclusion": "success",
        "release_log": (
            f"Record exact serving identity release_sha={SHA} api_revision={API_REVISION}"
        ),
        "service_image": SERVICE_TAG_IMAGE,
        "service_revision": API_REVISION,
        "service_traffic": [{
            "revisionName": API_REVISION, "percent": 100,
            "latestRevision": True,
        }],
        "revision_image": IMAGE,
        "latest_execution": NAMES[0],
        "missing_log": False,
        "active_on_second_check": False,
        "queued_checks": 0,
        "execution_images": {name: IMAGE for name in NAMES},
        "times": times,
        "records": {},
        "calls": [],
    }

    def report(name: str, rebuilds: int) -> dict:
        start, end = times[name]
        return {
            "mode": "maintain", "status": "ok", "severity": "INFO",
            "release_blocked": False, "event_lag_slo_seconds": 300,
            "candidate_scan_truncated": False, "candidate_company_count": 1,
            "rebuild_count": rebuilds,
            "started_at": stamp(start + timedelta(seconds=1)),
            "completed_at": stamp(end - timedelta(seconds=1)),
            "companies": [{
                "company_id": "qa-tenant", "rebuilt": bool(rebuilds),
                "pending_event_count_after": 0, "failed_event_count_after": 0,
                "repair_deferred": False, "repair_lag_slo_breached": False,
                "lag_slo_breached_before_recovery": False, "blockers_after": [],
                "oldest_pending_lag_seconds_before": 120,
                "oldest_repair_lag_seconds_after": None,
            }],
        }

    state["records"] = {NAMES[0]: report(NAMES[0], 0), NAMES[1]: report(NAMES[1], 1)}
    state["records"][NAMES[2]] = report(NAMES[2], 0)
    state["records"][NAMES[2]]["status"] = "blocked"
    state["records"][NAMES[2]]["release_blocked"] = True
    state["records"][NAMES[2]]["companies"][0]["oldest_repair_lag_seconds_after"] = 701
    state["records"][NAMES[2]]["companies"][0]["repair_lag_slo_breached"] = True
    inventory = guard.load_inventory(INVENTORY_PATH)
    private_job = next(row for row in inventory["jobs"] if row["scheduler_name"] == SCHEDULER)

    def fake_gh(arguments):
        state["calls"].append(("gh", arguments))
        if "--status" in arguments:
            if arguments[arguments.index("--status") + 1] == "queued":
                state["queued_checks"] += 1
                if state["active_on_second_check"] and state["queued_checks"] > 1:
                    state["active"] = True
            return [{"databaseId": 999}] if state["active"] else []
        if arguments[1] == "list":
            if not state["latest"]:
                return []
            return [{
                "databaseId": RUN_ID, "event": "workflow_dispatch",
                "headSha": state["qa_sha"], "status": "completed",
                "conclusion": state["qa_conclusion"],
            }]
        return {
            "databaseId": RUN_ID, "event": "workflow_dispatch",
            "headSha": state["qa_sha"], "status": "completed",
            "conclusion": state["qa_conclusion"],
            "workflowName": "Prod verification (Playwright)",
            "jobs": [{
                "name": name, "databaseId": index + 101,
                "conclusion": "success", "completedAt": stamp(state["qa_end"]),
            } for index, name in enumerate(REQUIRED_JOBS)],
        }

    def fake_gcloud(arguments, *, expect_json=False, timeout=60):
        state["calls"].append(("gcloud", arguments))
        if arguments[:3] == ["scheduler", "jobs", "resume"]:
            assert not expect_json
            return ""
        assert expect_json
        if arguments[:3] == ["run", "services", "describe"]:
            return {
                "spec": {"template": {"spec": {"containers": [
                    {"name": "api", "image": state["service_image"]}
                ]}}},
                "status": {
                    "latestReadyRevisionName": state["service_revision"],
                    "traffic": state["service_traffic"],
                },
            }
        if arguments[:3] == ["run", "revisions", "describe"]:
            assert arguments[3] == API_REVISION
            return {"spec": {"containers": [
                {"name": "api", "image": state["revision_image"]},
                {"name": "clamav", "image": "registry.example/clamav@sha256:" + "d" * 64},
            ]}}
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {"status": {"latestCreatedExecution": {"name": state["latest_execution"]}}}
        if arguments[:4] == ["run", "jobs", "executions", "list"]:
            assert "--sort-by=~metadata.creationTimestamp" in arguments
            assert "--limit=3" in arguments
            return [{"metadata": {
                "name": name, "creationTimestamp": stamp(state["times"][name][0]),
            }} for name in NAMES]
        if arguments[:4] == ["run", "jobs", "executions", "describe"]:
            name = arguments[4]
            start, end = state["times"][name]
            return {
                "metadata": {"name": name, "labels": {"run.googleapis.com/job": JOB}},
                "spec": {"taskCount": 1, "template": {"spec": {"containers": [{
                    "image": state["execution_images"][name],
                    "command": private_job["bootstrap"]["command"],
                    "args": private_job["bootstrap"]["args"],
                }]}}},
                "status": {
                    "startTime": stamp(start), "completionTime": stamp(end),
                    "succeededCount": 1, "failedCount": 0,
                    "conditions": [{"type": "Completed", "status": "True"}],
                },
            }
        if arguments[:2] == ["logging", "read"]:
            if state["missing_log"]:
                return []
            name = next(name for name in NAMES if f'execution_name"="{name}"' in arguments[2])
            record = state["records"][name]
            return [{
                "resource": {"type": "cloud_run_job", "labels": {"job_name": JOB}},
                "labels": {"run.googleapis.com/execution_name": name},
                "textPayload": "CASEOPS_PRIVATE_PROJECTION " + guard.json.dumps(record),
            }]
        raise AssertionError(arguments)

    monkeypatch.setattr(guard, "_run_gh", fake_gh)
    monkeypatch.setattr(guard, "_run_gh_text", lambda _args: state["release_log"])
    monkeypatch.setattr(guard, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(
        guard, "inspect_live", lambda selected, **_kwargs: (
            [], {"result": "pass", "state": selected["jobs"][0]["desired_state"]}
        ),
    )
    monkeypatch.setattr(
        guard.urllib_request, "urlopen",
        lambda *_args, **_kwargs: pytest.fail("network access is forbidden"),
    )
    monkeypatch.setattr(
        socket, "create_connection",
        lambda *_args, **_kwargs: pytest.fail("network access is forbidden"),
    )
    return inventory, state


def resume(inventory):
    return guard.resume_verified(
        inventory, scheduler=SCHEDULER,
        project=inventory["production_project"], region=inventory["location"],
        image=IMAGE, release_sha=SHA, qa_run_id=RUN_ID,
    )


def assert_no_resume(state):
    assert not any(
        args[:3] == ["scheduler", "jobs", "resume"]
        for kind, args in state["calls"] if kind == "gcloud"
    )


def test_private_resume_accepts_two_later_serial_clean_runs_after_historical_breach(monkeypatch):
    inventory, state = evidence(monkeypatch)
    original = copy.deepcopy(inventory)

    result = resume(inventory)

    assert result["state"] == "ENABLED"
    assert result["private_resume_evidence"]["maintenance_executions"] == [
        NAMES[1], NAMES[0]
    ]
    assert result["private_resume_evidence"]["rebuild_counts"] == [1, 0]
    assert state["records"][NAMES[2]]["companies"][0]["oldest_repair_lag_seconds_after"] == 701
    assert sum(
        args[:3] == ["scheduler", "jobs", "resume"]
        for kind, args in state["calls"] if kind == "gcloud"
    ) == 1
    assert inventory == original


def test_mutable_service_template_tag_does_not_override_revision_digest(monkeypatch):
    inventory, state = evidence(monkeypatch)
    assert state["service_image"] == SERVICE_TAG_IMAGE
    assert state["revision_image"] == IMAGE

    assert resume(inventory)["private_resume_evidence"]["qa_api_revision"] == API_REVISION


def test_long_qa_delay_needs_fresh_post_qa_maintenance_not_a_new_dispatch(monkeypatch):
    inventory, state = evidence(monkeypatch)
    state["qa_end"] = datetime.now(UTC) - timedelta(hours=8)

    result = resume(inventory)

    assert result["private_resume_evidence"]["qa_run_id"] == RUN_ID
    assert result["private_resume_evidence"]["rebuild_counts"] == [1, 0]


@pytest.mark.parametrize("failure", [
    "missing_qa", "unavailable_qa", "future_qa", "active_qa", "wrong_qa_sha",
    "failed_qa", "wrong_recorded_sha",
    "wrong_qa_revision_image", "changed_api_revision",
    "missing_traffic", "split_traffic", "partial_traffic", "tagged_traffic",
    "wrong_execution_image", "blockers", "deferred", "slo_breach",
    "prior_slo_breach", "second_rebuild", "overlap", "missing_log",
    "stale_execution_list", "active_after_maintenance",
])
def test_private_resume_fails_closed_on_unverified_evidence(monkeypatch, failure):
    inventory, state = evidence(monkeypatch)
    if failure == "missing_qa":
        state["latest"] = False
    elif failure == "unavailable_qa":
        monkeypatch.setattr(guard, "_run_gh", lambda _args: (_ for _ in ()).throw(
            guard.InventoryError("GitHub unavailable")
        ))
    elif failure == "future_qa":
        state["qa_end"] = datetime.now(UTC) + timedelta(minutes=1)
    elif failure == "active_qa":
        state["active"] = True
    elif failure == "wrong_qa_sha":
        state["qa_sha"] = "c" * 40
    elif failure == "failed_qa":
        state["qa_conclusion"] = "failure"
    elif failure == "wrong_recorded_sha":
        state["release_log"] = "release_sha=" + "c" * 40
    elif failure == "wrong_qa_revision_image":
        state["revision_image"] = "registry.example/api@sha256:" + "c" * 64
    elif failure == "changed_api_revision":
        state["service_revision"] = "caseops-api-newer-revision"
    elif failure == "missing_traffic":
        state["service_traffic"] = []
    elif failure == "split_traffic":
        state["service_traffic"].append({
            "revisionName": "caseops-api-older-revision", "percent": 0,
        })
    elif failure == "partial_traffic":
        state["service_traffic"][0]["percent"] = 99
    elif failure == "tagged_traffic":
        state["service_traffic"][0]["tag"] = "qa-tag"
    elif failure == "wrong_execution_image":
        state["execution_images"][NAMES[0]] = "registry.example/api@sha256:" + "c" * 64
    elif failure == "blockers":
        state["records"][NAMES[1]]["companies"][0]["blockers_after"] = [
            "active_generation_manifest_mismatch"
        ]
    elif failure == "deferred":
        state["records"][NAMES[1]]["companies"][0]["repair_deferred"] = True
    elif failure == "slo_breach":
        state["records"][NAMES[0]]["companies"][0]["repair_lag_slo_breached"] = True
    elif failure == "prior_slo_breach":
        state["records"][NAMES[1]]["companies"][0]["lag_slo_breached_before_recovery"] = True
    elif failure == "second_rebuild":
        state["records"][NAMES[0]]["rebuild_count"] = 1
        state["records"][NAMES[0]]["companies"][0]["rebuilt"] = True
    elif failure == "overlap":
        state["times"][NAMES[1]] = (
            state["times"][NAMES[1]][0], state["times"][NAMES[0]][0] + timedelta(seconds=1)
        )
    elif failure == "missing_log":
        state["missing_log"] = True
    elif failure == "stale_execution_list":
        state["latest_execution"] = NAMES[1]
    elif failure == "active_after_maintenance":
        state["active_on_second_check"] = True

    with pytest.raises(guard.InventoryError):
        resume(inventory)
    assert_no_resume(state)


def test_private_resume_requires_qa_arguments_but_paid_resume_does_not(monkeypatch):
    inventory, state = evidence(monkeypatch)
    with pytest.raises(guard.InventoryError, match="exact release SHA"):
        guard.resume_verified(
            inventory, scheduler=SCHEDULER,
            project=inventory["production_project"], region=inventory["location"],
            image=IMAGE,
        )
    assert_no_resume(state)
    state["calls"].clear()
    result = guard.resume_verified(
        inventory, scheduler="caseops-case-tracking-poll-1800-ist",
        project=inventory["production_project"], region=inventory["location"],
        image=IMAGE,
    )
    assert result["state"] == "ENABLED"
    assert not any(kind == "gh" for kind, _args in state["calls"])


def test_resume_cli_requires_evidence_and_accepts_verified_ids(monkeypatch, capsys):
    inventory, state = evidence(monkeypatch)
    common = [
        "resume", "--scheduler", SCHEDULER,
        "--project", inventory["production_project"],
        "--region", inventory["location"], "--image", IMAGE,
    ]
    assert guard.main(common) == 1
    assert_no_resume(state)
    assert "requires --release-sha and --qa-run-id" in capsys.readouterr().err

    assert guard.main([
        *common, "--release-sha", SHA, "--qa-run-id", str(RUN_ID),
    ]) == 0
    summary = guard.json.loads(capsys.readouterr().out)
    assert summary["private_resume_evidence"]["qa_run_id"] == RUN_ID


def test_reconcile_cannot_resume_private_cadence_without_evidence(monkeypatch):
    inventory, state = evidence(monkeypatch)
    inventory["jobs"] = [
        next(row for row in inventory["jobs"] if row["scheduler_name"] == SCHEDULER)
    ]
    inventory["legacy_schedulers_to_pause"] = []
    monkeypatch.setattr(guard, "run_job_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(guard, "scheduler_exists", lambda *_args, **_kwargs: True)

    original_gcloud = guard.run_gcloud

    def fake_gcloud(arguments, *, expect_json=False, timeout=60):
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            state["calls"].append(("gcloud", arguments))
            return {"state": "PAUSED"}
        if arguments[:3] == ["run", "jobs", "update"] or arguments[:4] == [
            "run", "jobs", "add-iam-policy-binding", JOB
        ] or arguments[:4] == ["scheduler", "jobs", "update", "http"]:
            state["calls"].append(("gcloud", arguments))
            return ""
        return original_gcloud(arguments, expect_json=expect_json, timeout=timeout)

    monkeypatch.setattr(guard, "run_gcloud", fake_gcloud)
    with pytest.raises(guard.InventoryError, match="evidence-checked resume"):
        guard.reconcile(
            inventory, project=inventory["production_project"],
            region=inventory["location"], image=IMAGE,
        )
    assert_no_resume(state)
    assert not any(
        args[:3] == ["run", "jobs", "update"]
        for kind, args in state["calls"] if kind == "gcloud"
    )


def test_gh_cli_evidence_transport_is_bounded_and_fails_closed(monkeypatch):
    calls = []
    monkeypatch.setattr(guard.shutil, "which", lambda _name: "fake-gh")

    def fake_cli(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, '[{"databaseId":12345}]', "")

    monkeypatch.setattr(guard.subprocess, "run", fake_cli)
    assert guard._run_gh(["run", "list"]) == [{"databaseId": 12345}]
    assert calls == [
        (["fake-gh", "run", "list"], {
            "check": False, "capture_output": True, "text": True,
            "encoding": "utf-8", "timeout": 30,
        })
    ]

    monkeypatch.setattr(
        guard.subprocess, "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 1, "", "offline"),
    )
    with pytest.raises(guard.InventoryError, match="unavailable"):
        guard._run_gh(["run", "list"])
