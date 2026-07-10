from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER = REPO_ROOT / "scripts" / "check_cloudrun_manifest_secrets.py"


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
    result = _run_scanner(REPO_ROOT / "infra" / "cloudrun")

    assert result.returncode == 0, result.stdout + result.stderr


def test_security_workflow_invokes_yaml_aware_manifest_scanner() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8"
    )

    assert "scripts/check_cloudrun_manifest_secrets.py infra/cloudrun" in workflow
    assert "grep -REn '^\\s*value:" not in workflow
