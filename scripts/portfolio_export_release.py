#!/usr/bin/env python3
"""Provision/verify only the production portfolio HTTP queue and HMAC secret.

Contracts (no App Engine bootstrap, task creation, or secret payload reads):
https://docs.cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues
https://docs.cloud.google.com/tasks/docs/reference/rest/v2/projects.locations.queues/setIamPolicy
https://docs.cloud.google.com/sdk/gcloud/reference/secrets/create
https://docs.cloud.google.com/sdk/gcloud/reference/secrets/versions/add
https://docs.cloud.google.com/sdk/gcloud/reference/secrets/versions/describe
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib import error, parse, request

import scheduler_inventory as inventory

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "perfect-period-305406"
REGION = "asia-south1"
SERVICE = "caseops-api"
RUNTIME_SA = f"caseops-runtime@{PROJECT}.iam.gserviceaccount.com"
QUEUE = "caseops-portfolio-exports"
SECRET = "caseops-portfolio-export-worker-secret"
CALLBACK = "https://api.caseops.ai/api/internal/portfolio-exports/run"
SECRET_ENV = "CASEOPS_PORTFOLIO_EXPORT_WORKER_SECRET"
QUEUE_ROLE = "roles/cloudtasks.enqueuer"
SECRET_ROLE = "roles/secretmanager.secretAccessor"
SHA = re.compile(r"[a-fA-F0-9]{40}")
REVISION = re.compile(r"caseops-api-[a-z0-9-]{1,63}")
MAX_PAGES = 100
PAGE_SIZE = 100
MAX_RESPONSE = 2_000_000
RATE = {"maxDispatchesPerSecond": 2, "maxConcurrentDispatches": 2}
RETRY = {
    "maxAttempts": 3,
    "maxRetryDuration": "120s",
    "minBackoff": "5s",
    "maxBackoff": "30s",
    "maxDoublings": 3,
}
ENV = {
    "CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE": "cloud_tasks",
    "CASEOPS_GCP_PROJECT_ID": PROJECT,
    "CASEOPS_PORTFOLIO_EXPORT_TASK_QUEUE": QUEUE,
    "CASEOPS_PORTFOLIO_EXPORT_TASK_REGION": REGION,
}
Error = inventory.InventoryError


def _git(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
            timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.TimeoutExpired):
        raise Error("canonical-main check unavailable or timed out") from None
    if result.returncode or len(result.stdout) > MAX_RESPONSE:
        raise Error("canonical-main check failed or exceeded its output bound")
    return result.stdout.strip()


def guard_current_main(expected_sha: str) -> None:
    if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
        raise Error("expected SHA must contain exactly 40 hexadecimal characters")
    _git(
        [
            "fetch",
            "--quiet",
            "--no-tags",
            "origin",
            "+refs/heads/main:refs/remotes/origin/main",
        ]
    )
    if _git(["symbolic-ref", "--quiet", "--short", "HEAD"]) != "main":
        raise Error("production helper requires the main branch")
    for ref in ("HEAD", "refs/heads/main", "refs/remotes/origin/main"):
        if _git(["rev-parse", "--verify", f"{ref}^{{commit}}"]) != expected_sha.lower():
            raise Error(
                "candidate is not current canonical main; revalidate the release"
            )
    if _git(["status", "--porcelain=v1", "--untracked-files=all"]):
        raise Error("production helper requires a clean main worktree")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def queue_body(name: str) -> dict:
    return {"name": name, "rateLimits": dict(RATE), "retryConfig": dict(RETRY)}


def check_queue(row: dict, name: str, *, exact: bool = True) -> None:
    if not isinstance(row, dict) or row.get("name") != name:
        raise Error("owned queue identity is unverified")
    if row.get("httpTarget") or row.get("appEngineRoutingOverride"):
        raise Error("owned queue must not override task URL, headers, auth, or routing")
    if row.get("state") not in {"RUNNING", "PAUSED"}:
        raise Error("owned queue is disabled or its state is unverified")
    if exact and (
        row.get("state") != "RUNNING"
        or any(row.get("rateLimits", {}).get(k) != v for k, v in RATE.items())
        or any(row.get("retryConfig", {}).get(k) != v for k, v in RETRY.items())
    ):
        raise Error("owned queue rate/retry/state configuration drift")


def grant_policy(policy: dict, role: str) -> tuple[dict, bool]:
    """Preserve the complete policy and its concurrency token, including conditions."""
    if (
        not isinstance(policy, dict)
        or not isinstance(policy.get("etag"), str)
        or not policy["etag"]
        or policy.get("version", 1) not in {1, 3}
        or not isinstance(policy.get("bindings", []), list)
        or len(policy.get("bindings", [])) > 1000
    ):
        raise Error("resource IAM policy or concurrency token is unverified")
    desired = copy.deepcopy(policy)
    bindings = desired.setdefault("bindings", [])
    member = f"serviceAccount:{RUNTIME_SA}"
    target = None
    present = False
    for binding in bindings:
        if (
            not isinstance(binding, dict)
            or not isinstance(binding.get("role"), str)
            or not isinstance(binding.get("members"), list)
            or len(binding["members"]) > 1500
            or any(not isinstance(m, str) for m in binding["members"])
        ):
            raise Error("resource IAM bindings are unverified")
        if "condition" in binding:
            if (
                policy.get("version") != 3
                or not isinstance(binding["condition"], dict)
                or not binding["condition"].get("expression")
            ):
                raise Error("conditional resource IAM policy is unverified")
        elif binding["role"] == role:
            if member in binding["members"]:
                present = True
            target = binding
    if present:
        return desired, False
    if target is None:
        bindings.append({"role": role, "members": [member]})
    else:
        target["members"].append(member)
    desired["version"] = 3
    return desired, True


def _policy_content(policy: dict) -> dict:
    content = {
        k: copy.deepcopy(v) for k, v in policy.items() if k not in {"etag", "version"}
    }
    for binding in content.get("bindings", []):
        binding["members"] = sorted(binding["members"])
    content["bindings"] = sorted(
        content.get("bindings", []), key=lambda b: json.dumps(b, sort_keys=True)
    )
    return content


class Release:
    def __init__(
        self, expected_sha: str, *, project: str = PROJECT, region: str = REGION
    ):
        if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
            raise Error("expected SHA must contain exactly 40 hexadecimal characters")
        if project != PROJECT or region != REGION:
            raise Error(
                "helper is restricted to the owned production project and region"
            )
        self.sha = expected_sha.lower()
        self.parent = f"projects/{PROJECT}/locations/{REGION}"
        self.queue = f"{self.parent}/queues/{QUEUE}"
        self.secret = f"projects/{PROJECT}/secrets/{SECRET}"
        self.project_number = ""
        self._token = ""

    def _call(self, args: list[str], *, json_result: bool = True):
        try:
            return inventory.run_gcloud(
                [
                    *args,
                    "--no-log-http",
                    "--verbosity=error",
                    "--project",
                    PROJECT,
                    "--quiet",
                ],
                expect_json=json_result,
                timeout=60,
            )
        except (Error, OSError, subprocess.SubprocessError):
            # CLI errors can echo raw environments, credentials, or request bodies.
            raise Error(
                "GCP metadata/control request failed; no implicit provisioning or retry"
            ) from None

    def _boundary(self) -> None:
        self._runtime(require_release=False)
        guard_current_main(self.sha)

    def _rest(
        self, api: str, path: str, *, method: str = "GET", body=None, query=None
    ) -> dict:
        bases = {
            "tasks": "https://cloudtasks.googleapis.com/v2/",
            "secrets": "https://secretmanager.googleapis.com/v1/",
        }
        if api not in bases or not path.startswith(f"projects/{PROJECT}/"):
            raise Error("unowned management resource")
        if not self._token:
            token = self._call(["auth", "print-access-token"], json_result=False)
            if (
                not isinstance(token, str)
                or not 1 <= len(token) <= 4096
                or any(ord(c) < 33 or ord(c) > 126 for c in token)
            ):
                raise Error("GCP management authentication is unverified")
            self._token = token
        data = None if body is None else json.dumps(body).encode("utf-8")
        url = bases[api] + path
        if query:
            url += "?" + parse.urlencode(query)
        req = request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "X-CaseOps-Automated-Test": "no-paid-providers",
            },
        )
        # getIamPolicy uses POST but is read-only. All other writes are fenced last.
        if method != "GET" and not path.endswith(":getIamPolicy"):
            self._boundary()
        try:
            with request.build_opener(_NoRedirect()).open(req, timeout=30) as response:
                raw = response.read(MAX_RESPONSE + 1)
                if response.status != 200 or len(raw) > MAX_RESPONSE:
                    raise Error("GCP management response status/size is unverified")
            result = json.loads(raw)
        except (error.URLError, OSError, ValueError):
            raise Error(
                "GCP management request failed; permissions/API prerequisites require review; "
                "no App Engine provisioning, terms acceptance, or retry performed"
            ) from None
        if not isinstance(result, dict):
            raise Error("GCP management response must be an object")
        return result

    def _runtime(self, *, require_release: bool) -> str:
        service = self._call(
            [
                "run",
                "services",
                "describe",
                SERVICE,
                "--region",
                REGION,
                "--format=json(metadata.name,spec.template.spec.serviceAccountName,spec.traffic,status)",
            ]
        )
        if (
            not isinstance(service, dict)
            or service.get("metadata", {}).get("name") != SERVICE
            or service.get("spec", {})
            .get("template", {})
            .get("spec", {})
            .get("serviceAccountName")
            != RUNTIME_SA
        ):
            raise Error("unexpected or unverified API runtime service account")
        status = service.get("status", {})
        revision = status.get("latestReadyRevisionName", "")
        traffic = status.get("traffic", [])
        desired = service.get("spec", {}).get("traffic", [])
        if (
            not isinstance(revision, str)
            or not REVISION.fullmatch(revision)
            or status.get("latestCreatedRevisionName") != revision
            or len(traffic) != 1
            or traffic[0].get("revisionName") != revision
            or traffic[0].get("percent") != 100
            or traffic[0].get("tag")
            or traffic[0].get("latestRevision") is not True
            or len(desired) != 1
            or desired[0].get("latestRevision") is not True
            or desired[0].get("percent") != 100
            or desired[0].get("tag")
            or desired[0].get("revisionName")
            or not any(
                c.get("type") == "Ready" and c.get("status") == "True"
                for c in status.get("conditions", [])
            )
        ):
            raise Error("API is not ready on untagged latest-only traffic")
        fields = (
            "metadata.name,metadata.labels,spec.serviceAccountName,"
            "spec.containers.name,spec.containers.image"
        )
        if require_release:
            fields += ",spec.containers.env"
        deployed = self._call(
            [
                "run",
                "revisions",
                "describe",
                revision,
                "--region",
                REGION,
                f"--format=json({fields})",
            ]
        )
        spec = deployed.get("spec", {})
        containers = spec.get("containers", [])
        api_containers = (
            [
                row
                for row in containers
                if isinstance(row, dict) and row.get("name") == "api"
            ]
            if isinstance(containers, list)
            else []
        )
        if (
            deployed.get("metadata", {}).get("name") != revision
            or deployed.get("metadata", {})
            .get("labels", {})
            .get("serving.knative.dev/service")
            != SERVICE
            or spec.get("serviceAccountName") != RUNTIME_SA
            or not isinstance(containers, list)
            or len(containers) != 2
            or any(
                not isinstance(row, dict) or not row.get("name") for row in containers
            )
            or len({row["name"] for row in containers}) != len(containers)
            or {row["name"] for row in containers} != {"api", "clamav"}
            or len(api_containers) != 1
        ):
            raise Error("serving API revision/runtime identity is unverified")
        if require_release:
            if not inventory.DIGEST_IMAGE.fullmatch(api_containers[0].get("image", "")):
                raise Error("serving API image is not digest-pinned")
            self._check_env(api_containers[0].get("env", []))
        return revision

    def _check_env(self, rows: list) -> None:
        if (
            not isinstance(rows, list)
            or len(rows) > 1000
            or any(
                not isinstance(r, dict) or not isinstance(r.get("name"), str)
                for r in rows
            )
            or len({r["name"] for r in rows}) != len(rows)
        ):
            raise Error("API environment inventory is invalid or duplicated")
        env = {r["name"]: r for r in rows}
        for key, value in {**ENV, "CASEOPS_RELEASE_SHA": self.sha}.items():
            if env.get(key, {}).get("value") != value or env[key].get("valueFrom"):
                raise Error(f"API release/environment drift: {key}")
        callback = env.get("CASEOPS_PORTFOLIO_EXPORT_TASK_URL")
        if callback is not None and (
            callback.get("value") != CALLBACK or callback.get("valueFrom")
        ):
            raise Error("API portfolio callback target drift")
        secret = env.get(SECRET_ENV, {})
        ref = secret.get("valueFrom", {}).get("secretKeyRef", {})
        allowed = {
            SECRET,
            self.secret,
            f"projects/{self.project_number}/secrets/{SECRET}",
        }
        if (
            "value" in secret
            or ref.get("name") not in allowed
            or ref.get("key") != "latest"
        ):
            raise Error("API dedicated worker secret reference drift")

    def _api_enabled(self) -> bool:
        rows = self._call(
            [
                "services",
                "list",
                "--enabled",
                "--filter=config.name=cloudtasks.googleapis.com",
                "--limit=2",
                "--format=json(config.name)",
            ]
        )
        if not isinstance(rows, list) or len(rows) > 1:
            raise Error("Cloud Tasks API inventory is invalid or truncated")
        if rows and rows != [{"config": {"name": "cloudtasks.googleapis.com"}}]:
            raise Error("Cloud Tasks API identity is unverified")
        return bool(rows)

    def _queue_inventory(self) -> dict | None:
        found = None
        token = ""
        seen = set()
        names = set()
        deadline = time.monotonic() + 180
        for _ in range(MAX_PAGES):
            if time.monotonic() >= deadline:
                raise Error("queue inventory deadline exceeded")
            page = self._rest(
                "tasks",
                f"{self.parent}/queues",
                query={
                    "pageSize": PAGE_SIZE,
                    **({"pageToken": token} if token else {}),
                },
            )
            rows = page.get("queues", [])
            if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
                raise Error("queue inventory page is invalid or truncated")
            for row in rows:
                name = row.get("name", "") if isinstance(row, dict) else ""
                if (
                    not isinstance(name, str)
                    or not name.startswith(f"{self.parent}/queues/")
                    or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", name.rsplit("/", 1)[-1])
                    or name in names
                ):
                    raise Error("queue inventory identity is invalid or duplicated")
                names.add(name)
                if name == self.queue:
                    found = row
            token = page.get("nextPageToken", "")
            if not isinstance(token, str) or len(token) > 4096 or token in seen:
                raise Error("queue inventory continuation is invalid or repeated")
            if not token:
                return found
            seen.add(token)
        raise Error("queue inventory exceeds 100 pages; refusing truncated evidence")

    def _secret_exists(self) -> bool:
        rows = self._call(
            [
                "secrets",
                "list",
                f"--filter=name~'/secrets/{SECRET}$'",
                "--limit=2",
                "--format=json(name)",
            ]
        )
        if (
            not isinstance(rows, list)
            or len(rows) > 1
            or any(
                not isinstance(row, dict)
                or row.get("name")
                not in {
                    self.secret,
                    f"projects/{self.project_number}/secrets/{SECRET}",
                }
                for row in rows
            )
        ):
            raise Error("exact secret inventory is invalid or truncated")
        return bool(rows)

    def _create_secret(self) -> None:
        # Fence the metadata create and first-version upload independently. A partial
        # create is never repaired by rotating an existing/versionless secret.
        descriptor, filename = tempfile.mkstemp(prefix="caseops-export-secret-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(secrets.token_hex(48).encode("ascii"))
            self._boundary()
            self._call(
                [
                    "secrets",
                    "create",
                    SECRET,
                    "--replication-policy=automatic",
                    "--format=none",
                ],
                json_result=False,
            )
            self._boundary()
            self._call(
                [
                    "secrets",
                    "versions",
                    "add",
                    SECRET,
                    "--data-file",
                    filename,
                    "--format=none",
                ],
                json_result=False,
            )
        finally:
            Path(filename).unlink(missing_ok=True)

    def _latest(self) -> str:
        version = self._call(
            [
                "secrets",
                "versions",
                "describe",
                "latest",
                "--secret",
                SECRET,
                "--format=json(name,state)",
            ]
        )
        prefix = (
            rf"projects/(?:{PROJECT}|{self.project_number})/secrets/{SECRET}/versions/"
        )
        if (
            not isinstance(version, dict)
            or version.get("state") != "ENABLED"
            or not re.fullmatch(prefix + r"[1-9][0-9]*", version.get("name", ""))
        ):
            raise Error(
                "existing latest worker secret version is not enabled; no rotation allowed"
            )
        return version["name"]

    def _policy(self, api: str, resource: str) -> dict:
        if api == "tasks":
            return self._rest(
                api,
                resource + ":getIamPolicy",
                method="POST",
                body={"options": {"requestedPolicyVersion": 3}},
            )
        return self._rest(
            api, resource + ":getIamPolicy", query={"options.requestedPolicyVersion": 3}
        )

    def _iam(self, api: str, resource: str, role: str, *, provision: bool) -> None:
        desired, changed = grant_policy(self._policy(api, resource), role)
        if not changed:
            return
        if not provision:
            raise Error("required unconditional resource-scoped IAM grant is missing")
        self._rest(
            api, resource + ":setIamPolicy", method="POST", body={"policy": desired}
        )
        actual = self._policy(api, resource)
        _, missing = grant_policy(actual, role)
        if missing or _policy_content(actual) != _policy_content(desired):
            raise Error("resource IAM grant/preservation readback is unverified")

    def run(self, command: str) -> dict:
        if command not in {"provision", "verify"}:
            raise Error("command must be provision or verify")
        provision = command == "provision"
        guard_current_main(self.sha)
        project = self._call(
            ["projects", "describe", PROJECT, "--format=json(projectId,projectNumber)"]
        )
        if (
            not isinstance(project, dict)
            or project.get("projectId") != PROJECT
            or not re.fullmatch(r"[0-9]{6,20}", str(project.get("projectNumber", "")))
        ):
            raise Error("production project identity is unverified")
        self.project_number = str(project["projectNumber"])
        self._runtime(require_release=not provision)
        if not self._api_enabled():
            if not provision:
                raise Error("Cloud Tasks API is not enabled")
            self._boundary()
            self._call(
                ["services", "enable", "cloudtasks.googleapis.com", "--format=none"],
                json_result=False,
            )
            if not self._api_enabled():
                raise Error("Cloud Tasks API enablement readback failed")
        row = self._queue_inventory()
        if row is None:
            if not provision:
                raise Error("owned queue is missing")
            self._rest(
                "tasks",
                f"{self.parent}/queues",
                method="POST",
                body=queue_body(self.queue),
            )
        else:
            check_queue(row, self.queue, exact=False)
            drift = any(
                row.get("rateLimits", {}).get(k) != v for k, v in RATE.items()
            ) or any(row.get("retryConfig", {}).get(k) != v for k, v in RETRY.items())
            if drift and provision:
                mask = ",".join(
                    [
                        *(f"rateLimits.{k}" for k in RATE),
                        *(f"retryConfig.{k}" for k in RETRY),
                    ]
                )
                self._rest(
                    "tasks",
                    self.queue,
                    method="PATCH",
                    body=queue_body(self.queue),
                    query={"updateMask": mask},
                )
            if row["state"] == "PAUSED" and provision:
                self._rest("tasks", self.queue + ":resume", method="POST", body={})
        check_queue(self._rest("tasks", self.queue), self.queue)
        if not self._secret_exists():
            if not provision:
                raise Error("dedicated worker secret is missing")
            self._create_secret()
            if not self._secret_exists():
                raise Error("dedicated worker secret creation readback failed")
        version = self._latest()
        self._iam("secrets", self.secret, SECRET_ROLE, provision=provision)
        self._iam("tasks", self.queue, QUEUE_ROLE, provision=provision)
        # Re-read all managed state; provision deliberately does not require the future API env.
        check_queue(self._rest("tasks", self.queue), self.queue)
        if self._latest() != version:
            raise Error("worker secret latest version changed during verification")
        for api, resource, role in (
            ("secrets", self.secret, SECRET_ROLE),
            ("tasks", self.queue, QUEUE_ROLE),
        ):
            self._iam(api, resource, role, provision=False)
        revision = self._runtime(require_release=not provision)
        guard_current_main(self.sha)
        return {
            "command": command,
            "expected_sha": self.sha,
            "project": PROJECT,
            "region": REGION,
            "queue": self.queue,
            "queue_state": "RUNNING",
            "runtime_service_account": RUNTIME_SA,
            "dedicated_worker_key_verified": True,
            "api_revision": revision,
            "api_release_verified": not provision,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("provision", "verify"))
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--project", default=PROJECT)
    parser.add_argument("--region", default=REGION)
    args = parser.parse_args(argv)
    try:
        result = Release(
            args.expected_sha, project=args.project, region=args.region
        ).run(args.command)
    except (Error, OSError, ValueError, TypeError, KeyError, AttributeError):
        print(
            "ERROR: portfolio export release checks failed; "
            "no retry or broader provisioning authorized.",
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
