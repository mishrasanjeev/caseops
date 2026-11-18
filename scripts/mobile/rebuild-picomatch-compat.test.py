"""Offline origin, reproducibility, exact scope and publication controls."""
from pathlib import Path
import importlib.util
import io
import json
import tempfile
import time
import types
import unittest
from unittest import mock
import tarfile

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "apps/mobile/vendor/picomatch-4.0.7-caseops.1"
NPM = ROOT / "apps/mobile/vendor/npm-11.12.1-caseops-security"
spec = importlib.util.spec_from_file_location("picomatch_backport", Path(__file__).with_name("rebuild-picomatch-compat.py"))
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class Backport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (VENDOR / "upstream/picomatch-4.0.7.tgz").read_bytes()
        cls.npm_raw = (NPM / "upstream/npm-11.12.1-caseops-security-20261028.tgz").read_bytes()
        cls.npm_provenance = (NPM / "upstream/PROVENANCE-20261028.json").read_bytes()
        cls.arborist_raw = (NPM / "upstream/arborist-9.9.3.tgz").read_bytes()

    def test_source_pin_is_read_through_a_real_descriptor(self):
        captured = builder.read_input(VENDOR / "upstream/picomatch-4.0.7.tgz")
        self.assertEqual(captured, self.raw)

    def test_every_committed_backport_byte_reproduces_twice(self):
        first, second = builder.build(self.raw), builder.build(self.raw)
        self.assertEqual(first, second)
        actual = {p.relative_to(VENDOR).as_posix(): p.read_bytes() for p in VENDOR.rglob("*") if p.is_file()}
        self.assertEqual(actual, first)

    def test_runtime_scope_and_original_mit_notice_are_exact(self):
        built = builder.build(self.raw)
        with tarfile.open(fileobj=io.BytesIO(self.raw), mode="r:gz") as archive:
            original = {member.name: archive.extractfile(member).read() for member in archive}
        for name, body in original.items():
            if name not in ("package/lib/parse.js", "package/package.json"):
                self.assertEqual(built[name], body, name)
        metadata = json.loads(built["package/package.json"])
        self.assertEqual(metadata["name"], "picomatch")
        self.assertEqual(metadata["version"], "4.0.7-caseops.1")
        self.assertIs(metadata["private"], True)
        self.assertIs(metadata["caseopsBackport"]["notUpstreamRelease"], True)
        self.assertEqual(built["LICENSE"], original["package/LICENSE"])

    def test_corrupted_source_is_refused_before_build(self):
        corrupted = bytearray(self.raw)
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "UPSTREAM_HASH_REQUIRED"):
            builder.build(bytes(corrupted))

    def test_every_committed_npm_byte_reproduces_twice(self):
        backport = builder.build(self.raw)
        first = builder.build_npm(self.npm_raw, self.npm_provenance, backport, self.arborist_raw)
        second = builder.build_npm(self.npm_raw, self.npm_provenance, backport, self.arborist_raw)
        self.assertEqual(first, second)
        for name, body in first.items():
            self.assertEqual((NPM / name).read_bytes(), body, name)

    def test_npm_own_code_and_every_unaffected_member_are_unchanged(self):
        built = builder.build_npm(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw)
        with tarfile.open(fileobj=io.BytesIO(self.npm_raw), mode="r:gz") as archive:
            original = {m.name: (archive.extractfile(m).read(), m.mode) for m in archive}
        with tarfile.open(fileobj=io.BytesIO(built["npm-11.12.1-caseops-security.tgz"]), mode="r:gz") as archive:
            actual = {m.name: (archive.extractfile(m).read(), m.mode) for m in archive}
        prefix = "package/node_modules/tinyglobby/node_modules/picomatch/"
        arborist_prefix = "package/node_modules/@npmcli/arborist/"
        for name, value in original.items():
            if not name.startswith((prefix, arborist_prefix)) and name not in (
                    "package/node_modules/tinyglobby/package.json", "package/package.json",
                    "package/node_modules/tinyglobby/node_modules/fdir/package.json"):
                self.assertEqual(actual[name], value, name)
        self.assertEqual(len(original), 2149)
        self.assertEqual(len(actual), 2154)
        before = json.loads(original["package/node_modules/tinyglobby/package.json"][0])
        after = json.loads(actual["package/node_modules/tinyglobby/package.json"][0])
        self.assertEqual(after["dependencies"]["picomatch"], "4.0.7-caseops.1")
        after["dependencies"]["picomatch"] = before["dependencies"]["picomatch"]
        self.assertEqual(before, after)
        peer_path = "package/node_modules/tinyglobby/node_modules/fdir/package.json"
        before_peer = json.loads(original[peer_path][0])
        after_peer = json.loads(actual[peer_path][0])
        self.assertEqual(after_peer["peerDependencies"]["picomatch"], "^3 || ^4 || 4.0.7-caseops.1")
        after_peer["peerDependencies"]["picomatch"] = before_peer["peerDependencies"]["picomatch"]
        self.assertEqual(before_peer, after_peer)
        before_root = json.loads(original["package/package.json"][0])
        after_root = json.loads(actual["package/package.json"][0])
        self.assertEqual(after_root["dependencies"]["@npmcli/arborist"], "9.9.3")
        after_root["dependencies"]["@npmcli/arborist"] = before_root["dependencies"]["@npmcli/arborist"]
        self.assertEqual(before_root, after_root)

    def test_official_arborist_runtime_and_notice_bytes_are_unmodified(self):
        built = builder.build_npm(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw)
        with tarfile.open(fileobj=io.BytesIO(self.arborist_raw), mode="r:gz") as archive:
            official = {m.name: (archive.extractfile(m).read(), m.mode) for m in archive}
        with tarfile.open(fileobj=io.BytesIO(built["npm-11.12.1-caseops-security.tgz"]), mode="r:gz") as archive:
            actual = {m.name: (archive.extractfile(m).read(), m.mode) for m in archive}
        prefix = "package/node_modules/@npmcli/arborist/"
        for name, value in official.items():
            target = prefix + name[8:]
            if name != "package/package.json":
                self.assertEqual(actual[target], value, name)
        before, after = json.loads(official["package/package.json"][0]), json.loads(actual[prefix + "package.json"][0])
        self.assertEqual(after["version"], "9.9.3")
        self.assertEqual(after["dependencies"]["minimatch"], "11.0.1")
        after["dependencies"]["minimatch"] = before["dependencies"]["minimatch"]
        self.assertEqual(before, after)

    def test_npm_baseline_archive_and_review_are_both_required(self):
        for raw, review in ((self.npm_raw + b"x", self.npm_provenance), (self.npm_raw, self.npm_provenance + b"x")):
            with self.subTest(archive_changed=raw != self.npm_raw):
                with self.assertRaisesRegex(ValueError, "EXACT_NPM_BASELINE_REQUIRED"):
                    builder.build_npm(raw, review, builder.build(self.raw), self.arborist_raw)

    def test_corrupted_arborist_is_refused(self):
        with self.assertRaisesRegex(ValueError, "EXACT_OFFICIAL_ARBORIST_REQUIRED"):
            builder.build_npm(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw + b"x")

    def test_output_requires_every_file_and_refuses_extra_files_and_empty_directories(self):
        with tempfile.TemporaryDirectory(prefix="picomatch-output-") as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            expected = {"ordinary.txt": b"retained output"}
            (root / "ordinary.txt").write_bytes(expected["ordinary.txt"])
            receipt = builder.verify_output(root, expected, time.monotonic() + 5)
            self.assertEqual(receipt, {"observations": 2, "files": 1, "rootPresent": True})
            (root / "unexpected.txt").write_bytes(expected["ordinary.txt"])
            with self.assertRaisesRegex(ValueError, "EXACT_OUTPUT_FILE_REQUIRED"):
                builder.verify_output(root, expected, time.monotonic() + 5)
            (root / "unexpected.txt").unlink()
            (root / "unexpected-directory").mkdir()
            with self.assertRaisesRegex(ValueError, "EXACT_OUTPUT_DIRECTORY_REQUIRED"):
                builder.verify_output(root, expected, time.monotonic() + 5)

    def test_output_rejects_missing_or_changed_bytes(self):
        with tempfile.TemporaryDirectory(prefix="picomatch-output-") as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            expected = {"ordinary.txt": b"retained output"}
            with self.assertRaisesRegex(ValueError, "COMPLETE_GENERATED_OUTPUT_REQUIRED"):
                builder.verify_output(root, expected, time.monotonic() + 5)
            (root / "ordinary.txt").write_bytes(b"changed bytes")
            with self.assertRaisesRegex(ValueError, "OUTPUT_BYTES_CHANGED"):
                builder.verify_output(root, expected, time.monotonic() + 5)

    def test_late_final_reconciliation_cannot_publish_success(self):
        with tempfile.TemporaryDirectory(prefix="picomatch-output-") as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(Path(tempfile.gettempdir()).resolve()))
            (root / "ordinary.txt").write_bytes(b"stable")
            ticks = []
            def stable_clock():
                ticks.append(0)
                return 0
            with mock.patch.object(builder, "time", types.SimpleNamespace(monotonic=stable_clock)):
                receipt = builder.verify_output(root, {"ordinary.txt": b"stable"}, 1)
            self.assertTrue(receipt["rootPresent"])
            total = len(ticks)
            calls = []
            def final_expiry():
                calls.append(0)
                return 1 if len(calls) == total else 0
            with mock.patch.object(builder, "time", types.SimpleNamespace(monotonic=final_expiry)):
                with self.assertRaisesRegex(ValueError, "OUTPUT_VERIFICATION_DEADLINE"):
                    builder.verify_output(root, {"ordinary.txt": b"stable"}, 1)
            self.assertEqual(len(calls), total)


if __name__ == "__main__":
    unittest.main()
