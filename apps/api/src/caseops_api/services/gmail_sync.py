"""Production-safe Gmail mailbox connector foundation.

The connector imports Gmail metadata into CaseOps review surfaces. It does not
store raw provider payloads or message bodies, and attachment bytes are fetched
only after a tenant user explicitly approves a candidate.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import uuid4

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    Communication,
    CommunicationChannel,
    CommunicationDirection,
    CommunicationStatus,
    CompanyMembership,
    DocumentProcessingAction,
    DocumentProcessingTargetType,
    MailboxAttachmentCandidate,
    MailboxAttachmentCandidateStatus,
    MailboxConnectionStatus,
    MailboxImportStatus,
    MailboxMessageImport,
    MailboxProvider,
    MailboxWebhookEvent,
    MailboxWebhookStatus,
    Matter,
    MatterActivity,
    MatterAttachment,
    MatterNote,
    MatterTask,
    MatterTaskPriority,
    MatterTaskStatus,
    TenantGoogleWorkspaceConfiguration,
    UserMailboxConnection,
)
from caseops_api.db.session import serialize_sqlite_writer
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
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    lock_company_memberships_for_oauth,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import (
    _decrypt_token_payload,
    _encrypt_secret,
    _encrypt_token_payload,
)
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.google_workspace import (
    GoogleWorkspaceTokenRefreshError,
    google_workspace_oauth_config,
    refresh_google_workspace_access_token,
)
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.idempotency import (
    IdempotencyClaimOutcome,
    claim_idempotency,
    complete_idempotency,
)
from caseops_api.services.identity import get_session_context
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.matter_write_fence import (
    lock_matter_private_authority,
    require_read_only_upload_session,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.storage_governance import (
    StorageQuotaExceeded,
    assert_storage_quota_allows_upload,
)

logger = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
_STATE_KIND = "gmail_mailbox_oauth"
_STATE_TTL_MINUTES = 10
_OAUTH_META_KEY = "_caseops_gmail_oauth"
_OAUTH_LEASE_SECONDS = 300
_MAX_SNIPPET_CHARS = 1000


class GmailProviderError(RuntimeError):
    """Provider failures safe to persist/display as redacted mailbox errors."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _oauth_token_scopes(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        raise GmailProviderError("Google returned an invalid token object.")
    access_token = payload.get("access_token")
    if (
        not isinstance(access_token, str)
        or not access_token
        or any(character.isspace() for character in access_token)
    ):
        raise GmailProviderError("Google returned an invalid access token.")
    if "refresh_token" in payload and (
        not isinstance(payload["refresh_token"], str)
        or not payload["refresh_token"]
        or any(character.isspace() for character in payload["refresh_token"])
    ):
        raise GmailProviderError("Google returned an invalid refresh token.")
    if "token_type" in payload and (
        not isinstance(payload["token_type"], str) or payload["token_type"].lower() != "bearer"
    ):
        raise GmailProviderError("Google returned an unsupported token type.")
    # RFC 6749 section 5.1 permits omission only for the original requested grant.
    scope_text = payload.get("scope", " ".join(GMAIL_SCOPES))
    if not isinstance(scope_text, str) or not set(GMAIL_SCOPES).issubset(scope_text.split()):
        raise GmailProviderError("Google did not grant the required connector permission.")
    try:
        bounded = len(json.dumps(payload, allow_nan=False)) <= 65536
    except (TypeError, ValueError) as exc:
        raise GmailProviderError("Google returned an invalid token object.") from exc
    if not bounded:
        raise GmailProviderError("Google returned an oversized token object.")
    return scope_text.split()


def _validate_oauth_identity(subject: Any, email: Any) -> None:
    if (
        not isinstance(subject, str)
        or not subject
        or len(subject) > 255
        or any(character.isspace() for character in subject)
    ):
        raise GmailProviderError("Google returned an invalid account identity.")
    if (
        not isinstance(email, str)
        or not email
        or len(email) > 320
        or email.count("@") != 1
        or not all(email.split("@"))
        or any(character.isspace() for character in email)
    ):
        raise GmailProviderError("Google returned an invalid account email.")


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
            scopes = _oauth_token_scopes(token_payload)
            access_token = token_payload["access_token"]
            profile_response = request_with_retries(
                "GET",
                "https://gmail.googleapis.com/gmail/v1/users/me/profile",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            profile = profile_response.json()
        except httpx.HTTPError as exc:
            raise GmailProviderError("Gmail OAuth exchange failed.") from exc
        if not isinstance(profile, dict):
            raise GmailProviderError("Google returned an invalid Gmail profile.")
        email = profile.get("emailAddress")
        _validate_oauth_identity(email, email)
        history_id = profile.get("historyId")
        if history_id is not None and (
            not isinstance(history_id, str)
            or not history_id
            or len(history_id) > 120
            or any(character.isspace() for character in history_id)
        ):
            raise GmailProviderError("Google returned an invalid mailbox history identity.")
        return {
            "token_payload": token_payload,
            "provider_account_id": email,
            "display_email": email,
            "history_id": history_id,
            "scopes": scopes,
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
            status_code = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            raise GmailProviderError(
                "Gmail message metadata import failed.", status_code=status_code
            ) from exc
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
            status_code = (
                exc.response.status_code
                if isinstance(exc, httpx.HTTPStatusError)
                else None
            )
            raise GmailProviderError(
                "Gmail attachment fetch failed.", status_code=status_code
            ) from exc
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


def _gmail_call_with_refresh(
    session: Session,
    *,
    context: SessionContext,
    connection: UserMailboxConnection,
    operation: Callable[[GmailProvider, dict[str, Any]], Any],
) -> tuple[dict[str, Any], Any]:
    token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    provider = _gmail_provider(session, context=context)
    try:
        return token_payload, operation(provider, token_payload)
    except GmailProviderError as exc:
        if exc.status_code != 401:
            raise
    token_payload = refresh_google_workspace_access_token(
        session,
        context=context,
        connector="gmail",
        token_payload=token_payload,
    )
    connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
    try:
        return token_payload, operation(provider, token_payload)
    except GmailProviderError as exc:
        if exc.status_code == 401:
            raise GoogleWorkspaceTokenRefreshError(
                "Gmail authorization could not be renewed. Reconnect this account.",
                reauthorization_required=True,
            ) from exc
        raise


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
        "nonce": uuid4().hex,
        "started_at": now.isoformat(),
        "company_id": context.company.id,
        "membership_id": context.membership.id,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, get_settings().auth_secret, algorithm="HS256")


def _verify_state(context: SessionContext, state: str) -> dict[str, Any]:
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
    return payload


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


def _oauth_now() -> datetime:
    return datetime.now(UTC)


def _oauth_error(reason: str, message: str, status_code: int = 409) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": "gmail_oauth_" + reason, "message": message},
    )


def _lock_oauth_authority(
    session: Session,
    context: SessionContext,
    *,
    check_config: bool = True,
) -> tuple[SessionContext, str]:
    # Serialize absent connection rows as well as existing ones; release before I/O.
    serialize_sqlite_writer(session)
    company_id, membership_id = context.company.id, context.membership.id
    token_issued_at = context.token_issued_at
    company, actors = lock_company_memberships_for_oauth(
        session,
        company_id=company_id,
        membership_ids=(membership_id,),
    )
    actor = actors.get(membership_id)
    if actor is None:
        raise _oauth_error("authority_changed", "An active membership is required.", 403)
    if company is None or not company.is_active:
        raise _oauth_error("authority_changed", "The workspace is not active.", 403)
    require_locked_membership_capability(session, actor, "calendar:sync")
    context = get_session_context(
        session,
        membership_id,
        token_issued_at=token_issued_at,
    )
    if not check_config:
        return context, ""
    configuration = session.scalar(
        select(TenantGoogleWorkspaceConfiguration)
        .where(TenantGoogleWorkspaceConfiguration.company_id == company_id)
        .with_for_update(of=TenantGoogleWorkspaceConfiguration)
        .execution_options(populate_existing=True)
    )
    runtime = _gmail_runtime_config(session, context=context)
    fingerprint = hashlib.sha256(
        repr(
            (
                runtime.client_id,
                runtime.client_secret,
                runtime.redirect_uri,
                configuration.id if configuration else None,
                configuration.updated_at if configuration else None,
            )
        ).encode()
    ).hexdigest()
    return context, fingerprint


def _oauth_connection(session: Session, context: SessionContext) -> UserMailboxConnection | None:
    return session.scalar(
        select(UserMailboxConnection)
        .where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        )
        .with_for_update(of=UserMailboxConnection)
        .execution_options(populate_existing=True)
    )


def _fail_oauth_claim(
    session: Session,
    *,
    context: SessionContext,
    company_id: str,
    connection_id: str,
    marker: str,
    config_fingerprint: str,
) -> None:
    session.rollback()
    restore_connected = False
    try:
        _, current_config = _lock_oauth_authority(session, context)
        restore_connected = current_config == config_fingerprint
    except HTTPException:
        # A revoked session may release its own claim but cannot restore access.
        session.rollback()
    connection = session.scalar(
        select(UserMailboxConnection)
        .where(
            UserMailboxConnection.id == connection_id,
            UserMailboxConnection.company_id == company_id,
        )
        .with_for_update(of=UserMailboxConnection)
        .execution_options(populate_existing=True)
    )
    if connection is not None and connection.status == MailboxConnectionStatus.ERROR:
        token = (
            _decrypt_token_payload(connection.encrypted_token_ref)
            if connection.encrypted_token_ref
            else {}
        )
        meta = token.get(_OAUTH_META_KEY, {})
        if isinstance(meta, dict) and meta.get("marker") == marker:
            # Cleanup owns only this attempt, never a replacement or revocation.
            token[_OAUTH_META_KEY] = {
                **meta,
                "marker": None,
                "expires_at": None,
                "result": "failed",
            }
            if restore_connected and meta.get("prior_connected") and token.get("access_token"):
                connection.status = MailboxConnectionStatus.CONNECTED
            connection.encrypted_token_ref = _encrypt_token_payload(token)
    session.commit()


def complete_gmail_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> MailboxConnectionCallbackResponse:
    state_payload = _verify_state(context, state)
    context, config_fingerprint = _lock_oauth_authority(session, context)
    provider = _gmail_provider(session, context=context)
    if not provider.configured:
        raise _oauth_error("unavailable", "Gmail OAuth is not configured.", 503)
    now = _oauth_now()
    attempt = hashlib.sha256((state + "\\0" + code).encode()).hexdigest()
    connection = _oauth_connection(session, context)
    token = (
        _decrypt_token_payload(connection.encrypted_token_ref)
        if connection is not None and connection.encrypted_token_ref
        else {}
    )
    meta = token.get(_OAUTH_META_KEY, {})
    if not isinstance(meta, dict):
        raise _oauth_error("invalid_attempt", "Restart the Gmail connection.")
    if meta.get("marker") and float(meta.get("expires_at") or 0) > now.timestamp():
        raise _oauth_error(
            "exchange_in_flight", "An OAuth exchange is already in progress. Wait briefly."
        )
    if connection is not None and connection.status == MailboxConnectionStatus.REVOKED:
        started = (
            datetime.fromisoformat(state_payload["started_at"])
            if state_payload.get("started_at")
            else datetime.fromtimestamp(state_payload["iat"], UTC)
        )
        revoked_at = (
            connection.updated_at.replace(tzinfo=UTC)
            if connection.updated_at.tzinfo is None
            else connection.updated_at
        )
        if started <= revoked_at:
            raise _oauth_error(
                "attempt_consumed", "This connection attempt was revoked. Start a new connection."
            )
    if connection is None:
        connection = UserMailboxConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=MailboxProvider.GMAIL,
        )
        session.add(connection)
        session.flush()
    # Digest-only consumption survives disconnect; neither state nor code is retried.
    for kind, value in (("state", state), ("code", code)):
        digest = hashlib.sha256(value.encode()).hexdigest()
        consumed = claim_idempotency(
            session,
            company_id=context.company.id,
            actor_scope=f"membership:{context.membership.id}",
            actor_membership_id=context.membership.id,
            http_method="GET",
            operation=f"workspace.oauth.gmail.{kind}_consumed",
            idempotency_key=digest,
            request_hash=digest,
        )
        if consumed.outcome != IdempotencyClaimOutcome.CLAIMED:
            raise _oauth_error(
                "attempt_consumed", "This connection attempt has finished. Start a new connection."
            )
        assert consumed.claim_token is not None and consumed.claim_generation is not None
        complete_idempotency(
            session,
            company_id=context.company.id,
            record_id=consumed.record.id,
            claim_token=consumed.claim_token,
            claim_generation=consumed.claim_generation,
            response_status=202,
            result_type="workspace_oauth_consumption",
            result_id=connection.id,
        )
    marker = uuid4().hex
    prior_connected = connection.status == MailboxConnectionStatus.CONNECTED or (
        meta.get("result") == "pending"
        and meta.get("prior_connected")
        and meta.get("config") == config_fingerprint
    )
    meta = {
        "attempt": attempt,
        "marker": marker,
        "result": "pending",
        "expires_at": min(now.timestamp() + _OAUTH_LEASE_SECONDS, state_payload["exp"]),
        "config": config_fingerprint,
        "prior_connected": bool(prior_connected),
    }
    token[_OAUTH_META_KEY] = meta
    connection.status = MailboxConnectionStatus.ERROR
    connection.encrypted_token_ref = _encrypt_token_payload(token)
    connection_id, company_id = connection.id, context.company.id
    session.commit()

    try:
        exchanged = provider.exchange_code(code=code)
        token_payload = exchanged.get("token_payload") if isinstance(exchanged, dict) else None
        _oauth_token_scopes(token_payload)
        _validate_oauth_identity(
            exchanged.get("provider_account_id"),
            exchanged.get("display_email"),
        )
        history_id = exchanged.get("history_id")
        if history_id is not None and (
            not isinstance(history_id, str)
            or not history_id
            or len(history_id) > 120
            or any(character.isspace() for character in history_id)
        ):
            raise GmailProviderError("Google returned an invalid mailbox history identity.")
        scopes = exchanged.get("scopes")
        if (
            not isinstance(scopes, (list, tuple))
            or any(not isinstance(scope, str) or not scope.strip() for scope in scopes)
            or not set(GMAIL_SCOPES).issubset(scopes)
        ):
            raise GmailProviderError("Google did not grant the required connector permission.")
        encrypted_token = _encrypt_token_payload(
            {
                **token_payload,
                _OAUTH_META_KEY: {
                    **meta,
                    "marker": None,
                    "expires_at": None,
                    "result": "complete",
                },
            }
        )
    except Exception as exc:
        _fail_oauth_claim(
            session,
            context=context,
            company_id=company_id,
            connection_id=connection_id,
            marker=marker,
            config_fingerprint=config_fingerprint,
        )
        raise _oauth_error(
            "exchange_failed",
            "Gmail authorization could not complete. Start a new connection.",
            502,
        ) from exc

    try:
        context, current_config = _lock_oauth_authority(session, context)
        connection = _oauth_connection(session, context)
        current = (
            _decrypt_token_payload(connection.encrypted_token_ref).get(_OAUTH_META_KEY, {})
            if connection is not None and connection.encrypted_token_ref
            else {}
        )
        if (
            current_config != config_fingerprint
            or connection is None
            or connection.id != connection_id
            or connection.status != MailboxConnectionStatus.ERROR
            or current.get("marker") != marker
            or float(current.get("expires_at") or 0) <= _oauth_now().timestamp()
        ):
            raise _oauth_error(
                "finalize_stale", "Connection authority changed. Start a new connection."
            )
        connection.provider_account_id = exchanged["provider_account_id"]
        connection.display_email = exchanged.get("display_email")
        connection.status = MailboxConnectionStatus.CONNECTED
        connection.encrypted_token_ref = encrypted_token
        connection.scopes_json = list(scopes)
        connection.last_history_id = history_id
        connection.connected_at = _oauth_now()
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
            connected=True, connection=_connection_record(connection)
        )
    except Exception:
        _fail_oauth_claim(
            session,
            context=context,
            company_id=company_id,
            connection_id=connection_id,
            marker=marker,
            config_fingerprint=config_fingerprint,
        )
        raise


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
    context, _ = _lock_oauth_authority(session, context, check_config=False)
    connection = session.scalar(
        select(UserMailboxConnection)
        .where(
            UserMailboxConnection.id == connection_id,
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.membership_id == context.membership.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        )
        .with_for_update(of=UserMailboxConnection)
        .execution_options(populate_existing=True)
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
    try:
        _token_payload, messages = _gmail_call_with_refresh(
            session,
            context=context,
            connection=connection,
            operation=lambda provider, token: provider.list_recent_messages(
                token_payload=token,
                limit=payload.limit,
            ),
        )
    except GoogleWorkspaceTokenRefreshError as exc:
        if exc.reauthorization_required:
            connection.status = MailboxConnectionStatus.ERROR
        session.add(connection)
        session.commit()
        raise HTTPException(
            status_code=(
                status.HTTP_409_CONFLICT
                if exc.reauthorization_required
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc
    except GmailProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail sync could not complete. Check the connection and try again.",
        ) from exc
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
                company_id=matter.company_id,
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


def _attachment_review_snapshot(*rows: Any) -> tuple[Any, ...]:
    # Include every persisted field: a relink, reject, reconnect or credential
    # rotation must win over bytes fetched using an earlier review snapshot.
    return tuple(
        tuple(getattr(row, column.key) for column in row.__table__.columns) for row in rows
    )


def _admit_attachment_review(
    session: Session,
    *,
    company_id: str,
    actor_id: str,
    token_issued_at: float | None,
    candidate_id: str,
    operational: bool,
) -> tuple[
    SessionContext,
    Matter,
    MailboxAttachmentCandidate,
    UserMailboxConnection,
    GmailRuntimeConfig,
    tuple[Any, ...],
]:
    with session.no_autoflush:
        lock_matter_private_authority(session, company_id=company_id)
        candidate = session.scalar(
            select(MailboxAttachmentCandidate)
            .where(
                MailboxAttachmentCandidate.id == candidate_id,
                MailboxAttachmentCandidate.company_id == company_id,
            )
            .execution_options(populate_existing=True)
        )
        message = (
            session.get(MailboxMessageImport, candidate.message_import_id, populate_existing=True)
            if candidate is not None
            else None
        )
        connection = (
            session.get(
                UserMailboxConnection, message.mailbox_connection_id, populate_existing=True
            )
            if message is not None
            else None
        )
        if (
            candidate is None
            or message is None
            or connection is None
            or message.company_id != company_id
            or connection.company_id != company_id
            or connection.provider != MailboxProvider.GMAIL
        ):
            raise HTTPException(status_code=404, detail="Mailbox attachment candidate not found.")
        owner_id, matter_id = connection.membership_id, candidate.matter_id
        actors = lock_company_memberships_for_assignment(
            session,
            company_id=company_id,
            membership_ids={actor_id, owner_id},
            no_key_update=True,
        )
        if actor_id not in actors or owner_id not in actors:
            raise HTTPException(status_code=403, detail="The current session is no longer active.")
        context = get_session_context(session, actor_id, token_issued_at=token_issued_at)
        require_locked_membership_capability(session, actors[actor_id], "calendar:sync")
        get_session_context(session, owner_id)
        if matter_id is None:
            raise HTTPException(status_code=409, detail="Candidate is not linked to a matter.")
        matter = session.scalar(
            select(Matter)
            .where(Matter.id == matter_id, Matter.company_id == company_id)
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
        if matter is None:
            raise HTTPException(status_code=404, detail="Matter not found.")
        assert_access(session, context=context, matter=matter, commit_denial=False)
        if operational:
            matter = require_operational_matter(
                session,
                matter=matter,
                operation="import a Gmail attachment",
            )
        configuration = session.scalar(
            select(TenantGoogleWorkspaceConfiguration)
            .where(TenantGoogleWorkspaceConfiguration.company_id == company_id)
            .with_for_update(of=TenantGoogleWorkspaceConfiguration)
            .execution_options(populate_existing=True)
        )
        runtime = _gmail_runtime_config(session, context=context)
        config_snapshot = (
            runtime,
            configuration.id if configuration else None,
            configuration.updated_at if configuration else None,
        )
        connection = session.scalar(
            select(UserMailboxConnection)
            .where(UserMailboxConnection.id == connection.id)
            .with_for_update(of=UserMailboxConnection)
            .execution_options(populate_existing=True)
        )
        message = session.scalar(
            select(MailboxMessageImport)
            .where(MailboxMessageImport.id == message.id)
            .with_for_update(of=MailboxMessageImport)
            .execution_options(populate_existing=True)
        )
        candidate = session.scalar(
            select(MailboxAttachmentCandidate)
            .where(MailboxAttachmentCandidate.id == candidate_id)
            .with_for_update(of=MailboxAttachmentCandidate)
            .execution_options(populate_existing=True)
        )
        if (
            connection is None
            or message is None
            or candidate is None
            or connection.company_id != company_id
            or connection.membership_id != owner_id
            or connection.provider != MailboxProvider.GMAIL
            or message.company_id != company_id
            or candidate.company_id != company_id
            or message.mailbox_connection_id != connection.id
            or candidate.message_import_id != message.id
            or candidate.matter_id != matter_id
            or message.matter_id != matter_id
        ):
            raise HTTPException(status_code=409, detail="Mailbox attachment review changed.")
        if operational and (
            connection.status != MailboxConnectionStatus.CONNECTED
            or not connection.encrypted_token_ref
            or not set(GMAIL_SCOPES).issubset(connection.scopes_json or [])
        ):
            raise HTTPException(
                status_code=409, detail="Gmail is not connected. Reconnect this account."
            )
        snapshot = (
            matter.lifecycle_version,
            config_snapshot,
            _attachment_review_snapshot(candidate, message, connection),
        )
        return context, matter, candidate, connection, runtime, snapshot


def _refresh_attachment_access_token(
    *,
    runtime: GmailRuntimeConfig,
    token_payload: dict[str, Any],
) -> dict[str, Any]:
    """Refresh from the captured tenant configuration without a database session."""
    import httpx

    if not runtime.configured:
        raise GoogleWorkspaceTokenRefreshError(
            "Google Workspace OAuth configuration is incomplete."
        )
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise GoogleWorkspaceTokenRefreshError(
            "Google authorization must be renewed. Reconnect this account.",
            reauthorization_required=True,
        )
    try:
        response = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": runtime.client_id,
                "client_secret": runtime.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise GoogleWorkspaceTokenRefreshError(
            "Google token refresh is temporarily unavailable. Try again shortly."
        ) from exc
    if response.status_code in {400, 401}:
        try:
            returned = response.json()
        except ValueError:
            returned = None
        if isinstance(returned, dict) and returned.get("error") == "invalid_grant":
            raise GoogleWorkspaceTokenRefreshError(
                "Google authorization expired or was revoked. Reconnect this account.",
                reauthorization_required=True,
            )
        raise GoogleWorkspaceTokenRefreshError(
            "Google rejected token refresh. Check the tenant's Google Workspace setup."
        )
    if response.status_code == 429 or response.status_code >= 500:
        raise GoogleWorkspaceTokenRefreshError(
            "Google token refresh is temporarily unavailable. Try again shortly."
        )
    if response.is_error:
        raise GoogleWorkspaceTokenRefreshError(
            "Google token refresh could not be completed. "
            "Check the tenant's Google Workspace setup."
        )
    try:
        returned = response.json()
    except ValueError as exc:
        raise GoogleWorkspaceTokenRefreshError(
            "Google returned an invalid token refresh response."
        ) from exc
    if (
        not isinstance(returned, dict)
        or not isinstance(returned.get("access_token"), str)
        or not returned["access_token"]
    ):
        raise GoogleWorkspaceTokenRefreshError("Google did not return a refreshed access token.")
    refreshed = {**token_payload, **returned}
    if not returned.get("refresh_token"):
        refreshed["refresh_token"] = refresh_token
    try:
        _oauth_token_scopes(refreshed)
    except GmailProviderError as exc:
        raise GoogleWorkspaceTokenRefreshError(
            "Google returned an invalid token refresh response."
        ) from exc
    return refreshed


def _imported_attachment_review_response(
    session: Session,
    candidate: MailboxAttachmentCandidate,
) -> MailboxAttachmentCandidateReviewResponse:
    attachment = (
        session.get(MatterAttachment, candidate.imported_attachment_id)
        if candidate.imported_attachment_id
        else None
    )
    if attachment is None or attachment.matter_id != candidate.matter_id:
        raise HTTPException(status_code=409, detail="The imported Gmail attachment is unavailable.")
    return MailboxAttachmentCandidateReviewResponse(
        candidate=_attachment_record(candidate),
        imported_attachment_id=attachment.id,
    )


def review_attachment_candidate(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
    payload: MailboxAttachmentCandidateReviewRequest,
) -> MailboxAttachmentCandidateReviewResponse:
    from caseops_api.services.communications import _persist_inbound_attachment
    from caseops_api.services.document_jobs import enqueue_processing_job
    from caseops_api.services.document_storage import delete_stored_document

    require_read_only_upload_session(
        session,
        detail="Gmail attachment review requires a read-only session before upload.",
    )
    company_id, actor_id, token_issued_at = (
        context.company.id,
        context.membership.id,
        context.token_issued_at,
    )

    def admit():
        return _admit_attachment_review(
            session,
            company_id=company_id,
            actor_id=actor_id,
            token_issued_at=token_issued_at,
            candidate_id=candidate_id,
            operational=payload.action != "reject",
        )

    context, matter, candidate, connection, runtime, snapshot = admit()
    if payload.action == "reject":
        if candidate.status == MailboxAttachmentCandidateStatus.APPROVED_IMPORTED:
            raise HTTPException(
                status_code=409, detail="This Gmail attachment was already imported."
            )
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
        session.flush()
        result = MailboxAttachmentCandidateReviewResponse(candidate=_attachment_record(candidate))
        session.commit()
        return result
    if candidate.status == MailboxAttachmentCandidateStatus.APPROVED_IMPORTED:
        result = _imported_attachment_review_response(session, candidate)
        session.rollback()
        return result
    provider_attachment_id = _decrypt_secret_safe(candidate.encrypted_provider_attachment_ref)
    if not provider_attachment_id:
        raise HTTPException(status_code=409, detail="Provider attachment reference is missing.")
    matter_id = matter.id
    message_id = candidate.message_import.provider_message_id
    filename, content_type = candidate.filename or "gmail-attachment", candidate.content_type
    token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    original_token = dict(token_payload)
    provider = _gmail_provider_override or GoogleGmailProvider(runtime)
    if not runtime.configured or not provider.configured:
        raise HTTPException(status_code=503, detail="Gmail OAuth is not configured.")
    session.rollback()
    attachment = None
    commit_attempted = False

    def discard_staged():
        if attachment is not None:
            try:
                delete_stored_document(attachment.storage_key)
            except Exception:
                logger.exception("gmail_attachment.staged_cleanup_failed")

    try:
        try:
            content = provider.fetch_attachment(
                token_payload=token_payload,
                message_id=message_id,
                attachment_id=provider_attachment_id,
            )
        except GmailProviderError as exc:
            if exc.status_code != 401:
                raise
            refreshed = _refresh_attachment_access_token(
                runtime=runtime, token_payload=token_payload
            )
            token_payload.update(refreshed)
            try:
                content = provider.fetch_attachment(
                    token_payload=token_payload,
                    message_id=message_id,
                    attachment_id=provider_attachment_id,
                )
            except GmailProviderError as retry_error:
                if retry_error.status_code == 401:
                    raise GoogleWorkspaceTokenRefreshError(
                        "Gmail authorization could not be renewed. Reconnect this account.",
                        reauthorization_required=True,
                    ) from retry_error
                raise
        attachment = _persist_inbound_attachment(
            session,
            company_id=company_id,
            matter_id=matter_id,
            actor_id=actor_id,
            staged_size_bytes=0,
            filename=filename,
            content_type=content_type,
            stream=BytesIO(content),
        )
        context, matter, candidate, connection, _, current = admit()
        if candidate.status == MailboxAttachmentCandidateStatus.APPROVED_IMPORTED:
            result = _imported_attachment_review_response(session, candidate)
            session.rollback()
            discard_staged()
            return result
        if current != snapshot:
            raise HTTPException(
                status_code=409,
                detail="Mailbox attachment review changed. Reload it.",
            )
        assert_storage_quota_allows_upload(
            session,
            company_id=company_id,
            matter_id=matter_id,
            incoming_size_bytes=attachment.size_bytes,
        )
        if token_payload != original_token:
            connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
        session.add(attachment)
        session.flush()
        enqueue_processing_job(
            session,
            company_id=company_id,
            requested_by_membership_id=actor_id,
            target_type=DocumentProcessingTargetType.MATTER_ATTACHMENT,
            attachment_id=attachment.id,
            action=DocumentProcessingAction.INITIAL_INDEX,
        )
        session.add(
            MatterActivity(
                matter_id=matter_id,
                actor_membership_id=actor_id,
                event_type="inbound_email_attachment_added",
                title="Gmail attachment imported",
                detail=f"{attachment.original_filename} queued for document processing.",
            )
        )
        candidate.status = MailboxAttachmentCandidateStatus.APPROVED_IMPORTED
        candidate.imported_attachment_id = attachment.id
        candidate.last_error_redacted = None
        record_from_context(
            session,
            context,
            action="mailbox.gmail_attachment.imported",
            target_type="mailbox_attachment_candidate",
            target_id=candidate_id,
            matter_id=matter_id,
            metadata={
                "provider": MailboxProvider.GMAIL,
                "attachment_id": redact_identifier(attachment.id),
            },
        )
        session.flush()
        result = MailboxAttachmentCandidateReviewResponse(
            candidate=_attachment_record(candidate),
            imported_attachment_id=attachment.id,
        )
        commit_attempted = True
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        # An acknowledgement failure is not proof that the database rolled back.
        if commit_attempted:
            raise
        discard_staged()
        if isinstance(exc, StorageQuotaExceeded):
            raise exc.to_http_exception() from exc
        if isinstance(exc, HTTPException):
            raise
        try:
            context, matter, candidate, connection, _, current = admit()
        except Exception:
            session.rollback()
            raise
        if current != snapshot:
            session.rollback()
            raise HTTPException(
                status_code=409,
                detail="Mailbox attachment review changed. Reload it.",
            ) from exc
        reconnect = (
            isinstance(exc, GoogleWorkspaceTokenRefreshError) and exc.reauthorization_required
        )
        if reconnect:
            connection.status = MailboxConnectionStatus.ERROR
        if token_payload != original_token:
            connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
        failure_detail = (
            str(exc)
            if isinstance(exc, GoogleWorkspaceTokenRefreshError)
            else "Gmail attachment is temporarily unavailable. Try again."
        )
        candidate.last_error_redacted = failure_detail
        record_from_context(
            session,
            context,
            action="mailbox.gmail_attachment.import_failed",
            target_type="mailbox_attachment_candidate",
            target_id=candidate_id,
            matter_id=matter_id,
            result="failed",
            metadata={
                "provider": MailboxProvider.GMAIL,
                "reason": "reauthorization_required" if reconnect else "provider_unavailable",
            },
        )
        session.commit()
        raise HTTPException(
            status_code=(
                409
                if reconnect
                else 503
                if isinstance(exc, GoogleWorkspaceTokenRefreshError)
                else 502
            ),
            detail=failure_detail,
        ) from exc


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
