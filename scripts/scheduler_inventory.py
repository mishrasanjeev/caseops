#!/usr/bin/env python3
"""Validate, reconcile, and audit the production recurring-job inventory.

The checked-in JSON file is the sole source for scheduler names, targets,
cadences, time zones, desired states, invoker identity, release-image policy,
task timeouts, and complete Cloud Run runtime contracts. Every recurring job
is converged and verified on every release.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json"
DIGEST_IMAGE = re.compile(r"^.+@sha256:[a-f0-9]{64}$")
# The five-minute private-projection job retained 1,899 executions in production
# on 2026-09-23. Keep a bounded unfiltered scan so an older active execution
# cannot hide behind newer completed rows, with room above the observed volume.
# Read the v2 API in bounded pages: gcloud's client-side materialization took
# 44 seconds for the same inventory and exceeded the drain's sub-deadline.
EXECUTION_DRAIN_SCAN_SENTINEL = 3001
EXECUTION_API_PAGE_SIZE = 1000
PRIVATE_PROJECTION_SCHEDULER = "caseops-private-projection-maintenance-cadence"
PROD_VERIFY_REPOSITORY = "mishrasanjeev/caseops"
PROD_VERIFY_WORKFLOW = "prod-verify.yml"
RELEASE_SHA = re.compile(r"[a-f0-9]{40}")


class InventoryError(RuntimeError):
    pass


def load_inventory(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot read inventory {path}: {exc}") from exc
    errors = validate_inventory(payload)
    if errors:
        raise InventoryError("invalid scheduler inventory:\n- " + "\n- ".join(errors))
    return payload


def hold_schedulers_paused(
    inventory: dict[str, Any],
    scheduler_names: list[str],
) -> dict[str, Any]:
    """Return a release-only inventory that keeps named schedulers paused."""

    requested = set(scheduler_names)
    canonical = {str(job["scheduler_name"]) for job in inventory["jobs"]}
    unknown = sorted(requested - canonical)
    if unknown:
        raise InventoryError(
            "cannot hold unknown scheduler(s) paused: " + ", ".join(unknown)
        )
    effective = copy.deepcopy(inventory)
    for job in effective["jobs"]:
        if job["scheduler_name"] in requested:
            job["desired_state"] = "PAUSED"
    return effective


def validate_inventory(payload: object) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["root must be an object"]
    if payload.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    for field in ("production_project", "location", "invoker_service_account"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(f"{field} must be a non-empty string")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        errors.append("jobs must be a non-empty list")
        return errors
    required = {
        "scheduler_name",
        "run_job_name",
        "schedule",
        "time_zone",
        "desired_state",
        "task_timeout_seconds",
        "image_policy",
        "canary_policy",
    }
    string_fields = required - {"task_timeout_seconds"}
    seen_schedulers: set[str] = set()
    seen_jobs: set[str] = set()
    for index, job in enumerate(jobs):
        label = f"jobs[{index}]"
        if not isinstance(job, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = sorted(required - job.keys())
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}")
            continue
        for field in string_fields:
            if not isinstance(job[field], str) or not job[field].strip():
                errors.append(f"{label}.{field} must be a non-empty string")
        scheduler = job["scheduler_name"]
        run_job = job["run_job_name"]
        if scheduler in seen_schedulers:
            errors.append(f"duplicate scheduler_name: {scheduler}")
        if run_job in seen_jobs:
            errors.append(f"duplicate run_job_name: {run_job}")
        seen_schedulers.add(scheduler)
        seen_jobs.add(run_job)
        if job["image_policy"] != "release_digest":
            errors.append(f"{label}.image_policy must be release_digest")
        if job["canary_policy"] not in {"manual_safe", "scheduled_execution"}:
            errors.append(f"{label}.canary_policy is invalid")
        if job["desired_state"] not in {"ENABLED", "PAUSED"}:
            errors.append(f"{label}.desired_state must be ENABLED or PAUSED")
        timeout = job["task_timeout_seconds"]
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, int)
            or not 1 <= timeout <= 86_400
        ):
            errors.append(
                f"{label}.task_timeout_seconds must be null or an integer "
                "between 1 and 86400"
            )
        bootstrap = job.get("bootstrap")
        if bootstrap is None:
            errors.append(f"{label}.bootstrap is required")
        else:
            errors.extend(_validate_bootstrap(bootstrap, label=label))
        retry = job.get("retry")
        if retry is not None:
            errors.extend(_validate_retry(retry, label=label))
    legacy = payload.get("legacy_schedulers_to_pause", [])
    if not isinstance(legacy, list) or any(
        not isinstance(value, str) for value in legacy
    ):
        errors.append("legacy_schedulers_to_pause must be a list of strings")
    elif seen_schedulers.intersection(legacy):
        errors.append("a canonical scheduler cannot also be marked legacy")
    return errors


def _validate_retry(retry: object, *, label: str) -> list[str]:
    if not isinstance(retry, dict):
        return [f"{label}.retry must be an object"]
    required = {
        "max_retry_attempts",
        "max_retry_duration_seconds",
        "min_backoff_seconds",
        "max_backoff_seconds",
        "max_doublings",
    }
    missing = sorted(required - retry.keys())
    if missing:
        return [f"{label}.retry missing fields: {', '.join(missing)}"]
    errors: list[str] = []
    for field in required:
        value = retry[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            errors.append(f"{label}.retry.{field} must be a non-negative integer")
    if errors:
        return errors
    if retry["max_retry_attempts"] > 5:
        errors.append(f"{label}.retry.max_retry_attempts must be at most 5")
    if retry["max_doublings"] > 16:
        errors.append(f"{label}.retry.max_doublings must be at most 16")
    if retry["min_backoff_seconds"] < 1:
        errors.append(f"{label}.retry.min_backoff_seconds must be at least 1")
    if retry["max_backoff_seconds"] < retry["min_backoff_seconds"]:
        errors.append(
            f"{label}.retry.max_backoff_seconds must be at least min_backoff_seconds"
        )
    if retry["max_retry_duration_seconds"] < retry["max_backoff_seconds"]:
        errors.append(
            f"{label}.retry.max_retry_duration_seconds must be at least max_backoff_seconds"
        )
    return errors


def _validate_bootstrap(bootstrap: object, *, label: str) -> list[str]:
    if not isinstance(bootstrap, dict):
        return [f"{label}.bootstrap must be an object"]
    required = {
        "command",
        "args",
        "environment",
        "secrets",
        "service_account",
        "cloud_sql_instances",
        "cpu",
        "memory",
        "max_retries",
    }
    errors: list[str] = []
    missing = sorted(required - bootstrap.keys())
    if missing:
        errors.append(f"{label}.bootstrap missing fields: {', '.join(missing)}")
        return errors
    for field in ("command", "args"):
        value = bootstrap[field]
        if (
            not isinstance(value, list)
            or (field == "command" and not value)
            or any(
                not isinstance(item, str) or not item or "," in item for item in value
            )
        ):
            errors.append(
                f"{label}.bootstrap.{field} must be "
                f"{'a non-empty' if field == 'command' else 'an'} array of strings"
            )
    command = bootstrap.get("command")
    if isinstance(command, list) and command:
        executable = str(command[0]).replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if executable in {"uv", "uv.exe", "uvx", "uvx.exe"}:
            errors.append(
                f"{label}.bootstrap.command must invoke the baked runtime directly; "
                "uv/uvx job startup is forbidden"
            )
    for field in ("environment", "secrets"):
        value = bootstrap[field]
        if (
            not isinstance(value, dict)
            or not value
            or any(
                not isinstance(key, str)
                or not key
                or not isinstance(item, str)
                or not item
                or "," in key
                or "," in item
                for key, item in value.items()
            )
        ):
            errors.append(
                f"{label}.bootstrap.{field} must be a non-empty string map "
                "without commas"
            )
    for field in (
        "service_account",
        "cloud_sql_instances",
        "cpu",
        "memory",
    ):
        value = bootstrap[field]
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{label}.bootstrap.{field} must be a non-empty string")
    retries = bootstrap["max_retries"]
    if (
        isinstance(retries, bool)
        or not isinstance(retries, int)
        or not 0 <= retries <= 10
    ):
        errors.append(
            f"{label}.bootstrap.max_retries must be an integer between 0 and 10"
        )
    return errors


def _invoke_gcloud(arguments: list[str], *, timeout: float = 60) -> Any:
    executable = shutil.which("gcloud")
    if not executable:
        raise InventoryError("gcloud CLI is required")
    try:
        return subprocess.run(
            [executable, *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise InventoryError("gcloud control-plane deadline exceeded") from exc


def run_gcloud(
    arguments: list[str], *, expect_json: bool = False, timeout: float = 60
) -> Any:
    completed = _invoke_gcloud(arguments, timeout=timeout)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise InventoryError(f"gcloud {' '.join(arguments)} failed: {detail}")
    if not expect_json:
        return completed.stdout.strip()
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"gcloud returned invalid JSON: {exc}") from exc


def _run_gh(arguments: list[str]) -> Any:
    output = _run_gh_text(arguments)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise InventoryError("GitHub returned invalid verification evidence") from exc


def _run_gh_text(arguments: list[str]) -> str:
    executable = shutil.which("gh")
    if not executable:
        raise InventoryError("gh CLI is required for private cadence resume")
    try:
        completed = subprocess.run(
            [executable, *arguments], check=False, capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InventoryError("GitHub verification evidence is unavailable") from exc
    if completed.returncode:
        raise InventoryError("GitHub verification evidence is unavailable")
    if len(completed.stdout) > 2_000_000:
        raise InventoryError("GitHub verification evidence exceeds bounded output")
    return completed.stdout


def scheduler_uri(project: str, region: str, run_job_name: str) -> str:
    return (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/"
        f"jobs/{run_job_name}:run"
    )


def _gcloud_resource_exists(arguments: list[str]) -> bool:
    completed = _invoke_gcloud(arguments)
    if completed.returncode == 0:
        return True
    detail = (completed.stderr or completed.stdout).strip()
    lowered = detail.lower()
    if any(
        marker in lowered
        for marker in (
            "not found",
            "cannot find",
            "could not be found",
            "does not exist",
        )
    ):
        return False
    raise InventoryError(f"gcloud {' '.join(arguments)} failed: {detail}")


def scheduler_exists(name: str, *, project: str, location: str) -> bool:
    return _gcloud_resource_exists(
        [
            "scheduler",
            "jobs",
            "describe",
            name,
            "--project",
            project,
            "--location",
            location,
            "--format=json(name)",
        ]
    )


def run_job_exists(name: str, *, project: str, region: str) -> bool:
    return _gcloud_resource_exists(
        [
            "run",
            "jobs",
            "describe",
            name,
            "--project",
            project,
            "--region",
            region,
            "--format=json(name)",
        ]
    )


def _bootstrap_arguments(
    job: dict[str, Any], *, action: str, project: str, region: str, image: str
) -> list[str]:
    bootstrap = job.get("bootstrap")
    if bootstrap is None:
        raise InventoryError(
            f"Cloud Run job {job['run_job_name']!r} is missing and has no "
            "checked-in bootstrap contract"
        )
    arguments = [
        "run",
        "jobs",
        action,
        job["run_job_name"],
        "--image",
        image,
        "--region",
        region,
        "--project",
        project,
        "--command",
        ",".join(bootstrap["command"]),
        _gcloud_args_flag(bootstrap["args"]),
        "--set-env-vars",
        ",".join(f"{key}={value}" for key, value in bootstrap["environment"].items()),
        "--set-secrets",
        ",".join(f"{key}={value}" for key, value in bootstrap["secrets"].items()),
        "--service-account",
        bootstrap["service_account"],
        "--set-cloudsql-instances",
        bootstrap["cloud_sql_instances"],
        "--cpu",
        bootstrap["cpu"],
        "--memory",
        bootstrap["memory"],
        "--max-retries",
        str(bootstrap["max_retries"]),
        "--quiet",
    ]
    task_timeout = job["task_timeout_seconds"]
    if task_timeout is not None:
        arguments.extend(["--task-timeout", f"{task_timeout}s"])
    return arguments


def _gcloud_args_flag(values: list[str]) -> str:
    """Bind job args to the flag even when the first value starts with a dash."""
    return "--args=" + ",".join(values)


def reconcile(
    inventory: dict[str, Any], *, project: str, region: str, image: str
) -> None:
    if project != inventory["production_project"]:
        raise InventoryError(
            f"project {project!r} does not match inventory production_project"
        )
    if not DIGEST_IMAGE.fullmatch(image):
        raise InventoryError("--image must be an immutable @sha256 reference")
    location = inventory["location"]
    invoker = inventory["invoker_service_account"]
    scope = "https://www.googleapis.com/auth/cloud-platform"
    member = f"serviceAccount:{invoker}"
    for job in inventory["jobs"]:
        run_job = job["run_job_name"]
        scheduler = job["scheduler_name"]
        print(f"converging {scheduler} -> {run_job}", flush=True)
        scheduler_preexists: bool | None = None
        if scheduler == PRIVATE_PROJECTION_SCHEDULER and job["desired_state"] == "ENABLED":
            scheduler_preexists = scheduler_exists(
                scheduler, project=project, location=location
            )
            if not scheduler_preexists:
                raise InventoryError(
                    "private cadence cannot be created enabled; hold it paused"
                )
            prior_state = run_gcloud(
                [
                    "scheduler", "jobs", "describe", scheduler,
                    "--location", location, "--project", project,
                    "--format=json(state)",
                ],
                expect_json=True,
            )
            if not isinstance(prior_state, dict) or prior_state.get("state") != "ENABLED":
                raise InventoryError(
                    "private cadence must remain paused until the evidence-checked "
                    "resume command succeeds"
                )
        exists = run_job_exists(run_job, project=project, region=region)
        if job.get("bootstrap") is not None:
            run_job_arguments = _bootstrap_arguments(
                job,
                action="update" if exists else "create",
                project=project,
                region=region,
                image=image,
            )
        elif exists:
            run_job_arguments = [
                "run",
                "jobs",
                "update",
                run_job,
                "--image",
                image,
                "--region",
                region,
                "--project",
                project,
                "--quiet",
            ]
            task_timeout = job["task_timeout_seconds"]
            if task_timeout is not None:
                run_job_arguments.extend(["--task-timeout", f"{task_timeout}s"])
        else:
            run_job_arguments = _bootstrap_arguments(
                job, action="create", project=project, region=region, image=image
            )
        run_gcloud(run_job_arguments)
        run_gcloud(
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
                region,
                "--project",
                project,
                "--quiet",
            ]
        )
        action = (
            "update"
            if scheduler_preexists is True or (
                scheduler_preexists is None
                and scheduler_exists(scheduler, project=project, location=location)
            )
            else "create"
        )
        scheduler_arguments = [
            "scheduler",
            "jobs",
            action,
            "http",
            scheduler,
            "--location",
            location,
            "--project",
            project,
            "--schedule",
            job["schedule"],
            "--time-zone",
            job["time_zone"],
            "--uri",
            scheduler_uri(project, region, run_job),
            "--http-method",
            "POST",
            "--message-body",
            "{}",
            "--oauth-service-account-email",
            invoker,
            "--oauth-token-scope",
            scope,
            "--quiet",
        ]
        retry = job.get("retry")
        if retry is not None:
            scheduler_arguments.extend(
                [
                    "--max-retry-attempts",
                    str(retry["max_retry_attempts"]),
                    "--max-retry-duration",
                    f"{retry['max_retry_duration_seconds']}s",
                    "--min-backoff",
                    f"{retry['min_backoff_seconds']}s",
                    "--max-backoff",
                    f"{retry['max_backoff_seconds']}s",
                    "--max-doublings",
                    str(retry["max_doublings"]),
                ]
            )
        run_gcloud(scheduler_arguments)
        scheduler_after_update = run_gcloud(
            [
                "scheduler",
                "jobs",
                "describe",
                scheduler,
                "--location",
                location,
                "--project",
                project,
                "--format=json(state)",
            ],
            expect_json=True,
        )
        if scheduler_after_update.get("state") != job["desired_state"]:
            state_action = "pause" if job["desired_state"] == "PAUSED" else "resume"
            if scheduler == PRIVATE_PROJECTION_SCHEDULER and state_action == "resume":
                raise InventoryError(
                    "private cadence must remain paused until the evidence-checked "
                    "resume command succeeds"
                )
            run_gcloud(
                [
                    "scheduler",
                    "jobs",
                    state_action,
                    scheduler,
                    "--location",
                    location,
                    "--project",
                    project,
                    "--quiet",
                ]
            )

    errors, _summary = inspect_live(
        inventory, project=project, region=region, expected_image=image
    )
    if errors:
        raise InventoryError(
            "refusing legacy pause; canonical drift remains:\n- " + "\n- ".join(errors)
        )
    for scheduler in inventory.get("legacy_schedulers_to_pause", []):
        if scheduler_exists(scheduler, project=project, location=location):
            run_gcloud(
                [
                    "scheduler",
                    "jobs",
                    "pause",
                    scheduler,
                    "--location",
                    location,
                    "--project",
                    project,
                    "--quiet",
                ]
            )
            print(f"paused superseded scheduler {scheduler}", flush=True)


def inspect_live(
    inventory: dict[str, Any],
    *,
    project: str,
    region: str,
    expected_image: str,
    audit_attempts: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    location = inventory["location"]
    invoker = inventory["invoker_service_account"]
    expected_member = f"serviceAccount:{invoker}"
    summaries: list[dict[str, str]] = []
    for job in inventory["jobs"]:
        scheduler_name = job["scheduler_name"]
        run_job_name = job["run_job_name"]
        scheduler = run_gcloud(
            [
                "scheduler",
                "jobs",
                "describe",
                scheduler_name,
                "--location",
                location,
                "--project",
                project,
                "--format=json",
            ],
            expect_json=True,
        )
        run_job = run_gcloud(
            [
                "run",
                "jobs",
                "describe",
                run_job_name,
                "--region",
                region,
                "--project",
                project,
                "--format=json",
            ],
            expect_json=True,
        )
        policy = run_gcloud(
            [
                "run",
                "jobs",
                "get-iam-policy",
                run_job_name,
                "--region",
                region,
                "--project",
                project,
                "--format=json",
            ],
            expect_json=True,
        )
        executions: list[dict[str, Any]] = []
        if audit_attempts:
            executions = run_gcloud(
                [
                    "run",
                    "jobs",
                    "executions",
                    "list",
                    "--job",
                    run_job_name,
                    "--region",
                    region,
                    "--project",
                    project,
                    "--sort-by=~metadata.creationTimestamp",
                    "--limit=1",
                    "--format=json",
                ],
                expect_json=True,
            )
        target = scheduler.get("httpTarget", {})
        run_spec = (
            run_job.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
        )
        actual_image = run_spec.get("containers", [{}])[0].get("image", "")
        container = run_spec.get("containers", [{}])[0]
        actual_timeout = _duration_seconds(run_spec.get("timeoutSeconds"))
        actual_member = target.get("oauthToken", {}).get("serviceAccountEmail")
        checks = {
            "state": scheduler.get("state") == job["desired_state"],
            "schedule": scheduler.get("schedule") == job["schedule"],
            "time_zone": scheduler.get("timeZone") == job["time_zone"],
            "uri": target.get("uri") == scheduler_uri(project, region, run_job_name),
            "identity": actual_member == invoker,
            "image": actual_image == expected_image,
            "invoker_iam": any(
                binding.get("role") == "roles/run.invoker"
                and expected_member in binding.get("members", [])
                for binding in policy.get("bindings", [])
            ),
        }
        expected_timeout = job["task_timeout_seconds"]
        if expected_timeout is not None:
            checks["task_timeout"] = actual_timeout == expected_timeout
        retry = job.get("retry")
        if retry is not None:
            actual_retry = scheduler.get("retryConfig") or {}
            checks["retry_config"] = all(
                (
                    actual_retry.get("retryCount") == retry["max_retry_attempts"],
                    _duration_seconds(actual_retry.get("maxRetryDuration"))
                    == retry["max_retry_duration_seconds"],
                    _duration_seconds(actual_retry.get("minBackoffDuration"))
                    == retry["min_backoff_seconds"],
                    _duration_seconds(actual_retry.get("maxBackoffDuration"))
                    == retry["max_backoff_seconds"],
                    actual_retry.get("maxDoublings") == retry["max_doublings"],
                )
            )
        bootstrap = job.get("bootstrap")
        if bootstrap is not None:
            actual_environment: dict[str, str] = {}
            actual_secrets: dict[str, str] = {}
            for item in container.get("env", []):
                name = item.get("name")
                if not isinstance(name, str):
                    continue
                secret = (item.get("valueFrom") or {}).get("secretKeyRef")
                if isinstance(secret, dict):
                    actual_secrets[name] = (
                        f"{secret.get('name', '')}:{secret.get('key', '')}"
                    )
                elif isinstance(item.get("value"), str):
                    actual_environment[name] = item["value"]
            annotations = (
                run_job.get("spec", {})
                .get("template", {})
                .get("metadata", {})
                .get("annotations", {})
            )
            resources = container.get("resources", {}).get("limits", {})
            checks["bootstrap_contract"] = all(
                (
                    container.get("command", []) == bootstrap["command"],
                    container.get("args", []) == bootstrap["args"],
                    actual_environment == bootstrap["environment"],
                    actual_secrets == bootstrap["secrets"],
                    run_spec.get("serviceAccountName") == bootstrap["service_account"],
                    annotations.get("run.googleapis.com/cloudsql-instances")
                    == bootstrap["cloud_sql_instances"],
                    str(resources.get("cpu", "")) == bootstrap["cpu"],
                    str(resources.get("memory", "")) == bootstrap["memory"],
                    run_spec.get("maxRetries") == bootstrap["max_retries"],
                )
            )
        scheduler_status = scheduler.get("status") or {}
        last_attempt = str(scheduler.get("lastAttemptTime") or "")
        scheduler_attempt_required = job["desired_state"] == "ENABLED"
        if audit_attempts and scheduler_attempt_required:
            checks["natural_or_canary_attempt"] = bool(last_attempt)
            checks["scheduler_delivery"] = not scheduler_status.get("code")
        for check, passed in checks.items():
            if not passed:
                errors.append(f"{scheduler_name}: {check} drift")
        summary = {
            "scheduler": scheduler_name,
            "run_job": run_job_name,
            "state": str(scheduler.get("state", "")),
            "desired_state": job["desired_state"],
            "schedule": str(scheduler.get("schedule", "")),
            "time_zone": str(scheduler.get("timeZone", "")),
            # Report the reviewed inventory identity, never a value read from the
            # scheduler's OAuth token configuration.
            "identity": invoker if checks["identity"] else "mismatch",
            "image": str(actual_image),
            "task_timeout_seconds": str(actual_timeout or ""),
            "configuration": "pass" if all(checks.values()) else "fail",
        }
        if audit_attempts:
            summary.update(
                {
                    "last_attempt": last_attempt,
                    "scheduler_delivery": (
                        ("pass" if not scheduler_status.get("code") else "fail")
                        if scheduler_attempt_required
                        else "not_required_paused"
                    ),
                    "latest_execution": summarize_execution(executions),
                }
            )
        summaries.append(summary)
    return errors, {"jobs": summaries, "result": "pass" if not errors else "fail"}


def _duration_seconds(value: object) -> int | None:
    """Normalize Cloud Run's integer or protobuf-duration JSON rendering."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.fullmatch(r"(\d+)(?:s)?", value.strip())
        if match:
            return int(match.group(1))
    return None


def summarize_execution(executions: object) -> dict[str, str]:
    """Return a bounded operational result without treating a job failure as IAM drift."""
    if not isinstance(executions, list) or not executions:
        return {"name": "", "created_at": "", "completed_at": "", "outcome": "missing"}
    execution = executions[0]
    if not isinstance(execution, dict):
        return {"name": "", "created_at": "", "completed_at": "", "outcome": "unknown"}
    metadata = execution.get("metadata") or {}
    status = execution.get("status") or {}
    conditions = status.get("conditions") or []
    completed = next(
        (
            condition
            for condition in conditions
            if isinstance(condition, dict) and condition.get("type") == "Completed"
        ),
        {},
    )
    condition_status = str(completed.get("status") or "").lower()
    if status.get("succeededCount") or condition_status == "true":
        outcome = "succeeded"
    elif status.get("failedCount") or condition_status == "false":
        outcome = "failed"
    else:
        outcome = "running_or_unknown"
    return {
        "name": str(metadata.get("name") or ""),
        "created_at": str(metadata.get("creationTimestamp") or ""),
        "completed_at": str(status.get("completionTime") or ""),
        "outcome": outcome,
    }


def _selected_job(inventory: dict[str, Any], scheduler: str) -> dict[str, Any]:
    for job in inventory["jobs"]:
        if job["scheduler_name"] == scheduler:
            return job
    raise InventoryError("rollout guard requires a canonical scheduler")


def _unfinished_executions(payload: object, *, job_name: str) -> list[str]:
    # Read the unfiltered history: a newest-only sample can hide an older worker.
    if (
        not isinstance(payload, list)
        or len(payload) >= EXECUTION_DRAIN_SCAN_SENTINEL
    ):
        raise InventoryError("execution inventory is invalid or truncated")
    unfinished: list[str] = []
    seen: set[str] = set()
    for row in payload:
        if not isinstance(row, dict):
            raise InventoryError("invalid execution record")
        metadata, status = row.get("metadata"), row.get("status", {})
        if not isinstance(metadata, dict) or not isinstance(status, dict):
            raise InventoryError("invalid execution metadata/status")
        name = metadata.get("name")
        labels = metadata.get("labels", {})
        if (
            not isinstance(name, str)
            or not name
            or name in seen
            or not isinstance(labels, dict)
            or labels.get("run.googleapis.com/job") != job_name
        ):
            raise InventoryError(
                "execution identity is missing, duplicated or mismatched"
            )
        seen.add(name)
        completed = status.get("completionTime")
        running = status.get("runningCount", 0)
        if isinstance(running, bool) or not isinstance(running, int) or running < 0:
            raise InventoryError("invalid execution running count")
        if completed:
            try:
                parsed = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    raise ValueError("missing timezone")
            except (AttributeError, TypeError, ValueError) as exc:
                raise InventoryError("invalid execution completion time") from exc
        if not completed or running:
            unfinished.append(name)
    return unfinished


def _list_job_executions_v2(
    *,
    job_name: str,
    project: str,
    region: str,
    access_token: str,
    timeout: float,
) -> list[dict[str, Any]]:
    """Read the complete retained execution inventory through bounded API pages."""

    if not access_token.strip():
        raise InventoryError("gcloud returned an empty access token")
    deadline = time.monotonic() + timeout
    parent = (
        f"projects/{project}/locations/{region}/jobs/{job_name}/executions"
    )
    endpoint = f"https://run.googleapis.com/v2/{parent}"
    fields = (
        "executions(name,job,createTime,completionTime,runningCount),"
        "nextPageToken"
    )
    page_token = ""
    seen_page_tokens: set[str] = set()
    executions: list[dict[str, Any]] = []

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InventoryError("Cloud Run execution inventory deadline exceeded")
        query: dict[str, str | int] = {
            "pageSize": min(
                EXECUTION_API_PAGE_SIZE,
                EXECUTION_DRAIN_SCAN_SENTINEL - len(executions),
            ),
            "fields": fields,
        }
        if page_token:
            query["pageToken"] = page_token
        request = urllib_request.Request(
            f"{endpoint}?{urllib_parse.urlencode(query)}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {access_token.strip()}",
            },
        )
        try:
            with urllib_request.urlopen(request, timeout=min(30, remaining)) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (
            json.JSONDecodeError,
            OSError,
            TimeoutError,
            UnicodeDecodeError,
            urllib_error.URLError,
        ) as exc:
            raise InventoryError(
                "Cloud Run execution inventory request failed"
            ) from exc
        if not isinstance(payload, dict) or not isinstance(
            payload.get("executions", []), list
        ):
            raise InventoryError("Cloud Run returned an invalid execution inventory")
        for execution in payload.get("executions", []):
            if not isinstance(execution, dict):
                raise InventoryError("Cloud Run returned an invalid execution record")
            name = execution.get("name")
            job = execution.get("job")
            if not isinstance(name, str) or not name.startswith(f"{parent}/"):
                raise InventoryError("Cloud Run returned a mismatched execution identity")
            executions.append(
                {
                    "metadata": {
                        "name": name.rsplit("/", 1)[-1],
                        "labels": {"run.googleapis.com/job": job},
                    },
                    "status": {
                        **(
                            {"completionTime": execution["completionTime"]}
                            if "completionTime" in execution
                            else {}
                        ),
                        "runningCount": execution.get("runningCount", 0),
                    },
                }
            )
            if len(executions) >= EXECUTION_DRAIN_SCAN_SENTINEL:
                raise InventoryError("execution inventory is invalid or truncated")
        next_page_token = payload.get("nextPageToken", "")
        if not next_page_token:
            return executions
        if (
            not isinstance(next_page_token, str)
            or next_page_token in seen_page_tokens
        ):
            raise InventoryError("Cloud Run returned an invalid execution page token")
        seen_page_tokens.add(next_page_token)
        page_token = next_page_token


def quiesce(
    inventory: dict[str, Any],
    *,
    scheduler: str,
    project: str,
    region: str,
    wait_seconds: int = 180,
) -> dict[str, Any]:
    job = _selected_job(inventory, scheduler)
    if not 5 <= wait_seconds <= 600:
        raise InventoryError("drain wait must be between 5 and 600 seconds")
    deadline = time.monotonic() + wait_seconds

    # Hosted and Windows gcloud control-plane calls can exceed 30 seconds.
    # Keep each call bounded by both the per-call cap and the drain deadline.
    access_token = run_gcloud(
        ["auth", "print-access-token"], timeout=min(90, wait_seconds)
    )
    if not isinstance(access_token, str) or not access_token.strip():
        raise InventoryError("gcloud returned an empty access token")

    def call(arguments: list[str], *, expect_json: bool = False) -> Any:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InventoryError(
                "execution drain deadline exceeded; scheduler remains paused; "
                "rerun this release after inspecting the active executions"
            )
        return run_gcloud(
            arguments, expect_json=expect_json, timeout=min(90, remaining)
        )

    location = ["--project", project, "--location", region]
    call(["scheduler", "jobs", "pause", scheduler, *location, "--quiet"])
    consecutive_clean = 0
    observed: set[str] = set()
    while True:
        state = call(
            ["scheduler", "jobs", "describe", scheduler, *location, "--format=json"],
            expect_json=True,
        )
        if (
            not isinstance(state, dict)
            or state.get("state") != "PAUSED"
            or state.get("httpTarget", {}).get("uri")
            != scheduler_uri(project, region, job["run_job_name"])
        ):
            raise InventoryError("scheduler pause/target could not be verified")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise InventoryError(
                "execution drain deadline exceeded; scheduler remains paused; "
                "rerun this release after inspecting the active executions"
            )
        executions = _list_job_executions_v2(
            job_name=job["run_job_name"],
            project=project,
            region=region,
            access_token=access_token,
            timeout=remaining,
        )
        active = _unfinished_executions(executions, job_name=job["run_job_name"])
        observed.update(active)
        consecutive_clean = 0 if active else consecutive_clean + 1
        if consecutive_clean == 2:
            return {
                "scheduler": scheduler,
                "state": "PAUSED",
                "drained": True,
                "observed_executions": sorted(observed),
                "clean_samples": 2,
            }
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def _evidence_time(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise InventoryError(f"missing {label} timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryError(f"invalid {label} timestamp") from exc
    if parsed.tzinfo is None:
        raise InventoryError(f"timezone-free {label} timestamp")
    return parsed.astimezone(UTC)


def _active_prod_verification() -> None:
    for status in ("queued", "in_progress", "waiting", "requested", "pending"):
        runs = _run_gh([
            "run", "list", "--repo", PROD_VERIFY_REPOSITORY,
            "--workflow", PROD_VERIFY_WORKFLOW, "--status", status,
            "--limit", "1", "--json", "databaseId",
        ])
        if not isinstance(runs, list):
            raise InventoryError("invalid active prod-verify inventory")
        if runs:
            raise InventoryError("prod-verify is active; private cadence stays paused")


def _successful_qa_dispatch(release_sha: str, qa_run_id: int) -> tuple[datetime, str]:
    if not RELEASE_SHA.fullmatch(release_sha) or qa_run_id <= 0:
        raise InventoryError("private resume requires an exact release SHA and QA run ID")
    _active_prod_verification()
    latest = _run_gh([
        "run", "list", "--repo", PROD_VERIFY_REPOSITORY,
        "--workflow", PROD_VERIFY_WORKFLOW, "--event", "workflow_dispatch",
        "--limit", "1", "--json", "databaseId,event,headSha,status,conclusion",
    ])
    if (
        not isinstance(latest, list) or len(latest) != 1
        or latest[0].get("databaseId") != qa_run_id
        or latest[0].get("event") != "workflow_dispatch"
        or latest[0].get("headSha") != release_sha
        or latest[0].get("status") != "completed"
        or latest[0].get("conclusion") != "success"
    ):
        raise InventoryError("latest exact-SHA prod-verify dispatch is not successful")
    detail = _run_gh([
        "run", "view", str(qa_run_id), "--repo", PROD_VERIFY_REPOSITORY,
        "--json", "databaseId,event,headSha,status,conclusion,workflowName,jobs",
    ])
    if (
        not isinstance(detail, dict)
        or detail.get("databaseId") != qa_run_id
        or detail.get("event") != "workflow_dispatch"
        or detail.get("headSha") != release_sha
        or detail.get("status") != "completed"
        or detail.get("conclusion") != "success"
        or detail.get("workflowName") != "Prod verification (Playwright)"
    ):
        raise InventoryError("prod-verify dispatch identity changed or is incomplete")
    jobs = detail.get("jobs")
    required = {
        "Resolve exact production release",
        "Prod Playwright (tester)",
        "Prod Playwright (legacy)",
        "Prod Playwright (supporting)",
        "Prod Playwright (patent-statute)",
        "Record exact-release evidence",
    }
    if not isinstance(jobs, list):
        raise InventoryError("prod-verify job evidence is missing")
    completed: list[datetime] = []
    successful: set[str] = set()
    release_job_id: int | None = None
    for job in jobs:
        if not isinstance(job, dict):
            raise InventoryError("invalid prod-verify job evidence")
        if job.get("name") in required and job.get("conclusion") == "success":
            successful.add(job["name"])
            completed.append(_evidence_time(job.get("completedAt"), "QA job completion"))
            if job["name"] == "Resolve exact production release":
                release_job_id = job.get("databaseId")
    if successful != required:
        raise InventoryError("prod-verify did not complete every required QA job")
    if not isinstance(release_job_id, int) or release_job_id <= 0:
        raise InventoryError("prod-verify release identity job is missing")
    release_log = _run_gh_text([
        "run", "view", str(qa_run_id), "--repo", PROD_VERIFY_REPOSITORY,
        "--job", str(release_job_id), "--log",
    ])
    recorded_shas = set(re.findall(r"\brelease_sha=([a-f0-9]{40})\b", release_log))
    if recorded_shas != {release_sha}:
        raise InventoryError("prod-verify did not record the exact serving SHA")
    api_revisions = set(re.findall(r"\bapi_revision=(caseops-api-[a-z0-9-]+)\b", release_log))
    if len(api_revisions) != 1:
        raise InventoryError("prod-verify did not record one serving API revision")
    qa_completed = max(completed)
    if qa_completed > datetime.now(UTC):
        raise InventoryError("prod-verify completion is future-dated")
    return qa_completed, api_revisions.pop()


def _clean_maintenance_record(record: object, *, second: bool) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise InventoryError("maintenance log has no structured record")
    if (
        record.get("mode") != "maintain"
        or record.get("status") != "ok"
        or record.get("severity") != "INFO"
        or record.get("release_blocked") is not False
        or record.get("event_lag_slo_seconds") != 300
        or record.get("candidate_scan_truncated") is not False
        or record.get("error_code")
    ):
        raise InventoryError("maintenance execution is blocked or incomplete")
    candidates = record.get("candidate_company_count")
    rebuilds = record.get("rebuild_count")
    companies = record.get("companies")
    if (
        isinstance(candidates, bool) or not isinstance(candidates, int)
        or not 0 <= candidates <= 50
        or isinstance(rebuilds, bool) or not isinstance(rebuilds, int)
        or not 0 <= rebuilds <= 5
        or not isinstance(companies, list) or len(companies) != candidates
        or (second and rebuilds != 0)
    ):
        raise InventoryError("maintenance candidate/rebuild accounting is invalid")
    rebuilt = 0
    for company in companies:
        if not isinstance(company, dict):
            raise InventoryError("invalid maintenance company record")
        if company.get("rebuilt") is True:
            rebuilt += 1
        elif company.get("rebuilt") is not False:
            raise InventoryError("maintenance rebuild result is missing")
        if (
            company.get("blockers_after") != []
            or company.get("repair_deferred") is not False
            or company.get("repair_lag_slo_breached") is not False
            or company.get("lag_slo_breached_before_recovery") is not False
            or company.get("error_code")
        ):
            raise InventoryError("maintenance retained a blocker, deferral or SLO breach")
        for field in ("pending_event_count_after", "failed_event_count_after"):
            count = company.get(field)
            if isinstance(count, bool) or not isinstance(count, int) or count != 0:
                raise InventoryError("maintenance retained pending or failed events")
        for field in (
            "oldest_pending_lag_seconds_before", "oldest_repair_lag_seconds_after"
        ):
            lag = company.get(field)
            if lag is not None and (
                isinstance(lag, bool) or not isinstance(lag, (int, float))
                or not 0 <= lag <= 300
            ):
                raise InventoryError("maintenance lag evidence is invalid")
    if rebuilt != rebuilds:
        raise InventoryError("maintenance rebuild accounting disagrees")
    return record


def _maintenance_execution(
    name: str, *, job: dict[str, Any], project: str, region: str,
    image: str, second: bool,
) -> tuple[datetime, datetime, dict[str, Any]]:
    execution = run_gcloud([
        "run", "jobs", "executions", "describe", name,
        "--project", project, "--region", region, "--format=json",
    ], expect_json=True)
    if not isinstance(execution, dict):
        raise InventoryError("maintenance execution detail is unavailable")
    metadata = execution.get("metadata") or {}
    status = execution.get("status") or {}
    spec = execution.get("spec") or {}
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    completed = [
        row for row in status.get("conditions", [])
        if isinstance(row, dict) and row.get("type") == "Completed"
    ]
    bootstrap = job["bootstrap"]
    if (
        str(metadata.get("name", "")).rsplit("/", 1)[-1] != name
        or (metadata.get("labels") or {}).get("run.googleapis.com/job")
        != job["run_job_name"]
        or spec.get("taskCount") != 1
        or len(containers) != 1
        or containers[0].get("image") != image
        or containers[0].get("command") != bootstrap["command"]
        or containers[0].get("args") != bootstrap["args"]
        or len(completed) != 1 or str(completed[0].get("status")).lower() != "true"
        or status.get("succeededCount") != 1
        or status.get("failedCount", 0) not in (0, None)
        or status.get("cancelledCount", 0) not in (0, None)
    ):
        raise InventoryError("maintenance execution identity, image or outcome is invalid")
    started = _evidence_time(status.get("startTime"), "maintenance start")
    ended = _evidence_time(status.get("completionTime"), "maintenance completion")
    if not started < ended <= datetime.now(UTC):
        raise InventoryError("maintenance execution timing is invalid")
    log_filter = (
        'resource.type="cloud_run_job" AND '
        f'resource.labels.job_name="{job["run_job_name"]}" AND '
        f'labels."run.googleapis.com/execution_name"="{name}" AND '
        f'logName="projects/{project}/logs/run.googleapis.com%2Fstdout" AND '
        'textPayload:"CASEOPS_PRIVATE_PROJECTION"'
    )
    logs = run_gcloud([
        "logging", "read", log_filter, "--project", project,
        "--order=desc", "--limit=3", "--format=json",
    ], expect_json=True)
    if not isinstance(logs, list) or len(logs) != 1:
        raise InventoryError("one execution-scoped maintenance record is required")
    log = logs[0]
    if not isinstance(log, dict):
        raise InventoryError("invalid maintenance log entry")
    payload = log.get("textPayload")
    if (
        (log.get("resource") or {}).get("type") != "cloud_run_job"
        or ((log.get("resource") or {}).get("labels") or {}).get("job_name")
        != job["run_job_name"]
        or (log.get("labels") or {}).get("run.googleapis.com/execution_name") != name
        or not isinstance(payload, str)
        or not payload.startswith("CASEOPS_PRIVATE_PROJECTION ")
    ):
        raise InventoryError("maintenance log is not bound to the execution")
    try:
        record = json.loads(payload.removeprefix("CASEOPS_PRIVATE_PROJECTION "))
    except json.JSONDecodeError as exc:
        raise InventoryError("invalid structured maintenance log") from exc
    _clean_maintenance_record(record, second=second)
    if not (
        started <= _evidence_time(record.get("started_at"), "maintenance log start")
        <= _evidence_time(record.get("completed_at"), "maintenance log completion")
        <= ended
    ):
        raise InventoryError("maintenance log time does not match execution")
    return started, ended, record


def _private_resume_evidence(
    *, job: dict[str, Any], project: str, region: str, image: str,
    release_sha: str, qa_run_id: int,
) -> dict[str, Any]:
    qa_completed, qa_api_revision = _successful_qa_dispatch(release_sha, qa_run_id)
    service = run_gcloud([
        "run", "services", "describe", "caseops-api", "--project", project,
        "--region", region, "--format=json",
    ], expect_json=True)
    if not isinstance(service, dict):
        raise InventoryError("serving API image evidence is unavailable")
    service_status = service.get("status")
    traffic = service_status.get("traffic") if isinstance(service_status, dict) else None
    if (
        not isinstance(service_status, dict)
        or service_status.get("latestReadyRevisionName") != qa_api_revision
        or not isinstance(traffic, list)
        or len(traffic) != 1
        or not isinstance(traffic[0], dict)
        or traffic[0].get("revisionName") != qa_api_revision
        or isinstance(traffic[0].get("percent"), bool)
        or traffic[0].get("percent") != 100
        or traffic[0].get("tag") not in (None, "")
    ):
        raise InventoryError("serving API revision or traffic differs from QA evidence")
    revision = run_gcloud([
        "run", "revisions", "describe", qa_api_revision,
        "--project", project, "--region", region, "--format=json",
    ], expect_json=True)
    revision_containers = (
        (revision.get("spec") or {}).get("containers")
        if isinstance(revision, dict) else None
    )
    revision_api = [
        row for row in revision_containers or []
        if isinstance(row, dict) and row.get("name") == "api"
    ]
    if (
        not isinstance(revision_containers, list)
        or len(revision_api) != 1
        or revision_api[0].get("image") != image
    ):
        raise InventoryError("QA serving revision does not use the maintenance image")
    rows = run_gcloud([
        "run", "jobs", "executions", "list", "--job", job["run_job_name"],
        "--project", project, "--region", region,
        "--sort-by=~metadata.creationTimestamp", "--limit=3", "--format=json",
    ], expect_json=True)
    if not isinstance(rows, list) or len(rows) < 2 or len(rows) > 3:
        raise InventoryError("two latest maintenance executions are unavailable")
    names: list[str] = []
    created: list[datetime] = []
    for row in rows:
        metadata = row.get("metadata") if isinstance(row, dict) else None
        if not isinstance(metadata, dict):
            raise InventoryError("invalid maintenance execution listing")
        name = metadata.get("name")
        if not isinstance(name, str) or not re.fullmatch(
            re.escape(job["run_job_name"]) + r"-[a-z0-9-]+", name
        ) or name in names:
            raise InventoryError("invalid maintenance execution identity")
        names.append(name)
        created.append(_evidence_time(metadata.get("creationTimestamp"), "execution creation"))
    if created != sorted(created, reverse=True) or len(set(created)) != len(created):
        raise InventoryError("latest maintenance execution order is unverified")
    job_status = run_gcloud([
        "run", "jobs", "describe", job["run_job_name"],
        "--project", project, "--region", region, "--format=json",
    ], expect_json=True)
    latest_execution = (
        ((job_status.get("status") or {}).get("latestCreatedExecution") or {})
        if isinstance(job_status, dict) else {}
    )
    if str(latest_execution.get("name", "")).rsplit("/", 1)[-1] != names[0]:
        raise InventoryError("maintenance execution list is not current")
    second_started, second_ended, second_record = _maintenance_execution(
        names[0], job=job, project=project, region=region, image=image, second=True,
    )
    first_started, first_ended, first_record = _maintenance_execution(
        names[1], job=job, project=project, region=region, image=image, second=False,
    )
    if not qa_completed < first_started < first_ended <= second_started < second_ended:
        raise InventoryError("maintenance runs are not serial and after completed QA")
    if _successful_qa_dispatch(release_sha, qa_run_id) != (qa_completed, qa_api_revision):
        raise InventoryError("prod-verify evidence changed during maintenance inspection")
    return {
        "qa_run_id": qa_run_id, "release_sha": release_sha,
        "qa_completed_at": qa_completed.isoformat(),
        "qa_api_revision": qa_api_revision, "image": image,
        "maintenance_executions": [names[1], names[0]],
        "rebuild_counts": [first_record["rebuild_count"], second_record["rebuild_count"]],
    }


def resume_verified(
    inventory: dict[str, Any],
    *,
    scheduler: str,
    project: str,
    region: str,
    image: str,
    release_sha: str = "",
    qa_run_id: int = 0,
) -> dict[str, Any]:
    job = _selected_job(inventory, scheduler)
    if not DIGEST_IMAGE.fullmatch(image) or job["desired_state"] != "ENABLED":
        raise InventoryError(
            "resume requires an immutable image and enabled canonical job"
        )
    if scheduler == PRIVATE_PROJECTION_SCHEDULER and (
        project != inventory["production_project"] or region != inventory["location"]
    ):
        raise InventoryError("private cadence evidence must target production project and region")
    selected = copy.deepcopy(inventory)
    selected["jobs"] = [copy.deepcopy(job)]
    selected["legacy_schedulers_to_pause"] = []
    selected["jobs"][0]["desired_state"] = "PAUSED"
    errors, _ = inspect_live(
        selected, project=project, region=region, expected_image=image
    )
    if errors:
        raise InventoryError(
            "paused release job failed verification: " + "; ".join(errors)
        )
    evidence = None
    if scheduler == PRIVATE_PROJECTION_SCHEDULER:
        evidence = _private_resume_evidence(
            job=job, project=project, region=region, image=image,
            release_sha=release_sha, qa_run_id=qa_run_id,
        )
    try:
        run_gcloud(
            [
                "scheduler",
                "jobs",
                "resume",
                scheduler,
                "--project",
                project,
                "--location",
                region,
                "--quiet",
            ]
        )
        selected["jobs"][0]["desired_state"] = "ENABLED"
        errors, summary = inspect_live(
            selected, project=project, region=region, expected_image=image
        )
        if errors:
            raise InventoryError(
                "resumed release job failed verification: " + "; ".join(errors)
            )
    except InventoryError:
        run_gcloud(
            [
                "scheduler",
                "jobs",
                "pause",
                scheduler,
                "--project",
                project,
                "--location",
                region,
                "--quiet",
            ]
        )
        raise
    if evidence is not None:
        summary["private_resume_evidence"] = evidence
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("validate", "reconcile", "verify", "audit", "quiesce", "resume"),
        nargs="?",
        default="validate",
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--project")
    parser.add_argument("--region")
    parser.add_argument("--image")
    parser.add_argument("--scheduler")
    parser.add_argument("--release-sha")
    parser.add_argument("--qa-run-id", type=int)
    parser.add_argument("--wait-seconds", type=int, default=180)
    parser.add_argument(
        "--hold-scheduler-paused",
        action="append",
        default=[],
        help="Keep one canonical scheduler paused during this reconcile only.",
    )
    args = parser.parse_args(argv)
    try:
        inventory = load_inventory(args.inventory)
        if args.hold_scheduler_paused and args.command != "reconcile":
            raise InventoryError("--hold-scheduler-paused is valid only for reconcile")
        if args.command == "validate":
            print(f"scheduler inventory valid: {len(inventory['jobs'])} recurring jobs")
            return 0
        project = args.project or inventory["production_project"]
        region = args.region or inventory["location"]
        if args.command in {"quiesce", "resume"}:
            if not args.scheduler:
                raise InventoryError("--scheduler is required for the rollout guard")
            if args.command == "quiesce":
                summary = quiesce(
                    inventory,
                    scheduler=args.scheduler,
                    project=project,
                    region=region,
                    wait_seconds=args.wait_seconds,
                )
            else:
                if args.scheduler == PRIVATE_PROJECTION_SCHEDULER and (
                    not args.release_sha or not args.qa_run_id
                ):
                    raise InventoryError(
                        "private cadence resume requires --release-sha and --qa-run-id"
                    )
                if args.scheduler != PRIVATE_PROJECTION_SCHEDULER and (
                    args.release_sha or args.qa_run_id
                ):
                    raise InventoryError(
                        "QA evidence arguments apply only to private cadence resume"
                    )
                summary = resume_verified(
                    inventory,
                    scheduler=args.scheduler,
                    project=project,
                    region=region,
                    image=args.image or "",
                    release_sha=args.release_sha or "",
                    qa_run_id=args.qa_run_id or 0,
                )
            print(json.dumps(summary, indent=2, sort_keys=True))
            return 0
        if not args.image:
            raise InventoryError("--image is required for reconcile, verify, and audit")
        if args.hold_scheduler_paused:
            inventory = hold_schedulers_paused(
                inventory,
                args.hold_scheduler_paused,
            )
        if args.command == "reconcile":
            reconcile(inventory, project=project, region=region, image=args.image)
        errors, summary = inspect_live(
            inventory,
            project=project,
            region=region,
            expected_image=args.image,
            audit_attempts=args.command == "audit",
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        if errors:
            raise InventoryError("live scheduler drift:\n- " + "\n- ".join(errors))
        return 0
    except InventoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
