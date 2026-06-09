from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    CalendarEventSync,
    CalendarProvider,
    DriveProvider,
    MailboxMessageImport,
    MailboxProvider,
    UserCalendarConnection,
    UserDriveConnection,
    UserMailboxConnection,
)
from caseops_api.schemas.integrations import ConnectorRecord, TenantConnectorRecord
from caseops_api.services.calendar_sync import (
    GOOGLE_CALENDAR_SCOPES,
    OUTLOOK_SCOPES,
    outlook_tenant_configuration_status,
)
from caseops_api.services.google_drive_imports import google_drive_provider_config_status
from caseops_api.services.google_workspace import (
    GOOGLE_WORKSPACE_DRIVE_SCOPES,
    GOOGLE_WORKSPACE_GMAIL_SCOPES,
    google_workspace_connector_configured,
    google_workspace_connector_missing_config_names,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.saas_billing import provider_readiness as billing_provider_readiness

TENANT_FORBIDDEN_PLATFORM_FIELDS = {
    "internal_cost_label",
    "risk_label",
    "platform_notes",
}


def _status(
    *,
    enabled: bool,
    configured: bool,
    blocked: bool,
    degraded: bool = False,
) -> str:
    if not enabled:
        return "disabled"
    if blocked or not configured:
        return "blocked"
    if degraded:
        return "degraded"
    return "healthy"


def _record(
    *,
    key: str,
    name: str,
    category: str,
    provider: str,
    enabled: bool,
    configured: bool,
    blocked: bool,
    degraded: bool = False,
    last_success: datetime | None = None,
    last_failure: datetime | None = None,
    next_run: datetime | None = None,
    webhook_status: str | None = None,
    token_expiry: datetime | None = None,
    required_config_names: list[str] | None = None,
    scopes: list[str] | None = None,
    runbook_link: str | None = None,
    provider_operations_link: str | None = "/app/admin/provider-operations",
    internal_cost_label: str | None = None,
    risk_label: str | None = None,
    platform_notes: list[str] | None = None,
    platform: bool = False,
) -> ConnectorRecord:
    status = _status(
        enabled=enabled,
        configured=configured,
        blocked=blocked,
        degraded=degraded,
    )
    return ConnectorRecord(
        key=key,
        name=name,
        category=category,
        provider=provider,
        status=status,  # type: ignore[arg-type]
        enabled=enabled,
        configured=configured,
        blocked=blocked or not configured,
        healthy=status == "healthy",
        degraded=status == "degraded",
        last_success=last_success,
        last_failure=last_failure,
        next_run=next_run,
        webhook_status=webhook_status,
        token_expiry=token_expiry,
        required_config_names=required_config_names or [],
        scopes=scopes or [],
        runbook_link=runbook_link,
        provider_operations_link=provider_operations_link,
        internal_cost_label=internal_cost_label if platform else None,
        risk_label=risk_label if platform else None,
        platform_notes=platform_notes or [],
    )


def _max_calendar_sync_times(
    session: Session,
    *,
    company_id: str | None,
    provider: CalendarProvider,
) -> tuple[datetime | None, datetime | None]:
    filters = [UserCalendarConnection.provider == provider]
    if company_id:
        filters.append(CalendarEventSync.company_id == company_id)
    last_success = session.scalar(
        select(func.max(CalendarEventSync.last_synced_at))
        .join(
            UserCalendarConnection,
            UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
        )
        .where(*filters)
    )
    last_failure = session.scalar(
        select(func.max(CalendarEventSync.updated_at))
        .join(
            UserCalendarConnection,
            UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
        )
        .where(*filters, CalendarEventSync.sync_status.in_(("failed", "dead_letter")))
    )
    return last_success, last_failure


def _config_missing(required: list[tuple[str, object | None]]) -> list[str]:
    return [name for name, value in required if not value]


def _sendgrid_missing() -> list[str]:
    settings = get_settings()
    return _config_missing(
        [
            ("SENDGRID_API_KEY", settings.sendgrid_api_key),
            ("SENDGRID_SENDER_EMAIL", settings.sendgrid_sender_email),
            ("SENDGRID_WEBHOOK_PUBLIC_KEY", settings.sendgrid_webhook_public_key),
        ]
    )


def _gmail_missing() -> list[str]:
    settings = get_settings()
    return _config_missing(
        [
            ("GMAIL_CLIENT_ID", settings.gmail_client_id),
            ("GMAIL_CLIENT_SECRET", settings.gmail_client_secret),
            ("GMAIL_REDIRECT_URI", settings.gmail_redirect_uri),
        ]
    )


def _gmail_webhook_missing() -> list[str]:
    settings = get_settings()
    return _config_missing(
        [
            ("GMAIL_PUBSUB_TOPIC", settings.gmail_pubsub_topic),
            ("GMAIL_WEBHOOK_VERIFICATION_TOKEN", settings.gmail_webhook_verification_token),
        ]
    )


def _max_gmail_times(
    session: Session,
    *,
    company_id: str | None,
) -> tuple[datetime | None, datetime | None]:
    filters = [UserMailboxConnection.provider == MailboxProvider.GMAIL]
    if company_id:
        filters.append(MailboxMessageImport.company_id == company_id)
    last_success = session.scalar(
        select(func.max(MailboxMessageImport.updated_at))
        .join(
            UserMailboxConnection,
            UserMailboxConnection.id == MailboxMessageImport.mailbox_connection_id,
        )
        .where(*filters, MailboxMessageImport.status == "imported")
    )
    last_failure = session.scalar(
        select(func.max(MailboxMessageImport.updated_at))
        .join(
            UserMailboxConnection,
            UserMailboxConnection.id == MailboxMessageImport.mailbox_connection_id,
        )
        .where(*filters, MailboxMessageImport.status.in_(("failed", "dead_letter")))
    )
    return last_success, last_failure


def _max_drive_times(
    session: Session,
    *,
    company_id: str | None,
) -> tuple[datetime | None, datetime | None]:
    filters = [UserDriveConnection.provider == DriveProvider.GOOGLE_DRIVE]
    if company_id:
        filters.append(UserDriveConnection.company_id == company_id)
    last_success = session.scalar(
        select(func.max(UserDriveConnection.last_list_at)).where(*filters)
    )
    last_failure = session.scalar(
        select(func.max(UserDriveConnection.updated_at)).where(
            *filters,
            UserDriveConnection.status == "error",
        )
    )
    return last_success, last_failure


def _sms_missing() -> list[str]:
    settings = get_settings()
    if settings.twilio_enabled:
        return _config_missing(
            [
                ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
                ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
                ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
            ]
        )
    return _config_missing(
        [
            ("TWILIO_ENABLED_OR_MSG91_AUTH_KEY", settings.msg91_auth_key),
            ("MSG91_SENDER_ID", settings.msg91_sender_id),
        ]
    )


def _whatsapp_missing() -> list[str]:
    settings = get_settings()
    return _config_missing(
        [
            ("WHATSAPP_ACCESS_TOKEN", settings.whatsapp_access_token),
            ("WHATSAPP_PHONE_NUMBER_ID", settings.whatsapp_phone_number_id),
            ("WHATSAPP_TEMPLATE_NAME", settings.whatsapp_template_name),
        ]
    )


def _pine_labs_required_config() -> list[str]:
    return [
        "PINE_LABS_API_BASE_URL",
        "PINE_LABS_CLIENT_ID_OR_API_KEY",
        "PINE_LABS_CLIENT_SECRET_OR_API_SECRET",
        "PINE_LABS_MERCHANT_ID",
        "PINE_LABS_WEBHOOK_SECRET",
    ]


def _pine_labs_missing() -> list[str]:
    settings = get_settings()
    return _config_missing(
        [
            ("PINE_LABS_API_BASE_URL", settings.pine_labs_api_base_url),
            (
                "PINE_LABS_CLIENT_ID_OR_API_KEY",
                settings.pine_labs_client_id or settings.pine_labs_api_key,
            ),
            (
                "PINE_LABS_CLIENT_SECRET_OR_API_SECRET",
                settings.pine_labs_client_secret or settings.pine_labs_api_secret,
            ),
            ("PINE_LABS_MERCHANT_ID", settings.pine_labs_merchant_id),
            ("PINE_LABS_WEBHOOK_SECRET", settings.pine_labs_webhook_secret),
        ]
    )


def _storage_required() -> list[str]:
    settings = get_settings()
    if settings.document_storage_backend == "gcs":
        return ["DOCUMENT_STORAGE_GCS_BUCKET", "DOCUMENT_STORAGE_GCS_PREFIX"]
    return ["DOCUMENT_STORAGE_PATH", "DOCUMENT_STORAGE_CACHE_PATH"]


def connector_registry(
    session: Session,
    *,
    context: SessionContext | None = None,
    platform: bool = False,
) -> list[ConnectorRecord]:
    settings = get_settings()
    company_id = None if platform or context is None else context.company.id
    last_outlook_success, last_outlook_failure = _max_calendar_sync_times(
        session,
        company_id=company_id,
        provider=CalendarProvider.OUTLOOK,
    )
    last_google_calendar_success, last_google_calendar_failure = _max_calendar_sync_times(
        session,
        company_id=company_id,
        provider=CalendarProvider.GOOGLE_CALENDAR,
    )
    last_gmail_success, last_gmail_failure = _max_gmail_times(
        session,
        company_id=company_id,
    )
    last_drive_success, last_drive_failure = _max_drive_times(
        session,
        company_id=company_id,
    )
    if context is not None and not platform:
        outlook = outlook_tenant_configuration_status(session, context=context)
        outlook_configured = outlook.configured
        outlook_enabled = outlook.enabled
        outlook_blocked = outlook.adp20_readiness != "ready_for_adp20_implementation"
        outlook_required = [item.name for item in outlook.required_config]
        outlook_scopes = outlook.approved_scopes
    else:
        outlook_missing = _config_missing(
            [
                ("OUTLOOK_CLIENT_ID", settings.outlook_client_id),
                ("OUTLOOK_CLIENT_SECRET", settings.outlook_client_secret),
                ("OUTLOOK_REDIRECT_URI", settings.outlook_redirect_uri),
            ]
        )
        outlook_configured = not outlook_missing
        outlook_enabled = outlook_configured
        outlook_blocked = not outlook_configured
        outlook_required = [
            "OUTLOOK_CLIENT_ID",
            "OUTLOOK_CLIENT_SECRET",
            "OUTLOOK_REDIRECT_URI",
            "OUTLOOK_TENANT_ID_OR_APPROVED_TENANT_MODE",
        ]
        outlook_scopes = list(OUTLOOK_SCOPES)

    if context is not None and not platform:
        google_calendar_missing = google_workspace_connector_missing_config_names(
            session,
            context=context,
            connector="calendar",
        )
        google_calendar_configured = google_workspace_connector_configured(
            session,
            context=context,
            connector="calendar",
        )
        gmail_missing = google_workspace_connector_missing_config_names(
            session,
            context=context,
            connector="gmail",
        )
        gmail_configured = google_workspace_connector_configured(
            session,
            context=context,
            connector="gmail",
        )
        drive_configured = google_workspace_connector_configured(
            session,
            context=context,
            connector="drive",
        )
        google_calendar_required = [
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        ]
        gmail_required = [
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GMAIL_REDIRECT_URI",
            "GMAIL_PUBSUB_TOPIC",
            "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
        ]
        drive_required = [
            "GOOGLE_WORKSPACE_CLIENT_ID",
            "GOOGLE_WORKSPACE_CLIENT_SECRET",
            "GOOGLE_DRIVE_REDIRECT_URI",
        ]
    else:
        drive_status = google_drive_provider_config_status()
        google_calendar_missing = _config_missing(
            [
                ("GOOGLE_CALENDAR_CLIENT_ID", settings.google_calendar_client_id),
                (
                    "GOOGLE_CALENDAR_CLIENT_SECRET",
                    settings.google_calendar_client_secret,
                ),
                ("GOOGLE_CALENDAR_REDIRECT_URI", settings.google_calendar_redirect_uri),
            ]
        )
        google_calendar_configured = not google_calendar_missing
        gmail_missing = _gmail_missing()
        gmail_configured = not gmail_missing
        drive_configured = drive_status.configured
        google_calendar_required = [
            "GOOGLE_CALENDAR_CLIENT_ID",
            "GOOGLE_CALENDAR_CLIENT_SECRET",
            "GOOGLE_CALENDAR_REDIRECT_URI",
        ]
        gmail_required = [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REDIRECT_URI",
            "GMAIL_PUBSUB_TOPIC",
            "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
        ]
        drive_required = [
            "GOOGLE_DRIVE_CLIENT_ID",
            "GOOGLE_DRIVE_CLIENT_SECRET",
            "GOOGLE_DRIVE_REDIRECT_URI",
        ]
    gmail_webhook_missing = _gmail_webhook_missing()
    gmail_webhook_configured = not gmail_webhook_missing
    sendgrid_missing = _sendgrid_missing()
    sms_missing = _sms_missing()
    whatsapp_missing = _whatsapp_missing()
    pine_missing = _pine_labs_missing()
    billing_readiness = billing_provider_readiness()
    storage_required = _storage_required()
    storage_missing = (
        _config_missing(
            [
                ("DOCUMENT_STORAGE_GCS_BUCKET", settings.document_storage_gcs_bucket),
                ("DOCUMENT_STORAGE_GCS_PREFIX", settings.document_storage_gcs_prefix),
            ]
        )
        if settings.document_storage_backend == "gcs"
        else _config_missing(
            [
                ("DOCUMENT_STORAGE_PATH", settings.document_storage_path),
                ("DOCUMENT_STORAGE_CACHE_PATH", settings.document_storage_cache_path),
            ]
        )
    )
    temporal_required = ["DURABLE_WORKFLOWS_ENABLED"]
    if settings.durable_workflows_backend == "temporal":
        temporal_required.extend(["TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE"])
    temporal_missing = (
        ["DURABLE_WORKFLOWS_ENABLED"]
        if not settings.durable_workflows_enabled
        else _config_missing(
            [
                ("TEMPORAL_ADDRESS", settings.temporal_address)
                if settings.durable_workflows_backend == "temporal"
                else ("DURABLE_WORKFLOWS_BACKEND", settings.durable_workflows_backend),
            ]
        )
    )
    clam_required = ["CLAMAV_HOST", "CLAMAV_PORT", "CLAMAV_REQUIRED"]
    clam_host = os.environ.get("CASEOPS_CLAMAV_HOST", "").strip()
    clam_required_flag = os.environ.get("CASEOPS_CLAMAV_REQUIRED", "").strip().lower()
    clam_enabled = bool(clam_host) or clam_required_flag in {"1", "true", "yes", "on"}

    connectors = [
        _record(
            key="outlook_calendar",
            name="Outlook calendar",
            category="calendar",
            provider="microsoft_graph",
            enabled=outlook_enabled,
            configured=outlook_configured,
            blocked=outlook_blocked,
            degraded=bool(
                last_outlook_failure
                and (
                    not last_outlook_success
                    or last_outlook_failure > last_outlook_success
                )
            ),
            last_success=last_outlook_success,
            last_failure=last_outlook_failure,
            webhook_status="not_enabled",
            required_config_names=outlook_required,
            scopes=outlook_scopes,
            runbook_link="docs/runbooks/adp20-outlook-provider-readiness.md",
            internal_cost_label="calendar sync variable cost",
            risk_label="OAuth/provider retry risk",
            platform_notes=["CaseOps-to-Outlook hearings only; no mailbox ingestion."],
            platform=platform,
        ),
        _record(
            key="microsoft_mailbox",
            name="Microsoft mailbox readiness",
            category="mailbox",
            provider="microsoft_graph",
            enabled=False,
            configured=False,
            blocked=True,
            webhook_status="not_enabled",
            required_config_names=[
                "MAILBOX_CONNECTOR_PROVIDER",
                "MAILBOX_CLIENT_ID",
                "MAILBOX_CLIENT_SECRET",
                "MAILBOX_WEBHOOK_SIGNING_SECRET",
            ],
            scopes=["Mail.Read", "Mail.ReadBasic"],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="mailbox ingestion pending",
            risk_label="token/raw-email leakage risk",
            platform_notes=["Readiness only; polling and provider webhooks are disabled."],
            platform=platform,
        ),
        _record(
            key="gmail",
            name="Gmail",
            category="mailbox",
            provider="google",
            enabled=gmail_configured,
            configured=gmail_configured,
            blocked=not gmail_configured,
            degraded=bool(
                last_gmail_failure
                and (not last_gmail_success or last_gmail_failure > last_gmail_success)
            ),
            last_success=last_gmail_success,
            last_failure=last_gmail_failure,
            webhook_status="configured" if gmail_webhook_configured else "missing",
            required_config_names=gmail_required,
            scopes=list(GOOGLE_WORKSPACE_GMAIL_SCOPES),
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="mailbox metadata ingestion cost driver",
            risk_label="OAuth/raw-email risk",
            platform_notes=[
                "Metadata/snippet import only; attachment bytes require review approval.",
                (
                    "Webhook processing remains blocked until Pub/Sub and verification "
                    "token are configured."
                ),
            ],
            platform=platform,
        ),
        _record(
            key="google_calendar",
            name="Google Calendar",
            category="calendar",
            provider="google",
            enabled=google_calendar_configured,
            configured=google_calendar_configured,
            blocked=not google_calendar_configured,
            degraded=bool(
                last_google_calendar_failure
                and (
                    not last_google_calendar_success
                    or last_google_calendar_failure > last_google_calendar_success
                )
            ),
            last_success=last_google_calendar_success,
            last_failure=last_google_calendar_failure,
            webhook_status="not_enabled",
            required_config_names=google_calendar_required,
            scopes=list(GOOGLE_CALENDAR_SCOPES),
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="calendar sync variable cost",
            risk_label="OAuth/provider retry risk",
            platform_notes=[
                "CaseOps-to-Google hearings only; no Gmail or Drive sync here.",
            ],
            platform=platform,
        ),
        _record(
            key="google_drive",
            name="Google Drive",
            category="documents",
            provider="google",
            enabled=drive_configured,
            configured=drive_configured,
            blocked=not drive_configured,
            degraded=bool(
                last_drive_failure
                and (
                    not last_drive_success
                    or last_drive_failure > last_drive_success
                )
            ),
            last_success=last_drive_success,
            last_failure=last_drive_failure,
            webhook_status="not_enabled",
            required_config_names=drive_required,
            scopes=list(GOOGLE_WORKSPACE_DRIVE_SCOPES),
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="document processing/storage cost driver",
            risk_label="OAuth/file-content risk",
            platform_notes=[
                "User Drive OAuth and metadata listing only; no durable Drive sync.",
            ],
            platform=platform,
        ),
        _record(
            key="pine_labs",
            name="Pine Labs Plural",
            category="payments",
            provider="pine_labs_plural",
            enabled=False,
            configured=not pine_missing,
            blocked=True,
            webhook_status="configured" if settings.pine_labs_webhook_secret else "missing",
            required_config_names=_pine_labs_required_config(),
            scopes=[],
            runbook_link="docs/runbooks/pine-labs-uat-readiness-2026-06-02.md",
            provider_operations_link=(
                "/app/platform-admin/provider-events" if platform else "/app/admin/billing"
            ),
            internal_cost_label="payment MDR/fixed-fee",
            risk_label="production payments disabled",
            platform_notes=[
                (
                    "Payment provider reports "
                    f"provider_disabled={billing_readiness['provider_disabled']}."
                ),
                "Do not enable live payments until founder UAT go/no-go.",
            ],
            platform=platform,
        ),
        _record(
            key="sendgrid",
            name="SendGrid",
            category="email",
            provider="sendgrid",
            enabled=not sendgrid_missing,
            configured=not sendgrid_missing,
            blocked=bool(sendgrid_missing),
            webhook_status="configured" if settings.sendgrid_webhook_public_key else "missing",
            required_config_names=[
                "SENDGRID_API_KEY",
                "SENDGRID_SENDER_EMAIL",
                "SENDGRID_WEBHOOK_PUBLIC_KEY",
            ],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="email delivery unit cost",
            risk_label="bounce/suppression webhook risk",
            platform=platform,
        ),
        _record(
            key="sms",
            name="SMS",
            category="messaging",
            provider="twilio_or_msg91",
            enabled=settings.twilio_enabled and not sms_missing,
            configured=not sms_missing,
            blocked=bool(sms_missing) or not settings.twilio_enabled,
            webhook_status="not_enabled",
            required_config_names=[
                "TWILIO_ACCOUNT_SID",
                "TWILIO_AUTH_TOKEN",
                "TWILIO_FROM_NUMBER",
                "MSG91_AUTH_KEY",
                "MSG91_SENDER_ID",
            ],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="SMS message cost",
            risk_label="external delivery disabled",
            platform=platform,
        ),
        _record(
            key="whatsapp",
            name="WhatsApp",
            category="messaging",
            provider="meta_cloud_api",
            enabled=settings.whatsapp_enabled and not whatsapp_missing,
            configured=not whatsapp_missing,
            blocked=bool(whatsapp_missing) or not settings.whatsapp_enabled,
            webhook_status="not_enabled",
            required_config_names=[
                "WHATSAPP_ACCESS_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID",
                "WHATSAPP_TEMPLATE_NAME",
            ],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="WhatsApp conversation cost",
            risk_label="template/provider approval risk",
            platform=platform,
        ),
        _record(
            key="case_tracking",
            name="Case tracking provider",
            category="courts",
            provider=settings.case_tracking_provider or "disabled",
            enabled=(
                settings.case_tracking_enabled
                and settings.case_tracking_provider != "disabled"
            ),
            configured=bool(settings.ecourtsindia_api_base_url and settings.ecourtsindia_api_token),
            blocked=(
                not settings.case_tracking_enabled
                or settings.case_tracking_provider == "disabled"
                or not settings.ecourtsindia_api_base_url
                or not settings.ecourtsindia_api_token
            ),
            webhook_status="not_applicable",
            required_config_names=[
                "CASE_TRACKING_ENABLED",
                "CASE_TRACKING_PROVIDER",
                "ECOURTSINDIA_API_BASE_URL",
                "ECOURTSINDIA_API_TOKEN",
            ],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="case refresh cost",
            risk_label="court provider quota/cost risk",
            platform=platform,
        ),
        _record(
            key="prs_legal_updates",
            name="PRS and legal updates",
            category="legal_updates",
            provider="prsindia",
            enabled=settings.legal_update_sync_enabled,
            configured=bool(settings.legal_update_prs_base_url),
            blocked=not settings.legal_update_sync_enabled,
            webhook_status="not_applicable",
            required_config_names=[
                "LEGAL_UPDATE_SYNC_ENABLED",
                "LEGAL_UPDATE_PRS_BASE_URL",
            ],
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="legal update crawl/summary cost",
            risk_label="scheduler disabled until approved",
            platform=platform,
        ),
        _record(
            key="temporal",
            name="Temporal",
            category="workflow",
            provider="temporal",
            enabled=settings.durable_workflows_enabled,
            configured=not temporal_missing,
            blocked=bool(temporal_missing),
            webhook_status="not_applicable",
            required_config_names=temporal_required,
            runbook_link="docs/runbooks/provider-operations-readiness-2026-06-02.md",
            internal_cost_label="workflow orchestration cost",
            risk_label="automation remains gated",
            platform=platform,
        ),
        _record(
            key="clamav",
            name="ClamAV",
            category="security",
            provider="clamav",
            enabled=clam_enabled,
            configured=bool(clam_host),
            blocked=clam_required_flag in {"1", "true", "yes", "on"} and not clam_host,
            webhook_status="not_applicable",
            required_config_names=clam_required,
            runbook_link="docs/CASEOPS_AI_ENHANCEMENTS_USER_GUIDE_2026-05-27.md",
            internal_cost_label="malware scanning infrastructure",
            risk_label="fail-closed in non-local envs",
            platform=platform,
        ),
        _record(
            key="storage",
            name="Document storage",
            category="storage",
            provider=settings.document_storage_backend,
            enabled=True,
            configured=not storage_missing,
            blocked=bool(storage_missing),
            webhook_status="not_applicable",
            required_config_names=storage_required,
            runbook_link="docs/runbooks/production-billing-signoff-2026-06-02.md",
            internal_cost_label="storage GB-month cost",
            risk_label="object path/key leakage risk",
            platform=platform,
        ),
    ]
    return connectors


def tenant_connector_registry(
    session: Session,
    *,
    context: SessionContext,
) -> list[TenantConnectorRecord]:
    rows = connector_registry(session, context=context, platform=False)
    safe_rows: list[TenantConnectorRecord] = []
    for row in rows:
        data = row.model_dump()
        for key in TENANT_FORBIDDEN_PLATFORM_FIELDS:
            data.pop(key, None)
        safe_rows.append(TenantConnectorRecord(**data))
    return safe_rows
