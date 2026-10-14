"""Optional one-shot release control; no input means no cloud calls or grant."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from scheduler_inventory import run_gcloud

PROJECT = "perfect-period-305406"
REGION = "asia-south1"
JOB = "caseops-test-legal-manual-ip-grant"
MODULE = "caseops_api.scripts.qa_manual_ip_entitlement"
SERVICE_ACCOUNT = f"caseops-runtime@{PROJECT}.iam.gserviceaccount.com"
CLOUD_SQL = f"{PROJECT}:{REGION}:caseops-db"
IMAGE_PREFIX = f"{REGION}-docker.pkg.dev/{PROJECT}/caseops-images/caseops-api@sha256:"
MAX_INPUT = 8_192
MAX_OUTPUT = 200_000
ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(RuntimeError):
    """Only constant, non-sensitive diagnostic codes leave this control."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReleaseError(code)


def _object(value: Any) -> dict:
    _require(isinstance(value, dict), "invalid_object")
    return value


def _array(value: Any) -> list:
    _require(isinstance(value, list), "invalid_array")
    return value


def _number(value: Any, *, minimum: int = 0) -> int:
    _require(type(value) is int and minimum <= value <= 1_000_000, "invalid_count")
    return value


def _uuid(value: Any) -> None:
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        valid = False
    _require(valid, "invalid_identifier")


def _unique(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for name, value in pairs:
        _require(name not in result, "duplicate_json_key")
        result[name] = value
    return result


def preflight(input_path: str | None, output_path: str | None) -> tuple[dict, str] | None:
    if not input_path:
        _require(not output_path, "output_without_input")
        return None
    _require(bool(output_path), "evidence_output_required")
    source, output = Path(input_path), Path(output_path)
    _require(
        source.is_absolute()
        and output.is_absolute()
        and not source.resolve().is_relative_to(ROOT.resolve())
        and not output.resolve().is_relative_to(ROOT.resolve()),
        "invalid_grant_paths",
    )
    _require(source.is_file() and not source.is_symlink(), "invalid_input_path")
    _require(not output.exists() and not output.is_symlink(), "evidence_already_exists")
    _require(output.parent.is_dir() and source.resolve() != output.resolve(), "invalid_output_path")
    try:
        with source.open("rb") as stream:
            raw = stream.read(MAX_INPUT + 1)
        _require(0 < len(raw) <= MAX_INPUT, "input_bounds")
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        raise ReleaseError("invalid_input_json") from None
    value = _object(value)
    _require(
        set(value)
        == {
            "schema_version",
            "company_id",
            "subscription_id",
            "before_sha256",
            "operation_id",
        },
        "invalid_input_fields",
    )
    _require(
        type(value["schema_version"]) is int and value["schema_version"] == 1,
        "invalid_input_version",
    )
    for key in ("company_id", "subscription_id", "operation_id"):
        _uuid(value[key])
    _require(
        isinstance(value["before_sha256"], str)
        and re.fullmatch(r"[a-f0-9]{64}", value["before_sha256"]) is not None,
        "invalid_before_fingerprint",
    )
    canonical = json.dumps(value, separators=(",", ":"), sort_keys=True)
    return value, hashlib.sha256(canonical.encode()).hexdigest()


def _cloud(arguments: list[str], *, timeout: float = 30) -> Any:
    try:
        value = run_gcloud(arguments, expect_json=True, timeout=timeout)
        _require(len(json.dumps(value).encode()) <= MAX_OUTPUT, "cloud_output_bounds")
        return value
    except ReleaseError:
        raise
    except Exception:
        raise ReleaseError("cloud_command_failed") from None


def _flags() -> list[str]:
    return ["--project", PROJECT, "--region", REGION, "--format=json"]


def _serving_release(image: str, release: str) -> dict:
    service = _object(_cloud(["run", "services", "describe", "caseops-api", *_flags()]))
    metadata, status = _object(service.get("metadata")), _object(service.get("status"))
    _require(
        re.fullmatch(r"[1-9][0-9]*", str(metadata.get("generation"))) is not None
        and str(metadata["generation"]) == str(status.get("observedGeneration")),
        "serving_generation_drift",
    )
    latest = status.get("latestReadyRevisionName")
    _require(
        isinstance(latest, str)
        and re.fullmatch(r"caseops-api-[a-z0-9-]+", latest) is not None
        and latest == status.get("latestCreatedRevisionName"),
        "serving_revision_drift",
    )
    for key in ("Ready", "ConfigurationsReady", "RoutesReady"):
        conditions = [
            row for row in _array(status.get("conditions")) if _object(row).get("type") == key
        ]
        _require(
            len(conditions) == 1 and str(conditions[0].get("status")).lower() == "true",
            "serving_not_ready",
        )
    traffic = _array(status.get("traffic"))
    _require(
        len(traffic) == 1
        and _object(traffic[0]).get("revisionName") == latest
        and type(traffic[0].get("percent")) is int
        and traffic[0]["percent"] == 100
        and not traffic[0].get("tag"),
        "serving_traffic_drift",
    )
    revision = _object(_cloud(["run", "revisions", "describe", latest, *_flags()]))
    _require(_object(revision.get("metadata")).get("name") == latest, "serving_revision_identity")
    containers = _array(_object(revision.get("spec")).get("containers"))
    api = [row for row in containers if _object(row).get("name") == "api"]
    _require(len(api) == 1 and api[0].get("image") == image, "serving_image_drift")
    labels = [
        row
        for row in _array(api[0].get("env"))
        if _object(row).get("name") == "CASEOPS_RELEASE_SHA"
    ]
    _require(labels == [{"name": "CASEOPS_RELEASE_SHA", "value": release}], "serving_release_drift")
    references = {}
    for name, secret in (
        ("CASEOPS_DATABASE_URL", "caseops-database-url"),
        ("CASEOPS_AUTH_SECRET", "caseops-auth-secret"),
    ):
        rows = [row for row in api[0]["env"] if _object(row).get("name") == name]
        _require(len(rows) == 1 and set(rows[0]) == {"name", "valueFrom"}, "serving_secret_drift")
        reference = _object(_object(rows[0]["valueFrom"]).get("secretKeyRef"))
        _require(
            set(reference) == {"name", "key"}
            and reference["name"] == secret
            and isinstance(reference["key"], str)
            and re.fullmatch(r"latest|[1-9][0-9]*", reference["key"]) is not None,
            "serving_secret_drift",
        )
        references[name] = reference
    return {
        "revision": latest,
        "image": image,
        "release_sha": release,
        "secret_references": references,
    }


def assert_current_main(release: str) -> None:
    try:
        values = []
        for args in (["rev-parse", "HEAD"], ["ls-remote", "origin", "refs/heads/main"]):
            result = subprocess.run(
                ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=30, check=False
            )
            _require(
                result.returncode == 0 and len(result.stdout) < 1_024, "canonical_main_unavailable"
            )
            values.append(result.stdout.strip().split()[0])
        _require(values == [release, release], "canonical_main_changed")
    except (OSError, subprocess.TimeoutExpired, IndexError):
        raise ReleaseError("canonical_main_unavailable") from None


def _args(request: dict) -> list[str]:
    return [
        "-m",
        MODULE,
        "grant",
        "--company-id",
        request["company_id"],
        "--subscription-id",
        request["subscription_id"],
        "--expected-before-sha256",
        request["before_sha256"],
        "--operation-id",
        request["operation_id"],
    ]


def _environment(container: dict, release: str, secrets: dict[str, str]) -> None:
    rows = _array(container.get("env"))
    names = [row.get("name") for row in rows if isinstance(row, dict)]
    _require(
        all(isinstance(name, str) for name in names) and len(names) == len(rows) == len(set(names)),
        "environment_identity",
    )
    values = {row["name"]: row for row in rows}
    literal = {
        "CASEOPS_ENV": "cloud",
        "CASEOPS_AUTO_MIGRATE": "false",
        "CASEOPS_RELEASE_SHA": release,
    }
    _require(set(values) == set(literal) | set(secrets), "unexpected_environment")
    for name, expected in literal.items():
        _require(values[name] == {"name": name, "value": expected}, "environment_drift")
    for name, version in secrets.items():
        secret_name = (
            "caseops-database-url" if name == "CASEOPS_DATABASE_URL" else "caseops-auth-secret"
        )
        _require(
            values[name]
            == {"name": name, "valueFrom": {"secretKeyRef": {"name": secret_name, "key": version}}},
            "secret_drift",
        )


def _task(task: dict, image: str, release: str, args: list[str], secrets: dict) -> None:
    _require(task.get("serviceAccountName") == SERVICE_ACCOUNT, "service_account_drift")
    _require(type(task.get("maxRetries")) is int and task["maxRetries"] == 0, "retry_drift")
    _require(
        type(task.get("timeoutSeconds")) in (int, str)
        and str(task["timeoutSeconds"]) in ("180", "180s"),
        "timeout_drift",
    )
    _require(task.get("volumes") in (None, []), "unexpected_volumes")
    containers = _array(task.get("containers"))
    _require(len(containers) == 1, "container_count_drift")
    container = _object(containers[0])
    _require(
        container.get("image") == image
        and container.get("command") == ["python"]
        and container.get("args") == args,
        "image_command_drift",
    )
    _require(
        not container.get("volumeMounts") and not container.get("workingDir"),
        "unexpected_container_override",
    )
    limits = _object(_object(container.get("resources")).get("limits"))
    _require(
        set(limits) == {"cpu", "memory"}
        and limits["cpu"] in ("1", "1000m")
        and limits["memory"] == "512Mi",
        "resource_drift",
    )
    _environment(container, release, secrets)


def validate_job(value: Any, image: str, release: str, args: list[str], secrets: dict) -> dict:
    value = _object(value)
    metadata, status = _object(value.get("metadata")), _object(value.get("status"))
    _require(
        metadata.get("name") == JOB
        and isinstance(metadata.get("uid"), str)
        and re.fullmatch(r"[a-zA-Z0-9-]{1,64}", metadata["uid"]) is not None,
        "job_identity",
    )
    generation = str(metadata.get("generation"))
    _require(
        re.fullmatch(r"[1-9][0-9]*", generation) is not None
        and generation == str(status.get("observedGeneration")),
        "job_generation",
    )
    labels = _object(metadata.get("labels"))
    _require(
        labels.get("caseops-release") == release
        and labels.get("caseops-control") == "test-legal-manual-ip",
        "release_label_drift",
    )
    ready = [
        item for item in _array(status.get("conditions")) if _object(item).get("type") == "Ready"
    ]
    _require(len(ready) == 1 and str(ready[0].get("status")).lower() == "true", "job_not_ready")
    template = _object(_object(value.get("spec")).get("template"))
    annotations = _object(_object(template.get("metadata")).get("annotations"))
    _require(
        annotations.get("run.googleapis.com/cloudsql-instances") == CLOUD_SQL, "cloud_sql_drift"
    )
    spec = _object(template.get("spec"))
    _require(
        type(spec.get("taskCount")) is int
        and spec["taskCount"] == 1
        and type(spec.get("parallelism")) is int
        and spec["parallelism"] == 1,
        "job_task_shape",
    )
    _task(_object(_object(spec.get("template")).get("spec")), image, release, args, secrets)
    return {
        "generation": generation,
        "uid": metadata["uid"],
        "execution_count": _number(status.get("executionCount", 0)),
        "latest": _object(status.get("latestCreatedExecution", {})).get("name", ""),
    }


def validate_execution(
    value: Any, name: str, job: dict, image: str, release: str, args: list[str], secrets: dict
) -> None:
    value = _object(value)
    metadata, spec, status = (_object(value.get(key)) for key in ("metadata", "spec", "status"))
    labels = _object(metadata.get("labels"))
    _require(
        str(metadata.get("name", "")).rsplit("/", 1)[-1] == name
        and labels.get("run.googleapis.com/job") == JOB
        and labels.get("run.googleapis.com/jobGeneration") == job["generation"],
        "execution_identity",
    )
    owners = _array(metadata.get("ownerReferences"))
    _require(
        any(
            _object(row).get("name") == JOB
            and row.get("uid") == job["uid"]
            and row.get("kind") == "Job"
            for row in owners
        ),
        "execution_owner",
    )
    _require(
        type(spec.get("taskCount")) is int
        and spec["taskCount"] == 1
        and type(spec.get("parallelism")) is int
        and spec["parallelism"] == 1,
        "execution_task_shape",
    )
    template = _object(spec.get("template"))
    _require(set(template) == {"spec"}, "execution_template_shape")
    annotations = _object(metadata.get("annotations"))
    _require(
        annotations.get("run.googleapis.com/cloudsql-instances") == CLOUD_SQL, "execution_cloud_sql"
    )
    _task(_object(template.get("spec")), image, release, args, secrets)
    conditions = [
        row for row in _array(status.get("conditions")) if _object(row).get("type") == "Completed"
    ]
    _require(
        len(conditions) == 1
        and str(conditions[0].get("status")).lower() == "true"
        and _number(status.get("succeededCount")) == 1
        and _number(status.get("failedCount", 0)) == 0
        and _number(status.get("cancelledCount", 0)) == 0
        and _number(status.get("runningCount", 0)) == 0
        and _number(status.get("retriedCount", 0)) == 0,
        "execution_not_successful",
    )
    try:
        start, end = (
            datetime.fromisoformat(status[key].replace("Z", "+00:00"))
            for key in ("startTime", "completionTime")
        )
        _require(
            start.tzinfo is not None
            and end.tzinfo is not None
            and start < end <= datetime.now(UTC),
            "execution_time",
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ReleaseError("execution_time") from None


def _secrets(references: dict) -> dict[str, str]:
    project = _object(_cloud(["projects", "describe", PROJECT, "--format=json"]))
    number = str(project.get("projectNumber", ""))
    _require(
        project.get("projectId") == PROJECT and re.fullmatch(r"[0-9]+", number) is not None,
        "secret_project_mismatch",
    )
    result = {}
    for environment, name in (
        ("CASEOPS_DATABASE_URL", "caseops-database-url"),
        ("CASEOPS_AUTH_SECRET", "caseops-auth-secret"),
    ):
        value = _object(
            _cloud(
                [
                    "secrets",
                    "versions",
                    "describe",
                    references[environment]["key"],
                    "--secret",
                    name,
                    "--project",
                    PROJECT,
                    "--format=json",
                ]
            )
        )
        resource = str(value.get("name", ""))
        match = re.fullmatch(rf"projects/[^/]+/secrets/{name}/versions/([1-9][0-9]*)", resource)
        _require(
            match is not None
            and resource.split("/")[1] in (PROJECT, number)
            and value.get("state") == "ENABLED"
            and (
                references[environment]["key"] == "latest"
                or references[environment]["key"] == match[1]
            ),
            "secret_version_unavailable",
        )
        result[environment] = match[1]
    return result


def _no_scheduler() -> None:
    jobs = _array(
        _cloud(
            [
                "scheduler",
                "jobs",
                "list",
                "--location",
                REGION,
                "--project",
                PROJECT,
                "--format=json",
            ]
        )
    )
    _require(len(jobs) <= 200, "scheduler_inventory_bounds")
    for value in jobs:
        target = _object(_object(value).get("httpTarget", {}))
        uri = target.get("uri", "")
        _require(isinstance(uri, str), "invalid_scheduler_uri")
        try:
            path = unquote(urlsplit(uri).path)
        except ValueError:
            raise ReleaseError("invalid_scheduler_uri") from None
        # Reject this reserved job identity even through a numeric namespace,
        # regional endpoint or another-region target from this region's scheduler.
        targeted = re.fullmatch(
            rf"/(?:v2/projects/[^/]+/locations/[^/]+|"
            rf"apis/run\.googleapis\.com/v1/namespaces/[^/]+)/jobs/{JOB}:run/?",
            path,
        )
        _require(targeted is None, "unexpected_scheduler")


def _receipt(name: str, request: dict, *, mode: str = "grant", fingerprint: str = "") -> dict:
    query = (
        f'resource.type="cloud_run_job" AND resource.labels.job_name="{JOB}" AND '
        f'labels."run.googleapis.com/execution_name"="{name}" AND '
        f'logName="projects/{PROJECT}/logs/run.googleapis.com%2Fstdout" AND '
        '(jsonPayload:* OR textPayload:"schema_version")'
    )
    deadline = time.monotonic() + 45
    while True:
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "receipt_observation_deadline")
        rows = _array(
            _cloud(
                [
                    "logging",
                    "read",
                    query,
                    "--project",
                    PROJECT,
                    "--order=asc",
                    "--limit=3",
                    "--format=json",
                ],
                timeout=min(20, remaining),
            )
        )
        if rows:
            break
        time.sleep(min(2, max(0, deadline - time.monotonic())))
    _require(len(rows) == 1, "grant_receipt_count")
    row = _object(rows[0])
    resource = _object(row.get("resource"))
    labels = _object(row.get("labels"))
    _require(
        resource.get("type") == "cloud_run_job"
        and _object(resource.get("labels")).get("job_name") == JOB
        and resource["labels"].get("project_id") == PROJECT
        and resource["labels"].get("location") == REGION
        and labels.get("run.googleapis.com/execution_name") == name
        and labels.get("run.googleapis.com/task_attempt") == "0"
        and labels.get("run.googleapis.com/task_index") == "0",
        "grant_receipt_origin",
    )
    _require(
        row.get("logName") == f"projects/{PROJECT}/logs/run.googleapis.com%2Fstdout",
        "grant_receipt_origin",
    )
    _require(("jsonPayload" in row) != ("textPayload" in row), "grant_receipt_format")
    if "jsonPayload" in row:
        receipt = _object(row["jsonPayload"])
    else:
        payload = row.get("textPayload")
        _require(isinstance(payload, str), "grant_receipt_format")
        try:
            receipt = _object(json.loads(payload, object_pairs_hook=_unique))
        except (UnicodeError, json.JSONDecodeError, RecursionError):
            raise ReleaseError("grant_receipt_format") from None
    schema_types = (int, float) if "jsonPayload" in row else (int,)
    if mode == "inspect":
        _require(
            type(receipt.get("schema_version")) in schema_types
            and receipt
            == {
                "schema_version": 1,
                "mode": "inspect",
                "company_id": request["company_id"],
                "subscription_id": request["subscription_id"],
                "before_sha256": fingerprint,
            },
            "inspection_state_mismatch",
        )
        return receipt
    expected_request = {**request, "expected_before_sha256": request["before_sha256"]}
    del expected_request["before_sha256"]
    request_sha = hashlib.sha256(
        json.dumps(
            expected_request,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    _require(
        type(receipt.get("schema_version")) in schema_types
        and receipt["schema_version"] == 1
        and receipt.get("mode") == "grant"
        and receipt.get("replayed") is False
        and all(receipt.get(key) == value for key, value in request.items())
        and receipt.get("request_sha256") == request_sha
        and set(receipt)
        == set(request)
        | {
            "mode",
            "replayed",
            "request_sha256",
            "after_sha256",
            "audit_event_id",
        },
        "grant_receipt_mismatch",
    )
    _uuid(receipt.get("audit_event_id"))
    expected_audit = str(
        uuid5(NAMESPACE_URL, f"caseops:qa-manual-ip-entitlement:{request['operation_id']}")
    )
    _require(receipt["audit_event_id"] == expected_audit, "grant_audit_identity")
    _require(
        isinstance(receipt.get("after_sha256"), str)
        and re.fullmatch(r"[a-f0-9]{64}", receipt["after_sha256"]) is not None,
        "grant_after_fingerprint",
    )
    return receipt


def _execution_name(response: Any, previous: set[str]) -> str:
    response = _object(response)
    name = str(_object(response.get("metadata")).get("name", "")).rsplit("/", 1)[-1]
    _require(
        re.fullmatch(rf"{JOB}-[a-z0-9]+", name) is not None and name not in previous,
        "execution_response_identity",
    )
    return name


def _await_execution(
    response: Any,
    *,
    previous: set[str],
    job: dict,
    image: str,
    release: str,
    args: list[str],
    secrets: dict,
) -> str:
    name = _execution_name(response, previous)
    deadline = time.monotonic() + 300
    while True:
        remaining = deadline - time.monotonic()
        _require(remaining > 0, "execution_readback_deadline")
        execution = _object(
            _cloud(
                ["run", "jobs", "executions", "describe", name, *_flags()],
                timeout=min(30, remaining),
            )
        )
        status = _object(execution.get("status"))
        terminal = any(
            _object(row).get("type") == "Completed"
            and str(row.get("status")).lower() in ("true", "false")
            for row in _array(status.get("conditions"))
        )
        if terminal:
            break
        time.sleep(5)
    validate_execution(execution, name, job, image, release, args, secrets)
    return name


def execute(
    input_path: str | None,
    output_path: str | None,
    *,
    release: str,
    image: str,
    expected_input_sha256: str,
) -> dict:
    prepared = preflight(input_path, output_path)
    if prepared is None:
        return {"status": "not_requested"}
    request, digest = prepared
    _require(digest == expected_input_sha256, "grant_input_changed")
    _require(re.fullmatch(r"[a-f0-9]{40}", release) is not None, "invalid_release_sha")
    _require(
        image.startswith(IMAGE_PREFIX)
        and re.fullmatch(r"[a-f0-9]{64}", image[len(IMAGE_PREFIX) :]) is not None,
        "invalid_release_image",
    )
    evidence = {
        "schema_version": 1,
        "release_sha": release,
        "image": image,
        "input_sha256": digest,
        "request": request,
        "status": "started",
        "execute_attempted": False,
    }
    with Path(output_path).open("x", encoding="utf-8") as stream:

        def record() -> None:
            stream.seek(0)
            stream.truncate()
            json.dump(evidence, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())

        record()
        try:
            assert_current_main(release)
            evidence["serving"] = _serving_release(image, release)
            record()
            _no_scheduler()
            jobs = _array(
                _cloud(
                    [
                        "run",
                        "jobs",
                        "list",
                        "--filter",
                        f"metadata.name={JOB}",
                        "--limit=2",
                        *_flags(),
                    ]
                )
            )
            _require(
                len(jobs) <= 1
                and all(_object(_object(row).get("metadata")).get("name") == JOB for row in jobs),
                "job_inventory_identity",
            )
            existing = (
                _array(
                    _cloud(
                        [
                            "run",
                            "jobs",
                            "executions",
                            "list",
                            "--job",
                            JOB,
                            "--limit=101",
                            *_flags(),
                        ]
                    )
                )
                if jobs
                else []
            )
            _require(len(existing) <= 100, "execution_inventory_bounds")
            for row in existing:
                status = _object(_object(row).get("status"))
                labels = _object(_object(_object(row).get("metadata")).get("labels"))
                _require(labels.get("run.googleapis.com/job") == JOB, "existing_execution_identity")
                _require(bool(status.get("completionTime")), "existing_execution_unfinished")
            secrets = _secrets(evidence["serving"]["secret_references"])
            args = _args(request)
            assert_current_main(release)
            _cloud(
                [
                    "run",
                    "jobs",
                    "deploy",
                    JOB,
                    "--image",
                    image,
                    "--command",
                    "python",
                    "--args",
                    "^|^" + "|".join(args),
                    "--service-account",
                    SERVICE_ACCOUNT,
                    "--set-env-vars",
                    f"CASEOPS_ENV=cloud,CASEOPS_AUTO_MIGRATE=false,CASEOPS_RELEASE_SHA={release}",
                    "--set-secrets",
                    ",".join(
                        f"{key}={name}:{secrets[key]}"
                        for key, name in (
                            ("CASEOPS_DATABASE_URL", "caseops-database-url"),
                            ("CASEOPS_AUTH_SECRET", "caseops-auth-secret"),
                        )
                    ),
                    "--set-cloudsql-instances",
                    CLOUD_SQL,
                    "--cpu",
                    "1",
                    "--memory",
                    "512Mi",
                    "--task-timeout",
                    "180s",
                    "--tasks",
                    "1",
                    "--parallelism",
                    "1",
                    "--max-retries",
                    "0",
                    "--labels",
                    f"caseops-control=test-legal-manual-ip,caseops-release={release}",
                    "--quiet",
                    *_flags(),
                ],
                timeout=180,
            )
            job = validate_job(
                _cloud(["run", "jobs", "describe", JOB, *_flags()]), image, release, args, secrets
            )
            evidence.update(job=job, secret_versions=secrets)
            record()
            assert_current_main(release)
            current_serving = _serving_release(image, release)
            _require(
                current_serving == evidence["serving"]
                and _secrets(current_serving["secret_references"]) == secrets,
                "serving_secret_changed",
            )
            evidence["execute_attempted"] = True
            record()
            response = _cloud(["run", "jobs", "execute", JOB, "--async", "--quiet", *_flags()])
            previous = {str(row["metadata"].get("name", "")).rsplit("/", 1)[-1] for row in existing}
            previous.add(str(job["latest"]).rsplit("/", 1)[-1])
            evidence["execution"] = _execution_name(response, previous)
            record()
            name = _await_execution(
                response,
                previous=previous,
                job=job,
                image=image,
                release=release,
                args=args,
                secrets=secrets,
            )
            evidence["execution"] = name
            record()
            after = validate_job(
                _cloud(["run", "jobs", "describe", JOB, *_flags()]), image, release, args, secrets
            )
            _require(
                after["generation"] == job["generation"]
                and after["uid"] == job["uid"]
                and after["execution_count"] == job["execution_count"] + 1
                and str(after["latest"]).rsplit("/", 1)[-1] == name,
                "execution_uniqueness",
            )
            evidence["receipt"] = _receipt(name, request)
            record()
            assert_current_main(release)
            inspect_args = [
                "-m",
                MODULE,
                "inspect",
                "--company-id",
                request["company_id"],
                "--subscription-id",
                request["subscription_id"],
            ]
            evidence["inspection_execute_attempted"] = True
            record()
            inspection = _cloud(
                [
                    "run",
                    "jobs",
                    "execute",
                    JOB,
                    "--async",
                    "--quiet",
                    "--args",
                    "^|^" + "|".join(inspect_args),
                    *_flags(),
                ]
            )
            evidence["inspection_execution"] = _execution_name(inspection, previous | {name})
            record()
            inspected_name = _await_execution(
                inspection,
                previous=previous | {name},
                job=job,
                image=image,
                release=release,
                args=inspect_args,
                secrets=secrets,
            )
            evidence["inspection_execution"] = inspected_name
            evidence["inspection"] = _receipt(
                inspected_name,
                request,
                mode="inspect",
                fingerprint=evidence["receipt"]["after_sha256"],
            )
            final = validate_job(
                _cloud(["run", "jobs", "describe", JOB, *_flags()]), image, release, args, secrets
            )
            _require(
                final["generation"] == job["generation"]
                and final["uid"] == job["uid"]
                and final["execution_count"] == job["execution_count"] + 2
                and str(final["latest"]).rsplit("/", 1)[-1] == inspected_name,
                "inspection_uniqueness",
            )
            evidence["readiness_scope"] = "job_ready_and_locked_entitlement_readback_only"
            _no_scheduler()
            assert_current_main(release)
            evidence["status"] = "verified"
            record()
            return evidence
        except ReleaseError as error:
            evidence.update(status="failed_closed", error_code=str(error))
            record()
            raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "execute"))
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--release-sha")
    parser.add_argument("--image")
    parser.add_argument("--expected-input-sha256")
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "validate":
            prepared = preflight(arguments.input, arguments.output)
            print(prepared[1] if prepared else "not_requested")
        else:
            result = execute(
                arguments.input,
                arguments.output,
                release=arguments.release_sha or "",
                image=arguments.image or "",
                expected_input_sha256=arguments.expected_input_sha256 or "",
            )
            print(json.dumps({"status": result["status"]}))
        return 0
    except (ReleaseError, OSError):
        print("ERROR: manual_ip_release_failed_closed; inspect bounded evidence.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
