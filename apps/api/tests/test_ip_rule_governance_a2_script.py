"""Offline proof of the IPLF-027B A2 config-only enable/rollback operator script.

Every CLI the script reaches is a fake on PATH; nothing calls Google Cloud.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.test_deploy_prod_hardening import (
    REPO_ROOT,
    _bash_path,
    _find_working_bash,
    _write_fake_executable,
)

PROJECT = "offline-project"
REGION = "asia-south1"
SERVICE = "caseops-api"
SHA = "abcdef1234567890abcdef1234567890abcdef12"
REPOSITORY = f"{REGION}-docker.pkg.dev/{PROJECT}/caseops-images/caseops-api"
DIGEST = "sha256:" + "a" * 64
IMAGE = f"{REPOSITORY}@{DIGEST}"
TAGGED_IMAGE = f"{REPOSITORY}:abcdef1"
FLAG = "CASEOPS_IP_RULE_GOVERNANCE_ENABLED"
EXPIRY = "CASEOPS_IP_RULE_GOVERNANCE_ROLLOUT_EXPIRES_AT"
BEFORE_REVISION = "caseops-api-00300-a1a"
AFTER_REVISION = "caseops-api-00301-a2b"

_FAKE_GCLOUD = """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$1 $2 $3" == "run services update" ]]; then
  printf '%s\\n' "$@" > "${FAKE_UPDATE_ARGS}"
  [[ "${FAKE_UPDATE_FAILS}" != "true" ]] || exit 1
  touch "${FAKE_UPDATED}"
elif [[ "$1 $2 $3" == "run services describe" ]]; then
  if [[ -f "${FAKE_UPDATED}" ]]; then
    cat "${FAKE_STATE_DIR}/service-after.json"
  else
    cat "${FAKE_STATE_DIR}/service-before.json"
  fi
elif [[ "$1 $2 $3" == "run revisions describe" ]]; then
  cat "${FAKE_STATE_DIR}/revision-$4.json"
elif [[ "$1 $2 $3 $4" == "artifacts docker images describe" ]]; then
  printf '%s\\n' "${FAKE_TAG_DIGEST}"
else
  exit 90
fi
"""


# The A1 check greps the real checked-out commit, so the pattern is proven
# against the real migration; the fake only maps the offline SHA to HEAD.
_FAKE_GIT = f"""#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "grep" ]]; then
  [[ "${{FAKE_A1_MIGRATION}}" == "present" ]] || exit 1
  arguments=()
  for argument in "$@"; do
    if [[ "${{argument}}" == "{SHA}" ]]; then
      arguments+=(HEAD)
    else
      arguments+=("${{argument}}")
    fi
  done
  exec "${{FAKE_REAL_GIT}}" "${{arguments[@]}}"
fi
exit 91
"""


def _utc_in(days: float) -> str:
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env(flag: str, expiry: str | None, sha: str = SHA) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"name": "CASEOPS_RELEASE_SHA", "value": sha},
        {"name": "CASEOPS_CLAMAV_REQUIRED", "value": "true"},
        {"name": FLAG, "value": flag},
        {
            "name": "CASEOPS_LLM_API_KEY",
            "valueFrom": {"secretKeyRef": {"key": "latest", "name": "caseops-openai-api-key"}},
        },
    ]
    if expiry is not None:
        rows.append({"name": EXPIRY, "value": expiry})
    return rows


def _service(
    revision: str,
    flag: str,
    expiry: str | None,
    *,
    sha: str = SHA,
    template_image: str = TAGGED_IMAGE,
    tagged: bool = False,
    extra_env: dict[str, str] | None = None,
) -> dict[str, object]:
    env = _env(flag, expiry, sha) + [
        {"name": name, "value": value} for name, value in (extra_env or {}).items()
    ]
    spec_traffic: list[dict[str, object]] = [{"latestRevision": True, "percent": 100}]
    status_traffic: list[dict[str, object]] = [
        {"latestRevision": True, "percent": 100, "revisionName": revision}
    ]
    if tagged:
        preview = {"percent": 0, "revisionName": "caseops-api-00250-old", "tag": "preview"}
        spec_traffic.append(preview)
        status_traffic.append(preview)
    return {
        "metadata": {"name": SERVICE, "generation": 9},
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "autoscaling.knative.dev/maxScale": "20",
                        "run.googleapis.com/client-name": "gcloud",
                        "run.googleapis.com/client-version": "568.0.0",
                    }
                },
                "spec": {
                    "containerConcurrency": 1,
                    "timeoutSeconds": 120,
                    "containers": [
                        {"name": "api", "image": template_image, "env": env},
                        {"name": "clamav", "image": "clamav/clamav:1.4"},
                    ],
                },
            },
            "traffic": spec_traffic,
        },
        "status": {
            "observedGeneration": 9,
            "latestCreatedRevisionName": revision,
            "latestReadyRevisionName": revision,
            "conditions": [
                {"type": condition, "status": "True"}
                for condition in ("Ready", "ConfigurationsReady", "RoutesReady")
            ],
            "traffic": status_traffic,
        },
    }


def _revision(
    name: str,
    flag: str,
    expiry: str | None,
    *,
    image: str = IMAGE,
    sha: str = SHA,
    reported_digest: str | None = None,
) -> dict[str, object]:
    status: dict[str, object] = {"conditions": [{"type": "Ready", "status": "True"}]}
    if reported_digest is not None:
        status["imageDigest"] = reported_digest
    return {
        "metadata": {"name": name},
        "spec": {
            "containers": [
                {"name": "api", "image": image, "env": _env(flag, expiry, sha)},
                {"name": "clamav", "image": "clamav/clamav:1.4"},
            ]
        },
        "status": status,
    }


def _run(
    tmp_path: Path,
    mode: str,
    *,
    service_before: dict[str, object],
    revision_before: dict[str, object],
    service_after: dict[str, object] | None = None,
    revision_after: dict[str, object] | None = None,
    extra_arguments: tuple[str, ...] = (),
    expected_image: str = IMAGE,
    expected_sha: str = SHA,
    tag_digest: str = DIGEST,
    update_fails: bool = False,
    a1_migration: bool = True,
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (tmp_path / "evidence").mkdir()
    for name, payload in (
        ("service-before.json", service_before),
        ("service-after.json", service_after or service_before),
        (f"revision-{BEFORE_REVISION}.json", revision_before),
        (f"revision-{AFTER_REVISION}.json", revision_after or revision_before),
    ):
        (state / name).write_text(json.dumps(payload), encoding="utf-8")
    _write_fake_executable(fake_bin / "gcloud", _FAKE_GCLOUD)
    _write_fake_executable(fake_bin / "git", _FAKE_GIT)
    _write_fake_executable(fake_bin / "sleep", "#!/usr/bin/env bash\nexit 0\n")
    _write_fake_executable(
        fake_bin / "python", '#!/usr/bin/env bash\nexec "${FAKE_REAL_PYTHON}" "$@"\n'
    )
    env = os.environ.copy()
    env.update(
        {
            "FAKE_GCLOUD_LOG": _bash_path(tmp_path / "gcloud.log"),
            "FAKE_UPDATE_ARGS": _bash_path(tmp_path / "update-args.txt"),
            "FAKE_UPDATED": _bash_path(tmp_path / "updated"),
            "FAKE_UPDATE_FAILS": "true" if update_fails else "false",
            "FAKE_STATE_DIR": _bash_path(state),
            "FAKE_TAG_DIGEST": tag_digest,
            "FAKE_REAL_PYTHON": _bash_path(Path(sys.executable)),
            "FAKE_REAL_GIT": _bash_path(Path(shutil.which("git") or "git")),
            "FAKE_A1_MIGRATION": "present" if a1_migration else "absent",
        }
    )
    arguments = [
        mode,
        "--project", PROJECT,
        "--region", REGION,
        "--expected-sha", expected_sha,
        "--expected-image", expected_image,
        *extra_arguments,
    ]
    return subprocess.run(
        [
            _find_working_bash(),
            "-c",
            'export PATH="$1:$PATH"; '
            'for cli in gcloud git python sleep; do '
            '[[ "$(command -v "$cli")" == "$1/$cli" ]] || exit 99; done; '
            'shift; bash scripts/ip-rule-governance-a2.sh "$@"',
            "a2-test",
            _bash_path(fake_bin),
            *arguments,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )


def _evidence_path(tmp_path: Path, name: str = "a2.json") -> Path:
    return tmp_path / "evidence" / name


def _enable(tmp_path: Path, expiry: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
    return _run(
        tmp_path,
        "enable",
        extra_arguments=(
            "--rollout-expires-at", expiry,
            "--evidence-output", _bash_path(_evidence_path(tmp_path)),
        ),
        **kwargs,  # type: ignore[arg-type]
    )


def _calls(tmp_path: Path) -> list[str]:
    log = tmp_path / "gcloud.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def _assert_unchanged(tmp_path: Path, result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode != 0, result.stdout + result.stderr
    assert not any(call.startswith("run services update") for call in _calls(tmp_path))
    assert list((tmp_path / "evidence").iterdir()) == []


@pytest.mark.parametrize(
    ("reported_digest", "template_after", "resolves_tag"),
    [
        # gcloud pins a by-tag template to the serving revision's reported
        # digest when an update carries no --image (_SwitchToDigestChange).
        (IMAGE, IMAGE, False),
        # Without a reported digest Cloud Run resolves the tag again, so the
        # tag must still name the expected digest before anything changes.
        (None, TAGGED_IMAGE, True),
    ],
    ids=["gcloud-pins-digest", "tag-resolved-again"],
)
def test_enable_issues_one_config_only_update_and_writes_evidence(
    tmp_path: Path, reported_digest: str | None, template_after: str, resolves_tag: bool
) -> None:
    expiry = _utc_in(30)
    result = _enable(
        tmp_path,
        expiry,
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(
            BEFORE_REVISION, "false", None, reported_digest=reported_digest
        ),
        service_after=_service(AFTER_REVISION, "true", expiry, template_image=template_after),
        revision_after=_revision(AFTER_REVISION, "true", expiry),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    calls = _calls(tmp_path)
    assert sum(call.startswith("run services update") for call in calls) == 1
    assert sum(call.startswith("run ") and "describe" not in call for call in calls) == 1
    assert any(
        call.startswith(f"artifacts docker images describe {TAGGED_IMAGE} ") for call in calls
    ) is resolves_tag
    update = (tmp_path / "update-args.txt").read_text(encoding="utf-8").splitlines()
    assert update == [
        "run", "services", "update", SERVICE,
        "--region", REGION,
        "--project", PROJECT,
        "--quiet",
        "--container", "api",
        "--update-env-vars", f"^|^{FLAG}=true|{EXPIRY}={expiry}",
    ]
    evidence = json.loads(_evidence_path(tmp_path).read_text(encoding="utf-8"))
    assert evidence["mode"] == "enable"
    assert (evidence["release_sha"], evidence["image"], evidence["service"]) == (
        SHA, IMAGE, SERVICE,
    )
    assert evidence["before"] == {
        "revision": BEFORE_REVISION, "environment": {FLAG: "false", EXPIRY: None},
    }
    assert evidence["after"] == {
        "revision": AFTER_REVISION, "environment": {FLAG: "true", EXPIRY: expiry},
    }
    assert evidence["gcloud_update_arguments"] == update[-4:]
    assert evidence["started_at"] <= evidence["updated_at"] <= evidence["completed_at"]
    assert [path.name for path in (tmp_path / "evidence").iterdir()] == ["a2.json"]


def test_rollback_restores_the_a1_configuration_and_writes_evidence(tmp_path: Path) -> None:
    expiry = _utc_in(30)
    result = _run(
        tmp_path,
        "rollback",
        service_before=_service(BEFORE_REVISION, "true", expiry),
        revision_before=_revision(BEFORE_REVISION, "true", expiry),
        service_after=_service(AFTER_REVISION, "false", None),
        revision_after=_revision(AFTER_REVISION, "false", None),
        extra_arguments=("--evidence-output", _bash_path(_evidence_path(tmp_path))),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    update = (tmp_path / "update-args.txt").read_text(encoding="utf-8").splitlines()
    assert update == [
        "run", "services", "update", SERVICE,
        "--region", REGION,
        "--project", PROJECT,
        "--quiet",
        "--container", "api",
        "--remove-env-vars", EXPIRY,
        "--update-env-vars", f"{FLAG}=false",
    ]
    assert sum(call.startswith("run services update") for call in _calls(tmp_path)) == 1
    evidence = json.loads(_evidence_path(tmp_path).read_text(encoding="utf-8"))
    assert evidence["mode"] == "rollback"
    assert evidence["before"]["environment"] == {FLAG: "true", EXPIRY: expiry}
    assert evidence["after"] == {
        "revision": AFTER_REVISION, "environment": {FLAG: "false", EXPIRY: None},
    }


@pytest.mark.parametrize(
    ("service_before", "revision_before", "tag_digest", "expected_error"),
    [
        (
            _service(BEFORE_REVISION, "false", None),
            _revision(BEFORE_REVISION, "false", None, image=f"{REPOSITORY}@sha256:{'b' * 64}"),
            DIGEST,
            f"api image is not {IMAGE}",
        ),
        (
            _service(BEFORE_REVISION, "false", None, sha="1" * 40),
            _revision(BEFORE_REVISION, "false", None, sha="1" * 40),
            DIGEST,
            "service template CASEOPS_RELEASE_SHA is not the expected release",
        ),
        (
            _service(BEFORE_REVISION, "false", None, tagged=True),
            _revision(BEFORE_REVISION, "false", None),
            DIGEST,
            "declared traffic is not one untagged 100% latest-revision entry",
        ),
        (
            _service(BEFORE_REVISION, "true", None),
            _revision(BEFORE_REVISION, "true", None),
            DIGEST,
            f"service template {FLAG} is not false",
        ),
        (
            _service(BEFORE_REVISION, "false", None),
            _revision(BEFORE_REVISION, "false", None),
            "sha256:" + "c" * 64,
            "a new revision would change the image",
        ),
    ],
    ids=["wrong-image", "wrong-sha", "tagged-traffic", "flag-already-true", "tag-moved"],
)
def test_enable_refuses_an_unexpected_starting_point_without_updating(
    tmp_path: Path,
    service_before: dict[str, object],
    revision_before: dict[str, object],
    tag_digest: str,
    expected_error: str,
) -> None:
    result = _enable(
        tmp_path,
        _utc_in(30),
        service_before=service_before,
        revision_before=revision_before,
        tag_digest=tag_digest,
    )

    _assert_unchanged(tmp_path, result)
    assert expected_error in result.stderr


def test_enable_refuses_a_release_without_the_a1_schema_before_any_gcloud_call(
    tmp_path: Path,
) -> None:
    result = _enable(
        tmp_path,
        _utc_in(30),
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(BEFORE_REVISION, "false", None),
        a1_migration=False,
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert f"{SHA} is not a fetched commit carrying A1 migration 20261031_0002" in result.stderr
    assert not (tmp_path / "gcloud.log").exists()


def test_rollback_refuses_when_governance_is_already_off(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        "rollback",
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(BEFORE_REVISION, "false", None),
        extra_arguments=("--evidence-output", _bash_path(_evidence_path(tmp_path))),
    )

    _assert_unchanged(tmp_path, result)
    assert f"service template {FLAG} is not true" in result.stderr


@pytest.mark.parametrize(
    ("mode", "arguments", "expected_error"),
    [
        ("enable", ("--rollout-expires-at", "past"), "must be a UTC timestamp"),
        ("enable", ("--rollout-expires-at", "2020-01-01T00:00:00Z"), "has passed"),
        ("enable", ("--rollout-expires-at", "far"), "more than 180 days away"),
        ("enable", ("--rollout-expires-at", "soon", "--evidence-output", "existing"),
         "refusing to overwrite existing evidence"),
        ("enable", ("--rollout-expires-at", "soon", "--evidence-output", "missing-dir"),
         "does not exist"),
        ("enable", ("--rollout-expires-at", "soon"), "--evidence-output is required"),
        ("rollback", ("--rollout-expires-at", "soon", "--evidence-output", "new"),
         "rollback removes the rollout expiry"),
    ],
    ids=["not-utc", "expired", "beyond-180-days", "evidence-exists", "evidence-dir-missing",
         "evidence-missing", "rollback-with-expiry"],
)
def test_invalid_arguments_stop_before_any_gcloud_call(
    tmp_path: Path, mode: str, arguments: tuple[str, ...], expected_error: str
) -> None:
    existing = tmp_path / "existing.json"
    existing.write_text("{}\n", encoding="utf-8")
    replacements = {
        "soon": _utc_in(30),
        "far": _utc_in(181),
        "existing": _bash_path(existing),
        "missing-dir": _bash_path(tmp_path / "absent" / "a2.json"),
        "new": _bash_path(tmp_path / "new.json"),
    }
    result = _run(
        tmp_path,
        mode,
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(BEFORE_REVISION, "false", None),
        extra_arguments=tuple(replacements.get(argument, argument) for argument in arguments),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert expected_error in result.stderr
    assert not (tmp_path / "gcloud.log").exists()


@pytest.mark.parametrize(
    ("expected_image", "expected_sha", "expected_error"),
    [
        (TAGGED_IMAGE, SHA, "pinned by sha256 digest"),
        (f"registry.invalid/caseops-api@{DIGEST}", SHA, "pinned by sha256 digest"),
        (IMAGE, SHA.upper(), "--expected-sha must be the exact lowercase"),
    ],
    ids=["tag-only", "other-registry", "uppercase-sha"],
)
def test_invalid_release_identity_stops_before_any_gcloud_call(
    tmp_path: Path, expected_image: str, expected_sha: str, expected_error: str
) -> None:
    result = _run(
        tmp_path,
        "rollback",
        service_before=_service(BEFORE_REVISION, "true", None),
        revision_before=_revision(BEFORE_REVISION, "true", None),
        expected_image=expected_image,
        expected_sha=expected_sha,
        extra_arguments=("--evidence-output", _bash_path(_evidence_path(tmp_path))),
    )

    assert result.returncode == 2
    assert expected_error in result.stderr
    assert not (tmp_path / "gcloud.log").exists()


@pytest.mark.parametrize(
    ("service_after", "revision_after", "expected_error"),
    [
        (
            _service(AFTER_REVISION, "true", "EXPIRY"),
            _revision(AFTER_REVISION, "true", "EXPIRY", image=f"{REPOSITORY}@sha256:{'d' * 64}"),
            f"api image is not {IMAGE}",
        ),
        (
            _service(AFTER_REVISION, "true", "EXPIRY", extra_env={"CASEOPS_EXTRA": "1"}),
            _revision(AFTER_REVISION, "true", "EXPIRY"),
            "revision template changed beyond the governance variables: containers",
        ),
        (
            _service(
                AFTER_REVISION, "true", "EXPIRY",
                template_image=f"{REPOSITORY}@sha256:{'e' * 64}",
            ),
            _revision(AFTER_REVISION, "true", "EXPIRY"),
            f"service template image changed to {REPOSITORY}@sha256:{'e' * 64}",
        ),
        (
            _service(BEFORE_REVISION, "true", "EXPIRY"),
            _revision(BEFORE_REVISION, "true", "EXPIRY"),
            f"still serves {BEFORE_REVISION}",
        ),
    ],
    ids=["image-re-resolved", "other-config-changed", "template-image-changed",
         "no-new-revision"],
)
def test_enable_writes_no_evidence_unless_the_new_revision_is_exact(
    tmp_path: Path,
    service_after: dict[str, object],
    revision_after: dict[str, object],
    expected_error: str,
) -> None:
    expiry = _utc_in(30)
    service_after = json.loads(json.dumps(service_after).replace("EXPIRY", expiry))
    revision_after = json.loads(json.dumps(revision_after).replace("EXPIRY", expiry))
    result = _enable(
        tmp_path,
        expiry,
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(BEFORE_REVISION, "false", None),
        service_after=service_after,
        revision_after=revision_after,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert expected_error in result.stderr
    assert sum(call.startswith("run services update") for call in _calls(tmp_path)) == 1
    assert list((tmp_path / "evidence").iterdir()) == []


def test_failed_update_writes_no_evidence(tmp_path: Path) -> None:
    result = _enable(
        tmp_path,
        _utc_in(30),
        service_before=_service(BEFORE_REVISION, "false", None),
        revision_before=_revision(BEFORE_REVISION, "false", None),
        update_fails=True,
    )

    assert result.returncode == 1
    assert "gcloud run services update failed" in result.stderr
    assert list((tmp_path / "evidence").iterdir()) == []
