from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import quote, urlencode
from uuid import uuid4

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import and_, or_, select
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
    IpDeadline,
    IpDeadlineCoverage,
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
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_projection_safety import (
    CALENDAR_UPSERT_CLAIM_PREFIX,
    CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
    calendar_sync_has_unreceipted_upsert_claim,
    calendar_sync_replay_safe_clause,
    calendar_sync_requires_manual_reconciliation,
    calendar_sync_upsert_claim_state,
    materialize_expired_calendar_sync_upsert_claim,
)
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.google_workspace import google_workspace_oauth_config
from caseops_api.services.http_retries import request_with_retries
from caseops_api.services.matter_access import (
    assert_access,
    can_access,
    can_access_ip_docket,
    visible_matters_filter,
)
from caseops_api.services.matter_operational_guard import matter_is_operational
from caseops_api.services.notification_delivery import (
    redact_provider_error,
    retry_delay_for_attempt,
)
from caseops_api.services.security import require_recent_step_up
from caseops_api.services.session_context import SessionContext
from caseops_api.services.shared_work import resolve_shared_work_target

OUTLOOK_SCOPES = ["offline_access", "User.Read", "Calendars.ReadWrite"]
GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
_STATE_KINDS = {
    CalendarProvider.OUTLOOK: "outlook_calendar_oauth",
    CalendarProvider.GOOGLE_CALENDAR: "google_calendar_oauth",
}
_STATE_TTL_MINUTES = 10
_CALENDAR_PROVIDER_LEASE = timedelta(minutes=5)
_CALENDAR_UPSERT_CLAIM_PREFIX = CALENDAR_UPSERT_CLAIM_PREFIX
_CALENDAR_DELETE_CLAIM_PREFIX = "provider_delete_claim:"
_CALENDAR_DRIFT_CLAIM_PREFIX = "provider_drift_claim:"
_CALENDAR_OAUTH_CLAIM_KEY = "_caseops_calendar_oauth_claim"
_CALENDAR_OAUTH_CLAIM_EXPIRES_KEY = "_caseops_calendar_oauth_claim_expires_at"

# These are the only coverage states that confer live projection authority.
# Historical or terminal coverage rows still classify the source as IP-owned,
# but they can never fall back to the generic Matter payload/ACL.
_IP_OPERATIONAL_COVERAGE_STATUSES = {
    "accepted",
    "emergency",
    "escalated",
    "pending",
    "reassigned",
    "transfer_pending",
}


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


@dataclass(frozen=True, slots=True)
class _IpCalendarProjectionAuthority:
    """Stable ids needed to reauthorize an IP projection after provider I/O."""

    source_type: str
    source_id: str
    docket_id: str
    ip_deadline_id: str | None = None
    matter_deadline_id: str | None = None
    coverage_id: str | None = None


@dataclass(frozen=True, slots=True)
class _CalendarSourceSnapshot:
    """Exact child and payload-parent generation dispatched to a provider."""

    source_type: str
    source_id: str
    source_values: tuple[tuple[str, object], ...]
    matter_values: tuple[tuple[str, object], ...] | None
    docket_values: tuple[tuple[str, object], ...] | None


def _snapshot_value(value: object) -> object:
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return value


def _mapped_values(row: object | None) -> tuple[tuple[str, object], ...] | None:
    if row is None:
        return None
    table = row.__table__
    return tuple(
        (column.name, _snapshot_value(getattr(row, column.name)))
        for column in table.columns
    )


def _calendar_source_snapshot(
    *,
    source_type: str,
    source_id: str,
    source_row: MatterHearing | MatterTask | MatterDeadline,
    matter: Matter | None,
    docket: IpDocketRecord | None,
) -> _CalendarSourceSnapshot:
    return _CalendarSourceSnapshot(
        source_type=source_type,
        source_id=source_id,
        source_values=_mapped_values(source_row) or (),
        matter_values=_mapped_values(matter),
        docket_values=_mapped_values(docket),
    )


def _calendar_source_model(
    source_type: str,
) -> type[MatterHearing] | type[MatterTask] | type[MatterDeadline]:
    if source_type == CalendarSyncSourceType.MATTER_HEARING.value:
        return MatterHearing
    if source_type == CalendarSyncSourceType.MATTER_TASK.value:
        return MatterTask
    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        return MatterDeadline
    raise CalendarProviderError("Unsupported calendar source type.")


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


def _assert_linked_ip_calendar_access(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    matter: Matter | None = None,
) -> Matter | None:
    """Require the IP ACL and, when present, the independent Matter ACL."""

    if (
        docket.company_id != context.company.id
        or not docket.is_active
        or docket.archived_by_matter_disposal
        or not can_access_ip_docket(session, context=context, docket=docket)
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP docket record not found.",
        )
    if docket.matter_id is None:
        return None
    linked_matter = matter or session.scalar(
        select(Matter).where(
            Matter.id == docket.matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if (
        linked_matter is None
        or not matter_is_operational(linked_matter)
        or not can_access(session, context=context, matter=linked_matter)
    ):
        # Neither side of the independent ACL boundary is disclosed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar source not found.",
        )
    return linked_matter


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

    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        coverage_rows = list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id == source_id,
                )
                .order_by(IpDeadlineCoverage.id)
            ).all()
        )
        if coverage_rows:
            operational = [
                coverage
                for coverage in coverage_rows
                if str(coverage.coverage_status)
                in _IP_OPERATIONAL_COVERAGE_STATUSES
            ]
            if len(operational) > 1:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_coverage_projection_shared_deadline_unsupported",
                        "message": (
                            "A deadline shared by multiple operational IP dockets "
                            "requires a group calendar projection."
                        ),
                        "matter_deadline_id": source_id,
                        "blocked_coverage_ids": [row.id for row in operational],
                        "blocked_docket_ids": sorted(
                            {row.docket_id for row in operational}
                        ),
                    },
                )
            if not operational:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "ip_coverage_projection_inactive",
                        "message": "The IP deadline coverage is no longer operational.",
                    },
                )
            coverage = operational[0]
            linked = session.execute(
                select(MatterDeadline, IpDocketRecord, Matter)
                .select_from(MatterDeadline)
                .join(
                    IpDocketRecord,
                    IpDocketRecord.id == coverage.docket_id,
                )
                .join(Matter, Matter.id == MatterDeadline.matter_id)
                .where(
                    MatterDeadline.id == source_id,
                    MatterDeadline.company_id == context.company.id,
                    MatterDeadline.status.in_(("open", "missed")),
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.matter_id == MatterDeadline.matter_id,
                    Matter.company_id == context.company.id,
                )
            ).first()
            if linked is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "code": "ip_coverage_projection_source_inactive",
                        "message": "The IP deadline source is no longer operational.",
                    },
                )
            deadline, docket, matter = linked
            if context.membership.id not in {
                coverage.responsible_membership_id,
                coverage.backup_membership_id,
            }:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Calendar source not found.",
                )
            _assert_linked_ip_calendar_access(
                session,
                context=context,
                docket=docket,
                matter=matter,
            )
            return _ip_source_payload(
                source_type=source_type,
                source_id=source_id,
                occurs_on=deadline.due_on,
                category="Deadline",
                docket=docket,
            )

    row = session.scalar(
        select(model).where(
            model.id == source_id,
            model.company_id == context.company.id,
            model.ip_docket_id.is_not(None),
        )
    )
    if row is None:
        if source_type != CalendarSyncSourceType.MATTER_DEADLINE.value:
            return None
        linked = session.execute(
            select(MatterDeadline, IpDeadline, IpDocketRecord, Matter)
            .join(
                IpDeadline,
                IpDeadline.matter_deadline_id == MatterDeadline.id,
            )
            .join(IpDocketRecord, IpDocketRecord.id == IpDeadline.docket_id)
            .join(Matter, Matter.id == MatterDeadline.matter_id)
            .where(
                MatterDeadline.id == source_id,
                MatterDeadline.company_id == context.company.id,
                MatterDeadline.ip_docket_id.is_(None),
                MatterDeadline.source_ref_type == "ip_deadline",
                MatterDeadline.source_ref_id == IpDeadline.id,
                IpDeadline.company_id == context.company.id,
                IpDocketRecord.company_id == context.company.id,
                IpDocketRecord.matter_id == MatterDeadline.matter_id,
                Matter.company_id == context.company.id,
            )
        ).first()
        if linked is None:
            return None
        deadline, _legal_deadline, docket, matter = linked
        _assert_linked_ip_calendar_access(
            session,
            context=context,
            docket=docket,
            matter=matter,
        )
        return _ip_source_payload(
            source_type=source_type,
            source_id=source_id,
            occurs_on=deadline.due_on,
            category="Deadline",
            docket=docket,
        )
    assert row.ip_docket_id is not None
    target = resolve_shared_work_target(
        session,
        context=context,
        ip_docket_id=row.ip_docket_id,
    )
    assert target.ip_docket is not None
    _assert_linked_ip_calendar_access(
        session,
        context=context,
        docket=target.ip_docket,
    )
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
        if hearing.status not in {
            MatterHearingStatus.SCHEDULED,
            MatterHearingStatus.ADJOURNED,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Terminal hearings are removed from provider calendars.",
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
        if task.due_on is None or task.status not in {
            MatterTaskStatus.TODO,
            MatterTaskStatus.IN_PROGRESS,
            MatterTaskStatus.BLOCKED,
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Terminal or undated tasks cannot be synced to calendar.",
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
        if str(deadline.status) not in {"open", "missed"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Terminal deadlines are removed from provider calendars.",
            )
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


def _test_outlook_tenant_configuration_fenced(
    session: Session,
    *,
    context: SessionContext,
) -> OutlookReadinessTestResponse:
    """Claim/probe/finalize readiness without holding locks over Graph I/O."""

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    actor = memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    require_locked_membership_capability(session, actor, "workspace:admin")
    context = SessionContext(company=context.company, membership=actor, user=actor.user)
    require_recent_step_up(
        session,
        context=context,
        purpose="outlook_readiness_probe",
    )
    row = _ensure_tenant_outlook_configuration(session, context=context)
    row = session.scalar(
        select(TenantOutlookConfiguration)
        .where(
            TenantOutlookConfiguration.id == row.id,
            TenantOutlookConfiguration.company_id == context.company.id,
        )
        .with_for_update(of=TenantOutlookConfiguration)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    tested_at = _current_time()
    status_summary = outlook_tenant_configuration_status(session, context=context)
    checks = [
        *(
            OutlookReadinessCheckResult(
                key=item.name,
                label=item.name,
                status="passed" if item.configured else "blocked",
            )
            for item in status_summary.required_config
        ),
        *(
            OutlookReadinessCheckResult(
                key=item.key,
                label=item.label,
                status="passed" if item.approved else "blocked",
            )
            for item in status_summary.required_approvals
        ),
    ]
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
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
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
    connection_snapshot = (
        connection.id,
        str(connection.status),
        _aware(connection.updated_at),
        hashlib.sha256((connection.encrypted_token_ref or "").encode()).hexdigest(),
        connection.provider_account_id,
    )
    token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
    provider = _provider(session, context=context)
    claim_marker = f"outlook_readiness_claim:{uuid4().hex}"
    row.last_test_status = "testing"
    row.last_tested_at = tested_at
    row.last_error_redacted = claim_marker
    session.add(row)
    row_id = row.id
    connection_id = connection.id
    session.commit()
    probe_error: str | None = None
    try:
        provider.validate_connection(token_payload=token_payload)
    except Exception as exc:  # noqa: BLE001 - provider boundary
        probe_error = _safe_error(exc)

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    actor = memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    require_locked_membership_capability(session, actor, "workspace:admin")
    context = SessionContext(company=context.company, membership=actor, user=actor.user)
    require_recent_step_up(
        session,
        context=context,
        purpose="outlook_readiness_probe",
    )
    row = session.scalar(
        select(TenantOutlookConfiguration)
        .where(
            TenantOutlookConfiguration.id == row_id,
            TenantOutlookConfiguration.company_id == context.company.id,
        )
        .with_for_update(of=TenantOutlookConfiguration)
        .execution_options(populate_existing=True)
    )
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    current_connection_snapshot = (
        connection.id,
        str(connection.status),
        _aware(connection.updated_at),
        hashlib.sha256((connection.encrypted_token_ref or "").encode()).hexdigest(),
        connection.provider_account_id,
    ) if connection is not None else None
    if (
        row is None
        or row.last_test_status != "testing"
        or row.last_error_redacted != claim_marker
        or current_connection_snapshot != connection_snapshot
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "outlook_readiness_probe_stale",
                "message": (
                    "Outlook configuration, connection, or authority changed "
                    "during the probe; its result was discarded."
                ),
            },
        )
    if probe_error is not None:
        checks.append(
            OutlookReadinessCheckResult(
                key="MICROSOFT_GRAPH_ME",
                label="Microsoft Graph /me probe",
                status="failed",
                detail=probe_error,
            )
        )
        row.last_test_status = "failed"
        row.last_tested_at = tested_at
        row.last_error_redacted = probe_error
        audit_action = "outlook.configuration.test_failed"
        audit_result = "failed"
    else:
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
        audit_action = "outlook.configuration.test_passed"
        audit_result = "success"
    record_from_context(
        session,
        context,
        action=audit_action,
        target_type="tenant_outlook_configuration",
        target_id=row.id,
        result=audit_result,
        metadata={"provider": CalendarProvider.OUTLOOK, "check_count": len(checks)},
    )
    session.commit()
    return OutlookReadinessTestResponse(
        status="failed" if probe_error is not None else "passed",
        checks=checks,
        adp20_readiness=(
            "blocked_pending_admin_configuration"
            if probe_error is not None
            else "ready_for_adp20_implementation"
        ),
        tested_at=tested_at,
    )


def test_outlook_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> OutlookReadinessTestResponse:
    return _test_outlook_tenant_configuration_fenced(
        session,
        context=context,
    )

    # Unreachable legacy body retained below until the guarded implementation
    # is fully exercised by compatibility tests.
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
        provider = _provider(session, context=context)
        session.commit()
        provider.validate_connection(
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


def _calendar_claim_marker(prefix: str) -> str:
    return f"{prefix}{uuid4().hex}"


def _calendar_claim_is_live(
    sync: CalendarEventSync,
    *,
    prefix: str,
    now: datetime,
) -> bool:
    return bool(
        str(sync.dead_letter_reason or "").startswith(prefix)
        and sync.next_attempt_at is not None
        and _aware(sync.next_attempt_at) > now
    )


def _materialize_expired_unreceipted_upsert_claim(
    session: Session,
    *,
    context: SessionContext,
    sync: CalendarEventSync,
    calendar_provider: CalendarProvider | str,
    now: datetime | None = None,
) -> bool:
    """Fence an ambiguous create before any authority writer can erase it.

    The caller owns the exact Sync row lock and, for deadline projections, its
    MatterDeadline parent lock.  A live lease remains the claimant's property;
    only an expired no-receipt create is classified here.
    """

    current_time = now or _current_time()
    if not materialize_expired_calendar_sync_upsert_claim(
        sync,
        now=current_time,
    ):
        return False
    session.add(sync)
    if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=sync.source_id,
        )
    record_from_context(
        session,
        context,
        action="calendar.sync.claim_expired",
        target_type="calendar_event_sync",
        target_id=sync.id,
        result="failed",
        metadata={
            "provider": str(calendar_provider),
            "source_type": sync.source_type,
            "source_ref": redact_identifier(sync.source_id),
        },
    )
    return True


def materialize_expired_calendar_upsert_claims(
    session: Session,
    *,
    context: SessionContext,
    calendar_provider: CalendarProvider | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> int:
    """Boundedly type expired no-receipt creates without resolving sources.

    Discovery intentionally ignores source existence, lifecycle, type-specific
    status, and calendar range. Each candidate is then materialized under the
    normal Membership/User -> source parent -> Sync order, with zero provider
    I/O, so cancelled/missing/out-of-range work remains operator-selectable.
    """

    current_time = now or _current_time()
    filters = [
        CalendarEventSync.company_id == context.company.id,
        CalendarEventSync.provider_event_id.is_(None),
        CalendarEventSync.dead_letter_reason.startswith(
            _CALENDAR_UPSERT_CLAIM_PREFIX
        ),
        or_(
            CalendarEventSync.next_attempt_at.is_(None),
            CalendarEventSync.next_attempt_at <= current_time,
        ),
        CalendarEventSync.source_type.in_(_GOOGLE_CALENDAR_SYNC_SOURCE_TYPES),
    ]
    if calendar_provider is not None:
        filters.append(UserCalendarConnection.provider == calendar_provider)
    candidates = list(
        session.execute(
            select(
                CalendarEventSync.id,
                CalendarEventSync.source_type,
                CalendarEventSync.source_id,
                UserCalendarConnection.membership_id,
                UserCalendarConnection.provider,
            )
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id
                == CalendarEventSync.calendar_connection_id,
            )
            .where(*filters)
            .order_by(CalendarEventSync.next_attempt_at, CalendarEventSync.id)
            .limit(max(1, limit))
        )
    )
    session.commit()
    materialized = 0
    for candidate in candidates:
        lock_company_memberships_for_assignment(
            session,
            company_id=context.company.id,
            membership_ids=(
                context.membership.id,
                candidate.membership_id,
            ),
        )
        _lock_calendar_projection_source_parent(
            session,
            company_id=context.company.id,
            source_type=str(candidate.source_type),
            source_id=candidate.source_id,
        )
        sync = session.scalar(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.id == candidate.id,
                CalendarEventSync.company_id == context.company.id,
                CalendarEventSync.source_type == candidate.source_type,
                CalendarEventSync.source_id == candidate.source_id,
            )
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        )
        if sync is None or not _materialize_expired_unreceipted_upsert_claim(
            session,
            context=context,
            sync=sync,
            calendar_provider=candidate.provider,
            now=current_time,
        ):
            session.rollback()
            continue
        session.commit()
        materialized += 1
    return materialized


def _classify_existing_upsert_claim_before_source_resolution(
    session: Session,
    *,
    context: SessionContext,
    source_type: str,
    source_id: str,
    calendar_provider: CalendarProvider,
) -> CalendarEventSyncResponse | None:
    """Resolve an existing create claim before payload/authority evaluation.

    Source access can disappear while a provider request is in flight.  Looking
    up the durable claim by its connection/source identity first prevents a
    later 404, lifecycle tombstone, or access denial from claiming that the
    unreceipted remote create is absent.
    """

    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == calendar_provider,
        )
    )
    if connection is None:
        return None
    advisory_sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
    )
    if (
        advisory_sync is None
        or not calendar_sync_has_unreceipted_upsert_claim(advisory_sync)
    ):
        return None

    # No row lock was taken by the advisory lookup. Acquire the canonical
    # Membership/User -> source parent -> Sync order, then re-evaluate.
    lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(connection.membership_id,),
    )
    _lock_calendar_projection_source_parent(
        session,
        company_id=context.company.id,
        source_type=source_type,
        source_id=source_id,
    )
    sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == advisory_sync.id,
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    if sync is None or not calendar_sync_has_unreceipted_upsert_claim(sync):
        session.rollback()
        return None
    now = _current_time()
    if _calendar_claim_is_live(
        sync,
        prefix=_CALENDAR_UPSERT_CLAIM_PREFIX,
        now=now,
    ):
        response = CalendarEventSyncResponse(sync=_sync_record(sync))
        session.rollback()
        return response
    if not _materialize_expired_unreceipted_upsert_claim(
        session,
        context=context,
        sync=sync,
        calendar_provider=calendar_provider,
        now=now,
    ):  # pragma: no cover - exact locked predicate above
        session.rollback()
        return None
    response = CalendarEventSyncResponse(sync=_sync_record(sync))
    session.commit()
    return response


def _lock_calendar_projection_source_parent(
    session: Session,
    *,
    company_id: str,
    source_type: str,
    source_id: str,
) -> None:
    """Fence deadline projection parents before Sync/Connection child locks.

    Coverage cutover takes MatterDeadline -> coverage family -> Sync ->
    Connection. Provider deletion and poison-row finalization use the same
    order so their atomic coverage recompute cannot form the reverse edge.
    """

    if source_type != CalendarSyncSourceType.MATTER_DEADLINE.value:
        return
    session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == source_id,
            MatterDeadline.company_id == company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.matter_deadline_id == source_id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    )
def _maybe_clear_revoked_calendar_credential(
    session: Session,
    *,
    connection: UserCalendarConnection | None,
) -> None:
    """Drop a revoked token only after every possible remote copy is drained.

    The encrypted token is the bounded revocation credential lease.  It is not
    exposed to workers until an exact sync row is claimed, and is retained when
    a provider delete is retrying/dead-lettered so revocation never strands a
    privileged remote calendar copy merely because the first delete failed.
    """

    if connection is None or connection.status != CalendarConnectionStatus.REVOKED:
        return
    outstanding = list(
        session.scalars(
            select(CalendarEventSync).where(
                CalendarEventSync.calendar_connection_id == connection.id,
                CalendarEventSync.company_id == connection.company_id,
            )
        ).all()
    )
    if any(
        (
            row.provider_event_id is not None
            and row.sync_status != CalendarEventSyncStatus.DELETED
        )
        or str(row.dead_letter_reason or "").startswith(
            _CALENDAR_UPSERT_CLAIM_PREFIX
        )
        or str(row.dead_letter_reason or "").startswith(
            _CALENDAR_DELETE_CLAIM_PREFIX
        )
        or calendar_sync_requires_manual_reconciliation(row)
        for row in outstanding
    ):
        return
    connection.encrypted_token_ref = None
    session.add(connection)


def _process_calendar_deletion_tombstone_by_id(
    session: Session,
    *,
    context: SessionContext,
    sync_id: str,
    expected_connection_id: str,
) -> tuple[str, bool]:
    """Claim, call, and finalize one delete without holding a transaction over I/O."""

    now = _current_time()
    advisory_sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
        )
        .execution_options(populate_existing=True)
    )
    if advisory_sync is None:
        session.rollback()
        return "skipped", False
    source_type = str(advisory_sync.source_type)
    source_id = advisory_sync.source_id
    session.rollback()
    _lock_calendar_projection_source_parent(
        session,
        company_id=context.company.id,
        source_type=source_type,
        source_id=source_id,
    )
    sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    if (
        sync is None
        or sync.calendar_connection_id != expected_connection_id
        or sync.sync_status != CalendarEventSyncStatus.DELETE_PENDING
        or (
            sync.next_attempt_at is not None
            and _aware(sync.next_attempt_at) > now
            and not str(sync.dead_letter_reason or "").startswith(
                _CALENDAR_UPSERT_CLAIM_PREFIX
            )
        )
    ):
        session.rollback()
        return "skipped", False
    if _calendar_claim_is_live(
        sync,
        prefix=_CALENDAR_DELETE_CLAIM_PREFIX,
        now=now,
    ):
        session.rollback()
        return "skipped", False
    if _calendar_claim_is_live(
        sync,
        prefix=_CALENDAR_UPSERT_CLAIM_PREFIX,
        now=now,
    ):
        # Revocation deliberately preserves an in-flight upsert claim.  Its
        # callback owns publishing the exact returned provider id; a delete
        # worker must not erase that fence or destroy the retained credential.
        session.rollback()
        return "skipped", False

    provider_event_id = sync.provider_event_id
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == expected_connection_id,
            UserCalendarConnection.company_id == context.company.id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if (
        str(sync.dead_letter_reason or "").startswith(
            _CALENDAR_UPSERT_CLAIM_PREFIX
        )
        and not provider_event_id
    ):
        # The lease expired without a provider receipt.  Retrying the create
        # could duplicate a privileged calendar copy, while clearing the
        # credential could make an already-created copy impossible to remove.
        # Preserve both the row and bounded encrypted revocation credential in
        # a typed manual-repair state.
        sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
        sync.last_error = "Calendar provider upsert outcome is unknown."
        sync.next_attempt_at = None
        sync.dead_letter_reason = CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        sync.durable_last_attempt_at = now
        session.add(sync)
        if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
            _recompute_ip_calendar_projection_status(
                session,
                company_id=context.company.id,
                matter_deadline_id=source_id,
            )
        record_from_context(
            session,
            context,
            action="calendar.sync.claim_expired",
            target_type="calendar_event_sync",
            target_id=sync.id,
            result="failed",
            metadata={
                "provider": connection.provider if connection is not None else None,
                "source_type": sync.source_type,
                "source_ref": redact_identifier(sync.source_id),
                "credential_retained_for_repair": bool(
                    connection is not None and connection.encrypted_token_ref
                ),
            },
        )
        _maybe_clear_revoked_calendar_credential(
            session,
            connection=connection,
        )
        session.commit()
        return "dead_lettered", False
    if not provider_event_id:
        sync.sync_status = CalendarEventSyncStatus.DELETED
        sync.last_error = None
        sync.last_synced_at = now
        sync.next_attempt_at = None
        sync.dead_letter_reason = None
        sync.durable_last_attempt_at = now
        session.add(sync)
        if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
            _recompute_ip_calendar_projection_status(
                session,
                company_id=context.company.id,
                matter_deadline_id=source_id,
            )
        _maybe_clear_revoked_calendar_credential(
            session,
            connection=connection,
        )
        session.commit()
        return "deleted", False

    claim_marker = _calendar_claim_marker(_CALENDAR_DELETE_CLAIM_PREFIX)
    provider: OutlookProvider | None = None
    token_payload: dict[str, Any] | None = None
    claim_error: Exception | None = None
    try:
        if connection is None:
            raise CalendarProviderError("Calendar connection no longer exists.")
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        provider = _provider_for(
            CalendarProvider(connection.provider),
            session,
            context=context,
        )
    except Exception as exc:  # noqa: BLE001 - credential/provider boundary
        claim_error = exc

    if claim_error is None:
        sync.dead_letter_reason = claim_marker
        sync.next_attempt_at = now + _CALENDAR_PROVIDER_LEASE
        sync.durable_last_attempt_at = now
        session.add(sync)
        session.commit()
        assert provider is not None and token_payload is not None
        try:
            provider.delete_event(
                token_payload=token_payload,
                provider_event_id=provider_event_id,
            )
        except Exception as exc:  # noqa: BLE001 - provider/network boundary
            provider_error: Exception | None = exc
        else:
            provider_error = None
    else:
        provider_error = claim_error

    # Canonical finalize order remains sync -> connection.  A stale callback
    # can observe a terminal/replaced row, but it can never revive it. For a
    # deadline projection, reacquire its parent family first: the claim commit
    # released those locks before provider I/O.
    _lock_calendar_projection_source_parent(
        session,
        company_id=context.company.id,
        source_type=source_type,
        source_id=source_id,
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
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == expected_connection_id,
            UserCalendarConnection.company_id == context.company.id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if sync is None:
        session.rollback()
        return "skipped", claim_error is None
    if claim_error is None and (
        sync.sync_status != CalendarEventSyncStatus.DELETE_PENDING
        or sync.provider_event_id != provider_event_id
        or sync.dead_letter_reason != claim_marker
    ):
        session.rollback()
        return "skipped", True

    completed_at = _current_time()
    if provider_error is None:
        sync.sync_status = CalendarEventSyncStatus.DELETED
        sync.last_error = None
        sync.last_synced_at = completed_at
        sync.next_attempt_at = None
        sync.dead_letter_reason = None
        sync.durable_last_attempt_at = completed_at
        if connection is not None:
            connection.last_sync_at = completed_at
            session.add(connection)
        outcome = "deleted"
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
    else:
        sync.attempts = min(sync.attempts + 1, sync.max_attempts)
        sync.last_error = redact_provider_error(provider_error)
        sync.durable_last_attempt_at = completed_at
        if sync.attempts >= sync.max_attempts:
            sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
            sync.next_attempt_at = None
            sync.dead_letter_reason = "provider_delete_retry_limit_exhausted"
            outcome = "dead_lettered"
        else:
            sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
            sync.next_attempt_at = completed_at + retry_delay_for_attempt(sync.attempts)
            sync.dead_letter_reason = "provider_delete_retry_scheduled"
            outcome = "retry_scheduled"
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
    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=source_id,
        )
    _maybe_clear_revoked_calendar_credential(
        session,
        connection=connection,
    )
    session.commit()
    return outcome, claim_error is None


def _recompute_ip_calendar_projection_status(
    session: Session,
    *,
    company_id: str,
    matter_deadline_id: str,
) -> str | None:
    """Derive coverage projection state from every current provider row.

    Coverage cutover creates/tombstones durable work, but it cannot claim the
    provider side is complete. Provider upsert and deletion workers call this
    after each result so ``projected`` means every connected responsible or
    backup calendar is synced and every other historical copy is deleted.
    """

    session.flush()
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == matter_deadline_id,
            MatterDeadline.company_id == company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    if deadline is None:
        return None
    coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.matter_deadline_id == matter_deadline_id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    )
    operational = [
        row
        for row in coverages
        if str(row.coverage_status) in _IP_OPERATIONAL_COVERAGE_STATUSES
    ]
    if not operational:
        return None

    sync_rows = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == company_id,
                CalendarEventSync.source_type
                == CalendarSyncSourceType.MATTER_DEADLINE.value,
                CalendarEventSync.source_id == matter_deadline_id,
            )
            .order_by(CalendarEventSync.calendar_connection_id, CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    desired_membership_ids = {
        membership_id
        for row in operational
        for membership_id in (
            row.responsible_membership_id,
            row.backup_membership_id,
        )
        if membership_id is not None
    }
    role_connection_ids = set(
        session.scalars(
            select(UserCalendarConnection.id).where(
                UserCalendarConnection.company_id == company_id,
                UserCalendarConnection.membership_id.in_(
                    sorted(desired_membership_ids)
                ),
            )
        ).all()
    )
    connection_ids = sorted(
        role_connection_ids
        | {row.calendar_connection_id for row in sync_rows}
    )
    connections = (
        list(
            session.scalars(
                select(UserCalendarConnection)
                .where(
                    UserCalendarConnection.company_id == company_id,
                    UserCalendarConnection.id.in_(connection_ids),
                )
                .order_by(UserCalendarConnection.id)
                .with_for_update(of=UserCalendarConnection)
                .execution_options(populate_existing=True)
            ).all()
        )
        if connection_ids
        else []
    )

    # Shared operational coverage is not supported by this projection slice.
    # Never let a provider completion accidentally turn an ambiguous group
    # projection green.
    if len(operational) != 1:
        for row in operational:
            row.calendar_projection_status = "pending"
            session.add(row)
        session.flush()
        return "pending"

    coverage = operational[0]
    desired_memberships = {
        membership_id
        for membership_id in (
            coverage.responsible_membership_id,
            coverage.backup_membership_id,
        )
        if membership_id is not None
    }
    desired_connection_ids = {
        row.id
        for row in connections
        if row.membership_id in desired_memberships
        and row.status == CalendarConnectionStatus.CONNECTED
    }
    sync_by_connection = {row.calendar_connection_id: row for row in sync_rows}
    projected = all(
        connection_id in sync_by_connection
        and sync_by_connection[connection_id].sync_status
        == CalendarEventSyncStatus.SYNCED
        for connection_id in desired_connection_ids
    ) and all(
        row.sync_status == CalendarEventSyncStatus.DELETED
        for row in sync_rows
        if row.calendar_connection_id not in desired_connection_ids
    )
    coverage.calendar_projection_status = "projected" if projected else "pending"
    session.add(coverage)
    session.flush()
    return coverage.calendar_projection_status


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
        select(
            CalendarEventSync.id,
            CalendarEventSync.calendar_connection_id,
        )
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
    candidates = list(session.execute(stmt).all())
    counters = {
        "examined": 0,
        "deleted": 0,
        "retry_scheduled": 0,
        "dead_lettered": 0,
        "provider_calls": 0,
    }

    # Candidate discovery must not accidentally keep a read transaction open
    # across the first provider callback.
    session.commit()
    for sync_id, expected_connection_id in candidates:
        outcome, provider_called = _process_calendar_deletion_tombstone_by_id(
            session,
            context=context,
            sync_id=sync_id,
            expected_connection_id=expected_connection_id,
        )
        if outcome == "skipped":
            continue
        counters["examined"] += 1
        counters["provider_calls"] += int(provider_called)
        if outcome == "deleted":
            counters["deleted"] += 1
        elif outcome == "retry_scheduled":
            counters["retry_scheduled"] += 1
        elif outcome == "dead_lettered":
            counters["dead_lettered"] += 1

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


def _record_calendar_sync_retry_failure_fenced(
    session: Session,
    *,
    sync: CalendarEventSync,
    context: SessionContext,
    raw_error: object,
    calendar_provider: CalendarProvider,
    now: datetime | None,
) -> str:
    """Retry only the exact post-finalize generation under canonical locks."""

    current_time = now or _current_time()
    sync_id = sync.id
    company_id = sync.company_id
    connection_id = sync.calendar_connection_id
    source_type = str(sync.source_type)
    source_id = sync.source_id
    expected_sync = (
        str(sync.sync_status),
        sync.dead_letter_reason,
        sync.provider_event_id,
        _aware(sync.updated_at),
        sync.neutralized_by_ip_lifecycle_event_id,
        sync.neutralized_by_ip_lifecycle_version,
        sync.neutralized_at,
    )
    source_model = _calendar_source_model(source_type)
    advisory_source = session.scalar(
        select(source_model).where(
            source_model.id == source_id,
            source_model.company_id == company_id,
        )
    )
    # Calendar children do not share one timestamp contract (MatterHearing,
    # for example, has no ``updated_at``). Fence the retry write with the same
    # exact mapped generation used by the provider-finalize path instead of a
    # model-specific timestamp guess.
    expected_source_values = _mapped_values(advisory_source)
    matter_id = advisory_source.matter_id if advisory_source is not None else None
    connection_membership_id = session.scalar(
        select(UserCalendarConnection.membership_id).where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == company_id,
        )
    )
    session.rollback()
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=company_id,
        membership_ids=(context.membership.id, connection_membership_id),
    )
    connection_membership = (
        memberships.get(connection_membership_id)
        if connection_membership_id is not None
        else None
    )
    capability_authorized = False
    if connection_membership is not None:
        try:
            require_locked_membership_capability(
                session,
                connection_membership,
                "calendar:sync",
            )
            capability_authorized = True
        except HTTPException:
            capability_authorized = False
    matter = (
        session.scalar(
            select(Matter)
            .where(Matter.id == matter_id, Matter.company_id == company_id)
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
        if matter_id is not None
        else None
    )
    _lock_calendar_projection_source_parent(
        session,
        company_id=company_id,
        source_type=source_type,
        source_id=source_id,
    )
    locked_source = session.scalar(
        select(source_model)
        .where(
            source_model.id == source_id,
            source_model.company_id == company_id,
        )
        .with_for_update(of=source_model)
        .execution_options(populate_existing=True)
    )
    locked_sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == company_id,
            CalendarEventSync.calendar_connection_id == connection_id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    locked_connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == company_id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if locked_sync is None:
        session.rollback()
        return "failed"
    current_sync = (
        str(locked_sync.sync_status),
        locked_sync.dead_letter_reason,
        locked_sync.provider_event_id,
        _aware(locked_sync.updated_at),
        locked_sync.neutralized_by_ip_lifecycle_event_id,
        locked_sync.neutralized_by_ip_lifecycle_version,
        locked_sync.neutralized_at,
    )
    source_stable = bool(
        locked_source is not None
        and expected_source_values is not None
        and _mapped_values(locked_source) == expected_source_values
        and matter is not None
        and matter_is_operational(matter)
    )
    if isinstance(locked_source, MatterHearing):
        source_stable = source_stable and locked_source.status in {
            MatterHearingStatus.SCHEDULED,
            MatterHearingStatus.ADJOURNED,
        }
    elif isinstance(locked_source, MatterTask):
        source_stable = source_stable and bool(
            locked_source.due_on is not None
            and locked_source.status
            in {
                MatterTaskStatus.TODO,
                MatterTaskStatus.IN_PROGRESS,
                MatterTaskStatus.BLOCKED,
            }
        )
    elif isinstance(locked_source, MatterDeadline):
        source_stable = source_stable and str(locked_source.status) in {"open", "missed"}
    if (
        current_sync != expected_sync
        or calendar_sync_upsert_claim_state(locked_sync) != "none"
        or locked_sync.sync_status
        in {
            CalendarEventSyncStatus.SYNCED,
            CalendarEventSyncStatus.DELETE_PENDING,
            CalendarEventSyncStatus.DELETED,
        }
        or locked_connection is None
        or locked_connection.status != CalendarConnectionStatus.CONNECTED
        or not capability_authorized
        or not source_stable
    ):
        status_value = str(locked_sync.sync_status)
        session.rollback()
        return status_value
    locked_sync.attempts = min(locked_sync.attempts + 1, locked_sync.max_attempts)
    locked_sync.last_error = redact_provider_error(raw_error)
    locked_sync.durable_last_attempt_at = current_time
    if locked_sync.attempts >= locked_sync.max_attempts:
        locked_sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
        locked_sync.next_attempt_at = None
        locked_sync.dead_letter_reason = "retry_limit_exhausted"
    else:
        locked_sync.sync_status = CalendarEventSyncStatus.RETRY_SCHEDULED
        locked_sync.next_attempt_at = current_time + retry_delay_for_attempt(
            locked_sync.attempts
        )
        locked_sync.dead_letter_reason = None
    session.add(locked_sync)
    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=company_id,
            matter_deadline_id=source_id,
        )
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
        target_id=locked_sync.id,
        result="failed",
        metadata={
            "provider": calendar_provider,
            "source_type": locked_sync.source_type,
            "source_ref": redact_identifier(locked_sync.source_id),
            "sync_status": locked_sync.sync_status,
            "attempts": locked_sync.attempts,
            "max_attempts": locked_sync.max_attempts,
            "retry_scheduled": (
                locked_sync.sync_status == CalendarEventSyncStatus.RETRY_SCHEDULED
            ),
            "dead_lettered": (
                locked_sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
            ),
            "error": locked_sync.last_error,
        },
    )
    session.commit()
    return str(locked_sync.sync_status)


def _record_calendar_sync_retry_failure(
    session: Session,
    *,
    sync: CalendarEventSync,
    context: SessionContext,
    raw_error: object,
    calendar_provider: CalendarProvider = CalendarProvider.OUTLOOK,
    now: datetime | None = None,
) -> str:
    return _record_calendar_sync_retry_failure_fenced(
        session,
        sync=sync,
        context=context,
        raw_error=raw_error,
        calendar_provider=calendar_provider,
        now=now,
    )


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
    if calendar_sync_upsert_claim_state(stored) != "none":
        return str(stored.sync_status)
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
    if calendar_sync_upsert_claim_state(stored) != "none":
        return str(stored.sync_status)
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
                calendar_sync_replay_safe_clause(),
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
            outcome = _process_durable_source_sync(
                session,
                context=connection_context,
                connection=sync.connection,
                source_type=sync.source_type,
                source_id=sync.source_id,
                calendar_provider=CalendarProvider.OUTLOOK,
                replay=True,
            )
        except HTTPException as exc:
            if _dead_letter_invalid_projection_source(
                session,
                context=connection_context,
                connection_id=sync.calendar_connection_id,
                source_type=str(sync.source_type),
                source_id=sync.source_id,
                error=exc,
            ):
                counters["dead_lettered"] += 1
            counters["skipped"] += 1
            continue
        counters["provider_calls"] += 1
        counters["replayed"] += 1
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
    materialized_claims = materialize_expired_calendar_upsert_claims(
        session,
        context=context,
        calendar_provider=CalendarProvider.OUTLOOK,
        limit=limit,
    )
    process_calendar_deletion_tombstones(
        session,
        context=context,
        calendar_provider=CalendarProvider.OUTLOOK,
        limit=limit,
    )
    if replay_failed_only:
        replay_result = _replay_durable_outlook_sync_rows(
            session,
            context=context,
            limit=limit,
        )
        return DurableOutlookSyncProcessResult(
            status=replay_result.status,
            adp20_readiness=replay_result.adp20_readiness,
            missing_config_names=replay_result.missing_config_names,
            missing_approval_keys=replay_result.missing_approval_keys,
            examined=replay_result.examined + materialized_claims,
            synced=replay_result.synced,
            failed=replay_result.failed,
            retry_scheduled=replay_result.retry_scheduled,
            dead_lettered=replay_result.dead_lettered + materialized_claims,
            skipped=replay_result.skipped,
            replayed=replay_result.replayed,
            provider_calls=replay_result.provider_calls,
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
        blocked_result = _durable_sync_blocked_result(
            missing_config_names=status_summary.missing_config_names,
            missing_approval_keys=status_summary.missing_approval_keys,
        )
        return DurableOutlookSyncProcessResult(
            status=blocked_result.status,
            adp20_readiness=blocked_result.adp20_readiness,
            missing_config_names=blocked_result.missing_config_names,
            missing_approval_keys=blocked_result.missing_approval_keys,
            examined=blocked_result.examined + materialized_claims,
            synced=blocked_result.synced,
            failed=blocked_result.failed,
            retry_scheduled=blocked_result.retry_scheduled,
            dead_lettered=blocked_result.dead_lettered + materialized_claims,
            skipped=blocked_result.skipped,
            replayed=blocked_result.replayed,
            provider_calls=blocked_result.provider_calls,
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
        "examined": materialized_claims,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": materialized_claims,
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
        # Coverage cutover writes one exact PENDING row per assigned calendar.
        # Drain those durable legal-deadline rows before the legacy hearing
        # enumeration; never infer a deadline projection merely because its
        # Matter happens to be visible to the calendar owner.
        pending_deadlines = _pending_projection_sources(
            session,
            connection=connection,
            source_types=(CalendarSyncSourceType.MATTER_DEADLINE.value,),
            limit=remaining,
            range_from=range_from,
            range_to=range_to,
        )
        for source_type, source_id in pending_deadlines:
            counters["examined"] += 1
            remaining -= 1
            try:
                item = _source_payload_for(
                    session,
                    context=connection_context,
                    source_type=source_type,
                    source_id=source_id,
                )
                _ip_calendar_authority_for_item(session, item=item)
                if not range_from <= item.occurs_on <= range_to:
                    counters["skipped"] += 1
                    continue
                outcome = _process_durable_source_sync(
                    session,
                    context=connection_context,
                    connection=connection,
                    source_type=source_type,
                    source_id=source_id,
                    calendar_provider=CalendarProvider.OUTLOOK,
                    replay=False,
                )
            except HTTPException as exc:
                # A stale/shared/now-inaccessible projection is isolated to
                # this row and cannot abort the tenant's remaining work.
                if _dead_letter_invalid_projection_source(
                    session,
                    context=connection_context,
                    connection_id=connection.id,
                    source_type=source_type,
                    source_id=source_id,
                    error=exc,
                ):
                    counters["dead_lettered"] += 1
                counters["skipped"] += 1
                continue
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
            "source_types": [
                CalendarSyncSourceType.MATTER_HEARING,
                CalendarSyncSourceType.MATTER_DEADLINE,
            ],
            "unsupported_source_types": [
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
                calendar_sync_replay_safe_clause(),
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
            outcome = _process_durable_source_sync(
                session,
                context=connection_context,
                connection=sync.connection,
                source_type=sync.source_type,
                source_id=sync.source_id,
                calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                replay=True,
            )
        except HTTPException as exc:
            if _dead_letter_invalid_projection_source(
                session,
                context=connection_context,
                connection_id=sync.calendar_connection_id,
                source_type=str(sync.source_type),
                source_id=sync.source_id,
                error=exc,
            ):
                counters["dead_lettered"] += 1
            counters["skipped"] += 1
            continue
        counters["provider_calls"] += 1
        counters["replayed"] += 1
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
    materialized_claims = materialize_expired_calendar_upsert_claims(
        session,
        context=context,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
        limit=limit,
    )
    process_calendar_deletion_tombstones(
        session,
        context=context,
        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
        limit=limit,
    )
    if replay_failed_only:
        replay_result = _replay_durable_google_calendar_sync_rows(
            session,
            context=context,
            limit=limit,
        )
        return DurableOutlookSyncProcessResult(
            status=replay_result.status,
            adp20_readiness=replay_result.adp20_readiness,
            missing_config_names=replay_result.missing_config_names,
            missing_approval_keys=replay_result.missing_approval_keys,
            examined=replay_result.examined + materialized_claims,
            synced=replay_result.synced,
            failed=replay_result.failed,
            retry_scheduled=replay_result.retry_scheduled,
            dead_lettered=replay_result.dead_lettered + materialized_claims,
            skipped=replay_result.skipped,
            replayed=replay_result.replayed,
            provider_calls=replay_result.provider_calls,
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
        blocked_result = _durable_sync_blocked_result(
            missing_config_names=missing,
            missing_approval_keys=[],
        )
        return DurableOutlookSyncProcessResult(
            status=blocked_result.status,
            adp20_readiness=blocked_result.adp20_readiness,
            missing_config_names=blocked_result.missing_config_names,
            missing_approval_keys=blocked_result.missing_approval_keys,
            examined=blocked_result.examined + materialized_claims,
            synced=blocked_result.synced,
            failed=blocked_result.failed,
            retry_scheduled=blocked_result.retry_scheduled,
            dead_lettered=blocked_result.dead_lettered + materialized_claims,
            skipped=blocked_result.skipped,
            replayed=blocked_result.replayed,
            provider_calls=blocked_result.provider_calls,
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
        "examined": materialized_claims,
        "synced": 0,
        "failed": 0,
        "retry_scheduled": 0,
        "dead_lettered": materialized_claims,
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
        # Exact durable deadline rows take priority over legacy enumeration so
        # a busy Matter with a small batch limit cannot starve an accepted IP
        # coverage projection indefinitely.
        durable_source_types = (
            CalendarSyncSourceType.MATTER_DEADLINE.value,
            CalendarSyncSourceType.MATTER_HEARING.value,
            CalendarSyncSourceType.MATTER_TASK.value,
        )
        for source_type in durable_source_types:
            if remaining <= 0:
                break
            if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
                # Legal-deadline calendars are explicit coverage projections.
                # The durable worker drains only their exact PENDING rows; it
                # must not enumerate every Matter-visible deadline and invent
                # new external copies.
                source_rows: list[tuple[CalendarSourcePayload, bool]] = []
                for pending_type, pending_id in _pending_projection_sources(
                    session,
                    connection=connection,
                    source_types=(CalendarSyncSourceType.MATTER_DEADLINE.value,),
                    limit=remaining,
                    range_from=range_from,
                    range_to=range_to,
                ):
                    try:
                        item = _source_payload_for(
                            session,
                            context=connection_context,
                            source_type=pending_type,
                            source_id=pending_id,
                        )
                        _ip_calendar_authority_for_item(session, item=item)
                    except HTTPException as exc:
                        if _dead_letter_invalid_projection_source(
                            session,
                            context=connection_context,
                            connection_id=connection.id,
                            source_type=pending_type,
                            source_id=pending_id,
                            error=exc,
                        ):
                            counters["dead_lettered"] += 1
                        counters["examined"] += 1
                        counters["skipped"] += 1
                        remaining -= 1
                        continue
                    if not range_from <= item.occurs_on <= range_to:
                        counters["examined"] += 1
                        counters["skipped"] += 1
                        remaining -= 1
                        continue
                    source_rows.append((item, True))
            else:
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
                try:
                    outcome = _process_durable_source_sync(
                        session,
                        context=connection_context,
                        connection=connection,
                        source_type=item.source_type,
                        source_id=item.source_id,
                        calendar_provider=CalendarProvider.GOOGLE_CALENDAR,
                        replay=False,
                    )
                except HTTPException as exc:
                    # One stale/shared authority row never aborts unrelated
                    # provider work for the company.
                    if _dead_letter_invalid_projection_source(
                        session,
                        context=connection_context,
                        connection_id=connection.id,
                        source_type=item.source_type,
                        source_id=item.source_id,
                        error=exc,
                    ):
                        counters["dead_lettered"] += 1
                    counters["skipped"] += 1
                    continue
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


def _calendar_connection_has_unresolved_remote_work(
    syncs: list[CalendarEventSync],
) -> bool:
    return any(
        calendar_sync_upsert_claim_state(sync) != "none"
        or (
            sync.provider_event_id is not None
            and sync.sync_status != CalendarEventSyncStatus.DELETED
        )
        or sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING
        or str(sync.dead_letter_reason or "").startswith(
            _CALENDAR_DELETE_CLAIM_PREFIX
        )
        for sync in syncs
    )


def _oauth_claim_from_connection(
    connection: UserCalendarConnection,
) -> tuple[dict[str, Any], str | None, datetime | None]:
    token_payload = (
        _decrypt_token_payload(connection.encrypted_token_ref)
        if connection.encrypted_token_ref
        else {}
    )
    marker = str(token_payload.get(_CALENDAR_OAUTH_CLAIM_KEY) or "") or None
    expiry_raw = token_payload.get(_CALENDAR_OAUTH_CLAIM_EXPIRES_KEY)
    try:
        expires_at = datetime.fromisoformat(str(expiry_raw)) if expiry_raw else None
    except ValueError:
        expires_at = None
    if expires_at is not None:
        expires_at = _aware(expires_at)
    return token_payload, marker, expires_at


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
    actor_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    actor = actor_memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active calendar membership is required.",
        )
    require_locked_membership_capability(session, actor, "calendar:sync")
    context = SessionContext(
        company=context.company,
        membership=actor,
        user=actor.user,
    )
    require_recent_step_up(
        session,
        context=context,
        purpose="calendar_connection_oauth",
    )
    advisory_connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == calendar_provider,
        )
    )
    syncs: list[CalendarEventSync] = []
    if advisory_connection is not None:
        syncs = list(
            session.scalars(
                select(CalendarEventSync)
                .where(
                    CalendarEventSync.company_id == context.company.id,
                    CalendarEventSync.calendar_connection_id
                    == advisory_connection.id,
                )
                .order_by(CalendarEventSync.id)
                .with_for_update(of=CalendarEventSync)
                .execution_options(populate_existing=True)
            ).all()
        )
        connection = session.scalar(
            select(UserCalendarConnection)
            .where(
                UserCalendarConnection.id == advisory_connection.id,
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
                UserCalendarConnection.provider == calendar_provider,
            )
            .with_for_update(of=UserCalendarConnection)
            .execution_options(populate_existing=True)
        )
        if connection is None:  # pragma: no cover - exact advisory identity
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Calendar connection changed; restart OAuth.",
            )
        if _calendar_connection_has_unresolved_remote_work(syncs):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "calendar_connection_cleanup_required",
                    "message": (
                        "Reconcile or drain every prior-account calendar copy "
                        "before reconnecting this provider."
                    ),
                },
            )
        prior_token, prior_claim, prior_claim_expires_at = (
            _oauth_claim_from_connection(connection)
        )
        if (
            prior_claim is not None
            and prior_claim_expires_at is not None
            and prior_claim_expires_at > _current_time()
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "calendar_oauth_exchange_in_flight",
                    "message": "A calendar OAuth exchange is already in flight.",
                },
            )
    else:
        connection = UserCalendarConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=calendar_provider,
            status=CalendarConnectionStatus.ERROR,
        )
        session.add(connection)
        session.flush()
        prior_token = {}
    claim_marker = uuid4().hex
    claim_expires_at = _current_time() + _CALENDAR_PROVIDER_LEASE
    claim_payload = {
        **{
            key: value
            for key, value in prior_token.items()
            if key not in {_CALENDAR_OAUTH_CLAIM_KEY, _CALENDAR_OAUTH_CLAIM_EXPIRES_KEY}
        },
        _CALENDAR_OAUTH_CLAIM_KEY: claim_marker,
        _CALENDAR_OAUTH_CLAIM_EXPIRES_KEY: claim_expires_at.isoformat(),
    }
    connection.status = CalendarConnectionStatus.ERROR
    connection.encrypted_token_ref = _encrypt_token_payload(claim_payload)
    session.add(connection)
    record_from_context(
        session,
        context,
        action="calendar.connection.oauth_claimed",
        target_type="user_calendar_connection",
        target_id=connection.id,
        metadata={"provider": calendar_provider},
    )
    connection_id = connection.id
    session.commit()

    # The provider exchange is intentionally outside every DB transaction.
    exchanged = provider.exchange_code(code=code)
    token_payload = exchanged.get("token_payload")
    if not isinstance(token_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Calendar OAuth provider returned an invalid token response.",
        )

    final_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    final_actor = final_memberships.get(context.membership.id)
    if final_actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active calendar membership is required.",
        )
    require_locked_membership_capability(session, final_actor, "calendar:sync")
    context = SessionContext(
        company=context.company,
        membership=final_actor,
        user=final_actor.user,
    )
    require_recent_step_up(
        session,
        context=context,
        purpose="calendar_connection_oauth",
    )
    syncs = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == context.company.id,
                CalendarEventSync.calendar_connection_id == connection_id,
            )
            .order_by(CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == calendar_provider,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Calendar connection changed during OAuth; restart the connection.",
        )
    _, final_claim, _ = _oauth_claim_from_connection(connection)
    if (
        connection.status != CalendarConnectionStatus.ERROR
        or final_claim != claim_marker
        or _calendar_connection_has_unresolved_remote_work(syncs)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "calendar_oauth_finalize_stale",
                "message": (
                    "Calendar authority or cleanup state changed during OAuth; "
                    "the exchanged credential was discarded."
                ),
            },
        )
    now = datetime.now(UTC)
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
    advisory_connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
        )
    )
    if advisory_connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar connection not found.",
        )
    actor_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    actor = actor_memberships.get(context.membership.id)
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active calendar membership is required.",
        )
    require_locked_membership_capability(session, actor, "calendar:sync")
    context = SessionContext(
        company=context.company,
        membership=actor,
        user=actor.user,
    )
    require_recent_step_up(
        session,
        context=context,
        purpose="connector_disconnect",
    )
    # Canonical order is sync -> connection. Queue every known remote copy
    # before revoking, and retain the encrypted credential until those exact
    # deletes drain. An in-flight upsert claim is also fenced: its callback can
    # only publish DELETE_PENDING and cannot restore CONNECTED/SYNCED state.
    syncs = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == context.company.id,
                CalendarEventSync.calendar_connection_id == connection_id,
            )
            .order_by(CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar connection not found.",
        )
    now = _current_time()
    queued_deletes = 0
    for sync in syncs:
        claim_state = calendar_sync_upsert_claim_state(sync, now=now)
        if claim_state == "expired":
            if _materialize_expired_unreceipted_upsert_claim(
                session,
                context=context,
                sync=sync,
                calendar_provider=connection.provider,
                now=now,
            ):
                sync.updated_at = now
            continue
        if claim_state in {"live", "manual_reconciliation"}:
            # Preserve the durable unknown-outcome tombstone. Without a
            # receipt or verified absence, revocation cannot truthfully mark
            # it deleted or discard the only remaining cleanup credential.
            session.add(sync)
            continue
        upsert_claimed = str(sync.dead_letter_reason or "").startswith(
            _CALENDAR_UPSERT_CLAIM_PREFIX
        )
        if upsert_claimed:
            # A known-ID update is not an ambiguous create. Revoke can safely
            # queue the exact provider id immediately; a stale PATCH finalize
            # cannot replace this tombstone because its claim marker is gone.
            sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
            sync.next_attempt_at = now
            sync.dead_letter_reason = "connection_revoked_delete"
            queued_deletes += 1
        elif sync.provider_event_id is not None:
            sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
            sync.next_attempt_at = now
            sync.dead_letter_reason = "connection_revoked_delete"
            queued_deletes += 1
        else:
            sync.sync_status = CalendarEventSyncStatus.DELETED
            sync.next_attempt_at = None
            sync.dead_letter_reason = None
        sync.updated_at = now
        session.add(sync)
    connection.status = CalendarConnectionStatus.REVOKED
    session.add(connection)
    _maybe_clear_revoked_calendar_credential(session, connection=connection)
    record_from_context(
        session,
        context,
        action="calendar.connection.revoked",
        target_type="user_calendar_connection",
        target_id=connection.id,
        metadata={
            "provider": connection.provider,
            "queued_remote_deletes": queued_deletes,
            "credential_retained_for_delete": bool(connection.encrypted_token_ref),
        },
    )
    session.commit()
    return _connection_record(connection)


def reconcile_calendar_unknown_outcome(
    session: Session,
    *,
    context: SessionContext,
    sync_id: str,
    action: Literal["attach_remote_event", "attest_remote_absence"],
    expected_updated_at: datetime,
    expected_status: str,
    expected_dead_letter_reason: str,
    expected_provider: str,
    expected_connection_id: str,
    expected_source_type: str,
    expected_source_id: str,
    evidence_reference: str,
    provider_event_id: str | None,
) -> CalendarEventSync:
    """Resolve one ambiguous provider create using independently verified evidence.

    This command never calls the provider. It records the operator's exact
    evidence under the normal canonical parent -> source -> Sync -> Connection
    lock chain, then either drains a verified remote id or closes a verified
    absence. Generic replay/resolve APIs deliberately cannot perform this
    transition.
    """

    evidence = evidence_reference.strip()
    if len(evidence) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A non-empty reconciliation evidence reference is required.",
        )
    advisory = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
        )
    )
    if advisory is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    advisory_connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.id == advisory.calendar_connection_id,
            UserCalendarConnection.company_id == context.company.id,
        )
    )
    source_model = _calendar_source_model(str(advisory.source_type))
    advisory_source = session.scalar(
        select(source_model).where(
            source_model.id == advisory.source_id,
            source_model.company_id == context.company.id,
        )
    )
    matter_ids: set[str] = set()
    docket_ids: set[str] = set()
    ip_deadline_ids: set[str] = set()
    if advisory_source is not None:
        matter_id = getattr(advisory_source, "matter_id", None)
        docket_id = getattr(advisory_source, "ip_docket_id", None)
        if matter_id:
            matter_ids.add(str(matter_id))
        if docket_id:
            docket_ids.add(str(docket_id))
    if isinstance(advisory_source, MatterDeadline):
        advisory_coverages = list(
            session.scalars(
                select(IpDeadlineCoverage).where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id == advisory.source_id,
                )
            ).all()
        )
        docket_ids.update(row.docket_id for row in advisory_coverages)
        if (
            advisory_source.source_ref_type == "ip_deadline"
            and advisory_source.source_ref_id
        ):
            ip_deadline_ids.add(advisory_source.source_ref_id)
    if docket_ids:
        advisory_dockets = list(
            session.scalars(
                select(IpDocketRecord).where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(sorted(docket_ids)),
                )
            ).all()
        )
        matter_ids.update(
            row.matter_id for row in advisory_dockets if row.matter_id is not None
        )
    owner_membership_id = (
        advisory_connection.membership_id
        if advisory_connection is not None
        else context.membership.id
    )
    session.rollback()

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id, owner_membership_id),
    )
    actor = memberships.get(context.membership.id)
    if actor is None:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Capability 'ip:approve' is required.",
        )
    require_locked_membership_capability(session, actor, "ip:approve")
    context = SessionContext(
        company=context.company,
        membership=actor,
        user=actor.user,
    )
    require_recent_step_up(
        session,
        context=context,
        purpose="calendar_unknown_outcome_reconciliation",
    )
    if matter_ids:
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(sorted(matter_ids)),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
    if docket_ids:
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.id.in_(sorted(docket_ids)),
                )
                .order_by(IpDocketRecord.id)
                .with_for_update(of=IpDocketRecord)
                .execution_options(populate_existing=True)
            ).all()
        )
    if ip_deadline_ids:
        list(
            session.scalars(
                select(IpDeadline)
                .where(
                    IpDeadline.company_id == context.company.id,
                    IpDeadline.id.in_(sorted(ip_deadline_ids)),
                )
                .order_by(IpDeadline.id)
                .with_for_update(of=IpDeadline)
                .execution_options(populate_existing=True)
            ).all()
        )
    locked_source = session.scalar(
        select(source_model)
        .where(
            source_model.id == expected_source_id,
            source_model.company_id == context.company.id,
        )
        .with_for_update(of=source_model)
        .execution_options(populate_existing=True)
    )
    if expected_source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id == expected_source_id,
                )
                .order_by(IpDeadlineCoverage.id)
                .with_for_update(of=IpDeadlineCoverage)
                .execution_options(populate_existing=True)
            ).all()
        )
    row = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == expected_connection_id,
            UserCalendarConnection.company_id == context.company.id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    if row is None or connection is None or locked_source is None:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Calendar reconciliation target changed. Refresh and retry.",
        )
    expected_time = _aware(expected_updated_at)
    current_time = _aware(row.updated_at)
    claim_state = calendar_sync_upsert_claim_state(row)
    logical_status = (
        str(CalendarEventSyncStatus.DEAD_LETTER)
        if claim_state == "expired"
        else str(row.sync_status)
    )
    logical_reason = (
        CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        if claim_state == "expired"
        else row.dead_letter_reason
    )
    matches_expected = bool(
        row.calendar_connection_id == expected_connection_id
        and str(connection.provider) == expected_provider
        and str(row.source_type) == expected_source_type
        and row.source_id == expected_source_id
        and logical_status == expected_status
        and logical_reason == expected_dead_letter_reason
        and current_time == expected_time
    )
    if not matches_expected:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "calendar_reconciliation_stale_state",
                "message": "Calendar reconciliation target changed. Refresh and retry.",
            },
        )
    if claim_state == "expired":
        materialize_expired_calendar_sync_upsert_claim(row)
        session.add(row)
    if not calendar_sync_requires_manual_reconciliation(row):
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "calendar_reconciliation_invalid_state",
                "message": "Only an unknown calendar create outcome can be reconciled.",
            },
        )
    now = _current_time()
    if action == "attach_remote_event":
        exact_remote_id = str(provider_event_id or "").strip()
        if not exact_remote_id:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A verified provider event id is required.",
            )
        row.provider_event_id = exact_remote_id
        row.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        row.dead_letter_reason = "manual_reconciliation_remote_event_attached"
        row.last_error = None
        row.next_attempt_at = now
    elif action == "attest_remote_absence":
        if provider_event_id is not None:
            session.rollback()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="A provider event id is not allowed for an absence attestation.",
            )
        row.provider_event_id = None
        row.sync_status = CalendarEventSyncStatus.DELETED
        row.dead_letter_reason = None
        row.last_error = None
        row.next_attempt_at = None
        row.last_synced_at = now
    else:  # pragma: no cover - schema and type boundary
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Unsupported calendar reconciliation action.",
        )
    row.durable_last_attempt_at = now
    row.updated_at = now
    session.add(row)
    if row.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=row.source_id,
        )
    _maybe_clear_revoked_calendar_credential(session, connection=connection)
    record_from_context(
        session,
        context,
        action="calendar.sync.unknown_outcome_reconciled",
        target_type="calendar_event_sync",
        target_id=row.id,
        metadata={
            "provider": str(connection.provider),
            "reconciliation_action": action,
            "source_type": str(row.source_type),
            "source_ref": redact_identifier(row.source_id),
            "evidence_reference": evidence,
            "remote_event_attached": action == "attach_remote_event",
        },
    )
    session.commit()
    return row


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


def _ip_calendar_authority_for_item(
    session: Session,
    *,
    item: CalendarSourcePayload,
) -> _IpCalendarProjectionAuthority | None:
    if item.ip_docket is None:
        return None
    ip_deadline_id: str | None = None
    coverage_id: str | None = None
    matter_deadline_id: str | None = None
    if item.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        matter_deadline_id = item.source_id
        ip_deadline_id = session.scalar(
            select(IpDeadline.id).where(
                IpDeadline.company_id == item.ip_docket.company_id,
                IpDeadline.docket_id == item.ip_docket.id,
                IpDeadline.matter_deadline_id == item.source_id,
            )
        )
        operational_coverages = list(
            session.execute(
                select(IpDeadlineCoverage.id, IpDeadlineCoverage.docket_id)
                .where(
                    IpDeadlineCoverage.company_id == item.ip_docket.company_id,
                    IpDeadlineCoverage.matter_deadline_id == item.source_id,
                    IpDeadlineCoverage.coverage_status.in_(
                        sorted(_IP_OPERATIONAL_COVERAGE_STATUSES)
                    ),
                )
                .order_by(IpDeadlineCoverage.id)
            ).all()
        )
        if len(operational_coverages) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ip_coverage_projection_shared_deadline_unsupported",
                    "message": (
                        "A deadline shared by multiple operational IP dockets "
                        "requires a group calendar projection."
                    ),
                    "matter_deadline_id": item.source_id,
                    "blocked_coverage_ids": [
                        row.id for row in operational_coverages
                    ],
                    "blocked_docket_ids": sorted(
                        {row.docket_id for row in operational_coverages}
                    ),
                },
            )
        if operational_coverages:
            only_coverage = operational_coverages[0]
            if only_coverage.docket_id != item.ip_docket.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "ip_calendar_projection_coverage_mismatch",
                        "message": (
                            "The deadline coverage belongs to a different IP docket."
                        ),
                        "matter_deadline_id": item.source_id,
                    },
                )
            coverage_id = only_coverage.id
    return _IpCalendarProjectionAuthority(
        source_type=item.source_type,
        source_id=item.source_id,
        docket_id=item.ip_docket.id,
        ip_deadline_id=ip_deadline_id,
        matter_deadline_id=matter_deadline_id,
        coverage_id=coverage_id,
    )


def _pending_projection_sources(
    session: Session,
    *,
    connection: UserCalendarConnection,
    source_types: tuple[str, ...],
    limit: int,
    range_from: date | None = None,
    range_to: date | None = None,
) -> list[tuple[str, str]]:
    """Return exact durable projection rows; never synthesize legal work."""

    if limit <= 0:
        return []
    statement = select(
        CalendarEventSync.source_type,
        CalendarEventSync.source_id,
    ).where(
        CalendarEventSync.company_id == connection.company_id,
        CalendarEventSync.calendar_connection_id == connection.id,
        CalendarEventSync.source_type.in_(source_types),
        CalendarEventSync.sync_status == CalendarEventSyncStatus.PENDING,
        or_(
            CalendarEventSync.next_attempt_at.is_(None),
            CalendarEventSync.next_attempt_at <= _current_time(),
        ),
    )
    if range_from is not None and range_to is not None:
        # Apply exact-source date eligibility before LIMIT. Otherwise one old
        # durable deadline can consume every bounded batch forever while a
        # later in-range projection never reaches the provider.
        statement = statement.where(
            or_(
                and_(
                    CalendarEventSync.source_type
                    == CalendarSyncSourceType.MATTER_HEARING.value,
                    select(MatterHearing.id)
                    .where(
                        MatterHearing.id == CalendarEventSync.source_id,
                        MatterHearing.company_id == connection.company_id,
                        MatterHearing.hearing_on >= range_from,
                        MatterHearing.hearing_on <= range_to,
                    )
                    .exists(),
                ),
                and_(
                    CalendarEventSync.source_type
                    == CalendarSyncSourceType.MATTER_TASK.value,
                    select(MatterTask.id)
                    .where(
                        MatterTask.id == CalendarEventSync.source_id,
                        MatterTask.company_id == connection.company_id,
                        MatterTask.due_on >= range_from,
                        MatterTask.due_on <= range_to,
                    )
                    .exists(),
                ),
                and_(
                    CalendarEventSync.source_type
                    == CalendarSyncSourceType.MATTER_DEADLINE.value,
                    select(MatterDeadline.id)
                    .where(
                        MatterDeadline.id == CalendarEventSync.source_id,
                        MatterDeadline.company_id == connection.company_id,
                        MatterDeadline.due_on >= range_from,
                        MatterDeadline.due_on <= range_to,
                    )
                    .exists(),
                ),
            )
        )
    return [
        (str(source_type), str(source_id))
        for source_type, source_id in session.execute(
            statement.order_by(CalendarEventSync.created_at, CalendarEventSync.id).limit(
                limit
            )
        ).all()
    ]


def _dead_letter_invalid_projection_source(
    session: Session,
    *,
    context: SessionContext,
    connection_id: str,
    source_type: str,
    source_id: str,
    error: HTTPException,
) -> bool:
    """Remove one poison durable row while preserving a repairable history."""

    # `_source_payload_for` performed advisory reads before raising. Release
    # that transaction, then follow the same parent -> Sync ordering as
    # coverage cutover and provider finalization.
    session.rollback()
    lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(context.membership.id,),
    )
    _lock_calendar_projection_source_parent(
        session,
        company_id=context.company.id,
        source_type=source_type,
        source_id=source_id,
    )
    sync = session.scalar(
        select(CalendarEventSync)
        .where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection_id,
            CalendarEventSync.source_type == source_type,
            CalendarEventSync.source_id == source_id,
        )
        .with_for_update(of=CalendarEventSync)
        .execution_options(populate_existing=True)
    )
    if sync is None or sync.sync_status in {
        CalendarEventSyncStatus.SYNCED,
        CalendarEventSyncStatus.DELETED,
        CalendarEventSyncStatus.DELETE_PENDING,
    }:
        session.rollback()
        return False
    if calendar_sync_has_unreceipted_upsert_claim(sync):
        if _materialize_expired_unreceipted_upsert_claim(
            session,
            context=context,
            sync=sync,
            calendar_provider=sync.connection.provider,
        ):
            session.commit()
            return True
        # A still-live claim belongs to the provider worker. Never replace its
        # receipt fence with an authority poison reason.
        session.rollback()
        return False
    detail = error.detail
    code = (
        str(detail.get("code") or f"http_{error.status_code}")
        if isinstance(detail, dict)
        else f"http_{error.status_code}"
    )
    now = _current_time()
    sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
    sync.dead_letter_reason = f"projection_authority_invalid:{code}"[:120]
    sync.last_error = redact_provider_error(code)
    sync.next_attempt_at = None
    sync.durable_last_attempt_at = now
    session.add(sync)
    if source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=source_id,
        )
    record_from_context(
        session,
        context,
        action="calendar.projection.authority_invalid",
        target_type="calendar_event_sync",
        target_id=sync.id,
        result="denied",
        metadata={
            "source_type": source_type,
            "source_ref": redact_identifier(source_id),
            "reason": code,
        },
    )
    session.commit()
    return True


def _assert_initial_ip_calendar_assignment(
    session: Session,
    *,
    authority: _IpCalendarProjectionAuthority | None,
    connection: UserCalendarConnection,
) -> None:
    if authority is None or authority.coverage_id is None:
        return
    coverage = session.scalar(
        select(IpDeadlineCoverage).where(
            IpDeadlineCoverage.id == authority.coverage_id,
            IpDeadlineCoverage.docket_id == authority.docket_id,
            IpDeadlineCoverage.matter_deadline_id == authority.matter_deadline_id,
        )
    )
    if coverage is None or connection.membership_id not in {
        coverage.responsible_membership_id,
        coverage.backup_membership_id,
    }:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This calendar connection is not assigned to the IP deadline.",
        )


def _post_provider_deletion_winner(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str | None,
    expected_lifecycle_version: int | None,
    expected_source_snapshot: _CalendarSourceSnapshot,
    ip_authority: _IpCalendarProjectionAuthority | None,
    sync_id: str,
    connection: UserCalendarConnection,
    calendar_provider: CalendarProvider,
    provider: OutlookProvider | None,
    token_payload: dict[str, Any] | None,
    returned_provider_event_id: str | None,
    claim_marker: str | None = None,
) -> CalendarEventSyncResponse | None:
    """Reauthorize source, assignee, connection, and tombstone after provider I/O."""

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(connection.membership_id,),
    )
    recipient = memberships.get(connection.membership_id)
    recipient_user = recipient.user if recipient is not None else None
    recipient_has_sync_capability = False
    if (
        recipient is not None
        and recipient_user is not None
        and recipient.is_active
        and recipient_user.is_active
    ):
        try:
            require_locked_membership_capability(
                session,
                recipient,
                "calendar:sync",
            )
            recipient_has_sync_capability = True
        except HTTPException:
            # Capability loss must win against disclosure/finalization, while
            # this same locked path must still persist cleanup/UNKNOWN state.
            recipient_has_sync_capability = False
    advisory_docket = (
        session.scalar(
            select(IpDocketRecord).where(
                IpDocketRecord.id == ip_authority.docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
        )
        if ip_authority is not None
        else None
    )
    matter_ids = sorted(
        {
            value
            for value in (
                matter_id,
                advisory_docket.matter_id if advisory_docket is not None else None,
            )
            if value is not None
        }
    )
    matters = (
        list(
            session.scalars(
                select(Matter)
                .where(
                    Matter.company_id == context.company.id,
                    Matter.id.in_(matter_ids),
                )
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            ).all()
        )
        if matter_ids
        else []
    )
    matter_by_id = {row.id: row for row in matters}
    matter = matter_by_id.get(matter_id) if matter_id is not None else None
    docket = (
        session.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == ip_authority.docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
            .with_for_update(of=IpDocketRecord)
            .execution_options(populate_existing=True)
        )
        if ip_authority is not None
        else None
    )
    ip_deadline = (
        session.scalar(
            select(IpDeadline)
            .where(
                IpDeadline.id == ip_authority.ip_deadline_id,
                IpDeadline.company_id == context.company.id,
                IpDeadline.docket_id == ip_authority.docket_id,
            )
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
        if ip_authority is not None and ip_authority.ip_deadline_id is not None
        else None
    )
    deadline = (
        session.scalar(
            select(MatterDeadline)
            .where(
                MatterDeadline.id == ip_authority.matter_deadline_id,
                MatterDeadline.company_id == context.company.id,
            )
            .with_for_update(of=MatterDeadline)
            .execution_options(populate_existing=True)
        )
        if ip_authority is not None and ip_authority.matter_deadline_id is not None
        else None
    )
    source_model = _calendar_source_model(expected_source_snapshot.source_type)
    source_row: MatterHearing | MatterTask | MatterDeadline | None
    if (
        source_model is MatterDeadline
        and deadline is not None
        and deadline.id == expected_source_snapshot.source_id
    ):
        source_row = deadline
    else:
        source_row = session.scalar(
            select(source_model)
            .where(
                source_model.id == expected_source_snapshot.source_id,
                source_model.company_id == context.company.id,
            )
            .with_for_update(of=source_model)
            .execution_options(populate_existing=True)
        )
    coverage_rows = (
        list(
            session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                IpDeadlineCoverage.matter_deadline_id
                == ip_authority.matter_deadline_id,
                IpDeadlineCoverage.coverage_status.in_(
                    sorted(_IP_OPERATIONAL_COVERAGE_STATUSES)
                ),
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
            ).all()
        )
        if ip_authority is not None and ip_authority.matter_deadline_id is not None
        else []
    )
    coverage = next(
        (
            row
            for row in coverage_rows
            if row.id == ip_authority.coverage_id
            and row.docket_id == ip_authority.docket_id
        ),
        None,
    ) if ip_authority is not None and ip_authority.coverage_id is not None else None
    coverage_set_changed = bool(
        ip_authority is not None
        and ip_authority.matter_deadline_id is not None
        and (
            len(coverage_rows) > 1
            or (
                ip_authority.coverage_id is None
                and bool(coverage_rows)
            )
            or (
                ip_authority.coverage_id is not None
                and (
                    len(coverage_rows) != 1
                    or coverage is None
                )
            )
        )
    )
    # Sync precedes connection everywhere, including coverage cutover and the
    # deletion worker.  This avoids a Connection <-> Sync wait cycle.
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
    if (
        claim_marker is None
        and calendar_sync_has_unreceipted_upsert_claim(sync)
    ):
        now = _current_time()
        if _calendar_claim_is_live(
            sync,
            prefix=_CALENDAR_UPSERT_CLAIM_PREFIX,
            now=now,
        ):
            response = CalendarEventSyncResponse(sync=_sync_record(sync))
            session.rollback()
            return response
        if _materialize_expired_unreceipted_upsert_claim(
            session,
            context=context,
            sync=sync,
            calendar_provider=calendar_provider,
            now=now,
        ):
            response = CalendarEventSyncResponse(sync=_sync_record(sync))
            session.commit()
            return response
    stale_claim = bool(
        claim_marker is not None and sync.dead_letter_reason != claim_marker
    )
    locked_connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection.id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == connection.membership_id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )

    deletion_state = sync.sync_status in {
        CalendarEventSyncStatus.DELETE_PENDING,
        CalendarEventSyncStatus.DELETED,
    } or (
        sync.sync_status == CalendarEventSyncStatus.DEAD_LETTER
        and str(sync.dead_letter_reason or "").startswith("provider_delete_")
    )
    lifecycle_changed = bool(
        matter_id is not None
        and (
            matter is None
            or not matter_is_operational(matter)
            or matter.lifecycle_version != expected_lifecycle_version
        )
    )
    authority_lost = bool(
        stale_claim
        or locked_connection is None
        or locked_connection.status != CalendarConnectionStatus.CONNECTED
        or recipient is None
        or recipient_user is None
        or not recipient.is_active
        or not recipient_user.is_active
        or not recipient_has_sync_capability
    )
    source_invalid = source_row is None
    if isinstance(source_row, MatterHearing):
        source_invalid = source_row.status not in {
            MatterHearingStatus.SCHEDULED,
            MatterHearingStatus.ADJOURNED,
        }
    elif isinstance(source_row, MatterTask):
        source_invalid = bool(
            source_row.due_on is None
            or source_row.status
            not in {
                MatterTaskStatus.TODO,
                MatterTaskStatus.IN_PROGRESS,
                MatterTaskStatus.BLOCKED,
            }
        )
    elif isinstance(source_row, MatterDeadline):
        source_invalid = str(source_row.status) not in {"open", "missed"}
    source_changed = bool(
        source_row is None
        or _calendar_source_snapshot(
            source_type=expected_source_snapshot.source_type,
            source_id=expected_source_snapshot.source_id,
            source_row=source_row,
            matter=(
                matter
                if expected_source_snapshot.matter_values is not None
                else None
            ),
            docket=(
                docket
                if expected_source_snapshot.docket_values is not None
                else None
            ),
        )
        != expected_source_snapshot
    )
    authority_lost = authority_lost or source_invalid or source_changed
    recipient_context = (
        SessionContext(
            company=context.company,
            membership=recipient,
            user=recipient_user,
        )
        if recipient is not None and recipient_user is not None
        else None
    )
    if ip_authority is None and matter_id is not None:
        # Membership -> Matter -> exact source -> Sync -> Connection is now
        # locked. Re-evaluate the canonical visibility predicate here so a
        # grant/team/wall writer that committed before this claim wins and no
        # provider disclosure starts from the earlier advisory read.
        authority_lost = authority_lost or bool(
            matter is None
            or recipient_context is None
            or not can_access(
                session,
                context=recipient_context,
                matter=matter,
            )
        )
    if ip_authority is not None:
        linked_matter = (
            matter_by_id.get(docket.matter_id)
            if docket is not None and docket.matter_id is not None
            else None
        )
        authority_lost = authority_lost or bool(
            docket is None
            or not docket.is_active
            or docket.archived_by_matter_disposal
            or source_invalid
            or coverage_set_changed
            or (
                docket.matter_id is not None
                and (linked_matter is None or not matter_is_operational(linked_matter))
            )
            or (
                ip_authority.ip_deadline_id is not None
                and (
                    ip_deadline is None
                    or str(ip_deadline.state) not in {"confirmed", "overdue"}
                    or ip_deadline.matter_deadline_id
                    != ip_authority.matter_deadline_id
                )
            )
            or (
                ip_authority.coverage_id is not None
                and (
                    coverage is None
                    or str(coverage.coverage_status)
                    in {"inactive_lifecycle", "completed"}
                    or locked_connection is None
                    or locked_connection.membership_id
                    not in {
                        coverage.responsible_membership_id,
                        coverage.backup_membership_id,
                    }
                    or deadline is None
                    or deadline.assignee_membership_id
                    != coverage.responsible_membership_id
                )
            )
            or (
                recipient_context is not None
                and docket is not None
                and not can_access_ip_docket(
                    session,
                    context=recipient_context,
                    docket=docket,
                )
            )
            or (
                recipient_context is not None
                and linked_matter is not None
                and not can_access(
                    session,
                    context=recipient_context,
                    matter=linked_matter,
                )
            )
        )
    if not deletion_state and not lifecycle_changed and not authority_lost:
        return None

    now = _current_time()
    cleanup_error: str | None = None
    if returned_provider_event_id:
        # A provider may have created/updated the event after disposal had
        # already written the tombstone. Persist the exact returned artifact
        # before any compensation call. The deletion worker claims and commits
        # this row before doing provider I/O, so a failed compensation can
        # never be lost with the lifecycle transaction.
        sync.provider_event_id = returned_provider_event_id
        sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        sync.last_error = None
        sync.next_attempt_at = now
        sync.dead_letter_reason = "calendar_authority_changed_delete"
        sync.durable_last_attempt_at = now
        if (
            locked_connection is not None
            and locked_connection.encrypted_token_ref is None
            and token_payload is not None
        ):
            # Revocation may have won immediately after the claim. Preserve an
            # encrypted snapshot of the already-authorized credential until
            # this exact returned remote id is deleted.
            locked_connection.encrypted_token_ref = _encrypt_token_payload(
                token_payload
            )
            session.add(locked_connection)
    elif (
        provider is not None
        and claim_marker is not None
        and sync.provider_event_id is None
    ):
        # The provider call ran, but no receipt survived. If authority changed
        # concurrently, claiming that no remote artifact exists would permit
        # revocation to destroy the only cleanup credential. Preserve a typed
        # manual-repair tombstone and the already-authorized token snapshot.
        sync.sync_status = CalendarEventSyncStatus.DEAD_LETTER
        sync.last_error = "Calendar provider upsert outcome is unknown."
        sync.next_attempt_at = None
        sync.dead_letter_reason = CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        sync.durable_last_attempt_at = now
        cleanup_error = "provider_upsert_outcome_unknown"
        if (
            locked_connection is not None
            and locked_connection.encrypted_token_ref is None
            and token_payload is not None
        ):
            locked_connection.encrypted_token_ref = _encrypt_token_payload(
                token_payload
            )
            session.add(locked_connection)
    elif sync.provider_event_id and sync.sync_status != CalendarEventSyncStatus.DELETED:
        # The upsert failed or returned no new id, but a previously-synced
        # remote event still needs the durable worker to remove it.
        sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        sync.next_attempt_at = now
        sync.dead_letter_reason = "calendar_authority_changed_delete"
    elif sync.sync_status != CalendarEventSyncStatus.DELETED:
        sync.sync_status = CalendarEventSyncStatus.DELETED
        sync.last_error = None
        sync.last_synced_at = now
        sync.next_attempt_at = None
        sync.dead_letter_reason = None

    session.add(sync)
    if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=sync.source_id,
        )
    record_from_context(
        session,
        context,
        action="calendar.sync.authority_change_won",
        target_type="calendar_event_sync",
        target_id=sync.id,
        matter_id=(
            matter_id
            or (docket.matter_id if docket is not None else None)
        ),
        ip_docket_id=docket.id if docket is not None else None,
        result="denied" if cleanup_error else "success",
        metadata={
            "provider": calendar_provider,
            "source_type": sync.source_type,
            "source_ref": redact_identifier(sync.source_id),
            "sync_status": sync.sync_status,
            "lifecycle_changed": lifecycle_changed,
            "authority_lost": authority_lost,
            "source_changed": source_changed,
            "stale_claim": stale_claim,
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
    claimed = _classify_existing_upsert_claim_before_source_resolution(
        session,
        context=context,
        source_type=source_type,
        source_id=source_id,
        calendar_provider=calendar_provider,
    )
    if claimed is not None:
        return claimed
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
    ip_authority = _ip_calendar_authority_for_item(session, item=item)
    source_model = _calendar_source_model(item.source_type)
    source_row = session.scalar(
        select(source_model).where(
            source_model.id == item.source_id,
            source_model.company_id == context.company.id,
        )
    )
    if source_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Calendar source not found.",
        )
    source_snapshot = _calendar_source_snapshot(
        source_type=item.source_type,
        source_id=item.source_id,
        source_row=source_row,
        matter=item.matter,
        docket=item.ip_docket,
    )
    _assert_initial_ip_calendar_assignment(
        session,
        authority=ip_authority,
        connection=connection,
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
    sync_id = sync.id
    existing_provider_event_id = sync.provider_event_id
    # Publish the pending row before provider I/O. Coverage/lifecycle writers
    # can now tombstone it without waiting on an uncommitted unique-key insert;
    # the post-provider fence below decides which transaction won.
    session.commit()
    fenced_memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(connection.membership_id,),
    )
    fenced_membership = fenced_memberships.get(connection.membership_id)
    fenced_user = fenced_membership.user if fenced_membership is not None else None
    fenced_context = (
        SessionContext(
            company=context.company,
            membership=fenced_membership,
            user=fenced_user,
        )
        if fenced_membership is not None and fenced_user is not None
        else context
    )
    fresh_connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection.id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == connection.membership_id,
        )
        .execution_options(populate_existing=True)
    )
    pre_provider_authorized = bool(
        fenced_membership is not None
        and fenced_user is not None
        and fenced_membership.is_active
        and fenced_user.is_active
        and fresh_connection is not None
        and fresh_connection.status == CalendarConnectionStatus.CONNECTED
    )
    if pre_provider_authorized and fenced_membership is not None:
        try:
            require_locked_membership_capability(
                session,
                fenced_membership,
                "calendar:sync",
            )
        except HTTPException:
            pre_provider_authorized = False
    if pre_provider_authorized and matter_id is not None:
        fresh_matter = session.scalar(
            select(Matter)
            .where(
                Matter.id == matter_id,
                Matter.company_id == context.company.id,
            )
            .execution_options(populate_existing=True)
        )
        pre_provider_authorized = bool(
            fresh_matter is not None
            and matter_is_operational(fresh_matter)
            and fresh_matter.lifecycle_version == expected_lifecycle_version
            and can_access(session, context=fenced_context, matter=fresh_matter)
        )
    if pre_provider_authorized and ip_authority is not None:
        fresh_docket = session.scalar(
            select(IpDocketRecord)
            .where(
                IpDocketRecord.id == ip_authority.docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
            .execution_options(populate_existing=True)
        )
        pre_provider_authorized = bool(
            fresh_docket is not None
            and fresh_docket.is_active
            and not fresh_docket.archived_by_matter_disposal
            and can_access_ip_docket(
                session,
                context=fenced_context,
                docket=fresh_docket,
            )
        )
        if pre_provider_authorized and fresh_docket is not None and fresh_docket.matter_id:
            fresh_linked_matter = session.scalar(
                select(Matter)
                .where(
                    Matter.id == fresh_docket.matter_id,
                    Matter.company_id == context.company.id,
                )
                .execution_options(populate_existing=True)
            )
            pre_provider_authorized = bool(
                fresh_linked_matter is not None
                and matter_is_operational(fresh_linked_matter)
                and can_access(
                    session,
                    context=fenced_context,
                    matter=fresh_linked_matter,
                )
            )
        fresh_deadline = (
            session.scalar(
                select(MatterDeadline)
                .where(
                    MatterDeadline.id == ip_authority.matter_deadline_id,
                    MatterDeadline.company_id == context.company.id,
                )
                .execution_options(populate_existing=True)
            )
            if pre_provider_authorized
            and ip_authority.matter_deadline_id is not None
            else None
        )
        fresh_ip_deadline = (
            session.scalar(
                select(IpDeadline)
                .where(
                    IpDeadline.id == ip_authority.ip_deadline_id,
                    IpDeadline.company_id == context.company.id,
                    IpDeadline.docket_id == ip_authority.docket_id,
                    IpDeadline.matter_deadline_id
                    == ip_authority.matter_deadline_id,
                )
                .execution_options(populate_existing=True)
            )
            if pre_provider_authorized
            and ip_authority.ip_deadline_id is not None
            else None
        )
        if pre_provider_authorized and ip_authority.matter_deadline_id is not None:
            pre_provider_authorized = bool(
                fresh_deadline is not None
                and str(fresh_deadline.status) in {"open", "missed"}
                and (
                    ip_authority.ip_deadline_id is None
                    or (
                        fresh_ip_deadline is not None
                        and str(fresh_ip_deadline.state) in {"confirmed", "overdue"}
                    )
                )
            )
        if pre_provider_authorized and ip_authority.matter_deadline_id is not None:
            fresh_coverages = list(
                session.scalars(
                    select(IpDeadlineCoverage)
                    .where(
                        IpDeadlineCoverage.company_id == context.company.id,
                        IpDeadlineCoverage.matter_deadline_id
                        == ip_authority.matter_deadline_id,
                        IpDeadlineCoverage.coverage_status.in_(
                            sorted(_IP_OPERATIONAL_COVERAGE_STATUSES)
                        ),
                    )
                    .order_by(IpDeadlineCoverage.id)
                    .execution_options(populate_existing=True)
                ).all()
            )
            fresh_coverage = next(
                (
                    row
                    for row in fresh_coverages
                    if row.id == ip_authority.coverage_id
                    and row.docket_id == ip_authority.docket_id
                ),
                None,
            )
            if ip_authority.coverage_id is None:
                pre_provider_authorized = not fresh_coverages
            else:
                pre_provider_authorized = bool(
                    len(fresh_coverages) == 1
                    and fresh_coverage is not None
                    and fresh_connection is not None
                    and fresh_connection.membership_id
                    in {
                        fresh_coverage.responsible_membership_id,
                        fresh_coverage.backup_membership_id,
                    }
                    and fresh_deadline is not None
                    and fresh_deadline.assignee_membership_id
                    == fresh_coverage.responsible_membership_id
                )
    if not pre_provider_authorized:
        deletion_response = _post_provider_deletion_winner(
            session,
            context=context,
            matter_id=matter_id,
            expected_lifecycle_version=expected_lifecycle_version,
            expected_source_snapshot=source_snapshot,
            ip_authority=ip_authority,
            sync_id=sync_id,
            connection=connection,
            calendar_provider=calendar_provider,
            provider=None,
            token_payload=None,
            returned_provider_event_id=None,
        )
        if deletion_response is None:  # pragma: no cover - locked checks agree
            raise CalendarProviderError("Calendar authority changed before provider call.")
        return deletion_response
    assert fresh_connection is not None

    # Re-run the authoritative check with the full canonical lock chain, then
    # persist a bounded claim.  The commit is the serialization point with
    # lifecycle, coverage, access, employee-deactivation, and connection
    # revocation writers; no lock or transaction survives into provider I/O.
    deletion_response = _post_provider_deletion_winner(
        session,
        context=context,
        matter_id=matter_id,
        expected_lifecycle_version=expected_lifecycle_version,
        expected_source_snapshot=source_snapshot,
        ip_authority=ip_authority,
        sync_id=sync_id,
        connection=connection,
        calendar_provider=calendar_provider,
        provider=None,
        token_payload=None,
        returned_provider_event_id=None,
    )
    if deletion_response is not None:
        return deletion_response
    sync = session.get(CalendarEventSync, sync_id)
    if sync is None:  # pragma: no cover - locked by the authority check
        raise CalendarProviderError("Calendar sync state disappeared before provider call.")
    claim_now = _current_time()
    if _calendar_claim_is_live(
        sync,
        prefix=_CALENDAR_UPSERT_CLAIM_PREFIX,
        now=claim_now,
    ):
        response = CalendarEventSyncResponse(sync=_sync_record(sync))
        session.rollback()
        return response
    if _materialize_expired_unreceipted_upsert_claim(
        session,
        context=context,
        sync=sync,
        calendar_provider=calendar_provider,
        now=claim_now,
    ):
        session.commit()
        return CalendarEventSyncResponse(sync=_sync_record(sync))
    claim_marker = _calendar_claim_marker(_CALENDAR_UPSERT_CLAIM_PREFIX)
    sync.sync_status = CalendarEventSyncStatus.PENDING
    sync.dead_letter_reason = claim_marker
    sync.next_attempt_at = claim_now + _CALENDAR_PROVIDER_LEASE
    sync.durable_last_attempt_at = claim_now
    session.add(sync)
    if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=sync.source_id,
        )
    encrypted_token_ref = fresh_connection.encrypted_token_ref
    provider: OutlookProvider | None = None
    token_payload: dict[str, Any] | None = None
    try:
        token_payload = _decrypt_token_payload(encrypted_token_ref)
        provider = _provider_for(calendar_provider, session, context=context)
    except Exception as exc:
        sync.sync_status = CalendarEventSyncStatus.FAILED
        sync.last_error = _safe_error(exc)
        sync.dead_letter_reason = None
        sync.next_attempt_at = None
        session.add(sync)
        if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
            _recompute_ip_calendar_projection_status(
                session,
                company_id=context.company.id,
                matter_deadline_id=sync.source_id,
            )
        session.commit()
        return CalendarEventSyncResponse(sync=_sync_record(sync))

    # Snapshot every ORM attribute used by provider adapters before commit.
    # Session factories use expire_on_commit=False, and the callback receives
    # no operation that can lazily query the database.
    hearing = (
        session.get(MatterHearing, item.source_id)
        if item.matter is not None
        and item.source_type == CalendarSyncSourceType.MATTER_HEARING.value
        else None
    )
    session.commit()
    try:
        if (
            item.matter is not None
            and item.source_type == CalendarSyncSourceType.MATTER_HEARING.value
            and hasattr(provider, "upsert_hearing_event")
        ):
            if hearing is None:
                raise CalendarProviderError("Hearing disappeared before sync.")
            provider_event_id = provider.upsert_hearing_event(
                token_payload=token_payload,
                hearing=hearing,
                matter=item.matter,
                existing_provider_event_id=existing_provider_event_id,
            )
        else:
            provider_event_id = provider.upsert_calendar_item(
                token_payload=token_payload,
                item=item,
                existing_provider_event_id=existing_provider_event_id,
            )
    except Exception as exc:
        deletion_response = _post_provider_deletion_winner(
            session,
            context=context,
            matter_id=matter_id,
            expected_lifecycle_version=expected_lifecycle_version,
            expected_source_snapshot=source_snapshot,
            ip_authority=ip_authority,
            sync_id=sync_id,
            connection=connection,
            calendar_provider=calendar_provider,
            provider=provider,
            token_payload=token_payload,
            returned_provider_event_id=None,
            claim_marker=claim_marker,
        )
        if deletion_response is not None:
            return deletion_response
        sync = session.get(CalendarEventSync, sync_id)
        if sync is None:  # pragma: no cover - protected by the locked recheck
            raise CalendarProviderError(
                "Calendar sync state disappeared after provider call."
            ) from exc
        sync.sync_status = (
            CalendarEventSyncStatus.DEAD_LETTER
            if existing_provider_event_id is None
            else CalendarEventSyncStatus.FAILED
        )
        sync.last_error = (
            "Calendar provider upsert outcome is unknown."
            if existing_provider_event_id is None
            else _safe_error(exc)
        )
        sync.dead_letter_reason = (
            CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
            if existing_provider_event_id is None
            else None
        )
        sync.next_attempt_at = None
        session.add(sync)
        if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
            _recompute_ip_calendar_projection_status(
                session,
                company_id=context.company.id,
                matter_deadline_id=sync.source_id,
            )
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

    deletion_response = _post_provider_deletion_winner(
        session,
        context=context,
        matter_id=matter_id,
        expected_lifecycle_version=expected_lifecycle_version,
        expected_source_snapshot=source_snapshot,
        ip_authority=ip_authority,
        sync_id=sync_id,
        connection=connection,
        calendar_provider=calendar_provider,
        provider=provider,
        token_payload=token_payload,
        returned_provider_event_id=provider_event_id,
        claim_marker=claim_marker,
    )
    if deletion_response is not None:
        if deletion_response.sync.sync_status == CalendarEventSyncStatus.DELETE_PENDING:
            _process_calendar_deletion_tombstone_by_id(
                session,
                context=context,
                sync_id=sync_id,
                expected_connection_id=connection.id,
            )
            refreshed = session.get(CalendarEventSync, sync_id)
            if refreshed is not None:
                return CalendarEventSyncResponse(sync=_sync_record(refreshed))
        return deletion_response

    # _post_provider_deletion_winner refreshed and locked this row.  Resolve it
    # again from the identity map so the success write targets the fresh state.
    sync = session.get(CalendarEventSync, sync_id)
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
    if sync.source_type == CalendarSyncSourceType.MATTER_DEADLINE.value:
        _recompute_ip_calendar_projection_status(
            session,
            company_id=context.company.id,
            matter_deadline_id=sync.source_id,
        )
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
    sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
    sync.next_attempt_at = _current_time()
    sync.dead_letter_reason = "explicit_hearing_delete"
    session.add(sync)
    session.commit()
    _process_calendar_deletion_tombstone_by_id(
        session,
        context=context,
        sync_id=sync.id,
        expected_connection_id=connection.id,
    )
    refreshed = session.get(CalendarEventSync, sync.id)
    if refreshed is None:  # pragma: no cover - FK-protected row
        raise CalendarProviderError("Calendar sync state disappeared during deletion.")
    if refreshed.sync_status == CalendarEventSyncStatus.DELETED:
        record_from_context(
            session,
            context,
            action="calendar.sync.deleted",
            target_type="calendar_event_sync",
            target_id=refreshed.id,
            matter_id=matter.id,
            metadata={
                "provider": calendar_provider,
                "source_type": CalendarSyncSourceType.MATTER_HEARING,
                "source_id": hearing.id,
                "provider_event_id": refreshed.provider_event_id,
            },
        )
        session.commit()
    return CalendarEventSyncResponse(sync=_sync_record(refreshed))


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
            .order_by(CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        )
    )
    queued: list[tuple[str, str]] = []
    now = _current_time()
    for sync in syncs:
        if not sync.provider_event_id:
            continue
        sync.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        sync.next_attempt_at = now
        sync.dead_letter_reason = "hearing_cancelled_delete"
        sync.updated_at = now
        session.add(sync)
        queued.append((sync.id, sync.calendar_connection_id))
        record_from_context(
            session,
            context,
            action="calendar.sync.auto_delete_queued",
            target_type="calendar_event_sync",
            target_id=sync.id,
            matter_id=matter_id,
            metadata={
                "provider": sync.connection.provider,
                "source_type": CalendarSyncSourceType.MATTER_HEARING,
                "source_id": hearing_id,
                "reason": "hearing_cancelled",
                "provider_event_ref": redact_identifier(sync.provider_event_id),
                **target_metadata,
            },
        )
    if commit:
        session.commit()
        for sync_id, connection_id in queued:
            _process_calendar_deletion_tombstone_by_id(
                session,
                context=context,
                sync_id=sync_id,
                expected_connection_id=connection_id,
            )
    return len(queued)


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


@dataclass(frozen=True, slots=True)
class _CalendarDriftSourceGeneration:
    """Every authority/payload value covered by one provider read claim."""

    source_snapshot: _CalendarSourceSnapshot
    ip_authority: _IpCalendarProjectionAuthority
    linked_matter_values: tuple[tuple[str, object], ...] | None
    coverage_values: tuple[
        tuple[str, tuple[tuple[str, object], ...]], ...
    ]
    ip_deadline_values: tuple[tuple[str, object], ...] | None
    occurs_on: date


@dataclass(frozen=True, slots=True)
class _CalendarDriftClaim:
    """Committed lease and immutable inputs for one provider GET."""

    sync_id: str
    connection_id: str
    owner_membership_id: str
    provider_event_id: str
    claim_marker: str
    source_type: str
    source_id: str
    generation: _CalendarDriftSourceGeneration
    connection_snapshot: tuple[object, ...]
    reader: Any | None


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


def _calendar_drift_source_generation(
    session: Session,
    *,
    context: SessionContext,
    source_type: str,
    source_id: str,
) -> _CalendarDriftSourceGeneration | None:
    """Resolve every exact IP authority value used by one provider read."""

    payload = _source_payload_for(
        session,
        context=context,
        source_type=source_type,
        source_id=source_id,
    )
    if payload.ip_docket is None:
        return None
    source_model = _calendar_source_model(source_type)
    source_row = session.scalar(
        select(source_model).where(
            source_model.id == source_id,
            source_model.company_id == context.company.id,
        )
    )
    if source_row is None:
        return None
    authority = _ip_calendar_authority_for_item(session, item=payload)
    if authority is None:  # pragma: no cover - payload invariant above
        return None
    linked_matter = payload.matter
    if linked_matter is None and payload.ip_docket.matter_id is not None:
        linked_matter = session.scalar(
            select(Matter).where(
                Matter.id == payload.ip_docket.matter_id,
                Matter.company_id == context.company.id,
            )
        )
    coverage_rows = (
        list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id
                    == authority.matter_deadline_id,
                )
                .order_by(IpDeadlineCoverage.id)
            ).all()
        )
        if authority.matter_deadline_id is not None
        else []
    )
    ip_deadline = (
        session.scalar(
            select(IpDeadline).where(
                IpDeadline.id == authority.ip_deadline_id,
                IpDeadline.company_id == context.company.id,
                IpDeadline.docket_id == authority.docket_id,
            )
        )
        if authority.ip_deadline_id is not None
        else None
    )
    return _CalendarDriftSourceGeneration(
        source_snapshot=_calendar_source_snapshot(
            source_type=source_type,
            source_id=source_id,
            source_row=source_row,
            matter=payload.matter,
            docket=payload.ip_docket,
        ),
        ip_authority=authority,
        linked_matter_values=_mapped_values(linked_matter),
        coverage_values=tuple(
            (row.id, _mapped_values(row) or ()) for row in coverage_rows
        ),
        ip_deadline_values=_mapped_values(ip_deadline),
        occurs_on=payload.occurs_on,
    )


def _calendar_drift_connection_snapshot(
    connection: UserCalendarConnection,
) -> tuple[object, ...]:
    return (
        connection.id,
        str(connection.status),
        str(connection.provider),
        connection.provider_account_id,
        _aware(connection.updated_at).isoformat(),
        hashlib.sha256((connection.encrypted_token_ref or "").encode()).hexdigest(),
    )


def _lock_calendar_drift_graph(
    session: Session,
    *,
    context: SessionContext,
    actor_membership_id: str,
    owner_membership_id: str,
    sync_id: str,
    connection_id: str,
    generation: _CalendarDriftSourceGeneration,
) -> tuple[
    CompanyMembership | None,
    CompanyMembership | None,
    CalendarEventSync | None,
    UserCalendarConnection | None,
]:
    """Lock Membership/User -> Matter/docket/source -> Sync -> Connection."""

    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids=(actor_membership_id, owner_membership_id),
    )
    matter_id = dict(generation.linked_matter_values or ()).get("id")
    if matter_id is not None:
        session.scalar(
            select(Matter)
            .where(
                Matter.id == str(matter_id),
                Matter.company_id == context.company.id,
            )
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
    authority = generation.ip_authority
    session.scalar(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.id == authority.docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpDocketRecord)
        .execution_options(populate_existing=True)
    )
    if authority.ip_deadline_id is not None:
        session.scalar(
            select(IpDeadline)
            .where(
                IpDeadline.id == authority.ip_deadline_id,
                IpDeadline.company_id == context.company.id,
            )
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
    source_model = _calendar_source_model(generation.source_snapshot.source_type)
    session.scalar(
        select(source_model)
        .where(
            source_model.id == generation.source_snapshot.source_id,
            source_model.company_id == context.company.id,
        )
        .with_for_update(of=source_model)
        .execution_options(populate_existing=True)
    )
    if authority.matter_deadline_id is not None:
        list(
            session.scalars(
                select(IpDeadlineCoverage)
                .where(
                    IpDeadlineCoverage.company_id == context.company.id,
                    IpDeadlineCoverage.matter_deadline_id
                    == authority.matter_deadline_id,
                )
                .order_by(IpDeadlineCoverage.id)
                .with_for_update(of=IpDeadlineCoverage)
                .execution_options(populate_existing=True)
            ).all()
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
    connection = session.scalar(
        select(UserCalendarConnection)
        .where(
            UserCalendarConnection.id == connection_id,
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == owner_membership_id,
        )
        .with_for_update(of=UserCalendarConnection)
        .execution_options(populate_existing=True)
    )
    return (
        memberships.get(actor_membership_id),
        memberships.get(owner_membership_id),
        sync,
        connection,
    )


def _locked_calendar_membership_authorized(
    session: Session,
    membership: CompanyMembership | None,
) -> bool:
    if membership is None:
        return False
    try:
        require_locked_membership_capability(session, membership, "calendar:sync")
    except HTTPException:
        return False
    return True


def _claim_calendar_drift_read(
    session: Session,
    *,
    context: SessionContext,
    sync_id: str,
) -> _CalendarDriftClaim | None:
    """Persist one read lease after exact source and authority validation."""

    advisory_sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.id == sync_id,
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.sync_status == CalendarEventSyncStatus.SYNCED,
            CalendarEventSync.provider_event_id.is_not(None),
        )
    )
    if advisory_sync is None:
        session.rollback()
        return None
    advisory_connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.id == advisory_sync.calendar_connection_id,
            UserCalendarConnection.company_id == context.company.id,
        )
    )
    if advisory_connection is None:
        session.rollback()
        return None
    try:
        generation = _calendar_drift_source_generation(
            session,
            context=context,
            source_type=str(advisory_sync.source_type),
            source_id=advisory_sync.source_id,
        )
    except HTTPException:
        session.rollback()
        return None
    if generation is None:
        session.rollback()
        return None
    owner_membership_id = advisory_connection.membership_id
    connection_id = advisory_connection.id
    provider_event_id = str(advisory_sync.provider_event_id)
    source_type = str(advisory_sync.source_type)
    source_id = advisory_sync.source_id
    session.rollback()

    actor, owner, sync, connection = _lock_calendar_drift_graph(
        session,
        context=context,
        actor_membership_id=context.membership.id,
        owner_membership_id=owner_membership_id,
        sync_id=sync_id,
        connection_id=connection_id,
        generation=generation,
    )
    if not _locked_calendar_membership_authorized(session, actor):
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Capability 'calendar:sync' is required.",
        )
    assert actor is not None
    actor_context = SessionContext(
        company=context.company,
        membership=actor,
        user=actor.user,
    )
    require_recent_step_up(
        session,
        context=actor_context,
        purpose="calendar_projection_drift_check",
    )
    if (
        not _locked_calendar_membership_authorized(session, owner)
        or sync is None
        or connection is None
        or sync.calendar_connection_id != connection_id
        or str(sync.source_type) != source_type
        or sync.source_id != source_id
        or sync.sync_status != CalendarEventSyncStatus.SYNCED
        or str(sync.provider_event_id or "") != provider_event_id
        or connection.status != CalendarConnectionStatus.CONNECTED
        or not connection.encrypted_token_ref
    ):
        session.rollback()
        return None
    assert owner is not None
    owner_context = SessionContext(
        company=context.company,
        membership=owner,
        user=owner.user,
    )
    try:
        actor_generation = _calendar_drift_source_generation(
            session,
            context=actor_context,
            source_type=source_type,
            source_id=source_id,
        )
        owner_generation = _calendar_drift_source_generation(
            session,
            context=owner_context,
            source_type=source_type,
            source_id=source_id,
        )
    except HTTPException:
        session.rollback()
        return None
    if actor_generation != generation or owner_generation != generation:
        session.rollback()
        return None
    now = _current_time()
    current_reason = str(sync.dead_letter_reason or "")
    if current_reason.startswith(_CALENDAR_DRIFT_CLAIM_PREFIX):
        if sync.next_attempt_at is not None and _aware(sync.next_attempt_at) > now:
            session.rollback()
            return None
    elif current_reason:
        session.rollback()
        return None
    reader = _drift_provider_reader(
        session,
        context=actor_context,
        connection=connection,
    )
    claim_marker = _calendar_claim_marker(_CALENDAR_DRIFT_CLAIM_PREFIX)
    sync.dead_letter_reason = claim_marker
    sync.next_attempt_at = now + _CALENDAR_PROVIDER_LEASE
    sync.durable_last_attempt_at = now
    sync.updated_at = now
    session.add(sync)
    connection_snapshot = _calendar_drift_connection_snapshot(connection)
    session.commit()
    return _CalendarDriftClaim(
        sync_id=sync_id,
        connection_id=connection_id,
        owner_membership_id=owner_membership_id,
        provider_event_id=provider_event_id,
        claim_marker=claim_marker,
        source_type=source_type,
        source_id=source_id,
        generation=generation,
        connection_snapshot=connection_snapshot,
        reader=reader,
    )


def _finalize_calendar_drift_read(
    session: Session,
    *,
    context: SessionContext,
    claim: _CalendarDriftClaim,
    drift_status: str,
    detail: str,
) -> CalendarDriftFinding | None:
    """Publish a provider read only if the exact claimed authority survives."""

    actor, owner, sync, connection = _lock_calendar_drift_graph(
        session,
        context=context,
        actor_membership_id=context.membership.id,
        owner_membership_id=claim.owner_membership_id,
        sync_id=claim.sync_id,
        connection_id=claim.connection_id,
        generation=claim.generation,
    )
    if sync is None or sync.dead_letter_reason != claim.claim_marker:
        session.rollback()
        return None
    actor_authorized = _locked_calendar_membership_authorized(session, actor)
    if actor_authorized and actor is not None:
        actor_context = SessionContext(
            company=context.company,
            membership=actor,
            user=actor.user,
        )
        try:
            require_recent_step_up(
                session,
                context=actor_context,
                purpose="calendar_projection_drift_check",
            )
        except HTTPException:
            actor_authorized = False
    else:
        actor_context = context
    owner_authorized = _locked_calendar_membership_authorized(session, owner)
    exact_row = bool(
        sync.calendar_connection_id == claim.connection_id
        and str(sync.source_type) == claim.source_type
        and sync.source_id == claim.source_id
        and sync.sync_status == CalendarEventSyncStatus.SYNCED
        and str(sync.provider_event_id or "") == claim.provider_event_id
    )
    exact_connection = bool(
        connection is not None
        and connection.status == CalendarConnectionStatus.CONNECTED
        and _calendar_drift_connection_snapshot(connection)
        == claim.connection_snapshot
    )
    generation_valid = False
    if actor_authorized and owner_authorized and exact_row and exact_connection:
        assert owner is not None
        owner_context = SessionContext(
            company=context.company,
            membership=owner,
            user=owner.user,
        )
        try:
            actor_generation = _calendar_drift_source_generation(
                session,
                context=actor_context,
                source_type=claim.source_type,
                source_id=claim.source_id,
            )
            owner_generation = _calendar_drift_source_generation(
                session,
                context=owner_context,
                source_type=claim.source_type,
                source_id=claim.source_id,
            )
        except HTTPException:
            generation_valid = False
        else:
            generation_valid = bool(
                actor_generation == claim.generation
                and owner_generation == claim.generation
            )
    if not (
        actor_authorized
        and owner_authorized
        and exact_row
        and exact_connection
        and generation_valid
    ):
        if exact_row:
            sync.dead_letter_reason = None
            sync.next_attempt_at = None
            sync.updated_at = _current_time()
            session.add(sync)
            session.commit()
        else:
            session.rollback()
        return None

    now = _current_time()
    sync.drift_status = drift_status
    sync.drift_checked_at = now
    sync.drift_detail = detail
    sync.dead_letter_reason = None
    sync.next_attempt_at = None
    sync.updated_at = now
    session.add(sync)
    finding = None
    if drift_status in {"moved", "missing", "unknown"}:
        finding = CalendarDriftFinding(
            sync_id=sync.id,
            connection_id=claim.connection_id,
            membership_id=claim.owner_membership_id,
            source_type=claim.source_type,
            source_id=claim.source_id,
            ip_docket_id=claim.generation.ip_authority.docket_id,
            drift_status=drift_status,
            detail=detail,
        )
        record_from_context(
            session,
            actor_context,
            action="calendar_event_sync.drift_detected",
            target_type="calendar_event_sync",
            target_id=sync.id,
            ip_docket_id=claim.generation.ip_authority.docket_id,
            metadata={
                "drift_status": drift_status,
                "source_type": claim.source_type,
            },
        )
    session.commit()
    return finding


def _check_ip_calendar_projection_drift_legacy(
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
            sync_id = row.id
            expected_provider_event_id = str(row.provider_event_id)
            session.commit()
            try:
                event = reader(expected_provider_event_id)
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

            row = session.scalar(
                select(CalendarEventSync)
                .where(
                    CalendarEventSync.id == sync_id,
                    CalendarEventSync.company_id == context.company.id,
                )
                .with_for_update(of=CalendarEventSync)
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.sync_status != CalendarEventSyncStatus.SYNCED
                or str(row.provider_event_id) != expected_provider_event_id
            ):
                # Lifecycle/revocation won while the provider was being read.
                # Drift is advisory and can never revive or rewrite that state.
                session.rollback()
                continue

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


def check_ip_calendar_projection_drift(
    session: Session,
    *,
    context: SessionContext,
) -> list[CalendarDriftFinding]:
    """Claim, read, and conditionally publish IP calendar drift findings."""

    sync_ids = list(
        session.scalars(
            select(CalendarEventSync.id)
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
    # Candidate discovery is advisory. Every exact claim starts from a clean
    # transaction and acquires the canonical authority graph below.
    session.rollback()
    findings: list[CalendarDriftFinding] = []
    for sync_id in sync_ids:
        claim = _claim_calendar_drift_read(
            session,
            context=context,
            sync_id=sync_id,
        )
        if claim is None:
            continue

        # `_claim_calendar_drift_read` committed the lease. No ORM access or
        # database lock crosses this external provider boundary.
        if claim.reader is None:
            status_value = "unknown"
            detail = "The calendar connection could not be read."
        else:
            try:
                event = claim.reader(claim.provider_event_id)
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
                    expected = claim.generation.occurs_on.isoformat()
                    actual = str(event.get("start_date") or "")
                    if actual and actual != expected:
                        status_value = "moved"
                        detail = "The event was moved away from the CaseOps date."
                    elif not actual:
                        status_value = "unknown"
                        detail = "The event carries no readable date."
                    else:
                        status_value = "matches"
                        detail = "The event matches the CaseOps date."

        finding = _finalize_calendar_drift_read(
            session,
            context=context,
            claim=claim,
            drift_status=status_value,
            detail=detail,
        )
        if finding is not None:
            findings.append(finding)
    return findings
