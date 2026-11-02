"""Offline native Git fixtures and real digest-pinned Gitleaks canaries."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "security_secret_scan", ROOT / "scripts/security_secret_scan.py"
)
assert SPEC is not None and SPEC.loader is not None
scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scan)
REAL_RUN = subprocess.run


class GitFixture(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix="caseops-secret-test-")
        self.addCleanup(self.storage.cleanup)
        self.root = Path(self.storage.name)
        evidence_root = os.environ.get("CASEOPS_SECRET_SCAN_TEST_EVIDENCE")
        if evidence_root:

            def retain():
                target = (
                    Path(evidence_root)
                    / hashlib.sha256(self.id().encode()).hexdigest()[:20]
                )
                target.mkdir(parents=True, exist_ok=False)
                (target / "identity.json").write_text(
                    json.dumps({"identity": self.id()})
                )
                for source in self.root.glob("*/progress.jsonl"):
                    shutil.copytree(source.parent, target / source.parent.name)

            self.addCleanup(retain)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Offline fixture")
        self.git("config", "user.email", "offline@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")
        self.git("remote", "add", "origin", "https://example.invalid/offline.git")
        self.write(".gitleaks.toml", "[extend]\nuseDefault = true\n")
        self.write(".gitleaksignore", "# No canary exclusions.\n")
        self.write("record.txt", "original\n")
        self.base = self.commit("base")

    def git(self, *args, check=True):
        env = dict(
            os.environ,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_DATE="2026-10-10T00:00:00+00:00",
            GIT_COMMITTER_DATE="2026-10-10T00:00:00+00:00",
        )
        result = REAL_RUN(
            ["git", "-C", str(self.repo), *args],
            capture_output=True,
            timeout=30,
            env=env,
            check=False,
        )
        if check and result.returncode:
            self.fail(
                f"Native fixture Git failed: {args[0]} (exit {result.returncode})"
            )
        return result.stdout.decode().strip()

    def write(self, path, content):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode("utf-8"))

    def commit(self, message):
        self.git("add", "--all")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def push(self, head, before=None):
        return {"before": before or self.base, "after": head, "deleted": False}

    def run_scan(self, head, event=None, event_name="push", **kwargs):
        return scan.run_scan(
            repo=self.repo,
            head=head,
            event_name=event_name,
            event=event or self.push(head),
            output=self.root / "evidence",
            **kwargs,
        )

    def progress(self):
        return [
            json.loads(line)
            for line in (self.root / "evidence/progress.jsonl").read_text().splitlines()
        ]

    def assert_incomplete(self):
        self.assertFalse((self.root / "evidence/completion.json").exists())
        self.assertEqual(self.progress()[-1]["event"], "scan_failed")

    def side_merge(self, content):
        self.git("switch", "-c", "side")
        self.write("side.txt", content)
        first = self.commit("side introduces record")
        self.write("side.txt", "clean retained record\n")
        second = self.commit("side removes credential")
        self.git("switch", "main")
        self.git("merge", "--no-ff", "side", "-m", "merge side")
        return first, second, self.git("rev-parse", "HEAD")

    def resolution_merge(self, content):
        self.git("switch", "-c", "side")
        self.write("record.txt", "side choice\n")
        side = self.commit("side choice")
        self.git("switch", "main")
        self.write("record.txt", "main choice\n")
        before = self.commit("main choice")
        self.git("merge", "--no-ff", "side", check=False)
        self.write("record.txt", content)
        merged = self.commit("resolve merge")
        return before, side, merged


class ReviewedPublicVectorTests(GitFixture):
    """Public-vector review remains bound to one exact immutable origin span."""

    def test_repository_public_certifi_digest_review_binds_current_immutable_origin(self):
        path = "scripts/mobile/host-platform-trust.py"
        origins = {
            "751b47fa9369d276c8dd280030fbc88b2837cf9d": 80,
            "df4b299a660e9ab00655054f7f4caf1b28a1f340": 81,
        }
        policy = (ROOT / ".gitleaksignore").read_text().splitlines()
        for origin, line in origins.items():
            self.assertEqual(policy.count(f"{origin}:{path}:generic-api-key:{line}"), 1)
        historical = "2fe2d37cc8623fe91d9e463244a2880469939612"
        self.assertEqual(policy.count(f"{historical}:{path}:generic-api-key:35"), 1)
        self.assertNotIn(f"{path}:generic-api-key:81", policy)
        self.assertNotIn(f"{path}:generic-api-key:35", policy)
        source = scan.git(ROOT, "show", "HEAD:" + path)
        expected = "0c3ed116e3a6d25ea71ba6336dabfa79c49fcdea1bc629a17ec6ce0b09637fe4"
        candidates = [
            (number, span)
            for number, span in enumerate(source.splitlines(keepends=True), 1)
            if hashlib.sha256(span).hexdigest() == expected
        ]
        self.assertEqual(len(candidates), 1)
        current_line, span = candidates[0]
        blame = scan.git(
            ROOT, "blame", "--line-porcelain", "-L", f"{current_line},{current_line}",
            "HEAD", "--", path,
        ).splitlines()
        origin, original, current = blame[0].decode().split()[:3]
        self.assertIn(origin, origins)
        self.assertEqual((int(original), int(current)), (origins[origin], current_line))
        retained = scan.git(ROOT, "show", f"{origin}:{path}").splitlines(
            keepends=True
        )[origins[origin] - 1]
        self.assertEqual(hashlib.sha256(retained).hexdigest(), hashlib.sha256(span).hexdigest())
        ancestor = REAL_RUN(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", origin, "HEAD"],
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_repository_public_apk_report_review_requires_all_six_exact_origins(self):
        origin = "e8c3049b7150219073718689d7106d4a82df7c5a"
        digests = (
            "d00f58706ee970aa5bc7268ba1a0146ab7707de76a09ca69bb19a9b359d1af71",
            "f45e8bba92099f478ca005fa2afa5a578ec2b424d4371d209c61dc8a88e5521d",
            "6b5ba4627d6a58f9fba527746694ec0d2f18da22627c440262228dbbd9de5e28",
        )
        policy = (ROOT / ".gitleaksignore").read_text().splitlines()
        for path, start in (
            ("scripts/mobile/android-native-proof.test.mjs", 36),
            ("scripts/mobile/build-android-local-acceptance.test.mjs", 30),
        ):
            source = scan.git(ROOT, "show", f"{origin}:{path}")
            for offset, digest in enumerate(digests):
                line = start + offset
                entry = f"{origin}:{path}:generic-api-key:{line}"
                self.assertEqual(policy.count(entry), 1)
                self.assertNotIn(f"{path}:generic-api-key:{line}", policy)
                span = source.splitlines(keepends=True)[line - 1]
                self.assertTrue(span.startswith(b"V2 Signer: public key "))
                self.assertEqual(hashlib.sha256(span).hexdigest(), digest)
        ancestor = REAL_RUN(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", origin, "HEAD"],
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_repository_review_matches_only_the_public_rfc6238_origin(self):
        origin = "438c79f776373ff31eba881e933ab07b9900231f"
        path = "scripts/mobile/tooling.test.mjs"
        entry = f"{origin}:{path}:generic-api-key:528"
        policy = (ROOT / ".gitleaksignore").read_text().splitlines()
        self.assertEqual(policy.count(entry), 1)
        self.assertNotIn(f"{path}:generic-api-key:528", policy)
        source = scan.git(ROOT, "show", f"{origin}:{path}")
        span = source.splitlines(keepends=True)[527]
        public_vector = base64.b32encode(b"12345678901234567890").decode()
        expected = f"  const secret = '{public_vector}';\n".encode()
        # Only digests can enter failure diagnostics, never a changed key value.
        self.assertEqual(hashlib.sha256(span).hexdigest(), hashlib.sha256(expected).hexdigest())
        self.assertEqual(
            hashlib.sha256(span).hexdigest(),
            "92e61d715b87e88b3152d737e72f08862cd37b51b80871373ff6b18c5cd0a60e",
        )
        ancestor = REAL_RUN(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", origin, "HEAD"],
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(ancestor.returncode, 0)

    def public_receipt_span(self):
        path = "apps/mobile/e2e/v1-workflows-fixture.mjs"
        expected = "b4fa24bbd7c17e0be213bea4f9d6fe0f3fdbbe1a83b79f639d8ff0c04eec38d6"
        source = scan.git(ROOT, "show", "HEAD:" + path)
        candidates = [
            (number, span)
            for number, span in enumerate(source.splitlines(keepends=True), 1)
            if hashlib.sha256(span).hexdigest() == expected
        ]
        self.assertEqual(len(candidates), 1)
        return path, candidates[0][0], candidates[0][1]

    def test_repository_public_receipt_review_binds_each_actual_origin_span(self):
        path, current_line, span = self.public_receipt_span()
        origins = {
            "f43c10e3eed509ea2240f5add52e09aea5c4857a",
            "a52e43caa57d1253271f581b347841e855112a29",
        }
        policy = (ROOT / ".gitleaksignore").read_text().splitlines()
        for origin in origins:
            fingerprint = f"{origin}:{path}:generic-api-key:225"
            self.assertEqual(policy.count(fingerprint), 1)
        self.assertNotIn(f"{path}:generic-api-key:225", policy)
        blame = scan.git(
            ROOT,
            "blame",
            "--line-porcelain",
            "-L",
            f"{current_line},{current_line}",
            "HEAD",
            "--",
            path,
        ).splitlines()
        origin, original, current = blame[0].decode().split()[:3]
        self.assertIn(origin, origins)
        self.assertEqual((int(original), int(current)), (225, current_line))
        original_span = scan.git(ROOT, "show", f"{origin}:{path}").splitlines(
            keepends=True
        )[224]
        self.assertEqual(
            hashlib.sha256(original_span).hexdigest(), hashlib.sha256(span).hexdigest()
        )
        ancestor = REAL_RUN(
            ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", origin, "HEAD"],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(ancestor.returncode, 0)

    def test_api_publication_requires_own_review_and_future_changed_span_stays_blocked(
        self,
    ):
        _path, _line, source_span = self.public_receipt_span()
        text = source_span.decode()
        self.write("record.txt", text)
        local_origin = self.commit("local public protocol receipt")
        self.git("switch", "-c", "api-publication", self.base)
        self.write("record.txt", text)
        api_origin = self.commit("API published public protocol receipt")
        self.assertNotEqual(local_origin, api_origin)
        self.assertEqual(
            self.git("show", f"{local_origin}:record.txt"),
            self.git("show", f"{api_origin}:record.txt"),
        )
        ancestor = REAL_RUN(
            [
                "git",
                "-C",
                str(self.repo),
                "merge-base",
                "--is-ancestor",
                local_origin,
                api_origin,
            ],
            capture_output=True,
            timeout=30,
        )
        self.assertEqual(ancestor.returncode, 1)

        def check(head, boundary, label):
            tree = self.root / f"{label}-{boundary}-tree"
            scan.tracked_tree(self.repo, head, tree)
            output = self.root / f"{label}-{boundary}-evidence"
            output.mkdir()
            finding = self.finding(head)
            if boundary == "tree":
                return scan.tree_policy_provenance(
                    self.repo, tree, [finding], output, head
                )
            return scan.history_policy_provenance(
                self.repo, tree, [finding], output, head, "--all"
            )

        self.write(".gitleaksignore", f"{local_origin}:record.txt:generic-api-key:1\n")
        local_only = self.commit("local origin review cannot cover separate API origin")
        for boundary in ("tree", "history"):
            with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
                check(local_only, boundary, "unreviewed-api")
        self.write(
            ".gitleaksignore",
            f"{local_origin}:record.txt:generic-api-key:1\n"
            f"{api_origin}:record.txt:generic-api-key:1\n",
        )
        reviewed = self.commit("both independently reviewed exact immutable origins")
        for boundary in ("tree", "history"):
            accepted = check(reviewed, boundary, "reviewed-api")
            self.assertTrue(accepted.endswith(boundary + "-policy.ignore"))
            proof = json.loads(
                (
                    self.root
                    / f"reviewed-api-{boundary}-evidence"
                    / f"{boundary}-policy-provenance.json"
                ).read_text()
            )
            self.assertEqual(proof["accepted_existing_policy"], 1)
            self.assertEqual(
                proof["findings"][0]["existing_fingerprint"],
                f"{api_origin}:record.txt:generic-api-key:1",
            )
            self.assertEqual(
                proof["findings"][0]["span_sha256"],
                hashlib.sha256(source_span).hexdigest(),
            )
        changed = (
            "const token = '"
            + hashlib.sha256(b"offline-unreviewed-replacement").hexdigest()
            + "';\n"
        )
        self.write("record.txt", changed)
        future = self.commit("new changed span cannot inherit either reviewed origin")
        for boundary in ("tree", "history"):
            with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
                check(future, boundary, "changed-future")

    def vector_fixture(self):
        public_vector = base64.b32encode(b"12345678901234567890").decode()
        self.span = f"const secret = '{public_vector}';\n"
        self.write("record.txt", self.span)
        origin = self.commit("public RFC vector")
        self.write(".gitleaksignore", f"{origin}:record.txt:generic-api-key:1\n")
        return origin, self.commit("exact origin review")

    def finding(self, head, start=1):
        return {"ruleId": "generic-api-key", "partialFingerprints": {"commitSha": head},
                "locations": [{"physicalLocation": {"artifactLocation": {"uri": "record.txt"},
                               "region": {"startLine": start, "endLine": start}}}]}

    def resolve(self, head, finding, boundary):
        tree = self.root / (boundary + "-tree")
        scan.tracked_tree(self.repo, head, tree)
        output = self.root / (boundary + "-evidence")
        output.mkdir()
        if boundary == "tree":
            return scan.tree_policy_provenance(self.repo, tree, [finding], output, head)
        return scan.history_policy_provenance(self.repo, tree, [finding], output, head, "--all")

    def test_shifted_public_vector_requires_exact_origin_in_tree_and_history(self):
        origin, _ = self.vector_fixture()
        self.write("record.txt", "// harmless line drift\n" + self.span)
        head = self.commit("preserved reviewed line")
        for boundary in ("tree", "history"):
            result = self.resolve(head, self.finding(head, 2), boundary)
            self.assertEqual(result, f"/scan/{boundary}-policy.ignore")
            proof = json.loads((self.root / (boundary + "-evidence") / (boundary + "-policy-provenance.json")).read_text())
            self.assertEqual(proof["accepted_existing_policy"], 1)
            self.assertEqual(proof["findings"][0]["existing_fingerprint"], f"{origin}:record.txt:generic-api-key:1")

    def test_changed_value_same_path_and_line_cannot_inherit_public_vector_review(self):
        self.vector_fixture()
        self.write("record.txt", self.span.replace("';\n", "A';\n"))
        head = self.commit("unreviewed changed span")
        for boundary in ("tree", "history"):
            with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
                self.resolve(head, self.finding(head), boundary)
            self.assertFalse((self.root / (boundary + "-policy.ignore")).exists())


class SelectionTests(GitFixture):
    def test_normal_push_exact_changed_inventory(self):
        self.write("record.txt", "changed\n")
        head = self.commit("changed")
        selection, ids = scan.history_selection(
            self.repo, head, "push", self.push(head)
        )
        self.assertEqual(selection, self.base + ".." + head)
        self.assertEqual(ids, [head])

    def test_side_parents_included_where_old_graph_scan_is_empty(self):
        first, second, head = self.side_merge("temporary credential\n")
        _, ids = scan.history_selection(self.repo, head, "push", self.push(head))
        self.assertEqual(ids, [first, second, head])
        self.assertEqual(
            self.git("rev-list", "--no-merges", "--first-parent", first + "^.." + head),
            "",
        )

    def test_pull_request_uses_actual_merge_and_both_parent_lineages(self):
        before, side, merged = self.resolution_merge("resolved\n")
        event = {"pull_request": {"base": {"sha": before}, "head": {"sha": side}}}
        _, ids = scan.history_selection(self.repo, merged, "pull_request", event)
        self.assertEqual(set(ids), {side, merged})

    def test_initial_push_and_schedule_inventory(self):
        for event_name, event in [
            ("push", self.push(self.base, "0" * 40)),
            ("schedule", {}),
        ]:
            _, ids = scan.history_selection(self.repo, self.base, event_name, event)
            self.assertEqual(ids, [self.base])

    def test_empty_changed_inventory_fails_closed(self):
        with self.assertRaisesRegex(scan.ScanError, "empty"):
            scan.history_selection(self.repo, self.base, "push", self.push(self.base))

    def test_malformed_or_wrong_event_candidate_fails_closed(self):
        bad = [
            self.push(self.base, "not-a-sha"),
            self.push("a" * 40),
            {**self.push(self.base), "deleted": True},
        ]
        for event in bad:
            with self.assertRaises(scan.ScanError):
                scan.history_selection(self.repo, self.base, "push", event)

    def test_missing_base_fails_closed(self):
        with self.assertRaises(scan.ScanError):
            scan.history_selection(
                self.repo, self.base, "push", self.push(self.base, "a" * 40)
            )

    def test_wrong_checkout_and_unsupported_event_fail_closed(self):
        with self.assertRaises(scan.ScanError):
            scan.history_selection(self.repo, "a" * 40, "schedule", {})
        with self.assertRaises(scan.ScanError):
            scan.history_selection(self.repo, self.base, "workflow_dispatch", {})

    def test_shallow_checkout_is_rejected(self):
        (self.repo / ".git/shallow").write_text(self.base + "\n")
        with self.assertRaisesRegex(scan.ScanError, "complete Git"):
            scan.history_selection(self.repo, self.base, "schedule", {})

    def test_malformed_and_duplicate_commit_inventory_is_rejected(self):
        self.write("record.txt", "change\n")
        head = self.commit("change")
        native_git = scan.git
        for output in (b"not-a-commit\n", (head + "\n" + head + "\n").encode()):

            def malformed(repo, *args, _output=output, **kwargs):
                if args[0] == "rev-list":
                    return _output
                return native_git(repo, *args, **kwargs)

            with (
                patch.object(scan, "git", side_effect=malformed),
                self.assertRaises(scan.ScanError),
            ):
                scan.history_selection(self.repo, head, "push", self.push(head))

    def test_force_push_walks_candidate_history_not_old_first_parent(self):
        self.write("record.txt", "abandoned branch\n")
        abandoned = self.commit("abandoned")
        self.git("switch", "--detach", self.base)
        self.write("record.txt", "replacement branch\n")
        replacement = self.commit("replacement")
        _, ids = scan.history_selection(
            self.repo, replacement, "push", self.push(replacement, abandoned)
        )
        self.assertEqual(ids, [replacement])


class TreeTests(GitFixture):
    def test_exact_blobs_ignore_dirty_untracked_export_and_checkout_filters(self):
        self.write(
            ".gitattributes",
            "record.txt export-ignore\nrecord.txt filter=unavailable\n",
        )
        head = self.commit("attributes")
        self.write("record.txt", "dirty not candidate\n")
        self.write("untracked.txt", "untracked not candidate\n")
        target = self.root / "snapshot"
        entries = scan.tracked_tree(self.repo, head, target)
        self.assertEqual((target / "record.txt").read_bytes(), b"original\n")
        self.assertNotIn("untracked.txt", [item["path"] for item in entries])
        self.assertGreater(sum(item["bytes"] for item in entries), 0)
        for policy in (".gitleaks.toml", ".gitleaksignore"):
            self.assertEqual(
                (target / policy).read_bytes(), (self.repo / policy).read_bytes()
            )

    def test_symlink_blob_is_literal_and_never_followed(self):
        oid = self.git("hash-object", "-w", "record.txt")
        self.git("update-index", "--add", "--cacheinfo", "120000," + oid + ",link")
        self.git("commit", "-m", "symlink")
        head = self.git("rev-parse", "HEAD")
        target = self.root / "snapshot"
        scan.tracked_tree(self.repo, head, target)
        self.assertFalse((target / "link").is_symlink())
        self.assertEqual((target / "link").read_bytes(), b"original\n")

    def test_empty_and_malformed_tree_inventory_fail_closed(self):
        for raw in (
            b"",
            b"not terminated",
            b"broken\0",
            b"100644 blob invalid\tfile\0",
        ):
            with (
                patch.object(scan, "git", return_value=raw),
                self.assertRaises(scan.ScanError),
            ):
                scan.tracked_tree(self.repo, self.base, self.root / "snapshot")

    def test_submodule_and_unsafe_paths_fail_closed(self):
        for mode, kind, name in [
            ("160000", "commit", "submodule"),
            ("100644", "blob", "../escape"),
            ("100644", "blob", "/absolute"),
            ("100644", "blob", ".git/config"),
        ]:
            raw = f"{mode} {kind} {'a' * 40}\t{name}\0".encode()
            with (
                patch.object(scan, "git", return_value=raw),
                self.assertRaises(scan.ScanError),
            ):
                scan.tracked_tree(self.repo, self.base, self.root / "snapshot")


class ReceiptTests(unittest.TestCase):
    def test_positive_receipts(self):
        output = b"INF 3 commits scanned.\nINF scanned ~24 bytes (24 bytes) in 1ms\n"
        self.assertEqual(
            scan.scanner_receipt(output, history=True),
            {"scanned_bytes": 24, "scanned_commits": 3},
        )

    def test_exact_byte_integer_survives_human_readable_large_units(self):
        output = (
            b"INF 3 commits scanned.\nINF scanned ~1234567 bytes (1.18 MB) in 1ms\n"
        )
        self.assertEqual(
            scan.scanner_receipt(output, history=True)["scanned_bytes"], 1234567
        )

    def test_zero_missing_malformed_and_duplicate_receipts_fail_closed(self):
        for output in (
            b"",
            b"0 commits scanned.\nscanned ~0 bytes (0)",
            b"1 commits scanned.\nscanned ~0 bytes (0)",
            b"0 commits scanned.\nscanned ~1 bytes (1 bytes)",
            b"1 commits scanned.\nscanned ~1 bytes (oops)",
            b"1 commits scanned.\nscanned ~1 bytes (1 bytes)\nscanned ~1 bytes (1 bytes)",
            b"1 commits scanned.\nscanned ~1 bytes (1 bytes)\npartial scan completed",
            b"ERR failed\n1 commits scanned.\nscanned ~1 bytes (1 bytes)",
        ):
            with self.assertRaises(scan.ScanError):
                scan.scanner_receipt(output, history=True)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix="caseops-cleanup-test-")
        self.addCleanup(self.storage.cleanup)
        self.root = Path(self.storage.name)
        self.workspace = self.root / "workspace"
        self.output = self.root / "evidence"
        self.workspace.mkdir()
        self.output.mkdir()
        self.now = 0.0
        self.calls = []
        self.visibility = ["absent"]
        self.remove_elapsed = 0.0
        self.inspect_elapsed = 0.0
        self.scan_error = None
        self.create_error = None
        self.create_elapsed = 0.0
        self.create_result = (0, ("a" * 64 + "\n").encode(), b"")
        self.owner = None

    def fake_run(self, args, **kwargs):
        self.calls.append((list(args), dict(kwargs)))
        self.assertEqual(args[0], "docker")
        if args[1] == "create":
            self.owner = args[args.index("--name") + 1]
            self.assertRegex(self.owner, r"^caseops-secret-[0-9a-f]{32}$")
            self.assertEqual(kwargs["timeout"], 1)
            self.assertEqual(args[args.index("--network") + 1], "none")
            self.assertEqual(args[args.index("--pull") + 1], "never")
            self.assertIn(scan.GITLEAKS_IMAGE, args)
            self.now += self.create_elapsed
            if self.create_error:
                raise self.create_error
            return subprocess.CompletedProcess(args, *self.create_result)
        if args[1] == "start":
            self.assertEqual(args, ["docker", "start", "--attach", "a" * 64])
            self.assertGreater(kwargs["timeout"], 0)
            self.assertLessEqual(kwargs["timeout"], 1 - self.create_elapsed)
            if self.scan_error:
                raise self.scan_error
            (self.workspace / "tree.sarif").write_text(
                json.dumps({"version": "2.1.0", "runs": [{"results": []}]})
            )
            return subprocess.CompletedProcess(
                args, 0, b"1 commits scanned.\nscanned ~1 bytes (1 bytes)\n", b""
            )
        self.assertEqual(args[-1], self.owner)
        self.assertGreater(kwargs["timeout"], 0)
        self.assertLessEqual(
            kwargs["timeout"], 30 - (self.now - self.create_elapsed)
        )
        if args[1] == "rm":
            self.assertEqual(args, ["docker", "rm", "--force", self.owner])
            self.now += self.remove_elapsed
            return subprocess.CompletedProcess(args, 0, b"", b"")
        self.assertEqual(args, ["docker", "inspect", self.owner])
        self.now += self.inspect_elapsed
        response = (
            self.visibility.pop(0) if len(self.visibility) > 1 else self.visibility[0]
        )
        if isinstance(response, BaseException):
            raise response
        if response == "present":
            return subprocess.CompletedProcess(args, 0, b"[{}]\n", b"")
        if response == "absent":
            return subprocess.CompletedProcess(
                args, 1, b"[]\n", f"Error: No such object: {self.owner}\n".encode()
            )
        return subprocess.CompletedProcess(args, *response)

    def boundary(self):
        def advance(seconds):
            self.assertGreater(seconds, 0)
            self.now += seconds

        with (
            patch.object(scan.subprocess, "run", side_effect=self.fake_run),
            patch.object(scan, "monotonic", side_effect=lambda: self.now, create=True),
            patch.object(scan, "sleep", side_effect=advance, create=True),
        ):
            return scan.scan_boundary(
                self.root,
                self.workspace,
                self.output,
                kind="tree",
                selection="",
                docker="docker",
                timeout=1,
                head="0" * 40,
            )

    def cleanup(self):
        return json.loads((self.output / "tree-cleanup.json").read_text())

    def assert_unconfirmed(self):
        self.assertFalse(self.cleanup()["cleanup_confirmed"])
        self.assertFalse((self.output / "tree-receipt.json").exists())

    def test_remove_acknowledgement_requires_actual_owned_absence(self):
        result = self.boundary()
        inspections = [args for args, _ in self.calls if args[1] == "inspect"]
        self.assertEqual(inspections, [["docker", "inspect", self.owner]])
        self.assertTrue(result["cleanup_confirmed"])
        self.assertEqual(self.cleanup()["inspect_attempts"], 1)

    def test_late_create_after_not_found_cannot_claim_cleanup(self):
        pending = False
        late_created = False
        error = subprocess.TimeoutExpired("docker create", 1)

        def late(args, **kwargs):
            nonlocal pending, late_created
            self.calls.append((list(args), dict(kwargs)))
            if args[1] in ("run", "create"):
                self.owner = args[args.index("--name") + 1]
                pending = True
                raise error
            if args[1] == "rm":
                self.assertTrue(pending)
                return subprocess.CompletedProcess(args, 0, b"", b"")
            self.assertEqual(args, ["docker", "inspect", self.owner])
            # The daemon settles the in-flight create AFTER this absence snapshot.
            self.assertTrue(pending)
            pending = False
            late_created = True
            return subprocess.CompletedProcess(
                args, 1, b"[]", f"Error: No such object: {self.owner}".encode()
            )

        with patch.object(self, "fake_run", side_effect=late):
            with self.assertRaises(scan.ScanError) as caught:
                self.boundary()
        self.assertIs(caught.exception.__context__, error)
        self.assertTrue(late_created)
        self.assert_unconfirmed()
        self.assertFalse(self.cleanup()["create_acknowledged"])
        self.assertFalse(any(args[1] == "start" for args, _ in self.calls))

    def test_start_requires_acknowledged_id_and_shares_original_deadline(self):
        self.create_elapsed = 0.75
        result = self.boundary()
        self.assertEqual(
            [args[1] for args, _ in self.calls], ["create", "start", "rm", "inspect"]
        )
        self.assertEqual(self.calls[1][1]["timeout"], 0.25)
        self.assertTrue(result["cleanup_confirmed"])
        self.assertEqual(self.cleanup()["container_id"], "a" * 64)
        self.assertTrue(self.cleanup()["create_acknowledged"])

    def test_create_consuming_scan_budget_cannot_start(self):
        self.create_elapsed = 1.0
        with self.assertRaises(subprocess.TimeoutExpired):
            self.boundary()
        self.assertFalse(any(args[1] == "start" for args, _ in self.calls))
        self.assertTrue(self.cleanup()["create_acknowledged"])
        self.assertTrue(self.cleanup()["cleanup_confirmed"])
        self.assertFalse((self.output / "tree-receipt.json").exists())

    def test_create_timeout_and_interruption_cannot_claim_settled_absence(self):
        for error in (
            subprocess.TimeoutExpired("docker create", 1),
            KeyboardInterrupt(),
        ):
            with self.subTest(error=type(error).__name__):
                self.create_error = error
                self.calls.clear()
                with self.assertRaisesRegex(scan.ScanError, "unacknowledged") as caught:
                    self.boundary()
                self.assertIs(caught.exception.__context__, error)
                self.assertEqual(
                    self.cleanup()["scan_error_type"], type(error).__name__
                )
                self.assertFalse(self.cleanup()["create_acknowledged"])
                self.assert_unconfirmed()
                self.assertFalse(any(args[1] == "start" for args, _ in self.calls))

    def test_failed_or_malformed_create_acknowledgement_cannot_start(self):
        for result in (
            (1, ("a" * 64 + "\n").encode(), b"transport error"),
            (0, b"", b""),
            (0, b"not-an-id\n", b""),
            (0, ("a" * 64 + "\n" + "b" * 64 + "\n").encode(), b""),
        ):
            with self.subTest(result=result):
                self.create_result = result
                self.calls.clear()
                with self.assertRaisesRegex(scan.ScanError, "unacknowledged") as caught:
                    self.boundary()
                self.assertIsInstance(caught.exception.__context__, scan.ScanError)
                self.assert_unconfirmed()
                self.assertFalse(self.cleanup()["create_acknowledged"])
                self.assertFalse(any(args[1] == "start" for args, _ in self.calls))

    def test_late_start_cannot_recreate_acknowledged_removed_container(self):
        original = self.fake_run
        exists = False
        pending_start = False
        error = subprocess.TimeoutExpired("docker start", 1)

        def late(args, **kwargs):
            nonlocal exists, pending_start
            if args[1] == "create":
                result = original(args, **kwargs)
                exists = True
                return result
            if args[1] == "start":
                self.assertEqual(args[-1], "a" * 64)
                self.assertTrue(exists)
                pending_start = True
                raise error
            if args[1] == "rm":
                exists = False
            result = original(args, **kwargs)
            if args[1] == "inspect":
                self.assertTrue(pending_start)
                self.assertFalse(exists)
                pending_start = False
            return result

        with patch.object(self, "fake_run", side_effect=late):
            with self.assertRaises(subprocess.TimeoutExpired) as caught:
                self.boundary()
        self.assertIs(caught.exception, error)
        self.assertFalse(exists)
        self.assertFalse(pending_start)
        self.assertTrue(self.cleanup()["cleanup_confirmed"])
        self.assertEqual(sum(args[1] == "create" for args, _ in self.calls), 1)

    def test_delayed_removal_visibility_is_verified_before_claim(self):
        self.visibility = ["present", "present", "absent"]
        result = self.boundary()
        self.assertEqual(self.cleanup()["inspect_attempts"], 3)
        self.assertTrue(result["cleanup_confirmed"])
        self.assertEqual(sum(args[1] == "rm" for args, _ in self.calls), 1)

    def test_permanently_retained_container_never_gets_cleanup_claim(self):
        self.visibility = ["present"]
        self.inspect_elapsed = 15
        with self.assertRaises(scan.ScanError):
            self.boundary()
        self.assert_unconfirmed()
        self.assertLessEqual(sum(args[1] == "inspect" for args, _ in self.calls), 2)

    def test_inspect_transport_error_is_not_absence(self):
        self.visibility = [(1, b"", b"Cannot connect to Docker daemon")]
        with self.assertRaises(scan.ScanError):
            self.boundary()
        self.assert_unconfirmed()

    def test_other_container_missing_error_is_not_owned_absence(self):
        self.visibility = [(1, b"[]", b"Error: No such object: someone-else")]
        with self.assertRaises(scan.ScanError):
            self.boundary()
        self.assert_unconfirmed()

    def test_missing_message_mixed_with_transport_error_is_not_absence(self):
        original = self.fake_run

        def mixed(args, **kwargs):
            if args[1] == "inspect":
                self.visibility = [
                    (
                        1,
                        b"[]",
                        f"Error: No such object: {self.owner}\nCannot connect to Docker daemon".encode(),
                    )
                ]
            return original(args, **kwargs)

        with patch.object(self, "fake_run", side_effect=mixed):
            with self.assertRaises(scan.ScanError):
                self.boundary()
        self.assert_unconfirmed()

    def test_inspect_timeout_does_not_claim_cleanup(self):
        self.visibility = [subprocess.TimeoutExpired("docker inspect", 1)]
        with self.assertRaises(subprocess.TimeoutExpired):
            self.boundary()
        self.assert_unconfirmed()

    def test_absence_returned_after_cleanup_budget_is_not_claimed(self):
        self.inspect_elapsed = 31
        with self.assertRaises(scan.ScanError):
            self.boundary()
        self.assert_unconfirmed()

    def test_remove_consuming_budget_does_not_start_inspect(self):
        self.remove_elapsed = 31
        with self.assertRaises(scan.ScanError):
            self.boundary()
        self.assert_unconfirmed()
        self.assertEqual(self.cleanup()["inspect_attempts"], 0)
        self.assertFalse(any(args[1] == "inspect" for args, _ in self.calls))

    def test_missing_error_with_retained_object_output_is_not_absence(self):
        original = self.fake_run

        def contradictory(args, **kwargs):
            if args[1] == "inspect":
                self.visibility = [
                    (1, b"[{}]", f"Error: No such object: {self.owner}".encode())
                ]
            return original(args, **kwargs)

        with patch.object(self, "fake_run", side_effect=contradictory):
            with self.assertRaises(scan.ScanError):
                self.boundary()
        self.assert_unconfirmed()

    def test_each_cleanup_command_uses_only_remaining_budget(self):
        self.remove_elapsed = 27.5
        self.visibility = ["present", "absent"]
        self.boundary()
        inspections = [
            kwargs["timeout"] for args, kwargs in self.calls if args[1] == "inspect"
        ]
        self.assertEqual(len(inspections), 2)
        self.assertEqual(inspections[0], 2.5)
        self.assertLess(inspections[1], inspections[0])

    def test_scan_timeout_is_preserved_after_verified_delayed_cleanup(self):
        self.scan_error = subprocess.TimeoutExpired("docker start", 1)
        self.visibility = ["present", "absent"]
        with self.assertRaises(subprocess.TimeoutExpired) as caught:
            self.boundary()
        self.assertIs(caught.exception, self.scan_error)
        self.assertTrue(self.cleanup()["cleanup_confirmed"])
        self.assertEqual(self.cleanup()["inspect_attempts"], 2)
        self.assertEqual(self.cleanup()["scan_error_type"], "TimeoutExpired")

    def test_original_scan_timeout_retained_when_cleanup_cannot_finish(self):
        self.scan_error = subprocess.TimeoutExpired("docker start", 1)
        self.visibility = ["present"]
        self.inspect_elapsed = 15
        with self.assertRaises(scan.ScanError) as caught:
            self.boundary()
        self.assertIs(caught.exception.__context__, self.scan_error)
        self.assert_unconfirmed()
        self.assertEqual(self.cleanup()["scan_error_type"], "TimeoutExpired")


class FailureTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.write("record.txt", "changed\n")
        self.head = self.commit("changed")
        self.creates = {}

    def fake_run(self, args, **kwargs):
        if args[0] != "docker":
            return REAL_RUN(args, **kwargs)
        if args[1] == "create":
            container_id = hashlib.sha256(
                args[args.index("--name") + 1].encode()
            ).hexdigest()
            self.creates[container_id] = list(args)
            return subprocess.CompletedProcess(
                args, 0, (container_id + "\n").encode(), b""
            )
        if args[1] == "start":
            created = self.creates[args[-1]]
            self.assertEqual(args, ["docker", "start", "--attach", args[-1]])
            args = created
            mount = args[args.index("--mount", args.index("--mount") + 1) + 1]
            workspace = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
            kind = "tree" if "dir" in args else "history"
            (workspace / (kind + ".sarif")).write_text(
                json.dumps(
                    {
                        "version": "2.1.0",
                        "runs": [{"results": []}],
                    }
                )
            )
            return subprocess.CompletedProcess(
                args, 0, b"1 commits scanned.\nscanned ~1 bytes (1 bytes)\n", b""
            )
        if args[1] == "inspect":
            return subprocess.CompletedProcess(
                args, 1, b"[]\n", f"Error: No such object: {args[-1]}\n".encode()
            )
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def test_complete_receipts_and_immutable_identity(self):
        with patch.object(scan.subprocess, "run", side_effect=self.fake_run):
            result = self.run_scan(self.head)
        self.assertEqual(result["head"], self.head)
        self.assertEqual(result["commits"], 1)
        self.assertEqual(self.progress()[-1]["event"], "scan_completed")
        self.assertEqual(set(result["boundaries"]), {"tree", "history"})

    def test_missing_binary_does_not_fall_through_to_other_tool(self):
        with self.assertRaises(FileNotFoundError):
            self.run_scan(self.head, docker=str(self.root / "absent-binary"))
        self.assert_incomplete()

    def test_scanner_failure_retains_report_without_completion(self):
        def failed(args, **kwargs):
            result = self.fake_run(args, **kwargs)
            if args[:2] == ["docker", "start"]:
                result.returncode = 2
            return result

        with (
            patch.object(scan.subprocess, "run", side_effect=failed),
            self.assertRaises(scan.ScanError),
        ):
            self.run_scan(self.head)
        self.assertTrue((self.root / "evidence/tree.sarif").exists())
        self.assert_incomplete()

    def test_zero_scanner_bytes_is_not_success_even_with_nonempty_git_inventory(self):
        def zero(args, **kwargs):
            result = self.fake_run(args, **kwargs)
            if args[:2] == ["docker", "start"]:
                result.stdout = b"0 commits scanned.\nscanned ~0 bytes (0)"
            return result

        with (
            patch.object(scan.subprocess, "run", side_effect=zero),
            self.assertRaises(scan.ScanError),
        ):
            self.run_scan(self.head)
        self.assert_incomplete()

    def test_timeout_and_interruption_clean_owned_container_and_do_not_complete(self):
        for error in (subprocess.TimeoutExpired("docker", 1), KeyboardInterrupt()):
            with self.subTest(error=type(error).__name__):
                cleanup_calls = []

                def interrupted(
                    args, _error=error, _cleanup_calls=cleanup_calls, **kwargs
                ):
                    if args[:2] == ["docker", "start"]:
                        raise _error
                    if args[:2] == ["docker", "rm"]:
                        _cleanup_calls.append(args)
                    return self.fake_run(args, **kwargs)

                with (
                    patch.object(scan.subprocess, "run", side_effect=interrupted),
                    self.assertRaises(type(error)),
                ):
                    scan.run_scan(
                        repo=self.repo,
                        head=self.head,
                        event_name="push",
                        event=self.push(self.head),
                        output=self.root / type(error).__name__,
                    )
                self.assertEqual(len(cleanup_calls), 1)
                self.assertTrue(cleanup_calls[0][-1].startswith("caseops-secret-"))
                self.assertFalse(
                    (self.root / type(error).__name__ / "completion.json").exists()
                )

    def test_existing_evidence_cannot_be_overwritten(self):
        output = self.root / "evidence"
        output.mkdir()
        (output / "retained").write_text("retained")
        with self.assertRaises(FileExistsError):
            self.run_scan(self.head)
        self.assertEqual((output / "retained").read_text(), "retained")

    def test_malformed_or_missing_sarif_fails_closed(self):
        def malformed(args, **kwargs):
            result = self.fake_run(args, **kwargs)
            if args[:2] == ["docker", "start"]:
                created = self.creates[args[-1]]
                mount = created[
                    created.index("--mount", created.index("--mount") + 1) + 1
                ]
                workspace = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
                (workspace / "tree.sarif").write_text("{}")
            return result

        with (
            patch.object(scan.subprocess, "run", side_effect=malformed),
            self.assertRaises(scan.ScanError),
        ):
            self.run_scan(self.head)
        self.assert_incomplete()

    def test_dirty_policy_cannot_add_unreviewed_suppression(self):
        self.write(".gitleaksignore", "unreviewed suppression\n")
        with self.assertRaisesRegex(scan.ScanError, "policy differs"):
            self.run_scan(self.head)
        self.assert_incomplete()

    def test_failed_cleanup_is_not_misclassified_as_absent_container(self):
        def unavailable(args, **kwargs):
            if args[:2] in (["docker", "rm"], ["docker", "inspect"]):
                return subprocess.CompletedProcess(
                    args, 1, b"", b"Cannot connect to Docker daemon"
                )
            return self.fake_run(args, **kwargs)

        with (
            patch.object(scan.subprocess, "run", side_effect=unavailable),
            self.assertRaises(scan.ScanError),
        ):
            self.run_scan(self.head)
        self.assert_incomplete()

    def test_unsettled_creation_records_failure_without_scan_completion(self):
        original = self.fake_run
        error = subprocess.TimeoutExpired("docker create", 1)

        def unsettled(args, **kwargs):
            if args[:2] == ["docker", "create"]:
                raise error
            self.assertNotEqual(args[:2], ["docker", "start"])
            return original(args, **kwargs)

        with patch.object(scan.subprocess, "run", side_effect=unsettled):
            with self.assertRaisesRegex(scan.ScanError, "unacknowledged") as caught:
                self.run_scan(self.head)
        self.assertIs(caught.exception.__context__, error)
        self.assert_incomplete()
        cleanup = json.loads((self.root / "evidence/tree-cleanup.json").read_text())
        self.assertFalse(cleanup["cleanup_confirmed"])
        self.assertFalse(cleanup["create_acknowledged"])
        self.assertEqual(cleanup["scan_error_type"], "TimeoutExpired")
        self.assertFalse((self.root / "evidence/tree-receipt.json").exists())


class RealGitleaksTests(GitFixture):
    @staticmethod
    def canary():
        # An offline synthetic Stripe-shaped token, generated rather than a
        # credential-looking committed literal. It is never sent anywhere.
        return (
            "payment_key = sk_"
            + "live_"
            + hashlib.sha256(b"offline-canary").hexdigest()[:24]
            + "\n"
        )

    def test_real_clean_push_has_two_nonempty_scanner_receipts(self):
        self.write("record.txt", "safe changed text\n")
        head = self.commit("clean change")
        result = self.run_scan(head)
        for boundary in result["boundaries"].values():
            self.assertGreater(boundary["scanned_bytes"], 0)
            self.assertTrue(boundary["cleanup_confirmed"])
            self.assertEqual(boundary["image"], scan.GITLEAKS_IMAGE)

    def assert_redacted_failure(self, expected_report):
        self.assert_incomplete()
        report = self.root / "evidence" / expected_report
        data = report.read_text()
        self.assertNotIn(self.canary().strip().split(" = ")[1], data)
        results = json.loads(data)["runs"][0]["results"]
        self.assertTrue(results)

    def test_real_removed_side_parent_secret_is_not_hidden_by_clean_head(self):
        first, second, head = self.side_merge(self.canary())
        with self.assertRaises(scan.ScanError):
            self.run_scan(head)
        self.assert_redacted_failure("history.sarif")
        inventory = json.loads((self.root / "evidence/inventory.json").read_text())
        self.assertEqual(inventory["commits"], [first, second, head])
        self.assertIn(
            "tree",
            [
                row.get("kind")
                for row in self.progress()
                if row["event"] == "boundary_completed"
            ],
        )

    def test_real_merge_only_resolution_secret_is_found_in_candidate_tree(self):
        before, _, merged = self.resolution_merge(self.canary())
        with self.assertRaises(scan.ScanError):
            self.run_scan(merged, self.push(merged, before))
        self.assert_redacted_failure("tree.sarif")

    def test_real_removed_merge_resolution_secret_is_found_in_history(self):
        before, _, merged = self.resolution_merge(self.canary())
        self.write("record.txt", "clean final resolution\n")
        head = self.commit("remove resolved credential")
        with self.assertRaises(scan.ScanError):
            self.run_scan(head, self.push(head, before))
        self.assert_redacted_failure("history.sarif")
        inventory = json.loads((self.root / "evidence/inventory.json").read_text())
        self.assertIn(merged, inventory["commits"])

    def test_real_empty_commit_zero_bytes_is_rejected_after_positive_tree(self):
        self.git("commit", "--allow-empty", "-m", "empty change")
        head = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(scan.ScanError, "nonzero scanned bytes"):
            self.run_scan(head)
        self.assert_incomplete()
        receipt = json.loads((self.root / "evidence/history-receipt.json").read_text())
        self.assertEqual(receipt["exit_code"], 0)
        self.assertIn("scanned ~0 bytes (0)", receipt["counter_lines"])
        self.assertIn("0 commits scanned.", receipt["counter_lines"])

    def reviewed_fixture(self):
        self.write("record.txt", self.canary())
        origin = self.commit("reviewed synthetic canary")
        self.write(
            ".gitleaksignore",
            f"{origin}:record.txt:stripe-access-token:1\n{origin}:record.txt:generic-api-key:1\n",
        )
        return origin, self.commit("existing exact reviewed fingerprint")

    def test_real_existing_commit_fingerprint_keeps_exact_unchanged_tree_provenance(
        self,
    ):
        origin, _ = self.reviewed_fixture()
        self.write("record.txt", "# harmless inserted line\n" + self.canary())
        head = self.commit("shift unchanged reviewed line")
        result = self.run_scan(head)
        self.assertGreater(
            result["boundaries"]["tree"]["existing_policy_translations"], 0
        )
        provenance = json.loads(
            (self.root / "evidence/tree-policy-provenance.json").read_text()
        )
        self.assertTrue(
            all(row["accepted_existing_policy"] for row in provenance["findings"])
        )
        self.assertTrue(
            all(
                row["existing_fingerprint"].startswith(origin + ":")
                for row in provenance["findings"]
            )
        )
        self.assertTrue((self.root / "evidence/tree-initial.sarif").exists())

    def test_real_future_secret_same_path_line_is_not_covered_by_historical_fingerprint(
        self,
    ):
        self.reviewed_fixture()
        replacement = (
            "payment_key = sk_"
            + "live_"
            + hashlib.sha256(b"new-offline-canary").hexdigest()[:24]
            + "\n"
        )
        self.write("record.txt", replacement)
        head = self.commit("future credential must fail")
        with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
            self.run_scan(head)
        self.assert_incomplete()
        provenance = json.loads(
            (self.root / "evidence/tree-policy-provenance.json").read_text()
        )
        self.assertEqual(provenance["accepted_existing_policy"], 0)

    def reviewed_multiline_checksum_fixture(self):
        checksum = hashlib.sha256(b"offline-readback-report").hexdigest()
        text = f"API receipt SHA256:\n`{checksum}`;\n"
        self.write("record.txt", text)
        origin = self.commit("reviewed multiline readback checksum")
        self.write(".gitleaksignore", f"{origin}:record.txt:generic-api-key:1\n")
        return origin, text, self.commit("exact historical checksum fingerprint")

    def test_real_reviewed_multiline_checksum_preserves_tree_and_history_provenance(
        self,
    ):
        origin, text, head = self.reviewed_multiline_checksum_fixture()
        result = self.run_scan(head)
        for boundary in result["boundaries"].values():
            self.assertGreater(boundary["scanned_bytes"], 0)
            self.assertTrue(boundary["cleanup_confirmed"])
        self.assertGreater(result["boundaries"]["history"]["scanned_commits"], 0)
        provenance = json.loads(
            (self.root / "evidence/tree-policy-provenance.json").read_text()
        )
        self.assertEqual(provenance["accepted_existing_policy"], 1)
        self.assertEqual(
            provenance["findings"],
            [
                {
                    "path": "record.txt",
                    "rule": "generic-api-key",
                    "start_line": 1,
                    "end_line": 2,
                    "existing_fingerprint": f"{origin}:record.txt:generic-api-key:1",
                    "accepted_existing_policy": True,
                    "span_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            ],
        )
        self.assertEqual((self.repo / "record.txt").read_bytes(), text.encode())

    def test_real_changed_multiline_checksum_cannot_inherit_reviewed_fingerprint(self):
        _, original, _ = self.reviewed_multiline_checksum_fixture()
        replacement = hashlib.sha256(b"different-unreviewed-readback").hexdigest()
        self.write("record.txt", f"API receipt SHA256:\n`{replacement}`;\n")
        head = self.commit("changed second line must fail provenance")
        with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
            self.run_scan(head)
        self.assert_incomplete()
        provenance = json.loads(
            (self.root / "evidence/tree-policy-provenance.json").read_text()
        )
        self.assertEqual(provenance["accepted_existing_policy"], 0)
        self.assertEqual(len(provenance["findings"]), 1)
        finding = provenance["findings"][0]
        self.assertEqual((finding["start_line"], finding["end_line"]), (1, 2))
        self.assertNotEqual(
            finding["span_sha256"], hashlib.sha256(original.encode()).hexdigest()
        )
        self.assertFalse((self.root / "evidence/history.sarif").exists())
        receipt = json.loads((self.root / "evidence/tree-receipt.json").read_text())
        self.assertEqual(receipt["exit_code"], 2)
        self.assertTrue(receipt["cleanup_confirmed"])

    def test_real_schedule_translates_reviewed_merge_and_line_drift_not_history_scope(
        self,
    ):
        origin, _ = self.reviewed_fixture()
        self.git("checkout", "-b", "reviewed-side")
        self.write("record.txt", "# harmless line drift\n" + self.canary())
        shifted = self.commit("shift reviewed fixture")
        self.git("checkout", "main")
        self.git("rm", "record.txt")
        self.write("other.txt", "independent clean main change\n")
        self.commit("independent main change")
        self.git("merge", "--no-ff", "reviewed-side", check=False)
        self.assertEqual(self.git("rev-parse", "MERGE_HEAD"), shifted)
        self.write("record.txt", "# harmless line drift\n" + self.canary())
        merged = self.commit("resolve with the reviewed side span")
        self.git("checkout", "-b", "empty-diff-side")
        self.write("temporary.txt", "clean transient side change\n")
        self.commit("transient clean side addition")
        self.git("rm", "temporary.txt")
        self.commit("remove transient clean side addition")
        self.git("checkout", "main")
        self.git(
            "merge", "--no-ff", "empty-diff-side", "-m", "empty first-parent merge diff"
        )
        empty_merge = self.git("rev-parse", "HEAD")
        self.git("commit", "--allow-empty", "-m", "empty history commit")
        head = self.git("rev-parse", "HEAD")
        result = self.run_scan(head, {}, "schedule")
        inventory = json.loads((self.root / "evidence/inventory.json").read_text())
        self.assertEqual(inventory["history_selection"], "--all")
        self.assertIn(origin, inventory["commits"])
        self.assertIn(shifted, inventory["commits"])
        self.assertIn(merged, inventory["commits"])
        self.assertIn(empty_merge, inventory["commits"])
        self.assertIn(head, inventory["commits"])
        # Pinned gitleaks omits the empty commit, empty-diff merge and the
        # deletion-only side commit, while all remain in the selected DAG.
        self.assertEqual(
            result["boundaries"]["history"]["scanned_commits"],
            len(inventory["commits"]) - 3,
        )
        output = self.root / "evidence"
        initial = json.loads((output / "history-initial-receipt.json").read_text())
        self.assertEqual(initial["exit_code"], 2)
        self.assertGreater(initial["scanned_bytes"], 0)
        proofs = json.loads((output / "history-policy-provenance.json").read_text())
        self.assertGreater(proofs["accepted_existing_policy"], 0)
        self.assertTrue(
            all(
                row["existing_fingerprint"].startswith(origin + ":")
                for row in proofs["findings"]
            )
        )
        self.assertIn(merged, {row["reported_commit"] for row in proofs["findings"]})
        for suffix in ("initial-cleanup", "cleanup"):
            self.assertTrue(
                json.loads((output / f"history-{suffix}.json").read_text())[
                    "cleanup_confirmed"
                ]
            )
        self.assertEqual(
            json.loads((output / "history.sarif").read_text())["runs"][0]["results"], []
        )
        self.assertEqual(result["boundaries"]["history"]["exit_code"], 0)

    def test_real_unreviewed_changed_span_removed_from_head_still_blocks_history(self):
        self.reviewed_fixture()
        changed = self.canary().replace(
            hashlib.sha256(b"offline-canary").hexdigest()[:24],
            hashlib.sha256(b"changed-history-canary").hexdigest()[:24],
        )
        self.write("record.txt", changed)
        unreviewed = self.commit("new unreviewed historical span")
        self.write("record.txt", "clean current head\n")
        head = self.commit("remove unreviewed historical span")
        with self.assertRaisesRegex(scan.ScanError, "History has unreviewed findings"):
            self.run_scan(head, {}, "schedule")
        self.assert_redacted_failure("history-initial.sarif")
        proof = json.loads(
            (self.root / "evidence/history-policy-provenance.json").read_text()
        )
        self.assertTrue(
            any(
                row["reported_commit"] == unreviewed
                and not row["accepted_existing_policy"]
                for row in proof["findings"]
            )
        )


class HistoryProvenanceTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.original = "reviewed first line\nreviewed second line\n"
        self.write("record.txt", self.original)
        self.origin = self.commit("reviewed original span")
        self.write(".gitleaksignore", f"{self.origin}:record.txt:generic-api-key:1\n")
        self.review = self.commit("existing reviewed origin fingerprint")

    def finding(self, commit, start=1, end=2):
        return {
            "ruleId": "generic-api-key",
            "partialFingerprints": {"commitSha": commit},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": "record.txt"},
                        "region": {"startLine": start, "endLine": end},
                    }
                }
            ],
        }

    def resolve(self, head, findings, selection="--all"):
        tree = self.root / "tree"
        scan.tracked_tree(self.repo, head, tree)
        output = self.root / "evidence"
        output.mkdir(exist_ok=True)
        return scan.history_policy_provenance(
            self.repo, tree, findings, output, head, selection
        )

    def assert_blocked(self, head, findings, selection="--all"):
        with self.assertRaises(scan.ScanError):
            self.resolve(head, findings, selection)
        self.assertFalse((self.root / "history-policy.ignore").exists())

    def test_exact_immutable_whole_span_at_shifted_historical_commit(self):
        self.write("record.txt", "inserted\n" + self.original)
        shifted = self.commit("line drift")
        self.write("record.txt", "removed from final head\n")
        head = self.commit("remove historical record")
        self.assertEqual(
            self.resolve(head, [self.finding(shifted, 2, 3)]),
            "/scan/history-policy.ignore",
        )
        proof = json.loads(
            (self.root / "evidence/history-policy-provenance.json").read_text()
        )["findings"][0]
        self.assertEqual(proof["reported_commit"], shifted)
        self.assertEqual(
            proof["existing_fingerprint"], f"{self.origin}:record.txt:generic-api-key:1"
        )
        self.assertEqual(
            proof["span_sha256"], hashlib.sha256(self.original.encode()).hexdigest()
        )
        self.assertIn(
            f"{shifted}:record.txt:generic-api-key:2",
            (self.root / "history-policy.ignore").read_text(),
        )
        self.assertEqual(
            (self.repo / ".gitleaksignore").read_bytes(),
            scan.git(self.repo, "show", self.review + ":.gitleaksignore"),
        )

    def test_changed_second_line_and_mixed_origin_are_not_inherited(self):
        self.write("record.txt", "reviewed first line\nunreviewed changed suffix\n")
        head = self.commit("new suffix")
        self.assert_blocked(head, [self.finding(head)])

    def test_identical_span_hash_reintroduced_by_new_origin_is_not_reviewed(self):
        self.write("record.txt", "removed\n")
        self.commit("remove reviewed lines")
        self.write("record.txt", self.original)
        head = self.commit("unrelated identical introduction")
        self.assert_blocked(head, [self.finding(head)])
        proof = json.loads(
            (self.root / "evidence/history-policy-provenance.json").read_text()
        )["findings"][0]
        self.assertEqual(
            proof["span_sha256"], hashlib.sha256(self.original.encode()).hexdigest()
        )
        self.assertFalse(proof["accepted_existing_policy"])

    def test_new_unreviewed_rule_cannot_inherit_another_rule(self):
        finding = self.finding(self.review)
        finding["ruleId"] = "another-rule"
        self.assert_blocked(self.review, [finding])

    def test_valid_commit_outside_selected_range_is_forged_provenance(self):
        self.assert_blocked(
            self.review, [self.finding(self.origin)], self.origin + ".." + self.review
        )

    def test_nonexistent_commit_and_missing_commit_fail_closed(self):
        for value in ("a" * 40, "HEAD", "0" * 40, None, True):
            with self.subTest(value=value):
                self.assert_blocked(self.review, [self.finding(value)])
        finding = self.finding(self.review)
        del finding["partialFingerprints"]
        self.assert_blocked(self.review, [finding])

    def test_malformed_path_span_rule_or_locations_fail_closed(self):
        changes = [
            ("path", "../record.txt"),
            ("path", "/record.txt"),
            ("path", "./record.txt"),
            ("path", "record.txt\nforged"),
            ("path", "C:record.txt"),
            ("rule", "generic-api-key\nforged"),
            ("start", True),
            ("start", 0),
            ("end", 200),
            ("end", 3),
            ("end", "2"),
            ("locations", []),
        ]
        for field, value in changes:
            finding = self.finding(self.review)
            physical = finding["locations"][0]["physicalLocation"]
            if field == "path":
                physical["artifactLocation"]["uri"] = value
            elif field == "rule":
                finding["ruleId"] = value
            elif field == "locations":
                finding["locations"] = value
            else:
                physical["region"][field + "Line"] = value
            with self.subTest(field=field, value=value):
                self.assert_blocked(self.review, [finding])

    def test_mixed_reviewed_and_unreviewed_inventory_has_no_partial_translation(self):
        finding = self.finding(self.review)
        other = self.finding(self.review)
        other["ruleId"] = "new-unreviewed-rule"
        self.assert_blocked(self.review, [finding, other])

    def test_unknown_blame_and_changed_origin_bytes_fail_closed(self):
        native = scan.git
        for bad_blame in (True, False):

            def altered(repo, *args, **kwargs):
                if bad_blame and "blame" in args:
                    return b"malformed blame\n"
                data = native(repo, *args, **kwargs)
                if not bad_blame and args == ("show", self.origin + ":record.txt"):
                    return data.replace(b"first", b"other")
                return data

            with (
                self.subTest(bad_blame=bad_blame),
                patch.object(scan, "git", side_effect=altered),
            ):
                self.assert_blocked(self.review, [self.finding(self.review)])

    def test_findings_blob_and_cache_bounds_fail_closed(self):
        for attr, value, findings in (
            ("MAX_FINDINGS", 1, [self.finding(self.review)] * 2),
            ("MAX_BLOB_BYTES", 1, [self.finding(self.review)]),
            ("MAX_CACHE_BYTES", 1, [self.finding(self.review)]),
        ):
            with self.subTest(bound=attr), patch.object(scan, attr, value):
                self.assert_blocked(self.review, findings)

    def test_multiple_sarif_runs_are_not_silently_dropped(self):
        report = self.root / "report.sarif"
        report.write_text(
            json.dumps(
                {
                    "version": "2.1.0",
                    "runs": [{"results": []}, {"results": [self.finding(self.review)]}],
                }
            )
        )
        with self.assertRaises(scan.ScanError):
            scan.report_findings(report)

    def test_exported_tree_bytes_must_still_match_the_immutable_source(self):
        tree = self.root / "tree"
        scan.tracked_tree(self.repo, self.review, tree)
        (tree / "record.txt").write_text("unreviewed first line\nunreviewed suffix\n")
        output = self.root / "evidence"
        output.mkdir()
        with self.assertRaisesRegex(scan.ScanError, "Captured tree differs"):
            scan.tree_policy_provenance(
                self.repo, tree, [self.finding(self.review)], output, self.review
            )
        self.assertFalse((self.root / "tree-policy.ignore").exists())


class ProvenanceTests(GitFixture):
    def cleanup_test_containers(self, names):
        for name in names:
            self.assertRegex(name, r"^caseops-secret-[0-9a-f]{32}$")
            present = REAL_RUN(
                ["docker", "inspect", name], capture_output=True, timeout=30
            )
            if present.returncode == 0:
                REAL_RUN(
                    ["docker", "rm", "--force", name],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
            absence = REAL_RUN(
                ["docker", "inspect", name], capture_output=True, timeout=30
            )
            self.assertEqual(absence.returncode, 1)
            self.assertIn(f"no such object: {name}".encode(), absence.stderr.lower())

    def test_new_multiline_suffix_cannot_inherit_reviewed_start_line(self):
        self.write("record.txt", "old first line\nold second line\n")
        origin = self.commit("old span")
        self.write(".gitleaksignore", f"{origin}:record.txt:generic-api-key:1\n")
        self.write("record.txt", "old first line\nnew secret suffix\n")
        head = self.commit("changed suffix")
        tree = self.root / "tree"
        scan.tracked_tree(self.repo, head, tree)
        output = self.root / "evidence"
        output.mkdir()
        finding = {
            "ruleId": "generic-api-key",
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": "record.txt"},
                        "region": {"startLine": 1, "endLine": 2},
                    }
                }
            ],
        }
        with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
            scan.tree_policy_provenance(self.repo, tree, [finding], output, head)
        self.assertFalse((tree.parent / "tree-policy.ignore").exists())

    def test_unrelated_equal_literal_cannot_use_another_commits_reviewed_fingerprint(
        self,
    ):
        self.write("record.txt", "reviewed equal literal\n")
        origin = self.commit("reviewed original")
        self.write("record.txt", "removed\n")
        self.commit("remove original")
        self.write("record.txt", "reviewed equal literal\n")
        self.write(".gitleaksignore", f"{origin}:record.txt:generic-api-key:1\n")
        head = self.commit("new introduction at same path")
        tree = self.root / "tree"
        scan.tracked_tree(self.repo, head, tree)
        output = self.root / "evidence"
        output.mkdir()
        finding = {
            "ruleId": "generic-api-key",
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": "record.txt"},
                        "region": {"startLine": 1, "endLine": 1},
                    }
                }
            ],
        }
        with self.assertRaisesRegex(scan.ScanError, "unreviewed findings"):
            scan.tree_policy_provenance(self.repo, tree, [finding], output, head)

    def test_real_client_timeout_removes_actual_owned_container(self):
        self.write("record.txt", "change\n")
        head = self.commit("change")
        names = []
        acknowledged = []
        timed_out = []
        timeout_errors = []
        self.addCleanup(self.cleanup_test_containers, names)

        def sleeping(args, **kwargs):
            if args[:2] == ["docker", "create"]:
                names.append(args[args.index("--name") + 1])
                index = args.index(scan.GITLEAKS_IMAGE)
                args = args[:index] + [
                    "--entrypoint",
                    "/bin/sh",
                    scan.GITLEAKS_IMAGE,
                    "-c",
                    "sleep 30",
                ]
                result = REAL_RUN(args, **kwargs)
                self.assertEqual(result.returncode, 0)
                acknowledged.append(result.stdout.decode().strip())
                (self.root / "evidence/timeout-create-ack.json").write_text(
                    json.dumps(
                        {
                            "container": names[0],
                            "container_id": acknowledged[0],
                            "network": "none",
                            "image": scan.GITLEAKS_IMAGE,
                        }
                    )
                )
                return result
            if args[:2] == ["docker", "start"]:
                self.assertEqual(
                    args, ["docker", "start", "--attach", acknowledged[0]]
                )
                self.assertGreater(kwargs["timeout"], 0)
                # Cap only the real attached client, within the remaining budget.
                kwargs["timeout"] = min(kwargs["timeout"], 1)
                self.assertLessEqual(kwargs["timeout"], 1)
                try:
                    return REAL_RUN(args, **kwargs)
                except subprocess.TimeoutExpired as exc:
                    timed_out.append(list(args))
                    timeout_errors.append(exc)
                    raise
            return REAL_RUN(args, **kwargs)

        with (
            patch.object(scan.subprocess, "run", side_effect=sleeping),
            self.assertRaises(subprocess.TimeoutExpired) as caught,
        ):
            self.run_scan(head, timeout=10)
        self.assert_incomplete()
        self.assertEqual(len(acknowledged), 1)
        self.assertEqual(
            timed_out, [["docker", "start", "--attach", acknowledged[0]]]
        )
        self.assertEqual(len(timeout_errors), 1)
        self.assertIs(caught.exception, timeout_errors[0])
        self.assertEqual(caught.exception.cmd, timed_out[0])
        self.assertGreater(caught.exception.timeout, 0)
        self.assertLessEqual(caught.exception.timeout, 1)
        cleanup = json.loads((self.root / "evidence/tree-cleanup.json").read_text())
        self.assertTrue(cleanup["create_acknowledged"])
        self.assertEqual(cleanup["container_id"], acknowledged[0])
        self.assertTrue(cleanup["cleanup_confirmed"])
        self.assertEqual(cleanup["scan_error_type"], "TimeoutExpired")
        absence = REAL_RUN(
            ["docker", "inspect", names[0]], capture_output=True, timeout=30
        )
        self.assertNotEqual(absence.returncode, 0)
        self.assertIn(f"no such object: {names[0]}".encode(), absence.stderr.lower())

    def test_real_running_container_is_removed_on_interruption(self):
        self.write("record.txt", "change\n")
        head = self.commit("change")
        names = []
        acknowledged = []
        self.addCleanup(self.cleanup_test_containers, names)

        def interrupted(args, **kwargs):
            if args[:2] == ["docker", "create"]:
                names.append(args[args.index("--name") + 1])
                index = args.index(scan.GITLEAKS_IMAGE)
                launch = args[:index] + [
                    "--entrypoint",
                    "/bin/sh",
                    scan.GITLEAKS_IMAGE,
                    "-c",
                    "sleep 30",
                ]
                result = REAL_RUN(launch, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0)
                acknowledged.append(result.stdout.decode().strip())
                return result
            if args[:2] == ["docker", "start"]:
                self.assertEqual(
                    args, ["docker", "start", "--attach", acknowledged[0]]
                )
                REAL_RUN(
                    ["docker", "start", acknowledged[0]],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                state = REAL_RUN(
                    ["docker", "inspect", "--format", "{{json .State}}", names[0]],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                state = json.loads(state.stdout)
                self.assertTrue(state["Running"])
                self.assertGreater(state["Pid"], 0)
                (self.root / "evidence/interruption-owned-container.json").write_text(
                    json.dumps(
                        {
                            "container": names[0],
                            "container_id": acknowledged[0],
                            "pid": state["Pid"],
                            "running": state["Running"],
                            "started_at": state["StartedAt"],
                            "network": "none",
                            "image": scan.GITLEAKS_IMAGE,
                        }
                    )
                )
                raise KeyboardInterrupt()
            return REAL_RUN(args, **kwargs)

        with (
            patch.object(scan.subprocess, "run", side_effect=interrupted),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.run_scan(head)
        self.assert_incomplete()
        cleanup = json.loads((self.root / "evidence/tree-cleanup.json").read_text())
        self.assertTrue(cleanup["create_acknowledged"])
        self.assertTrue(cleanup["cleanup_confirmed"])
        self.assertEqual(cleanup["scan_error_type"], "KeyboardInterrupt")
        absence = REAL_RUN(
            ["docker", "inspect", names[0]], capture_output=True, timeout=30
        )
        self.assertNotEqual(absence.returncode, 0)
        self.assertIn(f"no such object: {names[0]}".encode(), absence.stderr.lower())

    def test_real_lost_create_ack_is_cleaned_but_never_certified(self):
        self.write("record.txt", "change\n")
        head = self.commit("change")
        names = []
        self.addCleanup(self.cleanup_test_containers, names)
        error = subprocess.TimeoutExpired("docker create", 1)

        def lost(args, **kwargs):
            if args[:2] == ["docker", "create"]:
                names.append(args[args.index("--name") + 1])
                result = REAL_RUN(args, **kwargs)
                self.assertEqual(result.returncode, 0)
                state = REAL_RUN(
                    ["docker", "inspect", "--format", "{{json .State}}", names[0]],
                    capture_output=True,
                    timeout=30,
                    check=True,
                )
                self.assertFalse(json.loads(state.stdout)["Running"])
                (self.root / "evidence/unacknowledged-created-container.json").write_text(
                    json.dumps(
                        {
                            "container": names[0],
                            "container_id": result.stdout.decode().strip(),
                            "running": False,
                            "network": "none",
                            "image": scan.GITLEAKS_IMAGE,
                        }
                    )
                )
                raise error
            self.assertNotEqual(args[:2], ["docker", "start"])
            return REAL_RUN(args, **kwargs)

        with patch.object(scan.subprocess, "run", side_effect=lost):
            with self.assertRaisesRegex(scan.ScanError, "unacknowledged") as caught:
                self.run_scan(head)
        self.assertIs(caught.exception.__context__, error)
        self.assert_incomplete()
        cleanup = json.loads((self.root / "evidence/tree-cleanup.json").read_text())
        self.assertFalse(cleanup["cleanup_confirmed"])
        self.assertFalse(cleanup["create_acknowledged"])
        absence = REAL_RUN(
            ["docker", "inspect", names[0]], capture_output=True, timeout=30
        )
        self.assertEqual(absence.returncode, 1)
        self.assertIn(f"no such object: {names[0]}".encode(), absence.stderr.lower())


class ReviewedHistoryPolicyTests(unittest.TestCase):
    def reviewed_rows(self):
        review = json.loads(
            (ROOT / "docs/security/history-finding-review-2026-10-31.json").read_text()
        )
        rows = review["findings"]
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["fingerprint"] for row in rows}), 10)
        policy = (ROOT / ".gitleaksignore").read_text()
        start = "# 2026-10-31 scheduled all-refs:"
        end = "# End 2026-10-31 review."
        self.assertEqual(policy.count(start), 1)
        self.assertEqual(policy.count(end), 1)
        section = policy.split(start, 1)[1].split(end, 1)[0]
        entries = {
            line for line in section.splitlines() if line and not line.startswith("#")
        }
        self.assertEqual(entries, {row["fingerprint"] for row in rows})
        for row in rows:
            self.assertTrue(bool(re.fullmatch(
                r"[0-9a-f]{40}:[A-Za-z0-9_./-]+:generic-api-key:[1-9][0-9]*",
                row["fingerprint"],
            )))
            for field in ("blob_sha256", "span_sha256"):
                self.assertTrue(bool(re.fullmatch(r"[0-9a-f]{64}", row[field])))
        kinds = [row["kind"] for row in rows]
        self.assertEqual(
            {kind: kinds.count(kind) for kind in set(kinds)},
            {"reviewed_file_checksum": 1, "certifi_bundle_checksum": 1,
             "synthetic_receipt_kind": 1, "apk_public_key_digest": 6,
             "rfc6238_public_test_vector": 1},
        )
        return rows

    def assert_reachable_spans(self, rows, selected_commits):
        blobs = {}
        checked, not_selected = [], []
        for row in rows:
            commit, path, rule, number = row["fingerprint"].split(":")
            if commit not in selected_commits:
                not_selected.append(row["fingerprint"])
                continue
            key = commit + ":" + path
            if key not in blobs:
                blobs[key] = scan.git(ROOT, "show", key)
            with self.subTest(fingerprint=row["fingerprint"]):
                self.assertIsNotNone(re.fullmatch(r"[0-9a-f]{40}", commit))
                self.assertEqual(rule, "generic-api-key")
                blob = blobs[key]
                self.assertLess(len(blob), 200_000)
                self.assertEqual(hashlib.sha256(blob).hexdigest(), row["blob_sha256"])
                span = blob.splitlines(keepends=True)[int(number) - 1]
                self.assertEqual(hashlib.sha256(span).hexdigest(), row["span_sha256"])
                text = blob.decode("utf-8")
                line = span.decode("utf-8").strip()
                if row["kind"] == "apk_public_key_digest":
                    algorithm = row["algorithm"]
                    length = {"SHA-256": 64, "SHA-1": 40, "MD5": 32}[algorithm]
                    self.assertTrue(
                        bool(
                            re.fullmatch(
                                r"V2 Signer: public key "
                                + re.escape(algorithm)
                                + r" digest: [a-f0-9]{"
                                + str(length)
                                + r"}",
                                line,
                            )
                        ),
                        "Reviewed line must remain a public-key fingerprint",
                    )
                    self.assertTrue("const SDK37_REPORT =" in text)
                elif row["kind"] == "reviewed_file_checksum":
                    self.assertTrue("const reviewedFiles =" in text)
                    self.assertTrue("Object.entries(reviewedFiles)" in text)
                    self.assertTrue(
                        bool(re.search(r"""createHash\((['"])sha256\1\)""", text))
                    )
                elif row["kind"] == "certifi_bundle_checksum":
                    self.assertTrue("CERTIFI_BYTES =" in text)
                    self.assertTrue("sha(data) == CERTIFI_BYTES[key]" in text)
                elif row["kind"] == "synthetic_receipt_kind":
                    self.assertTrue("kind: plan.phase ===" in line)
                    self.assertTrue("syntheticDataOnly: true" in text)
                    self.assertTrue("fixture.v1.preparedOnly = true" in text)
                else:
                    self.assertEqual(row["kind"], "rfc6238_public_test_vector")
                    value = re.fullmatch(r"const secret = '([A-Z2-7]+)';", line)
                    self.assertTrue(
                        bool(value), "Expected the reviewed public RFC test vector"
                    )
                    self.assertTrue(
                        base64.b32decode(value.group(1)) == b"1234567890" * 2,
                        "Reviewed seed must be the published RFC6238 vector",
                    )
                    self.assertTrue("assert.equal(totp(secret, 59000)" in text)
                checked.append(row["fingerprint"])
        return {"checked": checked, "not_selected": not_selected}

    def test_october31_review_binds_exact_policy_and_selected_public_spans(self):
        rows = self.reviewed_rows()
        selected = set(scan.git(ROOT, "rev-list", "--all").decode().splitlines())
        self.assertTrue(selected, "Review requires a nonempty all-refs inventory")
        result = self.assert_reachable_spans(rows, selected)
        self.assertEqual(len(result["checked"]) + len(result["not_selected"]), 10)
        print("CASEOPS_HISTORY_REVIEW " + json.dumps({
            "checked": len(result["checked"]),
            "not_selected": len(result["not_selected"]),
            "scope": "actual current all-refs selection; not-selected is not source verification",
        }), flush=True)

    def test_unselected_deleted_branch_origins_need_no_git_blob_retention(self):
        rows = self.reviewed_rows()
        with patch.object(scan, "git", side_effect=AssertionError("Unselected origin lookup")):
            result = self.assert_reachable_spans(rows, set())
        self.assertEqual(result["checked"], [])
        self.assertEqual(len(result["not_selected"]), 10)

    def test_missing_selected_origin_blob_remains_fail_closed(self):
        rows = self.reviewed_rows()
        selected = {rows[0]["fingerprint"].split(":")[0]}
        with patch.object(scan, "git", side_effect=scan.ScanError("Missing selected blob")):
            with self.assertRaisesRegex(scan.ScanError, "Missing selected blob"):
                self.assert_reachable_spans(rows, selected)


if __name__ == "__main__":
    unittest.main()
