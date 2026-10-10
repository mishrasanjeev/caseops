"""Offline native Git fixtures and real digest-pinned Gitleaks canaries."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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
                target = Path(evidence_root) / hashlib.sha256(self.id().encode()).hexdigest()[:20]
                target.mkdir(parents=True, exist_ok=False)
                (target / "identity.json").write_text(json.dumps({"identity": self.id()}))
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
            self.fail(f"Native fixture Git failed: {args[0]} (exit {result.returncode})")
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


class SelectionTests(GitFixture):
    def test_normal_push_exact_changed_inventory(self):
        self.write("record.txt", "changed\n")
        head = self.commit("changed")
        selection, ids = scan.history_selection(self.repo, head, "push", self.push(head))
        self.assertEqual(selection, self.base + ".." + head)
        self.assertEqual(ids, [head])

    def test_side_parents_included_where_old_graph_scan_is_empty(self):
        first, second, head = self.side_merge("temporary credential\n")
        _, ids = scan.history_selection(self.repo, head, "push", self.push(head))
        self.assertEqual(ids, [first, second, head])
        self.assertEqual(
            self.git("rev-list", "--no-merges", "--first-parent", first + "^.." + head), ""
        )

    def test_pull_request_uses_actual_merge_and_both_parent_lineages(self):
        before, side, merged = self.resolution_merge("resolved\n")
        event = {"pull_request": {"base": {"sha": before}, "head": {"sha": side}}}
        _, ids = scan.history_selection(self.repo, merged, "pull_request", event)
        self.assertEqual(set(ids), {side, merged})

    def test_initial_push_and_schedule_inventory(self):
        for event_name, event in [("push", self.push(self.base, "0" * 40)), ("schedule", {})]:
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
            scan.history_selection(self.repo, self.base, "push", self.push(self.base, "a" * 40))

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
        self.write(".gitattributes", "record.txt export-ignore\nrecord.txt filter=unavailable\n")
        head = self.commit("attributes")
        self.write("record.txt", "dirty not candidate\n")
        self.write("untracked.txt", "untracked not candidate\n")
        target = self.root / "snapshot"
        entries = scan.tracked_tree(self.repo, head, target)
        self.assertEqual((target / "record.txt").read_bytes(), b"original\n")
        self.assertNotIn("untracked.txt", [item["path"] for item in entries])
        self.assertGreater(sum(item["bytes"] for item in entries), 0)
        for policy in (".gitleaks.toml", ".gitleaksignore"):
            self.assertEqual((target / policy).read_bytes(), (self.repo / policy).read_bytes())

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
        for raw in (b"", b"not terminated", b"broken\0", b"100644 blob invalid\tfile\0"):
            with patch.object(scan, "git", return_value=raw), self.assertRaises(scan.ScanError):
                scan.tracked_tree(self.repo, self.base, self.root / "snapshot")

    def test_submodule_and_unsafe_paths_fail_closed(self):
        for mode, kind, name in [
            ("160000", "commit", "submodule"),
            ("100644", "blob", "../escape"),
            ("100644", "blob", "/absolute"),
            ("100644", "blob", ".git/config"),
        ]:
            raw = f"{mode} {kind} {'a' * 40}\t{name}\0".encode()
            with patch.object(scan, "git", return_value=raw), self.assertRaises(scan.ScanError):
                scan.tracked_tree(self.repo, self.base, self.root / "snapshot")


class ReceiptTests(unittest.TestCase):
    def test_positive_receipts(self):
        output = b"INF 3 commits scanned.\nINF scanned ~24 bytes (24 bytes) in 1ms\n"
        self.assertEqual(
            scan.scanner_receipt(output, history=True), {"scanned_bytes": 24, "scanned_commits": 3}
        )

    def test_exact_byte_integer_survives_human_readable_large_units(self):
        output = b"INF 3 commits scanned.\nINF scanned ~1234567 bytes (1.18 MB) in 1ms\n"
        self.assertEqual(scan.scanner_receipt(output, history=True)["scanned_bytes"], 1234567)

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


class FailureTests(GitFixture):
    def setUp(self):
        super().setUp()
        self.write("record.txt", "changed\n")
        self.head = self.commit("changed")

    def fake_run(self, args, **kwargs):
        if args[0] != "docker":
            return REAL_RUN(args, **kwargs)
        if args[1] == "run":
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
            if args[:2] == ["docker", "run"]:
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
            if args[:2] == ["docker", "run"]:
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

                def interrupted(args, _error=error, _cleanup_calls=cleanup_calls, **kwargs):
                    if args[:2] == ["docker", "run"]:
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
                self.assertFalse((self.root / type(error).__name__ / "completion.json").exists())

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
            if args[:2] == ["docker", "run"]:
                mount = args[args.index("--mount", args.index("--mount") + 1) + 1]
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
                return subprocess.CompletedProcess(args, 1, b"", b"Cannot connect to Docker daemon")
            return self.fake_run(args, **kwargs)

        with (
            patch.object(scan.subprocess, "run", side_effect=unavailable),
            self.assertRaises(scan.ScanError),
        ):
            self.run_scan(self.head)
        self.assert_incomplete()


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
            [row.get("kind") for row in self.progress() if row["event"] == "boundary_completed"],
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

    def test_real_existing_commit_fingerprint_keeps_exact_unchanged_tree_provenance(self):
        origin, _ = self.reviewed_fixture()
        self.write("record.txt", "# harmless inserted line\n" + self.canary())
        head = self.commit("shift unchanged reviewed line")
        result = self.run_scan(head)
        self.assertGreater(result["boundaries"]["tree"]["existing_policy_translations"], 0)
        provenance = json.loads((self.root / "evidence/tree-policy-provenance.json").read_text())
        self.assertTrue(all(row["accepted_existing_policy"] for row in provenance["findings"]))
        self.assertTrue(
            all(
                row["existing_fingerprint"].startswith(origin + ":")
                for row in provenance["findings"]
            )
        )
        self.assertTrue((self.root / "evidence/tree-initial.sarif").exists())

    def test_real_future_secret_same_path_line_is_not_covered_by_historical_fingerprint(self):
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
        provenance = json.loads((self.root / "evidence/tree-policy-provenance.json").read_text())
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
        provenance = json.loads((self.root / "evidence/tree-policy-provenance.json").read_text())
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
        provenance = json.loads((self.root / "evidence/tree-policy-provenance.json").read_text())
        self.assertEqual(provenance["accepted_existing_policy"], 0)
        self.assertEqual(len(provenance["findings"]), 1)
        finding = provenance["findings"][0]
        self.assertEqual((finding["start_line"], finding["end_line"]), (1, 2))
        self.assertNotEqual(finding["span_sha256"], hashlib.sha256(original.encode()).hexdigest())
        self.assertFalse((self.root / "tree-policy.ignore").exists())
        self.assertFalse((self.root / "evidence/history.sarif").exists())
        receipt = json.loads((self.root / "evidence/tree-receipt.json").read_text())
        self.assertEqual(receipt["exit_code"], 2)
        self.assertTrue(receipt["cleanup_confirmed"])


class ProvenanceTests(GitFixture):
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

    def test_unrelated_equal_literal_cannot_use_another_commits_reviewed_fingerprint(self):
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

        def sleeping(args, **kwargs):
            if args[:2] == ["docker", "run"]:
                names.append(args[args.index("--name") + 1])
                index = args.index(scan.GITLEAKS_IMAGE)
                args = args[:index] + [
                    "--entrypoint",
                    "/bin/sh",
                    scan.GITLEAKS_IMAGE,
                    "-c",
                    "sleep 30",
                ]
            return REAL_RUN(args, **kwargs)

        with (
            patch.object(scan.subprocess, "run", side_effect=sleeping),
            self.assertRaises(subprocess.TimeoutExpired),
        ):
            self.run_scan(head, timeout=1)
        self.assert_incomplete()
        absence = REAL_RUN(["docker", "inspect", names[0]], capture_output=True, timeout=30)
        self.assertNotEqual(absence.returncode, 0)
        self.assertIn(f"no such object: {names[0]}".encode(), absence.stderr.lower())

    def test_real_running_container_is_removed_on_interruption(self):
        self.write("record.txt", "change\n")
        head = self.commit("change")
        names = []

        def interrupted(args, **kwargs):
            if args[:2] == ["docker", "run"]:
                names.append(args[args.index("--name") + 1])
                index = args.index(scan.GITLEAKS_IMAGE)
                launch = args[:index] + [
                    "--detach",
                    "--entrypoint",
                    "/bin/sh",
                    scan.GITLEAKS_IMAGE,
                    "-c",
                    "sleep 30",
                ]
                result = REAL_RUN(launch, capture_output=True, timeout=30)
                self.assertEqual(result.returncode, 0)
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
        absence = REAL_RUN(["docker", "inspect", names[0]], capture_output=True, timeout=30)
        self.assertNotEqual(absence.returncode, 0)
        self.assertIn(f"no such object: {names[0]}".encode(), absence.stderr.lower())


if __name__ == "__main__":
    unittest.main()
