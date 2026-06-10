from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CalendarProvider,
    DriveProvider,
    MailboxProvider,
    TenantMicrosoft365Configuration,
    UserCalendarConnection,
    UserDriveConnection,
    UserMailboxConnection,
)
from caseops_api.schemas.microsoft365 import (
    Microsoft365ApprovalItemStatus,
    Microsoft365ConfigurationItemStatus,
    Microsoft365ReadinessCheckResult,
    Microsoft365ReadinessTestResponse,
    Microsoft365TenantConfigurationResponse,
    Microsoft365TenantConfigurationUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.calendar_sync import _encrypt_secret
from caseops_api.services.identity import SessionContext
from caseops_api.services.notification_delivery import redact_provider_error

MICROSOFT365_SCOPES = [
    "offline_access",
    "User.Read",
    "Mail.ReadBasic",
    "Calendars.ReadWrite",
    "Files.Read.All",
    "Sites.Read.All",
]

_APPROVAL_LABELS = {
    "admin_consent_approved": "Microsoft Entra admin consent approved",
    "scopes_approved": "Graph scopes approved for review-first workflows",
}


def _now() -> datetime:
    return datetime.now(UTC)


def tenant_microsoft365_configuration(
    session: Session,
    *,
    company_id: str,
) -> TenantMicrosoft365Configuration | None:
    return session.scalar(
        select(TenantMicrosoft365Configuration).where(
            TenantMicrosoft365Configuration.company_id == company_id
        )
    )


def _ensure_config(
    session: Session,
    *,
    context: SessionContext,
) -> TenantMicrosoft365Configuration:
    row = tenant_microsoft365_configuration(session, company_id=context.company.id)
    if row is None:
        row = TenantMicrosoft365Configuration(
            company_id=context.company.id,
            created_by_membership_id=context.membership.id,
        )
        session.add(row)
        session.flush()
    return row


def _config_items(
    row: TenantMicrosoft365Configuration | None,
) -> list[Microsoft365ConfigurationItemStatus]:
    return [
        Microsoft365ConfigurationItemStatus(
            name="MICROSOFT_365_CLIENT_ID",
            configured=bool(row and row.client_id),
        ),
        Microsoft365ConfigurationItemStatus(
            name="MICROSOFT_365_CLIENT_SECRET",
            configured=bool(row and row.encrypted_client_secret_ref),
        ),
        Microsoft365ConfigurationItemStatus(
            name="MICROSOFT_365_TENANT_ID",
            configured=bool(row and row.tenant_id),
        ),
        Microsoft365ConfigurationItemStatus(
            name="MICROSOFT_365_REDIRECT_URI",
            configured=bool(row and row.redirect_uri),
        ),
    ]


def _approval_items(
    row: TenantMicrosoft365Configuration | None,
) -> list[Microsoft365ApprovalItemStatus]:
    return [
        Microsoft365ApprovalItemStatus(
            key="admin_consent_approved",
            label=_APPROVAL_LABELS["admin_consent_approved"],
            approved=bool(row and row.admin_consent_approved),
        ),
        Microsoft365ApprovalItemStatus(
            key="scopes_approved",
            label=_APPROVAL_LABELS["scopes_approved"],
            approved=bool(row and row.scopes_approved),
        ),
    ]


def _missing_config_names(
    row: TenantMicrosoft365Configuration | None,
) -> list[str]:
    missing = [item.name for item in _config_items(row) if not item.configured]
    if row is not None and not row.enabled:
        missing.append("MICROSOFT_365_ENABLED")
    return missing


def _missing_approval_keys(
    row: TenantMicrosoft365Configuration | None,
) -> list[str]:
    return [item.key for item in _approval_items(row) if not item.approved]


def _readiness(row: TenantMicrosoft365Configuration | None) -> str:
    if _missing_config_names(row) or _missing_approval_keys(row):
        return "blocked_pending_admin_configuration"
    return "ready_for_review_first_workflows"


def microsoft365_tenant_configuration_status(
    session: Session,
    *,
    context: SessionContext,
) -> Microsoft365TenantConfigurationResponse:
    row = tenant_microsoft365_configuration(session, company_id=context.company.id)
    connection_count = (
        session.scalar(
            select(func.count())
            .select_from(UserCalendarConnection)
            .where(
                UserCalendarConnection.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
            )
        )
        or 0
    )
    mail_count = (
        session.scalar(
            select(func.count())
            .select_from(UserMailboxConnection)
            .where(
                UserMailboxConnection.company_id == context.company.id,
                UserMailboxConnection.provider == MailboxProvider.OUTLOOK_MAIL,
            )
        )
        or 0
    )
    drive_count = (
        session.scalar(
            select(func.count())
            .select_from(UserDriveConnection)
            .where(
                UserDriveConnection.company_id == context.company.id,
                UserDriveConnection.provider == DriveProvider.ONEDRIVE_SHAREPOINT,
            )
        )
        or 0
    )
    configured = not _missing_config_names(row) and not _missing_approval_keys(row)
    return Microsoft365TenantConfigurationResponse(
        configured=configured,
        enabled=bool(row.enabled) if row else False,
        required_config=_config_items(row),
        required_approvals=_approval_items(row),
        approved_scopes=list(row.scopes_json or MICROSOFT365_SCOPES) if row else [],
        missing_config_names=_missing_config_names(row),
        missing_approval_keys=_missing_approval_keys(row),
        mail_enabled=bool(row.mail_enabled) if row else False,
        calendar_enabled=bool(row.calendar_enabled) if row else False,
        drive_enabled=bool(row.drive_enabled) if row else False,
        connection_count=int(connection_count + mail_count + drive_count),
        connected_account_count=int(connection_count + mail_count + drive_count),
        last_test_status=row.last_test_status if row else "not_run",  # type: ignore[arg-type]
        last_tested_at=row.last_tested_at if row else None,
        last_error_redacted=row.last_error_redacted if row else None,
        readiness=_readiness(row),  # type: ignore[arg-type]
    )


def update_microsoft365_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
    payload: Microsoft365TenantConfigurationUpdateRequest,
) -> Microsoft365TenantConfigurationResponse:
    row = _ensure_config(session, context=context)
    if payload.client_id is not None:
        row.client_id = payload.client_id
    if payload.client_secret is not None:
        row.encrypted_client_secret_ref = _encrypt_secret(payload.client_secret)
    if payload.tenant_id is not None:
        row.tenant_id = payload.tenant_id
    if payload.redirect_uri is not None:
        row.redirect_uri = payload.redirect_uri
    if payload.scopes is not None:
        row.scopes_json = [scope for scope in payload.scopes if scope]
    elif not row.scopes_json:
        row.scopes_json = list(MICROSOFT365_SCOPES)
    row.admin_consent_approved = bool(payload.admin_consent_approved)
    row.scopes_approved = bool(payload.scopes_approved)
    row.mail_enabled = bool(payload.mail_enabled)
    row.calendar_enabled = bool(payload.calendar_enabled)
    row.drive_enabled = bool(payload.drive_enabled)
    row.enabled = bool(payload.enabled)
    session.add(row)
    record_from_context(
        session,
        context,
        action="microsoft365.configuration.updated",
        target_type="tenant_microsoft365_configuration",
        target_id=row.id,
        metadata={
            "client_id_present": bool(row.client_id),
            "secret_present": bool(row.encrypted_client_secret_ref),
            "tenant_id_present": bool(row.tenant_id),
            "redirect_uri_present": bool(row.redirect_uri),
            "scope_count": len(row.scopes_json or []),
        },
    )
    session.commit()
    return microsoft365_tenant_configuration_status(session, context=context)


def test_microsoft365_tenant_configuration(
    session: Session,
    *,
    context: SessionContext,
) -> Microsoft365ReadinessTestResponse:
    row = _ensure_config(session, context=context)
    tested_at = _now()
    checks: list[Microsoft365ReadinessCheckResult] = []
    for item in _config_items(row):
        checks.append(
            Microsoft365ReadinessCheckResult(
                key=item.name,
                label=item.name,
                status="passed" if item.configured else "blocked",
            )
        )
    for approval in _approval_items(row):
        checks.append(
            Microsoft365ReadinessCheckResult(
                key=approval.key,
                label=approval.label,
                status="passed" if approval.approved else "blocked",
            )
        )
    missing = _missing_config_names(row)
    missing_approvals = _missing_approval_keys(row)
    passed = not missing and not missing_approvals
    row.last_test_status = "passed" if passed else "blocked"
    row.last_tested_at = tested_at
    row.last_error_redacted = (
        None if passed else redact_provider_error("Missing Microsoft 365 setup or approval.")
    )
    session.add(row)
    record_from_context(
        session,
        context,
        action="microsoft365.configuration.tested",
        target_type="tenant_microsoft365_configuration",
        target_id=row.id,
        result="success" if passed else "blocked",
        metadata={
            "external_provider_calls": 0,
            "missing_config_names": missing,
            "missing_approval_keys": missing_approvals,
        },
    )
    session.commit()
    return Microsoft365ReadinessTestResponse(
        status=row.last_test_status,  # type: ignore[arg-type]
        checks=checks,
        readiness=_readiness(row),  # type: ignore[arg-type]
        tested_at=tested_at,
    )
