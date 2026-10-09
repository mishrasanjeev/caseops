from __future__ import annotations

import os
import importlib
import unittest
from time import monotonic
from types import SimpleNamespace
from unittest.mock import Mock, patch

from drive_import_emulator import DriveImportEmulator, install_drive_import_emulator


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

    def test_actual_entrypoint_starts_and_resolves_authenticated_fixture_routes(self) -> None:
        environment = {
            "CASEOPS_ENV": "e2e", "CASEOPS_E2E_OAUTH_EMULATOR": "calendar-20261008",
            "CASEOPS_PUBLIC_APP_URL": "http://127.0.0.1:3100",
            "CASEOPS_DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "CASEOPS_AUTO_MIGRATE": "false",
            "CASEOPS_AUTH_SECRET": "offline-drive-entrypoint-unit-secret-at-least-32-characters",
        }
        with patch.dict(os.environ, environment, clear=True):
            entrypoint = importlib.import_module("oauth_emulator_api")
            from fastapi.testclient import TestClient
            from caseops_api.db.session import get_db_session
            from caseops_api.services.calendar_sync import GoogleCalendarProvider
            from caseops_api.services.drive_sync import set_google_drive_provider_for_tests

            app = entrypoint.app
            routes = [route for route in app.routes if route.path.startswith("/_e2e/drive-import/")]
            self.assertEqual(len(routes), 2)
            seed = next(route for route in routes if "POST" in route.methods)
            self.assertEqual(seed.endpoint.__annotations__["payload"].__name__, "FixtureRequest")
            self.assertFalse(any(isinstance(value, str) for value in seed.endpoint.__annotations__.values()))
            headers = {
                "X-CaseOps-Automated-Test": "no-paid-providers",
                "Authorization": "Bearer invalid-offline-token",
            }
            body = {"matter_id": "00000000-0000-0000-0000-000000000001"}
            try:
                # Keep startup's real mapper/lifespan work, but never resolve a model in a unit test.
                with patch("caseops_api.main.warm_reranker", return_value=None) as warm, TestClient(app) as client:
                    self.assertEqual(client.get("/_e2e/calendar-oauth/health").status_code, 200)
                    unmarked = client.post(seed.path, headers={"Authorization": headers["Authorization"]}, json=body)
                    self.assertEqual(unmarked.status_code, 403)
                    self.assertIn("no-paid-provider marker", unmarked.json()["detail"])
                    self.assertEqual(client.post(seed.path, headers=headers, json=body).status_code, 401)
                    self.assertEqual(client.get(seed.path + "/unknown", headers=headers).status_code, 401)
                    owner = next(dependency.call for dependency in seed.dependant.dependencies if dependency.name == "context")
                    app.dependency_overrides[owner] = lambda: SimpleNamespace(
                        membership=SimpleNamespace(role="owner"), company=SimpleNamespace(slug="ordinary-tenant"),
                    )
                    app.dependency_overrides[get_db_session] = lambda: None
                    self.assertEqual(client.post(seed.path, headers=headers, json={"matter_id": "short"}).status_code, 422)
                    self.assertEqual(client.post(seed.path, headers=headers, json=body).status_code, 403)
                warm.assert_called_once()
            finally:
                app.dependency_overrides.clear()
                entrypoint.emulator.stop()
                entrypoint.httpx.Client.send = entrypoint.original_send
                GoogleCalendarProvider.authorization_url = entrypoint.original_authorization_url
                set_google_drive_provider_for_tests(None)


if __name__ == "__main__":
    unittest.main()
