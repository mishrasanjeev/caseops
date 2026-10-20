from __future__ import annotations

import os
import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock, patch

from drive_import_emulator import DriveImportEmulator, install_drive_import_emulator

# Real entrypoint/lifespan and authenticated HTTP assertions are promoted to
# ram-2026-10-08-drive.spec.ts against the already-running canonical API.

class DriveImportIsolationTests(unittest.TestCase):
    def fetch(self, emulator, fixture, **changes):
        return emulator.fetch_file(**{
            "token_payload": {"access_token": fixture.access_token}, "file_id": fixture.file_id,
            "expected": SimpleNamespace(
                provider_file_id=fixture.file_id, name=fixture.filename, mime_type="text/plain",
                size_bytes=len(fixture.content), modified_time=fixture.modified_time,
            ),
            "expected_version": fixture.modified_time.isoformat(),
            "max_size_bytes": 4096, "deadline": monotonic() + 10,
            **changes,
        })

    def test_install_rejects_non_e2e_and_cloud_before_touching_application(self) -> None:
        environment = {
            "CASEOPS_ENV": "e2e", "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
            "CASEOPS_PUBLIC_APP_URL": "http://127.0.0.1:3100",
            "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///offline-drive.db",
            "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        }
        for changes in (
            {"CASEOPS_ENV": "production"}, {"CASEOPS_ENV": "local"},
            {"CASEOPS_E2E_OAUTH_EMULATOR": ""}, {"K_SERVICE": "caseops-api"},
            {"K_REVISION": "release"}, {"K_CONFIGURATION": "release"},
            {"CLOUD_RUN_JOB": "release"}, {"GOOGLE_CLOUD_PROJECT": "production"},
            {"CASEOPS_PUBLIC_APP_URL": "https://caseops.ai"},
            {"CASEOPS_DATABASE_URL": "postgresql+psycopg://user:pass@production/caseops"},
        ):
            app = Mock()
            with self.subTest(changes=changes), patch.dict(os.environ, {**environment, **changes}, clear=True):
                with self.assertRaises((RuntimeError, ValueError)):
                    install_drive_import_emulator(app)
            app.include_router.assert_not_called()

    def test_provider_returns_exact_registered_bytes_only(self) -> None:
        emulator = DriveImportEmulator()
        fixture = emulator.register()
        self.assertEqual(self.fetch(emulator, fixture), fixture.content)
        self.assertEqual(emulator.evidence(fixture.file_id)["fetch_calls"], 1)

    def test_provider_does_not_allow_cross_fixture_tokens(self) -> None:
        emulator = DriveImportEmulator()
        first, second = emulator.register(), emulator.register()
        for file_id, token in ((first.file_id, second.access_token), ("unknown", first.access_token)):
            with self.subTest(file_id=file_id), self.assertRaises(RuntimeError):
                self.fetch(emulator, first, token_payload={"access_token": token}, file_id=file_id)
        self.assertEqual(emulator.evidence(first.file_id)["fetch_calls"], 0)

    def test_provider_cannot_authorize_exchange_or_browse_google(self) -> None:
        emulator = DriveImportEmulator()
        with self.assertRaises(RuntimeError):
            emulator.authorization_url(state="anything")
        with self.assertRaises(RuntimeError):
            emulator.exchange_code(code="anything")
        with self.assertRaises(RuntimeError):
            emulator.list_files(token_payload={}, limit=1)

    def test_fixture_inventory_is_bounded(self) -> None:
        emulator = DriveImportEmulator()
        for _ in range(128):
            emulator.register()
        with self.assertRaises(RuntimeError):
            emulator.register()

    def test_provider_enforces_the_captured_version_size_and_deadline(self) -> None:
        emulator = DriveImportEmulator()
        fixture = emulator.register()
        for changes in (
            {"expected_version": "different-version"}, {"max_size_bytes": 1},
            {"deadline": monotonic() - 1},
        ):
            with self.subTest(changes=changes), self.assertRaises(RuntimeError):
                self.fetch(emulator, fixture, **changes)
        self.assertEqual(emulator.evidence(fixture.file_id)["fetch_calls"], 0)

if __name__ == "__main__":
    unittest.main()
