from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
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
    DriveFileCandidate,
    DriveProvider,
    DriveSyncControl,
    Matter,
    ReviewCandidateStatus,
    UserDriveConnection,
)
from caseops_api.schemas.drive import (
    DriveCandidateListResponse,
    DriveCandidateRecord,
    DriveCandidateReviewRequest,
    DriveCandidateReviewResponse,
    DriveCandidateSyncRequest,
    DriveCandidateSyncResponse,
    DriveSyncControlRecord,
    DriveSyncControlUpdateRequest,
    GoogleDriveConnectionCallbackResponse,
    GoogleDriveConnectionRecord,
    GoogleDriveConnectionStartResponse,
    GoogleDriveFileListResponse,
    GoogleDriveFileRecord,
    GoogleDriveStatusResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import _decrypt_token_payload, _encrypt_token_payload
from caseops_api.services.google_workspace import google_workspace_oauth_config
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.matter_access import assert_access, visible_matters_filter
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

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
    owner_display: str | None = None
    folder_path: str | None = None


class GoogleDriveProviderProtocol(Protocol):
    @property
    def configured(self) -> bool:
        raise NotImplementedError

    @property
    def unavailable_reason(self) -> str | None:
        raise NotImplementedError

    def authorization_url(self, *, state: str) -> str:

        raise NotImplementedError

    def exchange_code(self, *, code: str) -> dict[str, Any]:

        raise NotImplementedError

    def list_files(
        self,
        *,
        token_payload: dict[str, Any],
        limit: int,
    ) -> list[GoogleDriveFileMetadata]:
        raise NotImplementedError

    def fetch_file(
        self,
        *,
        token_payload: dict[str, Any],
        file_id: str,
    ) -> bytes:
        raise NotImplementedError


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
            raise GoogleDriveProviderError(self.unavailable_reason or "Google Drive unavailable.")
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
            raise GoogleDriveProviderError(self.unavailable_reason or "Google Drive unavailable.")
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
            about_response = request_with_retries(
                "GET",
                "https://www.googleapis.com/drive/v3/about",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"fields": "user"},
                timeout=15,
            )
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
            response = request_with_retries(
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "pageSize": min(max(limit, 1), 100),
                    "q": "trashed = false",
                    "orderBy": "modifiedTime desc",
                    "fields": (
                        "files(id,name,mimeType,size,modifiedTime,webViewLink,owners(displayName,emailAddress))"
                    ),
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise GoogleDriveProviderError("Google Drive file listing failed.") from exc
        files = response.json().get("files", [])
        return [_parse_drive_file(item) for item in files if isinstance(item, dict)]

    def fetch_file(
        self,
        *,
        token_payload: dict[str, Any],
        file_id: str,
    ) -> bytes:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover
            raise GoogleDriveProviderError("Google Drive HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise GoogleDriveProviderError("Stored Google Drive token is unavailable.")
        try:
            response = request_with_retries(
                "GET",
                f"https://www.googleapis.com/drive/v3/files/{file_id}",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"alt": "media"},
                timeout=30,
            )
        except httpx.HTTPError as exc:
            raise GoogleDriveProviderError("Google Drive file import failed.") from exc
        return bytes(response.content)


_drive_provider_override: GoogleDriveProviderProtocol | None = None


def set_google_drive_provider_for_tests(
    provider: GoogleDriveProviderProtocol | None,
) -> None:
    global _drive_provider_override
    _drive_provider_override = provider


def _drive_provider(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GoogleDriveProviderProtocol:
    return _drive_provider_override or GoogleDriveProvider(
        _google_drive_runtime_config(session, context=context)
    )


def _google_drive_runtime_config(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GoogleDriveRuntimeConfig:
    settings = get_settings()
    workspace_config = google_workspace_oauth_config(
        session,
        context=context,
        connector="drive",
    )
    if workspace_config.source in {"tenant_admin", "missing"}:
        return GoogleDriveRuntimeConfig(
            client_id=workspace_config.client_id,
            client_secret=workspace_config.client_secret,
            redirect_uri=workspace_config.redirect_uri,
        )
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


def _control_record(row: DriveSyncControl) -> DriveSyncControlRecord:
    return DriveSyncControlRecord(
        id=row.id,
        company_id=row.company_id,
        provider=row.provider,  # type: ignore[arg-type]
        allowed_folders=list(row.allowed_folders_json or []),
        blocked_folders=list(row.blocked_folders_json or []),
        max_file_size_bytes=row.max_file_size_bytes,
        allowed_mime_types=list(row.allowed_mime_types_json or []),
        mode=row.mode,  # type: ignore[arg-type]
        auto_import_enabled=row.auto_import_enabled,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _candidate_record(row: DriveFileCandidate) -> DriveCandidateRecord:
    return DriveCandidateRecord(
        id=row.id,
        company_id=row.company_id,
        provider=row.provider,  # type: ignore[arg-type]
        provider_file_id=row.provider_file_id,
        provider_version=row.provider_version,
        name=row.name,
        mime_type=row.mime_type,
        size_bytes=row.size_bytes,
        owner_display=row.owner_display,
        modified_time=row.modified_time,
        folder_path=row.folder_path,
        web_url=row.web_url,
        suggested_matter_id=row.suggested_matter_id,
        linked_matter_id=row.linked_matter_id,
        confidence=row.confidence,
        status=row.status,  # type: ignore[arg-type]
        imported_attachment_id=row.imported_attachment_id,
        provenance=row.provenance_json,
        last_error_redacted=row.last_error_redacted,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _ensure_drive_control(
    session: Session,
    *,
    context: SessionContext,
    provider: str = DriveProvider.GOOGLE_DRIVE,
) -> DriveSyncControl:
    row = session.scalar(
        select(DriveSyncControl).where(
            DriveSyncControl.company_id == context.company.id,
            DriveSyncControl.provider == str(provider),
        )
    )
    if row is None:
        row = DriveSyncControl(company_id=context.company.id, provider=str(provider))
        session.add(row)
        session.flush()
    return row


def _match_drive_matter(
    session: Session,
    *,
    context: SessionContext,
    file: GoogleDriveFileMetadata,
) -> Matter | None:
    haystack = f"{file.name} {file.folder_path or ''}".lower()
    matters = session.scalars(
        select(Matter).where(
            Matter.company_id == context.company.id,
            visible_matters_filter(context),
        )
    )
    for matter in matters:
        if matter.matter_code.lower() in haystack:
            return matter
    return None


def _provider_version(file: GoogleDriveFileMetadata) -> str:
    if file.modified_time is not None:
        return file.modified_time.isoformat()
    return "metadata"


def _candidate_allowed(control: DriveSyncControl, file: DriveFileCandidate) -> str | None:
    allowed_mime_types = list(control.allowed_mime_types_json or [])
    if allowed_mime_types and (file.mime_type or "") not in allowed_mime_types:
        return "MIME type is not allowed by tenant Drive controls."
    if file.size_bytes is not None and file.size_bytes > control.max_file_size_bytes:
        return "File exceeds tenant Drive max file size."
    blocked = [value.lower() for value in (control.blocked_folders_json or [])]
    folder_path = (file.folder_path or "").lower()
    if blocked and any(marker in folder_path for marker in blocked):
        return "File is under a blocked folder."
    allowed = [value.lower() for value in (control.allowed_folders_json or [])]
    if allowed and not any(marker in folder_path for marker in allowed):
        return "File is outside tenant allowed folders."
    return None


def get_drive_sync_control(
    session: Session,
    *,
    context: SessionContext,
    provider: str = DriveProvider.GOOGLE_DRIVE,
) -> DriveSyncControlRecord:
    return _control_record(_ensure_drive_control(session, context=context, provider=provider))


def update_drive_sync_control(
    session: Session,
    *,
    context: SessionContext,
    payload: DriveSyncControlUpdateRequest,
    provider: str = DriveProvider.GOOGLE_DRIVE,
) -> DriveSyncControlRecord:
    row = _ensure_drive_control(session, context=context, provider=provider)
    if payload.allowed_folders is not None:
        row.allowed_folders_json = payload.allowed_folders
    if payload.blocked_folders is not None:
        row.blocked_folders_json = payload.blocked_folders
    if payload.max_file_size_bytes is not None:
        row.max_file_size_bytes = payload.max_file_size_bytes
    if payload.allowed_mime_types is not None:
        row.allowed_mime_types_json = payload.allowed_mime_types
    if payload.mode is not None:
        row.mode = payload.mode
    if payload.auto_import_enabled is not None:
        row.auto_import_enabled = bool(payload.auto_import_enabled)
    row.auto_import_enabled = False
    session.add(row)
    record_from_context(
        session,
        context,
        action="drive.controls.updated",
        target_type="drive_sync_control",
        target_id=row.id,
        metadata={
            "provider": provider,
            "auto_import_enabled": False,
            "mode": row.mode,
        },
    )
    session.commit()
    return _control_record(row)


def list_google_drive_status(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleDriveStatusResponse:
    config = _google_drive_runtime_config(session, context=context)
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
    provider = _drive_provider(session, context=context)
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
    provider = _drive_provider(session, context=context)
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
        files = _drive_provider(session, context=context).list_files(
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


def sync_google_drive_candidates(
    session: Session,
    *,
    context: SessionContext,
    payload: DriveCandidateSyncRequest,
) -> DriveCandidateSyncResponse:
    connection = _connected_google_drive_connection(session, context=context)
    control = _ensure_drive_control(session, context=context)
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        files = _drive_provider(session, context=context).list_files(
            token_payload=token_payload,
            limit=payload.limit,
        )
    except Exception as exc:
        connection.status = DriveConnectionStatus.ERROR
        session.add(connection)
        record_from_context(
            session,
            context,
            action="drive.google.candidate_sync_failed",
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
            detail="Google Drive candidate sync failed.",
        ) from exc
    created = 0
    duplicate = 0
    candidates: list[DriveFileCandidate] = []
    for file in files:
        existing = session.scalar(
            select(DriveFileCandidate).where(
                DriveFileCandidate.company_id == context.company.id,
                DriveFileCandidate.provider == DriveProvider.GOOGLE_DRIVE,
                DriveFileCandidate.provider_file_id == file.provider_file_id,
                DriveFileCandidate.provider_version == _provider_version(file),
            )
        )
        if existing is not None:
            duplicate += 1
            candidates.append(existing)
            continue
        matter = _match_drive_matter(session, context=context, file=file)
        candidate = DriveFileCandidate(
            company_id=context.company.id,
            drive_connection_id=connection.id,
            provider=DriveProvider.GOOGLE_DRIVE,
            provider_file_id=file.provider_file_id,
            provider_version=_provider_version(file),
            name=file.name[:500],
            mime_type=file.mime_type,
            size_bytes=file.size_bytes,
            owner_display=file.owner_display,
            modified_time=file.modified_time,
            folder_path=file.folder_path,
            web_url=file.web_url,
            suggested_matter_id=matter.id if matter else None,
            confidence=0.9 if matter else None,
            status=ReviewCandidateStatus.NEW,
            provenance_json={
                "provider": DriveProvider.GOOGLE_DRIVE,
                "provider_file_id": file.provider_file_id,
                "provider_version": _provider_version(file),
                "content_imported": False,
            },
        )
        blocked_reason = _candidate_allowed(control, candidate)
        if blocked_reason:
            candidate.last_error_redacted = blocked_reason
            candidate.status = ReviewCandidateStatus.FAILED
        session.add(candidate)
        session.flush()
        created += 1
        candidates.append(candidate)
    connection.last_list_at = datetime.now(UTC)
    session.add(connection)
    record_from_context(
        session,
        context,
        action="drive.google.candidates_synced",
        target_type="user_drive_connection",
        target_id=connection.id,
        metadata={
            "provider": DriveProvider.GOOGLE_DRIVE,
            "examined_count": len(files),
            "created_count": created,
            "duplicate_count": duplicate,
            "content_imported": False,
        },
    )
    session.commit()
    return DriveCandidateSyncResponse(
        provider="google_drive",
        examined_count=len(files),
        created_count=created,
        duplicate_count=duplicate,
        candidates=[_candidate_record(row) for row in candidates],
    )


def list_drive_candidates(
    session: Session,
    *,
    context: SessionContext,
    provider: str | None = None,
    matter_id: str | None = None,
    status_filter: str | None = None,
    q: str | None = None,
    limit: int = 50,
) -> DriveCandidateListResponse:
    filters = [DriveFileCandidate.company_id == context.company.id]
    if provider:
        filters.append(DriveFileCandidate.provider == provider)
    if matter_id:
        filters.append(
            (DriveFileCandidate.linked_matter_id == matter_id)
            | (DriveFileCandidate.suggested_matter_id == matter_id)
        )
    if status_filter:
        filters.append(DriveFileCandidate.status == status_filter)
    if q:
        filters.append(DriveFileCandidate.name.ilike(f"%{q.strip()}%"))
    rows = list(
        session.scalars(
            select(DriveFileCandidate)
            .where(*filters)
            .order_by(DriveFileCandidate.updated_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )
    visible: list[DriveFileCandidate] = []
    for row in rows:
        target_matter_id = row.linked_matter_id or row.suggested_matter_id
        if target_matter_id is None:
            visible.append(row)
            continue
        matter = session.get(Matter, target_matter_id)
        if matter is None:
            continue
        try:
            assert_access(session, context=context, matter=matter)
        except HTTPException:
            continue
        visible.append(row)
    return DriveCandidateListResponse(
        candidates=[_candidate_record(row) for row in visible],
        pending_count=sum(1 for row in visible if row.status == ReviewCandidateStatus.NEW),
    )


def review_drive_candidate(
    session: Session,
    *,
    context: SessionContext,
    candidate_id: str,
    payload: DriveCandidateReviewRequest,
) -> DriveCandidateReviewResponse:
    candidate = session.scalar(
        select(DriveFileCandidate).where(
            DriveFileCandidate.id == candidate_id,
            DriveFileCandidate.company_id == context.company.id,
        )
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Drive candidate not found.")
    control = _ensure_drive_control(session, context=context, provider=candidate.provider)
    if payload.action == "ignore":
        candidate.status = ReviewCandidateStatus.IGNORED
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="drive.candidate.ignored",
            target_type="drive_file_candidate",
            target_id=candidate.id,
            metadata={"provider": candidate.provider},
        )
        session.commit()
        return DriveCandidateReviewResponse(candidate=_candidate_record(candidate))
    if payload.action == "retry":
        candidate.status = ReviewCandidateStatus.NEW
        candidate.last_error_redacted = None
        session.add(candidate)
        session.commit()
        return DriveCandidateReviewResponse(candidate=_candidate_record(candidate))
    matter_id = payload.matter_id or candidate.linked_matter_id or candidate.suggested_matter_id
    if not matter_id:
        raise HTTPException(status_code=400, detail="matter_id is required.")
    matter = session.get(Matter, matter_id)
    if matter is None or matter.company_id != context.company.id:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    matter = require_operational_matter(
        session,
        matter=matter,
        operation="link or import a Drive candidate",
    )
    if payload.action == "link_metadata":
        candidate.linked_matter_id = matter.id
        candidate.status = ReviewCandidateStatus.LINKED_METADATA
        candidate.provenance_json = {
            **(candidate.provenance_json or {}),
            "linked_matter_id": matter.id,
            "content_imported": False,
        }
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="drive.candidate.linked_metadata",
            target_type="drive_file_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            metadata={"provider": candidate.provider, "content_imported": False},
        )
        session.commit()
        return DriveCandidateReviewResponse(candidate=_candidate_record(candidate))
    if payload.action != "import_file":
        raise HTTPException(status_code=400, detail="Unsupported Drive candidate action.")
    blocked_reason = _candidate_allowed(control, candidate)
    if blocked_reason:
        candidate.status = ReviewCandidateStatus.FAILED
        candidate.last_error_redacted = blocked_reason
        session.add(candidate)
        session.commit()
        raise HTTPException(status_code=409, detail=blocked_reason)
    if candidate.provider != DriveProvider.GOOGLE_DRIVE:
        candidate.status = ReviewCandidateStatus.FAILED
        candidate.last_error_redacted = "Content import is blocked until provider config exists."
        session.add(candidate)
        session.commit()
        raise HTTPException(
            status_code=409,
            detail="Drive content import is blocked until provider connection is configured.",
        )
    connection = session.get(UserDriveConnection, candidate.drive_connection_id)
    if connection is None or connection.company_id != context.company.id:
        raise HTTPException(status_code=409, detail="Drive connection is unavailable.")
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        content = _drive_provider(session, context=context).fetch_file(
            token_payload=token_payload,
            file_id=candidate.provider_file_id,
        )
        from caseops_api.services.communications import _persist_inbound_attachment

        attachment, _job_id, _storage_key = _persist_inbound_attachment(
            session,
            context=context,
            matter=matter,
            filename=candidate.name,
            content_type=candidate.mime_type,
            stream=BytesIO(content),
        )
    except Exception as exc:
        candidate.status = ReviewCandidateStatus.FAILED
        candidate.last_error_redacted = redact_provider_error(str(exc))[:500]
        session.add(candidate)
        record_from_context(
            session,
            context,
            action="drive.candidate.import_failed",
            target_type="drive_file_candidate",
            target_id=candidate.id,
            matter_id=matter.id,
            result="failed",
            metadata={"provider": candidate.provider, "error": candidate.last_error_redacted},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Drive file import failed.",
        ) from exc
    candidate.linked_matter_id = matter.id
    candidate.status = ReviewCandidateStatus.CONTENT_IMPORTED
    candidate.imported_attachment_id = attachment.id
    candidate.last_error_redacted = None
    candidate.provenance_json = {
        **(candidate.provenance_json or {}),
        "linked_matter_id": matter.id,
        "imported_attachment_id": attachment.id,
        "content_imported": True,
    }
    session.add(candidate)
    record_from_context(
        session,
        context,
        action="drive.candidate.imported",
        target_type="drive_file_candidate",
        target_id=candidate.id,
        matter_id=matter.id,
        metadata={
            "provider": candidate.provider,
            "attachment_id": attachment.id,
            "provider_file_id_hash": hashlib.sha256(
                candidate.provider_file_id.encode("utf-8")
            ).hexdigest(),
        },
    )
    session.commit()
    return DriveCandidateReviewResponse(
        candidate=_candidate_record(candidate),
        imported_attachment_id=attachment.id,
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
    owners = payload.get("owners")
    owner_display = None
    if isinstance(owners, list) and owners:
        first_owner = owners[0]
        if isinstance(first_owner, dict):
            owner_display = (
                str(first_owner.get("displayName") or first_owner.get("emailAddress") or "") or None
            )
    return GoogleDriveFileMetadata(
        provider_file_id=str(payload.get("id") or ""),
        name=str(payload.get("name") or "Untitled"),
        mime_type=str(payload.get("mimeType") or "") or None,
        size_bytes=size_bytes,
        modified_time=modified_time,
        web_url=str(payload.get("webViewLink") or "") or None,
        owner_display=owner_display,
        folder_path=str(payload.get("folderPath") or "") or None,
    )


__all__ = [
    "GOOGLE_DRIVE_SCOPES",
    "GoogleDriveFileMetadata",
    "complete_google_drive_connection",
    "get_drive_sync_control",
    "list_drive_candidates",
    "list_google_drive_files",
    "list_google_drive_status",
    "review_drive_candidate",
    "revoke_google_drive_connection",
    "set_google_drive_provider_for_tests",
    "start_google_drive_connection",
    "sync_google_drive_candidates",
    "update_drive_sync_control",
]
