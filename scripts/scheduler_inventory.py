#!/usr/bin/env python3
"""Validate, reconcile, and audit the production recurring-job inventory.

The checked-in JSON file is the sole source for scheduler names, targets,
cadences, time zones, invoker identity, and release-image policy. The live
commands intentionally preserve each Cloud Run job's command, environment,
secrets, resources, and runtime service account; only its release image and
invoker binding are converged.
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
        "image_policy",
        "canary_policy",
    }
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
        for field in required:
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
    legacy = payload.get("legacy_schedulers_to_pause", [])
    if not isinstance(legacy, list) or any(not isinstance(value, str) for value in legacy):
        errors.append("legacy_schedulers_to_pause must be a list of strings")
    elif seen_schedulers.intersection(legacy):
        errors.append("a canonical scheduler cannot also be marked legacy")
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


def scheduler_exists(name: str, *, project: str, location: str) -> bool:
    executable = shutil.which("gcloud")
    if not executable:
        raise InventoryError("gcloud CLI is required")
    completed = subprocess.run(
        [
            executable,
            "scheduler",
            "jobs",
            "describe",
            name,
            "--project",
            project,
            "--location",
            location,
            "--format=json(name)",
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.returncode == 0


def reconcile(inventory: dict[str, Any], *, project: str, region: str, image: str) -> None:
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
        run_gcloud(
            [
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
        )
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
        action = "update" if scheduler_exists(scheduler, project=project, location=location) else "create"
        run_gcloud(
            [
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
        )

    errors, _summary = inspect_live(
        inventory, project=project, region=region, expected_image=image
    )
    if errors:
        raise InventoryError("refusing legacy pause; canonical drift remains:\n- " + "\n- ".join(errors))
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
        target = scheduler.get("httpTarget", {})
        actual_image = (
            run_job.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("containers", [{}])[0]
            .get("image", "")
        )
        actual_member = target.get("oauthToken", {}).get("serviceAccountEmail")
        checks = {
            "state": scheduler.get("state") == "ENABLED",
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
        for check, passed in checks.items():
            if not passed:
                errors.append(f"{scheduler_name}: {check} drift")
        summaries.append(
            {
                "scheduler": scheduler_name,
                "run_job": run_job_name,
                "state": str(scheduler.get("state", "")),
                "schedule": str(scheduler.get("schedule", "")),
                "time_zone": str(scheduler.get("timeZone", "")),
                "identity": str(actual_member or ""),
                "image": str(actual_image),
                "configuration": "pass" if all(checks.values()) else "fail",
            }
        )
    return errors, {"jobs": summaries, "result": "pass" if not errors else "fail"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("validate", "reconcile", "verify"), nargs="?", default="validate"
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
            raise InventoryError("--image is required for reconcile and verify")
        if args.command == "reconcile":
            reconcile(inventory, project=project, region=region, image=args.image)
        errors, summary = inspect_live(
            inventory, project=project, region=region, expected_image=args.image
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
