"""Production-safe Gmail mailbox connector foundation.

The connector imports Gmail metadata into CaseOps review surfaces. It does not
store raw provider payloads or message bodies, and attachment bytes are fetched
only after a tenant user explicitly approves a candidate.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    CompanyMembership,
    MailboxAttachmentCandidate,
    MailboxAttachmentCandidateStatus,
    MailboxConnectionStatus,
    MailboxImportStatus,
    MailboxMessageImport,
    MailboxProvider,
    MailboxWebhookEvent,
    MailboxWebhookStatus,
    Matter,
    MatterNote,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
    UserMailboxConnection,
)
from caseops_api.schemas.mailbox import (
    MailboxAttachmentCandidateListResponse,
    MailboxAttachmentCandidateRecord,
    MailboxAttachmentCandidateReviewRequest,
    MailboxAttachmentCandidateReviewResponse,
    MailboxConnectionCallbackResponse,
    MailboxConnectionRecord,
    MailboxConnectionStartResponse,
    MailboxImportRequest,
    MailboxImportResponse,
    MailboxImportSummary,
    MailboxMessageImportRecord,
    MailboxMessageReviewRequest,
    MailboxMessageReviewResponse,
    MailboxStatusResponse,
    MailboxWatchResponse,
    MailboxWebhookIngestResponse,
    OutlookMailCandidateCreateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import (
    _decrypt_token_payload,
    _encrypt_secret,
    _encrypt_token_payload,
)
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.google_workspace import google_workspace_oauth_config
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_STATE_KIND = "gmail_mailbox_oauth"
_STATE_TTL_MINUTES = 10
_MAX_SNIPPET_CHARS = 1000


class GmailProviderError(RuntimeError):
    """Provider failures safe to persist/display as redacted mailbox errors."""


@dataclass(frozen=True, slots=True)
class GmailRuntimeConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    pubsub_topic: str | None
    webhook_verification_token: str | None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    @property
    def webhook_configured(self) -> bool:
        return bool(self.pubsub_topic and self.webhook_verification_token)


@dataclass(frozen=True, slots=True)
class GmailAttachmentMetadata:
    attachment_id: str
    filename: str | None
    content_type: str | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class GmailMessageMetadata:
    provider_message_id: str
    provider_thread_id: str | None
    history_id: str | None
    subject: str | None
    sender_email: str | None
    sender_name: str | None
    received_at: datetime | None
    snippet: str | None
    labels: tuple[str, ...]
    attachments: tuple[GmailAttachmentMetadata, ...]


class GmailProvider(Protocol):
    @property
    def configured(self) -> bool:
        raise NotImplementedError

    @property
    def webhook_configured(self) -> bool:
        raise NotImplementedError

    @property
    def unavailable_reason(self) -> str | None:
        raise NotImplementedError

    def authorization_url(self, *, state: str) -> str:
        raise NotImplementedError

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        raise NotImplementedError

    def list_recent_messages(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GmailMessageMetadata]:
        raise NotImplementedError

    def list_history_messages(
        self,
        *,
        token_payload: dict[str, Any],
        start_history_id: str,
        limit: int,
    ) -> list[GmailMessageMetadata]:
        raise NotImplementedError

    def start_watch(self, *, token_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def fetch_attachment(
        self,
        *,
        token_payload: dict[str, Any],
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        raise NotImplementedError


class GoogleGmailProvider:
    def __init__(self, config: GmailRuntimeConfig | None = None) -> None:
        self._config = config

    def _runtime_config(self) -> GmailRuntimeConfig:
        return self._config or _gmail_runtime_config()

    @property
    def configured(self) -> bool:
        return self._runtime_config().configured

    @property
    def webhook_configured(self) -> bool:
        return self._runtime_config().webhook_configured

    @property
    def unavailable_reason(self) -> str | None:
        if self.configured:
            return None
        return "Gmail OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:
        config = self._runtime_config()
        if not self.configured:
            raise GmailProviderError(self.unavailable_reason or "Gmail unavailable.")
        qs = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "scope": " ".join(GMAIL_SCOPES),
                "state": state,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        config = self._runtime_config()
        if not self.configured:
            raise GmailProviderError(self.unavailable_reason or "Gmail unavailable.")
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GmailProviderError("Gmail HTTP client is unavailable.") from exc
        try:
            token_response = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                },
                timeout=15,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise GmailProviderError("Google did not return an access token.")
            profile_response = request_with_retries(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            profile = profile_response.json()
        except httpx.HTTPError as exc:
            raise GmailProviderError("Gmail OAuth exchange failed.") from exc
        scope_text = str(token_payload.get("scope") or " ".join(GMAIL_SCOPES))
        email = str(profile.get("emailAddress") or "") or None
        return {
            "token_payload": token_payload,
            "provider_account_id": email,
            "display_email": email,
            "history_id": str(profile.get("historyId") or "") or None,
            "scopes": scope_text.split(),
        }

    def list_recent_messages(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GmailMessageMetadata]:
        return self._list_messages(token_payload=token_payload, limit=limit)

    def list_history_messages(
        self,
        *,
        token_payload: dict[str, Any],
        start_history_id: str,
        limit: int,
    ) -> list[GmailMessageMetadata]:
        # Gmail history can be lossy/expired. This foundation fetches recent
        # metadata as a safe fallback while preserving the webhook event row.
        _ = start_history_id
        return self._list_messages(token_payload=token_payload, limit=limit)

    def _list_messages(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GmailMessageMetadata]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GmailProviderError("Gmail HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise GmailProviderError("Stored Gmail token is unavailable.")
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            listed = request_with_retries(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=headers,
                params={
                    "maxResults": min(max(limit, 1), 100),
                    "q": "newer_than:30d -in:spam -in:trash",
                },
                timeout=15,
            )
            ids = [str(item.get("id") or "") for item in listed.json().get("messages", [])]
            messages: list[GmailMessageMetadata] = []
            for message_id in [value for value in ids if value]:
                fetched = request_with_retries(
                    "GET",
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                    headers=headers,
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["Subject", "From", "Date"],
                    },
                    timeout=15,
                )
                messages.append(_parse_gmail_message_metadata(fetched.json()))
        except httpx.HTTPError as exc:
            raise GmailProviderError("Gmail message metadata import failed.") from exc
        return messages

    def start_watch(self, *, token_payload: dict[str, Any]) -> dict[str, Any]:
        config = self._runtime_config()
        if not config.webhook_configured:
            raise GmailProviderError("Gmail webhook configuration is incomplete.")
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GmailProviderError("Gmail HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise GmailProviderError("Stored Gmail token is unavailable.")
        try:
            response = httpx.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/watch",
                headers={"Authorization": f"Bearer {access_token}"},
                json={
                    "topicName": config.pubsub_topic,
                    "labelIds": ["INBOX"],
                    "labelFilterBehavior": "include",
                },
                timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GmailProviderError("Gmail watch setup failed.") from exc
        return response.json()

    def fetch_attachment(
        self,
        *,
        token_payload: dict[str, Any],
        message_id: str,
        attachment_id: str,
    ) -> bytes:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GmailProviderError("Gmail HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise GmailProviderError("Stored Gmail token is unavailable.")
        try:
            response = request_with_retries(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
                f"{message_id}/attachments/{attachment_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise GmailProviderError("Gmail attachment fetch failed.") from exc
        encoded = str(response.json().get("data") or "")
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))


_gmail_provider_override: GmailProvider | None = None


def set_gmail_provider_for_tests(provider: GmailProvider | None) -> None:
    global _gmail_provider_override
    _gmail_provider_override = provider


def _gmail_provider(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GmailProvider:
    return _gmail_provider_override or GoogleGmailProvider(
        _gmail_runtime_config(session, context=context)
    )


def _gmail_runtime_config(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GmailRuntimeConfig:
    settings = get_settings()
    workspace_config = google_workspace_oauth_config(
        session,
        context=context,
        connector="gmail",
    )
    if workspace_config.source in {"tenant_admin", "missing"}:
        return GmailRuntimeConfig(
            client_id=workspace_config.client_id,
            client_secret=workspace_config.client_secret,
            redirect_uri=workspace_config.redirect_uri,
            pubsub_topic=settings.gmail_pubsub_topic,
            webhook_verification_token=settings.gmail_webhook_verification_token,
        )
    return GmailRuntimeConfig(
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        redirect_uri=settings.gmail_redirect_uri,
        pubsub_topic=settings.gmail_pubsub_topic,
        webhook_verification_token=settings.gmail_webhook_verification_token,
    )


def _missing_gmail_config_names(config: GmailRuntimeConfig | None = None) -> list[str]:
    runtime = config or _gmail_runtime_config()
    missing: list[str] = []
    if not runtime.client_id:
        missing.append("GMAIL_CLIENT_ID")
    if not runtime.client_secret:
        missing.append("GMAIL_CLIENT_SECRET")
    if not runtime.redirect_uri:
        missing.append("GMAIL_REDIRECT_URI")
    return missing


def _missing_gmail_webhook_config_names(
    config: GmailRuntimeConfig | None = None,
) -> list[str]:
    runtime = config or _gmail_runtime_config()
    missing: list[str] = []
    if not runtime.pubsub_topic:
        missing.append("GMAIL_PUBSUB_TOPIC")
    if not runtime.webhook_verification_token:
        missing.append("GMAIL_WEBHOOK_VERIFICATION_TOKEN")
    return missing


def _sign_state(context: SessionContext) -> str:
    now = datetime.now(UTC)
    payload = {
        "kind": _STATE_KIND,
        "company_id": context.company.id,
        "membership_id": context.membership.id,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, get_settings().auth_secret, algorithm="HS256")


def _verify_state(context: SessionContext, state: str) -> None:
    try:
        payload = jwt.decode(state, get_settings().auth_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Gmail connection state.",
        ) from exc
    if (
        payload.get("kind") != _STATE_KIND
        or str(payload.get("company_id")) != context.company.id
        or str(payload.get("membership_id")) != context.membership.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Gmail connection state does not match the current session.",
        )


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def _safe_error(exc: BaseException | str) -> str:
    return redact_provider_error(str(exc) or exc.__class__.__name__)[:500]


def _connection_record(connection: UserMailboxConnection) -> MailboxConnectionRecord:
    return MailboxConnectionRecord(
        id=connection.id,
        company_id=connection.company_id,
        membership_id=connection.membership_id,
        provider=connection.provider,  # type: ignore[arg-type]
        provider_account_id=connection.provider_account_id,
        display_email=connection.display_email,
        status=connection.status,  # type: ignore[arg-type]
        scopes=list(connection.scopes_json or []),
        last_history_id=connection.last_history_id,
        watch_expires_at=connection.watch_expires_at,
        last_import_at=connection.last_import_at,
        connected_at=connection.connected_at,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _message_record(row: MailboxMessageImport) -> MailboxMessageImportRecord:
    return MailboxMessageImportRecord(
        id=row.id,
        company_id=row.company_id,
        mailbox_connection_id=row.mailbox_connection_id,
        provider=row.connection.provider,  # type: ignore[arg-type]
        matter_id=row.matter_id,
        communication_id=row.communication_id,
        provider_message_id=row.provider_message_id,
        provider_thread_id=row.provider_thread_id,
        subject=row.subject,
        sender_name=row.sender_name,
        occurred_at=row.occurred_at,
        snippet=row.snippet,
        labels=list(row.labels_json or []),
        attachment_count=row.attachment_count,
        status=row.status,  # type: ignore[arg-type]
        last_error_redacted=row.last_error_redacted,
        attempts=row.attempts,
        max_attempts=row.max_attempts,
        next_attempt_at=row.next_attempt_at,
        dead_letter_reason=row.dead_letter_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _attachment_record(
    row: MailboxAttachmentCandidate,
) -> MailboxAttachmentCandidateRecord:
    return MailboxAttachmentCandidateRecord(
        id=row.id,
        company_id=row.company_id,
        message_import_id=row.message_import_id,
        matter_id=row.matter_id,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        status=row.status,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_gmail_status(
    session: Session,
    *,
    context: SessionContext,
) -> MailboxStatusResponse:
    config = _gmail_runtime_config(session, context=context)
    rows = list(
        session.scalars(
            select(UserMailboxConnection)
            .where(
                UserMailboxConnection.company_id == context.company.id,
                UserMailboxConnection.membership_id == context.membership.id,
                UserMailboxConnection.provider == MailboxProvider.GMAIL,
            )
            .order_by(UserMailboxConnection.created_at.asc())
        )
    )
    return MailboxStatusResponse(
        configured=config.configured,
        webhook_configured=config.webhook_configured,
        missing_config_names=_missing_gmail_config_names(config),
        missing_webhook_config_names=_missing_gmail_webhook_config_names(config),
        connections=[_connection_record(row) for row in rows],
    )


def start_gmail_connection(
    session: Session,
    *,
    context: SessionContext,
) -> MailboxConnectionStartResponse:
    _ = session
    provider = _gmail_provider(session, context=context)
    if not provider.configured:
        return MailboxConnectionStartResponse(
            provider_available=False,
            unavailable_reason=provider.unavailable_reason,
        )
    return MailboxConnectionStartResponse(
        provider_available=True,
        auth_url=provider.authorization_url(state=_sign_state(context)),
    )


def complete_gmail_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> MailboxConnectionCallbackResponse:
    provider = _gmail_provider(session, context=context)
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=provider.unavailable_reason or "Gmail is unavailable.",
        )
    _verify_state(context, state)
    exchanged = provider.exchange_code(code=code)
    token_payload = exchanged.get("token_payload")
    if not isinstance(token_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail OAuth provider returned an invalid token response.",
        )
    now = datetime.now(UTC)
    connection = session.scalar(
        select(UserMailboxConnection).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        )
    )
    if connection is None:
        connection = UserMailboxConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=MailboxProvider.GMAIL,
        )
        session.add(connection)
        session.flush()
    connection.provider_account_id = str(exchanged.get("provider_account_id") or "") or None
    connection.display_email = str(exchanged.get("display_email") or "") or None
    connection.status = MailboxConnectionStatus.CONNECTED
    connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
    connection.scopes_json = [
        str(scope) for scope in exchanged.get("scopes", GMAIL_SCOPES) if str(scope)
    ]
    connection.last_history_id = str(exchanged.get("history_id") or "") or None
    connection.connected_at = now
    session.add(connection)
    record_from_context(
        session,
        context,
        action="mailbox.gmail.connected",
        target_type="user_mailbox_connection",
        target_id=connection.id,
        metadata={
            "provider": MailboxProvider.GMAIL,
            "display_email": connection.display_email,
            "scopes": connection.scopes_json,
        },
    )
    session.commit()
    return MailboxConnectionCallbackResponse(
        connected=True,
        connection=_connection_record(connection),
    )


def _connected_gmail_connection(
    session: Session,
    *,
    context: SessionContext,
) -> UserMailboxConnection:
    connection = session.scalar(
        select(UserMailboxConnection).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
            UserMailboxConnection.status == MailboxConnectionStatus.CONNECTED,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Gmail is not connected.",
        )
    return connection


def revoke_gmail_connection(
    session: Session,
    *,
    context: SessionContext,
    connection_id: str,
) -> MailboxConnectionRecord:
    connection = session.scalar(
        select(UserMailboxConnection).where(
            UserMailboxConnection.id == connection_id,
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Gmail connection not found.")
    connection.status = MailboxConnectionStatus.REVOKED
    connection.encrypted_token_ref = None
    session.add(connection)
    record_from_context(
        session,
        context,
        action="mailbox.gmail.revoked",
        target_type="user_mailbox_connection",
        target_id=connection.id,
        metadata={"provider": MailboxProvider.GMAIL},
    )
    session.commit()
    return _connection_record(connection)


def import_recent_gmail_messages(
    session: Session,
    *,
    context: SessionContext,
    payload: MailboxImportRequest,
) -> MailboxImportResponse:
    connection = _connected_gmail_connection(session, context=context)
    token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    provider = _gmail_provider(session, context=context)
    messages = provider.list_recent_messages(
        token_payload=token_payload,
        limit=payload.limit,
    )
    imports = _upsert_message_imports(
        session,
        context=context,
        connection=connection,
        messages=messages,
    )
    connection.last_import_at = datetime.now(UTC)
    if messages and messages[0].history_id:
        connection.last_history_id = messages[0].history_id
    session.add(connection)
    record_from_context(
        session,
        context,
        action="mailbox.gmail.imported",
        target_type="user_mailbox_connection",
        target_id=connection.id,
        metadata={
            "provider": MailboxProvider.GMAIL,
            "message_count": len(messages),
            "import_ids": [redact_identifier(row.id) for row in imports],
        },
    )
    session.commit()
    return MailboxImportResponse(
        summary=_import_summary(imports),
        imports=[_message_record(row) for row in imports],
    )


def _upsert_message_imports(
    session: Session,
    *,
    context: SessionContext,
    connection: UserMailboxConnection,
    messages: list[GmailMessageMetadata],
) -> list[MailboxMessageImport]:
    rows: list[MailboxMessageImport] = []
    for message in messages:
        row = _upsert_message_import(
            session,
            context=context,
            connection=connection,
            message=message,
        )
        rows.append(row)
    return rows


def _upsert_message_import(
    session: Session,
    *,
    context: SessionContext,
    connection: UserMailboxConnection,
    message: GmailMessageMetadata,
) -> MailboxMessageImport:
    existing = session.scalar(
        select(MailboxMessageImport).where(
            MailboxMessageImport.mailbox_connection_id == connection.id,
            MailboxMessageImport.provider_message_id == message.provider_message_id,
        )
    )
    if existing is not None:
        existing.status = MailboxImportStatus.DUPLICATE
        existing.updated_at = datetime.now(UTC)
        session.add(existing)
        return existing

    matter = _match_matter(session, context=context, message=message)
    status_value = (
        MailboxImportStatus.IMPORTED if matter is not None else MailboxImportStatus.UNMATCHED
    )
    communication: Communication | None = None
    if matter is not None:
        communication = Communication(
            company_id=context.company.id,
            matter_id=matter.id,
            direction=CommunicationDirection.INBOUND,
            channel=CommunicationChannel.EMAIL,
            subject=(message.subject or "").strip()[:500] or None,
            body=(message.snippet or "")[:_MAX_SNIPPET_CHARS] or None,
            recipient_name=message.sender_name,
            recipient_email=None,
            status=CommunicationStatus.LOGGED,
            occurred_at=message.received_at or datetime.now(UTC),
            external_message_id=f"gmail:{message.provider_message_id}",
            created_by_membership_id=context.membership.id,
            metadata_json={
                "source": "gmail_provider_import",
                "provider": MailboxProvider.GMAIL.value,
                "provider_message_id_hash": _hash(message.provider_message_id),
                "provider_thread_id_hash": _hash(message.provider_thread_id),
                "sender_email_hash": _hash(message.sender_email),
                "body_preview_chars": len(message.snippet or ""),
                "attachment_candidate_count": len(message.attachments),
                "match_basis": "matter_code_in_subject_or_snippet",
                "automation_mode": "provider_review_first",
            },
        )
        session.add(communication)
        session.flush()

    row = MailboxMessageImport(
        company_id=context.company.id,
        mailbox_connection_id=connection.id,
        matter_id=matter.id if matter is not None else None,
        communication_id=communication.id if communication is not None else None,
        provider_message_id=message.provider_message_id,
        provider_thread_id=message.provider_thread_id,
        history_id=message.history_id,
        subject=(message.subject or "")[:500] or None,
        sender_email_hash=_hash(message.sender_email),
        sender_name=message.sender_name,
        occurred_at=message.received_at,
        snippet=(message.snippet or "")[:_MAX_SNIPPET_CHARS] or None,
        labels_json=list(message.labels),
        attachment_count=len(message.attachments),
        status=status_value,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        existing_after_race = session.scalar(
            select(MailboxMessageImport).where(
                MailboxMessageImport.mailbox_connection_id == connection.id,
                MailboxMessageImport.provider_message_id == message.provider_message_id,
            )
        )
        if existing_after_race is None:
            raise
        existing_after_race.status = MailboxImportStatus.DUPLICATE
        return existing_after_race

    if matter is not None:
        for attachment in message.attachments:
            _upsert_attachment_candidate(
                session,
                context=context,
                message_import=row,
                attachment=attachment,
                matter=matter,
            )
    return row


def _match_matter(
    session: Session,
    *,
    context: SessionContext,
    message: GmailMessageMetadata,
) -> Matter | None:
    haystack = f"{message.subject or ''} {message.snippet or ''}".lower()
    if not haystack.strip():
        return None
    rows = list(
        session.scalars(
            select(Matter)
            .where(
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
            .order_by(Matter.created_at.desc())
            .limit(500)
        )
    )
    for matter in rows:
        code = (matter.matter_code or "").lower()
        if code and code in haystack:
            return matter
    return None


def _upsert_attachment_candidate(
    session: Session,
    *,
    context: SessionContext,
    message_import: MailboxMessageImport,
    attachment: GmailAttachmentMetadata,
    matter: Matter,
) -> MailboxAttachmentCandidate:
    attachment_hash = _hash(attachment.attachment_id) or "0" * 64
    existing = session.scalar(
        select(MailboxAttachmentCandidate).where(
            MailboxAttachmentCandidate.message_import_id == message_import.id,
            MailboxAttachmentCandidate.provider_attachment_ref_hash == attachment_hash,
        )
    )
    if existing is not None:
        return existing
    candidate = MailboxAttachmentCandidate(
        company_id=context.company.id,
        message_import_id=message_import.id,
        matter_id=matter.id,
        provider_attachment_ref_hash=attachment_hash,
        encrypted_provider_attachment_ref=_encrypt_secret(attachment.attachment_id),
        filename=attachment.filename,
        content_type=attachment.content_type,
        size_bytes=attachment.size_bytes,
        status=MailboxAttachmentCandidateStatus.NEEDS_REVIEW,
    )
    session.add(candidate)
    session.flush()
    return candidate


def _import_summary(rows: list[MailboxMessageImport]) -> MailboxImportSummary:
    return MailboxImportSummary(
        imported=sum(1 for row in rows if row.status == MailboxImportStatus.IMPORTED),
        unmatched=sum(1 for row in rows if row.status == MailboxImportStatus.UNMATCHED),
        duplicate=sum(1 for row in rows if row.status == MailboxImportStatus.DUPLICATE),
        failed=sum(1 for row in rows if row.status == MailboxImportStatus.FAILED),
        attachment_candidates=sum(row.attachment_count for row in rows),
    )


def list_message_imports(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
    provider: str | None = None,
    matter_id: str | None = None,
    status_filter: str | None = None,
    q: str | None = None,
) -> MailboxImportResponse:
    filters = [MailboxMessageImport.company_id == context.company.id]
    if provider:
        filters.append(UserMailboxConnection.provider == provider)
    if matter_id:
        filters.append(MailboxMessageImport.matter_id == matter_id)
    if status_filter:
        filters.append(MailboxMessageImport.status == status_filter)
    if q:
        like = f"%{q.strip()}%"
        filters.append(MailboxMessageImport.subject.ilike(like))
    rows = list(
        session.scalars(
            select(MailboxMessageImport)
            .options(joinedload(MailboxMessageImport.connection))
            .join(UserMailboxConnection)
            .where(*filters)
            .order_by(MailboxMessageImport.updated_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )
    visible: list[MailboxMessageImport] = []
    for row in rows:
        if row.matter_id is None:
            if row.connection.membership_id == context.membership.id:
                visible.append(row)
            continue
        matter = session.get(Matter, row.matter_id)
        if matter is None:
            continue
        try:
            assert_access(session, context=context, matter=matter)
        except HTTPException:
            continue
        visible.append(row)
    return MailboxImportResponse(
        summary=_import_summary(visible),
        imports=[_message_record(row) for row in visible],
    )


def _load_message_import_for_review(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
) -> MailboxMessageImport:
    row = session.scalar(
        select(MailboxMessageImport)
        .options(joinedload(MailboxMessageImport.connection))
        .where(
            MailboxMessageImport.id == import_id,
            MailboxMessageImport.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Mailbox import not found.")
    if row.matter_id is None:
        if row.connection.membership_id != context.membership.id:
            raise HTTPException(status_code=404, detail="Mailbox import not found.")
        return row
    matter = session.get(Matter, row.matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return row


def _matter_for_review(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
) -> Matter:
    if not matter_id:
        raise HTTPException(status_code=400, detail="matter_id is required.")
    matter = session.get(Matter, matter_id)
    if matter is None or matter.company_id != context.company.id:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    return matter


def _ensure_metadata_communication(
    session: Session,
    *,
    context: SessionContext,
    row: MailboxMessageImport,
    matter: Matter,
) -> Communication:
    if row.communication_id:
        existing = session.get(Communication, row.communication_id)
        if existing is not None:
            return existing
    provider = str(row.connection.provider)
    communication = Communication(
        company_id=context.company.id,
        matter_id=matter.id,
        direction=CommunicationDirection.INBOUND,
        channel=CommunicationChannel.EMAIL,
        subject=(row.subject or "").strip()[:500] or None,
        body=(row.snippet or "")[:_MAX_SNIPPET_CHARS] or None,
        recipient_name=row.sender_name,
        recipient_email=None,
        status=CommunicationStatus.LOGGED,
        occurred_at=row.occurred_at or datetime.now(UTC),
        external_message_id=f"{provider}:{row.provider_message_id}",
        created_by_membership_id=context.membership.id,
        metadata_json={
            "source": "mailbox_metadata_review",
            "provider": provider,
            "provider_message_id_hash": _hash(row.provider_message_id),
            "provider_thread_id_hash": _hash(row.provider_thread_id),
            "body_preview_chars": len(row.snippet or ""),
            "automation_mode": "review_first_metadata_only",
        },
    )
    session.add(communication)
    session.flush()
    row.communication_id = communication.id
    return communication


def review_message_import(
    session: Session,
    *,
    context: SessionContext,
    import_id: str,
    payload: MailboxMessageReviewRequest,
) -> MailboxMessageReviewResponse:
    row = _load_message_import_for_review(session, context=context, import_id=import_id)
    matter: Matter | None = None
    communication: Communication | None = None
    note: MatterNote | None = None
    task: MatterTask | None = None
    content_import_queued = False

    if payload.action == "ignore":
        row.status = MailboxImportStatus.IGNORED
        session.add(row)
        record_from_context(
            session,
            context,
            action="mailbox.message.ignored",
            target_type="mailbox_message_import",
            target_id=row.id,
            metadata={"provider": row.connection.provider},
        )
        session.commit()
        return MailboxMessageReviewResponse(import_record=_message_record(row))

    if payload.action in {"link_metadata", "create_note", "create_task"}:
        matter = _matter_for_review(
            session,
            context=context,
            matter_id=payload.matter_id or row.matter_id,
        )
        matter = require_operational_matter(
            session,
            matter=matter,
            operation="link mailbox work",
        )
        communication = _ensure_metadata_communication(
            session,
            context=context,
            row=row,
            matter=matter,
        )
        row.matter_id = matter.id
        row.status = MailboxImportStatus.LINKED_METADATA
        for candidate in row.attachment_candidates:
            candidate.matter_id = matter.id
            session.add(candidate)
        if payload.action == "create_note":
            body = payload.note_body or _default_note_body(row)
            note = MatterNote(
                matter_id=matter.id,
                author_membership_id=context.membership.id,
                body=body,
            )
            session.add(note)
            session.flush()
        if payload.action == "create_task":
            task = MatterTask(
                matter_id=matter.id,
                created_by_membership_id=context.membership.id,
                owner_membership_id=context.membership.id,
                title=(payload.task_title or row.subject or "Review linked email")[:255],
                description=payload.task_description or row.snippet,
                status=MatterTaskStatus.TODO,
                priority=MatterTaskPriority.MEDIUM,
            )
            session.add(task)
            session.flush()
        session.add(row)
        record_from_context(
            session,
            context,
            action=f"mailbox.message.{payload.action}",
            target_type="mailbox_message_import",
            target_id=row.id,
            matter_id=matter.id,
            metadata={
                "provider": row.connection.provider,
                "communication_id": redact_identifier(communication.id),
                "note_id": redact_identifier(note.id) if note else None,
                "task_id": redact_identifier(task.id) if task else None,
            },
        )
        session.commit()
        return MailboxMessageReviewResponse(
            import_record=_message_record(row),
            matter_id=matter.id,
            communication_id=communication.id,
            note_id=note.id if note else None,
            task_id=task.id if task else None,
        )

    if payload.action == "request_content_import":
        if row.matter_id is None:
            matter = _matter_for_review(session, context=context, matter_id=payload.matter_id)
            row.matter_id = matter.id
        else:
            matter = _matter_for_review(session, context=context, matter_id=row.matter_id)
        matter = require_operational_matter(
            session,
            matter=matter,
            operation="request mailbox content import",
        )
        row.status = MailboxImportStatus.CONTENT_IMPORT_REQUESTED
        session.add(row)
        record_from_context(
            session,
            context,
            action="mailbox.message.content_import_requested",
            target_type="mailbox_message_import",
            target_id=row.id,
            matter_id=matter.id,
            metadata={
                "provider": row.connection.provider,
                "raw_body_imported": False,
                "attachment_count": row.attachment_count,
            },
        )
        session.commit()
        content_import_queued = True
        return MailboxMessageReviewResponse(
            import_record=_message_record(row),
            matter_id=matter.id,
            communication_id=row.communication_id,
            content_import_queued=content_import_queued,
        )

    raise HTTPException(status_code=400, detail="Unsupported mailbox review action.")


def _default_note_body(row: MailboxMessageImport) -> str:
    lines = ["Linked email metadata"]
    if row.subject:
        lines.append(f"Subject: {row.subject}")
    if row.sender_name:
        lines.append(f"Sender: {row.sender_name}")
    if row.occurred_at:
        lines.append(f"Date: {row.occurred_at.isoformat()}")
    if row.snippet:
        lines.append("")
        lines.append(row.snippet)
    return "\n".join(lines)[:4000]


def create_outlook_mail_candidate(
    session: Session,
    *,
    context: SessionContext,
    payload: OutlookMailCandidateCreateRequest,
) -> MailboxMessageImportRecord:
    matter: Matter | None = None
    if payload.suggested_matter_id:
        matter = _matter_for_review(
            session,
            context=context,
            matter_id=payload.suggested_matter_id,
        )
    connection = session.scalar(
        select(UserMailboxConnection).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.OUTLOOK_MAIL,
        )
    )
    if connection is None:
        connection = UserMailboxConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=MailboxProvider.OUTLOOK_MAIL,
            provider_account_id="local-safe-review",
            display_email=None,
            status=MailboxConnectionStatus.ERROR,
            scopes_json=["Mail.ReadBasic"],
        )
        session.add(connection)
        session.flush()
    existing = session.scalar(
        select(MailboxMessageImport)
        .options(joinedload(MailboxMessageImport.connection))
        .where(
            MailboxMessageImport.mailbox_connection_id == connection.id,
            MailboxMessageImport.provider_message_id == payload.provider_message_id,
        )
    )
    if existing is not None:
        return _message_record(existing)
    row = MailboxMessageImport(
        company_id=context.company.id,
        mailbox_connection_id=connection.id,
        matter_id=matter.id if matter else None,
        provider_message_id=payload.provider_message_id,
        provider_thread_id=payload.provider_thread_id,
        subject=(payload.subject or "")[:500] or None,
        sender_email_hash=_hash(payload.sender_email),
        sender_name=payload.sender_name,
        occurred_at=payload.occurred_at,
        snippet=(payload.snippet or "")[:_MAX_SNIPPET_CHARS] or None,
        labels_json=list(payload.labels),
        attachment_count=payload.attachment_count,
        status=MailboxImportStatus.NEW,
    )
    session.add(row)
    session.flush()
    row.connection = connection
    record_from_context(
        session,
        context,
        action="mailbox.outlook_candidate.created",
        target_type="mailbox_message_import",
        target_id=row.id,
        matter_id=matter.id if matter else None,
        metadata={
            "provider": MailboxProvider.OUTLOOK_MAIL,
            "raw_body_imported": False,
            "provider_message_id_hash": _hash(payload.provider_message_id),
        },
    )
    session.commit()
    return _message_record(row)


def list_attachment_candidates(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 50,
) -> MailboxAttachmentCandidateListResponse:
    rows = list(
        session.scalars(
            select(MailboxAttachmentCandidate)
            .join(
                MailboxMessageImport,
                MailboxMessageImport.id == MailboxAttachmentCandidate.message_import_id,
            )
            .where(
                MailboxAttachmentCandidate.company_id == context.company.id,
                MailboxAttachmentCandidate.status == MailboxAttachmentCandidateStatus.NEEDS_REVIEW,
            )
            .order_by(MailboxAttachmentCandidate.created_at.asc())
            .limit(max(1, min(limit, 100)))
        )
    )
    visible: list[MailboxAttachmentCandidate] = []
    for row in rows:
        if row.matter_id is None:
            continue
        matter = session.get(Matter, row.matter_id)
        if matter is None:
            continue
        try:
            assert_access(session, context=context, matter=matter)
        except HTTPException:
            continue
        visible.append(row)
    return MailboxAttachmentCandidateListResponse(
        candidates=[_attachment_record(row) for row in visible],
        pending_count=len(visible),
    )


def review_attachment_candidate(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
    payload: MailboxAttachmentCandidateReviewRequest,
) -> MailboxAttachmentCandidateReviewResponse:
    candidate = session.scalar(
        select(MailboxAttachmentCandidate)
        .options(
            joinedload(MailboxAttachmentCandidate.message_import).joinedload(
                MailboxMessageImport.connection
            )
        )
        .where(
            MailboxAttachmentCandidate.id == candidate_id,
            MailboxAttachmentCandidate.company_id == context.company.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Mailbox attachment candidate not found.")
    if candidate.matter_id is None:
        raise HTTPException(status_code=409, detail="Candidate is not linked to a matter.")
    matter = session.get(Matter, candidate.matter_id)
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    if payload.action == "reject":
        candidate.status = MailboxAttachmentCandidateStatus.REJECTED
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="mailbox.gmail_attachment.rejected",
            target_type="mailbox_attachment_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            metadata={"provider": MailboxProvider.GMAIL},
        )
        session.commit()
        return MailboxAttachmentCandidateReviewResponse(
            candidate=_attachment_record(candidate),
        )
    if candidate.status == MailboxAttachmentCandidateStatus.APPROVED_IMPORTED:
        return MailboxAttachmentCandidateReviewResponse(
            candidate=_attachment_record(candidate),
            imported_attachment_id=candidate.imported_attachment_id,
        )
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="import a Gmail attachment",
        lock_for_write=False,
    )
    connection = candidate.message_import.connection
    provider_attachment_id = _decrypt_secret_safe(candidate.encrypted_provider_attachment_ref)
    if not provider_attachment_id:
        raise HTTPException(status_code=409, detail="Provider attachment reference is missing.")
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        content = _gmail_provider(session, context=context).fetch_attachment(
            token_payload=token_payload,
            message_id=candidate.message_import.provider_message_id,
            attachment_id=provider_attachment_id,
        )
    except Exception as exc:
        candidate.last_error_redacted = _safe_error(exc)
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="mailbox.gmail_attachment.import_failed",
            target_type="mailbox_attachment_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            result="failed",
            metadata={
                "provider": MailboxProvider.GMAIL,
                "error": candidate.last_error_redacted,
            },
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail attachment import failed.",
        ) from exc

    # A provider fetch can outlive a concurrent lifecycle transition. Reload
    # and lock before any attachment bytes, jobs, or audit rows are persisted.
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="import a Gmail attachment",
    )
    try:
        from caseops_api.services.communications import _persist_inbound_attachment

        attachment, _job_id, _storage_key = _persist_inbound_attachment(
            session,
            context=context,
            matter=matter,
            filename=candidate.filename or "gmail-attachment",
            content_type=candidate.content_type,
            stream=BytesIO(content),
        )
    except Exception as exc:
        candidate.last_error_redacted = _safe_error(exc)
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="mailbox.gmail_attachment.import_failed",
            target_type="mailbox_attachment_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            result="failed",
            metadata={
                "provider": MailboxProvider.GMAIL,
                "error": candidate.last_error_redacted,
            },
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail attachment import failed.",
        ) from exc
    candidate.status = MailboxAttachmentCandidateStatus.APPROVED_IMPORTED
    candidate.imported_attachment_id = attachment.id
    candidate.last_error_redacted = None
    session.add(candidate)
    record_from_context(
        session,
        context,
        action="mailbox.gmail_attachment.imported",
        target_type="mailbox_attachment_candidate",
        target_id=candidate.id,
        matter_id=matter.id,
        metadata={
            "provider": MailboxProvider.GMAIL,
            "attachment_id": redact_identifier(attachment.id),
        },
    )
    session.commit()
    return MailboxAttachmentCandidateReviewResponse(
        candidate=_attachment_record(candidate),
        imported_attachment_id=attachment.id,
    )


def start_gmail_watch(
    session: Session,
    *,
    context: SessionContext,
) -> MailboxWatchResponse:
    config = _gmail_runtime_config(session, context=context)
    provider = _gmail_provider(session, context=context)
    if not provider.configured or not provider.webhook_configured:
        return MailboxWatchResponse(
            watch_started=False,
            webhook_configured=provider.webhook_configured,
            missing_config_names=[
                *_missing_gmail_config_names(config),
                *_missing_gmail_webhook_config_names(config),
            ],
        )
    connection = _connected_gmail_connection(session, context=context)
    token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    response = provider.start_watch(token_payload=token_payload)
    history_id = str(response.get("historyId") or "") or None
    expiration_ms = response.get("expiration")
    expires_at = None
    if expiration_ms:
        try:
            expires_at = datetime.fromtimestamp(int(expiration_ms) / 1000, tz=UTC)
        except (TypeError, ValueError):
            expires_at = None
    connection.last_history_id = history_id or connection.last_history_id
    connection.watch_expires_at = expires_at
    connection.watch_resource_id = str(response.get("resourceId") or "") or None
    session.add(connection)
    record_from_context(
        session,
        context,
        action="mailbox.gmail.watch_started",
        target_type="user_mailbox_connection",
        target_id=connection.id,
        metadata={
            "provider": MailboxProvider.GMAIL,
            "history_id_present": history_id is not None,
            "watch_expires_at": expires_at,
        },
    )
    session.commit()
    return MailboxWatchResponse(
        watch_started=True,
        webhook_configured=True,
        history_id=history_id,
        watch_expires_at=expires_at,
    )


def ingest_gmail_webhook(
    session: Session,
    *,
    verification_token: str | None,
    payload: dict[str, Any],
) -> MailboxWebhookIngestResponse:
    config = _gmail_runtime_config()
    if not config.webhook_configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Gmail webhook configuration is incomplete.",
        )
    if verification_token != config.webhook_verification_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook token.")
    decoded = _decode_pubsub_payload(payload)
    history_id = str(decoded.get("historyId") or "")
    email_address = str(decoded.get("emailAddress") or "").strip().lower()
    if not history_id:
        raise HTTPException(status_code=400, detail="Gmail webhook historyId is required.")
    email_hash = _hash(email_address)
    existing_event = session.scalar(
        select(MailboxWebhookEvent).where(
            MailboxWebhookEvent.provider == MailboxProvider.GMAIL,
            MailboxWebhookEvent.history_id == history_id,
            MailboxWebhookEvent.email_address_hash == email_hash,
        )
    )
    if existing_event is not None:
        return MailboxWebhookIngestResponse(
            accepted=True,
            status=existing_event.status,  # type: ignore[arg-type]
            event_id=existing_event.id,
        )
    connection = None
    if email_address:
        connection = session.scalar(
            select(UserMailboxConnection)
            .options(
                joinedload(UserMailboxConnection.company),
                joinedload(UserMailboxConnection.membership).joinedload(CompanyMembership.user),
            )
            .where(
                func.lower(UserMailboxConnection.display_email) == email_address,
                UserMailboxConnection.provider == MailboxProvider.GMAIL,
                UserMailboxConnection.status == MailboxConnectionStatus.CONNECTED,
            )
        )
    event = MailboxWebhookEvent(
        company_id=connection.company_id if connection is not None else None,
        mailbox_connection_id=connection.id if connection is not None else None,
        provider=MailboxProvider.GMAIL,
        history_id=history_id,
        email_address_hash=email_hash,
        raw_payload_hash=_hash(json.dumps(payload, sort_keys=True, default=str)),
        status=MailboxWebhookStatus.QUEUED,
    )
    session.add(event)
    session.flush()
    if connection is None:
        event.status = MailboxWebhookStatus.PROCESSED
        event.processed_at = datetime.now(UTC)
        session.add(event)
        session.commit()
        return MailboxWebhookIngestResponse(
            accepted=True,
            status="processed",
            event_id=event.id,
        )

    context = SessionContext(
        company=connection.company,
        membership=connection.membership,
        user=connection.membership.user,
    )
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        messages = _gmail_provider(session, context=context).list_history_messages(
            token_payload=token_payload,
            start_history_id=connection.last_history_id or history_id,
            limit=50,
        )
        _upsert_message_imports(
            session,
            context=context,
            connection=connection,
            messages=messages,
        )
        connection.last_history_id = history_id
        connection.last_import_at = datetime.now(UTC)
        event.status = MailboxWebhookStatus.PROCESSED
        event.processed_at = datetime.now(UTC)
        session.add_all([event, connection])
        record_from_context(
            session,
            context,
            action="mailbox.gmail.webhook_processed",
            target_type="mailbox_webhook_event",
            target_id=event.id,
            metadata={
                "provider": MailboxProvider.GMAIL,
                "message_count": len(messages),
                "history_ref": redact_identifier(history_id),
            },
        )
    except Exception as exc:
        event.status = MailboxWebhookStatus.FAILED
        event.last_error_redacted = _safe_error(exc)
        event.attempts += 1
        session.add(event)
    session.commit()
    return MailboxWebhookIngestResponse(
        accepted=True,
        status=event.status,  # type: ignore[arg-type]
        event_id=event.id,
    )


def _decode_pubsub_payload(payload: dict[str, Any]) -> dict[str, Any]:
    message = payload.get("message")
    if not isinstance(message, dict):
        return payload
    encoded = str(message.get("data") or "")
    if not encoded:
        return {}
    try:
        raw = base64.b64decode(encoded + "=" * (-len(encoded) % 4))
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _decrypt_secret_safe(value: str | None) -> str | None:
    if not value:
        return None
    from caseops_api.services.calendar_sync import _decrypt_secret

    return _decrypt_secret(value)


def _parse_gmail_message_metadata(payload: dict[str, Any]) -> GmailMessageMetadata:
    headers = {
        str(item.get("name") or "").lower(): str(item.get("value") or "")
        for item in (payload.get("payload") or {}).get("headers", [])
        if isinstance(item, dict)
    }
    sender_name, sender_email = _parse_from_header(headers.get("from"))
    attachments = tuple(_iter_attachment_metadata(payload.get("payload") or {}))
    return GmailMessageMetadata(
        provider_message_id=str(payload.get("id") or ""),
        provider_thread_id=str(payload.get("threadId") or "") or None,
        history_id=str(payload.get("historyId") or "") or None,
        subject=headers.get("subject") or None,
        sender_email=sender_email,
        sender_name=sender_name,
        received_at=None,
        snippet=str(payload.get("snippet") or "")[:_MAX_SNIPPET_CHARS] or None,
        labels=tuple(str(label) for label in payload.get("labelIds", []) if str(label)),
        attachments=attachments,
    )


def _iter_attachment_metadata(part: dict[str, Any]) -> list[GmailAttachmentMetadata]:
    found: list[GmailAttachmentMetadata] = []
    body = part.get("body") if isinstance(part.get("body"), dict) else {}
    attachment_id = str(body.get("attachmentId") or "")
    filename = str(part.get("filename") or "") or None
    if attachment_id:
        found.append(
            GmailAttachmentMetadata(
                attachment_id=attachment_id,
                filename=filename,
                content_type=str(part.get("mimeType") or "") or None,
                size_bytes=int(body.get("size") or 0) or None,
            )
        )
    for child in part.get("parts") or []:
        if isinstance(child, dict):
            found.extend(_iter_attachment_metadata(child))
    return found


def _parse_from_header(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    if "<" in value and ">" in value:
        name = value.split("<", 1)[0].strip().strip('"') or None
        email = value.split("<", 1)[1].split(">", 1)[0].strip().lower() or None
        return name, email
    cleaned = value.strip().lower()
    return None, cleaned if "@" in cleaned else None


__all__ = [
    "GMAIL_SCOPES",
    "GmailAttachmentMetadata",
    "GmailMessageMetadata",
    "complete_gmail_connection",
    "import_recent_gmail_messages",
    "ingest_gmail_webhook",
    "list_attachment_candidates",
    "list_gmail_status",
    "list_message_imports",
    "review_attachment_candidate",
    "revoke_gmail_connection",
    "set_gmail_provider_for_tests",
    "start_gmail_connection",
    "start_gmail_watch",
]
