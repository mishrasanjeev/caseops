#!/usr/bin/env python3
"""Fence queue admission and prove legacy executor quiescence before activation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import scheduler_inventory as inventory
from worker_stop_evidence import RETENTION, prove_stopped

SERVICE = "caseops-api"
JOB = "caseops-document-processing"
SCHEDULER = "caseops-document-processing-cadence"
PROTOCOL = "CASEOPS_DOCUMENT_WORKER_ADMISSION_PROTOCOL_VERSION"
ADMISSION = "CASEOPS_DOCUMENT_WORKER_ADMISSION_ENABLED"
REVISION = re.compile(r"caseops-api-[a-z0-9-]{1,63}")
MAX_REVISIONS = 1000


@dataclass(frozen=True)
class Executor:
    job: str
    scheduler: str
    protocol: str
    admission: str
    command: str
    args: tuple[str, ...]
    mode_key: str
    target_key: str
    region_key: str


DOCUMENT = Executor(
    JOB, SCHEDULER, PROTOCOL, ADMISSION, "caseops-document-worker",
    ("--documents-only", "--once", "--batch-size=5", "--skip-migrations"),
    "CASEOPS_DOCUMENT_PROCESSING_DISPATCH_MODE", "CASEOPS_DOCUMENT_PROCESSING_RUN_JOB",
    "CASEOPS_DOCUMENT_PROCESSING_RUN_REGION",
)
COURT = Executor(
    "caseops-court-sync", "caseops-court-sync-cadence",
    "CASEOPS_COURT_SYNC_WORKER_ADMISSION_PROTOCOL_VERSION",
    "CASEOPS_COURT_SYNC_WORKER_ADMISSION_ENABLED", "caseops-court-sync-worker",
    ("--once", "--batch-size=3", "--skip-migrations"), "CASEOPS_COURT_SYNC_DISPATCH_MODE",
    "CASEOPS_COURT_SYNC_RUN_JOB", "CASEOPS_COURT_SYNC_RUN_REGION",
)
EXECUTORS = {"document": DOCUMENT, "court": COURT}


def _call(arguments: list[str], *, project: str, region: str, json_result=True):
    return inventory.run_gcloud(
        [*arguments, "--project", project, "--region", region],
        expect_json=json_result,
        timeout=90,
    )


def _env(container: dict) -> dict:
    rows = container.get("env", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise inventory.InventoryError("invalid executor environment")
    names = [row.get("name") for row in rows]
    if len(names) != len(set(names)):
        raise inventory.InventoryError("duplicate executor environment keys")
    return {row.get("name"): row.get("value") for row in rows}


def _service(*, project: str, region: str) -> tuple[str, dict]:
    payload = _call(
        ["run", "services", "describe", SERVICE, "--format=json"],
        project=project,
        region=region,
    )
    status = payload.get("status", {})
    traffic = status.get("traffic", [])
    desired = payload.get("spec", {}).get("traffic", [])
    annotations = payload.get("metadata", {}).get("annotations", {})
    revision = status.get("latestReadyRevisionName", "")
    if (
        not REVISION.fullmatch(revision)
        or status.get("latestCreatedRevisionName") != revision
    ):
        raise inventory.InventoryError("API latest revision is not ready")
    if (
        len(traffic) != 1
        or traffic[0].get("revisionName") != revision
        or traffic[0].get("percent") != 100
        or traffic[0].get("latestRevision") is not True
        or traffic[0].get("tag")
        or not isinstance(desired, list)
        or len(desired) != 1
        or not isinstance(desired[0], dict)
        or desired[0].get("latestRevision") is not True
        or desired[0].get("percent") != 100
        or desired[0].get("revisionName")
        or desired[0].get("tag")
    ):
        raise inventory.InventoryError(
            "API must have untagged latest-only 100% traffic"
        )
    if (
        not isinstance(annotations, dict)
        or annotations.get("run.googleapis.com/scalingMode", "automatic") != "automatic"
    ):
        raise inventory.InventoryError("API service must use automatic scaling")
    conditions = {
        row.get("type"): row.get("status") for row in status.get("conditions", [])
    }
    if any(
        conditions.get(name) != "True"
        for name in ("Ready", "RoutesReady", "ConfigurationsReady")
    ):
        raise inventory.InventoryError("API service is not healthy")
    return revision, payload


def _revision(name: str, *, project: str, region: str) -> tuple[str, dict]:
    if not REVISION.fullmatch(name):
        raise inventory.InventoryError("invalid captured API revision")
    payload = _call(
        ["run", "revisions", "describe", name, "--format=json"],
        project=project,
        region=region,
    )
    metadata = payload.get("metadata", {})
    containers = payload.get("spec", {}).get("containers", [])
    if (
        metadata.get("name") != name
        or metadata.get("labels", {}).get("serving.knative.dev/service") != SERVICE
        or not containers
        or not inventory.DIGEST_IMAGE.fullmatch(containers[0].get("image", ""))
    ):
        raise inventory.InventoryError("API revision identity/image is unverified")
    return containers[0]["image"], _env(containers[0])


def _retired_revision_inventory(
    current: str, *, project: str, region: str
) -> dict[str, dict]:
    rows = _call(
        [
            "run",
            "revisions",
            "list",
            "--service",
            SERVICE,
            f"--limit={MAX_REVISIONS + 1}",
            "--format=json(metadata.name,metadata.annotations,status.conditions,spec.timeoutSeconds)",
        ],
        project=project,
        region=region,
    )
    if not isinstance(rows, list) or not rows or len(rows) > MAX_REVISIONS:
        raise inventory.InventoryError(
            "API revision inventory is missing or exceeds its bound"
        )
    names: list[str] = []
    retired_revisions: dict[str, dict] = {}
    for row in rows:
        name = row.get("metadata", {}).get("name", "")
        if not REVISION.fullmatch(name) or name in names:
            raise inventory.InventoryError(
                "invalid or duplicate API revision inventory"
            )
        names.append(name)
        if name == current:
            continue
        active = [
            item
            for item in row.get("status", {}).get("conditions", [])
            if item.get("type") == "Active"
        ]
        if (
            len(active) != 1
            or active[0].get("status") != "False"
            or active[0].get("reason") != "Retired"
        ):
            raise inventory.InventoryError(
                "another API revision may execute legacy background work"
            )
        retired = active[0].get("lastTransitionTime")
        inventory._evidence_time(retired, "revision retirement")
        retired_revisions[name] = {
            "retired_at": retired,
            "timeout_seconds": row.get("spec", {}).get("timeoutSeconds"),
            "annotations": row.get("metadata", {}).get("annotations", {}),
        }
    if current not in names:
        raise inventory.InventoryError("serving API revision missing from inventory")
    return retired_revisions


def _older_retired_revisions(current: str, *, project: str, region: str) -> dict[str, str]:
    return {
        name: row["retired_at"] for name, row in _retired_revision_inventory(
            current, project=project, region=region
        ).items()
    }


def _stop_proof(
    revisions: dict[str, dict], *, project: str, region: str,
    native_required: str | None = None,
) -> dict[str, dict]:
    now = datetime.now(UTC)
    native: dict[str, str] = {}
    proof: dict[str, dict] = {}
    for name, row in revisions.items():
        retired = inventory._evidence_time(row["retired_at"], "revision retirement")
        if name == native_required or retired + timedelta(minutes=30) >= now - RETENTION:
            native[name] = row["retired_at"]
            continue
        timeout = row.get("timeout_seconds")
        annotations = row.get("annotations")
        if (
            type(timeout) is not int or not 1 <= timeout <= 3600
            or not isinstance(annotations, dict)
            or annotations.get("run.googleapis.com/cpu-throttling", "true") != "true"
            or annotations.get("run.googleapis.com/scalingMode", "automatic") != "automatic"
        ):
            raise inventory.InventoryError("historical runtime bounds are unverified")
        # No traffic, effective minimum or manual scaling can reactivate this
        # expired cohort. Autoscaling supplies operational retirement evidence,
        # not a physical execution deadline or fabricated missing metric zero.
        proof[name] = {
            "basis": "historical_autoscale_inference",
            "verdict": "operational_retirement_inference_not_physical_stop_proof",
            "retired_at": row["retired_at"], "checked_at": now.isoformat(),
            "request_timeout_seconds": timeout,
            "retirement_age_seconds": int((now - retired).total_seconds()),
            "routing": "untagged_unreferenced_retired", "minimum_allocation": 0,
            "source": "https://docs.cloud.google.com/run/docs/about-instance-autoscaling",
            "minimum_source": "https://docs.cloud.google.com/run/docs/configuring/min-instances",
            "limits": [
                "not_native_instance_measurement_or_physical_termination_proof",
                "does_not_release_prior_locks_or_cancel_already_issued_provider_work",
            ],
        }
    proof.update(prove_stopped(native, project=project, region=region))
    return proof


def _worker(*, project: str, region: str, executor: Executor = DOCUMENT) -> tuple[str, dict]:
    job = _call(
        ["run", "jobs", "describe", executor.job, "--format=json"],
        project=project,
        region=region,
    )
    containers = (
        job.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    if len(containers) != 1:
        raise inventory.InventoryError(
            "document worker container contract is unverified"
        )
    container = containers[0]
    env = _env(container)
    if (
        env.get(executor.protocol) != "1"
        or env.get(executor.admission) not in ("true", "false")
        or container.get("command") != [executor.command]
        or container.get("args") != list(executor.args)
        or not inventory.DIGEST_IMAGE.fullmatch(container.get("image", ""))
    ):
        raise inventory.InventoryError(
            "document worker does not prove admission protocol 1"
        )
    return container["image"], env


def preflight(*, project: str, region: str, release_sha: str) -> dict:
    revision, _ = _service(project=project, region=region)
    image, env = _revision(revision, project=project, region=region)
    prior_sha = env.get("CASEOPS_RELEASE_SHA", "")
    if not inventory.RELEASE_SHA.fullmatch(prior_sha):
        raise inventory.InventoryError("captured API release SHA is unverified")
    older = _retired_revision_inventory(revision, project=project, region=region)
    older_stop_proof = _stop_proof(older, project=project, region=region)
    if _retired_revision_inventory(revision, project=project, region=region) != older:
        raise inventory.InventoryError("API retirement inventory changed during preflight")
    if _service(project=project, region=region)[0] != revision:
        raise inventory.InventoryError("API routing changed during preflight")
    return {
        "schema_version": 1, "project": project, "region": region,
        "release_sha": release_sha, "prior_revision": revision,
        "prior_release_sha": prior_sha, "rollback_image": image,
        "older_retired_revisions": older, "older_instance_stop_proof": older_stop_proof,
    }


def prepare(
    *, project: str, region: str, release_sha: str, executor: Executor = DOCUMENT,
) -> dict:
    capture = preflight(project=project, region=region, release_sha=release_sha)
    _, env = _revision(capture["prior_revision"], project=project, region=region)
    job_exists = inventory.run_job_exists(executor.job, project=project, region=region)
    scheduler_exists = inventory.scheduler_exists(
        executor.scheduler, project=project, location=region
    )
    if job_exists != scheduler_exists:
        raise inventory.InventoryError("document job and scheduler existence disagree")
    if job_exists:
        prior_job_image, _ = _worker(project=project, region=region, executor=executor)
        _call(
            [
                "run",
                "jobs",
                "update",
                executor.job,
                "--update-env-vars",
                f"{executor.admission}=false",
                "--quiet",
            ],
            project=project,
            region=region,
            json_result=False,
        )
        actual_image, actual_env = _worker(project=project, region=region, executor=executor)
        if actual_image != prior_job_image or actual_env.get(executor.admission) != "false":
            raise inventory.InventoryError(
                "document admission disablement was not verified"
            )
    elif env.get(executor.mode_key) == "cloud_run_job":
        raise inventory.InventoryError("independent API executor has no durable worker")
    return {
        **capture,
        "executor": executor.job,
        "legacy_api_executor": env.get(executor.mode_key) != "cloud_run_job",
        "worker_preexisting": job_exists,
        "admission_disabled": True,
    }


def activate(
    state: dict, *, project: str, region: str, release_sha: str, image: str,
    executor: Executor = DOCUMENT,
) -> dict:
    if (
        state.get("schema_version") != 1
        or state.get("executor") != executor.job
        or state.get("project") != project
        or state.get("region") != region
        or state.get("release_sha") != release_sha
        or state.get("admission_disabled") is not True
        or not inventory.DIGEST_IMAGE.fullmatch(state.get("rollback_image", ""))
    ):
        raise inventory.InventoryError("document release capture is invalid or stale")
    current, _ = _service(project=project, region=region)
    current_image, env = _revision(current, project=project, region=region)
    if (
        current_image != image
        or env.get("CASEOPS_RELEASE_SHA") != release_sha
        or env.get(executor.mode_key) != "cloud_run_job"
        or env.get(executor.target_key) != executor.job
        or env.get(executor.region_key) != region
        or env.get("CASEOPS_GCP_PROJECT_ID") != project
    ):
        raise inventory.InventoryError(
            "independent exact-release API executor is unverified"
        )
    worker_image, worker_env = _worker(project=project, region=region, executor=executor)
    if worker_image != image or worker_env.get(executor.admission) != "false":
        raise inventory.InventoryError(
            "replacement document worker is not disabled at the exact image"
        )
    prior = state.get("prior_revision", "")
    if prior == current and state.get("legacy_api_executor") is True:
        raise inventory.InventoryError("captured legacy executor is still serving")
    if prior != current:
        prior_image, prior_env = _revision(prior, project=project, region=region)
        if prior_image != state["rollback_image"] or prior_env.get(
            "CASEOPS_RELEASE_SHA"
        ) != state.get("prior_release_sha"):
            raise inventory.InventoryError("legacy API revision changed since capture")
    retired = _retired_revision_inventory(current, project=project, region=region)
    # The captured serving revision always requires measured active/idle zeros,
    # even if an interrupted rollout is resumed after Monitoring retention.
    stop_proof = _stop_proof(
        retired, project=project, region=region, native_required=prior,
    )
    if _retired_revision_inventory(current, project=project, region=region) != retired:
        raise inventory.InventoryError(
            "API retirement inventory changed during stop verification"
        )
    if _service(project=project, region=region)[0] != current:
        raise inventory.InventoryError("API routing changed before document admission")
    try:
        _call(
            [
                "run",
                "jobs",
                "update",
                executor.job,
                "--update-env-vars",
                f"{executor.admission}=true",
                "--quiet",
            ],
            project=project,
            region=region,
            json_result=False,
        )
        actual_image, actual_env = _worker(project=project, region=region, executor=executor)
        if actual_image != image or actual_env.get(executor.admission) != "true":
            raise inventory.InventoryError("document admission readback failed")
    except inventory.InventoryError:
        _call(
            [
                "run",
                "jobs",
                "update",
                executor.job,
                "--update-env-vars",
                f"{executor.admission}=false",
                "--quiet",
            ],
            project=project,
            region=region,
            json_result=False,
        )
        raise
    return {
        **state,
        "serving_revision": current,
        "prior_revision_preserved": prior,
        "instance_stop_proof": stop_proof,
        "worker_image": image,
        "admission_enabled": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "prepare", "activate"))
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--state", type=Path)
    parser.add_argument("--image")
    parser.add_argument("--worker", choices=tuple(EXECUTORS), default="document")
    args = parser.parse_args(argv)
    try:
        canonical = inventory.load_inventory(inventory.DEFAULT_INVENTORY)
        if (
            args.project != canonical["production_project"]
            or args.region != canonical["location"]
            or not inventory.RELEASE_SHA.fullmatch(args.release_sha)
        ):
            raise inventory.InventoryError(
                "document rollout requires canonical production and exact SHA"
            )
        if args.command == "preflight":
            receipt = preflight(
                project=args.project, region=args.region, release_sha=args.release_sha,
            )
        elif args.command == "prepare":
            receipt = prepare(
                project=args.project, region=args.region, release_sha=args.release_sha,
                executor=EXECUTORS[args.worker],
            )
        else:
            if args.state is None or not inventory.DIGEST_IMAGE.fullmatch(
                args.image or ""
            ):
                raise inventory.InventoryError(
                    "activation requires captured state and immutable image"
                )
            state = json.loads(args.state.read_text(encoding="utf-8"))
            receipt = activate(
                state,
                project=args.project,
                region=args.region,
                release_sha=args.release_sha,
                image=args.image,
                executor=EXECUTORS[args.worker],
            )
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (inventory.InventoryError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"document worker release failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
