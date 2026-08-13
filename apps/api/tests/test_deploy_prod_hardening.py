from __future__ import annotations

import fnmatch
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
    ["playwright.prod-ram.config.ts", "playwright.notice-prod.config.ts"],
)
def test_production_playwright_does_not_retain_authenticated_media(
    config_path: str,
) -> None:
    config = _read_repo_text(config_path)

    for setting in ('trace: "off"', 'screenshot: "off"', 'video: "off"'):
        assert setting in config
    assert "retain-on-failure" not in config
    assert "only-on-failure" not in config


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
    assert "--min-instances \"${API_MIN_INSTANCES}\"" not in script
    assert "--min-instances \"${WEB_MIN_INSTANCES}\"" not in script
    assert "MIGRATION_TASK_TIMEOUT=30m" in script
    assert '--task-timeout "${MIGRATION_TASK_TIMEOUT}"' in script


def test_deploy_prod_preserves_single_request_instances_with_scale_headroom() -> None:
    """Cloud Run must not reject ordinary UI fan-out while handlers stay sync."""

    script = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/api-service.yaml")

    assert "API_CONCURRENCY=1" in script
    assert 'API_MAX_INSTANCES="${API_MAX_INSTANCES:-20}"' in script
    assert '--max "${API_MAX_INSTANCES}"' in script
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


def _run_deploy_with_fakes(
    tmp_path: Path,
    *arguments: str,
    git_status: str = "",
    curl_mode: str = "ok",
    expected_tag: str = "abcdef1",
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
elif [[ "$*" == *"run jobs describe"* ]]; then
  printf '%s%s\n' \
    'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
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
case "${FAKE_CURL_MODE}" in
  network-fail) exit 22 ;;
  degraded) printf '%s\n' '{"status":"degraded"}' ;;
  *) printf '%s\n' '{"status":"ok"}' ;;
esac
""",
    )
    _write_fake_executable(
        fake_bin / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "scripts/scheduler_inventory.py" ]]; then
  exit 0
fi
exec "${FAKE_REAL_PYTHON}" "$@"
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "FAKE_CURL_MODE": curl_mode,
            "FAKE_GCLOUD_LOG": _bash_path(gcloud_log),
            "FAKE_GIT_STATUS": git_status,
            "FAKE_REAL_PYTHON": _bash_path(Path(sys.executable)),
            "FAKE_TAG": expected_tag,
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
