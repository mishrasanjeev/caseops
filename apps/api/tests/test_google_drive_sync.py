from __future__ import annotations

from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime
from hashlib import md5
from time import monotonic
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    DocumentProcessingJob,
    DriveConnectionStatus,
    DriveFileCandidate,
    MatterActivity,
    MatterAttachment,
    UserDriveConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.calendar_sync import _decrypt_token_payload
from caseops_api.services.drive_sync import (
    GOOGLE_DRIVE_SCOPES,
    GoogleDriveFileMetadata,
    GoogleDriveProvider,
    GoogleDriveProviderError,
    GoogleDriveRuntimeConfig,
    set_google_drive_provider_for_tests,
)
from caseops_api.services.google_workspace import GoogleWorkspaceTokenRefreshError
from tests.test_google_drive_imports import _create_matter
from tests.test_legalworkspace_calendar_sync import _auth, _bootstrap_company


class StubDriveProvider:
    def __init__(self) -> None:
        self.list_calls = 0
        self.fetch_calls = 0

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

    def fetch_file(self, *, token_payload, file_id, **kwargs):
        self.fetch_calls += 1
        assert token_payload["access_token"] == "drive-access-credential"
        assert file_id == "drive-file-1"
        return b"Reviewed Drive file evidence"


class ReviewedDriveProvider(StubDriveProvider):
    def list_files(self, *, token_payload, limit):
        return [
            GoogleDriveFileMetadata(
                provider_file_id="drive-file-1",
                name="Reviewed evidence.txt",
                mime_type="text/plain",
                size_bytes=len(b"Reviewed Drive file evidence"),
                modified_time=datetime(2026, 10, 8, tzinfo=UTC),
            )
        ][:limit]


def test_google_drive_review_import_publishes_atomic_attachment(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from caseops_api.services import document_storage, virus_scan

    _configure_drive_env(monkeypatch)
    monkeypatch.setattr(document_storage, "_storage_backend", lambda: "local")
    monkeypatch.setattr(document_storage, "_document_root", lambda: tmp_path)
    monkeypatch.setattr(
        virus_scan,
        "scan_file_for_viruses",
        lambda _: virus_scan.ScanResult(status="clean", signature=None),
    )
    provider = ReviewedDriveProvider()
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-reviewed-content",
            email="owner@drive-content.example",
        )
        token = str(bootstrap["access_token"])
        matter_id = _create_matter(client, token, "DRIVE-REVIEW-001")
        connection_id = _connect_drive(client, token, provider)
        synced = client.post(
            "/api/drive/google/candidates/sync",
            headers=_auth(token),
            json={},
        )
        assert synced.status_code == 200, synced.text
        with get_session_factory()() as session:
            candidate = session.scalar(
                select(DriveFileCandidate).where(
                    DriveFileCandidate.drive_connection_id == connection_id,
                )
            )
            candidate_id = candidate.id
        reviewed = client.patch(
            f"/api/drive/candidates/{candidate_id}",
            headers=_auth(token),
            json={"action": "import_file", "matter_id": matter_id},
        )
        if reviewed.status_code == 502:
            with get_session_factory()() as session:
                failure = session.get(DriveFileCandidate, candidate_id).last_error_redacted
                assert "unexpected keyword argument 'context'" in failure, failure
        assert reviewed.status_code == 200, reviewed.text
        attachment_id = reviewed.json()["imported_attachment_id"]
        with get_session_factory()() as session:
            candidate = session.get(DriveFileCandidate, candidate_id)
            assert candidate.status == "content_imported"
            assert candidate.linked_matter_id == matter_id
            assert candidate.imported_attachment_id == attachment_id
            attachment = session.get(MatterAttachment, attachment_id)
            assert attachment.matter_id == matter_id
            assert (
                tmp_path / attachment.storage_key
            ).read_bytes() == b"Reviewed Drive file evidence"
            jobs = list(
                session.scalars(
                    select(DocumentProcessingJob).where(
                        DocumentProcessingJob.attachment_id == attachment_id,
                    )
                )
            )
            assert len(jobs) == 1
            assert jobs[0].action == "initial_index"
            assert jobs[0].target_type == "matter_attachment"
            assert (
                len(
                    list(
                        session.scalars(
                            select(MatterActivity.id).where(
                                MatterActivity.matter_id == matter_id,
                                MatterActivity.event_type == "drive_file_attachment_added",
                            )
                        )
                    )
                )
                == 1
            )
            assert (
                len(
                    list(
                        session.scalars(
                            select(AuditEvent.id).where(
                                AuditEvent.target_id == candidate_id,
                                AuditEvent.action == "drive.candidate.imported",
                            )
                        )
                    )
                )
                == 1
            )
        duplicate = client.patch(
            f"/api/drive/candidates/{candidate_id}",
            headers=_auth(token),
            json={"action": "import_file", "matter_id": matter_id},
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["imported_attachment_id"] == attachment_id
        assert provider.fetch_calls == 1
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


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


class ExpiredOnceDriveProvider(StubDriveProvider):
    def list_files(
        self,
        *,
        token_payload: dict[str, object],
        limit: int,
    ) -> list[GoogleDriveFileMetadata]:
        self.list_calls += 1
        if self.list_calls == 1:
            raise GoogleDriveProviderError("expired access token", status_code=401)
        assert token_payload["access_token"] == "drive-refreshed-access"
        return [
            GoogleDriveFileMetadata(
                provider_file_id="drive-refreshed-file",
                name="Refreshed Drive file.pdf",
                mime_type="application/pdf",
                size_bytes=1024,
                modified_time=datetime(2026, 6, 8, tzinfo=UTC),
            )
        ][:limit]


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


def test_google_drive_sync_refreshes_expired_access_token_and_persists_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = ExpiredOnceDriveProvider()
    monkeypatch.setattr(
        "caseops_api.services.drive_sync.refresh_google_workspace_access_token",
        lambda session, **kwargs: {
            **kwargs["token_payload"],
            "access_token": "drive-refreshed-access",
        },
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-refresh-recovery",
            email="owner@drive-refresh.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_drive(client, token, provider)

        response = client.post(
            "/api/drive/google/candidates/sync",
            headers=_auth(token),
            json={"limit": 5},
        )
        assert response.status_code == 200, response.text
        assert provider.list_calls == 2
        assert response.json()["created_count"] == 1

        with get_session_factory()() as session:
            connection = session.get(UserDriveConnection, connection_id)
            assert connection is not None
            assert connection.status == DriveConnectionStatus.CONNECTED
            refreshed = _decrypt_token_payload(connection.encrypted_token_ref)
            assert refreshed["access_token"] == "drive-refreshed-access"
            assert refreshed["refresh_token"] == "drive-refresh-credential"
            assert "drive-refreshed-access" not in connection.encrypted_token_ref
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_drive_file_browser_refreshes_expired_access_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = ExpiredOnceDriveProvider()
    monkeypatch.setattr(
        "caseops_api.services.drive_sync.refresh_google_workspace_access_token",
        lambda session, **kwargs: {
            **kwargs["token_payload"],
            "access_token": "drive-refreshed-access",
        },
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-browser-refresh",
            email="owner@drive-browser-refresh.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_drive(client, token, provider)

        response = client.get("/api/drive/google/files?limit=5", headers=_auth(token))

        assert response.status_code == 200, response.text
        assert response.json()["files"][0]["name"] == "Refreshed Drive file.pdf"
        assert provider.list_calls == 2
        with get_session_factory()() as session:
            connection = session.get(UserDriveConnection, connection_id)
            assert connection is not None
            assert connection.status == DriveConnectionStatus.CONNECTED
            payload = _decrypt_token_payload(connection.encrypted_token_ref)
            assert payload["access_token"] == "drive-refreshed-access"
            assert payload["refresh_token"] == "drive-refresh-credential"
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_drive_transient_sync_failure_does_not_disable_connection(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = StubDriveProvider()
    provider.list_files = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        GoogleDriveProviderError("provider unavailable", status_code=503)
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-refresh-transient",
            email="owner@drive-transient.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_drive(client, token, provider)
        response = client.post(
            "/api/drive/google/candidates/sync",
            headers=_auth(token),
            json={"limit": 5},
        )
        assert response.status_code == 502
        assert "try again" in response.json()["detail"].lower()
        with get_session_factory()() as session:
            connection = session.get(UserDriveConnection, connection_id)
            assert connection is not None
            assert connection.status == DriveConnectionStatus.CONNECTED
    finally:
        set_google_drive_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_drive_invalid_refresh_requires_reauthorization(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_drive_env(monkeypatch)
    provider = ExpiredOnceDriveProvider()
    monkeypatch.setattr(
        "caseops_api.services.drive_sync.refresh_google_workspace_access_token",
        lambda session, **kwargs: (_ for _ in ()).throw(
            GoogleWorkspaceTokenRefreshError(
                "Google authorization expired or was revoked. Reconnect this account.",
                reauthorization_required=True,
            )
        ),
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="drive-refresh-revoked",
            email="owner@drive-revoked.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_drive(client, token, provider)
        response = client.post(
            "/api/drive/google/candidates/sync",
            headers=_auth(token),
            json={"limit": 5},
        )
        assert response.status_code == 409
        assert "Reconnect this account" in response.json()["detail"]
        with get_session_factory()() as session:
            connection = session.get(UserDriveConnection, connection_id)
            assert connection is not None
            assert connection.status == DriveConnectionStatus.ERROR
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


@pytest.mark.parametrize("operation", ["list", "fetch"])
def test_google_drive_provider_preserves_unauthorized_status_for_safe_reads(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    def unauthorized_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(401, request=httpx.Request(method, url), json={"error": "expired"})

    monkeypatch.setattr(httpx, "request", unauthorized_request)
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda method, url, **kwargs: nullcontext(unauthorized_request(method, url)),
    )
    provider = GoogleDriveProvider(
        GoogleDriveRuntimeConfig(
            client_id="drive-client",
            client_secret="drive-secret",
            redirect_uri="https://api.caseops.ai/api/drive/google/callback",
        )
    )

    with pytest.raises(GoogleDriveProviderError) as raised:
        if operation == "list":
            provider.list_files(token_payload={"access_token": "expired"}, limit=5)
        else:
            provider.fetch_file(
                token_payload={"access_token": "expired"},
                file_id="drive-file-id",
            )

    assert raised.value.status_code == 401


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "no_checksum",
        "stale",
        "changed_during",
        "checksum",
        "native",
        "name",
        "mime",
        "size",
        "unknown_version",
        "missing_version",
        "trashed",
        "oversized_metadata",
        "oversized_body",
        "deadline",
        "429",
        "503",
    ],
)
def test_google_drive_reviewed_stream_is_bounded_and_source_pinned(monkeypatch, case):
    import json

    content = b"Reviewed Drive file evidence"
    stamp = datetime(2026, 10, 8, tzinfo=UTC)
    metadata = {
        "id": "source-file",
        "name": "evidence.txt",
        "mimeType": "text/plain",
        "size": str(len(content)),
        "modifiedTime": stamp.isoformat(),
        "version": "17",
        "md5Checksum": md5(content, usedforsecurity=False).hexdigest(),
        "trashed": False,
    }
    expected = GoogleDriveFileMetadata(
        provider_file_id="source-file",
        name="evidence.txt",
        mime_type="text/plain",
        size_bytes=len(content),
        modified_time=stamp,
    )
    if case == "no_checksum":
        metadata.pop("md5Checksum")
    elif case == "stale":
        metadata["modifiedTime"] = "2026-10-09T00:00:00+00:00"
    elif case == "checksum":
        metadata["md5Checksum"] = "0" * 32
    elif case == "native":
        metadata["mimeType"] = "application/vnd.google-apps.document"
    elif case == "name":
        metadata["name"] = "changed.txt"
    elif case == "mime":
        metadata["mimeType"] = "application/pdf"
    elif case == "size":
        metadata["size"] = str(len(content) + 1)
    elif case == "missing_version":
        metadata.pop("version")
    elif case == "trashed":
        metadata["trashed"] = True
    calls, yielded = [], []

    class Chunks(httpx.SyncByteStream):
        def __init__(self, chunks):
            self.chunks = chunks

        def __iter__(self):
            for chunk in self.chunks:
                yielded.append(len(chunk))
                yield chunk

    def stream(method, url, *, headers, params, timeout):
        calls.append(dict(params))
        assert method == "GET"
        assert url == "https://www.googleapis.com/drive/v3/files/source-file"
        assert headers["Authorization"] == "Bearer current-access"
        assert 0 < timeout.read <= 1
        assert 0 < timeout.connect <= 5
        assert headers["Accept-Encoding"] == "identity"
        request = httpx.Request(method, url)
        if case in {"429", "503"}:
            return nullcontext(httpx.Response(int(case), request=request))
        if params.get("alt") == "media":
            chunks = [content]
            if case == "oversized_body":
                chunks = [b"x" * 65536, b"unreachable"]
        else:
            current = dict(metadata)
            if case == "changed_during" and len(calls) == 3:
                current["version"] = "18"
            chunks = [json.dumps(current).encode()]
            if case == "oversized_metadata":
                chunks = [b"x" * 65536, b"x", b"unreachable"]
        return nullcontext(httpx.Response(200, request=request, stream=Chunks(chunks)))

    monkeypatch.setattr(httpx, "stream", stream)
    monkeypatch.setattr(
        httpx, "request", lambda *a, **kw: pytest.fail("Unexpected retry transport")
    )
    provider = GoogleDriveProvider(GoogleDriveRuntimeConfig("client", "secret", "redirect"))

    def fetch():
        return provider.fetch_file(
            token_payload={"access_token": "current-access"},
            file_id="source-file",
            expected=expected,
            expected_version="metadata" if case == "unknown_version" else stamp.isoformat(),
            max_size_bytes=1024,
            deadline=monotonic() - 1 if case == "deadline" else monotonic() + 30,
        )

    if case in {"valid", "no_checksum"}:
        assert fetch() == content
        assert len(calls) == 3
    elif case in {"deadline", "429", "503"}:
        with pytest.raises(GoogleDriveProviderError) as error:
            fetch()
        assert error.value.status_code == (int(case) if case != "deadline" else None)
        assert len(calls) == (0 if case == "deadline" else 1)
    else:
        with pytest.raises(HTTPException) as error:
            fetch()
        assert error.value.status_code == (413 if case.startswith("oversized") else 409)
        if case == "oversized_body":
            assert yielded[-1] == 65536
        elif case == "oversized_metadata":
            assert yielded == [65536, 1]
        assert len(calls) == (
            3 if case in {"changed_during", "checksum"} else 2 if case == "oversized_body" else 1
        )


@pytest.mark.parametrize("boundary", ["metadata", "body", "post_metadata", "refresh"])
def test_google_drive_deadline_charges_each_raw_transport_piece(monkeypatch, boundary):
    import json

    from caseops_api.services import drive_sync

    now, calls, pieces, closed = [0.0], [], [], []
    stamp = datetime(2026, 10, 8, tzinfo=UTC)
    metadata = {
        "id": "source-file",
        "name": "evidence.txt",
        "mimeType": "text/plain",
        "size": "100",
        "modifiedTime": stamp.isoformat(),
        "version": "17",
        "trashed": False,
    }

    class Body(httpx.SyncByteStream):
        def __init__(self, data, slow):
            self.data, self.slow = data, slow

        def __iter__(self):
            if self.slow:
                for _ in range(100):
                    now[0] += 1
                    pieces.append(now[0])
                    yield b"x"
            else:
                yield self.data

        def close(self):
            closed.append(True)

    @contextmanager
    def stream(method, url, **kwargs):
        calls.append(method)
        assert kwargs["timeout"].read <= 1
        assert kwargs["timeout"].connect <= 5
        phase = (
            "refresh"
            if method == "POST"
            else "metadata"
            if len(calls) == 1
            else "body"
            if len(calls) == 2
            else "post_metadata"
        )
        data = b"x" * 100 if phase == "body" else json.dumps(metadata).encode()
        response = httpx.Response(
            200, request=httpx.Request(method, url), stream=Body(data, phase == boundary)
        )
        try:
            yield response
        finally:
            response.close()

    monkeypatch.setattr(drive_sync, "monotonic", lambda: now[0])
    monkeypatch.setattr(httpx, "stream", stream)
    runtime = GoogleDriveRuntimeConfig("client", "secret", "redirect")
    if boundary == "refresh":
        with pytest.raises(GoogleWorkspaceTokenRefreshError, match="temporarily unavailable"):
            drive_sync._refresh_drive_import_token(
                runtime=runtime, token_payload={"refresh_token": "refresh"}, deadline=5
            )
    else:
        with pytest.raises(GoogleDriveProviderError, match="timed out"):
            GoogleDriveProvider(runtime).fetch_file(
                token_payload={"access_token": "access"},
                file_id="source-file",
                expected=GoogleDriveFileMetadata(
                    "source-file", "evidence.txt", "text/plain", 100, stamp
                ),
                expected_version=stamp.isoformat(),
                max_size_bytes=1024,
                deadline=5,
            )
    assert pieces == [1, 2, 3, 4, 5]
    assert now[0] == 5
    assert len(closed) == len(calls)
