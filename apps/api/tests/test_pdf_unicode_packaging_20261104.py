"""Offline source, attribution and finite builder-closure contracts for PDF fonts."""

from __future__ import annotations

import hashlib
import json
import shlex
import tarfile
import tomllib
from io import BytesIO
from pathlib import Path

import pytest

from tests.test_fpdf2_packaging_20261027 import ignored

ROOT = Path(__file__).resolve().parents[3]
ASSETS = ROOT / "apps/api/src/caseops_api/assets/pdf_fonts"
VENDOR = ROOT / "apps/api/vendor/pdf-fonts-20261104"
SHAPER = ROOT / "apps/api/vendor/uharfbuzz-0.57.0"
NOTICES = (
    (
        "liberation-fonts",
        "OFL-1.1",
        "93fed46019c38bbe566b479d22148e2e8a1e85ada614accb0211c37b2c61c19b",
    ),
    (
        "NotoSansDevanagari",
        "OFL-1.1",
        "0dab92d0544f7b233403f14b84a663bdbfa746982eda629e7f4f9ffe1b036feb",
    ),
    ("uharfbuzz", "Apache-2.0", "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
    ("uharfbuzz", "Old MIT", "ba8f810f2455c2f08e2d56bb49b72f37fcf68f1f4fade38977cfd7372050ad64"),
)


def test_exact_runtime_assets_and_notices_retain_every_original_byte():
    raw = (ASSETS / "manifest.json").read_bytes()
    assert len(raw) == 3773
    assert (
        hashlib.sha256(raw).hexdigest()
        == "a42bb856e26770f31de0d47c46dc038a4e946bea61fcf1079a9c2a22dafc7670"
    )
    manifest = json.loads(raw)
    pins = manifest["assets"] | manifest["notices"]
    names = {path.name for path in ASSETS.iterdir()}
    assert names == set(pins) | {"manifest.json", "NOTICE.txt"}
    assert len(manifest["assets"]) == 14
    for name, pin in pins.items():
        value = (ASSETS / name).read_bytes()
        assert len(value) == pin["bytes"]
        assert hashlib.sha256(value).hexdigest() == pin["sha256"]
    notice = (ASSETS / "NOTICE.txt").read_bytes()
    assert len(notice) == 732
    assert (
        hashlib.sha256(notice).hexdigest()
        == "79db66799e7f4c054e3e3b9ceae0c414b450f5ea37313401c625516d820d1b01"
    )


def test_liberation_binary_and_source_archives_match_fonts_and_original_ofl():
    provenance = json.loads((VENDOR / "SOURCE-AND-LICENSE.json").read_bytes())
    assert provenance["liberation_commit"] == "4b0192046158094654e865245832c66d2104219e"
    assert provenance["noto_commit"] == "ffebf8c1ee449e544955a7e813c54f9b73848eac"
    archives = {
        row["path"]: row
        for row in provenance["official_sources"]
        if row["path"].endswith(".tar.gz")
    }
    assert len(archives) == 2
    original_ofl = (ASSETS / "OFL-Liberation.txt").read_bytes()
    assert b"Reserved Font Name" in original_ofl
    runtime_names = {path.name for path in ASSETS.glob("Liberation*.ttf")}
    binary_names, source_names = set(), set()
    for name, pin in archives.items():
        raw = (VENDOR / name).read_bytes()
        assert len(raw) == pin["bytes"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
        with tarfile.open(fileobj=BytesIO(raw), mode="r:gz") as archive:
            members = archive.getmembers()
            assert len(members) <= 128
            licenses = [row for row in members if Path(row.name).name == "LICENSE"]
            assert len(licenses) == 1
            stream = archive.extractfile(licenses[0])
            assert stream is not None
            with stream:
                license_raw = stream.read()
            assert license_raw == original_ofl
            for member in members:
                leaf = Path(member.name).name
                if leaf.endswith(".ttf"):
                    binary_names.add(leaf)
                    stream = archive.extractfile(member)
                    assert stream is not None
                    with stream:
                        archived = stream.read()
                    shipped = (ASSETS / leaf).read_bytes()
                    assert archived == shipped
                if leaf.endswith(".sfd"):
                    source_names.add(leaf.removesuffix(".sfd") + ".ttf")
    assert binary_names == source_names == runtime_names
    assert len(binary_names) == 12


def test_exact_shaper_lock_and_both_native_and_python_license_obligations():
    project = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "apps/api/uv.lock").read_text())
    assert "uharfbuzz==0.57.0" in project["project"]["dependencies"]
    packages = [row for row in lock["package"] if row["name"] == "uharfbuzz"]
    assert len(packages) == 1
    package = packages[0]
    assert package["version"] == "0.57.0"
    provenance = json.loads((SHAPER / "provenance.json").read_bytes())
    assert provenance["upstream_commit"] == "59c2acb676ffdd0ffeae6ad9e718bce87523abe0"
    assert provenance["bundled_harfbuzz"]["version"] == "15.0.0"
    assert provenance["bundled_harfbuzz"]["commit"] == "35f656a1a2bab548ea7f54a6dd3fba2b09680d14"
    assert package["sdist"]["hash"] == "sha256:" + provenance["source_sdist_sha256"]
    locked = {row["url"].rsplit("/", 1)[1]: row["hash"] for row in package["wheels"]}
    assert len(locked) == 19
    for name, digest in provenance["official_wheels"].items():
        assert locked[name] == "sha256:" + digest
    assert {path.name for path in SHAPER.iterdir()} == {
        "LICENSE",
        "harfbuzz-COPYING",
        "provenance.json",
        "NOTICE.txt",
    }
    for pin in provenance["notices"]:
        raw = (SHAPER / pin["path"]).read_bytes()
        assert len(raw) == pin["bytes"]
        assert hashlib.sha256(raw).hexdigest() == pin["sha256"]
    apache = (SHAPER / "LICENSE").read_bytes()
    native = (SHAPER / "harfbuzz-COPYING").read_bytes()
    assert b"Apache License" in apache
    assert b"Permission is hereby granted" in native


@pytest.mark.parametrize("package,license_name,digest", NOTICES)
def test_public_notice_download_equals_catalog_and_retained_upstream(package, license_name, digest):
    catalog = json.loads((ROOT / "apps/web/app/third-party-notices/notices.json").read_bytes())
    component = next(row for row in catalog["components"] if row["packageName"] == package)
    notice = next(row for row in component["notices"] if row["license"] == license_name)
    retained = (ROOT / notice["retainedSource"]).read_bytes()
    public = (ROOT / "apps/web/public/third-party-notices" / notice["filename"]).read_bytes()
    assert retained == public == notice["text"].encode("utf-8")
    assert hashlib.sha256(retained).hexdigest() == notice["sha256"] == digest


def test_api_image_and_wheel_source_keep_font_and_notice_closure():
    docker = (ROOT / "apps/api/Dockerfile").read_text()
    assert "COPY src ./src" in docker
    assert (
        "from caseops_api.services.pdf_fonts import verify_package; "
        "print(json.dumps(verify_package()))"
        in docker
    )
    assert docker.index("uv pip install --system --no-deps .") < docker.index(
        "from caseops_api.services.pdf_fonts import verify_package"
    )
    assert (
        "COPY vendor/pdf-fonts-20261104 /usr/share/doc/caseops-api/third-party/pdf-fonts-20261104"
        in docker
    )
    assert (
        "COPY vendor/uharfbuzz-0.57.0 /usr/share/doc/caseops-api/third-party/uharfbuzz-0.57.0"
        in docker
    )
    project = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text())
    assert project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["src/caseops_api"]
    expected = [*ASSETS.iterdir(), *VENDOR.iterdir(), *SHAPER.iterdir()]
    assert len(expected) == 25
    for name in (".dockerignore", ".gcloudignore"):
        rules = (ROOT / "apps/api" / name).read_text()
        for path in expected:
            assert not ignored(path.relative_to(ROOT / "apps/api").as_posix(), rules)


def test_web_builder_copy_is_finite_and_excludes_api_runtime_inputs():
    expected = {
        "apps/api/pyproject.toml",
        "apps/api/uv.lock",
        "apps/api/src/caseops_api/assets/pdf_fonts/OFL-Liberation.txt",
        "apps/api/src/caseops_api/assets/pdf_fonts/OFL-Noto.txt",
        "apps/api/vendor/pdf-fonts-20261104/SOURCE-AND-LICENSE.json",
        "apps/api/vendor/uharfbuzz-0.57.0/LICENSE",
        "apps/api/vendor/uharfbuzz-0.57.0/harfbuzz-COPYING",
    }
    docker = (ROOT / "apps/web/Dockerfile").read_text()
    builder, runner = docker.split("# ---- runner", 1)
    copied = set()
    for line in builder.splitlines():
        if line.startswith("COPY "):
            words = shlex.split(line)
            copied.update(word for word in words[1:-1] if word.startswith("apps/api/"))
    assert copied == expected
    assert "apps/api" not in runner
    attrs = (ROOT / ".gitattributes").read_text()
    assert "apps/api/src/caseops_api/assets/pdf_fonts/** -text" in attrs
    assert "apps/api/vendor/pdf-fonts-20261104/** -text" in attrs
    assert "apps/api/vendor/uharfbuzz-0.57.0/LICENSE -text" in attrs
    assert "apps/api/vendor/uharfbuzz-0.57.0/harfbuzz-COPYING -text" in attrs
