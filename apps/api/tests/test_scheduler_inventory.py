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
    assert len(inventory["jobs"]) == 11
    document_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-document-processing"
    )
    assert document_job["schedule"] == "* * * * *"
    assert document_job["task_timeout_seconds"] == 600
    assert document_job["bootstrap"]["command"] == ["caseops-document-worker"]
    assert document_job["bootstrap"]["args"] == [
        "--documents-only",
        "--once",
        "--batch-size=5",
        "--skip-migrations",
    ]
    assert document_job["bootstrap"]["max_retries"] == 0
    assert document_job["additional_invoker_service_accounts"] == [
        "caseops-runtime@perfect-period-305406.iam.gserviceaccount.com"
    ]
    assert {job["run_job_name"] for job in inventory["jobs"]} == {
        "caseops-legal-update-sync",
        "caseops-case-tracking-poll",
        "caseops-activity-report",
        "caseops-reminders-job",
        "caseops-private-projection-maintenance",
        "caseops-extract-authority-metadata",
        "caseops-db-index-health",
        "caseops-ip-journal-watch",
        "caseops-judge-mapping-refresh",
        "caseops-document-processing",
        "caseops-court-sync",
    }
    authority_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-extract-authority-metadata"
    )
    assert authority_job["desired_state"] == "PAUSED"
    assert authority_job["task_timeout_seconds"] == 43_200
    watch_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-ip-journal-watch"
    )
    assert watch_job["bootstrap"]["command"] == ["caseops-ip-journal-watch"]
    assert watch_job["bootstrap"]["args"] == []
    index_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-db-index-health"
    )
    assert index_job["task_timeout_seconds"] == 600
    assert index_job["bootstrap"]["command"] == ["caseops-db-index-health"]
    assert index_job["bootstrap"]["args"] == []
    assert index_job["bootstrap"]["max_retries"] == 0
    reminders_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-reminders-job"
    )
    assert reminders_job["bootstrap"]["max_retries"] == 0
    private_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-private-projection-maintenance"
    )
    assert private_job["schedule"] == "*/5 * * * *"
    assert private_job["task_timeout_seconds"] == 900
    assert private_job["bootstrap"]["command"] == ["caseops-private-projection-maintenance"]
    assert private_job["bootstrap"]["memory"] == "4Gi"
    assert private_job["bootstrap"]["max_retries"] == 0
    assert private_job["retry"] == {
        "max_retry_attempts": 5,
        "max_retry_duration_seconds": 900,
        "min_backoff_seconds": 10,
        "max_backoff_seconds": 300,
        "max_doublings": 5,
    }
    mapping_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-judge-mapping-refresh"
    )
    assert mapping_job["schedule"] == "15 1 * * *"
    assert mapping_job["time_zone"] == "Asia/Kolkata"
    assert mapping_job["desired_state"] == "PAUSED"
    assert mapping_job["task_timeout_seconds"] == 3_600
    assert mapping_job["image_policy"] == "release_digest"
    assert mapping_job["canary_policy"] == "manual_safe"
    assert mapping_job["bootstrap"]["command"] == ["caseops-refresh-bench-analysis-layers"]
    assert mapping_job["bootstrap"]["args"] == []
    assert all(job.get("bootstrap") for job in inventory["jobs"])
    assert all(
        job["bootstrap"]["command"][0].casefold() not in {"uv", "uvx"} for job in inventory["jobs"]
    )
    assert all(
        job["desired_state"] == "ENABLED"
        for job in inventory["jobs"]
        if job not in (authority_job, mapping_job)
    )
    assert inventory["legacy_schedulers_to_pause"] == [
        "caseops-case-tracking-poll-midnight",
        "caseops-case-tracking-poll-1630-ist",
    ]
    tracking_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-case-tracking-poll"
    )
    assert (
        tracking_job["bootstrap"]["environment"]["CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS"]
        == "caseops-qa;caseops-ip-qa;test-legal"
    )
    assert tracking_job["scheduler_name"] == "caseops-case-tracking-poll-1800-ist"
    assert tracking_job["schedule"] == "*/5 18-19 * * *"
    assert tracking_job["time_zone"] == "Asia/Kolkata"
    environment = tracking_job["bootstrap"]["environment"]
    assert environment["CASEOPS_CASE_TRACKING_DAILY_WINDOW_START"] == "18:00"
    assert environment["CASEOPS_CASE_TRACKING_DAILY_WINDOW_END"] == "20:00"


def test_release_hold_pauses_only_the_named_effective_scheduler() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    scheduler_name = "caseops-private-projection-maintenance-cadence"

    effective = scheduler_inventory.hold_schedulers_paused(
        inventory,
        [scheduler_name],
    )

    canonical_job = next(
        job for job in inventory["jobs"] if job["scheduler_name"] == scheduler_name
    )
    effective_job = next(
        job for job in effective["jobs"] if job["scheduler_name"] == scheduler_name
    )
    assert canonical_job["desired_state"] == "ENABLED"
    assert effective_job["desired_state"] == "PAUSED"
    assert sum(job["desired_state"] == "PAUSED" for job in effective["jobs"]) == 3


def test_release_hold_rejects_an_unknown_scheduler() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)

    with pytest.raises(scheduler_inventory.InventoryError, match="unknown scheduler"):
        scheduler_inventory.hold_schedulers_paused(
            inventory,
            ["invented-private-projection-scheduler"],
        )


@pytest.mark.parametrize("job_name, admission_key, protocol_key", [
    ("caseops-document-processing", "CASEOPS_DOCUMENT_WORKER_ADMISSION_ENABLED",
     "CASEOPS_DOCUMENT_WORKER_ADMISSION_PROTOCOL_VERSION"),
    ("caseops-court-sync", "CASEOPS_COURT_SYNC_WORKER_ADMISSION_ENABLED",
     "CASEOPS_COURT_SYNC_WORKER_ADMISSION_PROTOCOL_VERSION"),
])
def test_execution_release_hold_disables_only_its_worker_admission(
    job_name, admission_key, protocol_key,
) -> None:
    canonical = scheduler_inventory.load_inventory(INVENTORY_PATH)
    held = scheduler_inventory.hold_schedulers_paused(
        canonical,
        [job_name + "-cadence"],
    )
    original = next(
        job for job in canonical["jobs"] if job["run_job_name"] == job_name
    )
    effective = next(
        job for job in held["jobs"] if job["run_job_name"] == job_name
    )
    assert (
        original["bootstrap"]["environment"][admission_key] == "true"
    )
    assert (
        effective["bootstrap"]["environment"][admission_key]
        == "false"
    )
    assert (
        effective["bootstrap"]["environment"][protocol_key]
        == "1"
    )
    assert effective["desired_state"] == "PAUSED" and original["desired_state"] == "ENABLED"
    assert [job for job in held["jobs"] if job["run_job_name"] != job_name] == [
        job for job in canonical["jobs"] if job["run_job_name"] != job_name
    ]


def test_court_worker_contract_is_bounded_and_contains_no_court_provider_secrets() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    job = next(row for row in inventory["jobs"] if row["run_job_name"] == "caseops-court-sync")
    assert job["schedule"] == "* * * * *" and job["task_timeout_seconds"] == 600
    assert job["bootstrap"]["command"] == ["caseops-court-sync-worker"]
    assert job["bootstrap"]["args"] == ["--once", "--batch-size=3", "--skip-migrations"]
    assert job["bootstrap"]["max_retries"] == 0
    assert job["bootstrap"]["environment"]["CASEOPS_COURT_SYNC_STALE_AFTER_MINUTES"] == "15"
    assert set(job["bootstrap"]["secrets"]) == {
        "CASEOPS_DATABASE_URL", "CASEOPS_AUTH_SECRET", "CASEOPS_LLM_API_KEY",
    }


@pytest.mark.parametrize("job_name", ["caseops-document-processing", "caseops-court-sync"])
def test_independent_worker_configuration_preserves_api_provider_and_transaction_policy(
    job_name,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    job = next(row for row in inventory["jobs"] if row["run_job_name"] == job_name)
    environment = job["bootstrap"]["environment"]
    assert environment["CASEOPS_LLM_PROVIDER"] == "openai"
    assert environment["CASEOPS_LLM_MODEL"] == "gpt-5.1"
    assert environment["CASEOPS_COMPLIANCE_AI_EXTRACTION_ENABLED"] == "false"
    assert environment["CASEOPS_COMPLIANCE_AI_EXTRACTION_AUTO_RUN_ENABLED"] == "false"
    assert environment["CASEOPS_DB_STATEMENT_TIMEOUT_MS"] == "60000"
    assert environment["CASEOPS_DB_LOCK_TIMEOUT_MS"] == "5000"
    assert environment["CASEOPS_DB_IDLE_TRANSACTION_TIMEOUT_MS"] == "60000"
    assert job["bootstrap"]["secrets"]["CASEOPS_LLM_API_KEY"] == "caseops-openai-api-key:latest"
    assert environment["CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS"] == (
        "caseops-qa;caseops-ip-qa;test-legal"
    )


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


def test_inventory_rejects_unsafe_or_incomplete_bootstrap_contract() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    watch_job = inventory["jobs"][-1]
    watch_job["bootstrap"]["command"] = []
    watch_job["bootstrap"]["args"] = ["contains,comma"]
    watch_job["bootstrap"]["environment"]["UNSAFE"] = "one,two"
    watch_job["bootstrap"]["max_retries"] = 11

    errors = scheduler_inventory.validate_inventory(inventory)

    assert any("bootstrap.command" in error for error in errors)
    assert any("bootstrap.args" in error for error in errors)
    assert any("bootstrap.environment" in error for error in errors)
    assert any("bootstrap.max_retries" in error for error in errors)


def test_inventory_rejects_runtime_dependency_resolution_and_missing_contract() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    inventory["jobs"][0]["bootstrap"]["command"] = ["uv"]
    inventory["jobs"][0]["bootstrap"]["args"] = [
        "run",
        "caseops-sync-legal-updates",
    ]
    inventory["jobs"][1].pop("bootstrap")

    errors = scheduler_inventory.validate_inventory(inventory)

    assert any("uv/uvx job startup is forbidden" in error for error in errors)
    assert any("bootstrap is required" in error for error in errors)


def test_inventory_rejects_invalid_scheduler_retry_contract() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    private_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-private-projection-maintenance"
    )
    private_job["retry"]["max_retry_attempts"] = 6
    private_job["retry"]["min_backoff_seconds"] = 301
    private_job["retry"]["max_backoff_seconds"] = 300

    errors = scheduler_inventory.validate_inventory(inventory)

    assert any("max_retry_attempts must be at most 5" in error for error in errors)
    assert any("max_backoff_seconds must be at least" in error for error in errors)


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
                    "ENABLED" if arguments[3] == authority_job["scheduler_name"] else "PAUSED"
                )
            }
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: True)
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
    enabled_update = next(call for call in update_calls if call[3] == enabled_job["run_job_name"])
    assert authority_update[-2:] == ["--task-timeout", "43200s"]
    assert enabled_update[enabled_update.index("--task-timeout") + 1] == "1800s"
    assert (
        "--args=-m,caseops_api.scripts.extract_authority_metadata,--concurrency,8"
    ) in authority_update
    assert "--args" not in authority_update
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


def test_reconcile_converges_private_scheduler_retry_contract(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    private_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-private-projection-maintenance"
    )
    inventory["jobs"] = [private_job]
    inventory["legacy_schedulers_to_pause"] = []
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64
    calls: list[list[str]] = []

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        calls.append(arguments)
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            assert expect_json
            return {"state": "ENABLED"}
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: True)
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

    update = next(
        call
        for call in calls
        if call[:4]
        == [
            "scheduler",
            "jobs",
            "update",
            "http",
        ]
    )
    assert update[update.index("--max-retry-attempts") + 1] == "5"
    assert update[update.index("--max-retry-duration") + 1] == "900s"
    assert update[update.index("--min-backoff") + 1] == "10s"
    assert update[update.index("--max-backoff") + 1] == "300s"
    assert update[update.index("--max-doublings") + 1] == "5"


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
        candidate for candidate in inventory["jobs"] if candidate["desired_state"] == desired_state
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
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: True)
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


def test_reconcile_bootstraps_a_missing_declared_run_job(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    watch_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-ip-journal-watch"
    )
    inventory["jobs"] = [watch_job]
    inventory["legacy_schedulers_to_pause"] = []
    expected_image = "registry.example/caseops-api@sha256:" + "c" * 64
    calls: list[list[str]] = []

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        calls.append(arguments)
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            assert expect_json
            return {"state": "ENABLED"}
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        scheduler_inventory,
        "scheduler_exists",
        lambda *_args, **_kwargs: False,
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
        image=expected_image,
    )

    create = next(call for call in calls if call[:3] == ["run", "jobs", "create"])
    assert create[3] == "caseops-ip-journal-watch"
    assert create[create.index("--image") + 1] == expected_image
    assert create[create.index("--command") + 1] == "caseops-ip-journal-watch"
    assert "--args=" in create
    assert create[create.index("--task-timeout") + 1] == "900s"
    assert create[create.index("--max-retries") + 1] == "1"
    assert (
        "CASEOPS_DATABASE_URL=caseops-database-url:latest"
        in create[create.index("--set-secrets") + 1]
    )


def test_reconcile_converges_an_existing_bootstrap_contract(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    watch_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-ip-journal-watch"
    )
    inventory["jobs"] = [watch_job]
    inventory["legacy_schedulers_to_pause"] = []
    calls: list[list[str]] = []

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        calls.append(arguments)
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            assert expect_json
            return {"state": "ENABLED"}
        return ""

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: True)
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
        image="registry.example/caseops-api@sha256:" + "e" * 64,
    )

    update = next(call for call in calls if call[:3] == ["run", "jobs", "update"])
    assert update[3] == "caseops-ip-journal-watch"
    assert "--set-env-vars" in update
    assert "--set-secrets" in update
    assert "--set-cloudsql-instances" in update


def test_bootstrap_arguments_bind_leading_dash_values_to_gcloud_args_flag() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    reminders_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-reminders-job"
    )

    arguments = scheduler_inventory._bootstrap_arguments(
        reminders_job,
        action="update",
        project=inventory["production_project"],
        region=inventory["location"],
        image="registry.example/caseops-api@sha256:" + "f" * 64,
    )

    assert "--args=--mode=auto,--limit=200" in arguments
    assert "--args" not in arguments
    assert "--mode=auto,--limit=200" not in arguments


def test_reconcile_fails_closed_when_a_missing_job_has_no_bootstrap(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    job = inventory["jobs"][0]
    job.pop("bootstrap")
    inventory["jobs"] = [job]
    inventory["legacy_schedulers_to_pause"] = []
    calls: list[list[str]] = []
    monkeypatch.setattr(
        scheduler_inventory,
        "run_gcloud",
        lambda arguments, **_kwargs: calls.append(arguments) or "",
    )
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: False)

    with pytest.raises(scheduler_inventory.InventoryError, match="bootstrap contract"):
        scheduler_inventory.reconcile(
            inventory,
            project=inventory["production_project"],
            region=inventory["location"],
            image="registry.example/caseops-api@sha256:" + "d" * 64,
        )

    assert calls == []


class _GcloudResult:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _reconcile_through_exit_codes(
    monkeypatch,
    inventory: dict,
    calls: list[list[str]],
    *,
    failing_invoker_job: str | None = None,
) -> None:
    """Drive reconcile through run_gcloud's real exit-code handling."""
    desired_state = {job["scheduler_name"]: job["desired_state"] for job in inventory["jobs"]}

    def fake_invoke(arguments: list[str], *, timeout: float = 60) -> _GcloudResult:
        calls.append(arguments)
        if arguments[:4] == ["run", "jobs", "add-iam-policy-binding", failing_invoker_job]:
            return _GcloudResult(1, stderr="PERMISSION_DENIED: invoker grant refused")
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return _GcloudResult(stdout=json.dumps({"state": desired_state[arguments[3]]}))
        return _GcloudResult()

    monkeypatch.setattr(scheduler_inventory, "_invoke_gcloud", fake_invoke)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *_args, **_kwargs: True)
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
        image="registry.example/caseops-api@sha256:" + "9" * 64,
    )


def test_reconcile_grants_each_job_invoker_before_its_scheduler(monkeypatch) -> None:
    # The inventory reconciler is the only scheduler/IAM writer; the retired
    # infra/cloudrun/deploy.ps1 path used to carry this ordering as well.
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["legacy_schedulers_to_pause"] = []
    member = f"serviceAccount:{inventory['invoker_service_account']}"
    calls: list[list[str]] = []

    _reconcile_through_exit_codes(monkeypatch, inventory, calls)

    assert len(inventory["jobs"]) == 11
    for job in inventory["jobs"]:
        run_job = job["run_job_name"]
        job_write = next(
            index
            for index, call in enumerate(calls)
            if call[:2] == ["run", "jobs"]
            and call[2] in {"create", "update"}
            and call[3] == run_job
        )
        grant = calls.index(
            [
                "run",
                "jobs",
                "add-iam-policy-binding",
                run_job,
                "--member",
                member,
                "--role",
                "roles/run.invoker",
                "--region",
                inventory["location"],
                "--project",
                inventory["production_project"],
                "--quiet",
            ]
        )
        scheduler_write = next(
            index
            for index, call in enumerate(calls)
            if call[:2] == ["scheduler", "jobs"]
            and call[2] in {"create", "update"}
            and call[3:5] == ["http", job["scheduler_name"]]
        )
        assert job_write < grant < scheduler_write, run_job
        for account in job.get("additional_invoker_service_accounts", []):
            extra_grant = next(
                index
                for index, call in enumerate(calls)
                if call[:4] == ["run", "jobs", "add-iam-policy-binding", run_job]
                and call[call.index("--member") + 1] == f"serviceAccount:{account}"
            )
            assert job_write < extra_grant < scheduler_write


def test_reconcile_stops_before_any_scheduler_write_when_an_invoker_grant_fails(
    monkeypatch,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["legacy_schedulers_to_pause"] = []
    first_job = inventory["jobs"][0]["run_job_name"]
    calls: list[list[str]] = []

    with pytest.raises(scheduler_inventory.InventoryError, match="PERMISSION_DENIED"):
        _reconcile_through_exit_codes(
            monkeypatch, inventory, calls, failing_invoker_job=first_job
        )

    assert calls[-1][:4] == ["run", "jobs", "add-iam-policy-binding", first_job]
    assert [
        call[3]
        for call in calls
        if call[:2] == ["run", "jobs"] and call[2] in {"create", "update"}
    ] == [first_job]
    assert not any(
        call[:2] == ["scheduler", "jobs"] and call[2] in {"create", "update", "pause", "resume"}
        for call in calls
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


@pytest.mark.parametrize("allow_missing", [False, True])
def test_quiesce_allows_slow_control_plane_calls_without_skipping_drain(
    monkeypatch,
    allow_missing,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    scheduler = "caseops-case-tracking-poll-1800-ist"
    job_name = "caseops-case-tracking-poll"
    calls: list[tuple[list[str], float]] = []
    scans: list[dict] = []

    def fake_gcloud(arguments, *, expect_json=False, timeout=60):
        calls.append((arguments, timeout))
        if arguments[:2] == ["auth", "print-access-token"]:
            return "test-token"
        if arguments[:3] == ["scheduler", "jobs", "pause"]:
            return ""
        assert expect_json and arguments[:3] == ["scheduler", "jobs", "describe"]
        return {
            "state": "PAUSED",
            "httpTarget": {
                "uri": scheduler_inventory.scheduler_uri(
                    inventory["production_project"], inventory["location"], job_name
                )
            },
        }

    def fake_executions(**kwargs):
        scans.append(kwargs)
        return []

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    monkeypatch.setattr(scheduler_inventory, "_list_job_executions_v2", fake_executions)
    monkeypatch.setattr(scheduler_inventory, "scheduler_exists", lambda *a, **k: True)
    monkeypatch.setattr(scheduler_inventory.time, "sleep", lambda _seconds: None)

    result = scheduler_inventory.quiesce(
        inventory,
        scheduler=scheduler,
        project=inventory["production_project"],
        region=inventory["location"],
        wait_seconds=300,
        allow_missing=allow_missing,
    )

    assert result["state"] == "PAUSED"
    assert result["clean_samples"] == 2
    assert result["drained"] is True
    assert len(scans) == 2
    assert len(calls) == 4  # token, pause, and two verified state samples
    assert all(timeout == 90 for _, timeout in calls)


@pytest.mark.parametrize(
    "accounts",
    [None, ["invalid"], ["same@example.test"] * 2, [{}], ["x"] * 5],
)
def test_inventory_rejects_invalid_additional_invoker_accounts(accounts) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["jobs"][-1]["additional_invoker_service_accounts"] = accounts
    assert any(
        "additional_invoker_service_accounts" in error
        for error in scheduler_inventory.validate_inventory(inventory)
    )


@pytest.mark.parametrize("job_exists", [False, True])
@pytest.mark.parametrize("job_name", ["caseops-document-processing", "caseops-court-sync"])
def test_first_execution_release_allows_absence_only_when_both_resources_are_missing(
    monkeypatch,
    job_exists,
    job_name,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    calls = []
    monkeypatch.setattr(scheduler_inventory, "scheduler_exists", lambda *a, **k: False)
    monkeypatch.setattr(scheduler_inventory, "run_job_exists", lambda *a, **k: job_exists)
    monkeypatch.setattr(scheduler_inventory, "run_gcloud", lambda *a, **k: calls.append(a))
    kwargs = dict(
        scheduler=job_name + "-cadence",
        project=inventory["production_project"],
        region=inventory["location"],
        wait_seconds=600,
        allow_missing=True,
    )
    if job_exists:
        with pytest.raises(scheduler_inventory.InventoryError, match="cannot certify its drain"):
            scheduler_inventory.quiesce(inventory, **kwargs)
    else:
        assert scheduler_inventory.quiesce(inventory, **kwargs) == {
            "scheduler": kwargs["scheduler"],
            "absent": True,
            "drained": True,
            "observed_executions": [],
        }
    assert not calls


@pytest.mark.parametrize("wait_seconds", [0, 4, 601])
@pytest.mark.parametrize("job_name", ["caseops-document-processing", "caseops-court-sync"])
def test_allow_missing_cannot_bypass_execution_drain_budget(
    monkeypatch, wait_seconds, job_name,
) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    monkeypatch.setattr(
        scheduler_inventory,
        "scheduler_exists",
        lambda *a, **k: pytest.fail("probe before budget validation"),
    )
    with pytest.raises(scheduler_inventory.InventoryError, match="between 5 and 600"):
        scheduler_inventory.quiesce(
            inventory,
            scheduler=job_name + "-cadence",
            project=inventory["production_project"],
            region=inventory["location"],
            wait_seconds=wait_seconds,
            allow_missing=True,
        )


@pytest.mark.parametrize(
    "condition, accepted", [("missing", False), ("conditional", False), ("unconditional", True)]
)
@pytest.mark.parametrize("job_name", ["caseops-document-processing", "caseops-court-sync"])
def test_execution_live_readback_requires_unconditional_runtime_invoker(
    monkeypatch,
    condition,
    accepted,
    job_name,
):
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    job = next(row for row in inventory["jobs"] if row["run_job_name"] == job_name)
    inventory["jobs"] = [job]
    expected_image = "registry.example/api@sha256:" + "a" * 64
    binding = {
        "role": "roles/run.invoker",
        "members": [
            "serviceAccount:caseops-runtime@perfect-period-305406.iam.gserviceaccount.com",
        ],
    }
    if condition == "conditional":
        binding["condition"] = {"expression": "false"}
    bindings = [] if condition == "missing" else [binding]

    def fake_gcloud(arguments, *, expect_json=False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": job["desired_state"],
                "schedule": job["schedule"],
                "timeZone": job["time_zone"],
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        job["run_job_name"],
                    ),
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
                },
            }
        if arguments[:3] == ["run", "jobs", "get-iam-policy"]:
            return {"bindings": bindings}
        assert arguments[:3] == ["run", "jobs", "describe"]
        return {
            "spec": {
                "template": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [{"image": expected_image}],
                                "timeoutSeconds": 600,
                            }
                        }
                    }
                }
            }
        }

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, _ = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
    )
    assert (f"{job['scheduler_name']}: additional_invoker_iam drift" not in errors) == accepted


def test_existence_probe_distinguishes_not_found_from_control_plane_failure(
    monkeypatch,
) -> None:
    class _Completed:
        returncode = 1
        stdout = ""
        stderr = "NOT_FOUND: Job could not be found"

    monkeypatch.setattr(scheduler_inventory.shutil, "which", lambda _name: "gcloud")
    monkeypatch.setattr(
        scheduler_inventory.subprocess,
        "run",
        lambda *_args, **_kwargs: _Completed(),
    )
    assert not scheduler_inventory.run_job_exists("missing", project="project", region="region")

    _Completed.stderr = "Cannot find job [missing]."
    assert not scheduler_inventory.run_job_exists("missing", project="project", region="region")

    _Completed.stderr = "PERMISSION_DENIED: caller is not authorized"
    with pytest.raises(scheduler_inventory.InventoryError, match="PERMISSION_DENIED"):
        scheduler_inventory.scheduler_exists("unknown", project="project", location="region")


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


def test_live_inspection_detects_private_scheduler_retry_drift(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    private_job = next(
        job
        for job in inventory["jobs"]
        if job["run_job_name"] == "caseops-private-projection-maintenance"
    )
    inventory["jobs"] = [private_job]
    expected_image = "registry.example/caseops-api@sha256:" + "d" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": private_job["desired_state"],
                "schedule": private_job["schedule"],
                "timeZone": private_job["time_zone"],
                "retryConfig": {"retryCount": 0},
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        private_job["run_job_name"],
                    ),
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
                },
            }
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {"template": {"spec": {"containers": [{"image": expected_image}]}}}
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [f"serviceAccount:{inventory['invoker_service_account']}"],
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

    assert f"{private_job['scheduler_name']}: retry_config drift" in errors
    assert summary["jobs"][0]["configuration"] == "fail"


def test_live_inspection_detects_bootstrap_contract_drift(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    watch_job = next(
        job for job in inventory["jobs"] if job["run_job_name"] == "caseops-ip-journal-watch"
    )
    inventory["jobs"] = [watch_job]
    expected_image = "registry.example/caseops-api@sha256:" + "f" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "ENABLED",
                "schedule": watch_job["schedule"],
                "timeZone": watch_job["time_zone"],
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        watch_job["run_job_name"],
                    ),
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
                },
            }
        if arguments[:3] == ["run", "jobs", "describe"]:
            bootstrap = watch_job["bootstrap"]
            return {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "run.googleapis.com/cloudsql-instances": bootstrap[
                                    "cloud_sql_instances"
                                ]
                            }
                        },
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "image": expected_image,
                                            "command": ["wrong-command"],
                                            "args": bootstrap["args"],
                                            "env": [
                                                *[
                                                    {"name": key, "value": value}
                                                    for key, value in bootstrap[
                                                        "environment"
                                                    ].items()
                                                ],
                                                *[
                                                    {
                                                        "name": key,
                                                        "valueFrom": {
                                                            "secretKeyRef": {
                                                                "name": value.split(":")[0],
                                                                "key": value.split(":")[1],
                                                            }
                                                        },
                                                    }
                                                    for key, value in bootstrap["secrets"].items()
                                                ],
                                            ],
                                            "resources": {
                                                "limits": {
                                                    "cpu": bootstrap["cpu"],
                                                    "memory": bootstrap["memory"],
                                                }
                                            },
                                        }
                                    ],
                                    "serviceAccountName": bootstrap["service_account"],
                                    "maxRetries": bootstrap["max_retries"],
                                    "timeoutSeconds": "900s",
                                }
                            }
                        },
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [f"serviceAccount:{inventory['invoker_service_account']}"],
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

    assert f"{watch_job['scheduler_name']}: bootstrap_contract drift" in errors
    assert summary["jobs"][0]["configuration"] == "fail"


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
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
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
                    "members": [f"serviceAccount:{inventory['invoker_service_account']}"],
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
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
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
                        "spec": {"template": {"spec": {"containers": [{"image": expected_image}]}}}
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [f"serviceAccount:{inventory['invoker_service_account']}"],
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
                    "oauthToken": {"serviceAccountEmail": inventory["invoker_service_account"]},
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
            bootstrap = authority_job["bootstrap"]
            return {
                "spec": {
                    "template": {
                        "metadata": {
                            "annotations": {
                                "run.googleapis.com/cloudsql-instances": bootstrap[
                                    "cloud_sql_instances"
                                ]
                            }
                        },
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {
                                            "image": expected_image,
                                            "command": bootstrap["command"],
                                            "args": bootstrap["args"],
                                            "env": [
                                                *[
                                                    {"name": key, "value": value}
                                                    for key, value in bootstrap[
                                                        "environment"
                                                    ].items()
                                                ],
                                                *[
                                                    {
                                                        "name": key,
                                                        "valueFrom": {
                                                            "secretKeyRef": {
                                                                "name": value.split(":")[0],
                                                                "key": value.split(":")[1],
                                                            }
                                                        },
                                                    }
                                                    for key, value in bootstrap["secrets"].items()
                                                ],
                                            ],
                                            "resources": {
                                                "limits": {
                                                    "cpu": bootstrap["cpu"],
                                                    "memory": bootstrap["memory"],
                                                }
                                            },
                                        }
                                    ],
                                    "serviceAccountName": bootstrap["service_account"],
                                    "maxRetries": bootstrap["max_retries"],
                                    "timeoutSeconds": "43200",
                                }
                            }
                        },
                    }
                }
            }
        return {
            "bindings": [
                {
                    "role": "roles/run.invoker",
                    "members": [f"serviceAccount:{inventory['invoker_service_account']}"],
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
