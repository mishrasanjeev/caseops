from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarProvider,
    DriveConnectionStatus,
    DriveProvider,
    MailboxConnectionStatus,
    MailboxProvider,
    TenantGoogleWorkspaceConfiguration,
    UserCalendarConnection,
    UserDriveConnection,
    UserMailboxConnection,
)
from caseops_api.schemas.google_workspace import (
    GoogleWorkspaceApprovalItemStatus,
    GoogleWorkspaceConfigurationItemStatus,
    GoogleWorkspaceConnectionCounts,
    GoogleWorkspaceMachineReadinessControlStatus,
    GoogleWorkspaceReadinessCheckResult,
    GoogleWorkspaceReadinessTestResponse,
    GoogleWorkspaceTenantConfigurationResponse,
    GoogleWorkspaceTenantConfigurationUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.http_retries import (
    DEFAULT_SAFE_HTTP_RETRY_BACKOFF_SECONDS,
    DEFAULT_SAFE_HTTP_RETRY_MAX_ATTEMPTS,
    RETRYABLE_READ_STATUS_CODES,
    SAFE_RETRY_METHODS,
)
from caseops_api.services.session_context import SessionContext

GoogleWorkspaceConnector = Literal["calendar", "gmail", "drive"]

GOOGLE_WORKSPACE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events"
]
GOOGLE_WORKSPACE_GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GOOGLE_WORKSPACE_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
GOOGLE_WORKSPACE_SCOPES = sorted(
    {
        *GOOGLE_WORKSPACE_CALENDAR_SCOPES,
        *GOOGLE_WORKSPACE_GMAIL_SCOPES,
        *GOOGLE_WORKSPACE_DRIVE_SCOPES,
    }
)
GOOGLE_WORKSPACE_MACHINE_CONTROL_VERSION = (
    "google-workspace-connector-controls/2026-08-30.1"
)

_CONNECTOR_REQUIRED_CONFIG_NAMES = {
    "calendar": [
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REDIRECT_URI",
    ],
    "gmail": [
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GMAIL_REDIRECT_URI",
    ],
    "drive": [
        "GOOGLE_WORKSPACE_CLIENT_ID",
        "GOOGLE_WORKSPACE_CLIENT_SECRET",
        "GOOGLE_DRIVE_REDIRECT_URI",
    ],
}

_ENV_REQUIRED_CONFIG_NAMES = {
    "calendar": [
        "GOOGLE_CALENDAR_CLIENT_ID",
        "GOOGLE_CALENDAR_CLIENT_SECRET",
        "GOOGLE_CALENDAR_REDIRECT_URI",
    ],
    "gmail": ["GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REDIRECT_URI"],
    "drive": [
        "GOOGLE_DRIVE_CLIENT_ID",
        "GOOGLE_DRIVE_CLIENT_SECRET",
        "GOOGLE_DRIVE_REDIRECT_URI",
    ],
}

_APPROVAL_LABELS = {
    "oauth_consent_model_approved": "Google Workspace OAuth consent approved",
    "scopes_approved": "Calendar, Gmail, and Drive scopes approved",
}


@dataclass(frozen=True, slots=True)
class GoogleWorkspaceOAuthConfig:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str | None
    source: str
    enabled: bool = True
    missing_config_names: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.client_id
            and self.client_secret
            and self.redirect_uri
        )


def _fernet() -> Fernet:
    digest = hashlib.sha256(get_settings().auth_secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encrypt_secret(value: str) -> str:
    return "fernet:" + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    if not value.startswith("fernet:"):
        raise RuntimeError("Stored Google Workspace credential is unavailable.")
    try:
        raw = _fernet().decrypt(value.removeprefix("fernet:").encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError(
            "Stored Google Workspace credential cannot be decrypted."
        ) from exc
    return raw.decode("utf-8")


def tenant_google_workspace_configuration(
    session: Session,
    *,
    company_id: str,
) -> TenantGoogleWorkspaceConfiguration | None:
    return session.scalar(
        select(TenantGoogleWorkspaceConfiguration).where(
            TenantGoogleWorkspaceConfiguration.company_id == company_id
        )
    )


def _ensure_tenant_google_workspace_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> TenantGoogleWorkspaceConfiguration:
    row = tenant_google_workspace_configuration(
        session,
        company_id=context.company.id,
    )
    if row is None:
        row = TenantGoogleWorkspaceConfiguration(
            company_id=context.company.id,
            created_by_membership_id=context.membership.id,
        )
        session.add(row)
        session.flush()
    return row


def _tenant_secret_configured(row: TenantGoogleWorkspaceConfiguration | None) -> bool:
    return bool(row is not None and row.encrypted_client_secret_ref)


def _tenant_connector_redirect(
    row: TenantGoogleWorkspaceConfiguration,
    *,
    connector: GoogleWorkspaceConnector,
) -> str | None:
    if connector == "calendar":
        return row.calendar_redirect_uri
    if connector == "gmail":
        return row.gmail_redirect_uri
    return row.drive_redirect_uri


def _tenant_connector_enabled(
    row: TenantGoogleWorkspaceConfiguration,
    *,
    connector: GoogleWorkspaceConnector,
) -> bool:
    if not row.enabled:
        return False
    if connector == "calendar":
        return row.calendar_enabled
    if connector == "gmail":
        return row.gmail_enabled
    return row.drive_enabled


def _env_oauth_config(*, connector: GoogleWorkspaceConnector) -> GoogleWorkspaceOAuthConfig:
    settings = get_settings()
    if connector == "calendar":
        client_id = settings.google_calendar_client_id
        client_secret = settings.google_calendar_client_secret
        redirect_uri = settings.google_calendar_redirect_uri
    elif connector == "gmail":
        client_id = settings.gmail_client_id
        client_secret = settings.gmail_client_secret
        redirect_uri = settings.gmail_redirect_uri
    else:
        client_id = settings.google_drive_client_id
        client_secret = settings.google_drive_client_secret
        redirect_uri = settings.google_drive_redirect_uri
    missing = []
    if not client_id:
        missing.append(_ENV_REQUIRED_CONFIG_NAMES[connector][0])
    if not client_secret:
        missing.append(_ENV_REQUIRED_CONFIG_NAMES[connector][1])
    if not redirect_uri:
        missing.append(_ENV_REQUIRED_CONFIG_NAMES[connector][2])
    return GoogleWorkspaceOAuthConfig(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        source="environment",
        enabled=True,
        missing_config_names=tuple(missing),
    )


def google_workspace_oauth_config(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
    connector: GoogleWorkspaceConnector,
) -> GoogleWorkspaceOAuthConfig:
    row = None
    if session is not None and context is not None:
        row = tenant_google_workspace_configuration(
            session,
            company_id=context.company.id,
        )
    return _google_workspace_oauth_config_from_row(row, connector=connector)


def _google_workspace_oauth_config_from_row(
    row: TenantGoogleWorkspaceConfiguration | None,
    *,
    connector: GoogleWorkspaceConnector,
) -> GoogleWorkspaceOAuthConfig:
    """Resolve one already-loaded tenant row without repeated tenant queries."""

    if row is not None:
        enabled = _tenant_connector_enabled(row, connector=connector)
        # Disabled rows are an authoritative kill switch. Do not even decrypt
        # their stored secret, and never continue to environment fallback.
        client_secret = (
            _decrypt_secret(row.encrypted_client_secret_ref)
            if enabled
            else None
        )
        redirect_uri = _tenant_connector_redirect(row, connector=connector)
        missing = []
        if not row.client_id:
            missing.append("GOOGLE_WORKSPACE_CLIENT_ID")
        if not client_secret:
            missing.append("GOOGLE_WORKSPACE_CLIENT_SECRET")
        if not redirect_uri:
            missing.append(_CONNECTOR_REQUIRED_CONFIG_NAMES[connector][2])
        if not enabled:
            missing.append(f"GOOGLE_WORKSPACE_{connector.upper()}_ENABLED")
        return GoogleWorkspaceOAuthConfig(
            client_id=row.client_id if enabled else None,
            client_secret=client_secret if enabled else None,
            redirect_uri=redirect_uri if enabled else None,
            source="tenant_admin",
            enabled=enabled,
            missing_config_names=tuple(missing),
        )
    env_config = _env_oauth_config(connector=connector)
    if env_config.configured:
        return env_config
    return GoogleWorkspaceOAuthConfig(
        client_id=env_config.client_id,
        client_secret=env_config.client_secret,
        redirect_uri=env_config.redirect_uri,
        source="missing",
        enabled=True,
        missing_config_names=env_config.missing_config_names,
    )


def _config_items(
    row: TenantGoogleWorkspaceConfiguration | None,
) -> list[GoogleWorkspaceConfigurationItemStatus]:
    if row is not None:
        return [
            GoogleWorkspaceConfigurationItemStatus(
                name="GOOGLE_WORKSPACE_CLIENT_ID",
                configured=bool(row.client_id),
            ),
            GoogleWorkspaceConfigurationItemStatus(
                name="GOOGLE_WORKSPACE_CLIENT_SECRET",
                configured=_tenant_secret_configured(row),
            ),
            GoogleWorkspaceConfigurationItemStatus(
                name="GOOGLE_CALENDAR_REDIRECT_URI",
                configured=bool(row.calendar_redirect_uri),
            ),
            GoogleWorkspaceConfigurationItemStatus(
                name="GMAIL_REDIRECT_URI",
                configured=bool(row.gmail_redirect_uri),
            ),
            GoogleWorkspaceConfigurationItemStatus(
                name="GOOGLE_DRIVE_REDIRECT_URI",
                configured=bool(row.drive_redirect_uri),
            ),
        ]
    calendar = _env_oauth_config(connector="calendar")
    gmail = _env_oauth_config(connector="gmail")
    drive = _env_oauth_config(connector="drive")
    return [
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_CALENDAR_CLIENT_ID",
            configured=bool(calendar.client_id),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_CALENDAR_CLIENT_SECRET",
            configured=bool(calendar.client_secret),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_CALENDAR_REDIRECT_URI",
            configured=bool(calendar.redirect_uri),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GMAIL_CLIENT_ID",
            configured=bool(gmail.client_id),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GMAIL_CLIENT_SECRET",
            configured=bool(gmail.client_secret),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GMAIL_REDIRECT_URI",
            configured=bool(gmail.redirect_uri),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_DRIVE_CLIENT_ID",
            configured=bool(drive.client_id),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_DRIVE_CLIENT_SECRET",
            configured=bool(drive.client_secret),
        ),
        GoogleWorkspaceConfigurationItemStatus(
            name="GOOGLE_DRIVE_REDIRECT_URI",
            configured=bool(drive.redirect_uri),
        ),
    ]


def _approval_items(
    row: TenantGoogleWorkspaceConfiguration | None,
) -> list[GoogleWorkspaceApprovalItemStatus]:
    required_scopes: set[str] = set()
    if row is not None and row.enabled:
        if row.calendar_enabled:
            required_scopes.update(GOOGLE_WORKSPACE_CALENDAR_SCOPES)
        if row.gmail_enabled:
            required_scopes.update(GOOGLE_WORKSPACE_GMAIL_SCOPES)
        if row.drive_enabled:
            required_scopes.update(GOOGLE_WORKSPACE_DRIVE_SCOPES)
    approved_scopes = set(row.scopes_json or ()) if row is not None else set()
    items: list[GoogleWorkspaceApprovalItemStatus] = []
    for key, label in _APPROVAL_LABELS.items():
        approved = bool(getattr(row, key, False)) if row is not None else False
        if key == "scopes_approved":
            # Scope authority is meaningful only when it covers every enabled
            # connector.  The stored boolean alone must never bless a partial
            # or invented permission set.
            approved = bool(
                approved
                and required_scopes
                and required_scopes.issubset(approved_scopes)
            )
        items.append(
            GoogleWorkspaceApprovalItemStatus(
                key=key,
                label=label,
                approved=approved,
            )
        )
    return items


def _machine_control_items(
    *,
    row: TenantGoogleWorkspaceConfiguration | None,
    connector_configs: dict[
        GoogleWorkspaceConnector,
        GoogleWorkspaceOAuthConfig,
    ],
) -> list[GoogleWorkspaceMachineReadinessControlStatus]:
    provider_retry_ready = bool(
        DEFAULT_SAFE_HTTP_RETRY_MAX_ATTEMPTS >= 2
        and DEFAULT_SAFE_HTTP_RETRY_BACKOFF_SECONDS > 0
        and {"GET", "HEAD"}.issubset(SAFE_RETRY_METHODS)
        and {408, 429, 500, 502, 503, 504}.issubset(
            RETRYABLE_READ_STATUS_CODES
        )
    )
    settings = get_settings()
    webhook_values = (
        bool(settings.gmail_pubsub_topic),
        bool(settings.gmail_webhook_verification_token),
    )
    gmail_enabled = bool(row is None or (row.enabled and row.gmail_enabled))
    webhook_configuration_consistent = bool(
        not gmail_enabled or all(webhook_values) or not any(webhook_values)
    )
    disable_boundary_ready = bool(
        row is None
        or row.enabled
        or all(
            not connector_configs[connector].configured
            for connector in ("calendar", "gmail", "drive")
        )
    )
    redaction_probe = "client_secret=connector-readiness-secret"
    redacted = redact_provider_error(redaction_probe)
    return [
        GoogleWorkspaceMachineReadinessControlStatus(
            key="provider_retry_policy",
            label="Bounded provider retry policy",
            version="provider-delivery-retry/v1",
            status="passed" if provider_retry_ready else "failed",
            detail=(
                "Safe read-only provider retries are bounded with exponential backoff."
                if provider_retry_ready
                else "Safe provider retry policy is incomplete or unbounded."
            ),
        ),
        GoogleWorkspaceMachineReadinessControlStatus(
            key="gmail_webhook_disable_boundary",
            label="Gmail webhook configuration and disable boundary",
            version="gmail-webhook-fail-closed/v1",
            status="passed" if webhook_configuration_consistent else "blocked",
            detail=(
                "Gmail is tenant-disabled; webhook delivery remains disabled."
                if not gmail_enabled
                else (
                    "Webhook signing configuration is complete."
                    if all(webhook_values)
                    else (
                        "Webhook delivery is fail-closed disabled because no webhook "
                        "configuration is present."
                        if not any(webhook_values)
                        else "Webhook configuration is partial; configure both required values."
                    )
                )
            ),
        ),
        GoogleWorkspaceMachineReadinessControlStatus(
            key="tenant_disable_boundary",
            label="Tenant connector disable boundary",
            version="google-workspace-tenant-disable/v1",
            status="passed" if disable_boundary_ready else "failed",
            detail=(
                "Disabled tenant connectors cannot fall back to environment credentials."
                if disable_boundary_ready
                else "Tenant disable boundary did not fail closed."
            ),
        ),
        GoogleWorkspaceMachineReadinessControlStatus(
            key="provider_error_redaction",
            label="Provider error redaction policy",
            version="provider-error-redaction/v1",
            status=(
                "passed"
                if "connector-readiness-secret" not in redacted
                else "failed"
            ),
            detail="Secret-bearing provider errors are redacted before persistence.",
        ),
    ]


def _enabled_connectors(
    row: TenantGoogleWorkspaceConfiguration | None,
) -> tuple[GoogleWorkspaceConnector, ...]:
    if row is None:
        return ("calendar", "gmail", "drive")
    if not row.enabled:
        return ()
    enabled: list[GoogleWorkspaceConnector] = []
    if row.calendar_enabled:
        enabled.append("calendar")
    if row.gmail_enabled:
        enabled.append("gmail")
    if row.drive_enabled:
        enabled.append("drive")
    return tuple(enabled)


def google_workspace_connector_missing_config_names(
    session: Session | None,
    *,
    context: SessionContext | None,
    connector: GoogleWorkspaceConnector,
) -> list[str]:
    config = google_workspace_oauth_config(
        session,
        context=context,
        connector=connector,
    )
    return list(config.missing_config_names)


def google_workspace_connector_configured(
    session: Session | None,
    *,
    context: SessionContext | None,
    connector: GoogleWorkspaceConnector,
) -> bool:
    return google_workspace_oauth_config(
        session,
        context=context,
        connector=connector,
    ).configured


def _connection_counts(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleWorkspaceConnectionCounts:
    calendar_total = session.scalar(
        select(func.count(UserCalendarConnection.id)).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.provider == CalendarProvider.GOOGLE_CALENDAR,
        )
    ) or 0
    calendar_connected = session.scalar(
        select(func.count(UserCalendarConnection.id)).where(
            UserCalendarConnection.company_id == context.company.id,
            UserCalendarConnection.provider == CalendarProvider.GOOGLE_CALENDAR,
            UserCalendarConnection.status == CalendarConnectionStatus.CONNECTED,
        )
    ) or 0
    gmail_total = session.scalar(
        select(func.count(UserMailboxConnection.id)).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
        )
    ) or 0
    gmail_connected = session.scalar(
        select(func.count(UserMailboxConnection.id)).where(
            UserMailboxConnection.company_id == context.company.id,
            UserMailboxConnection.provider == MailboxProvider.GMAIL,
            UserMailboxConnection.status == MailboxConnectionStatus.CONNECTED,
        )
    ) or 0
    drive_total = session.scalar(
        select(func.count(UserDriveConnection.id)).where(
            UserDriveConnection.company_id == context.company.id,
            UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
        )
    ) or 0
    drive_connected = session.scalar(
        select(func.count(UserDriveConnection.id)).where(
            UserDriveConnection.company_id == context.company.id,
            UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE,
            UserDriveConnection.status == DriveConnectionStatus.CONNECTED,
        )
    ) or 0
    return GoogleWorkspaceConnectionCounts(
        calendar_connection_count=int(calendar_total),
        gmail_connection_count=int(gmail_total),
        drive_connection_count=int(drive_total),
        connected_calendar_account_count=int(calendar_connected),
        connected_gmail_account_count=int(gmail_connected),
        connected_drive_account_count=int(drive_connected),
    )


def _readiness_value(
    *,
    configured: bool,
    approvals_ready: bool,
    machine_controls_ready: bool,
    last_test_status: str | None,
) -> str:
    if (
        configured
        and approvals_ready
        and machine_controls_ready
        and last_test_status == "passed"
    ):
        return "ready_for_user_connections"
    return "blocked_pending_admin_configuration"


def google_workspace_tenant_configuration_status(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleWorkspaceTenantConfigurationResponse:
    row = tenant_google_workspace_configuration(session, company_id=context.company.id)
    enabled_connectors = _enabled_connectors(row)
    connector_configs = {
        connector: _google_workspace_oauth_config_from_row(
            row,
            connector=connector,
        )
        for connector in ("calendar", "gmail", "drive")
    }
    connector_configured = {
        connector: config.configured
        for connector, config in connector_configs.items()
    }
    required_config = _config_items(row)
    required_approvals = _approval_items(row)
    machine_controls = _machine_control_items(
        row=row,
        connector_configs=connector_configs,
    )
    missing_config_names: list[str] = []
    if row is not None:
        for connector in enabled_connectors:
            for name in connector_configs[connector].missing_config_names:
                if name not in missing_config_names:
                    missing_config_names.append(name)
    else:
        for item in required_config:
            if not item.configured:
                missing_config_names.append(item.name)
    missing_approval_keys = [
        item.key for item in required_approvals if not item.approved
    ]
    missing_machine_control_keys = [
        item.key for item in machine_controls if item.status != "passed"
    ]
    configured = bool(
        enabled_connectors
        and all(connector_configured[connector] for connector in enabled_connectors)
    )
    if row is not None:
        config_source = "tenant_admin"
        enabled = bool(row.enabled)
        calendar_enabled = bool(row.enabled and row.calendar_enabled)
        gmail_enabled = bool(row.enabled and row.gmail_enabled)
        drive_enabled = bool(row.enabled and row.drive_enabled)
        last_test_status = row.last_test_status
        last_tested_at = row.last_tested_at
        last_error_redacted = row.last_error_redacted
        scopes = list(row.scopes_json or GOOGLE_WORKSPACE_SCOPES)
    else:
        config_source = "environment" if configured else "missing"
        enabled = configured
        calendar_enabled = connector_configured["calendar"]
        gmail_enabled = connector_configured["gmail"]
        drive_enabled = connector_configured["drive"]
        last_test_status = "not_run"
        last_tested_at = None
        last_error_redacted = None
        scopes = list(GOOGLE_WORKSPACE_SCOPES)
    approvals_ready = not missing_approval_keys if row is not None else False
    return GoogleWorkspaceTenantConfigurationResponse(
        configured=configured,
        config_source=config_source,  # type: ignore[arg-type]
        enabled=enabled,
        calendar_enabled=calendar_enabled,
        gmail_enabled=gmail_enabled,
        drive_enabled=drive_enabled,
        required_config=required_config,
        required_approvals=required_approvals,
        machine_control_version=GOOGLE_WORKSPACE_MACHINE_CONTROL_VERSION,
        machine_controls=machine_controls,
        approved_scopes=scopes,
        missing_config_names=missing_config_names,
        missing_approval_keys=missing_approval_keys,
        missing_machine_control_keys=missing_machine_control_keys,
        connection_counts=_connection_counts(session, context=context),
        last_test_status=last_test_status,  # type: ignore[arg-type]
        last_tested_at=last_tested_at,
        last_error_redacted=last_error_redacted,
        readiness=_readiness_value(
            configured=configured,
            approvals_ready=approvals_ready,
            machine_controls_ready=not missing_machine_control_keys,
            last_test_status=last_test_status,
        ),  # type: ignore[arg-type]
    )


def update_google_workspace_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
    payload: GoogleWorkspaceTenantConfigurationUpdateRequest,
) -> GoogleWorkspaceTenantConfigurationResponse:
    row = _ensure_tenant_google_workspace_configuration(session, context=context)
    if payload.client_id is not None:
        row.client_id = payload.client_id
    if payload.client_secret is not None:
        row.encrypted_client_secret_ref = _encrypt_secret(payload.client_secret)
    if payload.calendar_redirect_uri is not None:
        row.calendar_redirect_uri = payload.calendar_redirect_uri
    if payload.gmail_redirect_uri is not None:
        row.gmail_redirect_uri = payload.gmail_redirect_uri
    if payload.drive_redirect_uri is not None:
        row.drive_redirect_uri = payload.drive_redirect_uri
    row.scopes_json = list(payload.scopes or GOOGLE_WORKSPACE_SCOPES)
    row.oauth_consent_model_approved = payload.oauth_consent_model_approved
    row.scopes_approved = payload.scopes_approved
    row.calendar_enabled = payload.calendar_enabled
    row.gmail_enabled = payload.gmail_enabled
    row.drive_enabled = payload.drive_enabled
    row.enabled = payload.enabled
    row.updated_by_membership_id = context.membership.id
    row.last_test_status = "not_run"
    row.last_tested_at = None
    row.last_error_redacted = None
    session.add(row)
    record_from_context(
        session,
        context,
        action="google_workspace.configuration.updated",
        target_type="tenant_google_workspace_configuration",
        target_id=row.id,
        metadata={
            "configured_names": [
                item.name for item in _config_items(row) if item.configured
            ],
            "approved_keys": [
                item.key for item in _approval_items(row) if item.approved
            ],
            "machine_control_version": GOOGLE_WORKSPACE_MACHINE_CONTROL_VERSION,
            "enabled": row.enabled,
            "calendar_enabled": row.calendar_enabled,
            "gmail_enabled": row.gmail_enabled,
            "drive_enabled": row.drive_enabled,
        },
    )
    session.commit()
    return google_workspace_tenant_configuration_status(session, context=context)


def test_google_workspace_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> GoogleWorkspaceReadinessTestResponse:
    row = _ensure_tenant_google_workspace_configuration(session, context=context)
    tested_at = datetime.now(UTC)
    status_summary = google_workspace_tenant_configuration_status(
        session,
        context=context,
    )
    checks: list[GoogleWorkspaceReadinessCheckResult] = []
    for item in status_summary.required_config:
        checks.append(
            GoogleWorkspaceReadinessCheckResult(
                key=item.name,
                label=item.name,
                status="passed" if item.configured else "blocked",
                detail=None if item.configured else "Missing configuration value.",
            )
        )
    for item in status_summary.required_approvals:
        checks.append(
            GoogleWorkspaceReadinessCheckResult(
                key=item.key,
                label=item.label,
                status="passed" if item.approved else "blocked",
                detail=None if item.approved else "Tenant admin approval is pending.",
            )
        )
    for item in status_summary.machine_controls:
        checks.append(
            GoogleWorkspaceReadinessCheckResult(
                key=item.key,
                label=f"{item.label} ({item.version})",
                status=item.status,
                detail=item.detail,
            )
        )
    if not (
        status_summary.calendar_enabled
        or status_summary.gmail_enabled
        or status_summary.drive_enabled
    ):
        checks.append(
            GoogleWorkspaceReadinessCheckResult(
                key="google_workspace_enabled_service",
                label="At least one Google Workspace service enabled",
                status="blocked",
                detail="Enable Calendar, Gmail, or Drive before users connect.",
            )
        )
    passed = all(item.status == "passed" for item in checks)
    row.last_test_status = "passed" if passed else "blocked"
    row.last_tested_at = tested_at
    row.last_error_redacted = (
        None
        if passed
        else "Configuration, provider authority, or machine controls are incomplete."
    )
    session.add(row)
    record_from_context(
        session,
        context,
        action="google_workspace.configuration.tested",
        target_type="tenant_google_workspace_configuration",
        target_id=row.id,
        result="success" if passed else "blocked",
        metadata={
            "status": row.last_test_status,
            "missing_config_names": status_summary.missing_config_names,
            "missing_approval_keys": status_summary.missing_approval_keys,
            "missing_machine_control_keys": (
                status_summary.missing_machine_control_keys
            ),
            "machine_control_version": GOOGLE_WORKSPACE_MACHINE_CONTROL_VERSION,
            "external_provider_calls": 0,
        },
    )
    session.commit()
    latest = google_workspace_tenant_configuration_status(session, context=context)
    return GoogleWorkspaceReadinessTestResponse(
        status=row.last_test_status,  # type: ignore[arg-type]
        checks=checks,
        machine_control_version=GOOGLE_WORKSPACE_MACHINE_CONTROL_VERSION,
        readiness=latest.readiness,
        tested_at=tested_at,
    )


__all__ = [
    "GOOGLE_WORKSPACE_CALENDAR_SCOPES",
    "GOOGLE_WORKSPACE_DRIVE_SCOPES",
    "GOOGLE_WORKSPACE_GMAIL_SCOPES",
    "GOOGLE_WORKSPACE_SCOPES",
    "GoogleWorkspaceOAuthConfig",
    "google_workspace_connector_configured",
    "google_workspace_connector_missing_config_names",
    "google_workspace_oauth_config",
    "google_workspace_tenant_configuration_status",
    "tenant_google_workspace_configuration",
    "test_google_workspace_tenant_configuration",
    "update_google_workspace_tenant_configuration",
]
