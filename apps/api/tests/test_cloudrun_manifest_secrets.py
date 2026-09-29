from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER = REPO_ROOT / "scripts" / "check_cloudrun_manifest_secrets.py"
INVENTORY = REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json"


def _run_scanner(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCANNER), str(target)],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )


def test_cloudrun_secret_scanner_accepts_secret_refs_and_explicit_placeholders(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "safe.yaml"
    manifest.write_text(
        """apiVersion: serving.knative.dev/v1
kind: Service
spec:
  template:
    spec:
      containers:
        - env:
            - name: CASEOPS_AUTH_SECRET
              valueFrom:
                secretKeyRef:
                  name: caseops-auth-secret
                  key: latest
            - name: CASEOPS_PROVIDER_TOKEN
              value: "${PROVIDER_TOKEN}"
            - name: CASEOPS_DATABASE_URL
              value: "__DATABASE_URL__"
            - name: CASEOPS_ENV
              value: cloud
""",
        encoding="utf-8",
    )

    result = _run_scanner(manifest)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "checked 1 manifest" in result.stdout


def test_cloudrun_secret_scanner_rejects_even_short_literal_secret_values(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "unsafe.yaml"
    manifest.write_text(
        """apiVersion: run.googleapis.com/v1
kind: Job
spec:
  template:
    spec:
      template:
        spec:
          containers:
            - env:
                - name: CASEOPS_API_KEY
                  value: short
""",
        encoding="utf-8",
    )

    result = _run_scanner(manifest)

    assert result.returncode == 1
    assert f"{manifest}:10:" in result.stdout
    assert "CASEOPS_API_KEY uses a literal value" in result.stdout


def test_cloudrun_secret_scanner_requires_secret_key_ref(tmp_path: Path) -> None:
    manifest = tmp_path / "wrong-ref.yml"
    manifest.write_text(
        """env:
  - name: CASEOPS_AUTH_PASSWORD
    valueFrom:
      configMapKeyRef:
        name: not-a-secret
        key: password
""",
        encoding="utf-8",
    )

    result = _run_scanner(manifest)

    assert result.returncode == 1
    assert "CASEOPS_AUTH_PASSWORD must use valueFrom.secretKeyRef" in result.stdout


def test_repository_cloudrun_manifests_pass_secret_scanner() -> None:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))

    result = _run_scanner(REPO_ROOT / "infra" / "cloudrun")

    assert result.returncode == 0, result.stdout + result.stderr
    # The recurring-job inventory is the applied definition; a pass that never
    # parsed it would be the pre-2026-09-27 gate, which scanned only the
    # unapplied job YAMLs.
    assert (
        f"including {len(inventory['jobs'])} scheduler-inventory job contracts"
        in result.stdout
    )


def _inventory_copy(tmp_path: Path, mutate: Callable[[dict[str, Any]], None]) -> Path:
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    mutate(inventory)
    path = tmp_path / "scheduler-inventory.json"
    path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return path


def _bootstrap(inventory: dict[str, Any], run_job_name: str) -> dict[str, Any]:
    return next(
        job["bootstrap"] for job in inventory["jobs"] if job["run_job_name"] == run_job_name
    )


def test_cloudrun_secret_scanner_rejects_a_literal_secret_in_the_inventory(
    tmp_path: Path,
) -> None:
    # scheduler_inventory.py hands bootstrap.environment to --set-env-vars
    # verbatim, so a credential moved there would be applied as plain text.
    def move_sendgrid_key_to_environment(inventory: dict[str, Any]) -> None:
        bootstrap = _bootstrap(inventory, "caseops-activity-report")
        del bootstrap["secrets"]["CASEOPS_SENDGRID_API_KEY"]
        bootstrap["environment"]["CASEOPS_SENDGRID_API_KEY"] = "SG.literal-canary"

    result = _run_scanner(_inventory_copy(tmp_path, move_sendgrid_key_to_environment))

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "caseops-activity-report: CASEOPS_SENDGRID_API_KEY is a literal bootstrap "
        "environment value"
    ) in result.stdout
    assert "SG.literal-canary" not in result.stdout + result.stderr


def test_cloudrun_secret_scanner_requires_secret_manager_inventory_references(
    tmp_path: Path,
) -> None:
    def inline_database_url(inventory: dict[str, Any]) -> None:
        _bootstrap(inventory, "caseops-ip-journal-watch")["secrets"][
            "CASEOPS_DATABASE_URL"
        ] = "postgresql+psycopg://caseops:canary-password@/caseops"

    result = _run_scanner(_inventory_copy(tmp_path, inline_database_url))

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "caseops-ip-journal-watch: bootstrap.secrets.CASEOPS_DATABASE_URL must be a "
        "Secret Manager <secret>:<version> reference"
    ) in result.stdout
    assert "canary-password" not in result.stdout + result.stderr


def test_cloudrun_secret_scanner_rejects_a_name_that_is_both_value_and_secret(
    tmp_path: Path,
) -> None:
    def shadow_auth_secret(inventory: dict[str, Any]) -> None:
        _bootstrap(inventory, "caseops-reminders-job")["environment"][
            "CASEOPS_AUTH_SECRET"
        ] = "shadow-canary"

    result = _run_scanner(_inventory_copy(tmp_path, shadow_auth_secret))

    assert result.returncode == 1, result.stdout + result.stderr
    assert (
        "caseops-reminders-job: CASEOPS_AUTH_SECRET is both a bootstrap environment "
        "value and a secret"
    ) in result.stdout


def test_cloudrun_secret_scanner_fails_closed_without_definitions(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("no Cloud Run definitions here\n", encoding="utf-8")

    result = _run_scanner(tmp_path)

    assert result.returncode == 2
    assert "no Cloud Run definitions found" in result.stderr


def test_cloudrun_secret_scanner_rejects_unrecognized_json(tmp_path: Path) -> None:
    definition = tmp_path / "service.json"
    definition.write_text('{"env": [{"name": "CASEOPS_API_KEY"}]}\n', encoding="utf-8")

    result = _run_scanner(definition)

    assert result.returncode == 2
    assert "is not a scheduler inventory" in result.stderr


def test_security_workflow_invokes_yaml_aware_manifest_scanner() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/check_cloudrun_manifest_secrets.py infra/cloudrun" in workflow
    assert "grep -REn '^\\s*value:" not in workflow
