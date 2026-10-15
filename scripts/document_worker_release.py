#!/usr/bin/env python3
"""Fence queue admission and prove legacy executor quiescence before activation."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
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


def _call(arguments: list[str], *, project: str, region: str, json_result=True, timeout=90):
    return inventory.run_gcloud(
        [*arguments, "--project", project, "--region", region],
        expect_json=json_result,
        timeout=timeout,
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


def _qa_object(value: object) -> dict:
    if not isinstance(value, dict):
        raise inventory.InventoryError("QA quiescence resource metadata is invalid")
    return value


def _qa_environment(container: dict) -> dict:
    environment = container.get("env")
    if not isinstance(environment, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("name"), str) or not row["name"]
        for row in environment
    ):
        raise inventory.InventoryError("QA quiescence database environment is invalid")
    return _env(container)


def _qa_database_reference(container: dict) -> dict:
    _qa_environment(container)
    environment = container["env"]
    rows = [row for row in environment if row.get("name") == "CASEOPS_DATABASE_URL"]
    if len(rows) != 1:
        raise inventory.InventoryError("QA quiescence database secret is missing or ambiguous")
    reference = _qa_object(_qa_object(rows[0].get("valueFrom")).get("secretKeyRef"))
    if (
        set(reference) != {"name", "key"}
        or reference.get("name") != "caseops-database-url"
        or not isinstance(reference.get("key"), str)
        or not re.fullmatch(r"latest|[1-9][0-9]*", reference["key"])
        or rows[0]
        != {
            "name": "CASEOPS_DATABASE_URL",
            "valueFrom": {"secretKeyRef": reference},
        }
    ):
        raise inventory.InventoryError("QA quiescence database secret binding is invalid")
    return copy.deepcopy(reference)


def _qa_database_alias(annotations: dict, *, project: str, namespace: str) -> None:
    aliases = annotations.get("run.googleapis.com/secrets")
    if aliases is None:
        return
    if not isinstance(aliases, str) or len(aliases) > 65_536:
        raise inventory.InventoryError("QA quiescence secret alias metadata is invalid")
    matches = []
    for binding in aliases.split(","):
        alias, separator, resource = binding.partition(":")
        if alias.strip() == "caseops-database-url":
            matches.append(resource.strip() if separator else "")
    if len(matches) > 1 or any(
        value
        not in {
            f"projects/{project}/secrets/caseops-database-url",
            f"projects/{namespace}/secrets/caseops-database-url",
        }
        for value in matches
    ):
        raise inventory.InventoryError("QA quiescence database alias targets another authority")


def _qa_database_version(reference: dict, *, project: str, namespace: str) -> str:
    # Secret Manager is global. Never use the regional Cloud Run wrapper or access values.
    payload = _qa_object(
        inventory.run_gcloud(
            [
                "secrets",
                "versions",
                "describe",
                reference["key"],
                "--secret",
                "caseops-database-url",
                "--project",
                project,
                "--quiet",
                "--format=json",
            ],
            expect_json=True,
            timeout=30,
        )
    )
    name = payload.get("name")
    match = re.fullmatch(
        r"projects/([^/]+)/secrets/caseops-database-url/versions/([1-9][0-9]*)",
        name if isinstance(name, str) else "",
    )
    if (
        match is None
        or match[1] not in (project, namespace)
        or payload.get("state") != "ENABLED"
        or reference["key"] not in ("latest", match[2])
    ):
        raise inventory.InventoryError("QA quiescence database secret version is unverified")
    return match[2]


def _qa_quiescence_runtime(
    *,
    project: str,
    region: str,
    release_sha: str,
    image: str,
) -> tuple[str, dict, dict]:
    revision, _ = _service(project=project, region=region)
    serving = _qa_object(
        _call(
            ["run", "revisions", "describe", revision, "--format=json"],
            project=project,
            region=region,
            timeout=30,
        )
    )
    metadata = _qa_object(serving.get("metadata"))
    namespace = metadata.get("namespace")
    containers = _qa_object(serving.get("spec")).get("containers")
    if (
        metadata.get("name") != revision
        or _qa_object(metadata.get("labels")).get("serving.knative.dev/service") != SERVICE
        or not isinstance(namespace, str)
        or not re.fullmatch(r"[1-9][0-9]*", namespace)
        or not isinstance(containers, list)
        or any(not isinstance(row, dict) for row in containers)
    ):
        raise inventory.InventoryError("QA quiescence serving API authority is invalid")
    api = [row for row in containers if row.get("name") == "api"]
    if len(api) != 1:
        raise inventory.InventoryError("QA quiescence serving API container is ambiguous")
    job = _qa_object(
        _call(
            ["run", "jobs", "describe", JOB, "--format=json"],
            project=project,
            region=region,
            timeout=30,
        )
    )
    job_metadata = _qa_object(job.get("metadata"))
    template = _qa_object(_qa_object(job.get("spec")).get("template"))
    execution_spec = _qa_object(template.get("spec"))
    task = _qa_object(_qa_object(execution_spec.get("template")).get("spec"))
    if (
        type(execution_spec.get("taskCount")) is not int
        or execution_spec["taskCount"] != 1
        or "taskCount" in task
    ):
        raise inventory.InventoryError("QA quiescence requires an explicit single-task worker template")
    workers = task.get("containers")
    if not isinstance(workers, list) or len(workers) != 1 or not isinstance(workers[0], dict):
        raise inventory.InventoryError("QA quiescence worker template is invalid")
    worker = workers[0]
    env = _qa_environment(worker)
    if (
        api[0].get("image") != image
        or worker.get("image") != image
        or _qa_environment(api[0]).get("CASEOPS_RELEASE_SHA") != release_sha
        or env.get(PROTOCOL) != "1"
        or env.get(ADMISSION) != "true"
        or worker.get("command") != [DOCUMENT.command]
        or worker.get("args") != list(DOCUMENT.args)
        or type(task.get("maxRetries")) is not int
        or task["maxRetries"] != 0
    ):
        raise inventory.InventoryError("QA quiescence requires the enabled exact-release worker")
    generation = str(job_metadata.get("generation", ""))
    status = _qa_object(job.get("status"))
    conditions = status.get("conditions")
    if not isinstance(conditions, list) or any(not isinstance(row, dict) for row in conditions):
        raise inventory.InventoryError("QA quiescence worker readiness metadata is invalid")
    ready = [row for row in conditions if row.get("type") == "Ready"]
    if (
        job_metadata.get("name") != JOB
        or job_metadata.get("namespace") != namespace
        or not re.fullmatch(r"[1-9][0-9]*", generation)
        or str(status.get("observedGeneration")) != generation
        or len(ready) != 1
        or ready[0].get("status") != "True"
    ):
        raise inventory.InventoryError("QA quiescence worker generation or namespace is invalid")
    cloud_sql = f"{project}:{region}:caseops-db"
    annotation = "run.googleapis.com/cloudsql-instances"
    api_annotations = _qa_object(metadata.get("annotations"))
    worker_annotations = _qa_object(_qa_object(template.get("metadata")).get("annotations"))
    if (
        api_annotations.get(annotation) != cloud_sql
        or worker_annotations.get(annotation) != cloud_sql
    ):
        raise inventory.InventoryError("QA quiescence Cloud SQL database authority is invalid")
    _qa_database_alias(api_annotations, project=project, namespace=namespace)
    _qa_database_alias(worker_annotations, project=project, namespace=namespace)
    api_reference = _qa_database_reference(api[0])
    worker_reference = _qa_database_reference(worker)
    api_version = _qa_database_version(api_reference, project=project, namespace=namespace)
    worker_version = _qa_database_version(worker_reference, project=project, namespace=namespace)
    if api_version != worker_version:
        raise inventory.InventoryError("QA quiescence API and worker database versions differ")
    return (
        revision,
        job,
        {
            "api_revision": revision,
            "namespace": namespace,
            "api_database_reference": api_reference,
            "worker_database_reference": worker_reference,
            "database_version": api_version,
            "cloud_sql_instance": cloud_sql,
            "worker_generation": generation,
            "worker_task": copy.deepcopy(task),
            "api_annotations": api_annotations,
            "worker_annotations": worker_annotations,
        },
    )


def quiesce_qa(*, project: str, region: str, release_sha: str, image: str) -> dict:
    revision, job, authority = _qa_quiescence_runtime(
        project=project,
        region=region,
        release_sha=release_sha,
        image=image,
    )
    arguments = [*DOCUMENT.args, "--require-qa-quiescence"]
    expected_task = (
        job.get("spec", {}).get("template", {}).get("spec", {}).get("template", {}).get("spec", {})
    )
    expected_containers = expected_task.get("containers", [])
    if (
        len(expected_containers) != 1
        or expected_containers[0].get("image") != image
        or expected_containers[0].get("command") != [DOCUMENT.command]
        or expected_containers[0].get("args") != list(DOCUMENT.args)
        or _env(expected_containers[0]).get(ADMISSION) != "true"
        or expected_task.get("maxRetries") != 0
    ):
        raise inventory.InventoryError("QA quiescence worker template changed before execution")
    expected_container = copy.deepcopy(expected_containers[0])
    expected_container["args"] = arguments
    dispatched_at = datetime.now(UTC)
    response = _call(
        [
            "run",
            "jobs",
            "execute",
            JOB,
            "--async",
            "--quiet",
            "--format=json",
            inventory._gcloud_args_flag(arguments),
        ],
        project=project,
        region=region,
    )
    name = str(response.get("metadata", {}).get("name", "")).rsplit("/", 1)[-1]
    if not re.fullmatch(r"caseops-document-processing-[a-z0-9]+", name):
        raise inventory.InventoryError("QA quiescence execution identity is missing")
    deadline = time.monotonic() + 360
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise inventory.InventoryError("QA quiescence execution deadline; no QA dispatched")
        execution = _qa_object(
            _call(
                [
                    "run",
                    "jobs",
                    "executions",
                    "describe",
                    name,
                    "--format=json",
                ],
                project=project,
                region=region,
                timeout=min(30, remaining),
            )
        )
        status = _qa_object(execution.get("status"))
        outcomes = status.get("conditions")
        if not isinstance(outcomes, list) or any(not isinstance(row, dict) for row in outcomes):
            raise inventory.InventoryError("QA quiescence execution outcome metadata is invalid")
        conditions = [row for row in outcomes if row.get("type") == "Completed"]
        if len(conditions) > 1:
            raise inventory.InventoryError("QA quiescence execution has conflicting outcomes")
        if conditions and str(conditions[0].get("status")).lower() in {"true", "false"}:
            break
        time.sleep(min(5, max(0, deadline - time.monotonic())))
    metadata = _qa_object(execution.get("metadata"))
    labels = _qa_object(metadata.get("labels"))
    annotations = _qa_object(metadata.get("annotations"))
    spec = _qa_object(execution.get("spec"))
    task = _qa_object(_qa_object(spec.get("template")).get("spec"))
    containers = task.get("containers", [])
    if (
        str(metadata.get("name", "")).rsplit("/", 1)[-1] != name
        or labels.get("run.googleapis.com/job") != JOB
        or metadata.get("namespace") != authority["namespace"]
        or labels.get("run.googleapis.com/jobGeneration") != authority["worker_generation"]
        or annotations.get("run.googleapis.com/cloudsql-instances")
        != authority["cloud_sql_instance"]
        or type(spec.get("taskCount")) is not int
        or spec["taskCount"] != 1
        or not isinstance(containers, list)
        or len(containers) != 1
        or containers[0] != expected_container
        or containers[0].get("image") != image
        or containers[0].get("command") != [DOCUMENT.command]
        or containers[0].get("args") != arguments
        or str(conditions[0].get("status")).lower() != "true"
        or type(status.get("succeededCount")) is not int
        or status["succeededCount"] != 1
        or status.get("failedCount", 0) not in (None, 0)
        or status.get("cancelledCount", 0) not in (None, 0)
        or type(task.get("maxRetries")) is not int
        or task["maxRetries"] != 0
        or task.get("serviceAccountName") != expected_task.get("serviceAccountName")
    ):
        raise inventory.InventoryError("QA quiescence execution contract or outcome is invalid")
    _qa_database_alias(annotations, project=project, namespace=authority["namespace"])
    started = inventory._evidence_time(status.get("startTime"), "QA quiescence start")
    completed = inventory._evidence_time(status.get("completionTime"), "QA quiescence completion")
    if not dispatched_at <= started < completed <= datetime.now(UTC):
        raise inventory.InventoryError("QA quiescence execution timing is invalid")
    _, _, current_authority = _qa_quiescence_runtime(
        project=project,
        region=region,
        release_sha=release_sha,
        image=image,
    )
    if current_authority != authority:
        raise inventory.InventoryError(
            "API or worker database authority changed during QA quiescence"
        )
    return {
        "schema_version": 1,
        "release_sha": release_sha,
        "image": image,
        "api_revision": revision,
        "execution": name,
        "qa_queues_quiescent": True,
        "basis": "exact-image read-only queue gate completed successfully",
        "database_secret": "caseops-database-url",
        "database_version": authority["database_version"],
        "cloud_sql_instance": authority["cloud_sql_instance"],
        "worker_generation": authority["worker_generation"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "prepare", "activate", "quiesce-qa"))
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
        elif args.command == "quiesce-qa":
            if args.worker != "document" or not inventory.DIGEST_IMAGE.fullmatch(args.image or ""):
                raise inventory.InventoryError("QA quiescence requires the immutable document image")
            receipt = quiesce_qa(
                project=args.project, region=args.region, release_sha=args.release_sha,
                image=args.image,
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
