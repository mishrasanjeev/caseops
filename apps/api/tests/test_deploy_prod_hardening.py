from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_web_gcloudignore_blocks_local_build_artifacts() -> None:
    """Regression for the 2026-06-26 Windows deploy archive failure.

    Docker's .dockerignore is applied after gcloud has already staged
    the source archive. The web Cloud Build context needs its own
    .gcloudignore so local node_modules/.next never get uploaded.
    """
    ignore_text = _read_repo_text("apps/web/.gcloudignore")

    required_patterns = {
        "node_modules/",
        ".next/",
        ".env.local",
        ".env*.local",
        "tsconfig.tsbuildinfo",
        "test-results/",
        "playwright-report/",
    }
    for pattern in required_patterns:
        assert pattern in ignore_text


@pytest.mark.parametrize(
    "config_path",
    [
        "playwright.prod-ram.config.ts",
        "playwright.notice-prod.config.ts",
        "playwright.ip-a0-prod.config.ts",
    ],
)
def test_production_playwright_does_not_retain_authenticated_media(
    config_path: str,
) -> None:
    config = _read_repo_text(config_path)

    for setting in ('trace: "off"', 'screenshot: "off"', 'video: "off"'):
        assert setting in config
    assert "retain-on-failure" not in config
    assert "only-on-failure" not in config


def test_a0_production_acceptance_is_an_isolated_verify_only_gate() -> None:
    workflow = _read_repo_text(".github/workflows/prod-verify.yml")
    config = _read_repo_text("playwright.ip-a0-prod.config.ts")
    app_config = _read_repo_text("playwright.app.config.ts")
    root_config = _read_repo_text("playwright.config.ts")
    broad_config = _read_repo_text("playwright.prod-ram.config.ts")
    spec = _read_repo_text("tests/e2e/iplf-027b-a0-quiescence-2026-08-14-prod.spec.ts")

    assert "Run IPLF-027B A0 quiescence acceptance" in workflow
    prerequisite_gate = (
        "if: always() && !cancelled() && "
        "steps.prod-playwright-prerequisites.outputs.ready == 'true'"
    )
    assert "id: prod-playwright-prerequisites" in workflow
    assert workflow.count(prerequisite_gate) == 2
    assert "CASEOPS_IP_A0_PROD_MODE: verify" in workflow
    assert (
        "npx playwright test --config=playwright.ip-a0-prod.config.ts --reporter=list" in workflow
    )
    assert (
        workflow.index("Run prod-Playwright suite (ram-batch)")
        < workflow.index("Run IPLF-027B A0 quiescence acceptance")
        < workflow.index("Run prod-Playwright suite (notice module)")
    )
    assert "testMatch: /iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in config
    assert "testIgnore: /iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in app_config
    assert "testIgnore: /iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in root_config
    assert "iplf-027b-a0-quiescence-2026-08-14-prod" not in broad_config
    assert 'process.env.CASEOPS_IP_A0_PROD_MODE ?? "verify"' in spec
    assert 'const PROD_BASE_URL = "https://caseops.ai"' in spec
    assert 'const PROD_API_BASE_URL = "https://api.caseops.ai"' in spec
    assert 'const IP_QA_SLUG = "caseops-ip-qa"' in spec
    assert 'const IP_QA_EMAIL = "ip-qa-bot@caseops.ai"' in spec
    assert "process.env.PROD_BASE_URL" not in spec
    assert "process.env.PROD_API_BASE_URL" not in spec
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert "`${PROD_API_BASE_URL}/api/build`" in spec
    assert "`${PROD_BASE_URL}/api/release-identity`" in spec
    assert spec.count("await expectQuiesced(") == 3
    assert spec.count("newContext({ maxRedirects: 0 })") == 2
    test_body = spec.rsplit(
        'test("IPLF-027B A0 production quiescence and legal-deadline continuity"',
        maxsplit=1,
    )[1]
    assert (
        test_body.index("assertCanonicalProductionOrigins();")
        < test_body.index("newContext({ maxRedirects: 0 })")
        < test_body.index("assertExactRelease(api)")
    )
    for endpoint in (
        "/api/ip/deadline-rules",
        "/activate",
        "/transition",
        "/api/ip/dockets/${docket.id}/deadlines",
        "/deadlines/${proposed.id}/confirm",
        "/deadlines/${proposed.id}/recalculate",
        "/deadlines/${confirmed.id}/override",
        "/deadlines/${overridden.id}/complete",
    ):
        assert endpoint in spec
    assert "caseops-ip-qa-password --project perfect-period-305406" in spec
    assert "$LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace" in spec
    assert "Remove-Item Env:CASEOPS_IP_QA_PASSWORD" in spec
    assert "isReservedPreparationAdmin" in spec
    assert 'user.role === "admin"' in spec
    assert "iplf-027b-a0-(?:reviewer|legal-approver)-" in spec
    assert "@example\\.com$" in spec
    assert spec.index("await reconcilePreparationAdmins") < spec.index(
        "if (calendar && rule && selected)"
    )
    assert 'right_kind: "trademark"' in spec
    assert 'right_kind: "patent"' in spec
    assert "await reconcilePriorSyntheticMatters" in spec
    assert "/api/matters/${matterId}/lifecycle/status" in spec
    assert "expected_from_status: current.status" in spec
    assert "notification_intent_ids: []" in spec
    verify_body = spec.split("async function verifyQuiescenceAndDeadlineWriters", maxsplit=1)[
        1
    ].split("/**\n * One-time fixture preparation", maxsplit=1)[0]
    assert verify_body.index("createFreshMatter") < verify_body.index("try {")
    assert (
        verify_body.index("persistedRecalculation")
        < verify_body.index("finally {")
        < verify_body.index("disposeSyntheticMatter")
    )
    assert "test.skip" not in spec
    a0_step = workflow.split("Run IPLF-027B A0 quiescence acceptance", maxsplit=1)[1].split(
        "Run prod-Playwright suite (notice module)", maxsplit=1
    )[0]
    assert "timeout-minutes: 5" in a0_step
    assert "PROD_BASE_URL:" not in a0_step
    assert "PROD_API_BASE_URL:" not in a0_step
    assert "CASEOPS_IP_QA_EMAIL:" not in a0_step
    assert "CASEOPS_IP_QA_SLUG:" not in a0_step


def test_local_playwright_enables_rule_governance_journey_explicitly() -> None:
    e2e_env = _read_repo_text("tests/e2e/support/env.ts")

    assert 'CASEOPS_IP_RULE_GOVERNANCE_ENABLED: "true"' in e2e_env


def test_deploy_prod_uses_web_gcloudignore_explicitly() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "WEB_GCLOUDIGNORE_FILE=.gcloudignore" in script
    assert 'WEB_GCLOUDIGNORE_PATH="${WEB_SOURCE_DIR}/${WEB_GCLOUDIGNORE_FILE}"' in script
    assert '--ignore-file "${WEB_GCLOUDIGNORE_FILE}"' in script
    assert '[[ ! -f "${WEB_GCLOUDIGNORE_PATH}" ]]' in script


def test_deploy_prod_uses_api_gcloudignore_explicitly() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "API_GCLOUDIGNORE_FILE=.gcloudignore" in script
    assert 'API_GCLOUDIGNORE_PATH="${API_SOURCE_DIR}/${API_GCLOUDIGNORE_FILE}"' in script
    assert '--ignore-file "${API_GCLOUDIGNORE_FILE}"' in script
    assert '[[ ! -f "${API_GCLOUDIGNORE_PATH}" ]]' in script


def test_deploy_prod_uses_service_minimums_and_clears_stale_revision_tags() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert '--min "${API_MIN_INSTANCES}"' in script
    assert '--min "${WEB_MIN_INSTANCES}"' in script
    assert script.count("--min-instances default") == 2
    assert "--to-latest --clear-tags --quiet" in script
    assert '--min-instances "${API_MIN_INSTANCES}"' not in script
    assert '--min-instances "${WEB_MIN_INSTANCES}"' not in script
    assert "MIGRATION_TASK_TIMEOUT=30m" in script
    assert '--task-timeout "${MIGRATION_TASK_TIMEOUT}"' in script


def test_deploy_prod_fences_rule_governance_and_verifies_exact_traffic() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "CASEOPS_IP_RULE_GOVERNANCE_ENABLED=false" in script
    assert "LIVE_API_SERVICE_JSON=$(gcloud run services describe caseops-api" in script
    assert 'str(metadata.get("generation")) != str(status.get("observedGeneration"))' in script
    assert "len(status_traffic) != 1" in script
    assert 'env.get("CASEOPS_RELEASE_SHA") != expected_sha' in script
    assert 'env.get("CASEOPS_IP_RULE_GOVERNANCE_ENABLED") != "false"' in script
    assert "LIVE_API_REVISION_IMAGE=$(gcloud run revisions describe" in script
    assert '"${LIVE_API_REVISION_IMAGE}" != "${API_IMMUTABLE_IMAGE}"' in script


def test_deploy_prod_preserves_single_request_instances_with_scale_headroom() -> None:
    """Cloud Run must not reject ordinary UI fan-out while handlers stay sync."""

    script = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/api-service.yaml")

    assert "API_CONCURRENCY=1" in script
    assert 'API_MAX_INSTANCES="${API_MAX_INSTANCES:-20}"' in script
    assert '--max "${API_MAX_INSTANCES}"' in script
    assert '--max-instances "${API_MAX_INSTANCES}"' in script
    assert 'autoscaling.knative.dev/maxScale: "20"' in manifest


def _ignore_matches(ignore_text: str, relative_path: str) -> bool:
    """Evaluate the root-level canary subset used by these ignore files."""
    ignored = False
    for raw_pattern in ignore_text.splitlines():
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            matches = relative_path == directory or relative_path.startswith(f"{directory}/")
        else:
            matches = fnmatch.fnmatchcase(relative_path, pattern)
        if matches:
            ignored = not negated
    return ignored


@pytest.mark.parametrize("ignore_path", ["apps/api/.gcloudignore", "apps/api/.dockerignore"])
def test_api_build_context_excludes_secret_and_cache_canaries(ignore_path: str) -> None:
    ignore_text = _read_repo_text(ignore_path)

    excluded_canaries = {
        ".env",
        ".env.cloud",
        ".env.production.local",
        ".venv/Scripts/python.exe",
        ".uv-cache/archive-v0/package.whl",
        "__pycache__/settings.cpython-313.pyc",
        ".pytest_cache/v/cache/nodeids",
        ".pytest-tmp/session/data",
        ".mypy_cache/3.13/cache.json",
        ".ruff_cache/content",
    }
    for canary in excluded_canaries:
        assert _ignore_matches(ignore_text, canary), (
            f"{ignore_path} would include sensitive/cache canary {canary}"
        )

    assert not _ignore_matches(ignore_text, ".env.example")


@cache
def _find_working_bash() -> str:
    candidates: list[str | None]
    if os.name == "nt":
        git = shutil.which("git")
        discovered_git_bash = (
            str(Path(git).resolve().parents[1] / "bin" / "bash.exe") if git else None
        )
        candidates = [
            discovered_git_bash,
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            shutil.which("bash"),
        ]
    else:
        candidates = [shutil.which("bash")]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and "GNU bash" in result.stdout:
            return candidate
    return pytest.skip("GNU bash is unavailable")


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved.as_posix()
    drive = resolved.drive.rstrip(":").lower()
    return f"/{drive}{resolved.as_posix()[2:]}"


def _write_fake_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _a0_fingerprint_json() -> str:
    datasets = {
        "ip_rule_sets": {
            "content_sha256": "1" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None},
        },
        "ip_rule_versions": {
            "content_sha256": "2" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {
                "activated_at": None,
                "created_at": None,
                "disabled_at": None,
                "fixtures_passed_at": None,
            },
        },
        "company_ip_rule_policies": {
            "content_sha256": "3" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None, "updated_at": None},
        },
        "audit_events_ip_rule_governance": {
            "content_sha256": "4" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None},
        },
    }
    body = {
        "database_context": {
            "alembic_heads": ["20260813_0002"],
            "database_schema": "public",
            "dialect": "postgresql",
        },
        "datasets": datasets,
        "schema_version": 1,
        "scope": {
            "audit_filter": {
                "action_prefix": "ip.rule_version.",
                "match": "action_prefix_or_target_type",
                "target_types": [
                    "company_ip_rule_policy",
                    "ip_rule_set",
                    "ip_rule_version",
                ],
            },
            "datasets": [
                "ip_rule_sets",
                "ip_rule_versions",
                "company_ip_rule_policies",
                "audit_events_ip_rule_governance",
            ],
            "read_control": {
                "statement_timeout_ms": 60_000,
                "stream_batch_size": 500,
            },
        },
    }
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    snapshot = {
        **body,
        "captured_at": "2026-08-14T16:00:00.000000Z",
        "overall_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    return json.dumps(snapshot, separators=(",", ":"), sort_keys=True)


def _a0_qa_job_json(
    image: str,
    generation: int,
    *,
    execution_count: int = 9,
) -> str:
    return json.dumps(
        {
            "metadata": {"generation": generation},
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "client.knative.dev/nonce": f"nonce-{generation}",
                            "run.googleapis.com/execution-environment": "gen2",
                            "run.googleapis.com/cloudsql-instances": (
                                "perfect-period-305406:asia-south1:caseops-db"
                            ),
                        }
                    },
                    "spec": {
                        "taskCount": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "args": [],
                                        "command": ["caseops-bootstrap-ip-production-qa"],
                                        "env": [
                                            {
                                                "name": "CASEOPS_AUTO_MIGRATE",
                                                "value": "false",
                                            }
                                        ],
                                        "image": image,
                                    }
                                ],
                                "maxRetries": 0,
                                "serviceAccountName": (
                                    "caseops-runtime@perfect-period-305406.iam.gserviceaccount.com"
                                ),
                                "timeoutSeconds": 600,
                            }
                        },
                    },
                }
            },
            "status": {
                "conditions": [{"status": "True", "type": "Ready"}],
                "executionCount": execution_count,
                "latestCreatedExecution": {"name": "caseops-ip-qa-bootstrap-old"},
                "observedGeneration": generation,
            },
        },
        separators=(",", ":"),
    )


def _a0_fingerprint_job_json(image: str) -> str:
    return json.dumps(
        {
            "metadata": {
                "generation": 2,
                "labels": {
                    "caseops-control": "ip-rule-fingerprint",
                    "caseops-release": "abcdef1234567890abcdef1234567890abcdef12",
                },
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "run.googleapis.com/cloudsql-instances": (
                                "perfect-period-305406:asia-south1:caseops-db"
                            )
                        }
                    },
                    "spec": {
                        "taskCount": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "args": [
                                            "-m",
                                            "caseops_api.scripts.ip_rule_governance_fingerprint",
                                        ],
                                        "command": ["python"],
                                        "env": [
                                            {"name": "CASEOPS_ENV", "value": "cloud"},
                                            {
                                                "name": "CASEOPS_AUTO_MIGRATE",
                                                "value": "false",
                                            },
                                            {
                                                "name": "CASEOPS_AUTH_SECRET",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "key": "latest",
                                                        "name": "caseops-auth-secret",
                                                    }
                                                },
                                            },
                                            {
                                                "name": "CASEOPS_DATABASE_URL",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "key": "latest",
                                                        "name": "caseops-database-url",
                                                    }
                                                },
                                            },
                                        ],
                                        "image": image,
                                    }
                                ],
                                "maxRetries": 0,
                                "serviceAccountName": (
                                    "caseops-runtime@perfect-period-305406.iam.gserviceaccount.com"
                                ),
                                "timeoutSeconds": 600,
                            }
                        },
                    },
                }
            },
            "status": {
                "conditions": [{"status": "True", "type": "Ready"}],
                "observedGeneration": 2,
            },
        },
        separators=(",", ":"),
    )


def _a0_execution_json(
    image: str,
    *,
    succeeded: bool = True,
    expected_sha: str | None = None,
    execution_name: str = "caseops-ip-rule-governance-fingerprint-a0-test",
) -> str:
    arguments = ["-m", "caseops_api.scripts.ip_rule_governance_fingerprint"]
    if expected_sha is not None:
        arguments.append(f"--expect-sha256={expected_sha}")
    return json.dumps(
        {
            "metadata": {"name": execution_name},
            "spec": {
                "taskCount": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "args": arguments,
                                "command": ["python"],
                                "image": image,
                            }
                        ]
                    }
                },
            },
            "status": {
                "completionTime": "2026-08-14T16:00:02Z",
                "conditions": [{"status": "True" if succeeded else "False", "type": "Completed"}],
                "failedCount": 0 if succeeded else 1,
                "startTime": "2026-08-14T16:00:01Z",
                "succeededCount": 1 if succeeded else 0,
            },
        },
        separators=(",", ":"),
    )


def _a0_pending_execution_json(image: str) -> str:
    value = json.loads(_a0_execution_json(image))
    value["status"] = {
        "conditions": [{"status": "Unknown", "type": "Completed"}],
        "startTime": "2026-08-14T16:00:01Z",
    }
    return json.dumps(value, separators=(",", ":"))


def _run_deploy_with_fakes(
    tmp_path: Path,
    *arguments: str,
    git_status: str = "",
    curl_mode: str = "ok",
    traffic_mode: str = "ok",
    expected_tag: str = "abcdef1",
    a0_mode: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gcloud_log = tmp_path / "gcloud.log"

    _write_fake_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "status" ]]; then
  if [[ -n "${FAKE_GIT_STATUS:-}" ]]; then
    printf '%s\n' "${FAKE_GIT_STATUS}"
  fi
  exit 0
fi
if [[ "$1" == "rev-parse" && "$*" == *"--short=7"* ]]; then
  printf '%s\n' "abcdef1"
  exit 0
fi
if [[ "$1" == "rev-parse" && "$*" == *"1111111"* ]]; then
  printf '%s\n' "1111111111111111111111111111111111111111"
  exit 0
fi
if [[ "$1" == "rev-parse" ]]; then
  printf '%s\n' "abcdef1234567890abcdef1234567890abcdef12"
  exit 0
fi
exit 91
""",
    )
    _write_fake_executable(
        fake_bin / "gcloud",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"artifacts docker images describe"* ]]; then
  printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
elif [[ "$*" == *"run jobs update caseops-ip-qa-bootstrap"* ]]; then
  touch "${FAKE_QA_UPDATED}"
elif [[ "$*" == *"run jobs describe caseops-ip-qa-bootstrap"* && "$*" == *"--format=json"* ]]; then
  if [[ -f "${FAKE_QA_UPDATED}" ]]; then
    printf '%s\n' "${FAKE_QA_AFTER_JSON}"
  else
    printf '%s\n' "${FAKE_QA_BEFORE_JSON}"
  fi
elif [[ "$*" == *"run jobs executions list"* ]]; then
  printf '%s\n' "${FAKE_EXECUTIONS_JSON}"
elif [[ "$*" == *"run jobs describe caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JOB_JSON}"
elif [[ "$*" == *"run jobs execute caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' '{"metadata":{"name":"caseops-ip-rule-governance-fingerprint-a0-test"}}'
elif [[ "$*" == *"run jobs executions describe"* && \
  "$*" == *"caseops-ip-rule-governance-fingerprint-a0-test"* ]]; then
  if [[ "${FAKE_A0_MODE}" == "pending-structured" && \
    ! -f "${FAKE_EXECUTION_POLLED}" ]]; then
    touch "${FAKE_EXECUTION_POLLED}"
    printf '%s\n' "${FAKE_PENDING_EXECUTION_JSON}"
  else
    printf '%s\n' "${FAKE_EXECUTION_JSON}"
  fi
elif [[ "$*" == *"logging read"* && "$*" == *"stdout"* ]]; then
  if [[ "${FAKE_A0_MODE}" == "pending-structured" ]]; then
    exit 124
  fi
  printf '%s\n' "${FAKE_FINGERPRINT_LOG_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stderr"* ]]; then
  printf ''
elif [[ "$*" == *"auth print-access-token"* ]]; then
  printf '%s\n' 'fake-access-token'
elif [[ "$*" == *"run jobs describe"* ]]; then
  printf '%s%s\n' \
    'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"--format=json"* ]]; then
  FAKE_TRAFFIC_REVISION='caseops-api-test'
  FAKE_TRAFFIC_LATEST='true'
  FAKE_OBSERVED_GENERATION='2'
  FAKE_GOVERNANCE_FLAG='false'
  if [[ "${FAKE_TRAFFIC_MODE}" == "drift" ]]; then
    FAKE_TRAFFIC_REVISION='caseops-api-old'
    FAKE_TRAFFIC_LATEST='false'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "generation-drift" ]]; then
    FAKE_OBSERVED_GENERATION='1'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "flag-enabled" ]]; then
    FAKE_GOVERNANCE_FLAG='true'
  fi
  printf '%s' \
    '{"metadata":{"generation":2},' \
    '"spec":{"traffic":[{"latestRevision":true,"percent":100}],' \
    '"template":{"spec":{"containers":[{"name":"api","env":[' \
    '{"name":"CASEOPS_RELEASE_SHA",' \
    '"value":"abcdef1234567890abcdef1234567890abcdef12"},' \
    '{"name":"CASEOPS_IP_RULE_GOVERNANCE_ENABLED","value":"' \
    "${FAKE_GOVERNANCE_FLAG}" '"}' \
    ']}]}}},' \
    '"status":{"observedGeneration":' "${FAKE_OBSERVED_GENERATION}" ',' \
    '"latestCreatedRevisionName":"caseops-api-test",' \
    '"latestReadyRevisionName":"caseops-api-test","conditions":[' \
    '{"type":"Ready","status":"True"},' \
    '{"type":"ConfigurationsReady","status":"True"},' \
    '{"type":"RoutesReady","status":"True"}],"traffic":[' \
    '{"revisionName":"' "${FAKE_TRAFFIC_REVISION}" '",' \
    '"latestRevision":' "${FAKE_TRAFFIC_LATEST}" ',"percent":100}]}}'
  printf '\n'
elif [[ "$*" == *"run revisions describe"* ]]; then
  if [[ "${FAKE_TRAFFIC_MODE}" == "image-drift" ]]; then
    printf '%s%s\n' \
      'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  else
    printf '%s%s\n' \
      'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  fi
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[0].image"* ]]; then
  printf 'registry.invalid/caseops-api:%s\n' "${FAKE_TAG}"
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[1].image"* ]]; then
  printf 'clamav/clamav:1.4\n'
elif [[ "$*" == *"services describe caseops-web"* ]]; then
  printf 'registry.invalid/caseops-web:%s\n' "${FAKE_TAG}"
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[].name"* ]]; then
  printf 'api;clamav\n'
elif [[ "$*" == *"services describe caseops-api"* && \
  "$*" == *"startupProbe.initialDelaySeconds"* ]]; then
  printf ''
elif [[ "$*" == *"services describe caseops-api"* && \
  "$*" == *"startupProbe.periodSeconds"* ]]; then
  printf '2\n'
fi
""",
    )
    _write_fake_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"logging.googleapis.com/v2/entries:list"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_REST_JSON}"
  exit 0
fi
case "${FAKE_CURL_MODE}" in
  network-fail) exit 22 ;;
  degraded) printf '%s\n' '{"status":"degraded"}' ;;
  *) printf '%s\n' '{"status":"ok"}' ;;
esac
""",
    )
    _write_fake_executable(
        fake_bin / "sleep",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_fake_executable(
        fake_bin / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "scripts/scheduler_inventory.py" ]]; then
  printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
  exit 0
fi
exec "${FAKE_REAL_PYTHON}" "$@"
""",
    )

    immutable_image = (
        "asia-south1-docker.pkg.dev/perfect-period-305406/"
        "caseops-images/caseops-api@sha256:" + "a" * 64
    )
    env = os.environ.copy()
    fingerprint_json = _a0_fingerprint_json()
    fingerprint_log_json = json.dumps(
        [
            {
                ("jsonPayload" if a0_mode == "pending-structured" else "textPayload"): (
                    json.loads(fingerprint_json)
                    if a0_mode == "pending-structured"
                    else fingerprint_json
                )
            }
        ],
        separators=(",", ":"),
    )
    env.update(
        {
            "FAKE_A0_MODE": a0_mode or "",
            "FAKE_CURL_MODE": curl_mode,
            "FAKE_EXECUTION_JSON": _a0_execution_json(
                immutable_image,
                succeeded=a0_mode != "fingerprint-fail",
            ),
            "FAKE_EXECUTION_POLLED": _bash_path(tmp_path / "execution-polled"),
            "FAKE_EXECUTIONS_JSON": json.dumps(
                [
                    {
                        "metadata": {
                            "name": (
                                "running-execution"
                                if a0_mode == "nonterminal"
                                else "historical-failure"
                            )
                        },
                        "status": {
                            "conditions": [
                                {
                                    "status": "True" if a0_mode == "nonterminal" else "False",
                                    "type": (
                                        "Started" if a0_mode == "nonterminal" else "Completed"
                                    ),
                                }
                            ]
                        },
                    }
                ],
                separators=(",", ":"),
            ),
            "FAKE_FINGERPRINT_JOB_JSON": _a0_fingerprint_job_json(immutable_image),
            "FAKE_FINGERPRINT_LOG_JSON": fingerprint_log_json,
            "FAKE_FINGERPRINT_REST_JSON": json.dumps(
                {"entries": [{"jsonPayload": json.loads(fingerprint_json)}]},
                separators=(",", ":"),
            ),
            "FAKE_GCLOUD_LOG": _bash_path(gcloud_log),
            "FAKE_GIT_STATUS": git_status,
            "FAKE_QA_AFTER_JSON": _a0_qa_job_json(
                immutable_image,
                5,
                execution_count=10 if a0_mode == "qa-executed" else 9,
            ),
            "FAKE_QA_BEFORE_JSON": _a0_qa_job_json(
                "registry.invalid/caseops-api:old",
                4,
            ),
            "FAKE_QA_UPDATED": _bash_path(tmp_path / "qa-updated"),
            "FAKE_PENDING_EXECUTION_JSON": _a0_pending_execution_json(immutable_image),
            "FAKE_REAL_PYTHON": _bash_path(Path(sys.executable)),
            "FAKE_TAG": expected_tag,
            "FAKE_TRAFFIC_MODE": traffic_mode,
        }
    )
    if a0_mode is not None:
        env.update(
            {
                "CASEOPS_A0_CAPTURE_RULE_GOVERNANCE_BASELINE": "true",
                "CASEOPS_A0_RULE_GOVERNANCE_BASELINE_OUTPUT": _bash_path(
                    tmp_path / "a0-baseline.json"
                ),
            }
        )
    command = [
        _find_working_bash(),
        "-c",
        'export PATH="$1:$PATH"; shift; bash scripts/deploy-prod.sh "$@"',
        "deploy-test",
        _bash_path(fake_bin),
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def _run_fingerprint_wrapper_mismatch(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "wrapper-fake-bin"
    fake_bin.mkdir()
    gcloud_log = tmp_path / "wrapper-gcloud.log"
    image = (
        "asia-south1-docker.pkg.dev/perfect-period-305406/"
        "caseops-images/caseops-api@sha256:" + "a" * 64
    )
    expected_sha = "f" * 64
    _write_fake_executable(
        fake_bin / "gcloud",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"run jobs describe caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JOB_JSON}"
elif [[ "$*" == *"run jobs execute caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' '{"metadata":{"name":"caseops-ip-rule-governance-fingerprint-a0-mismatch"}}'
elif [[ "$*" == *"run jobs executions describe"* && \
  "$*" == *"caseops-ip-rule-governance-fingerprint-a0-mismatch"* ]]; then
  printf '%s\n' "${FAKE_EXECUTION_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stdout"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stderr"* ]]; then
  printf ''
fi
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FAKE_EXECUTION_JSON": _a0_execution_json(
                image,
                expected_sha=expected_sha,
                execution_name="caseops-ip-rule-governance-fingerprint-a0-mismatch",
            ),
            "FAKE_FINGERPRINT_JOB_JSON": _a0_fingerprint_job_json(image),
            "FAKE_FINGERPRINT_JSON": _a0_fingerprint_json(),
            "FAKE_GCLOUD_LOG": _bash_path(gcloud_log),
        }
    )
    return subprocess.run(
        [
            _find_working_bash(),
            "-c",
            (
                'export PATH="$1:$PATH"; '
                'bash scripts/ip-rule-governance-fingerprint-job.sh execute "$2" "$3"'
            ),
            "wrapper-test",
            _bash_path(fake_bin),
            image,
            expected_sha,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_deploy_prod_rejects_a_requested_commit_that_is_not_head(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(tmp_path, "1111111", expected_tag="1111111")

    assert result.returncode != 0
    assert "does not match current HEAD" in result.stdout
    assert not (tmp_path / "gcloud.log").exists()


def test_deploy_prod_rejects_dirty_build_context_before_gcloud(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        git_status=" M apps/api/src/caseops_api/main.py",
    )

    assert result.returncode != 0
    assert "build context is dirty" in result.stdout
    assert not (tmp_path / "gcloud.log").exists()


def test_deploy_prod_accepts_clean_head_and_healthy_api(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DONE abcdef1" in result.stdout
    assert (tmp_path / "gcloud.log").is_file()


def test_a0_deploy_captures_final_pre_route_baseline_in_fail_closed_order(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", a0_mode="ok")

    assert result.returncode == 0, result.stdout + result.stderr
    baseline = json.loads((tmp_path / "a0-baseline.json").read_text(encoding="utf-8"))
    assert len(baseline["overall_sha256"]) == 64
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()

    def call_index(fragment: str) -> int:
        return next(index for index, call in enumerate(calls) if fragment in call)

    assert call_index("run jobs execute caseops-migrate-job") < call_index(
        "scheduler_inventory.py reconcile"
    )
    assert call_index("scheduler_inventory.py reconcile") < call_index(
        "run jobs update caseops-ip-qa-bootstrap"
    )
    assert call_index("run jobs update caseops-ip-qa-bootstrap") < call_index(
        "run jobs executions list"
    )
    assert call_index("run jobs executions list") < call_index(
        "run jobs execute caseops-ip-rule-governance-fingerprint-a0"
    )
    assert call_index("run jobs execute caseops-ip-rule-governance-fingerprint-a0") < call_index(
        "run deploy caseops-api"
    )
    assert sum("run jobs executions list" in call for call in calls) == 1


def test_a0_fingerprint_waits_for_terminal_status_and_reads_structured_log(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        a0_mode="pending-structured",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    baseline = json.loads((tmp_path / "a0-baseline.json").read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 1
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    execution_describes = [
        call
        for call in calls
        if "run jobs executions describe caseops-ip-rule-governance-fingerprint-a0-test" in call
    ]
    assert len(execution_describes) == 2
    assert any("logging read" in call and "--format=json" in call for call in calls)
    assert any("auth print-access-token" in call for call in calls)
    assert any("logging.googleapis.com/v2/entries:list" in call for call in calls)


@pytest.mark.parametrize(
    "a0_mode",
    ["qa-executed", "nonterminal", "fingerprint-fail"],
)
def test_a0_deploy_does_not_route_when_pre_route_control_fails(
    tmp_path: Path,
    a0_mode: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", a0_mode=a0_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8")
    assert "run deploy caseops-api" not in calls
    assert not (tmp_path / "a0-baseline.json").exists()


def test_fingerprint_wrapper_fails_on_local_expected_digest_mismatch(
    tmp_path: Path,
) -> None:
    result = _run_fingerprint_wrapper_mismatch(tmp_path)

    assert result.returncode != 0
    assert "did not match the expected overall SHA-256" in result.stderr
    calls = (tmp_path / "wrapper-gcloud.log").read_text(encoding="utf-8")
    assert (
        "run jobs executions describe caseops-ip-rule-governance-fingerprint-a0-mismatch" in calls
    )
    assert 'execution_name"="caseops-ip-rule-governance-fingerprint-a0-mismatch' in calls


@pytest.mark.parametrize(
    ("traffic_mode", "expected_message"),
    [
        ("drift", "TRAFFIC/REVISION DRIFT"),
        ("generation-drift", "TRAFFIC/REVISION DRIFT"),
        ("flag-enabled", "TRAFFIC/REVISION DRIFT"),
        ("image-drift", "REVISION IMAGE DRIFT"),
    ],
)
def test_deploy_prod_fails_closed_on_api_traffic_or_config_drift(
    tmp_path: Path,
    traffic_mode: str,
    expected_message: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, traffic_mode=traffic_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_message in result.stdout
    assert "DONE abcdef1" not in result.stdout


@pytest.mark.parametrize(
    ("curl_mode", "expected_message"),
    [
        ("network-fail", "API health request failed"),
        ("degraded", "API health response is not healthy"),
    ],
)
def test_deploy_prod_fails_closed_on_unhealthy_api(
    tmp_path: Path,
    curl_mode: str,
    expected_message: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, curl_mode=curl_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_message in result.stdout
    assert "=== deploy-prod.sh — DONE" not in result.stdout
