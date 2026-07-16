"""Gmail mailbox connector regression coverage.

The tests use a local provider double only. They never call Google APIs and
assert that Gmail metadata import stays token-safe, tenant-scoped,
matter-access-aware, and review-first for attachments.
"""
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditEvent,
    Communication,
    MailboxAttachmentCandidate,
    MailboxAttachmentCandidateStatus,
    MailboxImportStatus,
    MailboxMessageImport,
    MailboxWebhookEvent,
    MailboxWebhookStatus,
    Matter,
    UserMailboxConnection,
)
from caseops_api.db.session import get_session_factory
from caseops_api.services.gmail_sync import (
    GMAIL_SCOPES,
    GmailAttachmentMetadata,
    GmailMessageMetadata,
    GmailRuntimeConfig,
    GoogleGmailProvider,
    set_gmail_provider_for_tests,
)
from tests.test_legalworkspace_calendar_sync import (
    _auth,
    _bootstrap_company,
    _create_matter,
)


class StubGmailProvider:
    def __init__(
        self,
        *,
        display_email: str = "owner@gmail.example",
        messages: list[GmailMessageMetadata] | None = None,
        history_messages: list[GmailMessageMetadata] | None = None,
    ) -> None:
        self.display_email = display_email
        self.messages = messages or []
        self.history_messages = history_messages or []
        self.recent_calls: list[int] = []
        self.history_calls: list[str] = []
        self.watch_calls = 0
        self.fetch_calls: list[dict[str, str]] = []

    @property
    def configured(self) -> bool:
        return True

    @property
    def webhook_configured(self) -> bool:
        return True

    @property
    def unavailable_reason(self) -> str | None:
        return None

    def authorization_url(self, *, state: str) -> str:
        return f"https://accounts.google.example.test/gmail?state={state}"

    def exchange_code(self, *, code: str) -> dict[str, object]:
        assert code == "gmail-oauth-code"
        return {
            "token_payload": {
                "access_token": "gmail-access-credential",
                "refresh_token": "gmail-refresh-credential",
            },
            "provider_account_id": self.display_email,
            "display_email": self.display_email,
            "history_id": "history-1",
            "scopes": list(GMAIL_SCOPES),
        }

    def list_recent_messages(
        self,
        *,
        token_payload: dict[str, object],
        limit: int,
    ) -> list[GmailMessageMetadata]:
        assert token_payload["access_token"] == "gmail-access-credential"
        self.recent_calls.append(limit)
        return self.messages[:limit]

    def list_history_messages(
        self,
        *,
        token_payload: dict[str, object],
        start_history_id: str,
        limit: int,
    ) -> list[GmailMessageMetadata]:
        assert token_payload["access_token"] == "gmail-access-credential"
        self.history_calls.append(start_history_id)
        return self.history_messages[:limit]

    def start_watch(self, *, token_payload: dict[str, object]) -> dict[str, object]:
        assert token_payload["access_token"] == "gmail-access-credential"
        self.watch_calls += 1
        expires = int((datetime.now(UTC) + timedelta(days=1)).timestamp() * 1000)
        return {
            "historyId": "history-watch",
            "expiration": str(expires),
            "resourceId": "gmail-resource-secret",
        }

    def fetch_attachment(
        self,
        *,
        token_payload: dict[str, object],
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        assert token_payload["access_token"] == "gmail-access-credential"
        self.fetch_calls.append(
            {"message_id": message_id, "attachment_id": attachment_id}
        )
        return b"safe attachment bytes"


class MissingGmailProvider:
    @property
    def configured(self) -> bool:
        return False

    @property
    def webhook_configured(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str | None:
        return "Gmail OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:  # pragma: no cover
        raise AssertionError("unavailable provider should not build auth URLs")

    def exchange_code(self, *, code: str) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not exchange codes")

    def list_recent_messages(self, **kwargs) -> list[GmailMessageMetadata]:  # pragma: no cover
        raise AssertionError("unavailable provider should not import")

    def list_history_messages(self, **kwargs) -> list[GmailMessageMetadata]:  # pragma: no cover
        raise AssertionError("unavailable provider should not process webhooks")

    def start_watch(self, **kwargs) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("unavailable provider should not start watch")

    def fetch_attachment(self, **kwargs) -> bytes:  # pragma: no cover
        raise AssertionError("unavailable provider should not fetch attachments")


def _message(
    *,
    message_id: str,
    subject: str,
    snippet: str,
    sender_email: str = "client@example.com",
    attachments: tuple[GmailAttachmentMetadata, ...] = (),
    history_id: str = "history-message",
) -> GmailMessageMetadata:
    return GmailMessageMetadata(
        provider_message_id=message_id,
        provider_thread_id=f"thread-{message_id}",
        history_id=history_id,
        subject=subject,
        sender_email=sender_email,
        sender_name="Client Sender",
        received_at=datetime(2026, 6, 8, 10, 0, tzinfo=UTC),
        snippet=snippet,
        labels=("INBOX",),
        attachments=attachments,
    )


def _connect_gmail(
    client: TestClient,
    token: str,
    provider: StubGmailProvider,
) -> str:
    set_gmail_provider_for_tests(provider)
    start = client.post("/api/mailbox/gmail/start", headers=_auth(token))
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["provider"] == "gmail"
    assert body["provider_available"] is True
    assert "gmail-access-credential" not in start.text
    state = parse_qs(urlparse(body["auth_url"]).query)["state"][0]

    callback = client.get(
        "/api/mailbox/gmail/callback",
        headers=_auth(token),
        params={"code": "gmail-oauth-code", "state": state},
    )
    assert callback.status_code == 200, callback.text
    assert callback.json()["connected"] is True
    assert callback.json()["connection"]["provider"] == "gmail"
    assert "gmail-access-credential" not in callback.text
    assert "gmail-refresh-credential" not in callback.text
    return str(callback.json()["connection"]["id"])


def _webhook_payload(email: str, history_id: str) -> dict[str, object]:
    encoded = base64.b64encode(
        json.dumps({"emailAddress": email, "historyId": history_id}).encode("utf-8")
    ).decode("ascii")
    return {"message": {"data": encoded, "messageId": "pubsub-1"}}


def test_gmail_status_and_start_fail_closed_without_config(
    client: TestClient,
) -> None:
    try:
        set_gmail_provider_for_tests(MissingGmailProvider())
        bootstrap = _bootstrap_company(
            client,
            slug="gmail-missing",
            email="owner@gmail-missing.example",
        )
        token = str(bootstrap["access_token"])

        status_response = client.get("/api/mailbox/gmail/status", headers=_auth(token))
        assert status_response.status_code == 200, status_response.text
        assert status_response.json()["configured"] is False
        assert status_response.json()["missing_config_names"] == [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REDIRECT_URI",
        ]

        start = client.post("/api/mailbox/gmail/start", headers=_auth(token))
        assert start.status_code == 200, start.text
        assert start.json()["provider_available"] is False
        assert start.json()["unavailable_reason"] == "Gmail OAuth is not configured."
        assert "gmail-access-credential" not in start.text
    finally:
        set_gmail_provider_for_tests(None)


def test_gmail_import_is_metadata_only_review_first_and_token_safe(
    client: TestClient,
) -> None:
    attachment = GmailAttachmentMetadata(
        attachment_id="provider-attachment-secret",
        filename="evidence.txt",
        content_type="text/plain",
        size_bytes=21,
    )
    provider = StubGmailProvider(
        messages=[
            _message(
                message_id="msg-1",
                subject="Update on GMAIL-IMPORT",
                snippet="Please review GMAIL-IMPORT before tomorrow.",
                attachments=(attachment,),
            ),
            _message(
                message_id="msg-2",
                subject="No matching matter",
                snippet="This should stay unmatched.",
            ),
        ],
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="gmail-import",
            email="owner@gmail-import.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_gmail(client, token, provider)
        matter = _create_matter(client, token, "GMAIL-IMPORT")

        response = client.post(
            "/api/mailbox/gmail/import",
            headers=_auth(token),
            json={"limit": 10},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["summary"] == {
            "imported": 1,
            "unmatched": 1,
            "duplicate": 0,
            "failed": 0,
            "attachment_candidates": 1,
        }
        assert provider.fetch_calls == []
        assert "gmail-access-credential" not in response.text
        assert "gmail-refresh-credential" not in response.text
        assert "client@example.com" not in response.text

        candidates = client.get(
            "/api/mailbox/attachment-candidates",
            headers=_auth(token),
        )
        assert candidates.status_code == 200, candidates.text
        assert candidates.json()["pending_count"] == 1
        candidate_id = candidates.json()["candidates"][0]["id"]
        assert candidates.json()["candidates"][0]["matter_id"] == matter["id"]
        assert "provider-attachment-secret" not in candidates.text

        reject = client.patch(
            f"/api/mailbox/attachment-candidates/{candidate_id}",
            headers=_auth(token),
            json={"action": "reject"},
        )
        assert reject.status_code == 200, reject.text
        assert reject.json()["candidate"]["status"] == "rejected"
        assert provider.fetch_calls == []

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserMailboxConnection, connection_id)
            assert connection is not None
            assert connection.encrypted_token_ref is not None
            assert "gmail-access-credential" not in connection.encrypted_token_ref
            assert "gmail-refresh-credential" not in connection.encrypted_token_ref

            communication = session.scalar(
                select(Communication).where(Communication.matter_id == matter["id"])
            )
            assert communication is not None
            assert communication.recipient_email is None
            assert communication.body == "Please review GMAIL-IMPORT before tomorrow."
            metadata = communication.metadata_json or {}
            assert metadata["source"] == "gmail_provider_import"
            assert metadata["automation_mode"] == "provider_review_first"
            assert "client@example.com" not in json.dumps(metadata)

            candidate = session.get(MailboxAttachmentCandidate, candidate_id)
            assert candidate is not None
            assert candidate.status == MailboxAttachmentCandidateStatus.REJECTED
            assert candidate.encrypted_provider_attachment_ref is not None
            assert "provider-attachment-secret" not in (
                candidate.encrypted_provider_attachment_ref
            )
    finally:
        set_gmail_provider_for_tests(None)


def test_disposed_matter_blocks_gmail_attachment_fetch_and_persistence(
    client: TestClient,
) -> None:
    provider = StubGmailProvider(
        messages=[
            _message(
                message_id="msg-disposed-attachment",
                subject="Evidence for GMAIL-DISPOSED",
                snippet="Review the attached evidence.",
                attachments=(
                    GmailAttachmentMetadata(
                        attachment_id="provider-disposed-secret",
                        filename="disposed-evidence.txt",
                        content_type="text/plain",
                        size_bytes=21,
                    ),
                ),
            )
        ],
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="gmail-disposed",
            email="owner@gmail-disposed.example",
        )
        token = str(bootstrap["access_token"])
        _connect_gmail(client, token, provider)
        matter = _create_matter(client, token, "GMAIL-DISPOSED")

        imported = client.post(
            "/api/mailbox/gmail/import",
            headers=_auth(token),
            json={"limit": 10},
        )
        assert imported.status_code == 200, imported.text
        candidates = client.get(
            "/api/mailbox/attachment-candidates",
            headers=_auth(token),
        )
        assert candidates.status_code == 200, candidates.text
        candidate_id = candidates.json()["candidates"][0]["id"]

        factory = get_session_factory()
        with factory() as session:
            db_matter = session.get(Matter, str(matter["id"]))
            assert db_matter is not None
            db_matter.status = "disposed"
            db_matter.is_active = False
            session.commit()

        approved = client.patch(
            f"/api/mailbox/attachment-candidates/{candidate_id}",
            headers=_auth(token),
            json={"action": "approve_import"},
        )
        assert approved.status_code == 409, approved.text
        assert "disposed" in approved.text.lower()
        assert provider.fetch_calls == []

        with factory() as session:
            candidate = session.get(MailboxAttachmentCandidate, candidate_id)
            assert candidate is not None
            assert candidate.status == MailboxAttachmentCandidateStatus.NEEDS_REVIEW
            assert candidate.imported_attachment_id is None
    finally:
        set_gmail_provider_for_tests(None)


def test_gmail_connection_revoke_is_token_safe(client: TestClient) -> None:
    provider = StubGmailProvider()
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="gmail-revoke",
            email="owner@gmail-revoke.example",
        )
        token = str(bootstrap["access_token"])
        connection_id = _connect_gmail(client, token, provider)

        revoked = client.delete(
            f"/api/mailbox/connections/{connection_id}",
            headers=_auth(token),
        )
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["id"] == connection_id
        assert revoked.json()["provider"] == "gmail"
        assert revoked.json()["status"] == "revoked"
        assert "gmail-access-credential" not in revoked.text
        assert "gmail-refresh-credential" not in revoked.text

        factory = get_session_factory()
        with factory() as session:
            connection = session.get(UserMailboxConnection, connection_id)
            assert connection is not None
            assert connection.encrypted_token_ref is None
            audit = session.scalar(
                select(AuditEvent)
                .where(
                    AuditEvent.action == "mailbox.gmail.revoked",
                    AuditEvent.company_id == str(bootstrap["company"]["id"]),
                )
                .order_by(AuditEvent.created_at.desc())
            )
            assert audit is not None
            assert "gmail-access-credential" not in (audit.metadata_json or "")
    finally:
        set_gmail_provider_for_tests(None)


def test_gmail_imports_are_cross_tenant_scoped(client: TestClient) -> None:
    provider = StubGmailProvider(
        messages=[
            _message(
                message_id="msg-tenant-a",
                subject="GMAIL-TEN-A update",
                snippet="GMAIL-TEN-A matched message.",
            )
        ],
    )
    try:
        boot_a = _bootstrap_company(
            client,
            slug="gmail-tenant-a",
            email="owner@gmail-tenant-a.example",
        )
        token_a = str(boot_a["access_token"])
        _connect_gmail(client, token_a, provider)
        _create_matter(client, token_a, "GMAIL-TEN-A")
        imported = client.post(
            "/api/mailbox/gmail/import",
            headers=_auth(token_a),
            json={"limit": 5},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["summary"]["imported"] == 1

        boot_b = _bootstrap_company(
            client,
            slug="gmail-tenant-b",
            email="owner@gmail-tenant-b.example",
        )
        token_b = str(boot_b["access_token"])
        listed_b = client.get("/api/mailbox/imports", headers=_auth(token_b))
        assert listed_b.status_code == 200, listed_b.text
        assert listed_b.json()["summary"]["imported"] == 0
        assert "GMAIL-TEN-A" not in listed_b.text
    finally:
        set_gmail_provider_for_tests(None)


def test_gmail_watch_and_webhook_are_token_verified_and_idempotent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CASEOPS_GMAIL_PUBSUB_TOPIC", "projects/caseops/topics/gmail")
    monkeypatch.setenv("CASEOPS_GMAIL_WEBHOOK_VERIFICATION_TOKEN", "webhook-token")
    get_settings.cache_clear()

    provider = StubGmailProvider(
        display_email="owner@gmail-webhook.example",
        history_messages=[
            _message(
                message_id="msg-webhook",
                subject="Webhook for GMAIL-WEBHOOK",
                snippet="GMAIL-WEBHOOK imported from history.",
                history_id="history-2",
            )
        ],
    )
    try:
        bootstrap = _bootstrap_company(
            client,
            slug="gmail-webhook",
            email="owner@gmail-webhook.example",
        )
        token = str(bootstrap["access_token"])
        _create_matter(client, token, "GMAIL-WEBHOOK")
        _connect_gmail(client, token, provider)

        watch = client.post("/api/mailbox/gmail/watch", headers=_auth(token))
        assert watch.status_code == 200, watch.text
        assert watch.json()["watch_started"] is True
        assert provider.watch_calls == 1
        assert "gmail-resource-secret" not in watch.text

        missing_token = client.post(
            "/api/mailbox/gmail/webhook",
            json=_webhook_payload("owner@gmail-webhook.example", "history-2"),
        )
        assert missing_token.status_code == 403, missing_token.text

        webhook = client.post(
            "/api/mailbox/gmail/webhook?token=webhook-token",
            json=_webhook_payload("owner@gmail-webhook.example", "history-2"),
        )
        assert webhook.status_code == 200, webhook.text
        assert webhook.json()["status"] == "processed"
        assert provider.history_calls == ["history-watch"]
        assert "owner@gmail-webhook.example" not in webhook.text

        duplicate = client.post(
            "/api/mailbox/gmail/webhook?token=webhook-token",
            json=_webhook_payload("owner@gmail-webhook.example", "history-2"),
        )
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["event_id"] == webhook.json()["event_id"]
        assert provider.history_calls == ["history-watch"]

        factory = get_session_factory()
        with factory() as session:
            event = session.get(MailboxWebhookEvent, webhook.json()["event_id"])
            assert event is not None
            assert event.status == MailboxWebhookStatus.PROCESSED
            assert event.raw_payload_hash is not None
            assert "owner@gmail-webhook.example" not in (event.raw_payload_hash or "")
            imported = session.scalar(
                select(MailboxMessageImport).where(
                    MailboxMessageImport.provider_message_id == "msg-webhook"
                )
            )
            assert imported is not None
            assert imported.status == MailboxImportStatus.IMPORTED
    finally:
        set_gmail_provider_for_tests(None)
        get_settings.cache_clear()


def test_google_gmail_provider_retries_transient_message_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_request(method: str, url: str, **kwargs: object) -> httpx.Response:
        nonlocal calls
        calls += 1
        request = httpx.Request(method, url)
        if calls == 1:
            return httpx.Response(503, request=request, json={"error": "temporary"})
        return httpx.Response(200, request=request, json={"messages": []})

    monkeypatch.setattr(httpx, "request", fake_request)
    provider = GoogleGmailProvider(
        GmailRuntimeConfig(
            client_id="gmail-client",
            client_secret="gmail-secret",
            redirect_uri="https://api.caseops.ai/api/mailbox/gmail/callback",
            pubsub_topic=None,
            webhook_verification_token=None,
        )
    )

    messages = provider.list_recent_messages(
        token_payload={"access_token": "gmail-access"},
        limit=5,
    )

    assert messages == []
    assert calls == 2

