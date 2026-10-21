"""The CaseOps FastEmbed wheel changes metadata, never upstream runtime or notices."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

API = Path(__file__).resolve().parents[1]
VENDOR = API / "vendor"
SPEC = importlib.util.spec_from_file_location("rebuild_fastembed", VENDOR / "rebuild_fastembed.py")
assert SPEC and SPEC.loader
REBUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REBUILD)


@pytest.fixture
def artifact():
    manifest = json.loads((VENDOR / REBUILD.MANIFEST_NAME).read_text())
    wheel = (VENDOR / REBUILD.WHEEL_NAME).read_bytes()
    REBUILD.verify(wheel, manifest)
    return wheel, manifest, REBUILD.read_members(wheel)


def test_exact_upstream_identity_and_only_metadata_members_changed(artifact):
    _, manifest, _ = artifact
    assert manifest["upstream"]["sha256"] == REBUILD.UPSTREAM_SHA256
    assert manifest["upstream"]["url"] == REBUILD.UPSTREAM_URL
    assert manifest["version"] == "0.8.0" and manifest["build"] == "1caseops1"
    assert set(manifest["changed_members"]) == {
        REBUILD.INFO + name for name in ("METADATA", "WHEEL", "RECORD")
    }
    assert len(manifest["unchanged_members"]) == 61
    assert all(name not in manifest["changed_members"]
               for name in manifest["unchanged_members"] if name.startswith("fastembed/"))
    assert "not an upstream claim" in manifest["description"]


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_upstream_licensed_notices_are_byte_identical(artifact, name):
    _, manifest, members = artifact
    path = REBUILD.INFO + "licenses/" + name
    assert path in manifest["unchanged_members"]
    assert REBUILD.sha256(members[path]) == manifest["unchanged_members"][path]
    assert members[path]


def test_metadata_retains_version_labels_rebuild_and_pins_pillow(artifact):
    _, _, members = artifact
    metadata = BytesParser().parsebytes(members[REBUILD.INFO + "METADATA"])
    wheel = BytesParser().parsebytes(members[REBUILD.INFO + "WHEEL"])
    assert metadata["Name"] == "fastembed" and metadata["Version"] == "0.8.0"
    assert "CaseOps metadata-only" in metadata.get_payload()
    assert "CaseOps-Provenance, " + REBUILD.PROVENANCE_URL in metadata.get_all("Project-URL")
    pillow = [Requirement(line) for line in metadata.get_all("Requires-Dist")
              if Requirement(line).name == "pillow"]
    assert len(pillow) == 3
    assert all(str(requirement.specifier) == "==13.0.0" for requirement in pillow)
    assert wheel["Build"] == "1caseops1" and wheel["Root-Is-Purelib"] == "true"
    assert wheel["Tag"] == "py3-none-any"


def test_project_and_frozen_lock_bind_exact_local_wheel_without_override(artifact):
    _, manifest, _ = artifact
    project = tomllib.loads((API / "pyproject.toml").read_text())
    lock = tomllib.loads((API / "uv.lock").read_text())
    expected = "vendor/" + REBUILD.WHEEL_NAME
    assert project["tool"]["uv"]["sources"]["fastembed"] == {"path": expected}
    assert not project["tool"]["uv"].get("override-dependencies")
    fastembed = next(item for item in lock["package"] if item["name"] == "fastembed")
    assert fastembed["version"] == "0.8.0" and fastembed["source"] == {"path": expected}
    assert fastembed["wheels"][0]["hash"] == "sha256:" + manifest["rebuilt"]["sha256"]
    pillow = next(item for item in lock["package"] if item["name"] == "pillow")
    assert pillow["version"] == "13.0.0"


def test_rebuilder_rejects_every_nonofficial_input_without_patching_code(artifact):
    wheel, _, _ = artifact
    with pytest.raises(ValueError, match="exact reviewed official"):
        REBUILD.rebuild(wheel)


def test_verifier_rejects_tampered_wheel(artifact):
    wheel, manifest, _ = artifact
    with pytest.raises(ValueError, match="digest differs"):
        REBUILD.verify(wheel + b"unreviewed", manifest)


def test_full_rebuild_from_pinned_official_wheel_matches_committed_bytes_and_manifest(artifact):
    wheel, manifest, members = artifact
    upstream = (API / "tests/fixtures/fastembed" / REBUILD.UPSTREAM_NAME).read_bytes()
    assert REBUILD.sha256(upstream) == REBUILD.UPSTREAM_SHA256
    rebuilt, rebuilt_manifest = REBUILD.rebuild(upstream)
    assert rebuilt == wheel and rebuilt_manifest == manifest
    encoded = (json.dumps(rebuilt_manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    assert encoded.encode() == (VENDOR / REBUILD.MANIFEST_NAME).read_bytes()
    original = REBUILD.read_members(upstream)
    for name in manifest["unchanged_members"]:
        assert members[name] == original[name]


def test_reviewed_artifacts_survive_native_git_autocrlf_checkout(tmp_path):
    root = API.parents[1]
    repo, checkout = tmp_path / "repo", tmp_path / "checkout"
    repo.mkdir()
    checkout.mkdir()
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], env=env, check=True, capture_output=True,
        )

    git("init", "--quiet")
    git("config", "core.autocrlf", "true")
    paths = [
        ".gitattributes",
        "apps/api/vendor/" + REBUILD.MANIFEST_NAME,
        "apps/api/vendor/" + REBUILD.WHEEL_NAME,
        "apps/api/tests/fixtures/fastembed/" + REBUILD.UPSTREAM_NAME,
    ]
    for relative in paths:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    git("add", "--", *paths)
    git("checkout-index", "--all", "--prefix=" + checkout.as_posix() + "/")
    for relative in paths[1:]:
        assert (checkout / relative).read_bytes() == (root / relative).read_bytes()


def test_structured_metadata_preserves_other_fields_dependencies_markers_and_body(artifact):
    _, manifest, members = artifact
    upstream = (API / "tests/fixtures/fastembed" / REBUILD.UPSTREAM_NAME).read_bytes()
    before = BytesParser(policy=policy.default).parsebytes(
        REBUILD.read_members(upstream)[REBUILD.INFO + "METADATA"]
    )
    after = BytesParser(policy=policy.default).parsebytes(members[REBUILD.INFO + "METADATA"])
    fields = {key for key in before.keys()} - {"Requires-Dist", "Project-URL"}
    for field in fields:
        assert before.get_all(field) == after.get_all(field)
    assert after.get_all("Project-URL")[:-1] == before.get_all("Project-URL")
    before_req = [Requirement(value) for value in before.get_all("Requires-Dist")]
    after_req = [Requirement(value) for value in after.get_all("Requires-Dist")]
    assert len(before_req) == len(after_req)
    for old, new in zip(before_req, after_req, strict=True):
        if old.name == "pillow":
            assert old.marker == new.marker and old.extras == new.extras and old.url == new.url
            assert str(new.specifier) == "==13.0.0"
        else:
            assert old == new
    assert after.get_payload(decode=True) == (
        manifest["description"].encode() + b"\n\n" + before.get_payload(decode=True)
    )


@pytest.mark.parametrize("existing_name", [REBUILD.WHEEL_NAME, REBUILD.MANIFEST_NAME])
def test_cli_preflights_both_outputs_and_preserves_existing_bytes(
    tmp_path, monkeypatch, existing_name,
):
    existing = tmp_path / existing_name
    existing.write_bytes(b"previous-reviewed-artifact")
    monkeypatch.setattr(sys, "argv", [
        "rebuild_fastembed", "--upstream",
        str(API / "tests/fixtures/fastembed" / REBUILD.UPSTREAM_NAME),
        "--output", str(tmp_path),
    ])
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        REBUILD.main()
    assert existing.read_bytes() == b"previous-reviewed-artifact"
    assert {item.name for item in tmp_path.iterdir()} == {existing_name}


def test_cli_exclusive_creation_rejects_a_file_created_after_preflight(tmp_path, monkeypatch):
    target = tmp_path / REBUILD.WHEEL_NAME
    real_open = Path.open

    def create_between_check_and_open(path, mode="r", *args, **kwargs):
        if path == target and mode == "xb":
            with real_open(path, "wb") as concurrent_writer:
                concurrent_writer.write(b"concurrent-existing-artifact")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", create_between_check_and_open)
    monkeypatch.setattr(sys, "argv", [
        "rebuild_fastembed", "--upstream",
        str(API / "tests/fixtures/fastembed" / REBUILD.UPSTREAM_NAME),
        "--output", str(tmp_path),
    ])
    with pytest.raises(FileExistsError):
        REBUILD.main()
    assert target.read_bytes() == b"concurrent-existing-artifact"
    assert not (tmp_path / REBUILD.MANIFEST_NAME).exists()


def test_security_audits_complete_installed_metadata_without_resolving_upstream_bounds():
    workflow = yaml.safe_load((API.parents[1] / ".github/workflows/security.yml").read_text())
    steps = workflow["jobs"]["pip-audit"]["steps"]
    sync = next(step for step in steps if step.get("name") == "Sync API deps")
    audit = next(step for step in steps if step.get("name") == "Run pip-audit")["run"]
    assert sync["run"] == "uv sync --frozen --no-install-project"
    assert "uv pip check\n" in audit
    assert '--strict' in audit and '--vulnerability-service osv' in audit
    assert '--path "$site_packages"' in audit
    assert 'assert paths["purelib"] == paths["platlib"]' in audit
    assert not any(flag in audit for flag in ("--ignore", "--no-deps", "--disable-pip", "--fix"))
