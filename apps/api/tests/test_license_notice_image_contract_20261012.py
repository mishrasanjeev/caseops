"""Release packaging boundaries for the exact managed-SaaS license review."""
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
REVIEW = "docs/security/js-license-compliance-review-2026-10-12.md"
REGISTRY = "license-policy/reviewed-packages.json"
QR_SOURCE = "license-policy/upstream/qrcode.react_4.2.0/qrcodegen-LICENSE.txt"
QR_SOURCE_SHA256 = "ba5a977288ff7463c51ea0cc5bf5a34372707985655c1ccc054f2a0caa3d9bff"
NODE_SOURCE = "license-policy/upstream/node_22.23.4/LICENSE"
NODE_SOURCE_SHA256 = "c738ae413cf561f174e34f6961f8ca458aae2369a73640dda6234c629b98bcc4"
NEXT_SOURCE = "license-policy/upstream/next_16.4.6/LICENSE.md"
NEXT_SOURCE_SHA256 = "ee765244e2d59f5234d474f62e0766fa0c8b99af967fdd4c0cb8dcb0c76ea224"
BUILD_TOOL_SOURCES = {
    "license-policy/upstream/_npmcli_arborist_9.9.3/LICENSE.md":
        "27d998b503b18cdb16c49e93da04069a99ba8a1d7e18d67146de8e242f9a6d21",
    "license-policy/upstream/_npmcli_arborist_9.9.3/package.json":
        "df0a95f15021d3cb892047195ee24fe6cd78bc8ad5f302f5acc7f8d97848183b",
    "license-policy/upstream/picomatch_4.0.7-caseops.1/LICENSE":
        "d0cd141b0c322fded5dfad1d4645bb2fedfc05b7321fe1009469638190d59ef9",
    "license-policy/upstream/picomatch_4.0.7-caseops.1/CASEOPS-BACKPORT-NOTICE.txt":
        "f08d9841fdd1e143095de28a772896efb62122bf416e6172c49ab04f309c63e2",
    "license-policy/upstream/picomatch_4.0.7-caseops.1/package.json":
        "6ca3e6f8fd2af0bbd7e9a84e7d28bada2be3431cea22bbf7033de9365c185424",
}


def test_security_runs_and_retains_the_native_upload_gate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"))
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
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
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
    dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22.23.4-alpine AS trusted-base" in dockerfile
    runner = dockerfile.split("FROM trusted-base AS runner", 1)[1]
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
    record = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
    assert len(record["packages"]) == 19
    expected = {
        material["path"]: material["sha256"]
        for entry in record["packages"] for material in entry["materials"]
        if material["path"].startswith("license-policy/upstream/")
    }
    # The new MIT source notice uses the base policy, not a historical exception.
    assert QR_SOURCE not in expected
    expected[QR_SOURCE] = QR_SOURCE_SHA256
    # The base runtime is supplemental material, not an npm license exception.
    assert NODE_SOURCE not in expected
    expected[NODE_SOURCE] = NODE_SOURCE_SHA256
    assert NEXT_SOURCE not in expected
    expected[NEXT_SOURCE] = NEXT_SOURCE_SHA256
    assert not set(expected) & set(BUILD_TOOL_SOURCES)
    expected.update(BUILD_TOOL_SOURCES)
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
    assert len(actual) == 62
    document_hash = hashlib.sha256((ROOT / REVIEW).read_bytes()).hexdigest()
    assert document_hash == record["review_document"]["sha256"]


def test_qr_runtime_and_public_notice_match_retained_source():
    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    assert package["dependencies"]["qrcode.react"] == "4.2.0"
    notices = json.loads(
        (ROOT / "apps/web/app/third-party-notices/notices.json").read_text(encoding="utf-8")
    )
    component = next(item for item in notices["components"] if item["name"] == "qrcode.react")
    assert component["version"] == "4.2.0"
    notice = next(item for item in component["notices"] if item["license"] == "MIT")
    assert notice["retainedSource"] == QR_SOURCE
    assert notice["sha256"] == QR_SOURCE_SHA256
    assert notice["sourceUrl"] == (
        "https://raw.githubusercontent.com/zpao/qrcode.react/v4.2.0/"
        "src/third-party/qrcodegen/LICENSE"
    )
    public = ROOT / "apps/web/public/third-party-notices/qrcode.react-4.2.0-Nayuki-MIT-LICENSE.txt"
    source = ROOT / QR_SOURCE
    assert public.read_bytes() == source.read_bytes() == notice["text"].encode("utf-8")
    assert hashlib.sha256(source.read_bytes()).hexdigest() == QR_SOURCE_SHA256


def test_next_public_notice_matches_the_exact_patched_lock_and_retained_source():
    notices = json.loads(
        (ROOT / "apps/web/app/third-party-notices/notices.json").read_text(encoding="utf-8")
    )
    component = next(item for item in notices["components"] if item["packageName"] == "next")
    assert component["version"] == "16.4.6"
    assert len(component["notices"]) == 1
    notice = component["notices"][0]
    assert notice["license"] == "MIT"
    assert notice["sourceUrl"] == (
        "https://raw.githubusercontent.com/vercel/next.js/"
        "54b876b6b161b0ecda19562eb264bec637e60d6d/license.md"
    )
    assert notice["retainedSource"] == "license-policy/upstream/next_16.4.6/LICENSE.md"
    assert notice["filename"] == "next-16.4.6-LICENSE.txt"
    assert notice["sha256"] == "ee765244e2d59f5234d474f62e0766fa0c8b99af967fdd4c0cb8dcb0c76ea224"
    retained = (ROOT / notice["retainedSource"]).read_bytes()
    public = (ROOT / "apps/web/public/third-party-notices" / notice["filename"]).read_bytes()
    assert retained == public == notice["text"].encode("utf-8")
    assert len(retained) == 1079
    assert hashlib.sha256(retained).hexdigest() == notice["sha256"]
    manifest = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
    assert manifest["dependencies"]["next"] == "16.4.6"
    assert lock["packages"]["node_modules/next"]["version"] == "16.4.6"
    registry = json.loads(
        (ROOT / "license-policy/reviewed-packages.json").read_text(encoding="utf-8")
    )
    assert "next" not in {entry["name"] for entry in registry["packages"]}


def test_node_notice_contract_survives_a_real_non_utf8_default():
    code = """
import importlib.util
import json
import locale
import sys
facts = {"utf8_mode": sys.flags.utf8_mode, "encoding": locale.getpreferredencoding(False)}
print(json.dumps(facts), flush=True)
assert facts["utf8_mode"] == 0
assert facts["encoding"].lower().replace("-", "").replace("_", "") != "utf8"
spec = importlib.util.spec_from_file_location("license_notice_encoding_control", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.test_node_runtime_public_notice_matches_retained_immutable_source()
print(json.dumps({"node_notice_verified": True}), flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code, str(Path(__file__).resolve())],
        env={
            **os.environ, "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0",
            "LC_ALL": "C", "LANG": "C",
        },
        capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
    )
    lines = result.stdout.splitlines()
    assert lines, f"Encoding control did not report its actual runtime: {result.stderr}"
    facts = json.loads(lines[0])
    assert facts["utf8_mode"] == 0
    assert facts["encoding"].lower().replace("-", "").replace("_", "") != "utf8"
    assert result.returncode == 0, f"{facts}: {result.stderr}"
    assert json.loads(lines[-1]) == {"node_notice_verified": True}


def test_node_runtime_public_notice_matches_retained_immutable_source():
    dockerfile = (ROOT / "apps/web/Dockerfile").read_text(encoding="utf-8")
    assert "FROM node:22.23.4-alpine AS trusted-base" in dockerfile
    notices = json.loads(
        (ROOT / "apps/web/app/third-party-notices/notices.json").read_text(encoding="utf-8")
    )
    component = next(item for item in notices["components"] if item["packageName"] == "node")
    assert component["version"] == "22.23.4"
    assert len(component["notices"]) == 1
    notice = component["notices"][0]
    assert notice["retainedSource"] == NODE_SOURCE
    assert notice["sourceUrl"] == "https://raw.githubusercontent.com/nodejs/node/27f213124280b4db4cd1e3dd42f6f8afd01ceff7/LICENSE"
    assert notice["sha256"] == NODE_SOURCE_SHA256
    source = (ROOT / NODE_SOURCE).read_bytes()
    public = (ROOT / "apps/web/public/third-party-notices/node-22.23.4-LICENSE.txt").read_bytes()
    assert len(source) == 145485
    assert source == public == notice["text"].encode("utf-8")
    assert hashlib.sha256(source).hexdigest() == NODE_SOURCE_SHA256
