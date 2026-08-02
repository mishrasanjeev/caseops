from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarProvider,
    ConnectorHealthProvider,
    ConnectorHealthRecord,
    ConnectorHealthStatus,
    DriveConnectionStatus,
    DriveProvider,
    MailboxConnectionStatus,
    MailboxMessageImport,
    MailboxProvider,
    TenantMicrosoft365Configuration,
    TrackedCase,
    TrackedCaseProviderOperation,
    UserCalendarConnection,
    UserDriveConnection,
    UserMailboxConnection,
)
from caseops_api.schemas.integrations import (
    ConnectorHealthCheckResponse,
    ConnectorHealthListResponse,
    ConnectorRecord,
)
from caseops_api.schemas.integrations import (
    ConnectorHealthRecord as ConnectorHealthSchema,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import GOOGLE_CALENDAR_SCOPES, OUTLOOK_SCOPES
from caseops_api.services.google_workspace import (
    GOOGLE_WORKSPACE_DRIVE_SCOPES,
    GOOGLE_WORKSPACE_GMAIL_SCOPES,
    GOOGLE_WORKSPACE_SCOPES,
    google_workspace_connector_configured,
    google_workspace_connector_missing_config_names,
)
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

_TENANT_ACCOUNT = "tenant"
_PROVIDER_OPERATIONS_LINK = "/app/admin/provider-operations"
_DEFAULT_FRESHNESS_THRESHOLD_MINUTES = 24 * 60
_BLOCKED_HEALTH_STATES = {
    str(ConnectorHealthStatus.MISSING_CONFIG),
    str(ConnectorHealthStatus.BLOCKED_BY_POLICY),
}
_UNHEALTHY_HEALTH_STATES = {
    str(ConnectorHealthStatus.DEGRADED),
    str(ConnectorHealthStatus.TOKEN_EXPIRED),
    str(ConnectorHealthStatus.SCOPE_MISSING),
    str(ConnectorHealthStatus.RATE_LIMITED),
    str(ConnectorHealthStatus.PROVIDER_OUTAGE),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _latest_time(*values: datetime | None) -> datetime | None:
    aware = [_as_aware(value) for value in values if value is not None]
    return max(aware) if aware else None


def _response_class(row: ConnectorHealthRecord) -> str:
    error = (row.error_category or "").lower()
    state = str(row.connected_state)
    combined = f"{state} {error}"
    if row.polling_status == "no_change":
        return "no_change"
    if "timeout" in combined:
        return "timeout"
    if state in {
        str(ConnectorHealthStatus.TOKEN_EXPIRED),
        str(ConnectorHealthStatus.SCOPE_MISSING),
    } or any(value in combined for value in ("auth", "token", "scope")):
        return "authentication"
    if state == str(ConnectorHealthStatus.RATE_LIMITED) or "rate" in combined:
        return "rate_limit"
    if any(value in combined for value in ("parse", "schema", "malformed")):
        return "parse_error"
    if state == str(ConnectorHealthStatus.PROVIDER_OUTAGE) or "outage" in combined:
        return "provider_outage"
    if state == str(ConnectorHealthStatus.MISSING_CONFIG):
        return "configuration"
    if state == str(ConnectorHealthStatus.BLOCKED_BY_POLICY):
        return "policy"
    last_success = _as_aware(row.last_success_at)
    last_failure = _as_aware(row.last_failure_at)
    if last_success is not None and (last_failure is None or last_success >= last_failure):
        return "success"
    return "unknown"


def _freshness(row: ConnectorHealthRecord) -> tuple[str, str, int | None]:
    connected_state = str(row.connected_state)
    configured_state = str(row.configured_state)
    if connected_state == str(ConnectorHealthStatus.DISABLED) or configured_state == str(
        ConnectorHealthStatus.DISABLED
    ):
        return "disabled", "disabled", None
    if connected_state in _BLOCKED_HEALTH_STATES or configured_state in _BLOCKED_HEALTH_STATES:
        return "blocked", "blocked", None

    last_success = _as_aware(row.last_success_at)
    if last_success is None:
        return "never_succeeded", "unhealthy", None
    age_minutes = max(0, int((_now() - last_success).total_seconds() // 60))
    if connected_state in _UNHEALTHY_HEALTH_STATES:
        return (
            "stale" if age_minutes > _DEFAULT_FRESHNESS_THRESHOLD_MINUTES else "fresh",
            "unhealthy",
            age_minutes,
        )
    if age_minutes > _DEFAULT_FRESHNESS_THRESHOLD_MINUTES:
        return "stale", "unhealthy", age_minutes
    return "fresh", "healthy", age_minutes


def _bounded_text(value: str | None, max_length: int) -> str | None:
    if value is None or len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def _hash_ref(value: str | None) -> str:
    if not value:
        return _TENANT_ACCOUNT
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _missing_scopes(required: list[str], granted: list[str]) -> list[str]:
    granted_set = set(granted)
    return [scope for scope in required if scope not in granted_set]


def _configured_state(*, configured: bool, disabled: bool = False) -> str:
    if disabled:
        return ConnectorHealthStatus.DISABLED
    return ConnectorHealthStatus.CONFIGURED if configured else ConnectorHealthStatus.MISSING_CONFIG


def _connection_state(
    *,
    connected: bool,
    configured: bool,
    missing_scopes: list[str] | None = None,
    disabled: bool = False,
    degraded: bool = False,
) -> str:
    if disabled:
        return ConnectorHealthStatus.DISABLED
    if not configured:
        return ConnectorHealthStatus.MISSING_CONFIG
    if missing_scopes:
        return ConnectorHealthStatus.SCOPE_MISSING
    if degraded:
        return ConnectorHealthStatus.DEGRADED
    if connected:
        return ConnectorHealthStatus.CONNECTED
    return ConnectorHealthStatus.CONFIGURED


def _get_or_create_health(
    session: Session,
    *,
    company_id: str,
    provider: str,
    account_ref_hash: str = _TENANT_ACCOUNT,
) -> ConnectorHealthRecord:
    provider_key = str(provider)
    for candidate in [*session.new, *session.identity_map.values()]:
        if (
            isinstance(candidate, ConnectorHealthRecord)
            and candidate.company_id == company_id
            and candidate.provider == provider_key
            and candidate.account_ref_hash == account_ref_hash
        ):
            return candidate

    row = _lookup_health(
        session,
        company_id=company_id,
        provider=provider_key,
        account_ref_hash=account_ref_hash,
    )
    if row is not None:
        return row

    values = {
        "company_id": company_id,
        "provider": provider_key,
        "account_ref_hash": account_ref_hash,
    }
    if _insert_health_if_missing(session, values=values):
        row = _lookup_health(
            session,
            company_id=company_id,
            provider=provider_key,
            account_ref_hash=account_ref_hash,
        )
        if row is not None:
            return row

    row = ConnectorHealthRecord(**values)
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        row = _lookup_health(
            session,
            company_id=company_id,
            provider=provider_key,
            account_ref_hash=account_ref_hash,
        )
        if row is not None:
            return row
        raise
    return row


def _lookup_health(
    session: Session,
    *,
    company_id: str,
    provider: str,
    account_ref_hash: str,
) -> ConnectorHealthRecord | None:
    return session.scalar(
        select(ConnectorHealthRecord).where(
            ConnectorHealthRecord.company_id == company_id,
            ConnectorHealthRecord.provider == provider,
            ConnectorHealthRecord.account_ref_hash == account_ref_hash,
        )
    )


def _insert_health_if_missing(session: Session, *, values: dict[str, str]) -> bool:
    dialect_name = session.get_bind().dialect.name
    if dialect_name != "postgresql":
        # SQLite writes must go through CaseOpsSession.flush(), which holds
        # the process-wide SQLite write lock until commit/rollback. A direct
        # Core upsert bypasses that lock and can still fail with
        # "database is locked" under concurrent TestClient requests.
        return False

    from sqlalchemy.dialects.postgresql import insert as dialect_insert

    statement = (
        dialect_insert(ConnectorHealthRecord)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=[
                ConnectorHealthRecord.company_id,
                ConnectorHealthRecord.provider,
                ConnectorHealthRecord.account_ref_hash,
            ]
        )
    )
    session.execute(statement)
    return True


def _update_health(
    row: ConnectorHealthRecord,
    *,
    configured_state: str,
    connected_state: str,
    required_scopes: list[str] | None = None,
    granted_scopes: list[str] | None = None,
    last_success_at: datetime | None = None,
    last_failure_at: datetime | None = None,
    error_category: str | None = None,
    token_expires_at: datetime | None = None,
    token_refresh_status: str | None = None,
    webhook_status: str | None = None,
    polling_status: str | None = None,
    rate_limit_status: str | None = None,
    next_retry_at: datetime | None = None,
    disabled_reason: str | None = None,
    account_label: str | None = None,
    operational_alerts: list[str] | None = None,
    setup_actions: list[str] | None = None,
) -> ConnectorHealthRecord:
    row.configured_state = str(configured_state)
    row.connected_state = str(connected_state)
    row.required_scopes_json = list(required_scopes or [])
    row.granted_scopes_json = list(granted_scopes or [])
    row.last_success_at = last_success_at
    row.last_failure_at = last_failure_at
    row.error_category = _bounded_text(
        redact_provider_error(error_category) if error_category else None,
        80,
    )
    row.token_expires_at = token_expires_at
    row.token_refresh_status = _bounded_text(token_refresh_status, 40)
    row.webhook_status = _bounded_text(webhook_status, 40)
    row.polling_status = _bounded_text(polling_status, 40)
    row.rate_limit_status = _bounded_text(rate_limit_status or "not_reported", 40)
    row.next_retry_at = next_retry_at
    row.disabled_reason = _bounded_text(disabled_reason, 160)
    row.account_label = _bounded_text(account_label, 120)
    row.operational_alerts_json = list(operational_alerts or [])
    row.setup_actions_json = list(setup_actions or [])
    row.last_checked_at = _now()
    return row


def _latest_mailbox_times(
    session: Session,
    *,
    company_id: str,
    provider: str,
) -> tuple[datetime | None, datetime | None, datetime | None, str | None]:
    rows = list(
        session.scalars(
            select(MailboxMessageImport)
            .join(UserMailboxConnection)
            .where(
                MailboxMessageImport.company_id == company_id,
                UserMailboxConnection.provider == provider,
            )
        )
    )
    success = max(
        (row.updated_at for row in rows if row.status in {"imported", "linked_metadata"}),
        default=None,
    )
    failures = [row for row in rows if row.status in {"failed", "dead_letter"}]
    failure = max((row.updated_at for row in failures), default=None)
    retry = min((row.next_attempt_at for row in failures if row.next_attempt_at), default=None)
    error = next((row.last_error_redacted for row in failures if row.last_error_redacted), None)
    return success, failure, retry, error


def _latest_calendar_times(
    session: Session,
    *,
    company_id: str,
    provider: str,
) -> tuple[datetime | None, datetime | None, datetime | None, str | None]:
    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .join(UserCalendarConnection)
            .where(
                CalendarEventSync.company_id == company_id,
                UserCalendarConnection.provider == provider,
            )
        )
    )
    success = max((row.last_synced_at for row in rows if row.last_synced_at), default=None)
    failures = [
        row for row in rows if row.sync_status in {"failed", "dead_letter", "retry_scheduled"}
    ]
    failure = max((row.updated_at for row in failures), default=None)
    retry = min((row.next_attempt_at for row in failures if row.next_attempt_at), default=None)
    error = next((row.last_error for row in failures if row.last_error), None)
    return success, failure, retry, error


def _microsoft365_configured(session: Session, *, company_id: str) -> tuple[bool, list[str]]:
    row = session.scalar(
        select(TenantMicrosoft365Configuration).where(
            TenantMicrosoft365Configuration.company_id == company_id
        )
    )
    settings = get_settings()
    missing: list[str] = []
    if row is not None:
        if not row.enabled:
            missing.append("MICROSOFT_365_ENABLED")
        if not row.client_id:
            missing.append("MICROSOFT_365_CLIENT_ID")
        if not row.encrypted_client_secret_ref:
            missing.append("MICROSOFT_365_CLIENT_SECRET")
        if not row.tenant_id:
            missing.append("MICROSOFT_365_TENANT_ID")
        if not row.redirect_uri:
            missing.append("MICROSOFT_365_REDIRECT_URI")
        if not row.admin_consent_approved:
            missing.append("MICROSOFT_365_ADMIN_CONSENT_APPROVED")
        return not missing, missing
    env_missing = []
    if not settings.outlook_client_id:
        env_missing.append("OUTLOOK_CLIENT_ID")
    if not settings.outlook_client_secret:
        env_missing.append("OUTLOOK_CLIENT_SECRET")
    if not settings.outlook_redirect_uri:
        env_missing.append("OUTLOOK_REDIRECT_URI")
    return not env_missing, env_missing


def refresh_connector_health_records(
    session: Session,
    *,
    context: SessionContext,
) -> list[ConnectorHealthRecord]:
    company_id = context.company.id
    settings = get_settings()
    rows: list[ConnectorHealthRecord] = []

    from caseops_api.services.case_tracking_providers import (
        provider_status as case_tracking_provider_status,
    )

    tracking_enabled, tracking_provider, tracking_configured, tracking_reason = (
        case_tracking_provider_status()
    )
    tracking_operations = list(
        session.scalars(
            select(TrackedCaseProviderOperation)
            .where(TrackedCaseProviderOperation.company_id == company_id)
            .order_by(TrackedCaseProviderOperation.updated_at.desc())
            .limit(200)
        )
    )
    tracking_success = max(
        (
            row.completed_at
            for row in tracking_operations
            if row.status in {"succeeded", "no_change"} and row.completed_at
        ),
        default=None,
    )
    tracking_failures = [row for row in tracking_operations if row.status == "failed"]
    tracking_failure = max(
        (row.completed_at for row in tracking_failures if row.completed_at), default=None
    )
    tracking_success_aware = _as_aware(tracking_success)
    tracking_failure_aware = _as_aware(tracking_failure)
    latest_tracking = tracking_operations[0] if tracking_operations else None
    tracked_count = len(
        list(
            session.scalars(
                select(TrackedCase.id).where(TrackedCase.company_id == company_id).limit(1001)
            )
        )
    )
    tracking_recent = bool(
        tracking_success_aware
        and (_now() - tracking_success_aware).total_seconds()
        <= _DEFAULT_FRESHNESS_THRESHOLD_MINUTES * 60
    )
    tracking_degraded = bool(
        tracking_enabled
        and tracking_configured
        and tracked_count
        and (
            not tracking_recent
            or (
                tracking_failure_aware
                and tracking_failure_aware
                > (tracking_success_aware or datetime.min.replace(tzinfo=UTC))
            )
        )
    )
    tracking_state = _connection_state(
        configured=tracking_configured,
        connected=tracking_recent,
        disabled=not tracking_enabled,
        degraded=tracking_degraded,
    )
    tracking_alerts: list[str] = []
    if tracking_degraded:
        tracking_alerts.append(
            "Enabled case tracking has no recent successful provider operation; "
            "inspect correlated operations."
        )
    if any(row.status == "quarantined" for row in tracking_operations):
        tracking_alerts.append("One or more tracked-case provider operations are quarantined.")
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.CASE_TRACKING,
            ),
            configured_state=_configured_state(
                configured=tracking_configured,
                disabled=not tracking_enabled,
            ),
            connected_state=tracking_state,
            last_success_at=tracking_success,
            last_failure_at=tracking_failure,
            error_category=(latest_tracking.error_redacted if latest_tracking else tracking_reason),
            polling_status=(latest_tracking.status if latest_tracking else "never_run"),
            next_retry_at=min(
                (row.next_attempt_at for row in tracking_failures if row.next_attempt_at),
                default=None,
            ),
            disabled_reason=(
                tracking_reason if not tracking_enabled or not tracking_configured else None
            ),
            account_label=f"{tracking_provider} · {tracked_count} tracked",
            operational_alerts=tracking_alerts,
            setup_actions=[] if tracking_configured else ["CASE_TRACKING_PROVIDER_CONFIGURATION"],
        )
    )

    google_missing = sorted(
        {
            *google_workspace_connector_missing_config_names(
                session,
                context=context,
                connector="calendar",
            ),
            *google_workspace_connector_missing_config_names(
                session,
                context=context,
                connector="gmail",
            ),
            *google_workspace_connector_missing_config_names(
                session,
                context=context,
                connector="drive",
            ),
        }
    )
    google_configured = not google_missing
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.GOOGLE_WORKSPACE,
            ),
            configured_state=_configured_state(configured=google_configured),
            connected_state=_connection_state(
                configured=google_configured,
                connected=google_configured,
            ),
            required_scopes=list(GOOGLE_WORKSPACE_SCOPES),
            webhook_status="gmail_configured" if settings.gmail_pubsub_topic else "missing",
            polling_status="manual_check",
            disabled_reason=", ".join(google_missing) if google_missing else None,
            setup_actions=google_missing,
        )
    )

    _refresh_mailbox_health(
        session,
        context=context,
        provider=MailboxProvider.GMAIL,
        health_provider=ConnectorHealthProvider.GMAIL,
        required_scopes=list(GOOGLE_WORKSPACE_GMAIL_SCOPES),
        configured=google_workspace_connector_configured(
            session,
            context=context,
            connector="gmail",
        ),
        webhook_status="configured" if settings.gmail_webhook_verification_token else "missing",
        rows=rows,
    )
    _refresh_drive_health(
        session,
        context=context,
        provider=DriveProvider.GOOGLE_DRIVE,
        health_provider=ConnectorHealthProvider.GOOGLE_DRIVE,
        required_scopes=list(GOOGLE_WORKSPACE_DRIVE_SCOPES),
        configured=google_workspace_connector_configured(
            session,
            context=context,
            connector="drive",
        ),
        rows=rows,
    )
    _refresh_calendar_health(
        session,
        context=context,
        provider=CalendarProvider.GOOGLE_CALENDAR,
        health_provider=ConnectorHealthProvider.GOOGLE_CALENDAR,
        required_scopes=list(GOOGLE_CALENDAR_SCOPES),
        configured=google_workspace_connector_configured(
            session,
            context=context,
            connector="calendar",
        ),
        rows=rows,
    )

    microsoft_configured, microsoft_missing = _microsoft365_configured(
        session,
        company_id=company_id,
    )
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.MICROSOFT_365,
            ),
            configured_state=_configured_state(configured=microsoft_configured),
            connected_state=_connection_state(
                configured=microsoft_configured,
                connected=microsoft_configured,
            ),
            required_scopes=[
                "offline_access",
                "User.Read",
                "Mail.ReadBasic",
                "Calendars.ReadWrite",
                "Files.Read.All",
            ],
            webhook_status="not_enabled",
            polling_status="manual_check",
            disabled_reason=", ".join(microsoft_missing) if microsoft_missing else None,
            setup_actions=microsoft_missing,
        )
    )
    _refresh_mailbox_health(
        session,
        context=context,
        provider=MailboxProvider.OUTLOOK_MAIL,
        health_provider=ConnectorHealthProvider.OUTLOOK_MAIL,
        required_scopes=["offline_access", "User.Read", "Mail.ReadBasic"],
        configured=microsoft_configured,
        webhook_status="not_enabled",
        rows=rows,
    )
    _refresh_calendar_health(
        session,
        context=context,
        provider=CalendarProvider.OUTLOOK,
        health_provider=ConnectorHealthProvider.OUTLOOK_CALENDAR,
        required_scopes=list(OUTLOOK_SCOPES),
        configured=microsoft_configured,
        rows=rows,
    )
    _refresh_drive_health(
        session,
        context=context,
        provider=DriveProvider.ONEDRIVE_SHAREPOINT,
        health_provider=ConnectorHealthProvider.ONEDRIVE_SHAREPOINT,
        required_scopes=["offline_access", "User.Read", "Files.Read.All", "Sites.Read.All"],
        configured=microsoft_configured,
        rows=rows,
    )

    email_configured = bool(settings.sendgrid_api_key and settings.sendgrid_sender_email)
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.EMAIL_DELIVERY,
            ),
            configured_state=_configured_state(configured=email_configured),
            connected_state=_connection_state(
                configured=email_configured,
                connected=email_configured,
                disabled=not email_configured,
            ),
            webhook_status="configured" if settings.sendgrid_webhook_public_key else "missing",
            polling_status="not_applicable",
            disabled_reason=None
            if email_configured
            else "Email delivery provider is not configured.",
            setup_actions=[] if email_configured else ["SENDGRID_API_KEY", "SENDGRID_SENDER_EMAIL"],
        )
    )
    sms_configured = bool(
        settings.twilio_enabled
        and settings.twilio_account_sid
        and settings.twilio_auth_token
        and settings.twilio_from_number
    )
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.SMS,
            ),
            configured_state=_configured_state(configured=sms_configured),
            connected_state=_connection_state(
                configured=sms_configured,
                connected=sms_configured,
                disabled=not sms_configured,
            ),
            webhook_status="not_enabled",
            polling_status="not_applicable",
            disabled_reason=None if sms_configured else "SMS provider is disabled or incomplete.",
            setup_actions=[]
            if sms_configured
            else ["TWILIO_ENABLED", "TWILIO_ACCOUNT_SID", "TWILIO_FROM_NUMBER"],
        )
    )
    whatsapp_configured = bool(
        settings.whatsapp_enabled
        and settings.whatsapp_access_token
        and settings.whatsapp_phone_number_id
        and settings.whatsapp_template_name
    )
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=ConnectorHealthProvider.WHATSAPP,
            ),
            configured_state=_configured_state(configured=whatsapp_configured),
            connected_state=_connection_state(
                configured=whatsapp_configured,
                connected=whatsapp_configured,
                disabled=not whatsapp_configured,
            ),
            webhook_status="not_enabled",
            polling_status="not_applicable",
            disabled_reason=None
            if whatsapp_configured
            else "WhatsApp provider is disabled or incomplete.",
            setup_actions=[]
            if whatsapp_configured
            else ["WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"],
        )
    )
    session.flush()
    return rows


def _refresh_mailbox_health(
    session: Session,
    *,
    context: SessionContext,
    provider: str,
    health_provider: str,
    required_scopes: list[str],
    configured: bool,
    webhook_status: str,
    rows: list[ConnectorHealthRecord],
) -> None:
    company_id = context.company.id
    success, failure, retry, error = _latest_mailbox_times(
        session,
        company_id=company_id,
        provider=str(provider),
    )
    connections = list(
        session.scalars(
            select(UserMailboxConnection).where(
                UserMailboxConnection.company_id == company_id,
                UserMailboxConnection.provider == str(provider),
            )
        )
    )
    degraded = bool(failure and (not success or failure > success))
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=str(health_provider),
            ),
            configured_state=_configured_state(configured=configured),
            connected_state=_connection_state(
                configured=configured,
                connected=any(
                    row.status == MailboxConnectionStatus.CONNECTED for row in connections
                ),
                degraded=degraded,
            ),
            required_scopes=required_scopes,
            granted_scopes=sorted(
                {scope for row in connections for scope in (row.scopes_json or [])}
            ),
            last_success_at=success,
            last_failure_at=failure,
            error_category=error,
            webhook_status=webhook_status,
            polling_status="manual_review_queue",
            next_retry_at=retry,
            token_refresh_status="stored_reference_only" if connections else "not_connected",
            disabled_reason=None if configured else "Provider OAuth is not configured.",
        )
    )
    for connection in connections:
        granted = list(connection.scopes_json or [])
        missing = _missing_scopes(required_scopes, granted)
        rows.append(
            _update_health(
                _get_or_create_health(
                    session,
                    company_id=company_id,
                    provider=str(health_provider),
                    account_ref_hash=_hash_ref(connection.id),
                ),
                configured_state=_configured_state(configured=configured),
                connected_state=_connection_state(
                    configured=configured,
                    connected=connection.status == MailboxConnectionStatus.CONNECTED,
                    missing_scopes=missing,
                    degraded=connection.status == MailboxConnectionStatus.ERROR,
                ),
                required_scopes=required_scopes,
                granted_scopes=granted,
                last_success_at=connection.last_import_at,
                last_failure_at=connection.updated_at
                if connection.status == MailboxConnectionStatus.ERROR
                else None,
                webhook_status="watch_active" if connection.watch_expires_at else webhook_status,
                polling_status="manual_review_queue",
                token_refresh_status="stored_reference_only"
                if connection.encrypted_token_ref
                else "missing_token_reference",
                disabled_reason=None
                if connection.status == MailboxConnectionStatus.CONNECTED
                else "Connection is revoked or errored.",
                account_label="connected_account",
            )
        )


def _refresh_drive_health(
    session: Session,
    *,
    context: SessionContext,
    provider: str,
    health_provider: str,
    required_scopes: list[str],
    configured: bool,
    rows: list[ConnectorHealthRecord],
) -> None:
    company_id = context.company.id
    connections = list(
        session.scalars(
            select(UserDriveConnection).where(
                UserDriveConnection.company_id == company_id,
                UserDriveConnection.provider == str(provider),
            )
        )
    )
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=str(health_provider),
            ),
            configured_state=_configured_state(configured=configured),
            connected_state=_connection_state(
                configured=configured,
                connected=any(row.status == DriveConnectionStatus.CONNECTED for row in connections),
            ),
            required_scopes=required_scopes,
            granted_scopes=sorted(
                {scope for row in connections for scope in (row.scopes_json or [])}
            ),
            last_success_at=max(
                (row.last_list_at for row in connections if row.last_list_at), default=None
            ),
            last_failure_at=max(
                (
                    row.updated_at
                    for row in connections
                    if row.status == DriveConnectionStatus.ERROR
                ),
                default=None,
            ),
            webhook_status="not_enabled",
            polling_status="manual_review_queue",
            token_refresh_status="stored_reference_only" if connections else "not_connected",
            disabled_reason=None if configured else "Provider OAuth is not configured.",
        )
    )
    for connection in connections:
        granted = list(connection.scopes_json or [])
        missing = _missing_scopes(required_scopes, granted)
        rows.append(
            _update_health(
                _get_or_create_health(
                    session,
                    company_id=company_id,
                    provider=str(health_provider),
                    account_ref_hash=_hash_ref(connection.id),
                ),
                configured_state=_configured_state(configured=configured),
                connected_state=_connection_state(
                    configured=configured,
                    connected=connection.status == DriveConnectionStatus.CONNECTED,
                    missing_scopes=missing,
                    degraded=connection.status == DriveConnectionStatus.ERROR,
                ),
                required_scopes=required_scopes,
                granted_scopes=granted,
                last_success_at=connection.last_list_at,
                last_failure_at=connection.updated_at
                if connection.status == DriveConnectionStatus.ERROR
                else None,
                webhook_status="not_enabled",
                polling_status="manual_review_queue",
                token_refresh_status="stored_reference_only"
                if connection.encrypted_token_ref
                else "missing_token_reference",
                account_label="connected_account",
            )
        )


def _refresh_calendar_health(
    session: Session,
    *,
    context: SessionContext,
    provider: str,
    health_provider: str,
    required_scopes: list[str],
    configured: bool,
    rows: list[ConnectorHealthRecord],
) -> None:
    company_id = context.company.id
    success, failure, retry, error = _latest_calendar_times(
        session,
        company_id=company_id,
        provider=str(provider),
    )
    connections = list(
        session.scalars(
            select(UserCalendarConnection).where(
                UserCalendarConnection.company_id == company_id,
                UserCalendarConnection.provider == str(provider),
            )
        )
    )
    degraded = bool(failure and (not success or failure > success))
    rows.append(
        _update_health(
            _get_or_create_health(
                session,
                company_id=company_id,
                provider=str(health_provider),
            ),
            configured_state=_configured_state(configured=configured),
            connected_state=_connection_state(
                configured=configured,
                connected=any(
                    row.status == CalendarConnectionStatus.CONNECTED for row in connections
                ),
                degraded=degraded,
            ),
            required_scopes=required_scopes,
            granted_scopes=sorted(
                {scope for row in connections for scope in (row.scopes_json or [])}
            ),
            last_success_at=success,
            last_failure_at=failure,
            error_category=error,
            webhook_status="not_enabled",
            polling_status="manual_conflict_review",
            next_retry_at=retry,
            token_refresh_status="stored_reference_only" if connections else "not_connected",
            disabled_reason=None if configured else "Calendar provider OAuth is not configured.",
        )
    )
    for connection in connections:
        granted = list(connection.scopes_json or [])
        missing = _missing_scopes(required_scopes, granted)
        rows.append(
            _update_health(
                _get_or_create_health(
                    session,
                    company_id=company_id,
                    provider=str(health_provider),
                    account_ref_hash=_hash_ref(connection.id),
                ),
                configured_state=_configured_state(configured=configured),
                connected_state=_connection_state(
                    configured=configured,
                    connected=connection.status == CalendarConnectionStatus.CONNECTED,
                    missing_scopes=missing,
                    degraded=connection.status == CalendarConnectionStatus.ERROR,
                ),
                required_scopes=required_scopes,
                granted_scopes=granted,
                last_success_at=connection.last_sync_at,
                last_failure_at=connection.updated_at
                if connection.status == CalendarConnectionStatus.ERROR
                else None,
                webhook_status="not_enabled",
                polling_status="manual_conflict_review",
                token_refresh_status="stored_reference_only"
                if connection.encrypted_token_ref
                else "missing_token_reference",
                account_label="connected_account",
            )
        )


def _record(row: ConnectorHealthRecord) -> ConnectorHealthSchema:
    required_scopes = list(row.required_scopes_json or [])
    granted_scopes = list(row.granted_scopes_json or [])
    freshness_state, operational_state, freshness_age_minutes = _freshness(row)
    last_attempted_at = _latest_time(
        row.last_checked_at,
        row.last_success_at,
        row.last_failure_at,
    )
    return ConnectorHealthSchema(
        id=row.id,
        company_id=row.company_id,
        provider=row.provider,
        configured_state=row.configured_state,  # type: ignore[arg-type]
        connected_state=row.connected_state,  # type: ignore[arg-type]
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        error_category=(redact_provider_error(row.error_category) if row.error_category else None),
        required_scopes=required_scopes,
        granted_scopes=granted_scopes,
        missing_scopes=_missing_scopes(required_scopes, granted_scopes),
        token_expires_at=row.token_expires_at,
        token_refresh_status=row.token_refresh_status,
        webhook_status=row.webhook_status,
        polling_status=row.polling_status,
        rate_limit_status=row.rate_limit_status,
        next_retry_at=row.next_retry_at,
        disabled_reason=(
            redact_provider_error(row.disabled_reason) if row.disabled_reason else None
        ),
        last_checked_at=row.last_checked_at,
        last_attempted_at=last_attempted_at,
        last_good_at=row.last_success_at,
        next_scheduled_at=row.next_retry_at,
        freshness_state=freshness_state,  # type: ignore[arg-type]
        operational_state=operational_state,  # type: ignore[arg-type]
        freshness_threshold_minutes=_DEFAULT_FRESHNESS_THRESHOLD_MINUTES,
        freshness_age_minutes=freshness_age_minutes,
        response_class=_response_class(row),  # type: ignore[arg-type]
        operator_attention_required=operational_state in {"unhealthy", "blocked"},
        current_error_redacted=(
            redact_provider_error(row.error_category or row.disabled_reason)
            if (row.error_category or row.disabled_reason)
            else None
        ),
        operational_alerts=list(row.operational_alerts_json or []),
        setup_actions=list(row.setup_actions_json or []),
        provider_operations_link=_PROVIDER_OPERATIONS_LINK,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _health_response(rows: list[ConnectorHealthRecord]) -> ConnectorHealthListResponse:
    health = [_record(row) for row in rows]
    return ConnectorHealthListResponse(
        health=health,
        healthy_count=sum(row.operational_state == "healthy" for row in health),
        unhealthy_count=sum(row.operational_state == "unhealthy" for row in health),
        stale_count=sum(row.freshness_state == "stale" for row in health),
        disabled_count=sum(row.operational_state == "disabled" for row in health),
    )


def list_tenant_connector_health(
    session: Session,
    *,
    context: SessionContext,
) -> ConnectorHealthListResponse:
    refresh_connector_health_records(session, context=context)
    rows = list(
        session.scalars(
            select(ConnectorHealthRecord)
            .where(ConnectorHealthRecord.company_id == context.company.id)
            .order_by(ConnectorHealthRecord.provider.asc(), ConnectorHealthRecord.created_at.asc())
        )
    )
    return _health_response(rows)


def check_tenant_connector_health(
    session: Session,
    *,
    context: SessionContext,
) -> ConnectorHealthCheckResponse:
    rows = refresh_connector_health_records(session, context=context)
    checked_at = _now()
    record_from_context(
        session,
        context,
        action="connector_health.checked",
        target_type="connector_health",
        metadata={"provider_count": len({row.provider for row in rows})},
    )
    session.commit()
    summary = _health_response(rows)
    return ConnectorHealthCheckResponse(
        checked_at=checked_at,
        health=summary.health,
        healthy_count=summary.healthy_count,
        unhealthy_count=summary.unhealthy_count,
        stale_count=summary.stale_count,
        disabled_count=summary.disabled_count,
    )


def list_platform_connector_health(session: Session) -> ConnectorHealthListResponse:
    rows = list(
        session.scalars(
            select(ConnectorHealthRecord).order_by(
                ConnectorHealthRecord.company_id.asc(),
                ConnectorHealthRecord.provider.asc(),
                ConnectorHealthRecord.updated_at.desc(),
            )
        )
    )
    return _health_response(rows)


def apply_health_to_connector_records(
    records: list[ConnectorRecord],
    health: list[ConnectorHealthRecord],
) -> list[ConnectorRecord]:
    by_provider = {row.provider: row for row in health if row.account_ref_hash == _TENANT_ACCOUNT}
    key_map = {
        "google_workspace": ConnectorHealthProvider.GOOGLE_WORKSPACE,
        "gmail": ConnectorHealthProvider.GMAIL,
        "google_drive": ConnectorHealthProvider.GOOGLE_DRIVE,
        "google_calendar": ConnectorHealthProvider.GOOGLE_CALENDAR,
        "outlook_calendar": ConnectorHealthProvider.OUTLOOK_CALENDAR,
        "microsoft_mailbox": ConnectorHealthProvider.OUTLOOK_MAIL,
        "sendgrid": ConnectorHealthProvider.EMAIL_DELIVERY,
        "sms": ConnectorHealthProvider.SMS,
        "whatsapp": ConnectorHealthProvider.WHATSAPP,
    }
    merged: list[ConnectorRecord] = []
    for record in records:
        provider = key_map.get(record.key)
        row = by_provider.get(str(provider)) if provider else None
        if row is None:
            merged.append(record)
            continue
        required = list(row.required_scopes_json or [])
        granted = list(row.granted_scopes_json or [])
        data = record.model_dump()
        data.update(
            {
                "status": row.connected_state,
                "last_success": row.last_success_at or record.last_success,
                "last_failure": row.last_failure_at or record.last_failure,
                "next_run": row.next_retry_at or record.next_run,
                "webhook_status": row.webhook_status or record.webhook_status,
                "polling_status": row.polling_status,
                "rate_limit_status": row.rate_limit_status,
                "token_expiry": row.token_expires_at,
                "token_refresh_status": row.token_refresh_status,
                "required_scopes": required,
                "granted_scopes": granted,
                "missing_scopes": _missing_scopes(required, granted),
                "error_category": row.error_category,
                "disabled_reason": row.disabled_reason,
                "last_checked_at": row.last_checked_at,
                "operational_alerts": list(row.operational_alerts_json or []),
                "setup_actions": list(row.setup_actions_json or []),
            }
        )
        merged.append(ConnectorRecord(**data))
    return merged
