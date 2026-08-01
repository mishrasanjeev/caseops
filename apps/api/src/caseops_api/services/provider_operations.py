from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditResult,
    CalendarEventCandidate,
    CalendarEventCandidateStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    ConnectorHealthRecord,
    DriveFileCandidate,
    InboundEmailEvent,
    MailboxImportStatus,
    MailboxMessageImport,
    MailboxWebhookEvent,
    MailboxWebhookStatus,
    NotificationDeliveryChannel,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    TrackedCasePollRun,
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
from caseops_api.services.google_workspace import (
    google_workspace_connector_configured,
    google_workspace_connector_missing_config_names,
    google_workspace_oauth_config,
)
from caseops_api.services.notification_delivery import redact_provider_error
from caseops_api.services.session_context import SessionContext

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
_MAILBOX_IMPORT_OPEN_STATUSES = {
    MailboxImportStatus.FAILED,
    MailboxImportStatus.DEAD_LETTER,
    MailboxImportStatus.UNMATCHED,
}
_MAILBOX_WEBHOOK_OPEN_STATUSES = {
    MailboxWebhookStatus.FAILED,
    MailboxWebhookStatus.DEAD_LETTER,
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
    if (
        kind
        not in {
            "calendar_sync",
            "notification_delivery",
            "case_tracking_poll",
            "mailbox_message_import",
            "mailbox_webhook",
        }
        or not row_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return kind, row_id


def _operator_state(
    dead_letter_reason: str | None,
) -> Literal[
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
        provider=str(row.connection.provider),
        company_id=row.company_id,
        matter_id=None,
        source_type=str(row.source_type),
        source_ref=redact_identifier(row.source_id),
        provider_item_ref=redact_identifier(row.provider_event_id),
        status=status_value,
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.last_error) if row.last_error else None,
        dead_letter_reason=redact_provider_error(row.dead_letter_reason)
        if row.dead_letter_reason
        else None,
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
            "gated by provider readiness."
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
    notes = ["Replay uses the existing idempotency key and cannot create a second delivery intent."]
    if is_external:
        notes.append(
            "External delivery remains blocked until provider policy and "
            "credentials are explicitly approved."
        )
    notes.extend(
        [
            f"dispatch_owner={row.dispatch_owner}",
            f"comparison_status={row.comparison_status}",
            f"fallback_created={bool(row.fallback_intent_id)}",
        ]
    )
    if row.suppression_reason:
        notes.append(f"suppression={row.suppression_reason}")
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
        dead_letter_reason=redact_provider_error(row.dead_letter_reason)
        if row.dead_letter_reason
        else None,
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


def _case_tracking_poll_record(row: TrackedCasePollRun) -> ProviderOperationRecord:
    metadata = dict(row.metadata_json or {})
    provider = str(metadata.get("provider") or "case_tracking")
    reason = metadata.get("reason") or metadata.get("partial_reason")
    notes = [
        f"tracked={metadata.get('tracked_count', 0)}",
        f"attempted={metadata.get('attempted_count', 0)}",
        f"checked={row.checked_count}",
        f"changed={row.update_count}",
        f"skipped={row.skipped_count}",
        f"blocked={row.blocked_count}",
        f"provider_calls={row.provider_call_count}",
        f"backlog={row.backlog_remaining_count}",
        "Only explicitly tracked/bookmarked cases are eligible for scheduled refresh.",
    ]
    window = metadata.get("window")
    if isinstance(window, dict):
        notes.append(
            "window="
            f"{window.get('window_start')}-{window.get('window_end')} "
            f"{window.get('timezone')}"
        )
    return ProviderOperationRecord(
        id=_operation_id("case_tracking_poll", row.id),
        job_kind="case_tracking_poll",
        provider=provider,
        company_id=row.company_id or "",
        matter_id=None,
        source_type="tracked_case_poll_run",
        source_ref=redact_identifier(row.id),
        provider_item_ref=None,
        status=row.status,
        operator_state="open",
        error_redacted=redact_provider_error(str(reason)) if reason else None,
        dead_letter_reason=None,
        attempts=1,
        max_attempts=1,
        next_attempt_at=None,
        created_at=row.started_at,
        updated_at=row.completed_at or row.started_at,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=notes,
    )


def _mailbox_import_record(row: MailboxMessageImport) -> ProviderOperationRecord:
    operator_state = _operator_state(row.dead_letter_reason)
    open_action = row.status not in {
        MailboxImportStatus.IMPORTED,
        MailboxImportStatus.DUPLICATE,
        MailboxImportStatus.IGNORED,
        MailboxImportStatus.RESOLVED,
    }
    replayable = row.status in {
        MailboxImportStatus.FAILED,
        MailboxImportStatus.DEAD_LETTER,
    }
    return ProviderOperationRecord(
        id=_operation_id("mailbox_message_import", row.id),
        job_kind="mailbox_message_import",
        provider="gmail",
        company_id=row.company_id,
        matter_id=row.matter_id,
        source_type="gmail_message_metadata",
        source_ref=redact_identifier(row.provider_message_id),
        provider_item_ref=redact_identifier(row.provider_thread_id),
        status=str(row.status),
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.last_error_redacted)
        if row.last_error_redacted
        else None,
        dead_letter_reason=redact_provider_error(row.dead_letter_reason)
        if row.dead_letter_reason
        else None,
        attempts=row.attempts,
        max_attempts=max(row.max_attempts, 1),
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=replayable,
        ignore_available=open_action and operator_state == "open",
        mark_resolved_available=open_action and operator_state == "open",
        notes=[
            "Gmail imports store metadata/snippets only; attachment bytes require "
            "explicit candidate approval."
        ],
    )


def _mailbox_webhook_record(row: MailboxWebhookEvent) -> ProviderOperationRecord:
    operator_state = _operator_state(row.last_error_redacted)
    replayable = (
        row.status in _MAILBOX_WEBHOOK_OPEN_STATUSES and row.mailbox_connection_id is not None
    )
    return ProviderOperationRecord(
        id=_operation_id("mailbox_webhook", row.id),
        job_kind="mailbox_webhook",
        provider=str(row.provider),
        company_id=row.company_id or "",
        matter_id=None,
        source_type="gmail_pubsub_webhook",
        source_ref=redact_identifier(row.history_id),
        provider_item_ref=redact_identifier(row.email_address_hash),
        status=str(row.status),
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.last_error_redacted)
        if row.last_error_redacted
        else None,
        dead_letter_reason=None,
        attempts=row.attempts,
        max_attempts=max(row.max_attempts, 1),
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=replayable,
        ignore_available=row.status != MailboxWebhookStatus.PROCESSED and operator_state == "open",
        mark_resolved_available=row.status != MailboxWebhookStatus.PROCESSED
        and operator_state == "open",
        notes=["Webhook payloads are hashed only; raw Pub/Sub data is not exposed."],
    )


def _drive_candidate_record(row: DriveFileCandidate) -> ProviderOperationRecord:
    return ProviderOperationRecord(
        id=_operation_id("drive_file_candidate", row.id),
        job_kind="drive_file_candidate",
        provider=str(row.provider),
        company_id=row.company_id,
        matter_id=row.linked_matter_id or row.suggested_matter_id,
        source_type="drive_file_metadata",
        source_ref=redact_identifier(row.provider_file_id),
        provider_item_ref=redact_identifier(row.provider_version),
        status=str(row.status),
        operator_state="open",
        error_redacted=redact_provider_error(row.last_error_redacted)
        if row.last_error_redacted
        else None,
        dead_letter_reason=None,
        attempts=1,
        max_attempts=1,
        next_attempt_at=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=["Drive file candidates require explicit user review before content import."],
    )


def _calendar_candidate_record(row: CalendarEventCandidate) -> ProviderOperationRecord:
    return ProviderOperationRecord(
        id=_operation_id("calendar_event_candidate", row.id),
        job_kind="calendar_event_candidate",
        provider=str(row.provider),
        company_id=row.company_id,
        matter_id=row.linked_matter_id or row.suggested_matter_id,
        source_type="provider_calendar_event",
        source_ref=redact_identifier(row.provider_event_id),
        provider_item_ref=redact_identifier(row.i_cal_uid),
        status=str(row.status),
        operator_state="open",
        error_redacted=redact_provider_error(row.last_error_redacted or row.conflict_reason)
        if (row.last_error_redacted or row.conflict_reason)
        else None,
        dead_letter_reason=None,
        attempts=1,
        max_attempts=1,
        next_attempt_at=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=["Calendar provider candidates are resolved from the calendar conflict queue."],
    )


def _inbound_email_event_record(row: InboundEmailEvent) -> ProviderOperationRecord:
    return ProviderOperationRecord(
        id=_operation_id("inbound_email_event", row.id),
        job_kind="inbound_email_event",
        provider=str(row.provider),
        company_id=row.company_id,
        matter_id=row.linked_matter_id or row.matched_matter_id,
        source_type="inbound_email_alias",
        source_ref=redact_identifier(row.provider_message_id),
        provider_item_ref=redact_identifier(row.alias_id),
        status=str(row.status),
        operator_state="open",
        error_redacted=redact_provider_error(row.redacted_failure_reason)
        if row.redacted_failure_reason
        else None,
        dead_letter_reason=None,
        attempts=1,
        max_attempts=1,
        next_attempt_at=None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=[
            "Inbound email events store metadata only; raw body and "
            "attachment bytes are not imported."
        ],
    )


def _connector_health_record(row: ConnectorHealthRecord) -> ProviderOperationRecord:
    return ProviderOperationRecord(
        id=_operation_id("connector_health", row.id),
        job_kind="connector_health",
        provider=str(row.provider),
        company_id=row.company_id,
        matter_id=None,
        source_type="connector_health",
        source_ref=redact_identifier(row.account_ref_hash),
        provider_item_ref=None,
        status=str(row.connected_state),
        operator_state="open",
        error_redacted=redact_provider_error(row.error_category or row.disabled_reason)
        if (row.error_category or row.disabled_reason)
        else None,
        dead_letter_reason=None,
        attempts=1,
        max_attempts=1,
        next_attempt_at=row.next_retry_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=["Connector health checks are refreshed from /admin/integrations/health/check."],
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
                NotificationDeliveryIntent.status.in_(tuple(_NOTIFICATION_OPEN_STATUSES)),
            )
            .order_by(NotificationDeliveryIntent.updated_at.desc())
            .limit(limit)
        )
    )
    poll_statuses = (
        ("blocked", "skipped", "partial", "failed")
        if not include_resolved
        else (
            "blocked",
            "skipped",
            "partial",
            "failed",
            "completed",
        )
    )
    case_tracking_rows = list(
        session.scalars(
            select(TrackedCasePollRun)
            .where(
                TrackedCasePollRun.company_id == context.company.id,
                TrackedCasePollRun.status.in_(poll_statuses),
            )
            .order_by(TrackedCasePollRun.started_at.desc())
            .limit(limit)
        )
    )
    mailbox_import_rows = list(
        session.scalars(
            select(MailboxMessageImport)
            .where(
                MailboxMessageImport.company_id == context.company.id,
                MailboxMessageImport.status.in_(tuple(_MAILBOX_IMPORT_OPEN_STATUSES)),
            )
            .order_by(MailboxMessageImport.updated_at.desc())
            .limit(limit)
        )
    )
    mailbox_webhook_rows = list(
        session.scalars(
            select(MailboxWebhookEvent)
            .where(
                MailboxWebhookEvent.company_id == context.company.id,
                MailboxWebhookEvent.status.in_(tuple(_MAILBOX_WEBHOOK_OPEN_STATUSES)),
            )
            .order_by(MailboxWebhookEvent.updated_at.desc())
            .limit(limit)
        )
    )
    drive_candidate_rows = list(
        session.scalars(
            select(DriveFileCandidate)
            .where(
                DriveFileCandidate.company_id == context.company.id,
                DriveFileCandidate.status == "failed",
            )
            .order_by(DriveFileCandidate.updated_at.desc())
            .limit(limit)
        )
    )
    calendar_candidate_rows = list(
        session.scalars(
            select(CalendarEventCandidate)
            .where(
                CalendarEventCandidate.company_id == context.company.id,
                CalendarEventCandidate.status.in_(
                    (
                        CalendarEventCandidateStatus.CONFLICT,
                        CalendarEventCandidateStatus.FAILED,
                    )
                ),
            )
            .order_by(CalendarEventCandidate.updated_at.desc())
            .limit(limit)
        )
    )
    inbound_email_event_rows = list(
        session.scalars(
            select(InboundEmailEvent)
            .where(
                InboundEmailEvent.company_id == context.company.id,
                InboundEmailEvent.status.in_(("failed", "rejected")),
            )
            .order_by(InboundEmailEvent.updated_at.desc())
            .limit(limit)
        )
    )
    connector_health_rows = list(
        session.scalars(
            select(ConnectorHealthRecord)
            .where(
                ConnectorHealthRecord.company_id == context.company.id,
                ConnectorHealthRecord.connected_state.in_(
                    (
                        "degraded",
                        "token_expired",
                        "scope_missing",
                        "rate_limited",
                        "provider_outage",
                        "blocked_by_policy",
                    )
                ),
            )
            .order_by(ConnectorHealthRecord.updated_at.desc())
            .limit(limit)
        )
    )
    records = [
        *(_calendar_record(row) for row in calendar_rows),
        *(_notification_record(row) for row in notification_rows),
        *(_case_tracking_poll_record(row) for row in case_tracking_rows),
        *(_mailbox_import_record(row) for row in mailbox_import_rows),
        *(_mailbox_webhook_record(row) for row in mailbox_webhook_rows),
        *(_drive_candidate_record(row) for row in drive_candidate_rows),
        *(_calendar_candidate_record(row) for row in calendar_candidate_rows),
        *(_inbound_email_event_record(row) for row in inbound_email_event_rows),
        *(_connector_health_record(row) for row in connector_health_rows),
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


def _load_case_tracking_poll_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> TrackedCasePollRun:
    row = session.scalar(
        select(TrackedCasePollRun).where(
            TrackedCasePollRun.id == row_id,
            TrackedCasePollRun.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return row


def _load_mailbox_import_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> MailboxMessageImport:
    row = session.scalar(
        select(MailboxMessageImport).where(
            MailboxMessageImport.id == row_id,
            MailboxMessageImport.company_id == context.company.id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider operation not found.",
        )
    return row


def _load_mailbox_webhook_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> MailboxWebhookEvent:
    row = session.scalar(
        select(MailboxWebhookEvent).where(
            MailboxWebhookEvent.id == row_id,
            MailboxWebhookEvent.company_id == context.company.id,
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
            provider=str(row.connection.provider),
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
                "Calendar sync row was rescheduled; provider calls "
                "remain gated by tenant readiness."
            )
            if changed
            else "Calendar sync row was already outside a replayable state.",
            operation=_calendar_record(row),
        )

    if kind == "case_tracking_poll":
        row = _load_case_tracking_poll_operation(session, context=context, row_id=row_id)
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="tracked_case_poll_run",
            target_id=row.id,
            provider=str((row.metadata_json or {}).get("provider") or "case_tracking"),
            previous_status=row.status,
            next_status=row.status,
            changed=False,
            result=AuditResult.DENIED,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action="replay",
            changed=False,
            message=(
                "Case tracking poll runs are scheduled-window controlled and "
                "are not replayed from provider operations. Run the poll job "
                "again in the configured window or use the explicit CLI force "
                "override for operator break-glass."
            ),
            operation=_case_tracking_poll_record(row),
        )

    if kind == "mailbox_message_import":
        row = _load_mailbox_import_operation(session, context=context, row_id=row_id)
        previous_status = str(row.status)
        changed = row.status in {
            MailboxImportStatus.FAILED,
            MailboxImportStatus.DEAD_LETTER,
        }
        if changed:
            if row.status == MailboxImportStatus.DEAD_LETTER:
                row.attempts = 0
            row.status = MailboxImportStatus.QUEUED
            row.next_attempt_at = current_time
            row.dead_letter_reason = None
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="mailbox_message_import",
            target_id=row.id,
            provider="gmail",
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
                "Gmail import row was queued for a bounded metadata retry."
                if changed
                else "Gmail import row was already outside a replayable state."
            ),
            operation=_mailbox_import_record(row),
        )

    if kind == "mailbox_webhook":
        row = _load_mailbox_webhook_operation(session, context=context, row_id=row_id)
        previous_status = str(row.status)
        changed = row.status in _MAILBOX_WEBHOOK_OPEN_STATUSES
        if changed:
            row.status = MailboxWebhookStatus.QUEUED
            row.attempts = 0
            row.last_error_redacted = None
            row.next_attempt_at = current_time
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="mailbox_webhook_event",
            target_id=row.id,
            provider=str(row.provider),
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
                "Gmail webhook row was queued for operator retry."
                if changed
                else "Gmail webhook row was already outside a replayable state."
            ),
            operation=_mailbox_webhook_record(row),
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
            "Notification intent was queued for in-app replay using its existing idempotency key."
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
        changed = (
            row.sync_status
            not in {
                CalendarEventSyncStatus.SYNCED,
                CalendarEventSyncStatus.DELETED,
            }
            and row.dead_letter_reason != marker
        )
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
            provider=str(row.connection.provider),
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

    if kind == "case_tracking_poll":
        row = _load_case_tracking_poll_operation(session, context=context, row_id=row_id)
        _audit_operation_action(
            session,
            context=context,
            action=action,
            target_type="tracked_case_poll_run",
            target_id=row.id,
            provider=str((row.metadata_json or {}).get("provider") or "case_tracking"),
            previous_status=row.status,
            next_status=row.status,
            changed=False,
            result=AuditResult.DENIED,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action=action,
            changed=False,
            message=(
                "Case tracking poll run history is read-only from provider "
                "operations; the next scheduled run will resume remaining "
                "eligible backlog."
            ),
            operation=_case_tracking_poll_record(row),
        )

    if kind == "mailbox_message_import":
        row = _load_mailbox_import_operation(session, context=context, row_id=row_id)
        previous_status = str(row.status)
        changed = row.status not in {
            MailboxImportStatus.IMPORTED,
            MailboxImportStatus.DUPLICATE,
            MailboxImportStatus.IGNORED,
            MailboxImportStatus.RESOLVED,
        }
        if changed:
            row.status = (
                MailboxImportStatus.IGNORED if action == "ignore" else MailboxImportStatus.RESOLVED
            )
            row.dead_letter_reason = marker
            row.next_attempt_at = None
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action=action,
            target_type="mailbox_message_import",
            target_id=row.id,
            provider="gmail",
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
                "Gmail import row was marked ignored."
                if action == "ignore"
                else "Gmail import row was marked operator-resolved."
            ),
            operation=_mailbox_import_record(row),
        )

    if kind == "mailbox_webhook":
        row = _load_mailbox_webhook_operation(session, context=context, row_id=row_id)
        previous_status = str(row.status)
        changed = row.status != MailboxWebhookStatus.PROCESSED
        if changed:
            row.status = MailboxWebhookStatus.DEAD_LETTER
            row.last_error_redacted = marker
            row.next_attempt_at = None
            row.updated_at = current_time
            session.add(row)
        _audit_operation_action(
            session,
            context=context,
            action=action,
            target_type="mailbox_webhook_event",
            target_id=row.id,
            provider=str(row.provider),
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
                "Gmail webhook row was marked ignored."
                if action == "ignore"
                else "Gmail webhook row was marked operator-resolved."
            ),
            operation=_mailbox_webhook_record(row),
        )

    row = _load_notification_operation(session, context=context, row_id=row_id)
    previous_status = str(row.status)
    changed = (
        row.status != NotificationDeliveryStatus.DELIVERED and row.dead_letter_reason != marker
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


def provider_readiness_status(
    session: Session | None = None,
    *,
    context: SessionContext | None = None,
) -> ProviderReadinessListResponse:
    settings = get_settings()
    workflow = durable_workflow_status(settings)
    drive_status = google_drive_provider_config_status(session, context=context)
    drive_missing_approvals = ["tenant_drive_sync_approved"]
    if session is not None and context is not None:
        email_oauth_config = google_workspace_oauth_config(
            session,
            context=context,
            connector="gmail",
        )
        drive_oauth_config = google_workspace_oauth_config(
            session,
            context=context,
            connector="drive",
        )
        email_missing_config = google_workspace_connector_missing_config_names(
            session,
            context=context,
            connector="gmail",
        )
        email_oauth_configured = google_workspace_connector_configured(
            session,
            context=context,
            connector="gmail",
        )
        if email_oauth_config.source == "tenant_admin":
            email_required_config = [
                "GOOGLE_WORKSPACE_CLIENT_ID",
                "GOOGLE_WORKSPACE_CLIENT_SECRET",
                "GMAIL_REDIRECT_URI",
                "GMAIL_PUBSUB_TOPIC",
                "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
            ]
        else:
            email_required_config = [
                "GMAIL_CLIENT_ID",
                "GMAIL_CLIENT_SECRET",
                "GMAIL_REDIRECT_URI",
                "GMAIL_PUBSUB_TOPIC",
                "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
            ]
        if drive_oauth_config.source == "tenant_admin":
            drive_required_config = [
                "GOOGLE_WORKSPACE_CLIENT_ID",
                "GOOGLE_WORKSPACE_CLIENT_SECRET",
                "GOOGLE_DRIVE_REDIRECT_URI",
            ]
        else:
            drive_required_config = [
                "GOOGLE_DRIVE_CLIENT_ID",
                "GOOGLE_DRIVE_CLIENT_SECRET",
                "GOOGLE_DRIVE_REDIRECT_URI",
            ]
    else:
        email_missing_config = []
        if not settings.gmail_client_id:
            email_missing_config.append("GMAIL_CLIENT_ID")
        if not settings.gmail_client_secret:
            email_missing_config.append("GMAIL_CLIENT_SECRET")
        if not settings.gmail_redirect_uri:
            email_missing_config.append("GMAIL_REDIRECT_URI")
        email_oauth_configured = not email_missing_config
        email_required_config = [
            "GMAIL_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GMAIL_REDIRECT_URI",
            "GMAIL_PUBSUB_TOPIC",
            "GMAIL_WEBHOOK_VERIFICATION_TOKEN",
        ]
        drive_required_config = [
            "GOOGLE_DRIVE_CLIENT_ID",
            "GOOGLE_DRIVE_CLIENT_SECRET",
            "GOOGLE_DRIVE_REDIRECT_URI",
        ]
    if not settings.gmail_pubsub_topic:
        email_missing_config.append("GMAIL_PUBSUB_TOPIC")
    if not settings.gmail_webhook_verification_token:
        email_missing_config.append("GMAIL_WEBHOOK_VERIFICATION_TOKEN")
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
                required_config_names=drive_required_config,
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
                    "Manual bounded dry-run only; no OAuth tokens or Drive file " +
                    "contents are stored.",
                    "Durable sync must remain disabled until tenant approval and " +
                    "provider credentials are supplied.",
                ],
            ),
            ProviderReadinessRecord(
                provider="email_connector",
                display_name="Mailbox ingestion",
                adp_slice="ADP-22",
                state="ready" if not email_missing_config else "blocked_missing_config",
                configured=not email_missing_config,
                enabled=email_oauth_configured,
                external_calls_enabled=not email_missing_config,
                durable_workflow_available=workflow.available,
                required_config_names=email_required_config,
                missing_config_names=email_missing_config,
                required_approval_keys=["review_first_mailbox_ingestion_approved"],
                missing_approval_keys=[]
                if not email_missing_config
                else ["review_first_mailbox_ingestion_approved"],
                endpoint_paths=[
                    "/api/mailbox/gmail/status",
                    "/api/mailbox/gmail/start",
                    "/api/mailbox/gmail/import",
                    "/api/mailbox/gmail/watch",
                    "/api/mailbox/gmail/webhook",
                    "/api/mailbox/attachment-candidates",
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
                    "Gmail imports store metadata/snippets only; raw provider payloads " +
                    "and OAuth tokens are never returned by APIs.",
                    "Attachment bytes are fetched only after explicit tenant review.",
                    "Matter association remains matter-code/review-first.",
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
                    "In-app previews are available; email/SMS/WhatsApp delivery " +
                    "requires provider approval.",
                    "Tenant email suppression exists for SendGrid-backed sends, " +
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
