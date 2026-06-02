from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarProvider,
    NotificationDeliveryChannel,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    UserCalendarConnection,
)
from caseops_api.schemas.provider_operations import (
    ProviderOperationAction,
    ProviderOperationActionResponse,
    ProviderOperationListResponse,
    ProviderOperationRecord,
    ProviderReadinessListResponse,
    ProviderReadinessRecord,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.durable_workflows import (
    durable_workflow_status,
    redact_identifier,
)
from caseops_api.services.google_drive_imports import (
    google_drive_provider_config_status,
)
from caseops_api.services.identity import SessionContext
from caseops_api.services.notification_delivery import redact_provider_error

_CALENDAR_OPEN_STATUSES = {
    CalendarEventSyncStatus.FAILED,
    CalendarEventSyncStatus.RETRY_SCHEDULED,
    CalendarEventSyncStatus.DEAD_LETTER,
}
_NOTIFICATION_OPEN_STATUSES = {
    NotificationDeliveryStatus.RETRY_SCHEDULED,
    NotificationDeliveryStatus.BLOCKED,
    NotificationDeliveryStatus.DEAD_LETTER,
}
_OPERATOR_IGNORE_REASON = "operator_ignored"
_OPERATOR_RESOLVE_REASON = "operator_resolved"


def _now() -> datetime:
    return datetime.now(UTC)


def _operation_id(kind: str, row_id: str) -> str:
    return f"{kind}:{row_id}"


def _split_operation_id(operation_id: str) -> tuple[str, str]:
    if ":" not in operation_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    kind, row_id = operation_id.split(":", 1)
    if kind not in {"calendar_sync", "notification_delivery"} or not row_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return kind, row_id


def _operator_state(dead_letter_reason: str | None) -> Literal[
    "open",
    "ignored",
    "resolved",
]:
    if dead_letter_reason == _OPERATOR_IGNORE_REASON:
        return "ignored"
    if dead_letter_reason == _OPERATOR_RESOLVE_REASON:
        return "resolved"
    return "open"


def _calendar_record(row: CalendarEventSync) -> ProviderOperationRecord:
    operator_state = _operator_state(row.dead_letter_reason)
    status_value = str(row.sync_status)
    replayable = row.sync_status in _CALENDAR_OPEN_STATUSES
    open_action = row.sync_status not in {
        CalendarEventSyncStatus.SYNCED,
        CalendarEventSyncStatus.DELETED,
    }
    return ProviderOperationRecord(
        id=_operation_id("calendar_sync", row.id),
        job_kind="calendar_sync",
        provider=str(CalendarProvider.OUTLOOK),
        company_id=row.company_id,
        matter_id=None,
        source_type=str(row.source_type),
        source_ref=redact_identifier(row.source_id),
        provider_item_ref=redact_identifier(row.provider_event_id),
        status=status_value,
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.last_error)
        if row.last_error
        else None,
        dead_letter_reason=row.dead_letter_reason,
        attempts=row.attempts,
        max_attempts=max(row.max_attempts, 1),
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=replayable,
        ignore_available=open_action and operator_state == "open",
        mark_resolved_available=open_action and operator_state == "open",
        notes=[
            "Replay only reschedules the stored sync row; provider calls remain "
            "gated by Outlook tenant readiness."
        ],
    )


def _notification_record(row: NotificationDeliveryIntent) -> ProviderOperationRecord:
    operator_state = _operator_state(row.dead_letter_reason)
    is_external = row.channel != NotificationDeliveryChannel.IN_APP
    replayable = (
        row.status in _NOTIFICATION_OPEN_STATUSES
        and row.channel == NotificationDeliveryChannel.IN_APP
    )
    open_action = row.status != NotificationDeliveryStatus.DELIVERED
    notes = [
        "Replay uses the existing idempotency key and cannot create a second "
        "delivery intent."
    ]
    if is_external:
        notes.append(
            "External delivery remains blocked until provider policy and "
            "credentials are explicitly approved."
        )
    return ProviderOperationRecord(
        id=_operation_id("notification_delivery", row.id),
        job_kind="notification_delivery",
        provider=str(row.channel),
        company_id=row.company_id,
        matter_id=row.matter_id,
        source_type=str(row.source_type),
        source_ref=redact_identifier(row.source_id),
        provider_item_ref=redact_identifier(row.in_app_notification_id),
        status=str(row.status),
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.last_error_redacted)
        if row.last_error_redacted
        else None,
        dead_letter_reason=row.dead_letter_reason,
        attempts=row.attempts,
        max_attempts=max(row.max_attempts, 1),
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=replayable,
        ignore_available=open_action and operator_state == "open",
        mark_resolved_available=open_action and operator_state == "open",
        notes=notes,
    )


def list_provider_operations(
    session: Session,
    *,
    context: SessionContext,
    include_resolved: bool = False,
    limit: int = 100,
) -> ProviderOperationListResponse:
    calendar_rows = list(
        session.scalars(
            select(CalendarEventSync)
            .join(
                UserCalendarConnection,
                UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
            )
            .where(
                CalendarEventSync.company_id == context.company.id,
                UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
                CalendarEventSync.sync_status.in_(tuple(_CALENDAR_OPEN_STATUSES)),
            )
            .order_by(CalendarEventSync.updated_at.desc())
            .limit(limit)
        )
    )
    notification_rows = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.status.in_(
                    tuple(_NOTIFICATION_OPEN_STATUSES)
                ),
            )
            .order_by(NotificationDeliveryIntent.updated_at.desc())
            .limit(limit)
        )
    )
    records = [
        *(_calendar_record(row) for row in calendar_rows),
        *(_notification_record(row) for row in notification_rows),
    ]
    if not include_resolved:
        records = [row for row in records if row.operator_state == "open"]
    records.sort(key=lambda row: row.updated_at, reverse=True)
    records = records[:limit]
    return ProviderOperationListResponse(
        operations=records,
        open_count=sum(1 for row in records if row.operator_state == "open"),
        ignored_count=sum(1 for row in records if row.operator_state == "ignored"),
        resolved_count=sum(1 for row in records if row.operator_state == "resolved"),
        replayable_count=sum(1 for row in records if row.replay_available),
    )


def _load_calendar_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> CalendarEventSync:
    row = session.scalar(
        select(CalendarEventSync)
        .join(
            UserCalendarConnection,
            UserCalendarConnection.id == CalendarEventSync.calendar_connection_id,
        )
        .where(
            CalendarEventSync.id == row_id,
            CalendarEventSync.company_id == context.company.id,
            UserCalendarConnection.provider == CalendarProvider.OUTLOOK,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return row


def _load_notification_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> NotificationDeliveryIntent:
    row = session.scalar(
        select(NotificationDeliveryIntent).where(
            NotificationDeliveryIntent.id == row_id,
            NotificationDeliveryIntent.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return row


def _audit_operation_action(
    session: Session,
    *,
    context: SessionContext,
    action: ProviderOperationAction,
    target_type: str,
    target_id: str,
    provider: str,
    previous_status: str,
    next_status: str,
    changed: bool,
    result: str = AuditResult.SUCCESS,
    reason: str | None = None,
) -> None:
    record_from_context(
        session,
        context,
        action=f"provider_operation.{action}",
        target_type=target_type,
        target_id=target_id,
        result=result,
        metadata={
            "provider": provider,
            "operation_ref": redact_identifier(target_id),
            "previous_status": previous_status,
            "next_status": next_status,
            "changed": changed,
            "reason_present": bool(reason and reason.strip()),
        },
    )


def replay_provider_operation(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
    reason: str | None = None,
) -> ProviderOperationActionResponse:
    kind, row_id = _split_operation_id(operation_id)
    current_time = _now()
    if kind == "calendar_sync":
        row = _load_calendar_operation(session, context=context, row_id=row_id)
        previous_status = str(row.sync_status)
        changed = row.sync_status in _CALENDAR_OPEN_STATUSES
        if changed:
            if row.sync_status == CalendarEventSyncStatus.DEAD_LETTER:
                row.attempts = 0
            row.sync_status = CalendarEventSyncStatus.PENDING
            row.next_attempt_at = current_time
            row.dead_letter_reason = None
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="calendar_event_sync",
            target_id=row.id,
            provider=str(CalendarProvider.OUTLOOK),
            previous_status=previous_status,
            next_status=str(row.sync_status),
            changed=changed,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action="replay",
            changed=changed,
            message=(
                "Calendar sync row was rescheduled; Outlook provider calls "
                "remain gated by tenant readiness."
            )
            if changed
            else "Calendar sync row was already outside a replayable state.",
            operation=_calendar_record(row),
        )

    row = _load_notification_operation(session, context=context, row_id=row_id)
    previous_status = str(row.status)
    if row.channel != NotificationDeliveryChannel.IN_APP:
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="notification_delivery_intent",
            target_id=row.id,
            provider=str(row.channel),
            previous_status=previous_status,
            next_status=str(row.status),
            changed=False,
            result=AuditResult.DENIED,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action="replay",
            changed=False,
            message=(
                "External delivery replay remains blocked because provider "
                "configuration and approval are not enabled."
            ),
            operation=_notification_record(row),
        )

    changed = row.status in _NOTIFICATION_OPEN_STATUSES
    if changed:
        if row.status == NotificationDeliveryStatus.DEAD_LETTER:
            row.attempts = 0
        row.status = NotificationDeliveryStatus.QUEUED
        row.next_attempt_at = current_time
        row.dead_letter_reason = None
        row.failed_at = None
        row.updated_at = current_time
        session.add(row)
    _audit_operation_action(
        session,
        context=context,
        action="replay",
        target_type="notification_delivery_intent",
        target_id=row.id,
        provider=str(row.channel),
        previous_status=previous_status,
        next_status=str(row.status),
        changed=changed,
        reason=reason,
    )
    session.commit()
    return ProviderOperationActionResponse(
        action="replay",
        changed=changed,
        message=(
            "Notification intent was queued for in-app replay using its "
            "existing idempotency key."
        )
        if changed
        else "Notification intent was already outside a replayable state.",
        operation=_notification_record(row),
    )


def update_provider_operation_state(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
    action: Literal["ignore", "mark_resolved"],
    reason: str | None = None,
) -> ProviderOperationActionResponse:
    kind, row_id = _split_operation_id(operation_id)
    marker = _OPERATOR_IGNORE_REASON if action == "ignore" else _OPERATOR_RESOLVE_REASON
    current_time = _now()

    if kind == "calendar_sync":
        row = _load_calendar_operation(session, context=context, row_id=row_id)
        previous_status = str(row.sync_status)
        changed = row.sync_status not in {
            CalendarEventSyncStatus.SYNCED,
            CalendarEventSyncStatus.DELETED,
        } and row.dead_letter_reason != marker
        if changed:
            row.sync_status = CalendarEventSyncStatus.DEAD_LETTER
            row.dead_letter_reason = marker
            row.next_attempt_at = None
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action=action,
            target_type="calendar_event_sync",
            target_id=row.id,
            provider=str(CalendarProvider.OUTLOOK),
            previous_status=previous_status,
            next_status=str(row.sync_status),
            changed=changed,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action=action,
            changed=changed,
            message=(
                "Calendar sync row was marked ignored."
                if action == "ignore"
                else "Calendar sync row was marked operator-resolved."
            ),
            operation=_calendar_record(row),
        )

    row = _load_notification_operation(session, context=context, row_id=row_id)
    previous_status = str(row.status)
    changed = (
        row.status != NotificationDeliveryStatus.DELIVERED
        and row.dead_letter_reason != marker
    )
    if changed:
        row.status = NotificationDeliveryStatus.DEAD_LETTER
        row.dead_letter_reason = marker
        row.next_attempt_at = None
        row.failed_at = current_time
        row.updated_at = current_time
        session.add(row)
    _audit_operation_action(
        session,
        context=context,
        action=action,
        target_type="notification_delivery_intent",
        target_id=row.id,
        provider=str(row.channel),
        previous_status=previous_status,
        next_status=str(row.status),
        changed=changed,
        reason=reason,
    )
    session.commit()
    return ProviderOperationActionResponse(
        action=action,
        changed=changed,
        message=(
            "Notification intent was marked ignored."
            if action == "ignore"
            else "Notification intent was marked operator-resolved."
        ),
        operation=_notification_record(row),
    )


def provider_readiness_status() -> ProviderReadinessListResponse:
    settings = get_settings()
    workflow = durable_workflow_status(settings)
    drive_status = google_drive_provider_config_status()
    drive_missing_approvals = ["tenant_drive_sync_approved"]
    email_missing_config = [
        "MAILBOX_CONNECTOR_PROVIDER",
        "MAILBOX_CLIENT_ID",
        "MAILBOX_CLIENT_SECRET",
        "MAILBOX_WEBHOOK_SIGNING_SECRET",
    ]
    digest_email_missing = []
    if not settings.sendgrid_api_key:
        digest_email_missing.append("SENDGRID_API_KEY")
    if not settings.sendgrid_sender_email:
        digest_email_missing.append("SENDGRID_SENDER_EMAIL")
    if not settings.sendgrid_webhook_public_key:
        digest_email_missing.append("SENDGRID_WEBHOOK_PUBLIC_KEY")

    return ProviderReadinessListResponse(
        providers=[
            ProviderReadinessRecord(
                provider="google_drive",
                display_name="Google Drive sync",
                adp_slice="ADP-21",
                state=(
                    "blocked_pending_admin_approval"
                    if drive_status.configured
                    else "blocked_missing_config"
                ),
                configured=drive_status.configured,
                enabled=False,
                external_calls_enabled=False,
                durable_workflow_available=workflow.available,
                required_config_names=[
                    "GOOGLE_DRIVE_CLIENT_ID",
                    "GOOGLE_DRIVE_CLIENT_SECRET",
                    "GOOGLE_DRIVE_REDIRECT_URI",
                ],
                missing_config_names=drive_status.missing_config_names,
                required_approval_keys=drive_missing_approvals,
                missing_approval_keys=drive_missing_approvals,
                endpoint_paths=[
                    "/api/matters/imports/drive/provider-config",
                    "/api/matters/{matter_id}/imports/drive/dry-run",
                ],
                idempotency_fields=[
                    "provider_file_id",
                    "version",
                    "content_hash",
                    "modified_time",
                ],
                change_detection_fields=[
                    "provider_file_id",
                    "version",
                    "content_hash",
                    "modified_time",
                ],
                review_queue="planned: updated/deleted/duplicate Drive file review",
                retry_dead_letter=(
                    "ADP-24 provider operations replay is available for "
                    "persisted provider jobs; Drive durable jobs remain gated."
                ),
                limitations=[
                    "Manual bounded dry-run only; no OAuth tokens or Drive file "
                    "contents are stored.",
                    "Durable sync must remain disabled until tenant approval and "
                    "provider credentials are supplied.",
                ],
            ),
            ProviderReadinessRecord(
                provider="email_connector",
                display_name="Mailbox ingestion",
                adp_slice="ADP-22",
                state="blocked_missing_config",
                configured=False,
                enabled=False,
                external_calls_enabled=False,
                durable_workflow_available=workflow.available,
                required_config_names=email_missing_config,
                missing_config_names=email_missing_config,
                required_approval_keys=[
                    "tenant_mailbox_ingestion_approved",
                    "redaction_rules_approved",
                    "matter_routing_review_approved",
                ],
                missing_approval_keys=[
                    "tenant_mailbox_ingestion_approved",
                    "redaction_rules_approved",
                    "matter_routing_review_approved",
                ],
                endpoint_paths=[
                    "/api/matters/{matter_id}/communications/import-email",
                    "/api/calendar/email-invitation-candidates",
                    "/api/calendar/email-invitation-candidates/extract",
                ],
                idempotency_fields=[
                    "provider_message_id",
                    "thread_id",
                    "internet_message_id",
                    "message_headers",
                ],
                change_detection_fields=["provider_message_id", "thread_id"],
                review_queue="available: email invitation candidates; planned: intake routing",
                retry_dead_letter=(
                    "ADP-24 provider operations covers notification delivery "
                    "intents; inbound mailbox provider jobs remain gated."
                ),
                limitations=[
                    "No mailbox polling, provider webhook ingestion, or raw email "
                    "body logging is enabled.",
                    "Matter association remains candidate/review-first.",
                ],
            ),
            ProviderReadinessRecord(
                provider="digest_delivery",
                display_name="Judgment and legal-update digests",
                adp_slice="ADP-23",
                state="foundation_available",
                configured=not digest_email_missing,
                enabled=False,
                external_calls_enabled=False,
                durable_workflow_available=workflow.available,
                required_config_names=[
                    "SENDGRID_API_KEY",
                    "SENDGRID_SENDER_EMAIL",
                    "SENDGRID_WEBHOOK_PUBLIC_KEY",
                ],
                missing_config_names=digest_email_missing,
                required_approval_keys=[
                    "external_digest_delivery_approved",
                    "unsubscribe_suppression_reviewed",
                ],
                missing_approval_keys=[
                    "external_digest_delivery_approved",
                    "unsubscribe_suppression_reviewed",
                ],
                endpoint_paths=[
                    "/api/authorities/alerts/digest-preview",
                    "/api/statutes/legal-updates/digest-preview",
                ],
                idempotency_fields=[
                    "company_id",
                    "recipient_membership_id",
                    "event_type",
                    "source_type",
                    "source_id",
                ],
                change_detection_fields=["alert_id", "source_record_id"],
                review_queue="in-app digest preview only",
                retry_dead_letter=(
                    "Notification delivery intents use ADP-24 replay and "
                    "dead-letter handling; external digest delivery is blocked."
                ),
                limitations=[
                    "In-app previews are available; email/SMS/WhatsApp delivery "
                    "requires provider approval.",
                    "Tenant email suppression exists for SendGrid-backed sends, "
                    "but digest sending is not enabled.",
                ],
            ),
        ]
    )


__all__ = [
    "list_provider_operations",
    "provider_readiness_status",
    "replay_provider_operation",
    "update_provider_operation_state",
]

