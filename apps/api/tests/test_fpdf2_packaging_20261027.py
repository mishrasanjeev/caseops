"""Offline, stdlib-only API source/license packaging controls (no fpdf import)."""

from __future__ import annotations

import fnmatch
import importlib.util
import io
import json
import os
import shutil
import socket
import tarfile
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
VENDOR = ROOT / "apps/api/vendor/fpdf2-2.8.8"
SPEC = importlib.util.spec_from_file_location("caseops_fpdf2_package_verify", VENDOR / "verify.py")
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


def ignored(relative, patterns):
    """Apply the actual API ignore rules to the few declared vendor paths."""
    excluded = False
    parts = PurePosixPath(relative).parts
    for raw in patterns.splitlines():
        pattern = raw.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negative = pattern.startswith("!")
        pattern = pattern.removeprefix("!").removeprefix("/")
        if pattern.endswith("/"):
            target = pattern[:-1]
            matched = any(fnmatch.fnmatchcase("/".join(parts[:n]), target)
                          for n in range(1, len(parts)))
        elif "/" in pattern:
            matched = fnmatch.fnmatchcase(relative, pattern)
        else:
            matched = any(fnmatch.fnmatchcase(part, pattern) for part in parts)
        if matched:
            excluded = not negative
    return excluded


class Distribution:
    def __init__(self, directory, *, version="2.8.8"):
        self.directory, self.version = directory, version
        self.files = [PurePosixPath("fpdf2-2.8.8.dist-info/METADATA"),
                      PurePosixPath("fpdf2-2.8.8.dist-info/licenses/LICENSE")]

    def locate_file(self, entry):
        return self.directory / str(entry)


class Fpdf2Packaging(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="caseops-fpdf2-package-")
        self.root = Path(self.temporary.name).resolve()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = self.root / "bundle"
        shutil.copytree(VENDOR, self.bundle)
        self.network = mock.patch.object(
            socket.socket, "connect", side_effect=AssertionError("Offline packaging control")
        )
        self.network.start()
        self.addCleanup(self.network.stop)

    def distribution(self):
        installed = self.root / "site-packages"
        distinfo = installed / "fpdf2-2.8.8.dist-info"
        (distinfo / "licenses").mkdir(parents=True)
        archive = (self.bundle / "fpdf2-2.8.8.tar.gz").read_bytes()
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            member = source.extractfile("fpdf2-2.8.8/PKG-INFO")
            assert member is not None
            with member:
                (distinfo / "METADATA").write_bytes(member.read())
        shutil.copyfile(self.bundle / "LICENSE", distinfo / "licenses/LICENSE")
        return Distribution(installed)

    def test_real_pinned_archive_and_all_notice_bytes_are_admitted(self):
        result = verify.validate_bundle(self.bundle)
        self.assertEqual(result, {
            "name": "fpdf2", "version": "2.8.8", "licenseExpression": "LGPL-3.0-only",
            "unmodifiedSourceSha256":
                "9e94e155e85e8053329a9a1fce8b566fd7a7c5bb79e98a1a3952d379b947c5b9",
            "bundleVerified": True,
        })

    def test_installed_exact_wheel_metadata_and_license_without_runtime_import(self):
        result = verify.verify_installed(self.bundle, self.distribution())
        self.assertTrue(result["installedMetadataAndLicenseVerified"])
        self.assertFalse(result["fpdfRuntimeImported"])

    def test_wrong_installed_version_refuses_before_member_read(self):
        distribution = Distribution(self.root, version="2.8.7")
        with mock.patch.object(distribution, "locate_file") as reader:
            with self.assertRaisesRegex(ValueError, "INSTALLED_VERSION_MISMATCH"):
                verify.verify_installed(self.bundle, distribution)
            reader.assert_not_called()

    def test_corrupted_installed_metadata_or_license_is_refused(self):
        distribution = self.distribution()
        for relative in ("METADATA", "licenses/LICENSE"):
            file = distribution.directory / "fpdf2-2.8.8.dist-info" / relative
            original = file.read_bytes()
            file.write_bytes(original[:-1] + b"!")
            with self.subTest(member=relative), self.assertRaisesRegex(
                ValueError, "PUBLIC_DIGEST_MISMATCH"
            ):
                verify.verify_installed(self.bundle, distribution)
            file.write_bytes(original)

    def test_each_missing_or_corrupt_source_license_notice_is_refused(self):
        for name in verify.FILES:
            file = self.bundle / name
            original = file.read_bytes()
            file.write_bytes(original[:-1] + b"!")
            with self.subTest(member=name), self.assertRaisesRegex(
                ValueError, "PUBLIC_DIGEST_MISMATCH"
            ):
                verify.validate_bundle(self.bundle)
            file.unlink()
            with self.subTest(missing=name), self.assertRaises(FileNotFoundError):
                verify.validate_bundle(self.bundle)
            file.write_bytes(original)

    def test_manifest_cannot_relabel_license_or_substitute_artifact_digests(self):
        file = self.bundle / "provenance.json"
        original = file.read_bytes()
        variants = [
            ("EXACT_UPSTREAM_IDENTITY_REQUIRED", lambda q: q.update(licenseExpression="MIT")),
            ("UPSTREAM_ARTIFACT_MISMATCH", lambda q: q["artifacts"][0].update(sha256="0" * 64)),
            ("PINNED_LICENSE_SOURCE_METADATA_REQUIRED",
             lambda q: q["bundledFiles"]["LICENSE"].update(sha256="0" * 64)),
        ]
        for code, change in variants:
            q = json.loads(original)
            change(q)
            file.write_text(json.dumps(q))
            with self.subTest(code=code), self.assertRaisesRegex(ValueError, code):
                verify.validate_bundle(self.bundle)
        file.write_bytes(original)

    def test_boolean_artifact_extent_is_not_an_integer_size(self):
        file = self.bundle / "provenance.json"
        q = json.loads(file.read_bytes())
        q["artifacts"][0]["sizeBytes"] = True
        file.write_text(json.dumps(q))
        with self.assertRaisesRegex(ValueError, "UPSTREAM_ARTIFACT_MISMATCH"):
            verify.validate_bundle(self.bundle)

    def test_actual_growing_fd_read_is_bounded_and_closed(self):
        file = self.root / "growing.txt"
        file.write_bytes(b"original")
        original_read, original_open = os.read, os.open
        descriptors, charged = [], []

        def opened(*args):
            descriptor = original_open(*args)
            descriptors.append(descriptor)
            return descriptor

        def read(descriptor, count):
            if not charged:
                with file.open("ab") as stream:
                    stream.write(b"x" * 65536)
            data = original_read(descriptor, count)
            charged.append(len(data))
            return data

        with mock.patch.object(verify.os, "open", side_effect=opened), \
                mock.patch.object(verify.os, "read", side_effect=read):
            with self.assertRaisesRegex(ValueError, "PUBLIC_FILE_SIZE_CHANGED"):
                verify.read_bound(file, limit=8)
        self.assertEqual(sum(charged), 9)
        self.assertEqual(len(descriptors), 1)
        with self.assertRaises(OSError):
            os.fstat(descriptors[0])

    def test_final_namespace_change_refuses_with_unchanged_bytes(self):
        file = self.root / "fixed.txt"
        file.write_bytes(b"original")
        original_read = os.read

        def read(descriptor, count):
            data = original_read(descriptor, count)
            if data:
                (self.root / "new-sibling").write_bytes(b"public")
            return data

        with mock.patch.object(verify.os, "read", side_effect=read):
            with self.assertRaisesRegex(ValueError, "PUBLIC_NAMESPACE_CHANGED"):
                verify.read_bound(file, limit=8)

    def test_api_copy_context_and_dirty_fence_cover_the_complete_bundle(self):
        docker = (ROOT / "apps/api/Dockerfile").read_text()
        copy = "COPY vendor/fpdf2-2.8.8 /usr/share/doc/caseops-api/third-party/fpdf2-2.8.8"
        run = "python /usr/share/doc/caseops-api/third-party/fpdf2-2.8.8/verify.py --installed"
        self.assertEqual(docker.splitlines().count(copy), 1)
        self.assertEqual(docker.count(run), 1)
        self.assertLess(docker.index(copy), docker.index("RUN uv export"))
        self.assertLess(docker.index("uv pip install --system"), docker.index(run))
        for name in (".dockerignore", ".gcloudignore"):
            patterns = (ROOT / "apps/api" / name).read_text()
            for file in VENDOR.iterdir():
                if not file.is_file():
                    continue
                relative = "vendor/fpdf2-2.8.8/" + file.name
                self.assertFalse(ignored(relative, patterns), (name, relative))
                self.assertTrue(ignored(relative, patterns + "\nvendor/\n"))
        deployment = (ROOT / "scripts/deploy-prod.sh").read_text()
        self.assertIn("API_SOURCE_DIR=apps/api", deployment)
        self.assertIn('"${API_SOURCE_DIR}" "apps/web" package.json package-lock.json', deployment)
        self.assertIn("git status --porcelain --untracked-files=all --", deployment)
        attributes = (ROOT / ".gitattributes").read_text().splitlines()
        for name in ("LICENSE", "COPYING.GPLv3", "NOTICE.txt", "provenance.json", "verify.py"):
            self.assertIn("apps/api/vendor/fpdf2-2.8.8/" + name + " text eol=lf", attributes)
            self.assertNotIn(b"\r\n", (VENDOR / name).read_bytes())
        self.assertIn("apps/api/vendor/fpdf2-2.8.8/fpdf2-2.8.8.tar.gz -text", attributes)


if __name__ == "__main__":
    unittest.main()
