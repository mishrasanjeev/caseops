from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, or_
from sqlalchemy.sql.elements import ColumnElement

from caseops_api.db.models import CalendarEventSync, CalendarEventSyncStatus

CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON = (
    "provider_upsert_claim_expired_remote_unknown"
)
CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE = (
    "calendar_upsert_outcome_unknown_reconciliation_required"
)
CALENDAR_UPSERT_CLAIM_PREFIX = "provider_upsert_claim:"
CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE = "calendar_upsert_claim_in_flight"
CALENDAR_OPERATOR_CLOSED_REASONS = frozenset(
    {"operator_ignored", "operator_resolved"}
)
CALENDAR_NON_REPLAYABLE_REASON_PREFIXES = (
    "projection_authority_invalid:",
    "provider_delete_",
)

CalendarUpsertClaimState = Literal[
    "none",
    "live",
    "expired",
    "manual_reconciliation",
]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def calendar_sync_requires_manual_reconciliation(
    row: CalendarEventSync,
) -> bool:
    """Return whether replay could duplicate an unreceipted remote create."""

    return bool(
        row.dead_letter_reason == CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
        and row.provider_event_id is None
    )


def calendar_sync_has_unreceipted_upsert_claim(
    row: CalendarEventSync,
) -> bool:
    """Return whether a dispatched no-ID create still has a durable claim.

    Projection and lifecycle writers must preserve this marker even after its
    lease timestamp passes. The calendar worker owns the atomic transition
    from an expired claim to the typed manual-reconciliation tombstone.
    """

    return bool(
        row.provider_event_id is None
        and str(row.dead_letter_reason or "").startswith(
            CALENDAR_UPSERT_CLAIM_PREFIX
        )
    )


def calendar_sync_upsert_claim_state(
    row: CalendarEventSync,
    *,
    now: datetime | None = None,
) -> CalendarUpsertClaimState:
    """Classify the no-receipt create state without changing the row.

    Callers may use this for records and advisory discovery. Any caller that
    acts on ``live`` or ``expired`` must first lock the exact
    ``CalendarEventSync`` row. Only the mutation helper below may turn an
    expired raw claim into the canonical reconciliation tombstone.
    """

    if calendar_sync_requires_manual_reconciliation(row):
        return "manual_reconciliation"
    if not calendar_sync_has_unreceipted_upsert_claim(row):
        return "none"
    current_time = now or datetime.now(UTC)
    if row.next_attempt_at is not None and _aware(row.next_attempt_at) > current_time:
        return "live"
    return "expired"


def materialize_expired_calendar_sync_upsert_claim(
    row: CalendarEventSync,
    *,
    now: datetime | None = None,
) -> bool:
    """Persist-ready transition from an expired raw claim to typed UNKNOWN.

    The caller must hold the exact Sync row lock plus every source parent lock
    required by its workflow. This helper only mutates the row; the caller owns
    ``session.add``/flush, projection recompute, audit, and commit atomically.
    """

    current_time = now or datetime.now(UTC)
    if calendar_sync_upsert_claim_state(row, now=current_time) != "expired":
        return False
    row.sync_status = CalendarEventSyncStatus.DEAD_LETTER
    row.dead_letter_reason = CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON
    row.last_error = "Calendar provider upsert outcome is unknown."
    row.next_attempt_at = None
    row.durable_last_attempt_at = current_time
    return True


def calendar_sync_automatic_replay_block_code(
    row: CalendarEventSync,
) -> str | None:
    claim_state = calendar_sync_upsert_claim_state(row)
    if claim_state in {"expired", "manual_reconciliation"}:
        return CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE
    if claim_state == "live":
        return CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE
    reason = str(row.dead_letter_reason or "")
    if reason in CALENDAR_OPERATOR_CLOSED_REASONS:
        return "calendar_operation_operator_closed"
    if reason.startswith("projection_authority_invalid:"):
        return "calendar_projection_authority_invalid"
    if reason.startswith("provider_delete_"):
        return "calendar_provider_delete_requires_exact_drain"
    return None


def calendar_sync_automatic_replay_allowed(row: CalendarEventSync) -> bool:
    return calendar_sync_automatic_replay_block_code(row) is None


def calendar_sync_replay_safe_clause() -> ColumnElement[bool]:
    """SQL equivalent used before LIMIT so a poison row cannot starve replay."""

    reason = CalendarEventSync.dead_letter_reason
    return and_(
        or_(
            reason.is_(None),
            reason != CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON,
            CalendarEventSync.provider_event_id.is_not(None),
        ),
        or_(
            reason.is_(None),
            reason.notin_(tuple(sorted(CALENDAR_OPERATOR_CLOSED_REASONS))),
        ),
        *(
            or_(reason.is_(None), ~reason.startswith(prefix))
            for prefix in CALENDAR_NON_REPLAYABLE_REASON_PREFIXES
        ),
    )


def calendar_sync_reconciliation_detail() -> dict[str, str]:
    return {
        "code": CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE,
        "message": (
            "The provider may already contain an unreceipted calendar copy. "
            "Automatic replay is disabled until the remote calendar is "
            "explicitly reconciled."
        ),
    }


def calendar_sync_claim_in_flight_detail() -> dict[str, str]:
    return {
        "code": CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE,
        "message": (
            "The calendar provider upsert is still in flight. Wait for its "
            "claim lease to finalize before taking an operator action."
        ),
    }


__all__ = [
    "CALENDAR_UPSERT_CLAIM_IN_FLIGHT_CODE",
    "CALENDAR_UPSERT_UNKNOWN_OUTCOME_CODE",
    "CALENDAR_UPSERT_UNKNOWN_OUTCOME_REASON",
    "CALENDAR_UPSERT_CLAIM_PREFIX",
    "calendar_sync_automatic_replay_allowed",
    "calendar_sync_automatic_replay_block_code",
    "calendar_sync_claim_in_flight_detail",
    "calendar_sync_reconciliation_detail",
    "calendar_sync_replay_safe_clause",
    "calendar_sync_has_unreceipted_upsert_claim",
    "calendar_sync_requires_manual_reconciliation",
    "calendar_sync_upsert_claim_state",
    "materialize_expired_calendar_sync_upsert_claim",
]
