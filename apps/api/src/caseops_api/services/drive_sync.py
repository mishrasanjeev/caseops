from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    DriveConnectionStatus,
    DriveProvider,
    UserDriveConnection,
)
from caseops_api.schemas.drive import (
    GoogleDriveConnectionCallbackResponse,
    GoogleDriveConnectionRecord,
    GoogleDriveConnectionStartResponse,
    GoogleDriveFileListResponse,
    GoogleDriveFileRecord,
    GoogleDriveStatusResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import _decrypt_token_payload, _encrypt_token_payload
from caseops_api.services.identity import SessionContext
from caseops_api.services.notification_delivery import redact_provider_error

GOOGLE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
_STATE_KIND = "google_drive_oauth"
_STATE_TTL_MINUTES = 10


class GoogleDriveProviderError(RuntimeError):
    """Provider failures safe to redact and show to users."""


@dataclass(frozen=True, slots=True)
class GoogleDriveRuntimeConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True, slots=True)
class GoogleDriveFileMetadata:
    provider_file_id: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    modified_time: datetime | None = None
    web_url: str | None = None


class GoogleDriveProviderProtocol(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def authorization_url(self, *, state: str) -> str: ...

    def exchange_code(self, *, code: str) -> dict[str, Any]: ...

    def list_files(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GoogleDriveFileMetadata]: ...


class GoogleDriveProvider:
    def __init__(self, config: GoogleDriveRuntimeConfig | None = None) -> None:
        self._config = config

    def _runtime_config(self) -> GoogleDriveRuntimeConfig:
        return self._config or _google_drive_runtime_config()

    @property
    def configured(self) -> bool:
        return self._runtime_config().configured

    @property
    def unavailable_reason(self) -> str | None:
        if self.configured:
            return None
        return "Google Drive OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:
        config = self._runtime_config()
        if not config.configured:
            raise GoogleDriveProviderError(
                self.unavailable_reason or "Google Drive unavailable."
            )
        qs = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "scope": " ".join(GOOGLE_DRIVE_SCOPES),
                "state": state,
                "access_type": "offline",
                "include_granted_scopes": "true",
                "prompt": "consent",
            }
        )
        return f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        config = self._runtime_config()
        if not config.configured:
            raise GoogleDriveProviderError(
                self.unavailable_reason or "Google Drive unavailable."
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GoogleDriveProviderError("Google Drive HTTP client is unavailable.") from exc
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
                raise GoogleDriveProviderError("Google did not return an access token.")
            about_response = httpx.get(
                "https://www.googleapis.com/drive/v3/about",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "user"},
                timeout=15,
            )
            about_response.raise_for_status()
            about = about_response.json()
        except httpx.HTTPError as exc:
            raise GoogleDriveProviderError("Google Drive OAuth exchange failed.") from exc
        user = about.get("user") if isinstance(about.get("user"), dict) else {}
        scope_text = str(token_payload.get("scope") or " ".join(GOOGLE_DRIVE_SCOPES))
        return {
            "token_payload": token_payload,
            "provider_account_id": str(user.get("permissionId") or "") or None,
            "display_email": str(user.get("emailAddress") or "") or None,
            "scopes": scope_text.split(),
        }

    def list_files(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GoogleDriveFileMetadata]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GoogleDriveProviderError("Google Drive HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise GoogleDriveProviderError("Stored Google Drive token is unavailable.")
        try:
            response = httpx.get(
                "https://www.googleapis.com/drive/v3/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "pageSize": min(max(limit, 1), 100),
                    "q": "trashed = false",
                    "orderBy": "modifiedTime desc",
                    "fields": (
                        "files(id,name,mimeType,size,modifiedTime,webViewLink)"
                    ),
                },
                timeout=15,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GoogleDriveProviderError("Google Drive file listing failed.") from exc
        files = response.json().get("files", [])
        return [_parse_drive_file(item) for item in files if isinstance(item, dict)]


_drive_provider_override: GoogleDriveProviderProtocol | None = None


def set_google_drive_provider_for_tests(
    provider: GoogleDriveProviderProtocol | None,
) -> None:
    global _drive_provider_override
    _drive_provider_override = provider


def _drive_provider() -> GoogleDriveProviderProtocol:
    return _drive_provider_override or GoogleDriveProvider(_google_drive_runtime_config())


def _google_drive_runtime_config() -> GoogleDriveRuntimeConfig:
    settings = get_settings()
    return GoogleDriveRuntimeConfig(
        client_id=settings.google_drive_client_id,
        client_secret=settings.google_drive_client_secret,
        redirect_uri=settings.google_drive_redirect_uri,
    )


def _missing_google_drive_config_names(
    config: GoogleDriveRuntimeConfig | None = None,
) -> list[str]:
    runtime = config or _google_drive_runtime_config()
    missing: list[str] = []
    if not runtime.client_id:
        missing.append("GOOGLE_DRIVE_CLIENT_ID")
    if not runtime.client_secret:
        missing.append("GOOGLE_DRIVE_CLIENT_SECRET")
    if not runtime.redirect_uri:
        missing.append("GOOGLE_DRIVE_REDIRECT_URI")
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
            detail="Invalid Google Drive connection state.",
        ) from exc
    if (
        payload.get("kind") != _STATE_KIND
        or str(payload.get("company_id")) != context.company.id
        or str(payload.get("membership_id")) != context.membership.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Google Drive connection state does not match the current session.",
        )


def _connection_record(connection: UserDriveConnection) -> GoogleDriveConnectionRecord:
    return GoogleDriveConnectionRecord(
        id=connection.id,
        company_id=connection.company_id,
        membership_id=connection.membership_id,
        provider=connection.provider,  # type: ignore[arg-type]
        provider_account_id=connection.provider_account_id,
        display_email=connection.display_email,
        status=connection.status,  # type: ignore[arg-type]
        scopes=list(connection.scopes_json or []),
        connected_at=connection.connected_at,
        last_list_at=connection.last_list_at,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _file_record(file: GoogleDriveFileMetadata) -> GoogleDriveFileRecord:
    return GoogleDriveFileRecord(
        provider_file_id=file.provider_file_id,
        name=file.name,
        mime_type=file.mime_type,
        size_bytes=file.size_bytes,
        modified_time=file.modified_time,
        web_url=file.web_url,
    )


def list_google_drive_status(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleDriveStatusResponse:
    config = _google_drive_runtime_config()
    rows = list(
        session.scalars(
            select(UserDriveConnection)
            .where(
                UserDriveConnection.company_id == context.company.id,
                UserDriveConnection.membership_id == context.membership.id,
                UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
            )
            .order_by(UserDriveConnection.created_at.asc())
        )
    )
    return GoogleDriveStatusResponse(
        configured=config.configured,
        missing_config_names=_missing_google_drive_config_names(config),
        connections=[_connection_record(row) for row in rows],
    )


def start_google_drive_connection(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleDriveConnectionStartResponse:
    _ = session
    provider = _drive_provider()
    if not provider.configured:
        return GoogleDriveConnectionStartResponse(
            provider_available=False,
            unavailable_reason=provider.unavailable_reason,
        )
    return GoogleDriveConnectionStartResponse(
        provider_available=True,
        auth_url=provider.authorization_url(state=_sign_state(context)),
    )


def complete_google_drive_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> GoogleDriveConnectionCallbackResponse:
    provider = _drive_provider()
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Drive OAuth is not configured.",
        )
    _verify_state(context, state)
    try:
        exchanged = provider.exchange_code(code=code)
    except GoogleDriveProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Drive OAuth exchange failed.",
        ) from exc
    token_payload = exchanged["token_payload"]
    now = datetime.now(UTC)
    existing = session.scalar(
        select(UserDriveConnection).where(
            UserDriveConnection.company_id == context.company.id,
            UserDriveConnection.membership_id == context.membership.id,
            UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
        )
    )
    if existing is None:
        existing = UserDriveConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=DriveProvider.GOOGLE_DRIVE,
        )
        session.add(existing)
    existing.provider_account_id = exchanged.get("provider_account_id")
    existing.display_email = exchanged.get("display_email")
    existing.status = DriveConnectionStatus.CONNECTED
    existing.encrypted_token_ref = _encrypt_token_payload(token_payload)
    existing.scopes_json = list(exchanged.get("scopes") or GOOGLE_DRIVE_SCOPES)
    existing.connected_at = now
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise
    record_from_context(
        session,
        context,
        action="drive.google.connected",
        target_type="user_drive_connection",
        target_id=existing.id,
        metadata={
            "provider": DriveProvider.GOOGLE_DRIVE,
            "scope_count": len(existing.scopes_json or []),
            "display_email_present": bool(existing.display_email),
        },
    )
    session.commit()
    session.refresh(existing)
    return GoogleDriveConnectionCallbackResponse(
        connected=True,
        connection=_connection_record(existing),
    )


def revoke_google_drive_connection(
    session: Session,
    *,
    context: SessionContext,
    connection_id: str,
) -> GoogleDriveConnectionRecord:
    connection = session.scalar(
        select(UserDriveConnection).where(
            UserDriveConnection.id == connection_id,
            UserDriveConnection.company_id == context.company.id,
            UserDriveConnection.membership_id == context.membership.id,
            UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
        )
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Google Drive connection not found.")
    connection.status = DriveConnectionStatus.REVOKED
    connection.encrypted_token_ref = None
    session.add(connection)
    record_from_context(
        session,
        context,
        action="drive.google.revoked",
        target_type="user_drive_connection",
        target_id=connection.id,
        metadata={"provider": DriveProvider.GOOGLE_DRIVE},
    )
    session.commit()
    session.refresh(connection)
    return _connection_record(connection)


def list_google_drive_files(
    session: Session,
    *,
    context: SessionContext,
    limit: int = 25,
) -> GoogleDriveFileListResponse:
    connection = _connected_google_drive_connection(session, context=context)
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        files = _drive_provider().list_files(
            token_payload=token_payload,
            limit=max(1, min(limit, 100)),
        )
    except Exception as exc:
        connection.status = DriveConnectionStatus.ERROR
        session.add(connection)
        record_from_context(
            session,
            context,
            action="drive.google.list_failed",
            target_type="user_drive_connection",
            target_id=connection.id,
            result="failed",
            metadata={
                "provider": DriveProvider.GOOGLE_DRIVE,
                "error": redact_provider_error(str(exc))[:500],
            },
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google Drive file listing failed.",
        ) from exc
    connection.last_list_at = datetime.now(UTC)
    session.add(connection)
    record_from_context(
        session,
        context,
        action="drive.google.files_listed",
        target_type="user_drive_connection",
        target_id=connection.id,
        metadata={
            "provider": DriveProvider.GOOGLE_DRIVE,
            "file_count": len(files),
        },
    )
    session.commit()
    return GoogleDriveFileListResponse(
        connection_id=connection.id,
        files=[_file_record(file) for file in files],
    )


def _connected_google_drive_connection(
    session: Session,
    *,
    context: SessionContext,
) -> UserDriveConnection:
    connection = session.scalar(
        select(UserDriveConnection).where(
            UserDriveConnection.company_id == context.company.id,
            UserDriveConnection.membership_id == context.membership.id,
            UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
            UserDriveConnection.status == DriveConnectionStatus.CONNECTED,
        )
    )
    if connection is None or not connection.encrypted_token_ref:
        raise HTTPException(status_code=409, detail="Google Drive is not connected.")
    return connection


def _parse_drive_file(payload: dict[str, Any]) -> GoogleDriveFileMetadata:
    modified_time = None
    raw_modified = str(payload.get("modifiedTime") or "")
    if raw_modified:
        try:
            modified_time = datetime.fromisoformat(raw_modified.replace("Z", "+00:00"))
        except ValueError:
            modified_time = None
    size = payload.get("size")
    try:
        size_bytes = int(size) if size is not None else None
    except (TypeError, ValueError):
        size_bytes = None
    return GoogleDriveFileMetadata(
        provider_file_id=str(payload.get("id") or ""),
        name=str(payload.get("name") or "Untitled"),
        mime_type=str(payload.get("mimeType") or "") or None,
        size_bytes=size_bytes,
        modified_time=modified_time,
        web_url=str(payload.get("webViewLink") or "") or None,
    )


__all__ = [
    "GOOGLE_DRIVE_SCOPES",
    "GoogleDriveFileMetadata",
    "complete_google_drive_connection",
    "list_google_drive_files",
    "list_google_drive_status",
    "revoke_google_drive_connection",
    "set_google_drive_provider_for_tests",
    "start_google_drive_connection",
]
