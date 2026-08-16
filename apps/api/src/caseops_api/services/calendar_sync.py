from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote, urlencode

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    CalendarSyncSourceType,
    Company,
    CompanyMembership,
    IpDocketRecord,
    Matter,
    MatterDeadline,
    MatterHearing,
    MatterHearingStatus,
    MatterTask,
    MatterTaskStatus,
    TenantOutlookConfiguration,
    UserCalendarConnection,
)
from caseops_api.schemas.calendar import (
    CalendarConnectionListResponse,
    CalendarConnectionRecord,
    CalendarConnectionStartResponse,
    CalendarEventSyncRecord,
    CalendarEventSyncResponse,
    CalendarProviderConfigStatus,
    CalendarSyncCapabilityStatus,
    CalendarSyncConflictCandidate,
    CalendarSyncConflictSummary,
    CalendarSyncStatusResponse,
    OutlookApprovalItemStatus,
    OutlookBulkSyncItem,
    OutlookBulkSyncRequest,
    OutlookBulkSyncResponse,
    OutlookConfigurationItemStatus,
    OutlookReadinessCheckResult,
    OutlookReadinessTestResponse,
    OutlookTenantConfigurationResponse,
    OutlookTenantConfigurationUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.google_workspace import google_workspace_oauth_config
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.matter_access import (
    assert_access,
    can_access_ip_docket,
    visible_matters_filter,
)
from caseops_api.services.matter_operational_guard import matter_is_operational
from caseops_api.services.notification_delivery import (
    redact_provider_error,
    retry_delay_for_attempt,
)
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import resolve_shared_work_target

OUTLOOK_SCOPES = ["offline_access", "User.Read", "Calendars.ReadWrite"]
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_STATE_KINDS = {
    CalendarProvider.OUTLOOK: "outlook_calendar_oauth",
    CalendarProvider.GOOGLE_CALENDAR: "google_calendar_oauth",
}
_STATE_TTL_MINUTES = 10


class CalendarProviderError(RuntimeError):
    """Provider failures safe to persist/display as sync errors."""


@dataclass(frozen=True)
class OutlookRuntimeConfig:
    client_id: str | None
    client_secret: str | None
    tenant_id: str
    redirect_uri: str | None
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True)
class GoogleCalendarRuntimeConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    source: str

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


@dataclass(frozen=True, slots=True)
class DurableOutlookSyncProcessResult:
    status: str
    adp20_readiness: str
    missing_config_names: tuple[str, ...]
    missing_approval_keys: tuple[str, ...]
    examined: int
    synced: int
    failed: int
    retry_scheduled: int
    dead_lettered: int
    skipped: int
    replayed: int
    provider_calls: int


@dataclass(frozen=True, slots=True)
class CalendarDeletionProcessResult:
    examined: int
    deleted: int
    retry_scheduled: int
    dead_lettered: int
    provider_calls: int


@dataclass(frozen=True, slots=True)
class CalendarSourcePayload:
    source_type: str
    source_id: str
    matter: Matter | None
    ip_docket: IpDocketRecord | None
    title: str
    occurs_on: date
    detail_lines: tuple[str, ...]
    category: str
    private_properties: dict[str, str]


class OutlookProvider(Protocol):
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

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, Any],
        hearing: MatterHearing,
        matter: Matter,
        existing_provider_event_id: str | None,
    ) -> str:
        raise NotImplementedError

    def upsert_calendar_item(
        self,
        *,
        token_payload: dict[str, Any],
        item: CalendarSourcePayload,
        existing_provider_event_id: str | None,
    ) -> str:
        raise NotImplementedError

    def validate_connection(self, *, token_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def delete_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> None:
        raise NotImplementedError

    def fetch_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> dict[str, Any] | None:
        """Read back a projected event so drift can be detected (UJ-62-EXC-03).

        Returns ``None`` when the event no longer exists, otherwise a dict with
        at least ``start_date`` (an ISO date string or ``None``) and
        ``cancelled``. Raising ``CalendarProviderError`` is the correct answer
        when the provider cannot be read: an unreadable provider is recorded as
        `unknown`, never as a match.
        """

        raise NotImplementedError


class MicrosoftGraphOutlookProvider:
    """Small Microsoft Graph adapter.

    Tests replace this provider through ``set_outlook_provider_for_tests`` so
    the API never needs live Graph credentials in CI.
    """

    def __init__(self, config: OutlookRuntimeConfig | None = None) -> None:
        self._config = config

    def _runtime_config(self) -> OutlookRuntimeConfig:
        if self._config is not None:
            return self._config
        settings = get_settings()
        return OutlookRuntimeConfig(
            client_id=settings.outlook_client_id,
            client_secret=settings.outlook_client_secret,
            tenant_id=settings.outlook_tenant_id.strip("/") or "organizations",
            redirect_uri=settings.outlook_redirect_uri,
            source="environment",
        )

    @property
    def configured(self) -> bool:
        return self._runtime_config().configured

    @property
    def unavailable_reason(self) -> str | None:
        if self.configured:
            return None
        return "Microsoft Graph OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:
        config = self._runtime_config()
        if not self.configured:
            raise CalendarProviderError(self.unavailable_reason or "Outlook unavailable.")
        tenant = config.tenant_id.strip("/") or "organizations"
        qs = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "response_mode": "query",
                "scope": " ".join(OUTLOOK_SCOPES),
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{qs}"

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        config = self._runtime_config()
        if not self.configured:
            raise CalendarProviderError(self.unavailable_reason or "Outlook unavailable.")
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc

        tenant = config.tenant_id.strip("/") or "organizations"
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        try:
            token_response = httpx.post(
                token_url,
                data={
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                    "scope": " ".join(OUTLOOK_SCOPES),
                },
                timeout=15,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise CalendarProviderError("Microsoft Graph did not return an access token.")
            me_response = request_with_retries(
                "GET",
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            me = me_response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Microsoft Graph OAuth exchange failed.") from exc

        scopes = str(token_payload.get("scope") or " ".join(OUTLOOK_SCOPES)).split()
        return {
            "token_payload": token_payload,
            "provider_account_id": str(me.get("id") or ""),
            "display_email": str(
                me.get("mail") or me.get("userPrincipalName") or ""
            ) or None,
            "scopes": scopes,
        }

    def validate_connection(self, *, token_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Outlook token is unavailable.")
        try:
            me_response = request_with_retries(
                "GET",
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            me = me_response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Microsoft Graph connection test failed.") from exc
        return {
            "provider_account_id": str(me.get("id") or ""),
            "display_email": str(
                me.get("mail") or me.get("userPrincipalName") or ""
            ) or None,
        }

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, Any],
        hearing: MatterHearing,
        matter: Matter,
        existing_provider_event_id: str | None,
    ) -> str:
        return self.upsert_calendar_item(
            token_payload=token_payload,
            item=_hearing_source_payload(hearing, matter),
            existing_provider_event_id=existing_provider_event_id,
        )

    def upsert_calendar_item(
        self,
        *,
        token_payload: dict[str, Any],
        item: CalendarSourcePayload,
        existing_provider_event_id: str | None,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Outlook token is unavailable.")

        start = f"{item.occurs_on.isoformat()}T00:00:00"
        end = f"{(item.occurs_on + timedelta(days=1)).isoformat()}T00:00:00"
        payload = {
            "subject": item.title[:255],
            "isAllDay": True,
            "start": {"dateTime": start, "timeZone": "India Standard Time"},
            "end": {"dateTime": end, "timeZone": "India Standard Time"},
            "body": {
                "contentType": "text",
                "content": "\n".join(item.detail_lines),
            },
            "categories": ["CaseOps", item.category],
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if existing_provider_event_id:
                response = httpx.patch(
                    f"https://graph.microsoft.com/v1.0/me/events/{existing_provider_event_id}",
                    headers=headers,
                    json=payload,
                    timeout=15,
                )
                response.raise_for_status()
                return existing_provider_event_id
            response = httpx.post(
                "https://graph.microsoft.com/v1.0/me/events",
                headers=headers,
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            event = response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Microsoft Graph calendar sync failed.") from exc
        event_id = str(event.get("id") or "")
        if not event_id:
            raise CalendarProviderError("Microsoft Graph did not return an event id.")
        return event_id

    def delete_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Outlook token is unavailable.")
        try:
            response = httpx.delete(
                "https://graph.microsoft.com/v1.0/me/events/"
                f"{quote(provider_event_id, safe='')}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Microsoft Graph calendar delete failed.") from exc

    def fetch_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> dict[str, Any] | None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Outlook token is unavailable.")
        try:
            response = httpx.get(
                "https://graph.microsoft.com/v1.0/me/events/"
                f"{quote(provider_event_id, safe='')}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    # Graph returns event start/end values in UTC unless the
                    # caller asks for a timezone. CaseOps creates these
                    # all-day projections at midnight India Standard Time, so
                    # reading the UTC representation and truncating its date
                    # would falsely move every event to the preceding day.
                    "Prefer": 'outlook.timezone="India Standard Time"',
                },
                params={"$select": "id,isAllDay,isCancelled,start"},
                timeout=15,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Microsoft Graph calendar read failed.") from exc
        start = body.get("start") or {}
        raw = str(start.get("dateTime") or "")
        return {
            "id": body.get("id"),
            # All-day events carry a date; take only the date half so no
            # timezone arithmetic can move the obligation across a day.
            "start_date": raw[:10] or None,
            "cancelled": bool(body.get("isCancelled")),
        }


class GoogleCalendarProvider:
    """Google Calendar adapter for CaseOps-to-Google hearing sync.

    Tests replace this provider through ``set_google_calendar_provider_for_tests``.
    The app never calls Google when the required OAuth settings are missing.
    """

    def __init__(self, config: GoogleCalendarRuntimeConfig | None = None) -> None:
        self._config = config

    def _runtime_config(self) -> GoogleCalendarRuntimeConfig:
        if self._config is not None:
            return self._config
        settings = get_settings()
        return GoogleCalendarRuntimeConfig(
            client_id=settings.google_calendar_client_id,
            client_secret=settings.google_calendar_client_secret,
            redirect_uri=settings.google_calendar_redirect_uri,
            source="environment",
        )

    @property
    def configured(self) -> bool:
        return self._runtime_config().configured

    @property
    def unavailable_reason(self) -> str | None:
        if self.configured:
            return None
        return "Google Calendar OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:
        config = self._runtime_config()
        if not self.configured:
            raise CalendarProviderError(
                self.unavailable_reason or "Google Calendar unavailable."
            )
        qs = urlencode(
            {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": config.redirect_uri,
                "scope": " ".join(GOOGLE_CALENDAR_SCOPES),
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
            raise CalendarProviderError(
                self.unavailable_reason or "Google Calendar unavailable."
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Google Calendar HTTP client is unavailable.") from exc

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
                raise CalendarProviderError("Google did not return an access token.")
            userinfo_response = request_with_retries(
                "GET",
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            userinfo = userinfo_response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Google Calendar OAuth exchange failed.") from exc

        scope_text = str(token_payload.get("scope") or " ".join(GOOGLE_CALENDAR_SCOPES))
        return {
            "token_payload": token_payload,
            "provider_account_id": str(userinfo.get("sub") or ""),
            "display_email": str(userinfo.get("email") or "") or None,
            "scopes": scope_text.split(),
        }

    def validate_connection(self, *, token_payload: dict[str, Any]) -> dict[str, Any]:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Google Calendar HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Google Calendar token is unavailable.")
        try:
            userinfo_response = request_with_retries(
                "GET",
                "https://www.googleapis.com/oauth2/v3/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            userinfo = userinfo_response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Google Calendar connection test failed.") from exc
        return {
            "provider_account_id": str(userinfo.get("sub") or ""),
            "display_email": str(userinfo.get("email") or "") or None,
        }

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, Any],
        hearing: MatterHearing,
        matter: Matter,
        existing_provider_event_id: str | None,
    ) -> str:
        return self.upsert_calendar_item(
            token_payload=token_payload,
            item=_hearing_source_payload(hearing, matter),
            existing_provider_event_id=existing_provider_event_id,
        )

    def upsert_calendar_item(
        self,
        *,
        token_payload: dict[str, Any],
        item: CalendarSourcePayload,
        existing_provider_event_id: str | None,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Google Calendar HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Google Calendar token is unavailable.")

        payload = {
            "summary": item.title[:255],
            "description": "\n".join(item.detail_lines),
            "start": {"date": item.occurs_on.isoformat()},
            "end": {"date": (item.occurs_on + timedelta(days=1)).isoformat()},
            "extendedProperties": {
                "private": item.private_properties,
            },
        }
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            if existing_provider_event_id:
                response = httpx.patch(
                    "https://www.googleapis.com/calendar/v3/calendars/primary/"
                    f"events/{quote(existing_provider_event_id, safe='')}",
                    headers=headers,
                    json=payload,
                    timeout=15,
                )
                response.raise_for_status()
                return existing_provider_event_id
            response = httpx.post(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers=headers,
                json=payload,
                timeout=15,
            )
            response.raise_for_status()
            event = response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Google Calendar sync failed.") from exc
        event_id = str(event.get("id") or "")
        if not event_id:
            raise CalendarProviderError("Google Calendar did not return an event id.")
        return event_id

    def delete_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Google Calendar HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Google Calendar token is unavailable.")
        try:
            response = httpx.delete(
                "https://www.googleapis.com/calendar/v3/calendars/primary/"
                f"events/{quote(provider_event_id, safe='')}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if response.status_code == 404:
                return
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Google Calendar delete failed.") from exc

    def fetch_event(
        self,
        *,
        token_payload: dict[str, Any],
        provider_event_id: str,
    ) -> dict[str, Any] | None:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Google Calendar HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Google Calendar token is unavailable.")
        try:
            response = httpx.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/"
                f"events/{quote(provider_event_id, safe='')}",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPError as exc:
            raise CalendarProviderError("Google Calendar read failed.") from exc
        start = body.get("start") or {}
        # An all-day event carries `date`; a moved-to-timed event carries
        # `dateTime`, and only its date half is compared.
        raw = str(start.get("date") or start.get("dateTime") or "")
        return {
            "id": body.get("id"),
            "start_date": raw[:10] or None,
            "cancelled": str(body.get("status") or "") == "cancelled",
        }


_outlook_provider_override: OutlookProvider | None = None
_google_calendar_provider_override: OutlookProvider | None = None


def set_outlook_provider_for_tests(provider: OutlookProvider | None) -> None:
    global _outlook_provider_override
    _outlook_provider_override = provider


def set_google_calendar_provider_for_tests(provider: OutlookProvider | None) -> None:
    global _google_calendar_provider_override
    _google_calendar_provider_override = provider


def _outlook_provider(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> OutlookProvider:
    return _outlook_provider_override or MicrosoftGraphOutlookProvider(
        _outlook_runtime_config(session, context=context)
    )


def _google_calendar_provider(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> OutlookProvider:
    return _google_calendar_provider_override or GoogleCalendarProvider(
        _google_calendar_runtime_config(session, context=context)
    )


def _provider(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> OutlookProvider:
    return _outlook_provider(session, context=context)


def _provider_for(
    provider: CalendarProvider,
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> OutlookProvider:
    if provider == CalendarProvider.OUTLOOK:
        return _outlook_provider(session, context=context)
    if provider == CalendarProvider.GOOGLE_CALENDAR:
        return _google_calendar_provider(session, context=context)
    raise CalendarProviderError(f"Unsupported calendar provider: {provider}.")


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_token_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "fernet:" + _fernet().encrypt(raw).decode("ascii")


def _encrypt_secret(value: str) -> str:
    raw = value.encode("utf-8")
    return "fernet:" + _fernet().encrypt(raw).decode("ascii")


def _decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("fernet:"):
        raise CalendarProviderError("Stored calendar credential is unavailable.")
    try:
        raw = _fernet().decrypt(value.removeprefix("fernet:").encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise CalendarProviderError("Stored calendar credential cannot be decrypted.") from exc
    return raw.decode("utf-8")


def _decrypt_token_payload(value: str | None) -> dict[str, Any]:
    if not value or not value.startswith("fernet:"):
        raise CalendarProviderError("Stored calendar token is unavailable.")
    try:
        raw = _fernet().decrypt(value.removeprefix("fernet:").encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise CalendarProviderError("Stored calendar token cannot be decrypted.") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalendarProviderError("Stored calendar token payload is malformed.") from exc
    if not isinstance(decoded, dict):
        raise CalendarProviderError("Stored calendar token payload is malformed.")
    return decoded


def _environment_runtime_config() -> OutlookRuntimeConfig:
    settings = get_settings()
    return OutlookRuntimeConfig(
        client_id=settings.outlook_client_id,
        client_secret=settings.outlook_client_secret,
        tenant_id=settings.outlook_tenant_id.strip("/") or "organizations",
        redirect_uri=settings.outlook_redirect_uri,
        source="environment",
    )


def _google_calendar_runtime_config(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> GoogleCalendarRuntimeConfig:
    workspace_config = google_workspace_oauth_config(
        session,
        context=context,
        connector="calendar",
    )
    if workspace_config.source in {"tenant_admin", "missing"}:
        return GoogleCalendarRuntimeConfig(
            client_id=workspace_config.client_id,
            client_secret=workspace_config.client_secret,
            redirect_uri=workspace_config.redirect_uri,
            source=workspace_config.source,
        )
    settings = get_settings()
    return GoogleCalendarRuntimeConfig(
        client_id=settings.google_calendar_client_id,
        client_secret=settings.google_calendar_client_secret,
        redirect_uri=settings.google_calendar_redirect_uri,
        source="environment",
    )


def _tenant_outlook_configuration(
    session: Session,
    *,
    company_id: str,
) -> TenantOutlookConfiguration | None:
    return session.scalar(
        select(TenantOutlookConfiguration).where(
            TenantOutlookConfiguration.company_id == company_id,
            TenantOutlookConfiguration.provider == CalendarProvider.OUTLOOK,
        )
    )


def _outlook_runtime_config(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> OutlookRuntimeConfig:
    if session is not None and context is not None:
        row = _tenant_outlook_configuration(session, company_id=context.company.id)
        if row is not None and row.enabled:
            return OutlookRuntimeConfig(
                client_id=row.client_id,
                client_secret=_decrypt_secret(row.encrypted_client_secret_ref),
                tenant_id=(row.tenant_id or "organizations").strip("/")
                or "organizations",
                redirect_uri=row.redirect_uri,
                source="tenant_admin",
            )
    return _environment_runtime_config()


def _sign_state(context: SessionContext, *, provider: CalendarProvider) -> str:
    now = datetime.now(UTC)
    payload = {
        "kind": _STATE_KINDS[provider],
        "provider": provider,
        "company_id": context.company.id,
        "membership_id": context.membership.id,
        "iat": now,
        "exp": now + timedelta(minutes=_STATE_TTL_MINUTES),
    }
    return jwt.encode(payload, get_settings().auth_secret, algorithm="HS256")


def _verify_state(
    context: SessionContext,
    state: str,
    *,
    provider: CalendarProvider,
) -> None:
    try:
        payload = jwt.decode(state, get_settings().auth_secret, algorithms=["HS256"])
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid calendar connection state.",
        ) from exc
    if (
        payload.get("kind") != _STATE_KINDS[provider]
        or str(payload.get("provider")) != str(provider)
        or str(payload.get("company_id")) != context.company.id
        or str(payload.get("membership_id")) != context.membership.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Calendar connection state does not match the current session.",
        )


def _connection_record(connection: UserCalendarConnection) -> CalendarConnectionRecord:
    return CalendarConnectionRecord(
        id=connection.id,
        company_id=connection.company_id,
        membership_id=connection.membership_id,
        provider=connection.provider,  # type: ignore[arg-type]
        provider_account_id=connection.provider_account_id,
        display_email=connection.display_email,
        status=connection.status,  # type: ignore[arg-type]
        scopes=list(connection.scopes_json or []),
        connected_at=connection.connected_at,
        last_sync_at=connection.last_sync_at,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _sync_record(sync: CalendarEventSync) -> CalendarEventSyncRecord:
    return CalendarEventSyncRecord(
        id=sync.id,
        company_id=sync.company_id,
        calendar_connection_id=sync.calendar_connection_id,
        source_type=sync.source_type,  # type: ignore[arg-type]
        source_id=sync.source_id,
        provider_event_id=sync.provider_event_id,
        sync_status=sync.sync_status,  # type: ignore[arg-type]
        last_error=sync.last_error,
        last_synced_at=sync.last_synced_at,
        attempts=sync.attempts,
        max_attempts=sync.max_attempts,
        next_attempt_at=sync.next_attempt_at,
        dead_letter_reason=sync.dead_letter_reason,
        created_at=sync.created_at,
        updated_at=sync.updated_at,
    )


def _hearing_source_payload(
    hearing: MatterHearing,
    matter: Matter,
) -> CalendarSourcePayload:
    detail_lines = [
        f"Matter: {matter.title}",
        f"Matter code: {matter.matter_code}",
        f"Forum: {hearing.forum_name}",
        f"Status: {hearing.status}",
    ]
    if hearing.judge_name:
        detail_lines.append(f"Judge: {hearing.judge_name}")
    if hearing.outcome_note:
        detail_lines.append(f"Outcome: {hearing.outcome_note}")
    return CalendarSourcePayload(
        source_type=CalendarSyncSourceType.MATTER_HEARING.value,
        source_id=hearing.id,
        matter=matter,
        ip_docket=None,
        title=f"{matter.matter_code}: {hearing.purpose or 'Hearing'}",
        occurs_on=hearing.hearing_on,
        detail_lines=tuple(detail_lines),
        category="Hearing",
        private_properties={
            "caseops_matter_id": matter.id,
            "caseops_source_type": CalendarSyncSourceType.MATTER_HEARING.value,
            "caseops_source_id": hearing.id,
            "caseops_hearing_id": hearing.id,
        },
    )


def _task_source_payload(task: MatterTask, matter: Matter) -> CalendarSourcePayload:
    detail_lines = [
        f"Matter: {matter.title}",
        f"Matter code: {matter.matter_code}",
        f"Status: {task.status}",
        f"Priority: {task.priority}",
    ]
    if task.description:
        detail_lines.append(f"Description: {task.description[:500]}")
    assert task.due_on is not None
    return CalendarSourcePayload(
        source_type=CalendarSyncSourceType.MATTER_TASK.value,
        source_id=task.id,
        matter=matter,
        ip_docket=None,
        title=f"{matter.matter_code}: {task.title}",
        occurs_on=task.due_on,
        detail_lines=tuple(detail_lines),
        category="Task",
        private_properties={
            "caseops_matter_id": matter.id,
            "caseops_source_type": CalendarSyncSourceType.MATTER_TASK.value,
            "caseops_source_id": task.id,
            "caseops_task_id": task.id,
        },
    )


def _deadline_source_payload(
    deadline: MatterDeadline,
    matter: Matter,
) -> CalendarSourcePayload:
    detail_lines = [
        f"Matter: {matter.title}",
        f"Matter code: {matter.matter_code}",
        f"Status: {deadline.status}",
        f"Source: {deadline.source}",
        f"Kind: {deadline.kind}",
    ]
    if deadline.notes:
        detail_lines.append(f"Notes: {deadline.notes[:500]}")
    return CalendarSourcePayload(
        source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
        source_id=deadline.id,
        matter=matter,
        ip_docket=None,
        title=f"{matter.matter_code}: {deadline.title}",
        occurs_on=deadline.due_on,
        detail_lines=tuple(detail_lines),
        category="Deadline",
        private_properties={
            "caseops_matter_id": matter.id,
            "caseops_source_type": CalendarSyncSourceType.MATTER_DEADLINE.value,
            "caseops_source_id": deadline.id,
            "caseops_deadline_id": deadline.id,
        },
    )


def _ip_source_payload(
    *,
    source_type: str,
    source_id: str,
    occurs_on: date,
    category: str,
    docket: IpDocketRecord,
) -> CalendarSourcePayload:
    """Build the deliberately minimal outbound IP projection.

    Provider calendars receive stable correlation and a CaseOps link, never
    the docket title, identifier, forum, notes, or other privileged content.
    """

    source_url = f"https://caseops.ai/app/ip?docket={docket.id}"
    return CalendarSourcePayload(
        source_type=source_type,
        source_id=source_id,
        matter=None,
        ip_docket=docket,
        title=f"CaseOps IP - {category}",
        occurs_on=occurs_on,
        detail_lines=(
            "Open CaseOps to view authorized details.",
            f"CaseOps source: {source_url}",
            f"Source version: {docket.current_version}",
        ),
        category=category,
        private_properties={
            "caseops_ip_docket_id": docket.id,
            "caseops_source_type": source_type,
            "caseops_source_id": source_id,
            "caseops_source_version": str(docket.current_version),
            "caseops_source_url": source_url,
        },
    )


def _ip_source_payload_for(
    session: Session,
    *,
    context: SessionContext,
    source_type: str,
    source_id: str,
) -> CalendarSourcePayload | None:
    model: type[MatterHearing] | type[MatterTask] | type[MatterDeadline]
    category: str
    occurs_on_attribute: str
    if source_type == CalendarSyncSourceType.MATTER_HEARING.value:
        model, category, occurs_on_attribute = MatterHearing, "Hearing", "hearing_on"
    elif source_type == CalendarSyncSourceType.MATTER_TASK.value:
        model, category, occurs_on_attribute = MatterTask, "Task", "due_on"
    elif source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        model, category, occurs_on_attribute = MatterDeadline, "Deadline", "due_on"
    else:
        return None

    row = session.scalar(
        select(model).where(
            model.id == source_id,
            model.company_id == context.company.id,
            model.ip_docket_id.is_not(None),
        )
    )
    if row is None:
        return None
    assert row.ip_docket_id is not None
    target = resolve_shared_work_target(
        session,
        context=context,
        ip_docket_id=row.ip_docket_id,
    )
    assert target.ip_docket is not None
    if isinstance(row, MatterHearing) and row.status == MatterHearingStatus.CANCELLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cancelled hearings are removed from provider calendars.",
        )
    occurs_on = getattr(row, occurs_on_attribute)
    if occurs_on is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{category} has no date and cannot be synced to calendar.",
        )
    return _ip_source_payload(
        source_type=source_type,
        source_id=source_id,
        occurs_on=occurs_on,
        category=category,
        docket=target.ip_docket,
    )


def _source_payload_for(
    session: Session,
    *,
    context: SessionContext,
    source_type: str,
    source_id: str,
) -> CalendarSourcePayload:
    ip_payload = _ip_source_payload_for(
        session,
        context=context,
        source_type=source_type,
        source_id=source_id,
    )
    if ip_payload is not None:
        return ip_payload
    if source_type == CalendarSyncSourceType.MATTER_HEARING.value:
        row = session.execute(
            select(MatterHearing, Matter)
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(
                MatterHearing.id == source_id,
                Matter.company_id == context.company.id,
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Hearing not found.",
            )
        hearing, matter = row
        assert_access(session, context=context, matter=matter)
        _assert_calendar_matter_operational(matter)
        if hearing.status == MatterHearingStatus.CANCELLED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cancelled hearings are removed from provider calendars.",
            )
        return _hearing_source_payload(hearing, matter)

    if source_type == CalendarSyncSourceType.MATTER_TASK.value:
        row = session.execute(
            select(MatterTask, Matter)
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                MatterTask.id == source_id,
                Matter.company_id == context.company.id,
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Task not found.",
            )
        task, matter = row
        assert_access(session, context=context, matter=matter)
        _assert_calendar_matter_operational(matter)
        if task.due_on is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task has no due date and cannot be synced to calendar.",
            )
        return _task_source_payload(task, matter)

    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        row = session.execute(
            select(MatterDeadline, Matter)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                MatterDeadline.id == source_id,
                Matter.company_id == context.company.id,
            )
        ).first()
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deadline not found.",
            )
        deadline, matter = row
        assert_access(session, context=context, matter=matter)
        _assert_calendar_matter_operational(matter)
        return _deadline_source_payload(deadline, matter)

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported calendar source type.",
    )


def _assert_calendar_matter_operational(matter: Matter) -> None:
    if str(matter.status) not in {"closed", "disposed"} and matter.is_active:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Disposed matters cannot create or update calendar events.",
    )


def _missing_outlook_config_names(
    provider: OutlookProvider,
    runtime_config: OutlookRuntimeConfig | None = None,
) -> list[str]:
    """Return config names only; never expose configured values."""
    if provider.configured:
        return []
    config = runtime_config or _environment_runtime_config()
    missing: list[str] = []
    if not config.client_id:
        missing.append("OUTLOOK_CLIENT_ID")
    if not config.client_secret:
        missing.append("OUTLOOK_CLIENT_SECRET")
    if not config.redirect_uri:
        missing.append("OUTLOOK_REDIRECT_URI")
    return missing


def _provider_config_status(
    provider: OutlookProvider,
    runtime_config: OutlookRuntimeConfig | None = None,
) -> CalendarProviderConfigStatus:
    return CalendarProviderConfigStatus(
        configured=provider.configured,
        missing_config_names=_missing_outlook_config_names(provider, runtime_config),
    )


def _missing_google_calendar_config_names(
    provider: OutlookProvider,
    runtime_config: GoogleCalendarRuntimeConfig | None = None,
) -> list[str]:
    """Return Google Calendar config names only; never expose values."""
    if provider.configured:
        return []
    config = runtime_config or _google_calendar_runtime_config()
    missing: list[str] = []
    if not config.client_id:
        missing.append("GOOGLE_CALENDAR_CLIENT_ID")
    if not config.client_secret:
        missing.append("GOOGLE_CALENDAR_CLIENT_SECRET")
    if not config.redirect_uri:
        missing.append("GOOGLE_CALENDAR_REDIRECT_URI")
    return missing


def _google_calendar_provider_config_status(
    provider: OutlookProvider,
    runtime_config: GoogleCalendarRuntimeConfig | None = None,
) -> CalendarProviderConfigStatus:
    return CalendarProviderConfigStatus(
        provider="google_calendar",
        configured=provider.configured,
        missing_config_names=_missing_google_calendar_config_names(
            provider, runtime_config
        ),
    )


_APPROVAL_LABELS = {
    "oauth_consent_model_approved": "OAuth consent model approved",
    "scopes_approved": "Microsoft Graph scopes approved",
    "durable_runbook_approved": "Durable sync retry/dead-letter/replay runbook approved",
    "rollback_approved": "Rollback and disable procedure approved",
    "redaction_rules_approved": "Provider error redaction rules approved",
}


def _config_items(runtime_config: OutlookRuntimeConfig) -> list[OutlookConfigurationItemStatus]:
    return [
        OutlookConfigurationItemStatus(
            name="OUTLOOK_CLIENT_ID",
            configured=bool(runtime_config.client_id),
        ),
        OutlookConfigurationItemStatus(
            name="OUTLOOK_CLIENT_SECRET",
            configured=bool(runtime_config.client_secret),
        ),
        OutlookConfigurationItemStatus(
            name="OUTLOOK_REDIRECT_URI",
            configured=bool(runtime_config.redirect_uri),
        ),
        OutlookConfigurationItemStatus(
            name="OUTLOOK_TENANT_ID_OR_APPROVED_TENANT_MODE",
            configured=bool(runtime_config.tenant_id),
        ),
    ]


def _approval_items(
    row: TenantOutlookConfiguration | None,
) -> list[OutlookApprovalItemStatus]:
    return [
        OutlookApprovalItemStatus(
            key=key,
            label=label,
            approved=bool(getattr(row, key, False)) if row is not None else False,
        )
        for key, label in _APPROVAL_LABELS.items()
    ]


def _readiness_value(
    *,
    configured: bool,
    approvals_ready: bool,
    last_test_status: str | None,
) -> str:
    if configured and approvals_ready and last_test_status == "passed":
        return "ready_for_adp20_implementation"
    return "blocked_pending_admin_configuration"


def _durable_automation_value(
    session: Session,
    *,
    context: SessionContext,
) -> str:
    status_summary = outlook_tenant_configuration_status(session, context=context)
    if status_summary.adp20_readiness == "ready_for_adp20_implementation":
        return "caseops_to_outlook_hearings_ready"
    return "blocked_pending_provider_approval"


def _connection_counts(
    session: Session,
    *,
    context: SessionContext,
) -> tuple[int, int]:
    connections = list(
        session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            )
        )
    )
    connected = [
        row
        for row in connections
        if row.status == CalendarConnectionStatus.CONNECTED
    ]
    return len(connections), len(connected)


def outlook_tenant_configuration_status(
    session: Session,
    *,
    context: SessionContext,
) -> OutlookTenantConfigurationResponse:
    row = _tenant_outlook_configuration(session, company_id=context.company.id)
    runtime_config = _outlook_runtime_config(session, context=context)
    provider = _provider(session, context=context)
    config_items = _config_items(runtime_config)
    approvals = _approval_items(row)
    missing_config = [
        item.name for item in config_items if not item.configured
    ]
    missing_approvals = [
        item.key for item in approvals if not item.approved
    ]
    connection_count, connected_account_count = _connection_counts(
        session,
        context=context,
    )
    if row is not None and row.enabled:
        config_source = "tenant_admin"
    elif provider.configured:
        config_source = runtime_config.source
    else:
        config_source = "missing"
    last_status = row.last_test_status if row is not None else "not_run"
    approvals_ready = not missing_approvals
    return OutlookTenantConfigurationResponse(
        configured=provider.configured,
        config_source=config_source,  # type: ignore[arg-type]
        enabled=bool(row.enabled) if row is not None else provider.configured,
        required_config=config_items,
        required_approvals=approvals,
        approved_scopes=list(row.scopes_json or OUTLOOK_SCOPES)
        if row is not None
        else OUTLOOK_SCOPES,
        missing_config_names=missing_config,
        missing_approval_keys=missing_approvals,
        connection_count=connection_count,
        connected_account_count=connected_account_count,
        last_test_status=last_status,  # type: ignore[arg-type]
        last_tested_at=row.last_tested_at if row is not None else None,
        last_error_redacted=row.last_error_redacted if row is not None else None,
        adp20_readiness=_readiness_value(
            configured=provider.configured,
            approvals_ready=approvals_ready,
            last_test_status=last_status,
        ),  # type: ignore[arg-type]
    )


def _ensure_tenant_outlook_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> TenantOutlookConfiguration:
    row = _tenant_outlook_configuration(session, company_id=context.company.id)
    if row is None:
        row = TenantOutlookConfiguration(
            company_id=context.company.id,
            provider=CalendarProvider.OUTLOOK,
            created_by_membership_id=context.membership.id,
        )
        session.add(row)
        session.flush()
    return row


def update_outlook_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
    payload: OutlookTenantConfigurationUpdateRequest,
) -> OutlookTenantConfigurationResponse:
    row = _ensure_tenant_outlook_configuration(session, context=context)
    if payload.client_id is not None:
        row.client_id = payload.client_id
    if payload.client_secret is not None:
        row.encrypted_client_secret_ref = _encrypt_secret(payload.client_secret)
    if payload.tenant_id is not None:
        row.tenant_id = payload.tenant_id.strip("/") or "organizations"
    elif not row.tenant_id:
        row.tenant_id = "organizations"
    if payload.redirect_uri is not None:
        row.redirect_uri = payload.redirect_uri
    row.scopes_json = list(payload.scopes or OUTLOOK_SCOPES)
    row.oauth_consent_model_approved = payload.oauth_consent_model_approved
    row.scopes_approved = payload.scopes_approved
    row.durable_runbook_approved = payload.durable_runbook_approved
    row.rollback_approved = payload.rollback_approved
    row.redaction_rules_approved = payload.redaction_rules_approved
    row.enabled = payload.enabled
    row.updated_by_membership_id = context.membership.id
    row.last_test_status = "not_run"
    row.last_tested_at = None
    row.last_error_redacted = None
    session.add(row)
    record_from_context(
        session,
        context,
        action="outlook.configuration.updated",
        target_type="tenant_outlook_configuration",
        target_id=row.id,
        metadata={
            "provider": CalendarProvider.OUTLOOK,
            "configured_names": [
                item.name
                for item in _config_items(_outlook_runtime_config(session, context=context))
                if item.configured
            ],
            "approved_keys": [
                item.key for item in _approval_items(row) if item.approved
            ],
            "enabled": row.enabled,
        },
    )
    session.commit()
    return outlook_tenant_configuration_status(session, context=context)


def _current_admin_connection(
    session: Session,
    *,
    context: SessionContext,
) -> UserCalendarConnection | None:
    return session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
        )
    )


def test_outlook_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> OutlookReadinessTestResponse:
    row = _ensure_tenant_outlook_configuration(session, context=context)
    tested_at = datetime.now(UTC)
    status_summary = outlook_tenant_configuration_status(session, context=context)
    checks: list[OutlookReadinessCheckResult] = []
    for item in status_summary.required_config:
        checks.append(
            OutlookReadinessCheckResult(
                key=item.name,
                label=item.name,
                status="passed" if item.configured else "blocked",
            )
        )
    for approval in status_summary.required_approvals:
        checks.append(
            OutlookReadinessCheckResult(
                key=approval.key,
                label=approval.label,
                status="passed" if approval.approved else "blocked",
            )
        )

    if status_summary.missing_config_names or status_summary.missing_approval_keys:
        row.last_test_status = "blocked"
        row.last_tested_at = tested_at
        row.last_error_redacted = "Outlook provider readiness prerequisites are incomplete."
        session.add(row)
        session.commit()
        return OutlookReadinessTestResponse(
            status="blocked",
            checks=checks,
            adp20_readiness="blocked_pending_admin_configuration",
            tested_at=tested_at,
        )

    connection = _current_admin_connection(session, context=context)
    if connection is None:
        checks.append(
            OutlookReadinessCheckResult(
                key="OUTLOOK_USER_CONNECTION",
                label="Admin Outlook OAuth connection",
                status="blocked",
                detail="Connect an Outlook account before running the end-to-end test.",
            )
        )
        row.last_test_status = "blocked"
        row.last_tested_at = tested_at
        row.last_error_redacted = "Outlook OAuth connection is required."
        session.add(row)
        session.commit()
        return OutlookReadinessTestResponse(
            status="blocked",
            checks=checks,
            adp20_readiness="blocked_pending_admin_configuration",
            tested_at=tested_at,
        )

    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        _provider(session, context=context).validate_connection(
            token_payload=token_payload,
        )
    except Exception as exc:
        error = _safe_error(exc)
        checks.append(
            OutlookReadinessCheckResult(
                key="MICROSOFT_GRAPH_ME",
                label="Microsoft Graph /me probe",
                status="failed",
                detail=error,
            )
        )
        row.last_test_status = "failed"
        row.last_tested_at = tested_at
        row.last_error_redacted = error
        record_from_context(
            session,
            context,
            action="outlook.configuration.test_failed",
            target_type="tenant_outlook_configuration",
            target_id=row.id,
            result="failed",
            metadata={"provider": CalendarProvider.OUTLOOK, "error": error},
        )
        session.commit()
        return OutlookReadinessTestResponse(
            status="failed",
            checks=checks,
            adp20_readiness="blocked_pending_admin_configuration",
            tested_at=tested_at,
        )

    checks.append(
        OutlookReadinessCheckResult(
            key="MICROSOFT_GRAPH_ME",
            label="Microsoft Graph /me probe",
            status="passed",
        )
    )
    row.last_test_status = "passed"
    row.last_tested_at = tested_at
    row.last_error_redacted = None
    record_from_context(
        session,
        context,
        action="outlook.configuration.test_passed",
        target_type="tenant_outlook_configuration",
        target_id=row.id,
        metadata={
            "provider": CalendarProvider.OUTLOOK,
            "check_count": len(checks),
        },
    )
    session.commit()
    return OutlookReadinessTestResponse(
        status="passed",
        checks=checks,
        adp20_readiness="ready_for_adp20_implementation",
        tested_at=tested_at,
    )


_DURABLE_OUTLOOK_SYNC_WINDOW_DAYS = 92
_GOOGLE_CALENDAR_SYNC_SOURCE_TYPES = (
    CalendarSyncSourceType.MATTER_HEARING.value,
    CalendarSyncSourceType.MATTER_TASK.value,
    CalendarSyncSourceType.MATTER_DEADLINE.value,
)


def _current_time() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def process_calendar_deletion_tombstones(
    session: Session,
    *,
    context: SessionContext,
    calendar_provider: CalendarProvider | None = None,
    limit: int = 100,
) -> CalendarDeletionProcessResult:
    """Drain durable provider-event deletion work created by disposal.

    A matter lifecycle transaction only writes ``DELETE_PENDING`` rows.  The
    external provider call happens here, after that transaction has committed,
    so a slow or unavailable calendar API cannot hold the lifecycle row lock or
    roll back the disposal itself.
    """

    now = _current_time()
    stmt = (
        select(CalendarEventSync.id)
        .join(
            UserCalendarConnection,
            UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
        )
        .where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.sync_status == CalendarEventSyncStatus.DELETE_PENDING,
            or_(
                CalendarEventSync.next_attempt_at.is_(None),
                CalendarEventSync.next_attempt_at <= now,
            ),
        )
        .order_by(CalendarEventSync.created_at, CalendarEventSync.id)
        .limit(limit)
    )
    if calendar_provider is not None:
        stmt = stmt.where(UserCalendarConnection.provider == calendar_provider)
    sync_ids = list(session.scalars(stmt))
    counters = {
        "examined": 0,
        "deleted": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "provider_calls": 0,
    }

    for sync_id in sync_ids:
        sync = session.scalar(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.id == sync_id,
                CalendarEventSync.company_id == context.company.id,
            )
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        )
        if sync is None or sync.sync_status != CalendarEventSyncStatus.DELETE_PENDING:
            continue
        if (
            sync.next_attempt_at is not None
            and _aware(sync.next_attempt_at) > _current_time()
        ):
            continue
        counters["examined"] += 1
        connection = session.get(UserCalendarConnection, sync.calendar_connection_id)

        try:
            if connection is None:
                raise CalendarProviderError("Calendar connection no longer exists.")
            if not sync.provider_event_id:
                # There is no remote artifact to delete; complete the tombstone
                # without a provider call.
                sync.sync_status = CalendarEventSyncStatus.DELETED
            else:
                token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
                provider_kind = CalendarProvider(connection.provider)
                counters["provider_calls"] += 1
                _provider_for(
                    provider_kind,
                    session,
                    context=context,
                ).delete_event(
                    token_payload=token_payload,
                    provider_event_id=sync.provider_event_id,
                )
                sync.sync_status = CalendarEventSyncStatus.DELETED
            completed_at = _current_time()
            sync.last_error = None
            sync.last_synced_at = completed_at
            sync.next_attempt_at = None
            sync.dead_letter_reason = None
            sync.durable_last_attempt_at = completed_at
            if connection is not None:
                connection.last_sync_at = completed_at
                session.add(connection)
            counters["deleted"] += 1
            record_from_context(
                session,
                context,
                action="calendar.deletion_tombstone.completed",
                target_type="calendar_event_sync",
                target_id=sync.id,
                metadata={
                    "provider": connection.provider if connection is not None else None,
                    "source_type": sync.source_type,
                    "source_ref": redact_identifier(sync.source_id),
                    "provider_event_ref": redact_identifier(sync.provider_event_id),
                },
            )
        except Exception as exc:
            failed_at = _current_time()
            sync.attempts = min(sync.attempts + 1, sync.max_attempts)
            sync.last_error = redact_provider_error(exc)
            sync.durable_last_attempt_at = failed_at
            if sync.attempts >= sync.max_attempts:
                sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
                sync.next_attempt_at = None
                sync.dead_letter_reason = "provider_delete_retry_limit_exhausted"
                counters["dead_lettered"] += 1
            else:
                sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
                sync.next_attempt_at = failed_at + retry_delay_for_attempt(sync.attempts)
                sync.dead_letter_reason = "matter_disposed_delete"
                counters["retry_scheduled"] += 1
            record_from_context(
                session,
                context,
                action="calendar.deletion_tombstone.failed",
                target_type="calendar_event_sync",
                target_id=sync.id,
                result="failed",
                metadata={
                    "provider": connection.provider if connection is not None else None,
                    "source_type": sync.source_type,
                    "source_ref": redact_identifier(sync.source_id),
                    "attempts": sync.attempts,
                    "max_attempts": sync.max_attempts,
                    "error": sync.last_error,
                },
            )
        session.add(sync)
        session.commit()

    return CalendarDeletionProcessResult(**counters)


def _membership_context(
    *,
    company: Company,
    membership: CompanyMembership,
) -> SessionContext:
    return SessionContext(
        company=company,
        user=membership.user,
        membership=membership,
    )


def _default_durable_range() -> tuple[date, date]:
    start = date.today()
    return start, start + timedelta(days=_DURABLE_OUTLOOK_SYNC_WINDOW_DAYS)


def _record_calendar_sync_retry_failure(
    session: Session,
    *,
    sync: CalendarEventSync,
    context: SessionContext,
    raw_error: object,
    calendar_provider: CalendarProvider = CalendarProvider.OUTLOOK,
    now: datetime | None = None,
) -> str:
    current_time = now or _current_time()
    sync.attempts = min(sync.attempts + 1, sync.max_attempts)
    sync.last_error = redact_provider_error(raw_error)
    sync.durable_last_attempt_at = current_time
    if sync.attempts >= sync.max_attempts:
        sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
        sync.next_attempt_at = None
        sync.dead_letter_reason = "retry_limit_exhausted"
    else:
        sync.sync_status = CalendarEventSyncStatus.RETRY_SCHEDULED
        sync.next_attempt_at = current_time + retry_delay_for_attempt(sync.attempts)
        sync.dead_letter_reason = None
    session.add(sync)
    action_name = (
        "calendar.durable_google_calendar_sync.failed"
        if calendar_provider == CalendarProvider.GOOGLE_CALENDAR
        else "calendar.durable_outlook_sync.failed"
    )
    record_from_context(
        session,
        context,
        action=action_name,
        target_type="calendar_event_sync",
        target_id=sync.id,
        result="failed",
        metadata={
            "provider": calendar_provider,
            "source_type": sync.source_type,
            "source_ref": redact_identifier(sync.source_id),
            "sync_status": sync.sync_status,
            "attempts": sync.attempts,
            "max_attempts": sync.max_attempts,
            "retry_scheduled": (
                sync.sync_status == CalendarEventSyncStatus.RETRY_SCHEDULED
            ),
            "dead_lettered": sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER,
            "error": sync.last_error,
        },
    )
    session.commit()
    return str(sync.sync_status)


def _durable_sync_blocked_result(
    *,
    missing_config_names: list[str],
    missing_approval_keys: list[str],
) -> DurableOutlookSyncProcessResult:
    return DurableOutlookSyncProcessResult(
        status="blocked",
        adp20_readiness="blocked_pending_admin_configuration",
        missing_config_names=tuple(missing_config_names),
        missing_approval_keys=tuple(missing_approval_keys),
        examined=0,
        synced=0,
        failed=0,
        retry_scheduled=0,
        dead_lettered=0,
        skipped=0,
        replayed=0,
        provider_calls=0,
    )


def _process_durable_hearing_sync(
    session: Session,
    *,
    context: SessionContext,
    hearing: MatterHearing,
    connection: UserCalendarConnection,
    replay: bool,
) -> str:
    sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == CalendarSyncSourceType.MATTER_HEARING,
            CalendarEventSync.source_id == hearing.id,
        )
    )
    if sync is not None and not replay:
        if sync.sync_status in {
            CalendarEventSyncStatus.DEAD_LETTER,
            CalendarEventSyncStatus.DELETED,
            CalendarEventSyncStatus.DELETE_PENDING,
        }:
            return "skipped"
        if (
            sync.sync_status == CalendarEventSyncStatus.RETRY_SCHEDULED
            and sync.next_attempt_at is not None
            and _aware(sync.next_attempt_at) > _current_time()
        ):
            return "skipped"

    response = sync_hearing_to_outlook(
        session,
        context=context,
        hearing_id=hearing.id,
    )
    stored = session.get(CalendarEventSync, response.sync.id)
    if stored is None:
        return "failed"
    if response.sync.sync_status == CalendarEventSyncStatus.SYNCED:
        return "synced"
    if response.sync.sync_status in {
        CalendarEventSyncStatus.DELETE_PENDING,
        CalendarEventSyncStatus.DELETED,
    }:
        return "skipped"
    return _record_calendar_sync_retry_failure(
        session,
        sync=stored,
        context=context,
        raw_error=response.sync.last_error or "Outlook calendar sync failed.",
    )


def _process_durable_source_sync(
    session: Session,
    *,
    context: SessionContext,
    connection: UserCalendarConnection,
    source_type: str,
    source_id: str,
    calendar_provider: CalendarProvider,
    replay: bool,
) -> str:
    sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
    )
    if sync is not None and not replay:
        if sync.sync_status in {
            CalendarEventSyncStatus.DEAD_LETTER,
            CalendarEventSyncStatus.DELETED,
            CalendarEventSyncStatus.DELETE_PENDING,
        }:
            return "skipped"
        if (
            sync.sync_status == CalendarEventSyncStatus.RETRY_SCHEDULED
            and sync.next_attempt_at is not None
            and _aware(sync.next_attempt_at) > _current_time()
        ):
            return "skipped"

    response = _sync_source_to_provider(
        session,
        context=context,
        source_type=source_type,
        source_id=source_id,
        calendar_provider=calendar_provider,
    )
    stored = session.get(CalendarEventSync, response.sync.id)
    if stored is None:
        return "failed"
    if response.sync.sync_status == CalendarEventSyncStatus.SYNCED:
        return "synced"
    if response.sync.sync_status in {
        CalendarEventSyncStatus.DELETE_PENDING,
        CalendarEventSyncStatus.DELETED,
    }:
        return "skipped"
    return _record_calendar_sync_retry_failure(
        session,
        sync=stored,
        context=context,
        raw_error=response.sync.last_error or f"{calendar_provider} calendar sync failed.",
        calendar_provider=calendar_provider,
    )


def _replay_durable_outlook_sync_rows(
    session: Session,
    *,
    context: SessionContext,
    limit: int,
) -> DurableOutlookSyncProcessResult:
    status_summary = outlook_tenant_configuration_status(session, context=context)
    if status_summary.adp20_readiness != "ready_for_adp20_implementation":
        record_from_context(
            session,
            context,
            action="calendar.durable_outlook_sync.skipped",
            target_type="tenant_outlook_configuration",
            target_id=context.company.id,
            result="denied",
            metadata={
                "provider": CalendarProvider.OUTLOOK,
                "reason": "blocked_pending_admin_configuration",
                "missing_config_names": status_summary.missing_config_names,
                "missing_approval_keys": status_summary.missing_approval_keys,
            },
        )
        session.commit()
        return _durable_sync_blocked_result(
            missing_config_names=status_summary.missing_config_names,
            missing_approval_keys=status_summary.missing_approval_keys,
        )

    counters = {
        "examined": 0,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "skipped": 0,
        "replayed": 0,
        "provider_calls": 0,
    }
    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
            )
            .options(
                joinedload(CalendarEventSync.connection)
                .joinedload(UserCalendarConnection.membership)
                .joinedload(CompanyMembership.user),
                joinedload(CalendarEventSync.connection).joinedload(
                    UserCalendarConnection.company
                ),
            )
            .where(
                CalendarEventSync.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
                CalendarEventSync.sync_status.in_(
                    (
                        CalendarEventSyncStatus.FAILED,
                        CalendarEventSyncStatus.RETRY_SCHEDULED,
                        CalendarEventSyncStatus.DEAD_LETTER,
                    )
                ),
            )
            .order_by(CalendarEventSync.updated_at.asc())
            .limit(limit)
        )
    )
    for sync in rows:
        counters["examined"] += 1
        if sync.source_type != CalendarSyncSourceType.MATTER_HEARING:
            counters["skipped"] += 1
            continue
        row = session.execute(
            select(MatterHearing, Matter)
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(
                MatterHearing.id == sync.source_id,
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                MatterHearing.status.in_(
                    (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
                ),
            )
        ).first()
        if row is None:
            counters["skipped"] += 1
            continue
        hearing, matter = row
        connection_context = _membership_context(
            company=sync.connection.company,
            membership=sync.connection.membership,
        )
        try:
            assert_access(session, context=connection_context, matter=matter)
        except HTTPException:
            counters["skipped"] += 1
            continue
        counters["provider_calls"] += 1
        counters["replayed"] += 1
        outcome = _process_durable_hearing_sync(
            session,
            context=connection_context,
            hearing=hearing,
            connection=sync.connection,
            replay=True,
        )
        if outcome == "synced":
            counters["synced"] += 1
        elif outcome == CalendarEventSyncStatus.RETRY_SCHEDULED:
            counters["retry_scheduled"] += 1
        elif outcome == CalendarEventSyncStatus.DEAD_LETTER:
            counters["dead_lettered"] += 1
        elif outcome == "skipped":
            counters["skipped"] += 1
        else:
            counters["failed"] += 1

    record_from_context(
        session,
        context,
        action="calendar.durable_outlook_sync.replayed",
        target_type="calendar_event_sync",
        target_id=context.company.id,
        metadata={
            "provider": CalendarProvider.OUTLOOK,
            "examined": counters["examined"],
            "replayed": counters["replayed"],
            "synced": counters["synced"],
            "retry_scheduled": counters["retry_scheduled"],
            "dead_lettered": counters["dead_lettered"],
            "skipped": counters["skipped"],
        },
    )
    session.commit()
    return DurableOutlookSyncProcessResult(
        status="processed",
        adp20_readiness="ready_for_adp20_implementation",
        missing_config_names=(),
        missing_approval_keys=(),
        **counters,
    )


def process_durable_outlook_sync(
    session: Session,
    *,
    context: SessionContext,
    range_from: date | None = None,
    range_to: date | None = None,
    replay_failed_only: bool = False,
    limit: int = 200,
) -> DurableOutlookSyncProcessResult:
    process_calendar_deletion_tombstones(
        session,
        context=context,
        calendar_provider=CalendarProvider.OUTLOOK,
        limit=limit,
    )
    if replay_failed_only:
        return _replay_durable_outlook_sync_rows(
            session,
            context=context,
            limit=limit,
        )

    status_summary = outlook_tenant_configuration_status(session, context=context)
    if status_summary.adp20_readiness != "ready_for_adp20_implementation":
        record_from_context(
            session,
            context,
            action="calendar.durable_outlook_sync.skipped",
            target_type="tenant_outlook_configuration",
            target_id=context.company.id,
            result="denied",
            metadata={
                "provider": CalendarProvider.OUTLOOK,
                "reason": "blocked_pending_admin_configuration",
                "missing_config_names": status_summary.missing_config_names,
                "missing_approval_keys": status_summary.missing_approval_keys,
            },
        )
        session.commit()
        return _durable_sync_blocked_result(
            missing_config_names=status_summary.missing_config_names,
            missing_approval_keys=status_summary.missing_approval_keys,
        )

    if range_from is None or range_to is None:
        default_from, default_to = _default_durable_range()
        range_from = range_from or default_from
        range_to = range_to or default_to
    if range_to < range_from:
        raise ValueError("Durable Outlook sync range is invalid.")
    if (range_to - range_from).days > _DURABLE_OUTLOOK_SYNC_WINDOW_DAYS:
        raise ValueError("Durable Outlook sync range exceeds the bounded window.")

    counters = {
        "examined": 0,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "skipped": 0,
        "replayed": 0,
        "provider_calls": 0,
    }
    connections = list(
        session.scalars(
            select(UserCalendarConnection)
            .options(
                joinedload(UserCalendarConnection.company),
                joinedload(UserCalendarConnection.membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
            )
            .order_by(UserCalendarConnection.created_at.asc())
        )
    )
    remaining = limit
    for connection in connections:
        if remaining <= 0:
            break
        connection_context = _membership_context(
            company=connection.company,
            membership=connection.membership,
        )
        rows = list(
            session.execute(
                select(MatterHearing, Matter)
                .join(Matter, Matter.id == MatterHearing.matter_id)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.is_active.is_(True),
                    Matter.status.notin_(("closed", "disposed")),
                    visible_matters_filter(session, context=connection_context),
                    MatterHearing.hearing_on >= range_from,
                    MatterHearing.hearing_on <= range_to,
                    MatterHearing.status.in_(
                        (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
                    ),
                )
                .order_by(MatterHearing.hearing_on, MatterHearing.id)
                .limit(remaining)
            ).all()
        )
        for hearing, _matter in rows:
            counters["examined"] += 1
            remaining -= 1
            outcome = _process_durable_hearing_sync(
                session,
                context=connection_context,
                hearing=hearing,
                connection=connection,
                replay=False,
            )
            if outcome == "skipped":
                counters["skipped"] += 1
                continue
            counters["provider_calls"] += 1
            if outcome == "synced":
                counters["synced"] += 1
            elif outcome == CalendarEventSyncStatus.RETRY_SCHEDULED:
                counters["retry_scheduled"] += 1
            elif outcome == CalendarEventSyncStatus.DEAD_LETTER:
                counters["dead_lettered"] += 1
            else:
                counters["failed"] += 1

    record_from_context(
        session,
        context,
        action="calendar.durable_outlook_sync.processed",
        target_type="tenant_outlook_configuration",
        target_id=context.company.id,
        metadata={
            "provider": CalendarProvider.OUTLOOK,
            "source_types": [CalendarSyncSourceType.MATTER_HEARING],
            "unsupported_source_types": [
                CalendarSyncSourceType.MATTER_DEADLINE,
                CalendarSyncSourceType.MATTER_TASK,
            ],
            "examined": counters["examined"],
            "synced": counters["synced"],
            "retry_scheduled": counters["retry_scheduled"],
            "dead_lettered": counters["dead_lettered"],
            "skipped": counters["skipped"],
        },
    )
    session.commit()
    return DurableOutlookSyncProcessResult(
        status="processed",
        adp20_readiness="ready_for_adp20_implementation",
        missing_config_names=(),
        missing_approval_keys=(),
        **counters,
    )


def process_durable_outlook_sync_by_company(
    company_id: str,
    *,
    initiated_by_membership_id: str | None = None,
    range_from: date | None = None,
    range_to: date | None = None,
    replay_failed_only: bool = False,
    limit: int = 200,
) -> DurableOutlookSyncProcessResult:
    from caseops_api.db.session import get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        company = session.get(Company, company_id)
        if company is None:
            return _durable_sync_blocked_result(
                missing_config_names=[],
                missing_approval_keys=["company_not_found"],
            )
        membership_stmt = (
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
            )
            .order_by(CompanyMembership.created_at.asc())
        )
        if initiated_by_membership_id is not None:
            membership_stmt = membership_stmt.where(
                CompanyMembership.id == initiated_by_membership_id,
            )
        membership = session.scalar(membership_stmt)
        if membership is None:
            return _durable_sync_blocked_result(
                missing_config_names=[],
                missing_approval_keys=["active_membership_not_found"],
            )
        context = _membership_context(company=company, membership=membership)
        return process_durable_outlook_sync(
            session,
            context=context,
            range_from=range_from,
            range_to=range_to,
            replay_failed_only=replay_failed_only,
            limit=limit,
        )


def _replay_durable_google_calendar_sync_rows(
    session: Session,
    *,
    context: SessionContext,
    limit: int,
) -> DurableOutlookSyncProcessResult:
    provider = _google_calendar_provider(session, context=context)
    if not provider.configured:
        missing = _missing_google_calendar_config_names(
            provider,
            _google_calendar_runtime_config(session, context=context),
        )
        record_from_context(
            session,
            context,
            action="calendar.durable_google_calendar_sync.skipped",
            target_type="user_calendar_connection",
            target_id=context.company.id,
            result="denied",
            metadata={
                "provider": CalendarProvider.GOOGLE_CALENDAR,
                "reason": "blocked_missing_google_calendar_config",
                "missing_config_names": missing,
            },
        )
        session.commit()
        return _durable_sync_blocked_result(
            missing_config_names=missing,
            missing_approval_keys=[],
        )

    counters = {
        "examined": 0,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "skipped": 0,
        "replayed": 0,
        "provider_calls": 0,
    }
    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
            )
            .options(
                joinedload(CalendarEventSync.connection)
                .joinedload(UserCalendarConnection.membership)
                .joinedload(CompanyMembership.user),
                joinedload(CalendarEventSync.connection).joinedload(
                    UserCalendarConnection.company
                ),
            )
            .where(
                CalendarEventSync.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.GOOGLE_CALENDAR,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
                CalendarEventSync.sync_status.in_(
                    (
                        CalendarEventSyncStatus.FAILED,
                        CalendarEventSyncStatus.RETRY_SCHEDULED,
                        CalendarEventSyncStatus.DEAD_LETTER,
                    )
                ),
            )
            .order_by(CalendarEventSync.updated_at.asc())
            .limit(limit)
        )
    )
    for sync in rows:
        counters["examined"] += 1
        connection_context = _membership_context(
            company=sync.connection.company,
            membership=sync.connection.membership,
        )
        try:
            _source_payload_for(
                session,
                context=connection_context,
                source_type=sync.source_type,
                source_id=sync.source_id,
            )
        except HTTPException:
            counters["skipped"] += 1
            continue
        counters["provider_calls"] += 1
        counters["replayed"] += 1
        outcome = _process_durable_source_sync(
            session,
            context=connection_context,
            connection=sync.connection,
            source_type=sync.source_type,
            source_id=sync.source_id,
            calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
            replay=True,
        )
        if outcome == "synced":
            counters["synced"] += 1
        elif outcome == CalendarEventSyncStatus.RETRY_SCHEDULED:
            counters["retry_scheduled"] += 1
        elif outcome == CalendarEventSyncStatus.DEAD_LETTER:
            counters["dead_lettered"] += 1
        elif outcome == "skipped":
            counters["skipped"] += 1
        else:
            counters["failed"] += 1

    record_from_context(
        session,
        context,
        action="calendar.durable_google_calendar_sync.replayed",
        target_type="calendar_event_sync",
        target_id=context.company.id,
        metadata={
            "provider": CalendarProvider.GOOGLE_CALENDAR,
            "source_types": list(_GOOGLE_CALENDAR_SYNC_SOURCE_TYPES),
            "examined": counters["examined"],
            "replayed": counters["replayed"],
            "synced": counters["synced"],
            "retry_scheduled": counters["retry_scheduled"],
            "dead_lettered": counters["dead_lettered"],
            "skipped": counters["skipped"],
        },
    )
    session.commit()
    return DurableOutlookSyncProcessResult(
        status="processed",
        adp20_readiness="ready_for_adp20_implementation",
        missing_config_names=(),
        missing_approval_keys=(),
        **counters,
    )


def process_durable_google_calendar_sync(
    session: Session,
    *,
    context: SessionContext,
    range_from: date | None = None,
    range_to: date | None = None,
    replay_failed_only: bool = False,
    limit: int = 200,
) -> DurableOutlookSyncProcessResult:
    process_calendar_deletion_tombstones(
        session,
        context=context,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
        limit=limit,
    )
    if replay_failed_only:
        return _replay_durable_google_calendar_sync_rows(
            session,
            context=context,
            limit=limit,
        )

    provider = _google_calendar_provider(session, context=context)
    if not provider.configured:
        missing = _missing_google_calendar_config_names(
            provider,
            _google_calendar_runtime_config(session, context=context),
        )
        record_from_context(
            session,
            context,
            action="calendar.durable_google_calendar_sync.skipped",
            target_type="user_calendar_connection",
            target_id=context.company.id,
            result="denied",
            metadata={
                "provider": CalendarProvider.GOOGLE_CALENDAR,
                "reason": "blocked_missing_google_calendar_config",
                "missing_config_names": missing,
            },
        )
        session.commit()
        return _durable_sync_blocked_result(
            missing_config_names=missing,
            missing_approval_keys=[],
        )

    if range_from is None or range_to is None:
        default_from, default_to = _default_durable_range()
        range_from = range_from or default_from
        range_to = range_to or default_to
    if range_to < range_from:
        raise ValueError("Durable Google Calendar sync range is invalid.")
    if (range_to - range_from).days > _DURABLE_OUTLOOK_SYNC_WINDOW_DAYS:
        raise ValueError("Durable Google Calendar sync range exceeds the bounded window.")

    counters = {
        "examined": 0,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "skipped": 0,
        "replayed": 0,
        "provider_calls": 0,
    }
    connections = list(
        session.scalars(
            select(UserCalendarConnection)
            .options(
                joinedload(UserCalendarConnection.company),
                joinedload(UserCalendarConnection.membership).joinedload(
                    CompanyMembership.user
                ),
            )
            .where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.GOOGLE_CALENDAR,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
            )
            .order_by(UserCalendarConnection.created_at.asc())
        )
    )
    remaining = limit
    for connection in connections:
        if remaining <= 0:
            break
        connection_context = _membership_context(
            company=connection.company,
            membership=connection.membership,
        )
        request = OutlookBulkSyncRequest.model_validate(
            {
                "from": range_from,
                "to": range_to,
                "source_types": list(_GOOGLE_CALENDAR_SYNC_SOURCE_TYPES),
                "limit": remaining,
            }
        )
        for source_type in _GOOGLE_CALENDAR_SYNC_SOURCE_TYPES:
            if remaining <= 0:
                break
            source_rows = _google_bulk_source_payloads(
                session,
                context=connection_context,
                payload=request,
                connection=connection,
                source_type=source_type,
                limit=remaining,
            )
            for item, _was_existing in source_rows:
                counters["examined"] += 1
                remaining -= 1
                outcome = _process_durable_source_sync(
                    session,
                    context=connection_context,
                    connection=connection,
                    source_type=item.source_type,
                    source_id=item.source_id,
                    calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                    replay=False,
                )
                if outcome == "skipped":
                    counters["skipped"] += 1
                    continue
                counters["provider_calls"] += 1
                if outcome == "synced":
                    counters["synced"] += 1
                elif outcome == CalendarEventSyncStatus.RETRY_SCHEDULED:
                    counters["retry_scheduled"] += 1
                elif outcome == CalendarEventSyncStatus.DEAD_LETTER:
                    counters["dead_lettered"] += 1
                else:
                    counters["failed"] += 1
                if remaining <= 0:
                    break

    record_from_context(
        session,
        context,
        action="calendar.durable_google_calendar_sync.processed",
        target_type="user_calendar_connection",
        target_id=context.company.id,
        metadata={
            "provider": CalendarProvider.GOOGLE_CALENDAR,
            "source_types": list(_GOOGLE_CALENDAR_SYNC_SOURCE_TYPES),
            "examined": counters["examined"],
            "synced": counters["synced"],
            "retry_scheduled": counters["retry_scheduled"],
            "dead_lettered": counters["dead_lettered"],
            "skipped": counters["skipped"],
        },
    )
    session.commit()
    return DurableOutlookSyncProcessResult(
        status="processed",
        adp20_readiness="ready_for_adp20_implementation",
        missing_config_names=(),
        missing_approval_keys=(),
        **counters,
    )


def process_durable_google_calendar_sync_by_company(
    company_id: str,
    *,
    initiated_by_membership_id: str | None = None,
    range_from: date | None = None,
    range_to: date | None = None,
    replay_failed_only: bool = False,
    limit: int = 200,
) -> DurableOutlookSyncProcessResult:
    from caseops_api.db.session import get_session_factory

    session_factory = get_session_factory()
    with session_factory() as session:
        company = session.get(Company, company_id)
        if company is None:
            return _durable_sync_blocked_result(
                missing_config_names=[],
                missing_approval_keys=["company_not_found"],
            )
        membership_stmt = (
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
            )
            .order_by(CompanyMembership.created_at.asc())
        )
        if initiated_by_membership_id is not None:
            membership_stmt = membership_stmt.where(
                CompanyMembership.id == initiated_by_membership_id,
            )
        membership = session.scalar(membership_stmt)
        if membership is None:
            return _durable_sync_blocked_result(
                missing_config_names=[],
                missing_approval_keys=["active_membership_not_found"],
            )
        context = _membership_context(company=company, membership=membership)
        return process_durable_google_calendar_sync(
            session,
            context=context,
            range_from=range_from,
            range_to=range_to,
            replay_failed_only=replay_failed_only,
            limit=limit,
        )


def _duplicate_conflict_candidates(
    syncs: list[CalendarEventSync],
) -> list[CalendarSyncConflictCandidate]:
    grouped: dict[tuple[str, str], list[CalendarEventSync]] = {}
    for sync in syncs:
        if not sync.provider_event_id:
            continue
        key = (sync.calendar_connection_id, sync.provider_event_id)
        grouped.setdefault(key, []).append(sync)

    candidates: list[CalendarSyncConflictCandidate] = []
    for (connection_id, provider_event_id), rows in sorted(grouped.items()):
        if len(rows) < 2:
            continue
        rows = sorted(rows, key=lambda row: (row.source_type, row.source_id, row.id))
        provider_value = rows[0].connection.provider
        provider_label = (
            "Outlook"
            if provider_value == CalendarProvider.OUTLOOK
            else "Google Calendar"
        )
        candidate_id = hashlib.sha256(
            f"{connection_id}:{provider_event_id}".encode()
        ).hexdigest()[:16]
        candidates.append(
            CalendarSyncConflictCandidate(
                id=f"dup-provider-event:{candidate_id}",
                conflict_type="duplicate_provider_event_id",
                provider=provider_value,  # type: ignore[arg-type]
                calendar_connection_id=connection_id,
                provider_event_id=provider_event_id,
                duplicate_count=len(rows),
                source_ids=[row.source_id for row in rows],
                source_types=sorted({row.source_type for row in rows}),  # type: ignore[list-item]
                sync_ids=[row.id for row in rows],
                message=(
                    "Multiple CaseOps calendar sync records point to the same "
                    f"{provider_label} event. Review before running another manual sync."
                ),
            )
        )
    return candidates


def _safe_error(exc: BaseException) -> str:
    return redact_provider_error(str(exc) or exc.__class__.__name__)[:500]


def list_connections(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarConnectionListResponse:
    provider = _outlook_provider(session, context=context)
    rows = list(
        session.scalars(
            select(UserCalendarConnection)
            .where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
            )
            .order_by(UserCalendarConnection.created_at.asc())
        )
    )
    return CalendarConnectionListResponse(
        provider_available=provider.configured,
        unavailable_reason=provider.unavailable_reason,
        durable_automation=_durable_automation_value(session, context=context),  # type: ignore[arg-type]
        connections=[_connection_record(row) for row in rows],
    )


def start_outlook_connection(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarConnectionStartResponse:
    return _start_connection(
        session,
        context=context,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def start_google_calendar_connection(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarConnectionStartResponse:
    return _start_connection(
        session,
        context=context,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def _start_connection(
    session: Session,
    *,
    context: SessionContext,
    calendar_provider: CalendarProvider,
) -> CalendarConnectionStartResponse:
    provider = _provider_for(calendar_provider, session, context=context)
    if not provider.configured:
        return CalendarConnectionStartResponse(
            provider=calendar_provider,  # type: ignore[arg-type]
            provider_available=False,
            unavailable_reason=provider.unavailable_reason,
        )
    return CalendarConnectionStartResponse(
        provider=calendar_provider,  # type: ignore[arg-type]
        provider_available=True,
        auth_url=provider.authorization_url(
            state=_sign_state(context, provider=calendar_provider)
        ),
    )


def complete_outlook_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> CalendarConnectionRecord:
    return _complete_connection(
        session,
        context=context,
        code=code,
        state=state,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def complete_google_calendar_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> CalendarConnectionRecord:
    return _complete_connection(
        session,
        context=context,
        code=code,
        state=state,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def _complete_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
    calendar_provider: CalendarProvider,
) -> CalendarConnectionRecord:
    provider = _provider_for(calendar_provider, session, context=context)
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=provider.unavailable_reason or "Calendar sync is unavailable.",
        )
    _verify_state(context, state, provider=calendar_provider)
    exchanged = provider.exchange_code(code=code)
    token_payload = exchanged.get("token_payload")
    if not isinstance(token_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Calendar OAuth provider returned an invalid token response.",
        )
    now = datetime.now(UTC)
    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == calendar_provider,
        )
    )
    if connection is None:
        connection = UserCalendarConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=calendar_provider,
        )
        session.add(connection)
        session.flush()
    connection.provider_account_id = str(exchanged.get("provider_account_id") or "") or None
    connection.display_email = str(exchanged.get("display_email") or "") or None
    connection.status = CalendarConnectionStatus.CONNECTED
    connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
    default_scopes = (
        OUTLOOK_SCOPES
        if calendar_provider == CalendarProvider.OUTLOOK
        else GOOGLE_CALENDAR_SCOPES
    )
    connection.scopes_json = [
        str(scope) for scope in exchanged.get("scopes", default_scopes) if str(scope)
    ]
    connection.connected_at = now
    session.add(connection)
    record_from_context(
        session,
        context,
        action="calendar.connection.connected",
        target_type="user_calendar_connection",
        target_id=connection.id,
        metadata={
            "provider": calendar_provider,
            "display_email": connection.display_email,
            "scopes": connection.scopes_json,
        },
    )
    session.commit()
    return _connection_record(connection)


def revoke_connection(
    session: Session,
    *,
    context: SessionContext,
    connection_id: str,
) -> CalendarConnectionRecord:
    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar connection not found.",
        )
    connection.status = CalendarConnectionStatus.REVOKED
    connection.encrypted_token_ref = None
    session.add(connection)
    record_from_context(
        session,
        context,
        action="calendar.connection.revoked",
        target_type="user_calendar_connection",
        target_id=connection.id,
        metadata={"provider": connection.provider},
    )
    session.commit()
    return _connection_record(connection)


def _connected_outlook_connection(
    session: Session,
    *,
    context: SessionContext,
) -> UserCalendarConnection:
    return _connected_calendar_connection(
        session,
        context=context,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def _connected_google_calendar_connection(
    session: Session,
    *,
    context: SessionContext,
) -> UserCalendarConnection:
    return _connected_calendar_connection(
        session,
        context=context,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def _connected_calendar_connection(
    session: Session,
    *,
    context: SessionContext,
    calendar_provider: CalendarProvider,
) -> UserCalendarConnection:
    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == calendar_provider,
            UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
        )
    )
    if connection is None:
        provider_label = (
            "Outlook"
            if calendar_provider == CalendarProvider.OUTLOOK
            else "Google Calendar"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{provider_label} is not connected.",
        )
    return connection


def sync_hearing_to_outlook(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
) -> CalendarEventSyncResponse:
    return _sync_hearing_to_provider(
        session,
        context=context,
        hearing_id=hearing_id,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def sync_hearing_to_google_calendar(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
) -> CalendarEventSyncResponse:
    return _sync_hearing_to_provider(
        session,
        context=context,
        hearing_id=hearing_id,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def sync_task_to_outlook(
    session: Session,
    *,
    context: SessionContext,
    task_id: str,
) -> CalendarEventSyncResponse:
    return _sync_source_to_provider(
        session,
        context=context,
        source_type=CalendarSyncSourceType.MATTER_TASK.value,
        source_id=task_id,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def sync_deadline_to_outlook(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
) -> CalendarEventSyncResponse:
    return _sync_source_to_provider(
        session,
        context=context,
        source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
        source_id=deadline_id,
        calendar_provider=CalendarProvider.OUTLOOK,
    )


def sync_task_to_google_calendar(
    session: Session,
    *,
    context: SessionContext,
    task_id: str,
) -> CalendarEventSyncResponse:
    return _sync_source_to_provider(
        session,
        context=context,
        source_type=CalendarSyncSourceType.MATTER_TASK.value,
        source_id=task_id,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def sync_deadline_to_google_calendar(
    session: Session,
    *,
    context: SessionContext,
    deadline_id: str,
) -> CalendarEventSyncResponse:
    return _sync_source_to_provider(
        session,
        context=context,
        source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
        source_id=deadline_id,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def delete_hearing_from_google_calendar(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
) -> CalendarEventSyncResponse:
    return _delete_hearing_from_provider(
        session,
        context=context,
        hearing_id=hearing_id,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
    )


def _sync_hearing_to_provider(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
    calendar_provider: CalendarProvider,
) -> CalendarEventSyncResponse:
    return _sync_source_to_provider(
        session,
        context=context,
        source_type=CalendarSyncSourceType.MATTER_HEARING.value,
        source_id=hearing_id,
        calendar_provider=calendar_provider,
    )


def _post_provider_deletion_winner(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    expected_lifecycle_version: int,
    sync_id: str,
    connection: UserCalendarConnection,
    calendar_provider: CalendarProvider,
    provider: OutlookProvider | None,
    token_payload: dict[str, Any] | None,
    returned_provider_event_id: str | None,
) -> CalendarEventSyncResponse | None:
    """Recheck lifecycle/tombstone state after an external provider call.

    Provider I/O is necessarily outside the Matter lock.  Disposal can win
    during that window, so the response is not allowed to blindly overwrite a
    tombstone with ``SYNCED``/``FAILED``.  Locking parent then sync mirrors the
    lifecycle writer and closes that TOCTOU window.
    """

    matter = session.scalar(
        select(Matter)
        .where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
        .with_for_update(of=Matter)
        .execution_options(populate_existing=True)
    )
    sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    if sync is None:
        raise CalendarProviderError("Calendar sync state disappeared after provider call.")

    deletion_state = sync.sync_status in {
        CalendarEventSyncStatus.DELETE_PENDING,
        CalendarEventSyncStatus.DELETED,
    } or (
        sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
        and str(sync.dead_letter_reason or "").startswith("provider_delete_")
    )
    lifecycle_changed = (
        matter is None
        or not matter_is_operational(matter)
        or matter.lifecycle_version != expected_lifecycle_version
    )
    if not deletion_state and not lifecycle_changed:
        return None

    now = _current_time()
    cleanup_error: str | None = None
    if returned_provider_event_id:
        # A provider may have created/updated the event after disposal had
        # already written the tombstone.  Delete that exact returned artifact;
        # if deletion fails, retain durable DELETE_PENDING work.
        sync.provider_event_id = returned_provider_event_id
        try:
            if provider is None or token_payload is None:
                raise CalendarProviderError(
                    "Provider response could not be cleaned up after lifecycle change."
                )
            provider.delete_event(
                token_payload=token_payload,
                provider_event_id=returned_provider_event_id,
            )
        except Exception as exc:
            cleanup_error = redact_provider_error(exc)
            sync.attempts = min(sync.attempts + 1, sync.max_attempts)
            sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
            sync.last_error = cleanup_error
            sync.next_attempt_at = now + retry_delay_for_attempt(sync.attempts)
            sync.dead_letter_reason = "matter_disposed_delete"
            sync.durable_last_attempt_at = now
        else:
            sync.sync_status = CalendarEventSyncStatus.DELETED
            sync.last_error = None
            sync.last_synced_at = now
            sync.next_attempt_at = None
            sync.dead_letter_reason = None
            sync.durable_last_attempt_at = now
            connection.last_sync_at = now
            session.add(connection)
    elif sync.provider_event_id and sync.sync_status != CalendarEventSyncStatus.DELETED:
        # The upsert failed or returned no new id, but a previously-synced
        # remote event still needs the durable worker to remove it.
        sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        sync.next_attempt_at = now
        sync.dead_letter_reason = "matter_disposed_delete"
    elif sync.sync_status != CalendarEventSyncStatus.DELETED:
        sync.sync_status = CalendarEventSyncStatus.DELETED
        sync.last_error = None
        sync.last_synced_at = now
        sync.next_attempt_at = None
        sync.dead_letter_reason = None

    session.add(sync)
    record_from_context(
        session,
        context,
        action="calendar.sync.lifecycle_change_won",
        target_type="calendar_event_sync",
        target_id=sync.id,
        matter_id=matter_id,
        result="denied" if cleanup_error else "success",
        metadata={
            "provider": calendar_provider,
            "source_type": sync.source_type,
            "source_ref": redact_identifier(sync.source_id),
            "sync_status": sync.sync_status,
            "lifecycle_changed": lifecycle_changed,
            "cleanup_error": cleanup_error,
        },
    )
    session.commit()
    return CalendarEventSyncResponse(sync=_sync_record(sync))


def _sync_source_to_provider(
    session: Session,
    *,
    context: SessionContext,
    source_type: str,
    source_id: str,
    calendar_provider: CalendarProvider,
) -> CalendarEventSyncResponse:
    item = _source_payload_for(
        session,
        context=context,
        source_type=source_type,
        source_id=source_id,
    )
    connection = _connected_calendar_connection(
        session,
        context=context,
        calendar_provider=calendar_provider,
    )
    sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == item.source_type,
            CalendarEventSync.source_id == item.source_id,
        )
    )
    if sync is None:
        sync = CalendarEventSync(
            company_id=context.company.id,
            calendar_connection_id=connection.id,
            source_type=item.source_type,
            source_id=item.source_id,
            sync_status=CalendarEventSyncStatus.PENDING,
        )
        session.add(sync)
        session.flush()
    expected_lifecycle_version = (
        item.matter.lifecycle_version if item.matter is not None else None
    )
    matter_id = item.matter.id if item.matter is not None else None
    target_metadata = (
        {"ip_docket_ref": redact_identifier(item.ip_docket.id)}
        if item.ip_docket is not None
        else {}
    )
    provider: OutlookProvider | None = None
    token_payload: dict[str, Any] | None = None
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        provider = _provider_for(calendar_provider, session, context=context)
        if (
            item.matter is not None
            and item.source_type == CalendarSyncSourceType.MATTER_HEARING.value
            and hasattr(provider, "upsert_hearing_event")
        ):
            hearing = session.get(MatterHearing, item.source_id)
            if hearing is None:
                raise CalendarProviderError("Hearing disappeared before sync.")
            provider_event_id = provider.upsert_hearing_event(
                token_payload=token_payload,
                hearing=hearing,
                matter=item.matter,
                existing_provider_event_id=sync.provider_event_id,
            )
        else:
            provider_event_id = provider.upsert_calendar_item(
                token_payload=token_payload,
                item=item,
                existing_provider_event_id=sync.provider_event_id,
            )
    except Exception as exc:
        if matter_id is not None and expected_lifecycle_version is not None:
            deletion_response = _post_provider_deletion_winner(
                session,
                context=context,
                matter_id=matter_id,
                expected_lifecycle_version=expected_lifecycle_version,
                sync_id=sync.id,
                connection=connection,
                calendar_provider=calendar_provider,
                provider=provider,
                token_payload=token_payload,
                returned_provider_event_id=None,
            )
            if deletion_response is not None:
                return deletion_response
        sync.sync_status = CalendarEventSyncStatus.FAILED
        sync.last_error = _safe_error(exc)
        session.add(sync)
        record_from_context(
            session,
            context,
            action="calendar.sync.failed",
            target_type="calendar_event_sync",
            target_id=sync.id,
            matter_id=matter_id,
            result="failed",
            metadata={
                "provider": calendar_provider,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "error": sync.last_error,
                **target_metadata,
            },
        )
        session.commit()
        return CalendarEventSyncResponse(sync=_sync_record(sync))

    if matter_id is not None and expected_lifecycle_version is not None:
        deletion_response = _post_provider_deletion_winner(
            session,
            context=context,
            matter_id=matter_id,
            expected_lifecycle_version=expected_lifecycle_version,
            sync_id=sync.id,
            connection=connection,
            calendar_provider=calendar_provider,
            provider=provider,
            token_payload=token_payload,
            returned_provider_event_id=provider_event_id,
        )
        if deletion_response is not None:
            return deletion_response

    # _post_provider_deletion_winner refreshed and locked this row.  Resolve it
    # again from the identity map so the success write targets the fresh state.
    sync = session.get(CalendarEventSync, sync.id)
    if sync is None:  # pragma: no cover - protected by the locked recheck
        raise CalendarProviderError("Calendar sync state disappeared after provider call.")
    now = datetime.now(UTC)
    sync.provider_event_id = provider_event_id
    sync.sync_status = CalendarEventSyncStatus.SYNCED
    sync.last_error = None
    sync.last_synced_at = now
    sync.next_attempt_at = None
    sync.dead_letter_reason = None
    # Re-projecting is the repair, so any recorded drift is now stale rather
    # than resolved: it is cleared to `unchecked` and must be re-checked to be
    # claimed as matching (UJ-62-EXC-03).
    sync.drift_status = "unchecked"
    sync.drift_checked_at = None
    sync.drift_detail = None
    connection.last_sync_at = now
    session.add_all([sync, connection])
    record_from_context(
        session,
        context,
        action="calendar.sync.succeeded",
        target_type="calendar_event_sync",
        target_id=sync.id,
        matter_id=matter_id,
        metadata={
            "provider": calendar_provider,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "provider_event_id": provider_event_id,
            **target_metadata,
        },
    )
    session.commit()
    return CalendarEventSyncResponse(sync=_sync_record(sync))


def _delete_hearing_from_provider(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
    calendar_provider: CalendarProvider,
) -> CalendarEventSyncResponse:
    row = session.execute(
        select(MatterHearing, Matter)
        .join(Matter, Matter.id == MatterHearing.matter_id)
        .where(
            MatterHearing.id == hearing_id,
            Matter.company_id == context.company.id,
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Hearing not found.",
        )
    hearing, matter = row
    assert_access(session, context=context, matter=matter)
    connection = _connected_calendar_connection(
        session,
        context=context,
        calendar_provider=calendar_provider,
    )
    sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == CalendarSyncSourceType.MATTER_HEARING,
            CalendarEventSync.source_id == hearing.id,
        )
    )
    if sync is None or not sync.provider_event_id:
        provider_label = (
            "Outlook"
            if calendar_provider == CalendarProvider.OUTLOOK
            else "Google Calendar"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No synced {provider_label} event found for this hearing.",
        )
    if sync.sync_status == CalendarEventSyncStatus.DELETED:
        return CalendarEventSyncResponse(sync=_sync_record(sync))

    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        _provider_for(
            calendar_provider,
            session,
            context=context,
        ).delete_event(
            token_payload=token_payload,
            provider_event_id=sync.provider_event_id,
        )
    except Exception as exc:
        sync.sync_status = CalendarEventSyncStatus.FAILED
        sync.last_error = _safe_error(exc)
        session.add(sync)
        record_from_context(
            session,
            context,
            action="calendar.sync.delete_failed",
            target_type="calendar_event_sync",
            target_id=sync.id,
            matter_id=matter.id,
            result="failed",
            metadata={
                "provider": calendar_provider,
                "source_type": CalendarSyncSourceType.MATTER_HEARING,
                "source_id": hearing.id,
                "error": sync.last_error,
            },
        )
        session.commit()
        return CalendarEventSyncResponse(sync=_sync_record(sync))

    now = datetime.now(UTC)
    sync.sync_status = CalendarEventSyncStatus.DELETED
    sync.last_error = None
    sync.last_synced_at = now
    sync.next_attempt_at = None
    sync.dead_letter_reason = None
    connection.last_sync_at = now
    session.add_all([sync, connection])
    record_from_context(
        session,
        context,
        action="calendar.sync.deleted",
        target_type="calendar_event_sync",
        target_id=sync.id,
        matter_id=matter.id,
        metadata={
            "provider": calendar_provider,
            "source_type": CalendarSyncSourceType.MATTER_HEARING,
            "source_id": hearing.id,
            "provider_event_id": sync.provider_event_id,
        },
    )
    session.commit()
    return CalendarEventSyncResponse(sync=_sync_record(sync))


def delete_synced_hearing_events_for_context(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
    commit: bool = True,
) -> int:
    hearing = session.scalar(
        select(MatterHearing).where(
            MatterHearing.id == hearing_id,
            MatterHearing.company_id == context.company.id,
        )
    )
    if hearing is None:
        return 0
    target = resolve_shared_work_target(
        session,
        context=context,
        matter_id=hearing.matter_id,
        ip_docket_id=hearing.ip_docket_id,
    )
    matter_id = target.matter_id
    target_metadata = (
        {"ip_docket_ref": redact_identifier(target.ip_docket_id)}
        if target.ip_docket_id is not None
        else {}
    )
    syncs = list(
        session.scalars(
            select(CalendarEventSync)
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id
                == CalendarEventSync.calendar_connection_id,
            )
            .options(joinedload(CalendarEventSync.connection))
            .where(
                CalendarEventSync.company_id == context.company.id,
                CalendarEventSync.source_type == CalendarSyncSourceType.MATTER_HEARING,
                CalendarEventSync.source_id == hearing_id,
                CalendarEventSync.provider_event_id.is_not(None),
                CalendarEventSync.sync_status != CalendarEventSyncStatus.DELETED,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
            )
        )
    )
    deleted_count = 0
    now = datetime.now(UTC)
    for sync in syncs:
        provider_event_id = sync.provider_event_id
        if not provider_event_id:
            continue
        try:
            token_payload = _decrypt_token_payload(sync.connection.encrypted_token_ref)
            _provider_for(
                CalendarProvider(sync.connection.provider),
                session,
                context=context,
            ).delete_event(
                token_payload=token_payload,
                provider_event_id=provider_event_id,
            )
        except Exception as exc:
            sync.sync_status = CalendarEventSyncStatus.FAILED
            sync.last_error = _safe_error(exc)
            sync.updated_at = now
            session.add(sync)
            record_from_context(
                session,
                context,
                action="calendar.sync.auto_delete_failed",
                target_type="calendar_event_sync",
                target_id=sync.id,
                matter_id=matter_id,
                result="failed",
                metadata={
                    "provider": sync.connection.provider,
                    "source_type": CalendarSyncSourceType.MATTER_HEARING,
                    "source_id": hearing_id,
                    "reason": "hearing_cancelled",
                    "error": sync.last_error,
                    **target_metadata,
                },
            )
            continue
        sync.sync_status = CalendarEventSyncStatus.DELETED
        sync.last_error = None
        sync.last_synced_at = now
        sync.next_attempt_at = None
        sync.dead_letter_reason = None
        sync.updated_at = now
        sync.connection.last_sync_at = now
        session.add_all([sync, sync.connection])
        deleted_count += 1
        record_from_context(
            session,
            context,
            action="calendar.sync.auto_deleted",
            target_type="calendar_event_sync",
            target_id=sync.id,
            matter_id=matter_id,
            metadata={
                "provider": sync.connection.provider,
                "source_type": CalendarSyncSourceType.MATTER_HEARING,
                "source_id": hearing_id,
                "reason": "hearing_cancelled",
                "provider_event_id": provider_event_id,
                **target_metadata,
            },
        )
    if commit:
        session.commit()
    return deleted_count


def resync_synced_hearing_events_for_context(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
) -> int:
    """Update only provider copies already selected by this user.

    The legal hearing commit happens before this helper is invoked. Provider
    failures therefore remain observable sync state and cannot undo CaseOps.
    """

    synced_hearing_exists = (
        select(CalendarEventSync.id)
        .where(
            CalendarEventSync.calendar_connection_id == UserCalendarConnection.id,
            CalendarEventSync.source_type == CalendarSyncSourceType.MATTER_HEARING,
            CalendarEventSync.source_id == hearing_id,
            CalendarEventSync.provider_event_id.is_not(None),
            CalendarEventSync.sync_status != CalendarEventSyncStatus.DELETED,
        )
        .exists()
    )
    connections = list(
        session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
                UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
                synced_hearing_exists,
            )
        )
    )
    for connection in connections:
        _sync_source_to_provider(
            session,
            context=context,
            source_type=CalendarSyncSourceType.MATTER_HEARING.value,
            source_id=hearing_id,
            calendar_provider=CalendarProvider(connection.provider),
        )
    return len(connections)


def sync_outlook_bulk(
    session: Session,
    *,
    context: SessionContext,
    payload: OutlookBulkSyncRequest,
) -> OutlookBulkSyncResponse:
    """BUG-039 (Hari 2026-05-09) — bounded manual bulk sync.

    Loops the caller's visible hearings within ``[from, to]`` (and
    optionally narrowed to a single ``matter_id``) and pushes each
    one to Outlook via ``sync_hearing_to_outlook``. Returns a
    structured summary instead of any HTTP-stream-of-status
    nonsense; the caller (frontend toast / runbook curl) renders
    the counts directly.

    Idempotency: each per-hearing call goes through the same
    ``CalendarEventSync (calendar_connection_id, source_type,
    source_id)`` unique constraint that the per-hearing endpoint
    relies on. Re-running a bulk sync over the same range is safe;
    rows with `sync_status="synced"` are touched again only if the
    Graph upsert actually returns a (possibly identical)
    ``provider_event_id``.

    Tenant + ethical-wall + team-scoping enforcement: the SELECT
    uses ``visible_matters_filter`` so opaque-walled matters never
    enter the loop. Each per-hearing call additionally re-asserts
    access defensively. No cross-tenant leakage is possible.

    Source types other than ``matter_hearing`` are accepted in the
    request but not actually synced — they are echoed as `skipped`
    items with `skip_reason="source_type_unsupported"`. Implementing
    task / deadline upsert against Microsoft Graph is a future
    extension that needs a separate provider method.

    Durable background provider sync remains blocked pending provider
    approval — see the response's ``durable_automation`` field.
    """

    # 409 if no Outlook connection — checked first so a user without a
    # connection always sees the same actionable env-state error,
    # regardless of any other request-shape issues. The frontend
    # disables the button in this state, but a hand-rolled curl call
    # gets a clean response.
    connection = _connected_outlook_connection(session, context=context)

    if (payload.range_to - payload.range_from).days > 92:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Range exceeds 92 days. Narrow the from/to window before "
                "retrying — bulk sync is intentionally bounded."
            ),
        )
    if payload.range_to < payload.range_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`to` must be on or after `from`.",
        )

    requested_sources = list(payload.source_types or ["matter_hearing"])
    seen_sources: set[str] = set()
    items: list[OutlookBulkSyncItem] = []
    counters = {"created": 0, "updated": 0, "failed": 0, "skipped": 0}
    examined = 0

    if "matter_hearing" in requested_sources:
        seen_sources.add("matter_hearing")
        # SELECT with the same visibility filter the calendar feed
        # uses — opaquely walled matters and out-of-team matters
        # are excluded at the SQL level. Optional matter_id narrows
        # further.
        stmt = (
            select(MatterHearing, Matter)
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                visible_matters_filter(session, context=context),
                MatterHearing.hearing_on >= payload.range_from,
                MatterHearing.hearing_on <= payload.range_to,
                MatterHearing.status.in_(
                    (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
                ),
            )
            .order_by(MatterHearing.hearing_on, MatterHearing.id)
            .limit(payload.limit)
        )
        if payload.matter_id is not None:
            stmt = stmt.where(Matter.id == payload.matter_id)

        rows = list(session.execute(stmt).all())

        # Materialise the hearing-id list so we can pre-detect
        # which rows already had a sync row before this batch (used
        # to split the `synced` outcome into `created` vs
        # `updated`). Materialising before the loop also makes the
        # commits inside `sync_hearing_to_outlook` safe — we never
        # iterate a result-set across a commit boundary.
        hearing_ids = [hearing.id for hearing, _ in rows]
        existing_sync_source_ids: set[str] = set()
        if hearing_ids:
            existing_sync_source_ids = set(
                session.scalars(
                    select(CalendarEventSync.source_id).where(
                        CalendarEventSync.company_id == context.company.id,
                        CalendarEventSync.calendar_connection_id
                        == connection.id,
                        CalendarEventSync.source_type
                        == CalendarSyncSourceType.MATTER_HEARING,
                        CalendarEventSync.source_id.in_(hearing_ids),
                    )
                )
            )

        for hearing, matter in rows:
            examined += 1
            was_existing = hearing.id in existing_sync_source_ids
            try:
                resp = sync_hearing_to_outlook(
                    session, context=context, hearing_id=hearing.id
                )
            except HTTPException as exc:
                # Only fires for races (the row vanished mid-batch)
                # or access changes between the SELECT above and the
                # per-hearing re-check inside the function. Counted
                # as failed; surface a redacted detail.
                counters["failed"] += 1
                items.append(
                    OutlookBulkSyncItem(
                        source_type="matter_hearing",
                        source_id=hearing.id,
                        sync_status=CalendarEventSyncStatus.FAILED,
                        matter_id=matter.id,
                        matter_title=matter.title,
                        last_error=str(exc.detail),
                    )
                )
                continue

            sync = resp.sync
            if sync.sync_status == CalendarEventSyncStatus.SYNCED:
                if was_existing:
                    counters["updated"] += 1
                else:
                    counters["created"] += 1
            else:
                counters["failed"] += 1
            items.append(
                OutlookBulkSyncItem(
                    source_type="matter_hearing",
                    source_id=hearing.id,
                    sync_status=sync.sync_status,
                    matter_id=matter.id,
                    matter_title=matter.title,
                    provider_event_id=sync.provider_event_id,
                    last_error=sync.last_error,
                )
            )

    # Unsupported source types — emit one skipped item per type so
    # the caller knows which were ignored without us silently
    # eating their request.
    for source in requested_sources:
        if source in seen_sources:
            continue
        seen_sources.add(source)
        counters["skipped"] += 1
        items.append(
            OutlookBulkSyncItem(
                source_type=source,
                source_id="",
                sync_status="skipped",
                matter_id=None,
                matter_title=None,
                skip_reason="source_type_unsupported",
            )
        )

    return OutlookBulkSyncResponse(
        examined=examined,
        created=counters["created"],
        updated=counters["updated"],
        failed=counters["failed"],
        skipped=counters["skipped"],
        items=items,
        durable_automation=_durable_automation_value(session, context=context),  # type: ignore[arg-type]
    )


def _google_bulk_source_payloads(
    session: Session,
    *,
    context: SessionContext,
    payload: OutlookBulkSyncRequest,
    connection: UserCalendarConnection,
    source_type: str,
    limit: int,
) -> list[tuple[CalendarSourcePayload, bool]]:
    if limit <= 0:
        return []

    if source_type == CalendarSyncSourceType.MATTER_HEARING:
        stmt = (
            select(MatterHearing, Matter)
            .join(Matter, Matter.id == MatterHearing.matter_id)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                visible_matters_filter(session, context=context),
                MatterHearing.hearing_on >= payload.range_from,
                MatterHearing.hearing_on <= payload.range_to,
                MatterHearing.status.in_(
                    (MatterHearingStatus.SCHEDULED, MatterHearingStatus.ADJOURNED)
                ),
            )
            .order_by(MatterHearing.hearing_on, MatterHearing.id)
            .limit(limit)
        )
        if payload.matter_id is not None:
            stmt = stmt.where(Matter.id == payload.matter_id)
        pairs = [
            _hearing_source_payload(hearing, matter)
            for hearing, matter in session.execute(stmt).all()
        ]
    elif source_type == CalendarSyncSourceType.MATTER_TASK.value:
        stmt = (
            select(MatterTask, Matter)
            .join(Matter, Matter.id == MatterTask.matter_id)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                visible_matters_filter(session, context=context),
                MatterTask.due_on.is_not(None),
                MatterTask.status.notin_(
                    (MatterTaskStatus.COMPLETED, MatterTaskStatus.CANCELLED)
                ),
                MatterTask.due_on >= payload.range_from,
                MatterTask.due_on <= payload.range_to,
            )
            .order_by(MatterTask.due_on, MatterTask.id)
            .limit(limit)
        )
        if payload.matter_id is not None:
            stmt = stmt.where(Matter.id == payload.matter_id)
        pairs = [
            _task_source_payload(task, matter)
            for task, matter in session.execute(stmt).all()
        ]
    elif source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        stmt = (
            select(MatterDeadline, Matter)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                Matter.company_id == context.company.id,
                Matter.is_active.is_(True),
                Matter.status.notin_(("closed", "disposed")),
                visible_matters_filter(session, context=context),
                MatterDeadline.status.notin_(("done", "cancelled")),
                MatterDeadline.due_on >= payload.range_from,
                MatterDeadline.due_on <= payload.range_to,
            )
            .order_by(MatterDeadline.due_on, MatterDeadline.id)
            .limit(limit)
        )
        if payload.matter_id is not None:
            stmt = stmt.where(Matter.id == payload.matter_id)
        pairs = [
            _deadline_source_payload(deadline, matter)
            for deadline, matter in session.execute(stmt).all()
        ]
    else:
        return []

    existing_ids: set[str] = set()
    source_ids = [item.source_id for item in pairs]
    if source_ids:
        existing_ids = set(
            session.scalars(
                select(CalendarEventSync.source_id).where(
                    CalendarEventSync.company_id == context.company.id,
                    CalendarEventSync.calendar_connection_id == connection.id,
                    CalendarEventSync.source_type == source_type,
                    CalendarEventSync.source_id.in_(source_ids),
                )
            )
        )
    return [(item, item.source_id in existing_ids) for item in pairs]


def sync_google_calendar_bulk(
    session: Session,
    *,
    context: SessionContext,
    payload: OutlookBulkSyncRequest,
) -> OutlookBulkSyncResponse:
    """Bounded manual Google Calendar sync for visible hearings/tasks/deadlines."""
    connection = _connected_google_calendar_connection(session, context=context)

    if (payload.range_to - payload.range_from).days > 92:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Range exceeds 92 days. Narrow the from/to window before "
                "retrying - bulk sync is intentionally bounded."
            ),
        )
    if payload.range_to < payload.range_from:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="`to` must be on or after `from`.",
        )

    requested_sources = list(payload.source_types or _GOOGLE_CALENDAR_SYNC_SOURCE_TYPES)
    seen_sources: set[str] = set()
    items: list[OutlookBulkSyncItem] = []
    counters = {"created": 0, "updated": 0, "failed": 0, "skipped": 0}
    examined = 0
    remaining = payload.limit

    for source in requested_sources:
        if source in seen_sources:
            continue
        seen_sources.add(source)
        if source not in _GOOGLE_CALENDAR_SYNC_SOURCE_TYPES:
            counters["skipped"] += 1
            items.append(
                OutlookBulkSyncItem(
                    source_type=source,
                    source_id="",
                    sync_status="skipped",
                    matter_id=None,
                    matter_title=None,
                    skip_reason="source_type_unsupported",
                )
            )
            continue
        if remaining <= 0:
            break

        source_rows = _google_bulk_source_payloads(
            session,
            context=context,
            payload=payload,
            connection=connection,
            source_type=source,
            limit=remaining,
        )
        for item, was_existing in source_rows:
            examined += 1
            remaining -= 1
            try:
                resp = _sync_source_to_provider(
                    session,
                    context=context,
                    source_type=item.source_type,
                    source_id=item.source_id,
                    calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                )
            except HTTPException as exc:
                counters["failed"] += 1
                items.append(
                    OutlookBulkSyncItem(
                        source_type=item.source_type,  # type: ignore[arg-type]
                        source_id=item.source_id,
                        sync_status=CalendarEventSyncStatus.FAILED,
                        matter_id=item.matter.id,
                        matter_title=item.matter.title,
                        last_error=str(exc.detail),
                    )
                )
                continue

            sync = resp.sync
            if sync.sync_status == CalendarEventSyncStatus.SYNCED:
                if was_existing:
                    counters["updated"] += 1
                else:
                    counters["created"] += 1
            else:
                counters["failed"] += 1
            items.append(
                OutlookBulkSyncItem(
                    source_type=item.source_type,  # type: ignore[arg-type]
                    source_id=item.source_id,
                    sync_status=sync.sync_status,
                    matter_id=item.matter.id,
                    matter_title=item.matter.title,
                    provider_event_id=sync.provider_event_id,
                    last_error=sync.last_error,
                )
            )
            if remaining <= 0:
                break

    return OutlookBulkSyncResponse(
        examined=examined,
        created=counters["created"],
        updated=counters["updated"],
        failed=counters["failed"],
        skipped=counters["skipped"],
        items=items,
        durable_automation="blocked_pending_provider_approval",
    )


def sync_status(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarSyncStatusResponse:
    runtime_config = _outlook_runtime_config(session, context=context)
    provider = _outlook_provider(session, context=context)
    google_runtime_config = _google_calendar_runtime_config(session, context=context)
    google_provider = _google_calendar_provider(session, context=context)
    connections = list(
        session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
            )
        )
    )
    syncs = list(
        session.scalars(
            select(CalendarEventSync)
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
            )
            .where(
                CalendarEventSync.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
            )
            .order_by(CalendarEventSync.updated_at.desc())
        )
    )
    conflict_candidates = _duplicate_conflict_candidates(syncs)
    durable_automation = _durable_automation_value(session, context=context)
    any_provider_configured = provider.configured or google_provider.configured
    return CalendarSyncStatusResponse(
        provider_available=any_provider_configured,
        durable_automation=durable_automation,  # type: ignore[arg-type]
        notification_delivery="wtd_5_3_foundation_available",
        capabilities=CalendarSyncCapabilityStatus(
            manual_sync_available=any_provider_configured,
            durable_automation=durable_automation,  # type: ignore[arg-type]
            notification_delivery="wtd_5_3_foundation_available",
            email_invitation_candidates="review_queue_available",
        ),
        provider_config=[
            _provider_config_status(provider, runtime_config),
            _google_calendar_provider_config_status(
                google_provider, google_runtime_config
            ),
        ],
        conflict_summary=CalendarSyncConflictSummary(
            has_conflicts=bool(conflict_candidates),
            candidate_count=len(conflict_candidates),
            duplicate_provider_event_count=len(conflict_candidates),
            changed_event_candidate_count=0,
            changed_event_detection="unsupported_no_provider_snapshot",
        ),
        conflict_candidates=conflict_candidates,
        connections=[_connection_record(row) for row in connections],
        syncs=[_sync_record(row) for row in syncs],
    )


__all__ = [
    "CalendarDeletionProcessResult",
    "complete_google_calendar_connection",
    "complete_outlook_connection",
    "delete_hearing_from_google_calendar",
    "delete_synced_hearing_events_for_context",
    "DurableOutlookSyncProcessResult",
    "GOOGLE_CALENDAR_SCOPES",
    "list_connections",
    "outlook_tenant_configuration_status",
    "process_calendar_deletion_tombstones",
    "process_durable_google_calendar_sync",
    "process_durable_google_calendar_sync_by_company",
    "process_durable_outlook_sync",
    "process_durable_outlook_sync_by_company",
    "resync_synced_hearing_events_for_context",
    "revoke_connection",
    "set_google_calendar_provider_for_tests",
    "set_outlook_provider_for_tests",
    "start_google_calendar_connection",
    "start_outlook_connection",
    "sync_google_calendar_bulk",
    "sync_deadline_to_google_calendar",
    "sync_deadline_to_outlook",
    "sync_hearing_to_google_calendar",
    "sync_hearing_to_outlook",
    "sync_status",
    "sync_task_to_google_calendar",
    "sync_task_to_outlook",
    "test_outlook_tenant_configuration",
    "update_outlook_tenant_configuration",
]


@dataclass(frozen=True)
class CalendarDriftFinding:
    """One projected event compared against the CaseOps source (UJ-62-EXC-03)."""

    sync_id: str
    connection_id: str
    membership_id: str | None
    source_type: str
    source_id: str
    ip_docket_id: str | None
    drift_status: str
    detail: str


def _drift_provider_reader(
    session: Session,
    *,
    context: SessionContext,
    connection: UserCalendarConnection,
):
    """Return a callable that reads one event back, or ``None`` if it cannot."""

    if connection.status != CalendarConnectionStatus.CONNECTED:
        return None
    try:
        # Tenant-admin OAuth configuration is resolved from the current
        # company. Omitting session/context silently falls back to environment
        # configuration and makes otherwise valid tenant connections unreadable.
        provider = _provider_for(connection.provider, session, context=context)
    except Exception:  # pragma: no cover - defensive: unknown provider string
        return None
    reader = getattr(provider, "fetch_event", None)
    if reader is None or not getattr(provider, "configured", False):
        # A provider that cannot be read yields `unknown`, never `matches`.
        return None
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    except CalendarProviderError:
        # A damaged or legacy token makes this connection unreadable; it must
        # not abort checks for every other connection in the tenant.
        return None
    if not token_payload:
        return None

    def _read(provider_event_id: str) -> dict[str, Any] | None:
        return reader(token_payload=token_payload, provider_event_id=provider_event_id)

    return _read


def check_ip_calendar_projection_drift(
    session: Session,
    *,
    context: SessionContext,
) -> list[CalendarDriftFinding]:
    """Detect projected IP events edited or deleted in the provider (UJ-62-EXC-03).

    The external calendar is a copy; CaseOps holds the obligation. Nothing
    detected a copy being changed out of band, so a lawyer's calendar could
    quietly disagree with the date they are accountable for.

    This **detects and records**; it does not silently rewrite someone's own
    calendar. A drifted row is surfaced so the change is deliberate, and a
    successful re-sync clears the finding.

    An unreadable provider records `unknown`. Reporting `matches` for something
    that was never read would be the same falsehood as counting unknown work as
    no work.
    """

    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == context.company.id,
                CalendarEventSync.source_type.in_(
                    [
                        CalendarSyncSourceType.MATTER_HEARING.value,
                        CalendarSyncSourceType.MATTER_TASK.value,
                        CalendarSyncSourceType.MATTER_DEADLINE.value,
                    ]
                ),
                CalendarEventSync.sync_status == CalendarEventSyncStatus.SYNCED,
                CalendarEventSync.provider_event_id.is_not(None),
            )
            .order_by(CalendarEventSync.id)
        ).all()
    )
    if not rows:
        return []

    connections = {
        connection.id: connection
        for connection in session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.id.in_({row.calendar_connection_id for row in rows}),
                UserCalendarConnection.company_id == context.company.id,
            )
        ).all()
    }
    readers: dict[str, Any] = {}
    now = _current_time()
    findings: list[CalendarDriftFinding] = []

    for row in rows:
        connection = connections.get(row.calendar_connection_id)
        if connection is None:
            continue
        # Only IP-linked sources are in scope for this slice; a non-IP row
        # returns None here and is left untouched.
        try:
            payload = _ip_source_payload_for(
                session,
                context=context,
                source_type=row.source_type,
                source_id=row.source_id,
            )
        except HTTPException:
            # The caller cannot open this record. One such row must not abort
            # the whole check for someone with partial access — it is simply
            # not theirs to check, and the record's owner will check it.
            continue
        if payload is None:
            continue
        # A drift finding names a record. A caller who cannot open that record
        # must not learn of it here, so the row is checked but not reported.
        docket = payload.ip_docket
        reportable = docket is not None and can_access_ip_docket(
            session, context=context, docket=docket
        )

        if connection.id not in readers:
            readers[connection.id] = _drift_provider_reader(
                session, context=context, connection=connection
            )
        reader = readers[connection.id]

        if reader is None:
            status_value = "unknown"
            detail = "The calendar connection could not be read."
        else:
            try:
                event = reader(str(row.provider_event_id))
            except CalendarProviderError as exc:
                status_value = "unknown"
                detail = _safe_error(exc)
            except Exception:  # pragma: no cover - provider adapters are varied
                status_value = "unknown"
                detail = "The calendar provider could not be read."
            else:
                if event is None or event.get("cancelled"):
                    status_value = "missing"
                    detail = "The event is no longer on the calendar."
                else:
                    expected = payload.occurs_on.isoformat()
                    actual = str(event.get("start_date") or "")
                    if actual and actual != expected:
                        status_value = "moved"
                        # Content-free: states that it moved, not to when — the
                        # authoritative date lives in CaseOps.
                        detail = "The event was moved away from the CaseOps date."
                    elif not actual:
                        status_value = "unknown"
                        detail = "The event carries no readable date."
                    else:
                        status_value = "matches"
                        detail = "The event matches the CaseOps date."

        row.drift_status = status_value
        row.drift_checked_at = now
        row.drift_detail = detail
        row.updated_at = now

        if status_value in {"moved", "missing", "unknown"} and reportable:
            findings.append(
                CalendarDriftFinding(
                    sync_id=row.id,
                    connection_id=connection.id,
                    membership_id=connection.membership_id,
                    source_type=row.source_type,
                    source_id=row.source_id,
                    ip_docket_id=getattr(payload.ip_docket, "id", None),
                    drift_status=status_value,
                    detail=detail,
                )
            )
            record_from_context(
                session,
                context,
                action="calendar_event_sync.drift_detected",
                target_type="calendar_event_sync",
                target_id=row.id,
                ip_docket_id=getattr(payload.ip_docket, "id", None),
                metadata={"drift_status": status_value, "source_type": row.source_type},
            )

    session.commit()
    return findings
