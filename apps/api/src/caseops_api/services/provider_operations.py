from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
    ProviderCostCategory,
    TrackedCasePollRun,
    TrackedCaseProviderOperation,
    UserCalendarConnection,
)
from caseops_api.schemas.provider_operations import (
    ProviderOperationAction,
    ProviderOperationActionResponse,
    ProviderOperationListResponse,
    ProviderOperationRecord,
    ProviderOperationReplayBatchResponse,
    ProviderOperationReplayPreviewItem,
    ProviderOperationReplayPreviewResponse,
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
from caseops_api.services.provider_costs import effective_cost_minor
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
_REPLAY_PREVIEW_TTL_MINUTES = 5
_MAX_REPLAY_BATCH_SIZE = 25


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
            "case_tracking_record",
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


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _classify_response(record: ProviderOperationRecord) -> str:
    value = " ".join(
        part for part in (record.status, record.error_redacted, record.dead_letter_reason) if part
    ).lower()
    if record.status in {"synced", "delivered", "processed", "completed", "imported"}:
        return "success"
    if record.status in {"no_change", "duplicate"}:
        return "no_change"
    if "timeout" in value:
        return "timeout"
    if any(item in value for item in ("auth", "token", "scope")):
        return "authentication"
    if "rate" in value or "quota" in value:
        return "rate_limit"
    if any(item in value for item in ("parse", "schema", "malformed")):
        return "parse_error"
    if "outage" in value or "unavailable" in value:
        return "provider_outage"
    if "config" in value or "disabled" in value:
        return "configuration"
    if "policy" in value or "suppression" in value:
        return "policy"
    return "unknown"


def _enrich_operation(record: ProviderOperationRecord) -> ProviderOperationRecord:
    response_class = (
        record.response_class if record.response_class != "unknown" else _classify_response(record)
    )
    successful = response_class in {"success", "no_change"}
    freshness_state = (
        record.freshness_state
        if record.freshness_state != "unknown"
        else ("fresh" if successful else "never_succeeded")
    )
    if record.status in {"disabled"}:
        freshness_state = "disabled"
    elif record.status in {"blocked", "blocked_by_policy", "missing_config"}:
        freshness_state = "blocked"
    return record.model_copy(
        update={
            "correlation_ref": redact_identifier(record.id),
            "response_class": response_class,
            "last_attempted_at": record.last_attempted_at or record.updated_at,
            "last_successful_at": record.last_successful_at
            or (record.updated_at if successful else None),
            "last_good_at": record.last_good_at or (record.updated_at if successful else None),
            "next_scheduled_at": record.next_scheduled_at or record.next_attempt_at,
            "freshness_state": freshness_state,
            "retryable": record.replay_available,
            "quarantined": record.status == "dead_letter",
        }
    )


def _encode_preview(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).rstrip(b"=")
    signature = hmac.new(
        get_settings().auth_secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    return body.decode("ascii") + "." + base64.urlsafe_b64encode(signature).decode("ascii")


def _decode_preview(token: str, *, company_id: str) -> dict[str, Any]:
    try:
        body_text, signature_text = token.split(".", 1)
        body = body_text.encode("ascii")
        signature = base64.urlsafe_b64decode(signature_text.encode("ascii"))
        expected = hmac.new(
            get_settings().auth_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("signature")
        padded = body + b"=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if payload.get("version") != 1 or payload.get("company_id") != company_id:
            raise ValueError("scope")
        expires_at = datetime.fromtimestamp(int(payload["expires_at"]), tz=UTC)
        if expires_at <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Replay preview expired. Generate a new preview.",
            )
        operations = payload.get("operations")
        if not isinstance(operations, list) or not 1 <= len(operations) <= _MAX_REPLAY_BATCH_SIZE:
            raise ValueError("operations")
        return payload
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Replay preview token is invalid.",
        ) from None


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
        response_class=(
            "no_change"
            if row.status == "completed" and row.update_count == 0
            else "success"
            if row.status == "completed"
            else "unknown"
        ),
        last_attempted_at=row.started_at,
        last_successful_at=(row.completed_at if row.status == "completed" else None),
        last_good_at=(row.completed_at if row.status == "completed" else None),
        records_affected=row.update_count,
        replay_available=False,
        ignore_available=False,
        mark_resolved_available=False,
        notes=notes,
    )


def _case_tracking_record(row: TrackedCaseProviderOperation) -> ProviderOperationRecord:
    metadata = dict(row.metadata_json or {})
    operator_state = str(metadata.get("operator_state") or "open")
    response_classes = {
        "success",
        "no_change",
        "timeout",
        "authentication",
        "rate_limit",
        "parse_error",
        "provider_outage",
        "configuration",
        "policy",
        "unknown",
    }
    response_class = row.response_class or "unknown"
    if response_class not in response_classes:
        response_class = "unknown"
    last_successful_at = row.completed_at if row.status in {"succeeded", "no_change"} else None
    freshness = "never_succeeded"
    if row.tracked_case.last_provider_successful_at:
        freshness = str(row.tracked_case.provider_freshness_status or "fresh")
        if freshness not in {"fresh", "stale", "never_succeeded", "disabled", "blocked"}:
            freshness = "stale"
    if row.status == "quarantined":
        freshness = "blocked"
    open_action = row.status in {"failed", "quarantined", "pending", "replay_queued"}
    replayable = row.status in {"failed", "quarantined"} and (
        row.status == "quarantined" or row.attempts < row.max_attempts
    )
    return ProviderOperationRecord(
        id=_operation_id("case_tracking_record", row.id),
        job_kind="case_tracking_record",
        provider=row.provider,
        company_id=row.company_id,
        matter_id=None,
        source_type="tracked_case_provider_operation",
        source_ref=redact_identifier(row.tracked_case_id),
        provider_item_ref=None,
        status=row.status,
        operator_state=operator_state,
        error_redacted=redact_provider_error(row.error_redacted) if row.error_redacted else None,
        dead_letter_reason=(
            redact_provider_error(row.quarantine_reason_redacted)
            if row.quarantine_reason_redacted
            else None
        ),
        attempts=row.attempts,
        max_attempts=max(1, row.max_attempts),
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        correlation_ref=redact_identifier(row.correlation_id),
        response_class=response_class,
        last_attempted_at=row.started_at,
        last_successful_at=last_successful_at,
        last_good_at=row.tracked_case.last_provider_successful_at,
        next_scheduled_at=row.tracked_case.next_provider_refresh_at,
        freshness_state=freshness,
        records_affected=int(metadata.get("created_update_count") or 0),
        estimated_cost_minor=max(0, row.cost_minor),
        estimated_cost_currency=row.currency,
        estimated_cost_basis="recorded_case_tracking_operation",
        retryable=replayable,
        quarantined=row.status == "quarantined",
        replay_available=replayable and operator_state == "open",
        ignore_available=open_action and operator_state == "open",
        mark_resolved_available=open_action and operator_state == "open",
        notes=[
            f"operation_type={row.operation_type}",
            "Raw provider evidence and the normalized diff are retained append-only.",
            "Replay executes in the next bounded poll and remains tenant scoped.",
        ],
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
    last_success = _as_aware(row.last_success_at) if row.last_success_at else None
    freshness_state = "never_succeeded"
    if str(row.connected_state) == "disabled":
        freshness_state = "disabled"
    elif str(row.connected_state) in {"blocked_by_policy", "missing_config"}:
        freshness_state = "blocked"
    elif last_success is not None:
        freshness_state = "fresh" if _now() - last_success <= timedelta(days=1) else "stale"
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
        response_class=(
            "authentication"
            if str(row.connected_state) in {"token_expired", "scope_missing"}
            else "rate_limit"
            if str(row.connected_state) == "rate_limited"
            else "provider_outage"
            if str(row.connected_state) == "provider_outage"
            else "policy"
            if str(row.connected_state) == "blocked_by_policy"
            else "configuration"
            if str(row.connected_state) == "missing_config"
            else "success"
            if last_success is not None
            else "unknown"
        ),
        last_attempted_at=row.last_checked_at,
        last_successful_at=row.last_success_at,
        last_good_at=row.last_success_at,
        next_scheduled_at=row.next_retry_at,
        freshness_state=freshness_state,  # type: ignore[arg-type]
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
    tracking_operation_statuses = (
        ("failed", "quarantined", "pending", "replay_queued")
        if not include_resolved
        else (
            "failed",
            "quarantined",
            "pending",
            "replay_queued",
            "running",
            "succeeded",
            "no_change",
            "resolved",
            "ignored",
        )
    )
    tracking_operation_rows = list(
        session.scalars(
            select(TrackedCaseProviderOperation)
            .where(
                TrackedCaseProviderOperation.company_id == context.company.id,
                TrackedCaseProviderOperation.status.in_(tracking_operation_statuses),
            )
            .order_by(TrackedCaseProviderOperation.updated_at.desc())
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
        *(_case_tracking_record(row) for row in tracking_operation_rows),
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
    records = [_enrich_operation(row) for row in records[:limit]]
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


def _load_case_tracking_record_operation(
    session: Session,
    *,
    context: SessionContext,
    row_id: str,
) -> TrackedCaseProviderOperation:
    row = session.scalar(
        select(TrackedCaseProviderOperation).where(
            TrackedCaseProviderOperation.id == row_id,
            TrackedCaseProviderOperation.company_id == context.company.id,
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


def _load_operation_record(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
) -> ProviderOperationRecord:
    kind, row_id = _split_operation_id(operation_id)
    if kind == "calendar_sync":
        return _enrich_operation(
            _calendar_record(_load_calendar_operation(session, context=context, row_id=row_id))
        )
    if kind == "notification_delivery":
        return _enrich_operation(
            _notification_record(
                _load_notification_operation(session, context=context, row_id=row_id)
            )
        )
    if kind == "case_tracking_poll":
        return _enrich_operation(
            _case_tracking_poll_record(
                _load_case_tracking_poll_operation(session, context=context, row_id=row_id)
            )
        )
    if kind == "case_tracking_record":
        return _enrich_operation(
            _case_tracking_record(
                _load_case_tracking_record_operation(session, context=context, row_id=row_id)
            )
        )
    if kind == "mailbox_message_import":
        return _enrich_operation(
            _mailbox_import_record(
                _load_mailbox_import_operation(session, context=context, row_id=row_id)
            )
        )
    return _enrich_operation(
        _mailbox_webhook_record(
            _load_mailbox_webhook_operation(session, context=context, row_id=row_id)
        )
    )


def _replay_cost(
    session: Session,
    *,
    record: ProviderOperationRecord,
) -> tuple[int, str, str | None]:
    if record.job_kind == "notification_delivery" and record.provider == str(
        NotificationDeliveryChannel.IN_APP
    ):
        return 0, "internal_idempotent_delivery", None
    if record.job_kind == "case_tracking_poll":
        cost, source = effective_cost_minor(
            session,
            category=ProviderCostCategory.BULK_CASE_REFRESH,
            provider="case_tracking",
        )
        return cost, source, None
    if record.job_kind == "case_tracking_record":
        return (
            record.estimated_cost_minor,
            "recorded_case_tracking_operation",
            None,
        )
    return (
        0,
        "unpriced_provider_call",
        "Provider pricing is not configured for this operation; the preview cost is "
        "therefore zero-recorded-cost, not a representation that the provider is free.",
    )


def preview_provider_operation_replay(
    session: Session,
    *,
    context: SessionContext,
    operation_ids: list[str],
) -> ProviderOperationReplayPreviewResponse:
    if not 1 <= len(operation_ids) <= _MAX_REPLAY_BATCH_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Replay scope must contain 1 to {_MAX_REPLAY_BATCH_SIZE} operations.",
        )

    items: list[ProviderOperationReplayPreviewItem] = []
    token_operations: list[dict[str, str]] = []
    warnings: list[str] = []
    total_cost = 0
    for operation_id in operation_ids:
        record = _load_operation_record(
            session,
            context=context,
            operation_id=operation_id,
        )
        if not record.replay_available:
            record_from_context(
                session,
                context,
                action="provider_operation.replay_preview_denied",
                target_type="provider_operation",
                target_id=redact_identifier(operation_id),
                result=AuditResult.DENIED,
                metadata={
                    "job_kind": record.job_kind,
                    "provider": record.provider,
                    "reason": "operation_not_replayable",
                },
            )
            session.commit()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Provider operation {operation_id} is not replayable.",
            )
        cost, cost_basis, warning = _replay_cost(session, record=record)
        total_cost += cost
        if warning and warning not in warnings:
            warnings.append(warning)
        record = record.model_copy(
            update={
                "estimated_cost_minor": cost,
                "estimated_cost_basis": cost_basis,
            }
        )
        expected_updated_at = _as_aware(record.updated_at)
        items.append(
            ProviderOperationReplayPreviewItem(
                operation=record,
                expected_updated_at=expected_updated_at,
                estimated_cost_minor=cost,
                cost_basis=cost_basis,
            )
        )
        token_operations.append(
            {
                "id": operation_id,
                "status": record.status,
                "updated_at": expected_updated_at.isoformat(),
            }
        )

    expires_at = _now() + timedelta(minutes=_REPLAY_PREVIEW_TTL_MINUTES)
    preview_token = _encode_preview(
        {
            "version": 1,
            "company_id": context.company.id,
            "expires_at": int(expires_at.timestamp()),
            "nonce": secrets.token_urlsafe(12),
            "operations": token_operations,
            "estimated_total_cost_minor": total_cost,
            "currency": "INR",
        }
    )
    record_from_context(
        session,
        context,
        action="provider_operation.replay_previewed",
        target_type="provider_operation_batch",
        metadata={
            "operation_count": len(items),
            "estimated_total_cost_minor": total_cost,
            "currency": "INR",
            "expires_at": expires_at.isoformat(),
        },
    )
    session.commit()
    return ProviderOperationReplayPreviewResponse(
        preview_token=preview_token,
        expires_at=expires_at,
        operation_count=len(items),
        estimated_total_cost_minor=total_cost,
        items=items,
        warnings=warnings,
    )


def _validated_preview_operations(
    session: Session,
    *,
    context: SessionContext,
    preview_token: str,
    expected_operation_ids: list[str] | None = None,
) -> tuple[list[str], int]:
    payload = _decode_preview(preview_token, company_id=context.company.id)
    raw_operations = payload["operations"]
    operation_ids = [str(item.get("id") or "") for item in raw_operations]
    if expected_operation_ids is not None and operation_ids != expected_operation_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Replay preview scope does not match the requested operation.",
        )

    replay_targets = {
        "calendar_sync": "pending",
        "notification_delivery": "queued",
        "mailbox_message_import": "queued",
        "mailbox_webhook": "queued",
        "case_tracking_record": "replay_queued",
    }
    for expected in raw_operations:
        operation_id = str(expected.get("id") or "")
        current = _load_operation_record(
            session,
            context=context,
            operation_id=operation_id,
        )
        already_replayed = current.status == replay_targets.get(current.job_kind)
        if not already_replayed and (
            current.status != expected.get("status")
            or _as_aware(current.updated_at).isoformat() != expected.get("updated_at")
            or not current.replay_available
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Replay scope changed after preview. Refresh the operation list and "
                    "generate a new preview."
                ),
            )
    return operation_ids, int(payload.get("estimated_total_cost_minor") or 0)


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
    commit: bool = True,
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
        session.commit() if commit else session.flush()
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
        session.commit() if commit else session.flush()
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

    if kind == "case_tracking_record":
        row = _load_case_tracking_record_operation(session, context=context, row_id=row_id)
        previous_status = row.status
        changed = row.status in {"failed", "quarantined"} and (
            row.status == "quarantined" or row.attempts < row.max_attempts
        )
        if changed:
            replay = TrackedCaseProviderOperation(
                company_id=row.company_id,
                tracked_case_id=row.tracked_case_id,
                requested_by_membership_id=context.membership.id,
                provider=row.provider,
                operation_type="replay",
                correlation_id=secrets.token_hex(16),
                status="pending",
                cost_minor=row.cost_minor,
                currency=row.currency,
                attempts=0,
                max_attempts=row.max_attempts,
                next_attempt_at=current_time,
                metadata_json={
                    "scope": "single_tracked_case",
                    "cost_disclosed": True,
                    "replay_of_operation_id": row.id,
                },
            )
            session.add(replay)
            session.flush()
            row.status = "replay_queued"
            row.next_attempt_at = None
            row.metadata_json = {
                **dict(row.metadata_json or {}),
                "replay_requested_at": current_time.isoformat(),
                "replay_reason_present": bool(reason and reason.strip()),
                "replay_operation_id": replay.id,
                "operator_state": "open",
            }
            row.tracked_case.quarantined_at = None
            row.tracked_case.quarantine_reason_redacted = None
            row.tracked_case.next_provider_refresh_at = current_time
            session.add_all([row, replay, row.tracked_case])
        _audit_operation_action(
            session,
            context=context,
            action="replay",
            target_type="tracked_case_provider_operation",
            target_id=row.id,
            provider=row.provider,
            previous_status=previous_status,
            next_status=row.status,
            changed=changed,
            reason=reason,
        )
        session.commit() if commit else session.flush()
        return ProviderOperationActionResponse(
            action="replay",
            changed=changed,
            message=(
                "A new tracked-case provider operation was queued for the next bounded poll."
                if changed
                else "Tracked-case provider work was not replayable."
            ),
            operation=_case_tracking_record(row),
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
        session.commit() if commit else session.flush()
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
        session.commit() if commit else session.flush()
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
        session.commit() if commit else session.flush()
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
    session.commit() if commit else session.flush()
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


def confirm_provider_operation_replay(
    session: Session,
    *,
    context: SessionContext,
    preview_token: str,
    reason: str,
    expected_operation_ids: list[str] | None = None,
) -> ProviderOperationReplayBatchResponse:
    operation_ids, estimated_total_cost_minor = _validated_preview_operations(
        session,
        context=context,
        preview_token=preview_token,
        expected_operation_ids=expected_operation_ids,
    )
    responses: list[ProviderOperationActionResponse] = []
    try:
        for operation_id in operation_ids:
            response = replay_provider_operation(
                session,
                context=context,
                operation_id=operation_id,
                reason=reason,
                commit=False,
            )
            responses.append(
                response.model_copy(update={"operation": _enrich_operation(response.operation)})
            )
        record_from_context(
            session,
            context,
            action="provider_operation.replay_batch_confirmed",
            target_type="provider_operation_batch",
            metadata={
                "operation_count": len(responses),
                "changed_count": sum(response.changed for response in responses),
                "estimated_total_cost_minor": estimated_total_cost_minor,
                "currency": "INR",
                "reason_present": bool(reason.strip()),
            },
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return ProviderOperationReplayBatchResponse(
        changed_count=sum(response.changed for response in responses),
        unchanged_count=sum(not response.changed for response in responses),
        estimated_total_cost_minor=estimated_total_cost_minor,
        operations=responses,
    )


def resolve_case_tracking_incident(
    session: Session,
    *,
    context: SessionContext,
    operation_id: str,
    root_cause: str,
    prevention: str,
    canary_evidence: str,
) -> ProviderOperationActionResponse:
    kind, row_id = _split_operation_id(operation_id)
    if kind != "case_tracking_record":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Structured incident closure applies only to tracked-case record operations.",
        )
    row = _load_case_tracking_record_operation(session, context=context, row_id=row_id)
    metadata = dict(row.metadata_json or {})
    replay_id = str(metadata.get("replay_operation_id") or "")
    replay = (
        _load_case_tracking_record_operation(session, context=context, row_id=replay_id)
        if replay_id
        else None
    )
    if replay is None or replay.status not in {"succeeded", "no_change"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Run and monitor a successful bounded canary replay before closing this incident."
            ),
        )
    previous_status = row.status
    changed = row.status != "resolved"
    if changed:
        row.status = "resolved"
        row.next_attempt_at = None
        row.metadata_json = {
            **metadata,
            "operator_state": "resolved",
            "incident_closed_at": _now().isoformat(),
            "incident_root_cause": redact_provider_error(root_cause),
            "incident_prevention": redact_provider_error(prevention),
            "incident_canary_evidence": redact_provider_error(canary_evidence),
            "incident_canary_operation_id": replay.id,
        }
        session.add(row)
    _audit_operation_action(
        session,
        context=context,
        action="mark_resolved",
        target_type="tracked_case_provider_operation",
        target_id=row.id,
        provider=row.provider,
        previous_status=previous_status,
        next_status=row.status,
        changed=changed,
        reason=root_cause,
    )
    record_from_context(
        session,
        context,
        action="provider_operation.incident_closed",
        target_type="tracked_case_provider_operation",
        target_id=row.id,
        metadata={
            "provider": row.provider,
            "canary_operation_ref": redact_identifier(replay.id),
            "root_cause_present": True,
            "prevention_present": True,
            "canary_evidence_present": True,
        },
    )
    session.commit()
    return ProviderOperationActionResponse(
        action="mark_resolved",
        changed=changed,
        message=(
            "Tracked-case provider incident closed with successful canary evidence."
            if changed
            else "Tracked-case provider incident was already closed."
        ),
        operation=_case_tracking_record(row),
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

    if kind == "case_tracking_record":
        row = _load_case_tracking_record_operation(session, context=context, row_id=row_id)
        if action == "mark_resolved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Tracked-case incidents require root cause, prevention, and a successful "
                    "canary through the resolve-incident endpoint."
                ),
            )
        previous_status = row.status
        changed = row.status not in {"succeeded", "no_change", "resolved", "ignored"}
        if changed:
            if action == "ignore":
                row.status = "quarantined"
                row.quarantined_at = current_time
                row.quarantine_reason_redacted = redact_provider_error(reason or marker)
                row.tracked_case.quarantined_at = current_time
                row.tracked_case.quarantine_reason_redacted = row.quarantine_reason_redacted
                row.tracked_case.provider_freshness_status = "quarantined"
                operator_state = "open"
            else:
                row.status = "resolved"
                row.next_attempt_at = None
                operator_state = "resolved"
            row.metadata_json = {
                **dict(row.metadata_json or {}),
                "operator_state": operator_state,
                "operator_action_at": current_time.isoformat(),
                "incident_root_cause_present": bool(reason and reason.strip()),
            }
            session.add_all([row, row.tracked_case])
        _audit_operation_action(
            session,
            context=context,
            action=action,
            target_type="tracked_case_provider_operation",
            target_id=row.id,
            provider=row.provider,
            previous_status=previous_status,
            next_status=row.status,
            changed=changed,
            reason=reason,
        )
        session.commit()
        return ProviderOperationActionResponse(
            action=action,
            changed=changed,
            message=(
                "Tracked-case provider work was quarantined; other records may continue."
                if action == "ignore" and changed
                else "Tracked-case provider incident was marked resolved."
                if changed
                else "Tracked-case provider operation was already terminal."
            ),
            operation=_case_tracking_record(row),
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
                    "Manual bounded dry-run only; no OAuth tokens or Drive file "
                    + "contents are stored.",
                    "Durable sync must remain disabled until tenant approval and "
                    + "provider credentials are supplied.",
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
                    "Gmail imports store metadata/snippets only; raw provider payloads "
                    + "and OAuth tokens are never returned by APIs.",
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
                    "In-app previews are available; email/SMS/WhatsApp delivery "
                    + "requires provider approval.",
                    "Tenant email suppression exists for SendGrid-backed sends, "
                    + "but digest sending is not enabled.",
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
