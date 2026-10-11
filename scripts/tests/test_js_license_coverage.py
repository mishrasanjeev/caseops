"""Offline coverage, identity, SPDX-policy and standard Security wiring checks."""
from __future__ import annotations

import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("js_license_coverage", ROOT / "scripts/check_js_license_coverage.py")
assert SPEC is not None and SPEC.loader is not None
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


def identities(suite):
    result = []
    for item in suite:
        result.extend(identities(item) if isinstance(item, unittest.TestSuite) else [item.id()])
    return result


def workflow_contract(text):
    block = text.split("  license-allowlist:\n", 1)[1].split("  openapi-client-drift:", 1)[0]
    block = "\n".join(line for line in block.splitlines() if not line.lstrip().startswith("#"))
    required = (
        "license-checker@25.0.1", "node-version: \"22\"", "test_js_license_coverage.py -v",
        "scripts/check_js_license_coverage.py inventory", "scripts/check_js_license_coverage.py verify",
        'license-checker --json --packages "$packages"', '--onlyAllow "$allowlist"',
        'CASEOPS_LICENSE_CHECKER_PACKAGE=', 'if: always()', 'if-no-files-found: error',
        '${{ runner.temp }}/js-license-evidence',
        'npm install --prefix "$audit"', 'export PATH="$audit/node_modules/.bin:$PATH"',
        'output="$CASEOPS_JS_LICENSE_EVIDENCE/host"',
        'name: Audit actual pruned Linux x64 musl production licenses',
        'if: ${{ always() && !cancelled() }}', '--platform linux/amd64 --file apps/web/Dockerfile',
        '--target prod-deps', 'image="caseops-js-license-musl:$GITHUB_SHA"',
        'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', 'docker image inspect --format',
        'docker run --rm -i --user 0 --workdir /app', '"$image_id" sh -eu',
        'dst=/license-guard/check_js_license_coverage.py,readonly', 'dst=/evidence',
        'apk add --no-cache python3', 'npm install --prefix /license-audit',
        '--ignore-scripts --no-audit --no-fund --save-exact license-checker@25.0.1',
        '--require-platform linux-x64-musl --require-pruned-tree',
        'license-checker --start /app --json --packages "$packages"',
        'audit_status=${PIPESTATUS[0]}', 'exit "$audit_status"',
        'name: js-license-report\n          path: ${{ runner.temp }}/js-license-evidence\n',
    )
    if any(marker not in block for marker in required) or any(marker in block for marker in ("--production", "--excludePackages", "--excludePrivatePackages", "continue-on-error", "npx", "npm install --prefix /app", "|| true")):
        raise ValueError("License coverage or policy wiring missing")


class LicenseFixture(unittest.TestCase):
    def setUp(self):
        temporary = ROOT / ".tmp/license-unit-fixtures"
        temporary.mkdir(parents=True, exist_ok=True)
        storage = tempfile.TemporaryDirectory(dir=temporary)
        self.addCleanup(storage.cleanup)
        self.root = Path(storage.name)
        self.manifest = {"name": "caseops", "private": True, "workspaces": ["apps/web"]}
        self.web = {"name": "@caseops/web", "private": True, "dependencies": {"a": "1.0.0"}}
        self.packages = {"": {"name": "caseops", "workspaces": ["apps/web"]},
            "apps/web": {"name": "@caseops/web", "dependencies": {"a": "1.0.0"}},
            "node_modules/a": {"version": "1.0.0", "license": "MIT"}}
        self.add_package("a", "1.0.0", "MIT")
        self.save()
        network = patch.object(socket.socket, "connect", side_effect=AssertionError("Offline license test attempted network"))
        network.start()
        self.addCleanup(network.stop)

    def save(self):
        self.write("package.json", self.manifest)
        self.write("apps/web/package.json", self.web)
        self.write("package-lock.json", {"lockfileVersion": 3, "packages": self.packages})

    def write(self, path, value):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")

    def add_package(self, name, version, license_value, path=None):
        path = path or "node_modules/" + name
        metadata = self.packages.get(path, {})
        edges = {key: metadata[key] for key in ("dependencies", "optionalDependencies", "peerDependencies", "peerDependenciesMeta") if key in metadata}
        self.write(path + "/package.json", {"name": name, "version": version, "license": license_value, **edges})

    def prepared(self):
        self.save()
        return coverage.inventory(self.root)

    def report(self, license_value="MIT"):
        return {"a@1.0.0": {"licenses": license_value, "path": str(self.root / "node_modules/a")}}

    def scanner(self):
        path = os.environ.get("CASEOPS_LICENSE_CHECKER_PACKAGE")
        self.assertIsNotNone(path, "Set pinned license-checker package metadata; tests must not silently skip")
        return Path(path)

    def verify(self, report=None, prepared=None):
        return coverage.verify(self.root, prepared or self.prepared(), self.report() if report is None else report, self.scanner())


class InventoryTests(LicenseFixture):
    def test_private_workspace_production_inventory_is_nonempty(self):
        self.assertEqual(set(self.prepared()["expected"]), {"a@1.0.0"})

    def test_missing_installed_package_fails(self):
        (self.root / "node_modules/a/package.json").unlink()
        with self.assertRaises(OSError):
            self.prepared()

    def test_installed_version_must_match_lock(self):
        self.add_package("a", "2.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "Installed identity"):
            self.prepared()

    def test_installed_license_must_match_lock(self):
        self.add_package("a", "1.0.0", "OFL-1.1")
        with self.assertRaisesRegex(ValueError, "Installed license"):
            self.prepared()

    def test_shared_dev_optional_dependency_is_not_excluded(self):
        self.packages["node_modules/a"]["devOptional"] = True
        self.assertEqual(len(self.prepared()["expected"]), 1)

    def test_runtime_dependency_cannot_be_hidden_by_dev_flag(self):
        self.packages["node_modules/a"]["dev"] = True
        with self.assertRaisesRegex(ValueError, "misclassified"):
            self.prepared()

    def test_hoisted_transitive_and_nested_versions_are_retained(self):
        self.packages["node_modules/a"]["dependencies"] = {"b": "2.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        self.packages["node_modules/b"] = {"version": "2.0.0", "license": "MIT"}
        self.packages["node_modules/a/node_modules/b"] = {"version": "1.0.0", "license": "MIT"}
        self.add_package("b", "2.0.0", "MIT")
        self.add_package("b", "1.0.0", "MIT", "node_modules/a/node_modules/b")
        self.assertEqual(set(self.prepared()["expected"]), {"a@1.0.0", "b@1.0.0", "b@2.0.0"})

    def test_scoped_package_identity(self):
        self.web["dependencies"] = {"@scope/a": "1.0.0"}
        self.packages["apps/web"]["dependencies"] = self.web["dependencies"].copy()
        self.packages["node_modules/@scope/a"] = self.packages.pop("node_modules/a")
        self.add_package("@scope/a", "1.0.0", "MIT")
        self.assertEqual(set(self.prepared()["expected"]), {"@scope/a@1.0.0"})

    def test_optional_foreign_platform_has_explicit_exclusion(self):
        self.packages["node_modules/native"] = {"version": "1.0.0", "optional": True, "os": ["linux"], "cpu": ["arm64"]}
        self.save()
        result = coverage.inventory(self.root, {"os": "win32", "cpu": "x64", "libc": "unknown"})
        self.assertEqual(len(result["platform_exclusions"]), 1)
        self.assertEqual(set(result["expected"]), {"a@1.0.0"})

    def test_compatible_optional_package_may_not_disappear(self):
        self.packages["node_modules/a"]["optional"] = True
        (self.root / "node_modules/a/package.json").unlink()
        with self.assertRaises(OSError):
            self.prepared()

    def test_required_foreign_platform_is_not_ignored(self):
        self.packages["node_modules/a"]["os"] = ["foreign-os"]
        with self.assertRaisesRegex(ValueError, "Required production package incompatible"):
            self.prepared()

    def test_optional_foreign_edge_does_not_claim_required_installed_coverage(self):
        self.packages["node_modules/a"]["optionalDependencies"] = {"native": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        self.packages["node_modules/native"] = {"version": "1.0.0", "optional": True, "dev": True, "os": ["foreign-os"]}
        result = self.prepared()
        self.assertEqual(set(result["expected"]), {"a@1.0.0"})
        self.assertEqual(result["platform_exclusions"][0]["parent"], "node_modules/a")

    def test_missing_transitive_lock_edge_fails(self):
        self.packages["node_modules/a"]["dependencies"] = {"absent": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "Dependency absent"):
            self.prepared()

    def test_installed_transitive_edge_cannot_be_hidden_in_lock(self):
        self.write("node_modules/a/package.json", {"name": "a", "version": "1.0.0", "license": "MIT", "dependencies": {"hidden": "1.0.0"}})
        with self.assertRaisesRegex(ValueError, "Manifest dependency"):
            self.prepared()

    def test_required_peer_cannot_be_hidden_by_dev_flag(self):
        self.packages["node_modules/a"]["peerDependencies"] = {"peer": "1.0.0"}
        self.packages["node_modules/peer"] = {"version": "1.0.0", "license": "MIT", "dev": True}
        self.add_package("a", "1.0.0", "MIT")
        self.add_package("peer", "1.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "misclassified"):
            self.prepared()

    def test_missing_required_peer_fails(self):
        self.packages["node_modules/a"]["peerDependencies"] = {"peer": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "Dependency absent"):
            self.prepared()

    def test_optional_uninstalled_peer_is_not_a_shipped_package(self):
        self.packages["node_modules/a"].update({"peerDependencies": {"peer": "1.0.0"}, "peerDependenciesMeta": {"peer": {"optional": True}}})
        self.add_package("a", "1.0.0", "MIT")
        self.assertEqual(set(self.prepared()["expected"]), {"a@1.0.0"})

    def test_lock_cannot_silently_change_peer_optionality(self):
        self.packages["node_modules/a"]["peerDependencies"] = {"peer": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        self.packages["node_modules/a"]["peerDependenciesMeta"] = {"peer": {"optional": True}}
        with self.assertRaisesRegex(ValueError, "Manifest dependency"):
            self.prepared()

    def test_glob_workspace_is_not_silently_unscanned(self):
        self.manifest["workspaces"] = ["apps/*"]
        with self.assertRaisesRegex(ValueError, "explicit contained"):
            self.prepared()

    def test_windows_workspace_escape_fails(self):
        self.manifest["workspaces"] = ["..\\foreign"]
        with self.assertRaisesRegex(ValueError, "explicit contained"):
            self.prepared()

    def test_unsafe_lock_package_path_fails(self):
        self.packages["node_modules/../../foreign"] = {"version": "1.0.0"}
        with self.assertRaisesRegex(ValueError, "Unsafe lock package path"):
            self.prepared()

    def test_workspace_dependency_drift_fails(self):
        self.web["dependencies"]["b"] = "1.0.0"
        with self.assertRaisesRegex(ValueError, "Manifest dependency"):
            self.prepared()

    def test_empty_inventory_fails(self):
        self.web["dependencies"] = {}
        self.packages["apps/web"]["dependencies"] = {}
        del self.packages["node_modules/a"]
        with self.assertRaisesRegex(ValueError, "inventory is empty"):
            self.prepared()


class ReportTests(LicenseFixture):
    def test_complete_allowed_report_passes(self):
        result = self.verify()
        self.assertTrue(result["coverage_exact"])
        self.assertEqual(result["inventory_host"], coverage.host_platform())
        self.assertIn("other target-platform install trees are not certified", result["scope"])
        self.assertEqual(result["denied"], [])

    def test_empty_exit_zero_report_fails(self):
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.verify({})

    def test_partial_report_fails(self):
        self.packages["node_modules/b"] = {"version": "1.0.0", "license": "MIT"}
        self.add_package("b", "1.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "missing=.*b@1.0.0"):
            self.verify()

    def test_unexpected_report_identity_fails(self):
        report = self.report()
        report["extra@1.0.0"] = report["a@1.0.0"].copy()
        with self.assertRaisesRegex(ValueError, "extra=.*extra@1.0.0"):
            self.verify(report)

    def test_report_wrong_version_fails(self):
        with self.assertRaisesRegex(ValueError, "coverage mismatch"):
            self.verify({"a@2.0.0": self.report()["a@1.0.0"]})

    def test_report_cannot_substitute_another_package_path(self):
        report = self.report()
        report["a@1.0.0"]["path"] = str(self.root / "node_modules/other")
        with self.assertRaisesRegex(ValueError, "Report path"):
            self.verify(report)

    def test_malformed_license_array_fails(self):
        report = self.report()
        report["a@1.0.0"]["licenses"] = ["MIT"]
        with self.assertRaisesRegex(ValueError, "malformed license"):
            self.verify(report)

    def test_report_cannot_relabel_unsupported_installed_license(self):
        self.packages["node_modules/a"]["license"] = "OFL-1.1"
        self.add_package("a", "1.0.0", "OFL-1.1")
        with self.assertRaisesRegex(ValueError, "Reported license differs"):
            self.verify()

    def test_prepared_lock_staleness_fails(self):
        prepared = self.prepared()
        self.packages["node_modules/a"]["optional"] = True
        self.save()
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            self.verify(prepared=prepared)

    def test_installed_bytes_staleness_fails(self):
        prepared = self.prepared()
        self.write("node_modules/a/package.json", {"name": "a", "version": "1.0.0", "license": "MIT", "description": "new bytes"})
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            self.verify(prepared=prepared)

    def test_duplicate_report_keys_fail(self):
        target = self.root / "report.json"
        target.write_text('{"a@1.0.0":{},"a@1.0.0":{}}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            coverage.read_json(target)

    def test_unsupported_license_is_reported_not_omitted(self):
        self.packages["node_modules/a"]["license"] = "OFL-1.1"
        self.add_package("a", "1.0.0", "OFL-1.1")
        self.assertEqual(self.verify(self.report("OFL-1.1"))["denied"], [{"identity": "a@1.0.0", "license": "OFL-1.1"}])


class ReviewCounterexampleTests(LicenseFixture):
    def excluded_target(self, field):
        self.packages["node_modules/a"][field] = {"native": "1.0.0"}
        self.packages["node_modules/native"] = {"version": "1.0.0", "optional": True, "os": ["foreign-os"]}
        self.add_package("a", "1.0.0", "MIT")

    def test_required_dependency_cannot_resolve_to_excluded_optional_target(self):
        self.excluded_target("dependencies")
        with self.assertRaisesRegex(ValueError, "Required dependency target"):
            self.prepared()

    def test_required_peer_cannot_resolve_to_excluded_optional_target(self):
        self.excluded_target("peerDependencies")
        with self.assertRaisesRegex(ValueError, "Required dependency target"):
            self.prepared()

    def duplicate_without_license(self, value, present):
        path = "node_modules/b/node_modules/a"
        self.packages[path] = {"version": "1.0.0"}
        package = {"name": "a", "version": "1.0.0"}
        if present:
            package["license"] = value
        self.write(path + "/package.json", package)
        (self.root / path / "LICENSE").write_text("GPL-3.0-or-later", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Declared installed license"):
            self.verify()

    def test_duplicate_copy_without_declared_license_cannot_borrow_mit(self):
        self.duplicate_without_license(None, False)

    def test_duplicate_copy_with_empty_license_cannot_borrow_mit(self):
        self.duplicate_without_license("", True)

    def malformed_receipt(self, path, value):
        self.save()
        self.write(path, value)
        output = self.root / "receipt"
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            result = coverage.main(["inventory", "--root", str(self.root), "--output", str(output)])
        self.assertEqual(result, 1)
        failure = coverage.read_json(output / "inventory-failure.json")
        self.assertEqual(failure["status"], "blocked")
        self.assertTrue(failure["error"])

    def test_root_array_rejection_retains_structured_receipt(self):
        self.malformed_receipt("package.json", [])

    def test_lock_array_rejection_retains_structured_receipt(self):
        self.malformed_receipt("package-lock.json", [])

    def test_workspace_array_rejection_retains_structured_receipt(self):
        self.malformed_receipt("apps/web/package.json", [])

    def test_installed_array_rejection_retains_structured_receipt(self):
        self.malformed_receipt("node_modules/a/package.json", [])

    def test_lock_entry_array_rejection_retains_structured_receipt(self):
        self.packages["node_modules/a"] = []
        self.malformed_receipt("package-lock.json", {"lockfileVersion": 3, "packages": self.packages})

    def test_falsey_dependency_mapping_rejection_retains_receipt(self):
        self.packages["node_modules/a"]["dependencies"] = []
        self.add_package("a", "1.0.0", "MIT")
        self.malformed_receipt("package-lock.json", {"lockfileVersion": 3, "packages": self.packages})

    def test_falsey_optional_flag_rejection_retains_receipt(self):
        self.packages["node_modules/a"]["optional"] = 0
        self.malformed_receipt("package-lock.json", {"lockfileVersion": 3, "packages": self.packages})

    def platform_receipt(self, value):
        self.packages["node_modules/a"]["os"] = value
        self.malformed_receipt("package-lock.json", {"lockfileVersion": 3, "packages": self.packages})

    def test_empty_mapping_platform_rejection_retains_receipt(self):
        self.platform_receipt({})

    def test_empty_string_platform_rejection_retains_receipt(self):
        self.platform_receipt("")

    def test_false_boolean_platform_rejection_retains_receipt(self):
        self.platform_receipt(False)

    def test_zero_platform_rejection_retains_receipt(self):
        self.platform_receipt(0)


class PolicyTests(LicenseFixture):
    def test_all_eight_reported_r11_musl_licenses_remain_blocked(self):
        reported = {
            "@fontsource/atkinson-hyperlegible@5.2.8": "OFL-1.1",
            "@fontsource/jetbrains-mono@5.2.8": "OFL-1.1",
            "@fontsource/libre-caslon-text@5.2.7": "OFL-1.1",
            "@img/sharp-libvips-linux-x64@1.3.4": "LGPL-3.0-or-later",
            "@img/sharp-libvips-linuxmusl-x64@1.3.4": "LGPL-3.0-or-later",
            "@img/sharp-wasm32@0.35.5": "Apache-2.0 AND LGPL-3.0-or-later AND MIT",
            "nodemailer@10.0.13": "MIT-0",
            "pako@1.0.11": "(MIT AND Zlib)",
        }
        self.assertEqual(coverage.check_licenses(list(reported.values()), self.scanner()), [False] * 8)

    def test_or_choice_is_approved_without_approving_gpl(self):
        self.assertEqual(coverage.check_licenses(["(MIT OR GPL-3.0-or-later)", "GPL-3.0-or-later"], self.scanner()), [True, False])

    def test_and_requires_all_terms_not_substring_allowance(self):
        self.assertEqual(coverage.check_licenses(["Apache-2.0 AND LGPL-3.0-or-later", "(MIT AND Zlib)"], self.scanner()), [False, False])

    def test_mit_zero_is_not_mit_by_substring(self):
        self.assertEqual(coverage.check_licenses(["MIT-0", "MIT"], self.scanner()), [False, True])

    def test_unknown_and_malformed_fail_closed(self):
        self.assertEqual(coverage.check_licenses(["UNKNOWN", "UNLICENSED", "MIT OR", "MIT*"], self.scanner()), [False, False, False, False])

    def test_existing_apache_alias_retained(self):
        self.assertEqual(coverage.check_licenses(["Apache 2.0"], self.scanner()), [True])

    def test_unpinned_parser_source_is_rejected(self):
        target = self.root / "scanner/package.json"
        self.write("scanner/package.json", {"name": "license-checker", "version": "0.0.0"})
        with self.assertRaisesRegex(ValueError, "Pinned offline SPDX evaluator failed"):
            coverage.check_licenses(["MIT"], target)


class MuslAndPrunedTests(LicenseFixture):
    def linux_host(self, libc, stdout="", stderr="", status=0):
        with patch.object(coverage.sys, "platform", "linux"), patch.object(coverage.platform, "machine", return_value="x86_64"), \
                patch.object(coverage.platform, "libc_ver", return_value=(libc, "")), \
                patch.object(coverage.subprocess, "run", return_value=subprocess.CompletedProcess(["ldd", "--version"], status, stdout, stderr)) as probe:
            result = coverage.host_platform()
            probe.assert_called_once_with(["ldd", "--version"], capture_output=True, text=True, timeout=3, check=False)
            return result

    def test_musl_stderr_banner_exit_one_is_positive_detection(self):
        self.assertEqual(self.linux_host("", stderr="musl libc (x86_64)\nVersion 1.2.5\n", status=1), {"os": "linux", "cpu": "x64", "libc": "musl"})

    def test_musl_stdout_banner_is_positive_detection(self):
        self.assertEqual(self.linux_host("", stdout="musl libc (x86_64)\nVersion 1.2.5\n")["libc"], "musl")

    def test_unknown_linux_libc_is_not_accepted(self):
        with self.assertRaisesRegex(ValueError, "positively identify Linux libc"):
            self.linux_host("", stderr="ldd failed", status=1)

    def test_known_glibc_does_not_claim_musl(self):
        self.assertEqual(self.linux_host("glibc", stdout="ldd (GNU libc) 2.39\n")["libc"], "glibc")

    def test_unknown_linux_missing_ldd_fails_closed(self):
        with patch.object(coverage.sys, "platform", "linux"), patch.object(coverage.platform, "libc_ver", return_value=("", "")), \
                patch.object(coverage.subprocess, "run", side_effect=FileNotFoundError("offline missing ldd")):
            with self.assertRaisesRegex(ValueError, "positively identify Linux libc"):
                coverage.host_platform()

    def test_unknown_linux_ldd_timeout_fails_closed(self):
        with patch.object(coverage.sys, "platform", "linux"), patch.object(coverage.platform, "libc_ver", return_value=("", "")), \
                patch.object(coverage.subprocess, "run", side_effect=subprocess.TimeoutExpired("ldd", 3)):
            with self.assertRaisesRegex(ValueError, "positively identify Linux libc"):
                coverage.host_platform()

    def test_pruned_tree_exact_physical_inventory_passes(self):
        self.save()
        result = coverage.inventory(self.root, require_pruned=True)
        self.assertTrue(result["pruned_tree"])
        self.assertEqual(result["physical_package_paths"], ["node_modules/a"])
        verified = coverage.verify(self.root, result, self.report(), self.scanner(), require_pruned=True)
        self.assertTrue(verified["pruned_tree"])
        self.assertEqual(verified["installed_path_count"], 1)

    def test_pruned_tree_cannot_hide_dev_only_installed_package(self):
        self.packages["node_modules/dev"] = {"version": "1.0.0", "license": "MIT", "dev": True}
        self.add_package("dev", "1.0.0", "MIT")
        self.save()
        with self.assertRaisesRegex(ValueError, "Pruned physical package coverage mismatch"):
            coverage.inventory(self.root, require_pruned=True)

    def test_pruned_tree_cannot_hide_unlocked_physical_package(self):
        self.add_package("unknown", "1.0.0", "MIT")
        self.save()
        with self.assertRaisesRegex(ValueError, "Pruned physical package coverage mismatch"):
            coverage.inventory(self.root, require_pruned=True)

    def test_pruned_verification_flag_cannot_be_dropped(self):
        self.save()
        prepared = coverage.inventory(self.root, require_pruned=True)
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            coverage.verify(self.root, prepared, self.report(), self.scanner())

    def test_platform_cli_rejects_glibc_with_retained_receipt(self):
        self.save()
        output = self.root / "platform-failure"
        with patch.object(coverage, "host_platform", return_value={"os": "linux", "cpu": "x64", "libc": "glibc"}), \
                contextlib.redirect_stderr(io.StringIO()):
            result = coverage.main(["inventory", "--root", str(self.root), "--require-platform", "linux-x64-musl", "--output", str(output)])
        self.assertEqual(result, 1)
        self.assertIn("linux-x64-musl", coverage.read_json(output / "inventory-failure.json")["error"])

    def test_platform_cli_requires_positive_musl_and_pruned_receipt(self):
        self.save()
        output = self.root / "platform-positive"
        with patch.object(coverage, "host_platform", return_value={"os": "linux", "cpu": "x64", "libc": "musl"}), \
                contextlib.redirect_stdout(io.StringIO()):
            result = coverage.main(["inventory", "--root", str(self.root), "--require-platform", "linux-x64-musl", "--require-pruned-tree", "--output", str(output)])
        self.assertEqual(result, 0)
        self.assertTrue(coverage.read_json(output / "inventory.json")["pruned_tree"])


class PhysicalOptionalCoverageTests(LicenseFixture):
    def setUp(self):
        super().setUp()
        host = patch.object(coverage, "host_platform", return_value={"os": "linux", "cpu": "x64", "libc": "musl"})
        host.start()
        self.addCleanup(host.stop)

    def foreign_optional(self, field="os", present=True, license_value="MIT"):
        self.packages["node_modules/a"]["optionalDependencies"] = {"native": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        self.packages["node_modules/native"] = {"version": "1.0.0", "license": license_value,
            "optional": True, field: [{"os": "win32", "cpu": "arm64", "libc": "glibc"}[field]]}
        if present:
            self.add_package("native", "1.0.0", license_value)
        self.save()

    def foreign_report(self, license_value="MIT"):
        return {**self.report(), "native@1.0.0": {"licenses": license_value, "path": str(self.root / "node_modules/native")}}

    def included_foreign(self, field):
        self.foreign_optional(field)
        prepared = self.prepared()
        self.assertEqual(set(prepared["expected"]), {"a@1.0.0", "native@1.0.0"})
        self.assertEqual(prepared["expected"]["native@1.0.0"][0]["path"], "node_modules/native")
        self.assertEqual(prepared["platform_exclusions"], [])

    def test_present_optional_foreign_os_is_in_inventory(self):
        self.included_foreign("os")

    def test_present_optional_foreign_cpu_is_in_inventory(self):
        self.included_foreign("cpu")

    def test_present_optional_foreign_libc_is_in_inventory(self):
        self.included_foreign("libc")

    def test_present_foreign_optional_cannot_disappear_from_report(self):
        self.foreign_optional()
        with self.assertRaisesRegex(ValueError, "coverage mismatch: missing=.*native@1.0.0"):
            self.verify()

    def test_present_foreign_optional_denied_license_is_not_hidden(self):
        self.foreign_optional(license_value="OFL-1.1")
        self.assertEqual(self.verify(self.foreign_report("OFL-1.1"))["denied"],
            [{"identity": "native@1.0.0", "license": "OFL-1.1"}])

    def test_present_foreign_optional_pruned_tree_is_fully_licensed(self):
        self.foreign_optional()
        prepared = coverage.inventory(self.root, require_pruned=True)
        self.assertEqual(prepared["physical_package_paths"], ["node_modules/a", "node_modules/native"])
        verified = coverage.verify(self.root, prepared, self.foreign_report(), self.scanner(), require_pruned=True)
        self.assertEqual(verified["installed_path_count"], 2)
        self.assertTrue(verified["coverage_exact"])
        self.assertEqual(verified["denied"], [])

    def test_absent_foreign_optional_keeps_explicit_exclusion(self):
        self.foreign_optional(present=False)
        prepared = coverage.inventory(self.root, require_pruned=True)
        self.assertEqual(set(prepared["expected"]), {"a@1.0.0"})
        self.assertEqual(prepared["physical_package_paths"], ["node_modules/a"])
        self.assertTrue(prepared["platform_exclusions"])
        self.assertEqual({item["path"] for item in prepared["platform_exclusions"]}, {"node_modules/native"})
        verified = coverage.verify(self.root, prepared, self.report(), self.scanner(), require_pruned=True)
        self.assertEqual(verified["installed_path_count"], 1)
        self.assertEqual(verified["denied"], [])

    def required_present(self, field):
        self.foreign_optional()
        del self.packages["node_modules/a"]["optionalDependencies"]
        self.packages["node_modules/a"][field] = {"native": "1.0.0"}
        self.add_package("a", "1.0.0", "MIT")
        with self.assertRaisesRegex(ValueError, "Required dependency target"):
            self.prepared()

    def test_present_incompatible_optional_target_is_not_a_required_dependency(self):
        self.required_present("dependencies")

    def test_present_incompatible_optional_target_is_not_a_required_peer(self):
        self.required_present("peerDependencies")

    def test_present_foreign_optional_without_manifest_is_not_excluded(self):
        self.foreign_optional()
        (self.root / "node_modules/native/package.json").unlink()
        with self.assertRaises(OSError):
            self.prepared()

    def test_present_foreign_optional_without_license_is_not_excluded(self):
        self.foreign_optional()
        self.write("node_modules/native/package.json", {"name": "native", "version": "1.0.0"})
        with self.assertRaisesRegex(ValueError, "Declared installed license"):
            self.prepared()

    def test_all_present_foreign_optional_duplicate_copies_are_covered(self):
        self.foreign_optional("cpu")
        path = "node_modules/a/node_modules/native"
        self.packages[path] = self.packages["node_modules/native"].copy()
        self.add_package("native", "1.0.0", "MIT", path)
        self.save()
        prepared = coverage.inventory(self.root, require_pruned=True)
        self.assertEqual({copy["path"] for copy in prepared["expected"]["native@1.0.0"]}, {path, "node_modules/native"})
        self.assertEqual(prepared["platform_exclusions"], [])
        verified = coverage.verify(self.root, prepared, self.foreign_report(), self.scanner(), require_pruned=True)
        self.assertEqual(verified["expected_count"], 2)
        self.assertEqual(verified["installed_path_count"], 3)
        self.assertEqual(verified["denied"], [])


class WorkspaceLinkTests(LicenseFixture):
    link_path = "node_modules/@caseops/web"

    def directory_link(self, path, target):
        link = self.root / path
        link.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            subprocess.run(["node", "-e", "require('node:fs').symlinkSync(process.argv[1], process.argv[2], 'junction');",
                str(target.absolute()), str(link)], capture_output=True, check=True, timeout=10)
            self.assertTrue(link.is_junction())
            print("Workspace fixture link: actual Windows junction")
        else:
            link.symlink_to(target, target_is_directory=True)
            self.assertTrue(link.is_symlink())
            print("Workspace fixture link: actual directory symlink")
        return link

    def workspace_link(self, target=None, path=None, workspace="apps/web"):
        path = path or self.link_path
        self.packages[path] = {"resolved": workspace, "link": True}
        self.save()
        return self.directory_link(path, self.root / workspace if target is None else target)

    def foreign_workspace(self, same_name=False, copied=False):
        foreign = {**self.web, "description": "different installed bytes", "license": "OFL-1.1"}
        if not same_name:
            foreign["name"] = "different-unreviewed-workspace"
        if copied:
            foreign["dependencies"] = {"copied": "1.0.0"}
            self.write("foreign/node_modules/copied/package.json", {"name": "copied", "version": "1.0.0", "license": "OFL-1.1"})
        self.write("foreign/package.json", foreign)
        return self.root / "foreign"

    def pruned_inventory(self):
        self.save()
        return coverage.inventory(self.root, require_pruned=True)

    def test_correct_workspace_link_is_accepted(self):
        self.workspace_link()
        prepared = self.pruned_inventory()
        self.assertEqual(prepared["physical_package_paths"], [self.link_path, "node_modules/a"])
        result = coverage.verify(self.root, prepared, self.report(), self.scanner(), require_pruned=True)
        self.assertEqual(result["installed_path_count"], 1)
        self.assertEqual(result["denied"], [])

    def test_prepared_workspace_link_binds_target_identity_and_manifest_hash(self):
        self.workspace_link()
        prepared = self.pruned_inventory()
        self.assertEqual(prepared["workspace_links"], {self.link_path: {"workspace": "apps/web", "target": "apps/web",
            "name": "@caseops/web", "package_sha256": coverage.digest(self.root / "apps/web/package.json")}})

    def test_within_root_wrong_workspace_target_is_rejected(self):
        self.workspace_link(self.foreign_workspace())
        with self.assertRaisesRegex(ValueError, "Workspace link target"):
            self.pruned_inventory()

    def test_same_name_different_manifest_target_is_rejected(self):
        target = self.foreign_workspace(same_name=True)
        self.assertEqual(coverage.read_json(target / "package.json")["name"], self.web["name"])
        self.assertNotEqual(coverage.digest(target / "package.json"), coverage.digest(self.root / "apps/web/package.json"))
        self.workspace_link(target)
        with self.assertRaisesRegex(ValueError, "Workspace link target"):
            self.pruned_inventory()

    def test_directory_masquerading_as_workspace_link_is_rejected(self):
        self.packages[self.link_path] = {"resolved": "apps/web", "link": True}
        self.write(self.link_path + "/package.json", self.web)
        with self.assertRaisesRegex(ValueError, "Workspace link must be a physical"):
            self.pruned_inventory()

    def test_outside_root_workspace_target_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=self.root.parent) as storage:
            outside = Path(storage)
            (outside / "package.json").write_text(json.dumps(self.web), encoding="utf-8")
            link = self.workspace_link(outside)
            try:
                with self.assertRaisesRegex(ValueError, "Workspace link target|escapes root"):
                    self.pruned_inventory()
            finally:
                link.unlink() if link.is_symlink() else link.rmdir()

    def test_broken_workspace_target_is_rejected(self):
        self.workspace_link(self.root / "missing-workspace")
        with self.assertRaisesRegex(ValueError, "Workspace link target"):
            self.pruned_inventory()

    def test_absent_workspace_link_is_rejected(self):
        self.packages[self.link_path] = {"resolved": "apps/web", "link": True}
        with self.assertRaisesRegex(ValueError, "Workspace link must be a physical"):
            self.pruned_inventory()

    def test_valid_nested_workspace_and_its_installed_dependencies_are_covered(self):
        workspace = "apps/web/tools/nested"
        nested = {"name": "@caseops/nested", "private": True, "dependencies": {"b": "2.0.0"}}
        self.manifest["workspaces"].append(workspace)
        self.packages[""]["workspaces"] = self.manifest["workspaces"].copy()
        self.packages[workspace] = nested.copy()
        self.write(workspace + "/package.json", nested)
        self.packages[workspace + "/node_modules/b"] = {"version": "2.0.0", "license": "MIT"}
        self.add_package("b", "2.0.0", "MIT", workspace + "/node_modules/b")
        self.workspace_link()
        self.workspace_link(path="node_modules/@caseops/nested", workspace=workspace)
        prepared = self.pruned_inventory()
        report = {**self.report(), "b@2.0.0": {"licenses": "MIT", "path": str(self.root / workspace / "node_modules/b")}}
        result = coverage.verify(self.root, prepared, report, self.scanner(), require_pruned=True)
        self.assertEqual(result["expected_count"], 2)
        self.assertEqual(result["installed_path_count"], 2)
        self.assertEqual(prepared["physical_package_paths"], [workspace + "/node_modules/b", "node_modules/@caseops/nested", self.link_path, "node_modules/a"])

    def test_retargeted_link_with_identical_manifest_bytes_is_rejected_at_verify(self):
        link = self.workspace_link()
        prepared = self.pruned_inventory()
        self.write("foreign/package.json", self.web)
        self.assertEqual(coverage.digest(self.root / "foreign/package.json"), coverage.digest(self.root / "apps/web/package.json"))
        link.unlink() if link.is_symlink() else link.rmdir()
        self.directory_link(self.link_path, self.root / "foreign")
        with self.assertRaisesRegex(ValueError, "Workspace link target"):
            coverage.verify(self.root, prepared, self.report(), self.scanner(), require_pruned=True)

    def test_workspace_manifest_byte_change_is_rejected_at_verify(self):
        self.workspace_link()
        prepared = self.pruned_inventory()
        self.web["description"] = "same identity and edges, changed bytes"
        self.save()
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            coverage.verify(self.root, prepared, self.report(), self.scanner(), require_pruned=True)

    def test_prepared_workspace_binding_tampering_is_rejected(self):
        self.workspace_link()
        prepared = self.pruned_inventory()
        prepared["workspace_links"][self.link_path]["target"] = "foreign"
        with self.assertRaisesRegex(ValueError, "changed after preparation"):
            coverage.verify(self.root, prepared, self.report(), self.scanner(), require_pruned=True)

    def test_review_counterexample_cannot_hide_foreign_manifest_and_subtree(self):
        self.workspace_link(self.foreign_workspace(copied=True))
        with self.assertRaisesRegex(ValueError, "Workspace link target"):
            self.verify()

    def test_required_workspace_edge_uses_the_validated_physical_link(self):
        self.manifest["dependencies"] = {"@caseops/web": "file:apps/web"}
        self.packages[""]["dependencies"] = self.manifest["dependencies"].copy()
        self.workspace_link()
        result = coverage.verify(self.root, self.pruned_inventory(), self.report(), self.scanner(), require_pruned=True)
        self.assertTrue(result["coverage_exact"])
        self.assertEqual(result["denied"], [])


class WiringTests(unittest.TestCase):
    def test_standard_unittest_discovery_covers_entire_module(self):
        loader = unittest.TestLoader()
        discovered = identities(loader.discover(str(ROOT / "scripts/tests"), pattern="test_js_license_coverage.py"))
        expected = identities(loader.loadTestsFromModule(sys.modules[__name__]))
        self.assertTrue(expected)
        self.assertEqual(sorted(discovered), sorted(expected))

    def test_actual_standard_security_workflow_selects_guard_and_tests(self):
        workflow_contract((ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"))

    def test_historical_filter_comment_is_not_an_executable_bypass(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        workflow_contract(text.replace("    steps:\n", "    # Previous --production and --excludePackages scan was empty.\n    steps:\n"))

    def test_missing_verifier_wiring_is_rejected(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace("scripts/check_js_license_coverage.py verify", "echo skipped"))

    def test_old_empty_production_filter_is_rejected(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('license-checker --json --packages "$packages"', 'license-checker --production --json'))

    def test_musl_step_cannot_depend_on_host_policy_success(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('if: ${{ always() && !cancelled() }}', 'if: success()'))

    def test_audit_tools_cannot_be_installed_into_app_dependencies(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('npm install --prefix /license-audit', 'npm install --prefix /app'))

    def test_actual_pruned_target_cannot_be_replaced_with_runner_or_host(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('--target prod-deps', '--target runner'))

    def test_musl_admission_and_pruned_checks_cannot_be_omitted(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('--require-platform linux-x64-musl --require-pruned-tree', ''))

    def test_guard_mount_must_be_read_only(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('check_js_license_coverage.py,readonly', 'check_js_license_coverage.py'))

    def test_exact_checkout_sha_binding_cannot_be_omitted(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', 'echo unbound'))

    def test_artifact_must_retain_both_host_and_musl_evidence(self):
        text = (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wiring missing"):
            workflow_contract(text.replace('path: ${{ runner.temp }}/js-license-evidence', 'path: ${{ runner.temp }}/js-license-evidence/host'))


if __name__ == "__main__":
    unittest.main()
