"""Offline regressions for the real Temporal fixture's acquisition boundary."""
import hashlib
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

SCRIPT = Path(__file__).resolve().parents[1] / "prepare_temporal_test_server.py"
spec = importlib.util.spec_from_file_location("temporal_fixture", SCRIPT)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


class TemporalFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="caseops-temporal-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        header = bytearray(64)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = (62).to_bytes(2, "little")
        self.binary = bytes(header) + b"Synthetic test fixture, never executed."
        self.archive = self.bundle([("temporal-test-server", self.binary, False)])
        self.pin = {
            "version": "1.40.0",
            "url": "https://github.com/temporalio/sdk-java/releases/download/v1.40.0/temporal-test-server_1.40.0_linux_amd64.tar.gz",
            "archive_sha256": hashlib.sha256(self.archive).hexdigest(),
            "archive_bytes": len(self.archive), "binary_sha256": hashlib.sha256(self.binary).hexdigest(),
        }
        self.cache = self.root / "cache"
        self.cache.mkdir()

    def bundle(self, rows):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, data, linked in rows:
                member = tarfile.TarInfo(name)
                if linked:
                    member.type, member.linkname = tarfile.SYMTYPE, "/unexpected"
                    archive.addfile(member)
                else:
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def cached_archive(self, payload=None):
        (self.cache / "temporal-test-server.tar.gz").write_bytes(self.archive if payload is None else payload)

    def test_manifest_is_exact_and_versioned(self):
        path = self.root / "pin.json"
        path.write_text(json.dumps(self.pin))
        self.assertEqual(fixture.load_pin(path), self.pin)
        for key, value in [("url", "http://example.com/tool"), ("version", "latest"),
                           ("archive_sha256", "0"), ("binary_sha256", None),
                           ("archive_bytes", True), ("extra", "unreviewed")]:
            with self.subTest(key=key):
                path.write_text(json.dumps({**self.pin, key: value}))
                with self.assertRaises(fixture.FixtureError):
                    fixture.load_pin(path)

    def test_committed_manifest_uses_the_reviewed_official_release(self):
        pin = fixture.load_pin()
        self.assertEqual(pin["version"], "1.40.0")
        self.assertEqual(pin["archive_bytes"], 27208794)
        self.assertEqual(pin["archive_sha256"],
                         "524465a96274831e004326f6e2f2a5f3ef9aaed72c2069cf16c1d64b8b1ec3ca")
        self.assertEqual(pin["binary_sha256"],
                         "19defb9f7318c7cf249518b3642a735efb79876c2b6918afe312336476b796a5")

    def test_cold_acquisition_is_verified_then_cache_hit_needs_no_transport(self):
        response = io.BytesIO(self.archive)
        opener = Mock()
        opener.open.return_value = response
        binary = fixture.provision(self.cache, self.pin, opener=opener)
        self.assertEqual(binary.read_bytes(), self.binary)
        self.assertEqual(opener.open.call_count, 1)
        forbidden = Mock()
        forbidden.open.side_effect = AssertionError("Cached execution attempted a download")
        self.assertEqual(fixture.provision(self.cache, self.pin, opener=forbidden), binary)
        forbidden.open.assert_not_called()

    def test_preacquired_verified_archive_needs_no_transport(self):
        self.cached_archive()
        forbidden = Mock()
        forbidden.open.side_effect = AssertionError("Offline preparation attempted a download")
        binary = fixture.provision(self.cache, self.pin, opener=forbidden)
        self.assertEqual(binary.read_bytes(), self.binary)
        forbidden.open.assert_not_called()

    def test_corrupt_cache_is_retained_and_never_replaced_from_network(self):
        for kind in ("archive", "binary"):
            with self.subTest(kind=kind):
                cache = self.root / kind
                cache.mkdir()
                name = "temporal-test-server" + (".tar.gz" if kind == "archive" else "")
                target = cache / name
                target.write_bytes(b"Corrupt retained evidence")
                target.chmod(0o755)
                forbidden = Mock()
                with self.assertRaises(fixture.FixtureError):
                    fixture.provision(cache, self.pin, opener=forbidden)
                self.assertEqual(target.read_bytes(), b"Corrupt retained evidence")
                forbidden.open.assert_not_called()

    def test_checksum_failure_is_not_retried(self):
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"Wrong bytes")
        with self.assertRaises(fixture.FixtureError):
            fixture.provision(self.cache, self.pin, opener=opener)
        self.assertEqual(opener.open.call_count, 1)
        self.assertTrue((self.cache / "temporal-test-server.tar.gz.attempt-0").exists())
        self.assertFalse((self.cache / "temporal-test-server").exists())

    def test_transient_acquisition_retries_are_bounded(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(self.pin["url"], 503, "unavailable", {}, None)
        sleeping = Mock()
        with self.assertRaises(fixture.FixtureError):
            fixture.acquire(self.cache / "archive", self.pin, opener=opener, sleep=sleeping)
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual([row.args for row in sleeping.call_args_list], [(1,), (2,)])

    def test_permanent_http_failure_does_not_retry(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(self.pin["url"], 404, "not found", {}, None)
        with self.assertRaises(fixture.FixtureError):
            fixture.acquire(self.cache / "archive", self.pin, opener=opener)
        self.assertEqual(opener.open.call_count, 1)

    def test_archives_reject_duplicate_link_and_traversal_entries(self):
        variants = [
            [("temporal-test-server", self.binary, False)] * 2,
            [("temporal-test-server", b"", True)],
            [("../temporal-test-server", self.binary, False)],
            [("other-file", self.binary, False)],
        ]
        for index, rows in enumerate(variants):
            with self.subTest(index=index):
                archive = self.bundle(rows)
                cache = self.root / f"unsafe-{index}"
                cache.mkdir()
                (cache / "temporal-test-server.tar.gz").write_bytes(archive)
                pin = {**self.pin, "archive_sha256": hashlib.sha256(archive).hexdigest(),
                       "archive_bytes": len(archive)}
                with self.assertRaises(fixture.FixtureError):
                    fixture.provision(cache, pin)
                self.assertFalse((cache / "temporal-test-server").exists())

    def test_non_executable_wrong_architecture_and_linked_cache_are_rejected(self):
        target = self.cache / "temporal-test-server"
        target.write_bytes(self.binary)
        target.chmod(0o755)
        with patch.object(fixture.os, "access", return_value=False):
            with self.assertRaises(fixture.FixtureError):
                fixture.verify_binary(target, self.pin)
        wrong = b"Not ELF" + bytes(80)
        target.write_bytes(wrong)
        with self.assertRaises(fixture.FixtureError):
            fixture.verify_binary(target, {**self.pin, "binary_sha256": hashlib.sha256(wrong).hexdigest()})
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(fixture.FixtureError):
                fixture.provision(self.cache, self.pin)

    def test_environment_export_preserves_prior_entries_and_exact_pin(self):
        destination = self.root / "github-env"
        destination.write_text("RETAINED=true\n")
        binary = self.cache / "temporal-test-server"
        fixture.export_environment(destination, binary, self.pin)
        self.assertEqual(destination.read_text(), "RETAINED=true\n"
                         f"CASEOPS_TEST_TEMPORAL_SERVER_PATH={binary.resolve()}\n"
                         f"CASEOPS_TEST_TEMPORAL_SERVER_SHA256={self.pin['binary_sha256']}\n")

    def test_redirects_reject_downgrade_and_unreviewed_hosts(self):
        handler = fixture.OfficialRedirects()
        for url in ("http://github.com/tool", "https://example.com/tool", "https://github.com:8443/tool"):
            with self.subTest(url=url), self.assertRaises(fixture.FixtureError):
                handler.redirect_request(None, None, 302, "", {}, url)


if __name__ == "__main__":
    unittest.main()
