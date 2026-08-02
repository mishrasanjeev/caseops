from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from caseops_api.core.settings import get_settings
from caseops_api.db.models import UserDriveConnection
from caseops_api.db.session import get_session_factory
from caseops_api.services.drive_sync import (
    GOOGLE_DRIVE_SCOPES,
    GoogleDriveFileMetadata,
    GoogleDriveProvider,
    GoogleDriveRuntimeConfig,
    set_google_drive_provider_for_tests,
)
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company


class StubDriveProvider:
    def __init__(self) -> None:
        self.list_calls = 0

    @property
    def configured(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.example.test/drive?state={state}"

    def exchange_code(self, *, code: str) -> dict[str, object]:
        assert code == "drive-oauth-code"
        return {
            "token_payload": {
                "access_token": "drive-access-credential",
                "refresh_token": "drive-refresh-credential",
            },
            "provider_account_id": "drive-account-1",
            "display_email": "owner@drive.example",
            "scopes": list(GOOGLE_DRIVE_SCOPES),
        }

    def list_files(
        self,
        *,
        token_payload: dict[str, object],
        limit: int,
    ) -> list[GoogleDriveFileMetadata]:
        assert token_payload["access_token"] == "drive-access-credential"
        self.list_calls += 1
        return [
            GoogleDriveFileMetadata(
                provider_file_id="drive-file-1",
                name="Signed vakalatnama.pdf",
                mime_type="application/pdf",
                size_bytes=2048,
                modified_time=datetime(2026, 6, 8, tzinfo=UTC),
            )
        ][:limit]


class MissingDriveProvider:
    @property
    def configured(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return "Google Drive OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not build auth URLs")

    def exchange_code(self, *, code: str) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not exchange codes")

    def list_files(self, **kwargs) -> list[GoogleDriveFileMetadata]:  # pragma: no cover
        raise AssertionError("unavailable provider should not list files")


def _configure_drive_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_ID", "drive-client")
    monkeypatch.setenv("CASEOPS_GOOGLE_DRIVE_CLIENT_SECRET", "drive-secret")
    monkeypatch.setenv(
        "CASEOPS_GOOGLE_DRIVE_REDIRECT_URI",
        "https://api.caseops.ai/api/drive/google/callback",
    )
    get_settings.cache_clear()


def _connect_drive(client: TestClient, token: str, provider: StubDriveProvider) -> str:
    set_google_drive_provider_for_tests(provider)
    start = client.post("/api/drive/google/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["provider"] == "google_drive"
    assert body["provider_available"] is True
    assert "drive-access-credential" not in start.text
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]

    callback = client.get(
        "/api/drive/google/callback",
        headers=_auth(token),
        params={"code": "drive-oauth-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["connected"] is True
    assert callback.json()["connection"]["provider"] == "google_drive"
    assert "drive-access-credential" not in callback.text
    assert "drive-refresh-credential" not in callback.text
    return str(callback.json()["connection"]["id"])


def test_google_drive_status_and_start_fail_closed_without_config(
    client: TestClient,
) -> None:
    try:
        set_google_drive_provider_for_tests(MissingDriveProvider())
        bootstrap = _bootstrap_company(
            client,
            slug="drive-missing",
            email="owner@drive-missing.example",
        )
        token = str(bootstrap["access_token"])

        status_response = client.get("/api/drive/google/status", headers=_auth(token))
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["configured"] is False
        assert status_response.json()["missing_config_names"] == [
            "GOOGLE_DRIVE_CLIENT_ID",
            "GOOGLE_DRIVE_CLIENT_SECRET",
            "GOOGLE_DRIVE_REDIRECT_URI",
        ]

        start = client.post("/api/drive/google/start", headers=_auth(token))
        assert start.status_code == 200, start.text
        assert start.json()["provider_available"] is False
        assert start.json()["unavailable_reason"] == "Google Drive OAuth is not configured."
    finally:
        set_google_drive_provider_for_tests(None)


def test_google_drive_connect_list_revoke_is_token_safe(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = StubDriveProvider()
    purposes: list[str] = []
    monkeypatch.setattr(
        "caseops_api.api.routes.drive.require_recent_step_up",
        lambda *args, **kwargs: purposes.append(kwargs["purpose"]),
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-connect",
            email="owner@drive-connect.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_drive(client, token, provider)

        listed = client.get("/api/drive/google/files?limit=5", headers=_auth(token))
        assert listed.status_code == 200, listed.text
        assert listed.json()["files"][0]["name"] == "Signed vakalatnama.pdf"
        assert "drive-access-credential" not in listed.text
        assert "drive-refresh-credential" not in listed.text
        assert provider.list_calls == 1

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserDriveConnection, connection_id)
            assert connection is not None
            assert connection.encrypted_token_ref is not None
            assert "drive-access-credential" not in connection.encrypted_token_ref
            assert "drive-refresh-credential" not in connection.encrypted_token_ref

        revoked = client.delete(
            f"/api/drive/connections/{connection_id}",
            headers=_auth(token),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"
        assert "drive-access-credential" not in revoked.text
        assert purposes == ["connector_disconnect"]
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_drive_connections_are_cross_tenant_scoped(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = StubDriveProvider()
    try:
        boot_a = _bootstrap_company(
            client,
            slug="drive-tenant-a",
            email="owner@drive-tenant-a.example",
        )
        token_a = str(boot_a["access_token"])
        connection_id = _connect_drive(client, token_a, provider)

        boot_b = _bootstrap_company(
            client,
            slug="drive-tenant-b",
            email="owner@drive-tenant-b.example",
        )
        token_b = str(boot_b["access_token"])

        listed_b = client.get("/api/drive/google/files", headers=_auth(token_b))
        assert listed_b.status_code == 409, listed_b.text
        revoke_b = client.delete(
            f"/api/drive/connections/{connection_id}",
            headers=_auth(token_b),
        )
        assert revoke_b.status_code == 404, revoke_b.text
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_drive_provider_retries_transient_file_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        request = httpx.Request(method, url)
        if calls == 1:
            return httpx.Response(503, request=request, json={"error": "temporary"})
        return httpx.Response(
            200,
            request=request,
            json={"files": [{"id": "drive-file-1", "name": "Retried.pdf"}]},
        )

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = GoogleDriveProvider(
        GoogleDriveRuntimeConfig(
            client_id="drive-client",
            client_secret="drive-secret",
            redirect_uri="https://api.caseops.ai/api/drive/google/callback",
        )
    )

    files = provider.list_files(token_payload={"access_token": "drive-access"}, limit=5)

    assert [file.name for file in files] == ["Retried.pdf"]
    assert calls == 2
