"""Release packaging boundaries for the exact managed-SaaS license review."""
from __future__ import annotations

import hashlib
import json
import shlex
from pathlib import Path, PurePosixPath

import pytest

ROOT = Path(__file__).resolve().parents[3]
REVIEW = "docs/security/js-license-compliance-review-2026-10-12.md"
REGISTRY = "license-policy/reviewed-packages.json"


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
    assert (
        lines.index("!license-policy/")
        < lines.index("license-policy/**")
        < lines.index(f"!{REGISTRY}")
    )


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
