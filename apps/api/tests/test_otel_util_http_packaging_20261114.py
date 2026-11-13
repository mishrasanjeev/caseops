"""Exact notices and installed identity for the optional telemetry patch cohort."""

from __future__ import annotations

import importlib.metadata
import json
import shlex
import tomllib
from pathlib import Path

import pytest
import yaml

from tests.test_dnspython_security_20261028 import _read_bound, _text
from tests.test_fpdf2_packaging_20261027 import ignored

ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / "apps/api/vendor/opentelemetry-util-http-0.66b2"


def provenance():
    return json.loads(_read_bound(VENDOR / "provenance.json", limit=16384))


def test_optional_distribution_lock_matches_exact_official_artifacts():
    lock = tomllib.loads(_text(ROOT / "apps/api/uv.lock"))
    rows = [row for row in lock["package"] if row["name"] == "opentelemetry-util-http"]
    assert len(rows) == 1
    row = rows[0]
    assert row["version"] == "0.66b2"
    assert row["source"] == {"registry": "https://pypi.org/simple"}
    expected = {
        x["url"]: ("sha256:" + x["sha256"], x["sizeBytes"])
        for x in provenance()["artifacts"]
    }
    assert {x["url"]: (x["hash"], x["size"]) for x in [row["sdist"], *row["wheels"]]} == expected


def test_exact_upstream_notice_is_in_image_upload_and_deployment_boundaries():
    value = provenance()
    assert value["release"]["commit"] == "a34b6fa56948bebb539cfece22adf5d022cc3c19"
    assert value["upstreamLicense"]["wheelLicensePresent"] is False
    assert value["upstreamLicense"]["sdistLicensePresent"] is False
    for name, expected in value["bundledFiles"].items():
        _read_bound(
            VENDOR / name,
            limit=expected["sizeBytes"],
            expected=(expected["sizeBytes"], expected["sha256"]),
        )
    license_bytes = _read_bound(
        VENDOR / "LICENSE",
        limit=11357,
        expected=(11357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
    )
    assert b"Apache License" in license_bytes
    docker = _text(ROOT / "apps/api/Dockerfile")
    copy = (
        "COPY vendor/opentelemetry-util-http-0.66b2 "
        "/usr/share/doc/caseops-api/third-party/opentelemetry-util-http-0.66b2"
    )
    assert docker.splitlines().count(copy) == 1
    assert docker.index(copy) < docker.index("RUN uv export")
    for name in (".dockerignore", ".gcloudignore"):
        patterns = _text(ROOT / "apps/api" / name)
        for file in VENDOR.iterdir():
            relative = "vendor/opentelemetry-util-http-0.66b2/" + file.name
            assert not ignored(relative, patterns)
            assert ignored(relative, patterns + "\nvendor/\n")
    deployment = _text(ROOT / "scripts/deploy-prod.sh")
    assert "API_SOURCE_DIR=apps/api" in deployment
    assert '"${API_SOURCE_DIR}" "apps/web" package.json package-lock.json' in deployment
    assert "git status --porcelain --untracked-files=all --" in deployment


def test_public_notice_bytes_have_exact_cross_checkout_attributes():
    attributes = _text(ROOT / ".gitattributes").splitlines()
    for name in ("LICENSE", "NOTICE.txt", "provenance.json"):
        assert (
            "apps/api/vendor/opentelemetry-util-http-0.66b2/" + name + " text eol=lf"
        ) in attributes
        assert b"\r\n" not in _read_bound(VENDOR / name)


def test_installed_optional_distribution_matches_reviewed_wheel_members():
    try:
        distribution = importlib.metadata.distribution("opentelemetry-util-http")
    except importlib.metadata.PackageNotFoundError:
        pytest.skip("Installed optional cohort requires the observability extra")
    assert distribution.version == "0.66b2"
    for name, expected in provenance()["installedMembers"].items():
        relative = (
            "opentelemetry_util_http-0.66b2.dist-info/METADATA" if name == "METADATA" else name
        )
        _read_bound(
            Path(distribution.locate_file(relative)),
            limit=expected["sizeBytes"],
            expected=(expected["sizeBytes"], expected["sha256"]),
        )


def test_strict_installed_ci_audit_also_admits_optional_cohort():
    workflow = yaml.safe_load(_text(ROOT / ".github/workflows/security.yml"))
    steps = workflow["jobs"]["pip-audit"]["steps"]
    install = [step for step in steps if step.get("name") == "Sync API deps"]
    assert len(install) == 1
    assert shlex.split(install[0]["run"]) == [
        "uv", "sync", "--frozen", "--no-install-project", "--extra", "observability"
    ]
    audit = [step for step in steps if step.get("name") == "Run pip-audit"]
    assert len(audit) == 1
    command = audit[0]["run"]
    assert "uv pip check" in command
    assert "--strict" in command
    assert "--vulnerability-service osv" in command
    assert '--path "$site_packages"' in command
    assert "--ignore-vuln" not in command
