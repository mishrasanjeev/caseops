"""Offline Android fixture provenance, public byte, and isolation regressions."""

import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


spec = importlib.util.spec_from_file_location("android_files_fixture", Path(__file__).with_name("prepare-android-files-fixture.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.cache = self.root / "docker"
        self.cache.mkdir()
        self.receipt = self.cache / "receipt-core-unit.json"
        project, sha = "caseops-mobile-android-unit", "a" * 40
        self.config = {"CASEOPS_MOBILE_PLATFORM": "android", "CASEOPS_MOBILE_PROJECT": project,
                       "CASEOPS_MOBILE_API_PORT": "8453", "CASEOPS_MOBILE_WEB_PORT": "3453",
                       "CASEOPS_MOBILE_API_ORIGIN": "https://10.0.2.2:8453", "CASEOPS_MOBILE_WEB_ORIGIN": "https://10.0.2.2:3453",
                       "CASEOPS_MOBILE_API_SHA": sha, "CASEOPS_MOBILE_WEB_SHA": sha,
                       "CASEOPS_MOBILE_API_REVISION": "unit-api", "CASEOPS_MOBILE_WEB_REVISION": "unit-web"}
        self.core = {"platform": "android", "environment": "docker-integration", "syntheticDataOnly": True,
                     "productionAccessed": False, "noPaidProviderKeysInAPIOrWeb": True,
                     "apiWebPostgresScannerNetworkInternal": True, "project": project,
                     "apiOrigin": "https://10.0.2.2:8453", "webOrigin": "https://10.0.2.2:3453",
                     "gatewayUrl": "https://127.0.0.1:8453", "webGatewayUrl": "https://127.0.0.1:3453",
                     "backendSha": sha, "webSha": sha, "backendRevision": "unit-api", "webRevision": "unit-web",
                     "webIdentity": {"release_sha": sha, "revision": "unit-web"},
                     "source": {key: {"head": sha, "dirty": False} for key in ("api", "web")},
                     "tlsProof": {"strictDefaultTLS": True, "verificationDisabled": False,
                                  "unknownCARejected": True, "wrongHostnameRejected": True,
                                  "hostnames": [{"name": name, "verified": True} for name in ("127.0.0.1", "10.0.2.2", "localhost")]},
                     "containers": [{"id": str(index) * 64, "image": "sha256:" + str(index + 3) * 64,
                                     "name": f"/{project}-{service}-1", "networks": [project + "_default"],
                                     "project": project} for index, service in enumerate(("api", "web", "postgres"), 1)],
                     "fixtureSourceHashes": {"scripts/mobile/local-fixture.py": hashlib.sha256((fixture.HERE / "local-fixture.py").read_bytes()).hexdigest()}}
        self.seed = {"environment": "docker-integration", "syntheticDataOnly": True,
                     "companyId": "11111111-1111-4111-8111-111111111111",
                     "membershipId": "22222222-2222-4222-8222-222222222222",
                     "sourceId": "33333333-3333-4333-8333-333333333333",
                     "sourceSha256": hashlib.sha256(fixture.PUBLIC_SOURCE).hexdigest(), "cleanUploadAndDownload": True,
                     "matter": {"id": "44444444-4444-4444-8444-444444444444", "identityLabel": "MOBILE-LOCAL-001"}}
        self.output = self.root / "assets"
        self.write_inputs()

    def write_inputs(self):
        for path, body in ((self.cache / "config.json", self.config), (self.cache / "seed.json", self.seed), (self.receipt, self.core)):
            path.write_text(json.dumps(body))

    def generate(self, output=None):
        result = fixture.prepare(self.cache, self.receipt, output or self.output)
        data, _ = fixture.read_bound(result["manifest"]["path"], result["manifest"]["sha256"])
        return result, json.loads(data)

    def assert_refused_before_output(self):
        self.write_inputs()
        with self.assertRaises((ValueError, OSError)):
            self.generate()
        self.assertFalse(self.output.exists())

    def test_seven_public_assets_bind_actual_android_receipt_seed_helper_and_encoders(self):
        result, manifest = self.generate()
        self.assertEqual((manifest["schemaVersion"], manifest["kind"], manifest["platform"]),
                         (1, "android-files-synthetic-fixtures", "android"))
        self.assertEqual([row["id"] for row in manifest["assets"]], ["txt", "pdf", "png", "jpeg", "docx", "eicar", "unsupported"])
        self.assertEqual(result["assetCount"], 7)
        for key in ("isolationReceipt", "baseSeed", "configEvidence", "helperSource", "encoderSource", "fixtureSource"):
            ref = manifest[key]
            self.assertEqual(hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest(), ref["sha256"])
        self.assertEqual(manifest["configEvidence"]["path"], str(self.output / "config-evidence.json"))
        self.assertEqual(manifest["observedConfigLocator"]["path"], str(self.cache / "config.json"))
        self.assertEqual(manifest["matter"], self.seed["matter"])
        self.assertEqual(manifest["companyId"], self.seed["companyId"])
        self.assertEqual(manifest["ownerMembershipId"], self.seed["membershipId"])
        self.assertEqual(manifest["apiOrigin"], "https://10.0.2.2:8453")
        self.assertEqual(manifest["webOrigin"], "https://10.0.2.2:3453")
        self.assertRegex(manifest["runId"], r"^[a-f0-9]{12}$")
        for row in manifest["assets"]:
            path = Path(row["path"])
            data = path.read_bytes()
            self.assertEqual(path.parent, self.output)
            self.assertEqual(path.name, row["filename"])
            self.assertRegex(path.name, rf"^CaseOps-android-files-{manifest['runId']}-{row['id']}\.[a-z]+$")
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual(len(data), row["sizeBytes"])
            self.assertLessEqual(len(data), 256 * 1024)
        self.assertEqual(result["totalBytes"], sum(row["sizeBytes"] for row in manifest["assets"]))
        self.assertLessEqual(result["totalBytes"], 1024 * 1024)
        self.assertTrue(manifest["syntheticDataOnly"])
        for key in ("credentialsRead", "networkAccessed", "attachmentsCreated", "legacyDocProvided"):
            self.assertFalse(manifest[key])
        self.assertFalse((self.cache / "credentials.json").exists())

    def test_base_txt_oracle_is_exact_public_seed_source_not_a_new_attachment(self):
        _, manifest = self.generate()
        self.assertEqual(manifest["source"], {"matterId": self.seed["matter"]["id"], "attachmentId": self.seed["sourceId"],
                         "filename": "mobile-source.txt", "sha256": self.seed["sourceSha256"],
                         "sizeBytes": 70, "text": fixture.PUBLIC_SOURCE.decode("ascii")})
        self.assertEqual(hashlib.sha256(manifest["source"]["text"].encode()).hexdigest(), self.seed["sourceSha256"])

    def test_shared_real_formats_retain_segments_pages_images_docx_and_exact_negative_bytes(self):
        _, manifest = self.generate()
        rows = {row["id"]: row for row in manifest["assets"]}
        text = Path(rows["txt"]["path"]).read_text()
        self.assertEqual(len(text), 24000)
        for index, marker in enumerate(rows["txt"]["expected"]["segmentMarkers"]):
            self.assertTrue(text[index * 10000:].startswith(marker + "\n"))
        pdf = Path(rows["pdf"]["path"]).read_bytes()
        self.assertIn(b"/Kids [4 0 R 6 0 R] /Count 2", pdf)
        for marker in rows["pdf"]["expected"]["pageMarkers"]:
            self.assertIn(marker.encode(), pdf)
        self.assertTrue(Path(rows["png"]["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(Path(rows["jpeg"]["path"]).read_bytes().endswith(b"\xff\xd9"))
        with zipfile.ZipFile(io.BytesIO(Path(rows["docx"]["path"]).read_bytes())) as archive:
            self.assertIn(rows["docx"]["marker"].encode(), archive.read("word/document.xml"))
        self.assertFalse(rows["docx"]["expected"]["readerSupported"])
        encoders, _ = fixture.load_encoders()
        self.assertEqual(Path(rows["eicar"]["path"]).read_bytes(), encoders.EICAR)
        self.assertEqual(len(encoders.EICAR), 68)
        self.assertFalse(rows["eicar"]["admittable"])
        self.assertFalse(rows["unsupported"]["admittable"])
        self.assertTrue(rows["unsupported"]["filename"].endswith(".rtf"))

    def test_dynamic_ports_do_not_reuse_ios_or_default_android_ports(self):
        for key, port in (("API", "9653"), ("WEB", "4653")):
            field = "apiOrigin" if key == "API" else "webOrigin"
            gateway = "gatewayUrl" if key == "API" else "webGatewayUrl"
            self.config[f"CASEOPS_MOBILE_{key}_PORT"] = port
            self.config[f"CASEOPS_MOBILE_{key}_ORIGIN"] = self.core[field] = "https://10.0.2.2:" + port
            self.core[gateway] = "https://127.0.0.1:" + port
        self.write_inputs()
        _, manifest = self.generate()
        self.assertEqual(manifest["apiOrigin"], "https://10.0.2.2:9653")
        self.assertEqual(manifest["webOrigin"], "https://10.0.2.2:4653")

    def test_ios_foreign_project_non_synthetic_paid_or_external_network_refused(self):
        for key, value in (("platform", "ios"), ("project", "foreign"), ("syntheticDataOnly", False),
                           ("productionAccessed", True), ("noPaidProviderKeysInAPIOrWeb", False),
                           ("apiWebPostgresScannerNetworkInternal", False), ("apiOrigin", "https://example.com"),
                           ("webOrigin", "https://127.0.0.1:3453")):
            with self.subTest(key=key):
                original = self.core[key]
                self.core[key] = value
                self.assert_refused_before_output()
                self.core[key] = original

    def test_dirty_different_or_unidentified_serving_sources_refused(self):
        for scope in ("api", "web"):
            for field, value in (("dirty", True), ("head", "b" * 40)):
                with self.subTest(scope=scope, field=field):
                    original = self.core["source"][scope][field]
                    self.core["source"][scope][field] = value
                    self.assert_refused_before_output()
                    self.core["source"][scope][field] = original
        self.core["webIdentity"]["revision"] = "stale"
        self.assert_refused_before_output()

    def test_unverified_tls_wrong_hostname_and_unknown_ca_controls_refused(self):
        for key, value in (("strictDefaultTLS", False), ("verificationDisabled", True),
                           ("unknownCARejected", False), ("wrongHostnameRejected", False)):
            with self.subTest(key=key):
                original = self.core["tlsProof"][key]
                self.core["tlsProof"][key] = value
                self.assert_refused_before_output()
                self.core["tlsProof"][key] = original
        self.core["tlsProof"]["hostnames"][1]["verified"] = False
        self.assert_refused_before_output()

    def test_container_network_image_identity_and_duplicate_service_refused(self):
        valid = copy.deepcopy(self.core["containers"])
        for key, value in (("networks", ["external"]), ("project", "foreign"), ("image", "latest"), ("id", "x" * 64)):
            with self.subTest(key=key):
                self.core["containers"] = copy.deepcopy(valid)
                self.core["containers"][0][key] = value
                self.assert_refused_before_output()
        self.core["containers"] = valid + [copy.deepcopy(valid[0])]
        self.assert_refused_before_output()

    def test_changed_seed_source_or_fixture_code_and_foreign_matter_refused(self):
        for key, value in (("sourceSha256", "f" * 64), ("sourceId", "bad"), ("cleanUploadAndDownload", False)):
            with self.subTest(key=key):
                original = self.seed[key]
                self.seed[key] = value
                self.assert_refused_before_output()
                self.seed[key] = original
        self.seed["matter"]["identityLabel"] = "FOREIGN"
        self.assert_refused_before_output()
        self.seed["matter"]["identityLabel"] = "MOBILE-LOCAL-001"
        self.core["fixtureSourceHashes"]["scripts/mobile/local-fixture.py"] = "0" * 64
        self.assert_refused_before_output()

    def test_asset_limit_failure_occurs_before_output_not_after_partial_write(self):
        encoders, ref = fixture.load_encoders()
        encoders.txt = lambda marker: (b"a" * (fixture.MAX_ASSET_BYTES + 1), {})
        with patch.object(fixture, "load_encoders", return_value=(encoders, ref)):
            self.assert_refused_before_output()

    def test_output_must_be_new_physical_and_outside_git_and_prior_bytes_remain(self):
        result, _ = self.generate()
        before = Path(result["manifest"]["path"]).read_bytes()
        with self.assertRaises(FileExistsError):
            self.generate()
        self.assertEqual(Path(result["manifest"]["path"]).read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "outside Git"):
            fixture.prepare(self.cache, self.receipt, fixture.REPO / "android-assets-unit-refused")
        alias = self.root / "alias"
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Canonical output parent"):
            self.generate(alias / "new")

    def test_hash_tamper_symlink_fifo_and_foreign_receipt_refused_without_blocking(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            fixture.read_bound(self.receipt, "0" * 64)
        link = self.cache / "receipt-link.json"
        link.symlink_to(self.receipt)
        with self.assertRaises(ValueError):
            fixture.read_bound(link)
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "Regular evidence"):
            fixture.read_bound(fifo)
        with self.assertRaisesRegex(ValueError, "Immutable cache receipt"):
            fixture.prepare(self.cache, self.root / self.receipt.name, self.output)
        self.assertFalse(self.output.exists())

    def test_configuration_evidence_survives_source_gateway_reset_but_rejects_immutable_snapshot_tampering(self):
        _, manifest = self.generate()
        reference = manifest["configEvidence"]
        original, _ = fixture.read_bound(reference["path"], reference["sha256"])
        self.config["CASEOPS_MOBILE_GATEWAY_RUN_ID"] = "fresh-gateway-after-preparation"
        self.write_inputs()
        self.assertNotEqual((self.cache / "config.json").read_bytes(), original)
        retained, _ = fixture.read_bound(reference["path"], reference["sha256"])
        self.assertEqual(retained, original)
        self.assertEqual(json.loads(retained), {key: value for key, value in self.config.items() if key != "CASEOPS_MOBILE_GATEWAY_RUN_ID"})
        Path(reference["path"]).write_bytes(b'{"changed":"must-not-verify"}')
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            fixture.read_bound(reference["path"], reference["sha256"])


if __name__ == "__main__":
    unittest.main()
