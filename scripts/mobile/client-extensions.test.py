"""Independent literal inventory. Pure source assertions, never native proof."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
IOS = (
    "CX28-CAM-01", "CX28-CAM-02", "CX28-CAM-03", "CX28-CAM-04", "CX28-CAM-05", "CX28-CAM-06",
    "CX28-LOCK-01", "CX28-LOCK-02", "CX28-LOCK-03", "CX28-LOCK-04", "CX28-LOCK-05",
    "CX28-LINK-01", "CX28-LINK-02", "CX28-LINK-03", "CX28-LINK-04", "CX28-LINK-05",
    "CX28-READ-01", "CX28-READ-02", "CX28-READ-03", "CX28-READ-04",
    "CX28-VERSION-01", "CX28-VERSION-02", "CX28-VERSION-03", "CX28-VERSION-04",
)
ANDROID = (
    "CX28-CAM-01", "CX28-CAM-02", "CX28-CAM-03", "CX28-CAM-04", "CX28-CAM-05", "CX28-CAM-06",
    "CX28-LOCK-01", "CX28-LOCK-02", "CX28-LOCK-03", "CX28-LOCK-04", "CX28-LOCK-05",
    "CX28-LINK-01", "CX28-LINK-02", "CX28-LINK-03", "CX28-LINK-04", "CX28-LINK-05",
    "CX28-READ-01", "CX28-READ-02", "CX28-READ-03", "CX28-READ-04",
    "CX28-VERSION-01", "CX28-VERSION-02", "CX28-VERSION-03", "CX28-VERSION-04",
)


class ClientExtensionInventory(unittest.TestCase):
    def test_both_platform_inventories_are_independently_literal_and_exact(self):
        source = (ROOT / "apps/mobile/e2e/client-extensions-inventory.mjs").read_text()
        ios, android = source.split("export const androidClientExtensions", 1)
        for actual, expected in ((ios, IOS), (android, ANDROID)):
            self.assertEqual(tuple(re.findall(r'"id":"(CX28-[A-Z]+-\d{2})"', actual)), expected)
            self.assertEqual(len(expected), 24)
            self.assertEqual(len(set(expected)), 24)

    def test_complete_callbacks_match_every_literal_identity(self):
        source = (ROOT / "apps/mobile/e2e/client-extensions-20261028.mjs").read_text()
        callbacks = tuple(re.findall(r"\{id:'(CX28-[A-Z]+-\d{2})',(?:requires:\[[^\]]*\],)?run:async c=>", source))
        self.assertEqual(callbacks, IOS)
        self.assertEqual(callbacks, ANDROID)
        self.assertNotIn("skip:", source)
        self.assertNotIn(".only(", source)

    def test_original_case_identity_inventories_are_separate(self):
        import json
        core = json.loads((ROOT / "apps/mobile/e2e/core-20261025.json").read_text())
        self.assertEqual([row["id"] for row in core["cases"]], [f"NATIVE-{i:02d}" for i in range(1, 24)])
        for platform in ("ios", "android"):
            source = (ROOT / f"apps/mobile/e2e/{platform}-files.mjs").read_text().split("].map", 1)[0]
            self.assertEqual(re.findall(r"\['(FILES-\d{2})',", source), [f"FILES-{i:02d}" for i in range(1, 18)])
        self.assertTrue(set(IOS).isdisjoint(row["id"] for row in core["cases"]))

    def test_actual_public_collection_is_exact_for_each_platform_without_native_dispatch(self):
        import json, os, subprocess
        for platform, expected in (("ios", IOS), ("android", ANDROID)):
            child = subprocess.run([os.environ.get("CASEOPS_NATIVE_NODE", "node"), str(ROOT / "scripts/mobile/run-client-extensions.mjs"), platform, "--collect"], cwd=ROOT, capture_output=True, text=True, timeout=10, check=False)
            self.assertEqual(child.returncode, 0, child.stderr)
            value = json.loads(child.stdout)
            self.assertEqual(value["intended"], [platform + ":" + name for name in expected])
            self.assertEqual(value["discovered"], value["intended"])
            self.assertEqual(value["phases"], [{"id": platform + ":" + name, "phase": phase} for name in expected for phase in ("setup", "call", "teardown")])
            self.assertEqual(len(value["callbacks"]), 24)
            self.assertEqual([row["id"] for row in value["callbacks"]], value["intended"])
            self.assertTrue(all(row["executable"] is True and re.fullmatch("[a-f0-9]{64}", row["sourceSha256"]) for row in value["callbacks"]))
            self.assertEqual(len({row["sourceSha256"] for row in value["callbacks"]}), 24)
            self.assertEqual(value["nativeExecution"], "not-run")
            self.assertEqual((value["expectedCases"], value["expectedPhases"], value["expectedSessions"]), (24, 72, 24))

    def test_new_profile_has_exact_mounted_source_pin_lf_and_ci_closure(self):
        import hashlib
        attributes = (ROOT / ".gitattributes").read_text()
        workflow = (ROOT / ".github/workflows/mobile-source.yml").read_text()
        compose = (ROOT / "compose.mobile-local.yml").read_text()
        bootstrap = (ROOT / "scripts/mobile/local-bootstrap.py").read_text()
        self.assertIn('./scripts/mobile:/mobile-fixture:ro', compose)
        self.assertIn('glob("local-*")', bootstrap)
        base = hashlib.sha256((ROOT / "scripts/mobile/local-v1-controls.py").read_bytes()).hexdigest()
        self.assertIn(base, (ROOT / "scripts/mobile/local-client-extension-controls.py").read_text())
        self.assertIn('native-client-extensions-v1', (ROOT / "scripts/mobile/local-gateway.py").read_text())
        for name in ('local-client-extension-controls.py', 'local-client-extension-controls.test.py', 'local-client-extension-fixture.py', 'client-extension-fixture.test.py', 'client-extensions.test.py'):
            self.assertIn('scripts/mobile/' + name + ' text eol=lf', attributes)
        for name in ('local-client-extension-controls.test.py', 'client-extension-fixture.test.py', 'client-extensions.test.py'):
            self.assertIn('python3 scripts/mobile/' + name, workflow)
        self.assertIn('scripts/mobile/client-extensions.test.mjs', workflow)
        for source in (ROOT / 'apps/mobile/e2e/client-extensions-inventory.mjs').read_text().split('export const androidClientExtensions'):
            if 'CX28-READ-04' in source and 'CX28-VERSION-01' in source:
                self.assertLess(source.index('CX28-READ-04'), source.index('CX28-VERSION-01'))

    def test_ci_runs_this_independent_source_contract(self):
        workflow = (ROOT / ".github/workflows/mobile-source.yml").read_text()
        self.assertIn("run: python3 scripts/mobile/client-extensions.test.py", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
