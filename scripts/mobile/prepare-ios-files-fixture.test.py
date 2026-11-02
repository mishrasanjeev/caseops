"""Offline generator and immutable isolation-boundary regression tests."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib


spec = importlib.util.spec_from_file_location("ios_files_fixture", Path(__file__).with_name("prepare-ios-files-fixture.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cache = self.root / "docker"
        self.cache.mkdir()
        self.receipt = self.cache / "receipt-core-unit.json"
        self.config = {"CASEOPS_MOBILE_PLATFORM": "ios", "CASEOPS_MOBILE_PROJECT": "caseops-mobile-unit",
                       "CASEOPS_MOBILE_API_PORT": "8443"}
        self.core = {"platform": "ios", "environment": "docker-integration", "syntheticDataOnly": True,
                     "productionAccessed": False, "noPaidProviderKeysInAPIOrWeb": True,
                     "project": "caseops-mobile-unit", "apiOrigin": "https://127.0.0.1:8443",
                     "backendSha": "a" * 40, "backendRevision": "unit"}
        self.seed = {"companyId": "11111111-1111-4111-8111-111111111111",
                     "membershipId": "22222222-2222-4222-8222-222222222222",
                     "sourceId": "33333333-3333-4333-8333-333333333333",
                     "matter": {"id": "44444444-4444-4444-8444-444444444444", "identityLabel": "MOBILE-LOCAL-001"}}
        self.write_inputs()

    def write_inputs(self):
        for path, body in ((self.cache / "config.json", self.config), (self.cache / "seed.json", self.seed), (self.receipt, self.core)):
            path.write_text(json.dumps(body))

    def generate(self):
        result = fixture.prepare(self.cache, self.receipt, self.root / "assets")
        return result, json.loads(Path(result["manifest"]["path"]).read_text())

    def test_manifest_binds_actual_seed_receipt_bytes_and_every_asset(self):
        result, manifest = self.generate()
        self.assertEqual(result["assetCount"], 7)
        self.assertEqual([row["id"] for row in manifest["assets"]], ["txt", "pdf", "png", "jpeg", "docx", "eicar", "unsupported"])
        for key in ("baseSeed", "isolationReceipt", "helperSource"):
            reference = manifest[key]
            self.assertEqual(hashlib.sha256(Path(reference["path"]).read_bytes()).hexdigest(), reference["sha256"])
        self.assertEqual(manifest["matter"], self.seed["matter"])
        self.assertEqual(manifest["companyId"], self.seed["companyId"])
        for row in manifest["assets"]:
            path = Path(row["path"])
            data = path.read_bytes()
            self.assertEqual(path.parent, self.root / "assets")
            self.assertEqual(path.name, row["filename"])
            self.assertIn(manifest["runId"], path.name)
            self.assertEqual(len(data), row["sizeBytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertLessEqual(len(data), fixture.MAX_ASSET_BYTES)
        self.assertFalse(manifest["credentialsRead"])
        self.assertFalse(manifest["attachmentsCreated"])
        self.assertFalse(manifest["networkAccessed"])
        self.assertFalse((self.cache / "credentials.json").exists())

    def test_text_has_three_exact_renderer_segments_with_distinct_markers(self):
        content, expected = fixture.txt("CASEOPS-IOS-UNIT-TXT")
        text = content.decode("ascii")
        self.assertEqual(len(text), 24000)
        parts = [text[offset:offset + 10000] for offset in range(0, len(text), 10000)]
        self.assertEqual(len(parts), expected["segments"])
        for part, marker in zip(parts, expected["segmentMarkers"], strict=True):
            self.assertTrue(part.startswith(marker + "\n"))
        self.assertEqual(len(set(expected["segmentMarkers"])), 3)

    def test_pdf_cross_reference_points_to_all_real_two_page_objects(self):
        data, expected = fixture.pdf("CASEOPS-IOS-UNIT-PDF")
        self.assertEqual(expected["pages"], 2)
        self.assertIn(b"/Kids [4 0 R 6 0 R] /Count 2", data)
        start = int(data.rsplit(b"startxref\n", 1)[1].splitlines()[0])
        lines = data[start:].splitlines()
        self.assertEqual(lines[:2], [b"xref", b"0 8"])
        for index, line in enumerate(lines[3:10], 1):
            offset = int(line.split()[0])
            self.assertTrue(data[offset:].startswith(f"{index} 0 obj\n".encode()))
        for marker in expected["pageMarkers"]:
            self.assertIn(marker.encode(), data)

    def test_png_decodes_crc_checked_rgb_scanlines_and_jpeg_has_full_baseline_frame(self):
        data, expected = fixture.png("CASEOPS-IOS-UNIT-PNG")
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        offset, chunks = 8, {}
        while offset < len(data):
            length = struct.unpack(">I", data[offset:offset + 4])[0]
            kind = data[offset + 4:offset + 8]
            body = data[offset + 8:offset + 8 + length]
            self.assertEqual(struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0], zlib.crc32(kind + body) & 0xffffffff)
            chunks[kind] = body
            offset += 12 + length
        self.assertEqual(len(zlib.decompress(chunks[b"IDAT"])), (1 + expected["width"] * 3) * expected["height"])
        jpeg, expected_jpeg = fixture.jpeg("CASEOPS-IOS-UNIT-JPEG")
        self.assertTrue(jpeg.startswith(b"\xff\xd8\xff\xe0"))
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))
        start = jpeg.index(b"\xff\xc0")
        self.assertEqual(struct.unpack(">HH", jpeg[start + 5:start + 9]), (expected_jpeg["height"], expected_jpeg["width"]))
        self.assertIn(b"\xff\xc4", jpeg)
        self.assertIn(b"\xff\xda", jpeg)

    def test_docx_is_valid_office_zip_xml_and_negative_inputs_cannot_be_admitted(self):
        data, expected = fixture.docx("CASEOPS-IOS-UNIT-DOCX")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()), {"[Content_Types].xml", "_rels/.rels", "word/document.xml"})
            for name in archive.namelist():
                ET.fromstring(archive.read(name))
            self.assertIn(b"CASEOPS-IOS-UNIT-DOCX", archive.read("word/document.xml"))
        self.assertFalse(expected["readerSupported"])
        _, manifest = self.generate()
        rows = {row["id"]: row for row in manifest["assets"]}
        self.assertEqual(Path(rows["eicar"]["path"]).read_bytes(), fixture.EICAR)
        self.assertEqual(len(fixture.EICAR), 68)
        self.assertFalse(rows["eicar"]["admittable"])
        self.assertFalse(rows["unsupported"]["admittable"])
        self.assertTrue(rows["unsupported"]["filename"].endswith(".rtf"))
        self.assertFalse(manifest["legacyDocProvided"])

    def test_rejects_foreign_platform_project_origin_and_non_synthetic_receipt_before_output(self):
        for key, value in (("platform", "android"), ("project", "foreign-project"),
                           ("apiOrigin", "https://example.com"), ("syntheticDataOnly", False),
                           ("productionAccessed", True), ("noPaidProviderKeysInAPIOrWeb", False)):
            original = self.core[key]
            self.core[key] = value
            self.write_inputs()
            with self.assertRaises(ValueError):
                self.generate()
            self.assertFalse((self.root / "assets").exists())
            self.core[key] = original

    def test_rejects_foreign_seed_target_and_preserves_prior_output(self):
        self.seed["matter"]["identityLabel"] = "foreign"
        self.write_inputs()
        with self.assertRaises(ValueError):
            self.generate()
        self.seed["matter"]["identityLabel"] = "MOBILE-LOCAL-001"
        self.write_inputs()
        result, _ = self.generate()
        prior = Path(result["manifest"]["path"]).read_bytes()
        with self.assertRaises(FileExistsError):
            fixture.prepare(self.cache, self.receipt, self.root / "assets")
        self.assertEqual(Path(result["manifest"]["path"]).read_bytes(), prior)

    def test_evidence_hash_mismatch_and_symlinks_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            fixture.read_bound(self.receipt, "0" * 64)
        link = self.cache / "receipt-link.json"
        link.symlink_to(self.receipt)
        with self.assertRaises(OSError):
            fixture.read_bound(link)


if __name__ == "__main__":
    unittest.main()
