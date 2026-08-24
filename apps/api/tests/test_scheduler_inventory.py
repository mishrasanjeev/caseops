from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "scheduler_inventory.py"
SPEC = importlib.util.spec_from_file_location("scheduler_inventory", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
scheduler_inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scheduler_inventory)
INVENTORY_PATH = REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json"


def test_checked_in_inventory_is_complete_and_valid() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)

    assert scheduler_inventory.validate_inventory(inventory) == []
    assert len(inventory["jobs"]) == 7
    assert {job["run_job_name"] for job in inventory["jobs"]} == {
        "caseops-legal-update-sync",
        "caseops-case-tracking-poll",
        "caseops-activity-report",
        "caseops-reminders-job",
        "caseops-extract-authority-metadata",
        "caseops-db-index-health",
        "caseops-ip-journal-watch",
    }
    authority_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-extract-authority-metadata"
    )
    assert authority_job["desired_state"] == "PAUSED"
    assert authority_job["task_timeout_seconds"] == 43_200
    assert all(
        job["desired_state"] == "ENABLED"
        for job in inventory["jobs"]
        if job is not authority_job
    )
    assert inventory["legacy_schedulers_to_pause"] == [
        "caseops-case-tracking-poll-midnight"
    ]


def test_inventory_rejects_duplicate_owners_and_mutable_image_policy() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    inventory["jobs"][1]["scheduler_name"] = inventory["jobs"][0]["scheduler_name"]
    inventory["jobs"][1]["image_policy"] = "mutable_tag"
    inventory["jobs"][1]["desired_state"] = "RUNNING"
    inventory["jobs"][1]["task_timeout_seconds"] = "43200"

    errors = scheduler_inventory.validate_inventory(inventory)

    assert any("duplicate scheduler_name" in error for error in errors)
    assert any("image_policy must be release_digest" in error for error in errors)
    assert any("desired_state must be ENABLED or PAUSED" in error for error in errors)
    assert any("task_timeout_seconds must be null or an integer" in error for error in errors)


def test_reconcile_converges_inventory_owned_timeout_and_scheduler_state(
    monkeypatch,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    authority_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-extract-authority-metadata"
    )
    enabled_job = inventory["jobs"][0]
    inventory["jobs"] = [enabled_job, authority_job]
    inventory["legacy_schedulers_to_pause"] = []
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64
    calls: list[list[str]] = []

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        calls.append(arguments)
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            assert expect_json
            return {
                "state": (
                    "ENABLED"
                    if arguments[3] == authority_job["scheduler_name"]
                    else "PAUSED"
                )
            }
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "scheduler_exists", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        scheduler_inventory,
        "inspect_live",
        lambda *_args, **_kwargs: ([], {"result": "pass"}),
    )

    scheduler_inventory.reconcile(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        image=expected_image,
    )

    update_calls = [call for call in calls if call[:3] == ["run", "jobs", "update"]]
    authority_update = next(
        call for call in update_calls if call[3] == "caseops-extract-authority-metadata"
    )
    enabled_update = next(
        call for call in update_calls if call[3] == enabled_job["run_job_name"]
    )
    assert authority_update[-2:] == ["--task-timeout", "43200s"]
    assert "--task-timeout" not in enabled_update
    assert [
        "scheduler",
        "jobs",
        "pause",
        authority_job["scheduler_name"],
    ] == next(call[:4] for call in calls if call[:3] == ["scheduler", "jobs", "pause"])
    assert [
        "scheduler",
        "jobs",
        "resume",
        enabled_job["scheduler_name"],
    ] == next(call[:4] for call in calls if call[:3] == ["scheduler", "jobs", "resume"])


@pytest.mark.parametrize(
    ("desired_state", "current_state", "expected_action"),
    [
        ("ENABLED", "ENABLED", None),
        ("PAUSED", "PAUSED", None),
        ("ENABLED", "PAUSED", "resume"),
        ("PAUSED", "ENABLED", "pause"),
    ],
)
def test_reconcile_transitions_scheduler_state_only_on_mismatch(
    monkeypatch,
    desired_state: str,
    current_state: str,
    expected_action: str | None,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    job = next(
        candidate
        for candidate in inventory["jobs"]
        if candidate["desired_state"] == desired_state
    )
    inventory["jobs"] = [job]
    inventory["legacy_schedulers_to_pause"] = []
    calls: list[list[str]] = []

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        calls.append(arguments)
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            assert expect_json
            return {"state": current_state}
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(
        scheduler_inventory,
        "scheduler_exists",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        scheduler_inventory,
        "inspect_live",
        lambda *_args, **_kwargs: ([], {"result": "pass"}),
    )

    scheduler_inventory.reconcile(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        image="registry.example/caseops-api@sha256:" + "b" * 64,
    )

    state_calls = [
        call
        for call in calls
        if call[:2] == ["scheduler", "jobs"] and call[2] in {"pause", "resume"}
    ]
    if expected_action is None:
        assert state_calls == []
    else:
        assert len(state_calls) == 1
        assert state_calls[0][:4] == [
            "scheduler",
            "jobs",
            expected_action,
            job["scheduler_name"],
        ]


def test_reconcile_requires_an_immutable_release_image() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)

    with pytest.raises(scheduler_inventory.InventoryError, match="immutable"):
        scheduler_inventory.reconcile(
            inventory,
            project=inventory["production_project"],
            region=inventory["location"],
            image="registry.example/caseops-api:latest",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows gcloud uses a .CMD shim")
def test_gcloud_runner_resolves_windows_command_shim(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(
        scheduler_inventory.shutil,
        "which",
        lambda _name: r"C:\Cloud SDK\bin\gcloud.CMD",
    )
    monkeypatch.setattr(
        scheduler_inventory.subprocess,
        "run",
        lambda arguments, **_kwargs: calls.append(arguments) or _Completed(),
    )

    assert scheduler_inventory.run_gcloud(["--version"]) == "ok"
    assert calls == [[r"C:\Cloud SDK\bin\gcloud.CMD", "--version"]]


def test_live_inspection_detects_identity_and_image_drift(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["jobs"] = [inventory["jobs"][0]]
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "ENABLED",
                "schedule": "0 0 * * *",
                "timeZone": "Asia/Kolkata",
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        "caseops-legal-update-sync",
                    ),
                    "oauthToken": {"serviceAccountEmail": "wrong@example.test"},
                },
            }
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {
                            "template": {
                                "spec": {"containers": [{"image": "registry/image:mutable"}]}
                            }
                        }
                    }
                }
            }
        return {"bindings": []}

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, summary = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
    )

    assert "caseops-legal-update-sync-midnight: identity drift" in errors
    assert "caseops-legal-update-sync-midnight: image drift" in errors
    assert "caseops-legal-update-sync-midnight: invoker_iam drift" in errors
    assert summary["result"] == "fail"


def test_live_inspection_detects_authority_state_and_timeout_drift(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    authority_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-extract-authority-metadata"
    )
    inventory["jobs"] = [authority_job]
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "ENABLED",
                "schedule": authority_job["schedule"],
                "timeZone": authority_job["time_zone"],
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        authority_job["run_job_name"],
                    ),
                    "oauthToken": {
                        "serviceAccountEmail": inventory["invoker_service_account"]
                    },
                },
            }
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [{"image": expected_image}],
                                    "timeoutSeconds": "86400s",
                                }
                            }
                        }
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [
                        f"serviceAccount:{inventory['invoker_service_account']}"
                    ],
                }
            ]
        }

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, summary = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
    )

    scheduler_name = authority_job["scheduler_name"]
    assert f"{scheduler_name}: state drift" in errors
    assert f"{scheduler_name}: task_timeout drift" in errors
    assert summary["jobs"][0]["desired_state"] == "PAUSED"
    assert summary["jobs"][0]["task_timeout_seconds"] == "86400"


def test_execution_summary_distinguishes_success_failure_and_missing() -> None:
    assert scheduler_inventory.summarize_execution([])["outcome"] == "missing"
    assert (
        scheduler_inventory.summarize_execution(
            [
                {
                    "metadata": {"name": "job-ok", "creationTimestamp": "2026-08-05T00:00:00Z"},
                    "status": {
                        "completionTime": "2026-08-05T00:01:00Z",
                        "conditions": [{"type": "Completed", "status": "True"}],
                        "succeededCount": 1,
                    },
                }
            ]
        )["outcome"]
        == "succeeded"
    )
    assert (
        scheduler_inventory.summarize_execution(
            [
                {
                    "metadata": {"name": "job-safe-stop"},
                    "status": {
                        "conditions": [{"type": "Completed", "status": "False"}],
                        "failedCount": 1,
                    },
                }
            ]
        )["outcome"]
        == "failed"
    )


def test_attempt_audit_requires_delivery_but_reports_workload_failure(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["jobs"] = [inventory["jobs"][0]]
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "ENABLED",
                "schedule": "0 0 * * *",
                "timeZone": "Asia/Kolkata",
                "lastAttemptTime": "",
                "status": {"code": 7, "message": "delivery rejected"},
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        "caseops-legal-update-sync",
                    ),
                    "oauthToken": {
                        "serviceAccountEmail": inventory["invoker_service_account"]
                    },
                },
            }
        if arguments[:4] == ["run", "jobs", "executions", "list"]:
            return [
                {
                    "metadata": {"name": "execution-failed"},
                    "status": {
                        "conditions": [{"type": "Completed", "status": "False"}],
                        "failedCount": 1,
                    },
                }
            ]
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {
                            "template": {
                                "spec": {"containers": [{"image": expected_image}]}
                            }
                        }
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [
                        f"serviceAccount:{inventory['invoker_service_account']}"
                    ],
                }
            ]
        }

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, summary = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
        audit_attempts=True,
    )

    assert "caseops-legal-update-sync-midnight: natural_or_canary_attempt drift" in errors
    assert "caseops-legal-update-sync-midnight: scheduler_delivery drift" in errors
    assert summary["jobs"][0]["latest_execution"]["outcome"] == "failed"


def test_attempt_audit_does_not_require_delivery_for_paused_scheduler(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    authority_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-extract-authority-metadata"
    )
    inventory["jobs"] = [authority_job]
    expected_image = "registry.example/caseops-api@sha256:" + "c" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "PAUSED",
                "schedule": authority_job["schedule"],
                "timeZone": authority_job["time_zone"],
                "lastAttemptTime": "",
                "status": {"code": -1, "message": "paused"},
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        authority_job["run_job_name"],
                    ),
                    "oauthToken": {
                        "serviceAccountEmail": inventory["invoker_service_account"]
                    },
                },
            }
        if arguments[:4] == ["run", "jobs", "executions", "list"]:
            return [
                {
                    "metadata": {"name": "authority-last-execution"},
                    "status": {
                        "conditions": [{"type": "Completed", "status": "False"}],
                        "failedCount": 1,
                    },
                }
            ]
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [{"image": expected_image}],
                                    "timeoutSeconds": "43200",
                                }
                            }
                        }
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [
                        f"serviceAccount:{inventory['invoker_service_account']}"
                    ],
                }
            ]
        }

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, summary = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
        audit_attempts=True,
    )

    assert errors == []
    job_summary = summary["jobs"][0]
    assert job_summary["scheduler_delivery"] == "not_required_paused"
    assert job_summary["latest_execution"]["name"] == "authority-last-execution"
    assert job_summary["latest_execution"]["outcome"] == "failed"
