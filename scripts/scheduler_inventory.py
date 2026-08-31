#!/usr/bin/env python3
"""Validate, reconcile, and audit the production recurring-job inventory.

The checked-in JSON file is the sole source for scheduler names, targets,
cadences, time zones, desired states, invoker identity, release-image policy,
task timeouts, and complete Cloud Run runtime contracts. Every recurring job
is converged and verified on every release.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json"
DIGEST_IMAGE = re.compile(r"^.+@sha256:[a-f0-9]{64}$")


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


def run_gcloud(arguments: list[str], *, expect_json: bool = False) -> Any:
    executable = shutil.which("gcloud")
    if not executable:
        raise InventoryError("gcloud CLI is required")
    completed = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise InventoryError(f"gcloud {' '.join(arguments)} failed: {detail}")
    if not expect_json:
        return completed.stdout.strip()
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise InventoryError(f"gcloud returned invalid JSON: {exc}") from exc


def scheduler_uri(project: str, region: str, run_job_name: str) -> str:
    return (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}/"
        f"jobs/{run_job_name}:run"
    )


def _gcloud_resource_exists(arguments: list[str]) -> bool:
    executable = shutil.which("gcloud")
    if not executable:
        raise InventoryError("gcloud CLI is required")
    completed = subprocess.run(
        [executable, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
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
            if scheduler_exists(scheduler, project=project, location=location)
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
            "identity": str(actual_member or ""),
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("validate", "reconcile", "verify", "audit"),
        nargs="?",
        default="validate",
    )
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--project")
    parser.add_argument("--region")
    parser.add_argument("--image")
    args = parser.parse_args(argv)
    try:
        inventory = load_inventory(args.inventory)
        if args.command == "validate":
            print(f"scheduler inventory valid: {len(inventory['jobs'])} recurring jobs")
            return 0
        project = args.project or inventory["production_project"]
        region = args.region or inventory["location"]
        if not args.image:
            raise InventoryError("--image is required for reconcile, verify, and audit")
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
