"""Provider-free calendar withdrawal primitives for lifecycle and offboarding."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CalendarEventSync,
    CalendarEventSyncStatus,
    UserCalendarConnection,
)
from caseops_api.services.calendar_projection_safety import (
    calendar_sync_upsert_claim_state,
    materialize_expired_calendar_sync_upsert_claim,
)


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CalendarProjectionTombstoneResult:
    tombstoned_sync_ids: tuple[str, ...]
    delete_pending_sync_ids: tuple[str, ...]
    deleted_sync_ids: tuple[str, ...]



def _tombstone_calendar_sync_row(
    row: CalendarEventSync,
    *,
    changed_at: datetime,
    reason: str,
) -> bool:
    """Create durable delete work without erasing provider/history evidence."""

    upsert_claim_state = calendar_sync_upsert_claim_state(row, now=changed_at)
    if upsert_claim_state == "live":
        # A committed create claim means provider I/O is still in flight. Keep
        # its exact marker/status and credential fence for the claimant.
        return False
    if upsert_claim_state == "expired":
        # The provider may have accepted the create without returning a
        # receipt. Materialize the canonical operator-only tombstone while the
        # exact source and Sync locks are still held.
        return materialize_expired_calendar_sync_upsert_claim(
            row,
            now=changed_at,
        )
    if upsert_claim_state == "manual_reconciliation":
        # With neither a provider receipt nor a proven absence, "deleted"
        # would be a false assertion and would make this row replayable after
        # a later assignment/lifecycle change.
        return False
    if row.sync_status == CalendarEventSyncStatus.DELETED:
        return False
    if row.provider_event_id:
        if row.sync_status != CalendarEventSyncStatus.DELETE_PENDING:
            # A new authoritative tombstone revives an earlier upsert/delete
            # failure, but repeated terminalization must not reset backoff.
            row.attempts = 0
            row.last_error = None
            row.durable_last_attempt_at = None
        row.sync_status = CalendarEventSyncStatus.DELETE_PENDING
        row.next_attempt_at = changed_at
        row.dead_letter_reason = reason[:160]
    else:
        row.sync_status = CalendarEventSyncStatus.DELETED
        row.next_attempt_at = None
        row.last_error = None
        row.dead_letter_reason = None
        row.last_synced_at = changed_at
    row.drift_status = "unchecked"
    row.drift_checked_at = None
    row.drift_detail = None
    return True



def _tombstone_calendar_sync_rows(
    session: Session,
    *,
    rows: list[CalendarEventSync],
    changed_at: datetime,
    reason: str,
) -> CalendarProjectionTombstoneResult:
    tombstoned: list[str] = []
    delete_pending: list[str] = []
    deleted: list[str] = []
    for row in rows:
        if not _tombstone_calendar_sync_row(
            row,
            changed_at=changed_at,
            reason=reason,
        ):
            continue
        tombstoned.append(row.id)
        if row.sync_status == CalendarEventSyncStatus.DELETE_PENDING:
            delete_pending.append(row.id)
        elif row.sync_status == CalendarEventSyncStatus.DELETED:
            deleted.append(row.id)
        session.add(row)
    session.flush()
    return CalendarProjectionTombstoneResult(
        tombstoned_sync_ids=tuple(tombstoned),
        delete_pending_sync_ids=tuple(delete_pending),
        deleted_sync_ids=tuple(deleted),
    )



def tombstone_membership_calendar_projections(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
    reason: str,
    changed_at: datetime | None = None,
) -> CalendarProjectionTombstoneResult:
    """Terminalize all calendar rows owned by one fenced membership.

    The membership must already be locked by the caller. Connection ids are
    discovered without locks; Sync rows are then locked before Connection rows
    and membership ownership is revalidated before any state changes.
    """

    if not reason:
        raise ValueError("Calendar tombstones require a reason.")
    connection_ids = sorted(
        session.scalars(
            select(UserCalendarConnection.id).where(
                UserCalendarConnection.company_id == company_id,
                UserCalendarConnection.membership_id == membership_id,
            )
        ).all()
    )
    if not connection_ids:
        return CalendarProjectionTombstoneResult((), (), ())
    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == company_id,
                CalendarEventSync.calendar_connection_id.in_(connection_ids),
            )
            .order_by(CalendarEventSync.calendar_connection_id, CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    connections = list(
        session.scalars(
            select(UserCalendarConnection)
            .where(
                UserCalendarConnection.id.in_(connection_ids),
                UserCalendarConnection.company_id == company_id,
            )
            .order_by(UserCalendarConnection.id)
            .with_for_update(of=UserCalendarConnection)
            .execution_options(populate_existing=True)
        ).all()
    )
    authorized_connection_ids = {
        row.id for row in connections if row.membership_id == membership_id
    }
    return _tombstone_calendar_sync_rows(
        session,
        rows=[
            row
            for row in rows
            if row.calendar_connection_id in authorized_connection_ids
        ],
        changed_at=changed_at or _now(),
        reason=reason,
    )
