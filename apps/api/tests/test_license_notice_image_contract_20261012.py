"""Release packaging boundaries for the exact managed-SaaS license review."""
from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
REVIEW = "docs/security/js-license-compliance-review-2026-10-12.md"
REGISTRY = "license-policy/reviewed-packages.json"


def test_security_runs_and_retains_the_native_upload_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text())
    job = workflow["jobs"]["web-upload-context"]
    assert job["timeout-minutes"] == 5
    steps = job["steps"]
    sdk = next(
        step for step in steps
        if step.get("uses", "").startswith("google-github-actions/setup-gcloud@")
    )
    assert sdk["uses"] == (
        "google-github-actions/setup-gcloud@e427ad8a34f8676edf47cf7d7925499adf3eb74f"
    )
    assert sdk["with"]["version"] == "568.0.0"
    runs = [step for step in steps if "run" in step]
    assert len(runs) == 1
    assert shlex.split(runs[0]["run"]) == [
        "python3", "-B", "-m", "unittest", "discover", "-s", "scripts/tests",
        "-p", "test_web_upload_context.py", "-v",
    ]
    assert runs[0]["env"] == {
        "CASEOPS_WEB_UPLOAD_EVIDENCE": "${{ runner.temp }}/web-upload-context",
    }
    artifact = steps[-1]
    assert artifact["uses"] == "actions/upload-artifact@v4"
    assert artifact["if"] == "always()"
    assert artifact["with"] == {
        "name": "web-upload-context-native", "path": "${{ runner.temp }}/web-upload-context",
        "if-no-files-found": "error",
    }


@pytest.mark.parametrize("name", [".dockerignore", ".gcloudignore"])
def test_compliance_context_is_narrow_and_blocks_hidden_material(name):
    lines = (ROOT / name).read_text().splitlines()
    assert lines[0] == "**"
    admitted = {line for line in lines if line.startswith(("!license-policy/", "!docs/"))}
    assert admitted == {
        "!license-policy/", f"!{REGISTRY}", "!license-policy/upstream/",
        "!license-policy/upstream/**", "!docs/", "!docs/security/", f"!{REVIEW}",
    }
    assert "license-policy/upstream/**/.*" in lines
    reset = "license-policy/*" if name == ".gcloudignore" else "license-policy/**"
    assert (
        lines.index("!license-policy/")
        < lines.index(reset)
        < lines.index(f"!{REGISTRY}")
    )
    suffix = "*" if name == ".gcloudignore" else "**"
    assert (
        lines.index("!docs/") < lines.index(f"docs/{suffix}")
        < lines.index("!docs/security/") < lines.index(f"docs/security/{suffix}")
        < lines.index(f"!{REVIEW}")
    )
    assert lines.index("apps/web/.env*") < lines.index("!apps/web/.env.local.example")


def test_runner_retains_public_notices_and_nonpublic_operator_materials():
    dockerfile = (ROOT / "apps/web/Dockerfile").read_text()
    runner = dockerfile.split("FROM node:22.14.0-alpine AS runner", 1)[1]
    copies = [shlex.split(line) for line in runner.splitlines() if line.startswith("COPY ")]
    public = [tokens for tokens in copies if tokens[-2:] == ["/app/apps/web/public", "./public"]]
    assert len(public) == 1 and "--from=builder" in public[0]
    expected = {
        REGISTRY: f"/app/third-party-compliance/{REGISTRY}",
        "license-policy/upstream/": "/app/third-party-compliance/license-policy/upstream/",
        REVIEW: f"/app/third-party-compliance/{REVIEW}",
    }
    compliance = [
        tokens for tokens in copies
        if tokens[-2].startswith(("license-policy/", "docs/security/"))
    ]
    assert {tokens[-2]: tokens[-1] for tokens in compliance} == expected
    assert len(compliance) == len(expected)
    for tokens in compliance:
        target = PurePosixPath(tokens[-1])
        assert target.is_relative_to("/app/third-party-compliance")
        assert not target.is_relative_to("/app/apps/web/public")
        assert not target.is_relative_to("/app/apps/web/.next")
    notices = [tokens for tokens in copies if tokens[-2:] == [
        "/app/apps/web/public/third-party-notices",
        "/app/third-party-compliance/apps/web/public/third-party-notices",
    ]]
    assert len(notices) == 1 and "--from=builder" in notices[0]


def test_shipped_upstream_inventory_equals_hash_bound_review_materials():
    record = json.loads((ROOT / REGISTRY).read_text())
    assert len(record["packages"]) == 19
    expected = {
        material["path"]: material["sha256"]
        for entry in record["packages"] for material in entry["materials"]
        if material["path"].startswith("license-policy/upstream/")
    }
    actual = set()
    for visited, path in enumerate((ROOT / "license-policy/upstream").rglob("*"), start=1):
        assert visited <= 128
        assert not path.is_symlink() and not path.is_junction()
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        assert relative in expected, "Undeclared operator material must not enter the image"
        actual.add(relative)
        assert len(actual) <= 64
        assert path.stat().st_size <= 1024 * 1024
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected[relative]
    assert actual == set(expected)
    assert len(actual) == 54
    document_hash = hashlib.sha256((ROOT / REVIEW).read_bytes()).hexdigest()
    assert document_hash == record["review_document"]["sha256"]
