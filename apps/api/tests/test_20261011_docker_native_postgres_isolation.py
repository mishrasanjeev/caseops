"""Offline wrapper regression; no application dependencies or real Docker calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = REPO_ROOT / "scripts/verify-docker.ps1"
SHELL_NAMES = ["powershell", "pwsh"] if os.name == "nt" else ["pwsh"]
EXPECTED_CASES = [
    "isolated-migrate-seed-index-and-full-pytest",
    "restore-unset-native-environment",
    "existing-database-refused-without-drop",
    "creation-exception-without-drop",
    "extension-exit-restores-and-drops",
    "independent-upgrade-exit-restores-and-drops",
    "exact-image-seed-exit-restores-and-drops",
    "pre-index-exit-restores-and-drops",
    "pytest-exit-preserved-after-cleanup",
    "pytest-exception-restores-location-and-environment",
    "missing-journal-fails-closed",
    "post-index-exit-restores-and-drops",
    "cleanup-only-exit-fails-gate",
    "cleanup-only-exception-fails-gate",
    "primary-exit-survives-cleanup-exit",
    "primary-exception-survives-cleanup-exception",
    "reject-project-sql-shell-injection",
    "reject-uppercase-project-identity",
    "reject-mismatched-release-project",
    "reject-malformed-release",
    "reject-port-injection",
    "reject-out-of-range-port",
    "reject-uninspected-image",
    "reject-network-injection",
    "reject-browser-native-url",
    "reject-foreign-browser-url",
    "second-invocation-migrates-independent-empty-database",
]
EXPECTED_CAPTURE_CASES = [
    "bounded-safe-capture-before-owned-cleanup",
    "logs-exit-is-separate-and-state-still-captured",
    "logs-exception-is-separate-and-state-still-captured",
    "inventory-exit-is-separate",
    "invalid-container-id-never-inspected",
    "container-inventory-is-bounded",
    "state-exit-is-separate",
    "manifest-io-error-preserves-primary-exception",
    "capture-exception-preserves-primary-exception",
    "repeated-capture-never-overwrites-evidence",
]


@pytest.mark.parametrize("shell_name", SHELL_NAMES)
def test_actual_gate_with_fake_commands_and_reconciled_inventory(
    shell_name: str, tmp_path: Path
) -> None:
    shell = shutil.which(shell_name)
    assert shell, f"The wrapper guard requires {shell_name}, not a skipped success."
    evidence = tmp_path / "retained-guard-evidence"
    environment = os.environ.copy()
    environment.update(
        CASEOPS_TEST_POSTGRES_URL="outer-test-url",
        CASEOPS_DATABASE_URL="outer-application-url",
        CASEOPS_E2E_DATABASE_URL="outer-browser-url",
    )
    result = subprocess.run(
        [
            shell,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "tests/docker-native-postgres-isolation-guard.ps1"),
            "-EvidenceDirectory",
            str(evidence),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    (tmp_path / "guard.stdout.log").write_text(result.stdout, encoding="utf-8")
    (tmp_path / "guard.stderr.log").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "27 regression cases passed" in result.stdout
    inventory = json.loads((evidence / "guard-inventory.json").read_text(encoding="utf-8-sig"))
    reports = [
        json.loads(line)
        for line in (evidence / "guard-results.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    completion = json.loads((evidence / "guard-completion.json").read_text(encoding="utf-8-sig"))
    assert inventory == EXPECTED_CASES
    assert [report["nodeid"] for report in reports] == EXPECTED_CASES
    assert all(report["outcome"] == "passed" for report in reports)
    assert completion == {"event": "execution_finished", "tests": 27, "exit_code": 0}
    native_run = reports[0]["invocations"]
    urls = {command["test_url"] for command in native_run if command["stage"] == "pytest"}
    assert urls == {
        "postgresql+psycopg://caseops:caseops@127.0.0.1:25432/"
        "caseops_native_111111111111_aaaaaaaaaaaa"
    }
    assert all(command["browser_url"].endswith("/caseops") for command in native_run)


def test_standard_gate_keeps_full_native_inventory_and_browser_boundaries() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    main = source.split('$PinnedNodeVersion =', 1)[1]
    assert main.index("stop --timeout 30 worker") < main.index(
        "Invoke-IsolatedNativePostgresGate -Validation {"
    ) < main.index("& $ApiPython @NativeArguments")
    assert main.count("& $ApiPython @NativeArguments") == 1
    assert '(Join-Path $RepoRoot "scripts\\run_postgres_acceptance.py")' in main
    assert '"--api-dir", $ApiDir, "--results-directory", $ResultsDirectory' in main
    assert 'Join-Path $ResultsDirectory "postgres-driver-completion.json"' in main
    assert "$NativeCompletion.shards -ne 8" in main
    assert "-not $NativeCompletion.source_unchanged" in main
    assert "$NativeCompletion.collected -lt 1" in main
    assert (
        'CASEOPS_TEST_RESULT_JOURNAL = (Join-Path $ResultsDirectory "postgres-results.jsonl")'
    ) in main
    assert "did not retain its incremental result journal" in main
    assert "--retries" not in source and "--maxfail" not in source
    assert 'Assert-CandidateSourceUnchanged -Stage "before isolated PostgreSQL acceptance"' in main
    assert 'Assert-CandidateSourceUnchanged -Stage "after isolated PostgreSQL acceptance"' in main
    assert main.index("Invoke-IsolatedNativePostgresGate -Validation {") < main.index(
        "PostgreSQL post-rehearsal index health gate failed."
    ) < main.index("start worker")
    seed = (
        "& docker compose --project-name $ComposeProject --file $ComposeFile "
        "exec --no-TTY api python -m caseops_api.scripts.seed_statutes"
    )
    assert main.count(seed) == 1
    assert main.index("$ImageRevision -ne $ReleaseSha") < main.index(seed)
    assert main.index("& $ApiPython @NativeArguments") < main.index(seed)
    assert main.index(seed) < main.index("start worker") < main.index(
        'Assert-CandidateSourceUnchanged -Stage "before browser acceptance"'
    )
    assert 'tests\\docker-native-postgres-isolation-guard.ps1' in main


def test_native_environment_scope_and_fixed_browser_secret() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    acceptance = source.split("$AcceptanceEnvironment = @{", 1)[1].split("\n}", 1)[0]
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert 'CASEOPS_E2E_AUTH_SECRET = "change-me-change-me-change-me-2026"' in acceptance
    assert "CASEOPS_AUTH_SECRET: change-me-change-me-change-me-2026" in compose
    assert (
        'CASEOPS_E2E_DATABASE_URL = "postgresql+psycopg://caseops:caseops@127.0.0.1:'
        '$PostgresPort/caseops"'
    ) in acceptance
    gate = source.split("function Invoke-IsolatedNativePostgresGate {", 1)[1].split(
        "$PinnedNodeVersion =", 1
    )[0]
    assert '@("CASEOPS_TEST_POSTGRES_URL", "CASEOPS_DATABASE_URL")' in gate
    assert 'SetEnvironmentVariable($Name, $SavedNativeEnvironment[$Name], "Process")' in gate
    assert 'SetEnvironmentVariable("CASEOPS_E2E_DATABASE_URL"' not in gate
    assert '"--template", "template0", "--", $NativeDatabaseName' in gate
    assert "createdb" in gate and "dropdb" in gate
    assert "DROP DATABASE" not in gate and "CREATE DATABASE" not in gate
    assert "sh -c" not in gate and "Invoke-Expression" not in gate
    assert gate.count("& docker @NativeImageArguments caseops-db-index-health") == 2
    assert "& docker @NativeImageArguments alembic upgrade head" in gate
    assert "& docker @NativeImageArguments python -m caseops_api.scripts.seed_statutes" in gate


def test_dedicated_migration_rehearsals_and_http_template_remain_independent() -> None:
    migration = (REPO_ROOT / "apps/api/tests/test_postgres_validation.py").read_text(
        encoding="utf-8"
    )
    fixtures = (REPO_ROOT / "apps/api/tests/fixtures_postgres_client.py").read_text(
        encoding="utf-8"
    )
    assert 'database_name = f"caseops_migration_{uuid4().hex}"' in migration
    assert 'connection.exec_driver_sql(f"CREATE DATABASE {identifier}")' in migration
    assert 'command.upgrade(config, "head")' in migration
    assert "original_catalogue" in migration and "original_revision" in migration
    assert "with temporary_http_database(source_url) as template:" in fixtures
    assert 'command.upgrade(config, "head")' in fixtures
    assert 'ALLOW_CONNECTIONS false' in fixtures
    assert 'template.database if template is not None else \'template0\'' in fixtures
    assert "template=migrated_http_template" in fixtures


@pytest.mark.parametrize("shell_name", SHELL_NAMES)
def test_failure_evidence_capture_before_cleanup_preserves_primary_exception(
    shell_name: str, tmp_path: Path
) -> None:
    shell = shutil.which(shell_name)
    assert shell, f"Failure evidence guard requires {shell_name}."
    evidence = tmp_path / "retained-capture-evidence"
    result = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(REPO_ROOT / "tests/docker-failure-evidence-guard.ps1"),
            "-EvidenceDirectory", str(evidence),
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
    )
    (tmp_path / "guard.stdout.log").write_text(result.stdout, encoding="utf-8")
    (tmp_path / "guard.stderr.log").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "10 regression cases passed" in result.stdout
    inventory = json.loads((evidence / "guard-inventory.json").read_text(encoding="utf-8-sig"))
    reports = [
        json.loads(line)
        for line in (evidence / "guard-results.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    completion = json.loads((evidence / "guard-completion.json").read_text(encoding="utf-8-sig"))
    assert inventory == EXPECTED_CAPTURE_CASES
    assert [report["nodeid"] for report in reports] == EXPECTED_CAPTURE_CASES
    assert all(report["outcome"] == "passed" for report in reports)
    assert completion == {"event": "execution_finished", "tests": 10, "exit_code": 0}


@pytest.mark.parametrize("shell_name", SHELL_NAMES)
def test_release_image_identity_uses_actual_inspected_caller(
    shell_name: str, tmp_path: Path
) -> None:
    shell = shutil.which(shell_name)
    assert shell, f"Release image guard requires {shell_name}."
    evidence = tmp_path / "image-identity"
    result = subprocess.run(
        [
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
            str(REPO_ROOT / "tests/docker-release-image-identity-guard.ps1"),
            "-EvidenceDirectory", str(evidence),
        ],
        cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False,
    )
    (tmp_path / "image-guard.stdout.log").write_text(result.stdout, encoding="utf-8")
    (tmp_path / "image-guard.stderr.log").write_text(result.stderr, encoding="utf-8")
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "10 regression cases passed" in result.stdout
    expected = [
        "abbreviated-compose-image-resolves-canonical",
        "bare-full-compose-image-resolves-canonical",
        "canonical-compose-image-retains-canonical",
        "invalid-compose-handle-rejected",
        "compose-exit-rejected",
        "inspect-exit-rejected",
        "empty-inspection-rejected",
        "ambiguous-inspection-rejected",
        "noncanonical-inspected-id-rejected",
        "wrong-release-image-rejected",
    ]
    inventory = json.loads((evidence / "guard-inventory.json").read_text(encoding="utf-8-sig"))
    reports = [
        json.loads(line)
        for line in (evidence / "guard-results.jsonl").read_text(encoding="utf-8-sig").splitlines()
    ]
    completion = json.loads((evidence / "guard-completion.json").read_text(encoding="utf-8-sig"))
    assert inventory == expected
    assert [report["nodeid"] for report in reports] == expected
    assert all(report["outcome"] == "passed" for report in reports)
    assert completion == {
        "event": "execution_finished", "tests": 10, "failures": 0, "exit_code": 0
    }
    source = WRAPPER.read_text(encoding="utf-8")
    assert 'tests\\docker-release-image-identity-guard.ps1' in source
    assert '$ApiImageId = $ImageMetadata[0].Id' in source
    assert '$ApiImageId = $ImageId' not in source
