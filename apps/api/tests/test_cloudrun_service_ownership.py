"""Cloud Run resources are never replaced from checked-in manifests.

`scripts/deploy-prod.sh` owns the caseops-api service and deploys it with
`gcloud run deploy`, which carries forward the ClamAV sidecar and every live
value the release does not set. Recurring jobs are created and converged from
`infra/cloudrun/scheduler-inventory.json`. The never-applied
infra/cloudrun/api-service.yaml, retired on 2026-09-27, disagreed with the live
service on command, billing mode, sidecar, probes, CPU boost and CASEOPS_ENV.
A full-spec `gcloud run services replace` from it would have dropped the
scanner and produced a revision unable to pass its required-scanner fence.
"""

from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNED_ROOTS = ("infra", "scripts", ".github", "docs/runbooks")
SCANNED_FILES = ("docs/GCP_DEPLOY.md",)
MANIFEST_SUFFIXES = {".json", ".yaml", ".yml"}
COMMENT_PREFIXES = ("#", "//", "::", "REM ")
LIVE_EXPORT_REPAIR = "scripts/eg003-apply-clamav.sh"
REPLACE_INVOCATION = re.compile(
    r"\b(?P<kind>services|jobs)\s+replace\b"
    r"|[\"'](?P<listed>services|jobs)[\"']\s*,\s*[\"']replace[\"']"
)


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _governed_files() -> list[Path]:
    files = {
        path
        for root in SCANNED_ROOTS
        for path in (REPO_ROOT / root).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    files.update(REPO_ROOT / name for name in SCANNED_FILES)
    files.update(REPO_ROOT.glob("*.y*ml"))
    files.update(REPO_ROOT.glob("apps/*/*.y*ml"))
    return sorted(path for path in files if path.is_file())


def _documents(path: Path) -> list[object]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        return [json.loads(text)]
    return [document for document in yaml.safe_load_all(text) if document is not None]


def _operator_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield lines a tool or an operator would run.

    Scripts and manifests count line by line. Markdown counts only fenced code,
    which is what an operator pastes; prose that warns against a command is not
    an invocation of it.
    """
    # Undecodable bytes must not hide an ASCII invocation, so never skip a file.
    text = path.read_bytes().decode("utf-8", errors="replace")
    markdown = path.suffix == ".md"
    in_code = not markdown
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if markdown and stripped.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code and not stripped.startswith(COMMENT_PREFIXES):
            yield number, line


def test_no_checked_in_manifest_declares_a_cloud_run_service() -> None:
    manifests = [path for path in _governed_files() if path.suffix in MANIFEST_SUFFIXES]
    # A snapshot without these roots would otherwise pass having scanned nothing.
    assert {
        "infra/cloudrun/scheduler-inventory.json",
        "infra/cloudrun/migrate-job.yaml",
        ".github/workflows/ci.yml",
        "apps/api/cloudbuild.yaml",
    } <= {_relative(path) for path in manifests}

    services = [
        _relative(path)
        for path in manifests
        for document in _documents(path)
        if isinstance(document, dict)
        and document.get("kind") == "Service"
        and str(document.get("apiVersion", "")).startswith(
            ("serving.knative.dev/", "run.googleapis.com/")
        )
    ]

    assert services == [], (
        "Cloud Run services are deployed only by scripts/deploy-prod.sh; a full-spec "
        f"service manifest can drop the ClamAV sidecar and live-only settings: {services}"
    )


def test_only_the_live_export_repair_replaces_a_cloud_run_resource() -> None:
    invocations: dict[str, list[str]] = {"jobs": [], "services": []}
    scanned: set[str] = set()
    for path in _governed_files():
        scanned.add(_relative(path))
        for number, line in _operator_lines(path):
            for match in REPLACE_INVOCATION.finditer(line):
                kind = match.group("kind") or match.group("listed")
                invocations[kind].append(f"{_relative(path)}:{number}")
    assert {
        "scripts/deploy-prod.sh",
        LIVE_EXPORT_REPAIR,
        "infra/cloudrun/README.md",
        "docs/GCP_DEPLOY.md",
    } <= scanned

    assert invocations["jobs"] == [], (
        "Recurring jobs are created and converged from scheduler-inventory.json by "
        f"scripts/scheduler_inventory.py, never replaced from a manifest: {invocations['jobs']}"
    )
    assert {entry.rsplit(":", 1)[0] for entry in invocations["services"]} == {
        LIVE_EXPORT_REPAIR
    }, invocations["services"]

    # The one remaining replace starts from the live service and converges the
    # sidecar into that export; it never applies a checked-in specification.
    repair = (REPO_ROOT / LIVE_EXPORT_REPAIR).read_text(encoding="utf-8")
    export = repair.index('--format=export \\\n  > "$WORK/current.yaml"')
    mutate = repair.index('"$PY_BIN" - "$WORK/current.yaml" "$WORK/desired.yaml"')
    replace = repair.index('gcloud run services replace "$WORK/desired.yaml"')
    assert export < mutate < replace
    assert "containers.append(sidecar)" in repair
    assert '"image": "clamav/clamav:1.4"' in repair


API_DEPLOY_LINE = "gcloud run deploy caseops-api \\"
OVERRIDING_FLAGS = {"--command", "--args", "--no-cpu-throttling", "--no-cpu-boost"}
SENSITIVE_ENV = re.compile(r"SECRET|TOKEN|API_KEY|PASSWORD|DATABASE_URL|PUBLIC_KEY")


def _shell_command(text: str) -> list[str]:
    """Tokenize the backslash-continued `gcloud run deploy caseops-api` command."""
    lines = text.splitlines()
    (start,) = [index for index, line in enumerate(lines) if line.strip() == API_DEPLOY_LINE]
    joined = ""
    for line in lines[start:]:
        if not line.endswith("\\"):
            joined += line
            break
        joined += line[:-1]
    return shlex.split(joined)


def _flag_sections(tokens: list[str]) -> dict[str, dict[str, str]]:
    """Split deploy tokens into service-level and per-container flags."""
    sections: dict[str, dict[str, str]] = {"service": {}}
    current = sections["service"]
    position = 4  # past `gcloud run deploy caseops-api`
    while position < len(tokens):
        token = tokens[position]
        position += 1
        if not token.startswith("--"):
            continue  # an array expansion such as "${API_DEPENDENCY_FLAGS[@]}"
        flag, separator, value = token.partition("=")
        if not separator:
            if position < len(tokens) and not tokens[position].startswith("--"):
                value = tokens[position]
                position += 1
            else:
                value = "true"
        if flag == "--container":
            current = sections.setdefault(value, {})
            continue
        assert flag not in current, flag
        current[flag] = value
    return sections


def _release_sections() -> dict[str, dict[str, str]]:
    script = (REPO_ROOT / "scripts" / "deploy-prod.sh").read_text(encoding="utf-8")
    constants: dict[str, str] = {}
    for line in script.splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.+)", line)
        if match:
            name, value = match.group(1), match.group(2).strip('"')
            default = re.fullmatch(rf"\$\{{{name}:-(.+)\}}", value)
            constants.setdefault(name, default.group(1) if default else value)

    def resolve(value: str) -> str:
        return re.sub(
            r"\$\{([A-Z][A-Z0-9_]*)\}", lambda match: constants.get(match[1], match[0]), value
        )

    return {
        section: {flag: resolve(value) for flag, value in flags.items()}
        for section, flags in _flag_sections(_shell_command(script)).items()
    }


def _assignments(value: str) -> dict[str, str]:
    return dict(item.split("=", 1) for item in value.split(","))


def test_fresh_project_bootstrap_creates_the_release_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runbook = (REPO_ROOT / "docs" / "GCP_DEPLOY.md").read_text(encoding="utf-8")
    bootstrap = _flag_sections(_shell_command(runbook))
    release = _release_sections()

    assert list(bootstrap) == list(release) == ["service", "api", "clamav"]
    for flag in ("--concurrency", "--max", "--max-instances", "--min", "--min-instances"):
        assert bootstrap["service"][flag] == release["service"][flag], flag
    assert bootstrap["service"]["--timeout"].rstrip("s") == release["service"]["--timeout"].rstrip(
        "s"
    )
    # The bootstrap declares request-based billing and startup CPU boost, and no
    # release overrides them or the image command.
    assert bootstrap["service"].get("--cpu-throttling") == "true"
    assert bootstrap["service"].get("--cpu-boost") == "true"
    for sections in (bootstrap, release):
        for flags in sections.values():
            assert not OVERRIDING_FLAGS & set(flags)
    for container in ("api", "clamav"):
        assert bootstrap[container]["--startup-probe"] == release[container]["--startup-probe"]
    for flag in ("--port", "--cpu", "--memory"):
        assert bootstrap["api"][flag] == release["api"][flag], flag
    repair = (REPO_ROOT / LIVE_EXPORT_REPAIR).read_text(encoding="utf-8")
    assert (bootstrap["clamav"]["--image"], bootstrap["clamav"]["--cpu"]) == (
        "clamav/clamav:1.4",
        "1",
    )
    assert bootstrap["clamav"]["--memory"] == "1500Mi"
    for resource in ('"image": "clamav/clamav:1.4"', '"cpu": "1"', '"memory": "1500Mi"'):
        assert resource in repair
    assert "|CASEOPS_CLAMAV_REQUIRED=true|" in release["api"]["--update-env-vars"]

    environment = _assignments(bootstrap["api"]["--set-env-vars"])
    secrets = _assignments(bootstrap["api"]["--set-secrets"])
    assert not [name for name in environment if SENSITIVE_ENV.search(name)]
    assert {
        "CASEOPS_DATABASE_URL",
        "CASEOPS_AUTH_SECRET",
        "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET",
        "CASEOPS_LLM_API_KEY",
    } <= set(secrets)

    # The documented environment must pass the production validators and
    # require the sidecar scanner, not merely resemble the release command.
    from caseops_api.core.settings import Settings
    from caseops_api.services import virus_scan

    for name in list(os.environ):
        if name.startswith("CASEOPS_"):
            monkeypatch.delenv(name)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    for index, name in enumerate(sorted(secrets)):
        monkeypatch.setenv(name, f"bootstrap-secret-{index}-{'x' * 40}")
    settings = Settings(_env_file=None)
    assert settings.env == "production"
    assert settings.auto_migrate is False
    host, port, _timeout, required = virus_scan._config_from_env()
    assert (host, port, required) == ("127.0.0.1", 3310, True)


def test_markdown_code_fences_count_as_operator_invocations(tmp_path: Path) -> None:
    runbook = tmp_path / "runbook.md"
    runbook.write_text(
        "Never run `gcloud run services replace` from a checked-in manifest.\n"
        "```bash\n"
        "gcloud run services replace api-service.yaml\n"
        "```\n",
        encoding="utf-8",
    )

    assert [line for _, line in _operator_lines(runbook)] == [
        "gcloud run services replace api-service.yaml"
    ]
