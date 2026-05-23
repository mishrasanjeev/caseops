from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import urlencode

import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    CalendarSyncSourceType,
    Matter,
    MatterHearing,
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
    OutlookBulkSyncItem,
    OutlookBulkSyncRequest,
    OutlookBulkSyncResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import (
    assert_access,
    visible_matters_filter,
)

OUTLOOK_SCOPES = ["offline_access", "User.Read", "Calendars.ReadWrite"]
_STATE_KIND = "outlook_calendar_oauth"
_STATE_TTL_MINUTES = 10


class CalendarProviderError(RuntimeError):
    """Provider failures safe to persist/display as sync errors."""


class OutlookProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def unavailable_reason(self) -> str | None: ...

    def authorization_url(self, *, state: str) -> str: ...

    def exchange_code(self, *, code: str) -> dict[str, Any]: ...

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, Any],
        hearing: MatterHearing,
        matter: Matter,
        existing_provider_event_id: str | None,
    ) -> str: ...


class MicrosoftGraphOutlookProvider:
    """Small Microsoft Graph adapter.

    Tests replace this provider through ``set_outlook_provider_for_tests`` so
    the API never needs live Graph credentials in CI.
    """

    @property
    def configured(self) -> bool:
        settings = get_settings()
        return bool(
            settings.outlook_client_id
            and settings.outlook_client_secret
            and settings.outlook_redirect_uri
        )

    @property
    def unavailable_reason(self) -> str | None:
        if self.configured:
            return None
        return "Microsoft Graph OAuth is not configured."

    def authorization_url(self, *, state: str) -> str:
        settings = get_settings()
        if not self.configured:
            raise CalendarProviderError(self.unavailable_reason or "Outlook unavailable.")
        tenant = settings.outlook_tenant_id.strip("/") or "organizations"
        qs = urlencode(
            {
                "client_id": settings.outlook_client_id,
                "response_type": "code",
                "redirect_uri": settings.outlook_redirect_uri,
                "response_mode": "query",
                "scope": " ".join(OUTLOOK_SCOPES),
                "state": state,
                "prompt": "select_account",
            }
        )
        return f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize?{qs}"

    def exchange_code(self, *, code: str) -> dict[str, Any]:
        settings = get_settings()
        if not self.configured:
            raise CalendarProviderError(self.unavailable_reason or "Outlook unavailable.")
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc

        tenant = settings.outlook_tenant_id.strip("/") or "organizations"
        token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
        try:
            token_response = httpx.post(
                token_url,
                data={
                    "client_id": settings.outlook_client_id,
                    "client_secret": settings.outlook_client_secret,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": settings.outlook_redirect_uri,
                    "scope": " ".join(OUTLOOK_SCOPES),
                },
                timeout=15,
            )
            token_response.raise_for_status()
            token_payload = token_response.json()
            access_token = str(token_payload.get("access_token") or "")
            if not access_token:
                raise CalendarProviderError("Microsoft Graph did not return an access token.")
            me_response = httpx.get(
                "https://graph.microsoft.com/v1.0/me",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=15,
            )
            me_response.raise_for_status()
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

    def upsert_hearing_event(
        self,
        *,
        token_payload: dict[str, Any],
        hearing: MatterHearing,
        matter: Matter,
        existing_provider_event_id: str | None,
    ) -> str:
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency is present in app envs
            raise CalendarProviderError("Microsoft Graph HTTP client is unavailable.") from exc
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise CalendarProviderError("Stored Outlook token is unavailable.")

        subject = f"{matter.matter_code}: {hearing.purpose or 'Hearing'}"
        start = f"{hearing.hearing_on.isoformat()}T00:00:00"
        end = f"{(hearing.hearing_on + timedelta(days=1)).isoformat()}T00:00:00"
        body_lines = [
            f"Matter: {matter.title}",
            f"Forum: {hearing.forum_name}",
        ]
        if hearing.judge_name:
            body_lines.append(f"Judge: {hearing.judge_name}")
        if hearing.outcome_note:
            body_lines.append(f"Outcome: {hearing.outcome_note}")
        payload = {
            "subject": subject[:255],
            "isAllDay": True,
            "start": {"dateTime": start, "timeZone": "India Standard Time"},
            "end": {"dateTime": end, "timeZone": "India Standard Time"},
            "body": {
                "contentType": "text",
                "content": "\n".join(body_lines),
            },
            "categories": ["CaseOps", "Hearing"],
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


_outlook_provider_override: OutlookProvider | None = None


def set_outlook_provider_for_tests(provider: OutlookProvider | None) -> None:
    global _outlook_provider_override
    _outlook_provider_override = provider


def _provider() -> OutlookProvider:
    return _outlook_provider_override or MicrosoftGraphOutlookProvider()


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_token_payload(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return "fernet:" + _fernet().encrypt(raw).decode("ascii")


def _decrypt_token_payload(value: str | None) -> dict[str, Any]:
    if not value or not value.startswith("fernet:"):
        raise CalendarProviderError("Stored Outlook token is unavailable.")
    try:
        raw = _fernet().decrypt(value.removeprefix("fernet:").encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise CalendarProviderError("Stored Outlook token cannot be decrypted.") from exc
    decoded = json.loads(raw.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise CalendarProviderError("Stored Outlook token payload is malformed.")
    return decoded


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
            detail="Invalid Outlook connection state.",
        ) from exc
    if (
        payload.get("kind") != _STATE_KIND
        or str(payload.get("company_id")) != context.company.id
        or str(payload.get("membership_id")) != context.membership.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Outlook connection state does not match the current session.",
        )


def _connection_record(connection: UserCalendarConnection) -> CalendarConnectionRecord:
    return CalendarConnectionRecord(
        id=connection.id,
        company_id=connection.company_id,
        membership_id=connection.membership_id,
        provider="outlook",
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
        created_at=sync.created_at,
        updated_at=sync.updated_at,
    )


def _missing_outlook_config_names(provider: OutlookProvider) -> list[str]:
    """Return config names only; never expose configured values."""
    if provider.configured:
        return []
    settings = get_settings()
    missing: list[str] = []
    if not settings.outlook_client_id:
        missing.append("OUTLOOK_CLIENT_ID")
    if not settings.outlook_client_secret:
        missing.append("OUTLOOK_CLIENT_SECRET")
    if not settings.outlook_redirect_uri:
        missing.append("OUTLOOK_REDIRECT_URI")
    return missing


def _provider_config_status(provider: OutlookProvider) -> CalendarProviderConfigStatus:
    return CalendarProviderConfigStatus(
        configured=provider.configured,
        missing_config_names=_missing_outlook_config_names(provider),
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
        candidate_id = hashlib.sha256(
            f"{connection_id}:{provider_event_id}".encode()
        ).hexdigest()[:16]
        candidates.append(
            CalendarSyncConflictCandidate(
                id=f"dup-provider-event:{candidate_id}",
                conflict_type="duplicate_provider_event_id",
                calendar_connection_id=connection_id,
                provider_event_id=provider_event_id,
                duplicate_count=len(rows),
                source_ids=[row.source_id for row in rows],
                source_types=sorted({row.source_type for row in rows}),  # type: ignore[list-item]
                sync_ids=[row.id for row in rows],
                message=(
                    "Multiple CaseOps calendar sync records point to the same "
                    "Outlook event. Review before running another manual sync."
                ),
            )
        )
    return candidates


def _safe_error(exc: BaseException) -> str:
    text = str(exc) or exc.__class__.__name__
    for token_word in ("access_token", "refresh_token", "client_secret", "Authorization"):
        text = text.replace(token_word, "[redacted]")
    return text[:500]


def list_connections(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarConnectionListResponse:
    provider = _provider()
    rows = list(
        session.scalars(
            select(UserCalendarConnection)
            .where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.membership_id == context.membership.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            )
            .order_by(UserCalendarConnection.created_at.asc())
        )
    )
    return CalendarConnectionListResponse(
        provider_available=provider.configured,
        unavailable_reason=provider.unavailable_reason,
        connections=[_connection_record(row) for row in rows],
    )


def start_outlook_connection(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarConnectionStartResponse:
    del session
    provider = _provider()
    if not provider.configured:
        return CalendarConnectionStartResponse(
            provider_available=False,
            unavailable_reason=provider.unavailable_reason,
        )
    return CalendarConnectionStartResponse(
        provider_available=True,
        auth_url=provider.authorization_url(state=_sign_state(context)),
    )


def complete_outlook_connection(
    session: Session,
    *,
    context: SessionContext,
    code: str,
    state: str,
) -> CalendarConnectionRecord:
    provider = _provider()
    if not provider.configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=provider.unavailable_reason or "Outlook calendar sync is unavailable.",
        )
    _verify_state(context, state)
    exchanged = provider.exchange_code(code=code)
    token_payload = exchanged.get("token_payload")
    if not isinstance(token_payload, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Outlook OAuth provider returned an invalid token response.",
        )
    now = datetime.now(UTC)
    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
        )
    )
    if connection is None:
        connection = UserCalendarConnection(
            company_id=context.company.id,
            membership_id=context.membership.id,
            provider=CalendarProvider.OUTLOOK,
        )
        session.add(connection)
        session.flush()
    connection.provider_account_id = str(exchanged.get("provider_account_id") or "") or None
    connection.display_email = str(exchanged.get("display_email") or "") or None
    connection.status = CalendarConnectionStatus.CONNECTED
    connection.encrypted_token_ref = _encrypt_token_payload(token_payload)
    connection.scopes_json = [
        str(scope) for scope in exchanged.get("scopes", OUTLOOK_SCOPES) if str(scope)
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
            "provider": CalendarProvider.OUTLOOK,
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
    connection = session.scalar(
        select(UserCalendarConnection).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.membership_id == context.membership.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
        )
    )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Outlook calendar is not connected.",
        )
    return connection


def sync_hearing_to_outlook(
    session: Session,
    *,
    context: SessionContext,
    hearing_id: str,
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
    connection = _connected_outlook_connection(session, context=context)
    sync = session.scalar(
        select(CalendarEventSync).where(
            CalendarEventSync.company_id == context.company.id,
            CalendarEventSync.calendar_connection_id == connection.id,
            CalendarEventSync.source_type == CalendarSyncSourceType.MATTER_HEARING,
            CalendarEventSync.source_id == hearing.id,
        )
    )
    if sync is None:
        sync = CalendarEventSync(
            company_id=context.company.id,
            calendar_connection_id=connection.id,
            source_type=CalendarSyncSourceType.MATTER_HEARING,
            source_id=hearing.id,
            sync_status=CalendarEventSyncStatus.PENDING,
        )
        session.add(sync)
        session.flush()
    try:
        token_payload = _decrypt_token_payload(connection.encrypted_token_ref)
        provider_event_id = _provider().upsert_hearing_event(
            token_payload=token_payload,
            hearing=hearing,
            matter=matter,
            existing_provider_event_id=sync.provider_event_id,
        )
    except Exception as exc:
        sync.sync_status = CalendarEventSyncStatus.FAILED
        sync.last_error = _safe_error(exc)
        session.add(sync)
        record_from_context(
            session,
            context,
            action="calendar.sync.failed",
            target_type="calendar_event_sync",
            target_id=sync.id,
            matter_id=matter.id,
            result="failed",
            metadata={
                "provider": CalendarProvider.OUTLOOK,
                "source_type": CalendarSyncSourceType.MATTER_HEARING,
                "source_id": hearing.id,
                "error": sync.last_error,
            },
        )
        session.commit()
        return CalendarEventSyncResponse(sync=_sync_record(sync))

    now = datetime.now(UTC)
    sync.provider_event_id = provider_event_id
    sync.sync_status = CalendarEventSyncStatus.SYNCED
    sync.last_error = None
    sync.last_synced_at = now
    connection.last_sync_at = now
    session.add_all([sync, connection])
    record_from_context(
        session,
        context,
        action="calendar.sync.succeeded",
        target_type="calendar_event_sync",
        target_id=sync.id,
        matter_id=matter.id,
        metadata={
            "provider": CalendarProvider.OUTLOOK,
            "source_type": CalendarSyncSourceType.MATTER_HEARING,
            "source_id": hearing.id,
            "provider_event_id": provider_event_id,
        },
    )
    session.commit()
    return CalendarEventSyncResponse(sync=_sync_record(sync))


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

    Durable background sync remains blocked pending Temporal — see
    the response's ``durable_automation`` field.
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
                visible_matters_filter(session, context=context),
                MatterHearing.hearing_on >= payload.range_from,
                MatterHearing.hearing_on <= payload.range_to,
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
    )


def sync_status(
    session: Session,
    *,
    context: SessionContext,
) -> CalendarSyncStatusResponse:
    provider = _provider()
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
    return CalendarSyncStatusResponse(
        provider_available=provider.configured,
        notification_delivery="pending_wtd_5_3",
        capabilities=CalendarSyncCapabilityStatus(
            manual_sync_available=provider.configured,
            durable_automation="blocked_pending_temporal",
            notification_delivery="pending_wtd_5_3",
            email_invitation_candidates="deferred_pending_review_queue",
        ),
        provider_config=[_provider_config_status(provider)],
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
    "complete_outlook_connection",
    "list_connections",
    "revoke_connection",
    "set_outlook_provider_for_tests",
    "start_outlook_connection",
    "sync_hearing_to_outlook",
    "sync_status",
]
