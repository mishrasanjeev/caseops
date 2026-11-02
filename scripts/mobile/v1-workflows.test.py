"""Independent literal inventory controls; no service, device or credential IO."""

from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    "SOURCE-01", "SOURCE-02", "SOURCE-03", "SOURCE-04", "SOURCE-05", "SOURCE-06", "SOURCE-07",
    "WORK-01", "WORK-02", "WORK-03", "WORK-04", "WORK-05", "WORK-06", "WORK-07", "WORK-08",
    "COUNSEL-01", "INBOX-01",
)


class V1InventoryTests(unittest.TestCase):
    def test_complete_literal_inventory_and_platforms(self):
        source = (ROOT / "apps/mobile/e2e/v1-workflows-inventory.mjs").read_text()
        self.assertEqual(tuple(re.findall(r"\['((?:SOURCE|WORK|COUNSEL|INBOX)-\d{2})',", source)), CASES)
        self.assertIn("Object.freeze(['android', 'ios'])", source)
        self.assertIn("expectedPhases: 51", source)
        self.assertIn("expectedSessions: 17", source)

    def test_all_named_cases_have_executable_bodies(self):
        source = (ROOT / "apps/mobile/e2e/v1-workflows.mjs").read_text()
        self.assertEqual(tuple(re.findall(r"\{ id: '((?:SOURCE|WORK|COUNSEL|INBOX)-\d{2})',", source)), CASES)
        self.assertEqual(len(re.findall(r"\{ id: '(?:SOURCE|WORK|COUNSEL|INBOX)-\d{2}',[^\n]*run: async", source)), 17)

    def test_cross_language_actual_control_ceilings_preserve_whole_bound(self):
        javascript = (ROOT / "apps/mobile/e2e/v1-workflows-inventory.mjs").read_text()
        python = (ROOT / "scripts/mobile/local-v1-controls.py").read_text()
        js_limits = dict((key, int(value)) for key, value in re.findall(r"'((?:SOURCE|WORK|COUNSEL|INBOX)-\d{2})': (\d+)", javascript))
        py_limits = dict((key, int(value)) for key, value in re.findall(r'"((?:SOURCE|WORK|COUNSEL|INBOX)-\d{2})": (\d+)', python))
        self.assertEqual(tuple(js_limits), CASES)
        self.assertEqual(js_limits, py_limits)
        self.assertEqual(sum(js_limits.values()) + 1, 255)
        self.assertLessEqual(sum(js_limits.values()) + 1, 264)
        self.assertEqual({prefix: sum(key.startswith(prefix) for key in CASES) for prefix in ("SOURCE", "WORK", "COUNSEL", "INBOX")},
                         {"SOURCE": 7, "WORK": 8, "COUNSEL": 1, "INBOX": 1})
        contract = (ROOT / "apps/mobile/e2e/v1-workflows-contract.mjs").read_text()
        self.assertEqual(tuple(re.findall(r"caseId: '(WORK-\d{2})', kind: '([^']+)'", contract)),
                         (("WORK-01", "task"), ("WORK-03", "hearing"), ("WORK-04", "follow-up-task"), ("WORK-06", "unknown-save-task")))
        self.assertIn('96 - len(NATIVE_CREATIONS)', python)

    def test_existing_inventories_are_separate(self):
        core = json.loads((ROOT / "apps/mobile/e2e/core-20261025.json").read_text())
        files = (ROOT / "apps/mobile/e2e/ios-files.mjs").read_text()
        self.assertEqual(core["inventoryId"], "native-core-2026-10-25")
        self.assertEqual(len(core["cases"]), 23)
        self.assertIn("native-ios-files-2026-10-26", files)
        self.assertNotIn("SOURCE-01", [row["id"] for row in core["cases"]])
        self.assertNotIn("WORK-01", files)

    def test_cli_has_complete_inventory_and_no_case_slice(self):
        source = (ROOT / "scripts/mobile/run-v1-workflows.mjs").read_text()
        self.assertIn("for (const scenario of v1WorkflowScenarios)", source)
        self.assertNotIn("--case", source)
        self.assertNotIn("--grep", source)
        self.assertIn("connectionRetryCount: 0", source)
        self.assertIn("V1_THIRTY_MINUTE_SERIAL_BOUND", source)

    def test_pending_projection_does_not_claim_native_execution(self):
        source = (ROOT / "scripts/mobile/prepare-v1-fixture.mjs").read_text()
        self.assertIn("preparedOnly: true, readyForLive: false", source)
        self.assertIn("FUTURE_CANONICAL_SOURCE_PENDING", source)
        self.assertIn("nativeExecution: 'not-run'", source)
        self.assertNotIn("8928c0db10b3b3811074b6b9ff27d854c68ce04e", source)

    def test_reader_call_follows_both_live_identity_reads(self):
        source = (ROOT / "scripts/mobile/run-v1-workflows.mjs").read_text()
        self.assertLess(source.index("io.getJson(isolation.gatewayUrl + '/api/build')"), source.index("const loaded = io.reader("))
        self.assertLess(source.index("io.getJson(isolation.webGatewayUrl + '/api/release-identity')"), source.index("const loaded = io.reader("))
        self.assertLess(source.index("const publicMembers = config.members.map"), source.index("const loaded = io.reader("))


if __name__ == "__main__":
    unittest.main()
