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
import re
from collections.abc import Iterator
from pathlib import Path

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
