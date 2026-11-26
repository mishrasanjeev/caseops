"""Offline origin, reproducibility, exact scope and publication controls."""
from pathlib import Path
import importlib.util
import io
import json
import tempfile
import time
import types
import unittest
import unittest.mock
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
            if name not in ("package/lib/parse.js", "package/lib/utils.js", "package/package.json"):
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

    def current_npm(self, **changes):
        inputs = {
            "raw": self.npm_raw, "baseline_provenance": self.npm_provenance,
            "backport": builder.build(self.raw), "arborist_raw": self.arborist_raw,
            "glob_raw": (NPM / "upstream/glob-14.0.6-caseops.2.tgz").read_bytes(),
            "minimatch_raw": (NPM / "upstream/minimatch-11.0.8.tgz").read_bytes(),
            "nonrecursive_raw": (NPM / "upstream/nonrecursive-glob-match-1.1.0.tgz").read_bytes(),
            "brace_raw": (NPM / "upstream/brace-expansion-5.0.13.tgz").read_bytes(),
        }
        inputs.update(changes)
        return builder.build_npm(**inputs)

    def test_every_committed_npm_byte_reproduces_twice(self):
        first, second = self.current_npm(), self.current_npm()
        self.assertEqual(first, second)
        receipt = builder.verify_output(NPM, first, time.monotonic() + 5)
        self.assertTrue(receipt["rootPresent"])
        self.assertEqual(receipt["files"], len(first))

    def test_current_npm_keeps_every_unaffected_historical_payload_and_all_parent_edges(self):
        previous = builder.build_npm_historical_picopatch(
            self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw)
        current = self.current_npm()
        artifact = "npm-11.12.1-caseops-security.tgz"
        def members(raw):
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                return {item.name: (archive.extractfile(item).read(), item.mode) for item in archive}
        before, after = members(previous[artifact]), members(current[artifact])
        proof = json.loads(current["PROVENANCE.json"])
        layer = proof["dependencySecurityLayer20261122"]
        self.assertFalse(layer["npmOwnCodeChanged"])
        self.assertEqual(layer["previousArtifact"], json.loads(previous["PROVENANCE.json"])["artifact"])
        changed = set(layer["changedMembers"])
        removed = set(layer["removedMembers"])
        prefixes = ("package/node_modules/glob/", "package/node_modules/minimatch/",
                    "package/node_modules/@isaacs/nonrecursive-glob-match/",
                    "package/node_modules/brace-expansion/")
        parents = {"package/node_modules/@npmcli/arborist/package.json",
                   "package/node_modules/@npmcli/map-workspaces/package.json",
                   "package/node_modules/@npmcli/package-json/package.json",
                   "package/node_modules/@tufjs/models/package.json",
                   "package/node_modules/cacache/package.json",
                   "package/node_modules/ignore-walk/package.json",
                   "package/node_modules/libnpmdiff/package.json", "package/package.json"}
        self.assertEqual(changed, {name for name in after if after[name] != before.get(name)})
        self.assertEqual(removed, set(before) - set(after))
        self.assertTrue(all(name.startswith(prefixes) or name in parents for name in changed))
        self.assertTrue(all(name.startswith(prefixes) for name in removed))
        for name, value in before.items():
            if not name.startswith(prefixes) and name not in parents:
                self.assertEqual(after[name], value, name)
        for name in removed:
            self.assertNotIn(name, after)
        edits = proof["manifestEdits"][-10:]
        self.assertEqual({row["path"] for row in edits}, parents)
        for row in edits:
            # The explicit successor records ten runtime edges, independent of
            # the earlier backport's historical manifest edits.
            self.assertEqual(json.loads(after[row["path"]][0])["dependencies"][row["field"].split(".", 1)[1]], row["to"])
        for member in parents:
            expected = json.loads(before[member][0])
            for row in edits:
                if row["path"] == member:
                    key = row["field"].split(".", 1)[1]
                    self.assertEqual(expected["dependencies"][key], row["from"])
                    expected["dependencies"][key] = row["to"]
            self.assertEqual(json.loads(after[member][0]), expected)
        current_inputs = {row["name"]: row for row in proof["upstreamInputs"]}
        archives = {"glob": "glob-14.0.6-caseops.2.tgz", "minimatch": "minimatch-11.0.8.tgz",
                    "@isaacs/nonrecursive-glob-match": "nonrecursive-glob-match-1.1.0.tgz",
                    "brace-expansion": "brace-expansion-5.0.13.tgz"}
        for name, version in [("glob", "14.0.6-caseops.2"), ("minimatch", "11.0.8"),
                              ("@isaacs/nonrecursive-glob-match", "1.1.0"),
                              ("brace-expansion", "5.0.13")]:
            prefix = "package/node_modules/" + name + "/"
            self.assertEqual(json.loads(after[prefix + "package.json"][0])["version"], version)
            self.assertEqual(current_inputs[name]["version"], version)
            self.assertTrue(any(member.startswith(prefix) and "LICENSE" in member for member in after))
            # Independently compare complete payload bytes AND modes, not just
            # the patched version or a matching package.json.
            source_members = members((NPM / "upstream" / archives[name]).read_bytes())
            wanted = {prefix + member[8:]: value for member, value in source_members.items()}
            actual = {member: value for member, value in after.items() if member.startswith(prefix)}
            self.assertEqual(actual, wanted)
        self.assertEqual(layer["supersededCandidate"]["sha256"],
                         "e11da6ed76a0f7d7b56e9c7c9df991f4949319ff3364fd997eb4532cfe0da62c")
        self.assertIs(layer["supersededCandidate"]["currentAcceptance"], False)
        self.assertEqual(before["package/bin/npm-cli.js"], after["package/bin/npm-cli.js"])
        self.assertEqual(before["package/LICENSE"], after["package/LICENSE"])

    def test_current_npm_requires_all_four_exact_successor_inputs(self):
        for field in ["glob_raw", "minimatch_raw", "nonrecursive_raw", "brace_raw"]:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "EXACT_CURRENT_NPM_DEPENDENCY_INPUT_REQUIRED"):
                    self.current_npm(**{field: b"not the approved package"})

    def test_npm_own_code_and_every_unaffected_member_are_unchanged(self):
        built = builder.build_npm_historical_picopatch(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw)
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
        built = builder.build_npm_historical_picopatch(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw)
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
                    builder.build_npm_historical_picopatch(raw, review, builder.build(self.raw), self.arborist_raw)

    def test_corrupted_arborist_is_refused(self):
        with self.assertRaisesRegex(ValueError, "EXACT_OFFICIAL_ARBORIST_REQUIRED"):
            builder.build_npm_historical_picopatch(self.npm_raw, self.npm_provenance, builder.build(self.raw), self.arborist_raw + b"x")

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
            with unittest.mock.patch.object(builder, "time", types.SimpleNamespace(monotonic=stable_clock)):
                receipt = builder.verify_output(root, {"ordinary.txt": b"stable"}, 1)
            self.assertTrue(receipt["rootPresent"])
            total = len(ticks)
            calls = []
            def final_expiry():
                calls.append(0)
                return 1 if len(calls) == total else 0
            with unittest.mock.patch.object(builder, "time", types.SimpleNamespace(monotonic=final_expiry)):
                with self.assertRaisesRegex(ValueError, "OUTPUT_VERIFICATION_DEADLINE"):
                    builder.verify_output(root, {"ordinary.txt": b"stable"}, 1)
            self.assertEqual(len(calls), total)


if __name__ == "__main__":
    unittest.main()
