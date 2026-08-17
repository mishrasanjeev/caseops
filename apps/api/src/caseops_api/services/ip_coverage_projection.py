"""Atomic projections for an IP deadline coverage cutover.

``IpDeadlineCoverage`` is the workflow decision row.  The operational
deadline, effective-dated responsibility evidence, calendar work, and queued
delivery intents are projections of that decision and must move in the same
database transaction.  This module deliberately performs no commit and no
provider I/O.

Callers must acquire locks in this order before changing the coverage row::

    CompanyMembership/User -> Matter -> IpDocketRecord -> IpDeadline
    -> MatterDeadline -> IpDeadlineCoverage -> IpResponsibilityAssignment
    -> CalendarEventSync -> UserCalendarConnection
    -> NotificationDeliveryIntent

The public cutover helper re-locks the deadline and coverage rows and acquires
the remaining child locks in that order.  ``previous_*`` values must be the
values observed before the caller changed the locked coverage row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    CalendarConnectionStatus,
    CalendarEventSync,
    CalendarEventSyncStatus,
    CalendarSyncSourceType,
    CompanyMembership,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpResponsibilityAssignment,
    MatterDeadline,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    UserCalendarConnection,
)
from caseops_api.services.calendar_projection_safety import (
    calendar_sync_upsert_claim_state,
    materialize_expired_calendar_sync_upsert_claim,
)
from caseops_api.services.notification_delivery import (
    cancel_pending_notification_intents,
    enqueue_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext

_ACTIVE_COVERAGE_STATUSES = {
    "accepted",
    "emergency",
    "escalated",
    "pending",
    "reassigned",
    "transfer_pending",
}


@dataclass(frozen=True, slots=True)
class CalendarProjectionCutoverResult:
    desired_connection_ids: tuple[str, ...]
    created_sync_ids: tuple[str, ...]
    revived_sync_ids: tuple[str, ...]
    tombstoned_sync_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CalendarProjectionTombstoneResult:
    tombstoned_sync_ids: tuple[str, ...]
    delete_pending_sync_ids: tuple[str, ...]
    deleted_sync_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IpCoverageTerminalProjectionResult:
    coverage_ids: tuple[str, ...]
    calendar: CalendarProjectionTombstoneResult


@dataclass(frozen=True, slots=True)
class NotificationProjectionCutoverResult:
    cancelled_intent_ids: tuple[str, ...]
    replacement_intent_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IpCoverageProjectionCutoverResult:
    matter_deadline_id: str
    ip_deadline_id: str | None
    expired_assignment_ids: tuple[str, ...]
    replacement_assignment_ids: tuple[str, ...]
    calendar: CalendarProjectionCutoverResult
    notifications: NotificationProjectionCutoverResult


@dataclass(frozen=True, slots=True)
class _ReminderTemplate:
    key: str
    channel: str
    event_type: str
    source_type: str
    notification_rule_id: str | None
    title: str | None
    body: str | None
    scheduled_for: datetime | None
    critical: bool
    confidentiality_mode: str
    recipient_membership_id: str
    original_intent_ids: tuple[str, ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _conflict(code: str, message: str, **metadata: object) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **metadata},
    )


def _member_label(membership: CompanyMembership) -> str:
    return membership.user.full_name or membership.user.email


def _load_resulting_memberships(
    session: Session,
    *,
    company_id: str,
    membership_ids: set[str],
) -> dict[str, CompanyMembership]:
    rows = list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.id.in_(sorted(membership_ids)),
            )
            .order_by(CompanyMembership.id)
            .execution_options(populate_existing=True)
        ).all()
    )
    found = {row.id: row for row in rows}
    if set(found) != membership_ids or any(
        not row.is_active or not row.user.is_active for row in rows
    ):
        raise _conflict(
            "ip_coverage_projection_membership_inactive",
            "Every resulting coverage owner must remain an active company member.",
            blocked_membership_ids=sorted(membership_ids - set(found)),
        )
    return found


def _lock_projection_deadline_and_coverage(
    session: Session,
    *,
    company_id: str,
    docket: IpDocketRecord,
    coverage: IpDeadlineCoverage,
) -> tuple[IpDeadline | None, MatterDeadline, IpDeadlineCoverage]:
    ip_deadline_id = session.scalar(
        select(IpDeadline.id).where(
            IpDeadline.company_id == company_id,
            IpDeadline.docket_id == docket.id,
            IpDeadline.matter_deadline_id == coverage.matter_deadline_id,
        )
    )
    ip_deadline = (
        session.scalar(
            select(IpDeadline)
            .where(
                IpDeadline.id == ip_deadline_id,
                IpDeadline.company_id == company_id,
                IpDeadline.docket_id == docket.id,
                IpDeadline.matter_deadline_id == coverage.matter_deadline_id,
            )
            .with_for_update(of=IpDeadline)
            .execution_options(populate_existing=True)
        )
        if ip_deadline_id is not None
        else None
    )
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == coverage.matter_deadline_id,
            MatterDeadline.company_id == company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    locked_coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.matter_deadline_id == coverage.matter_deadline_id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    )
    locked_coverage = next(
        (
            row
            for row in locked_coverages
            if row.id == coverage.id and row.docket_id == docket.id
        ),
        None,
    )
    operational_coverages = [
        row
        for row in locked_coverages
        if str(row.coverage_status) not in {"inactive_lifecycle", "completed"}
    ]
    if len(operational_coverages) > 1:
        raise _conflict(
            "ip_coverage_projection_shared_deadline_unsupported",
            "A deadline shared by multiple operational IP dockets requires a group cutover.",
            matter_deadline_id=coverage.matter_deadline_id,
            blocked_coverage_ids=[row.id for row in operational_coverages],
            blocked_docket_ids=sorted({row.docket_id for row in operational_coverages}),
        )
    linked_to_docket = bool(
        deadline is not None
        and (
            deadline.ip_docket_id == docket.id
            or (
                docket.matter_id is not None
                and deadline.matter_id == docket.matter_id
                and deadline.ip_docket_id is None
            )
        )
    )
    if deadline is None or locked_coverage is None or not linked_to_docket:
        raise _conflict(
            "ip_coverage_projection_target_mismatch",
            "Coverage no longer points at an operational deadline for this IP docket.",
            coverage_id=coverage.id,
        )
    if (
        not docket.is_active
        or docket.archived_by_matter_disposal
        or str(locked_coverage.coverage_status) not in _ACTIVE_COVERAGE_STATUSES
        or str(deadline.status) not in {"open", "missed"}
    ):
        raise _conflict(
            "ip_coverage_projection_inactive",
            "Lifecycle-neutralized coverage cannot create operational projections.",
            coverage_id=coverage.id,
        )
    if ip_deadline is not None and str(ip_deadline.state) not in {"confirmed", "overdue"}:
        raise _conflict(
            "ip_coverage_projection_legal_deadline_inactive",
            "Only a confirmed or overdue legal deadline may change responsibility.",
            ip_deadline_id=ip_deadline.id,
        )
    return ip_deadline, deadline, locked_coverage


def _cutover_responsibility_assignments(
    session: Session,
    *,
    context: SessionContext,
    deadline: MatterDeadline,
    coverage: IpDeadlineCoverage,
    ip_deadline: IpDeadline | None,
    previous_responsible_membership_id: str,
    previous_backup_membership_id: str | None,
    memberships: dict[str, CompanyMembership],
    reason: str,
    replacement_source: str,
    responsible_accepted_at: datetime | None,
    changed_at: datetime,
) -> tuple[list[str], list[str], list[IpResponsibilityAssignment]]:
    if deadline.assignee_membership_id != previous_responsible_membership_id:
        raise _conflict(
            "ip_coverage_projection_assignee_mismatch",
            "The operational deadline assignee does not match the prior coverage owner.",
            matter_deadline_id=deadline.id,
        )

    if ip_deadline is None:
        deadline.assignee_membership_id = coverage.responsible_membership_id
        session.add(deadline)
        return [], [], []

    active = list(
        session.scalars(
            select(IpResponsibilityAssignment)
            .where(
                IpResponsibilityAssignment.company_id == context.company.id,
                IpResponsibilityAssignment.docket_id == coverage.docket_id,
                IpResponsibilityAssignment.deadline_id == ip_deadline.id,
                IpResponsibilityAssignment.effective_until.is_(None),
            )
            .order_by(IpResponsibilityAssignment.role, IpResponsibilityAssignment.id)
            .with_for_update(of=IpResponsibilityAssignment)
            .execution_options(populate_existing=True)
        ).all()
    )
    primary_rows = [row for row in active if row.role == "primary"]
    if len(primary_rows) != 1 or (
        primary_rows[0].membership_id != previous_responsible_membership_id
    ):
        raise _conflict(
            "ip_coverage_projection_primary_history_mismatch",
            "Exactly one active primary responsibility must match the prior coverage owner.",
            ip_deadline_id=ip_deadline.id,
            active_primary_assignment_ids=[row.id for row in primary_rows],
        )

    backup_evidence_rows = [
        row
        for row in active
        if row.role in {"backup", "supervisor", "docketing"}
        and row.membership_id == previous_backup_membership_id
        and row.accepted_at is not None
    ]
    if previous_backup_membership_id is not None and not backup_evidence_rows:
        raise _conflict(
            "ip_coverage_projection_backup_history_mismatch",
            "Active backup responsibility does not match the prior coverage backup.",
            ip_deadline_id=ip_deadline.id,
        )
    colliding_secondary_rows = [
        row
        for row in active
        if row.role in {"backup", "supervisor", "docketing"}
        and row.membership_id == coverage.responsible_membership_id
    ]
    if colliding_secondary_rows:
        raise _conflict(
            "ip_coverage_projection_primary_secondary_collision",
            "The resulting primary already has an active secondary responsibility.",
            ip_deadline_id=ip_deadline.id,
            conflicting_assignment_ids=[row.id for row in colliding_secondary_rows],
            conflicting_roles=sorted({row.role for row in colliding_secondary_rows}),
        )
    if coverage.backup_membership_id != previous_backup_membership_id:
        raise _conflict(
            "ip_coverage_projection_backup_change_unsupported",
            "Backup-role changes require an explicit responsibility decision and are refused.",
            ip_deadline_id=ip_deadline.id,
        )

    deadline.assignee_membership_id = coverage.responsible_membership_id
    session.add(deadline)
    if (
        coverage.responsible_membership_id == previous_responsible_membership_id
        and responsible_accepted_at is not None
        and primary_rows[0].accepted_at is None
    ):
        # Immediate/emergency assignment is operational before acceptance.
        # When that same owner later accepts, stamp the live evidence instead
        # of manufacturing a replacement history row. Acceptance is itself a
        # versioned legal decision, so preserve its reason/source provenance
        # on the evidence row instead of silently changing only a timestamp.
        primary_rows[0].accepted_at = responsible_accepted_at
        primary_rows[0].delegation_reason = reason
        primary_rows[0].replacement_source = replacement_source
        primary_rows[0].version += 1
        session.add(primary_rows[0])

    replacements: list[tuple[IpResponsibilityAssignment, str, datetime | None]] = []
    if coverage.responsible_membership_id != previous_responsible_membership_id:
        replacements.append(
            (primary_rows[0], coverage.responsible_membership_id, responsible_accepted_at)
        )
    expired_ids: list[str] = []
    replacement_rows: list[IpResponsibilityAssignment] = []
    for old_row, new_membership_id, accepted_at in replacements:
        old_row.effective_until = changed_at
        session.add(old_row)
        expired_ids.append(old_row.id)
        if not new_membership_id:
            continue
        membership = memberships[new_membership_id]
        replacement = IpResponsibilityAssignment(
            company_id=old_row.company_id,
            docket_id=old_row.docket_id,
            deadline_id=old_row.deadline_id,
            membership_id=membership.id,
            membership_label_snapshot=_member_label(membership),
            role=old_row.role,
            effective_from=changed_at,
            accepted_at=accepted_at,
            delegation_reason=reason,
            replacement_source=replacement_source,
            escalation_policy_json=dict(old_row.escalation_policy_json or {}),
            version=old_row.version + 1,
            created_by_membership_id=context.membership.id,
            creator_label_snapshot=_member_label(context.membership),
        )
        session.add(replacement)
        replacement_rows.append(replacement)
    session.flush()
    return expired_ids, [row.id for row in replacement_rows], active + replacement_rows


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


def tombstone_matter_deadline_calendar_projections(
    session: Session,
    *,
    company_id: str,
    matter_deadline_id: str,
    reason: str,
    changed_at: datetime | None = None,
) -> CalendarProjectionTombstoneResult:
    """Terminalize every exact-source calendar row without provider I/O.

    Callers cutting over multiple old/new sources must pre-lock all source
    parents in sorted order. This primitive re-locks its MatterDeadline, then
    locks CalendarEventSync rows in the canonical child order.
    """

    if not reason:
        raise ValueError("Calendar tombstones require a reason.")
    session.flush()
    session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == matter_deadline_id,
            MatterDeadline.company_id == company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    rows = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == company_id,
                CalendarEventSync.source_type
                == CalendarSyncSourceType.MATTER_DEADLINE.value,
                CalendarEventSync.source_id == matter_deadline_id,
            )
            .order_by(CalendarEventSync.calendar_connection_id, CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    return _tombstone_calendar_sync_rows(
        session,
        rows=rows,
        changed_at=changed_at or _now(),
        reason=reason,
    )


def terminalize_coverage_only_deadline_projection(
    session: Session,
    *,
    company_id: str,
    matter_deadline_id: str,
    reason: str,
    changed_at: datetime | None = None,
) -> IpCoverageTerminalProjectionResult:
    """Atomically complete coverage-only state and exact calendar work.

    The caller must already own the canonical Membership -> Matter -> sorted
    docket(s) -> MatterDeadline -> coverage-family locks. This helper takes no
    Membership lock and performs no provider I/O. It re-locks the source and
    all sibling coverages defensively, rejects a typed ``IpDeadline`` link,
    then terminalizes every exact calendar row and every non-lifecycle-terminal
    coverage in the same transaction.
    """

    if not reason:
        raise ValueError("Coverage terminalization requires a reason.")
    session.flush()
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == matter_deadline_id,
            MatterDeadline.company_id == company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    if deadline is None:
        raise _conflict(
            "ip_coverage_projection_deadline_missing",
            "The covered Matter deadline no longer exists.",
            matter_deadline_id=matter_deadline_id,
        )
    coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == company_id,
                IpDeadlineCoverage.matter_deadline_id == matter_deadline_id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    )
    if not coverages:
        raise _conflict(
            "ip_coverage_projection_missing",
            "The Matter deadline has no IP coverage projection to terminalize.",
            matter_deadline_id=matter_deadline_id,
        )
    linked_ip_deadline_id = session.scalar(
        select(IpDeadline.id)
        .where(
            IpDeadline.company_id == company_id,
            IpDeadline.matter_deadline_id == matter_deadline_id,
        )
        .limit(1)
    )
    if linked_ip_deadline_id is not None:
        raise _conflict(
            "ip_deadline_workflow_required",
            "Typed IP legal-deadline lifecycle must use its dedicated workflow.",
            matter_deadline_id=matter_deadline_id,
            ip_deadline_id=linked_ip_deadline_id,
        )

    at = changed_at or _now()
    calendar = tombstone_matter_deadline_calendar_projections(
        session,
        company_id=company_id,
        matter_deadline_id=matter_deadline_id,
        reason=reason,
        changed_at=at,
    )
    for coverage in coverages:
        if str(coverage.coverage_status) == "inactive_lifecycle":
            continue
        coverage.coverage_status = "completed"
        coverage.calendar_projection_status = "completed"
        coverage.updated_at = at
        session.add(coverage)
    session.flush()
    return IpCoverageTerminalProjectionResult(
        coverage_ids=tuple(row.id for row in coverages),
        calendar=calendar,
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


def reconcile_ip_coverage_calendar_projections(
    session: Session,
    *,
    coverage: IpDeadlineCoverage,
    changed_at: datetime | None = None,
) -> CalendarProjectionCutoverResult:
    """Reconcile all provider connections without contacting a provider.

    Connected calendars for the resulting responsible/backup memberships are
    desired.  Every other historical sync for this source is a tombstone.
    Lifecycle-neutralized rows are irreversible history and are never revived.
    """

    # CaseOps sessions deliberately disable autoflush. Preserve a caller's
    # already-decided coverage fields before populate_existing refreshes the
    # authoritative locked row.
    session.flush()
    at = changed_at or _now()
    # Lock the source parent before every coverage child. Besides making this
    # public primitive safe to call on its own, the parent lock prevents a new
    # sibling coverage from being inserted through the deadline FK while the
    # desired calendar set is computed.
    deadline = session.scalar(
        select(MatterDeadline)
        .where(
            MatterDeadline.id == coverage.matter_deadline_id,
            MatterDeadline.company_id == coverage.company_id,
        )
        .with_for_update(of=MatterDeadline)
        .execution_options(populate_existing=True)
    )
    locked_coverages = list(
        session.scalars(
            select(IpDeadlineCoverage)
            .where(
                IpDeadlineCoverage.company_id == coverage.company_id,
                IpDeadlineCoverage.matter_deadline_id
                == coverage.matter_deadline_id,
            )
            .order_by(IpDeadlineCoverage.id)
            .with_for_update(of=IpDeadlineCoverage)
            .execution_options(populate_existing=True)
        ).all()
    )
    locked_coverage = next(
        (row for row in locked_coverages if row.id == coverage.id),
        None,
    )
    operational_coverages = [
        row
        for row in locked_coverages
        if str(row.coverage_status) not in {"inactive_lifecycle", "completed"}
    ]
    if len(operational_coverages) > 1:
        raise _conflict(
            "ip_coverage_projection_shared_deadline_unsupported",
            "A deadline shared by multiple operational IP dockets requires a group cutover.",
            matter_deadline_id=coverage.matter_deadline_id,
            blocked_coverage_ids=[row.id for row in operational_coverages],
            blocked_docket_ids=sorted({row.docket_id for row in operational_coverages}),
        )
    if (
        deadline is None
        or locked_coverage is None
        or operational_coverages != [locked_coverage]
    ):
        raise _conflict(
            "ip_coverage_projection_inactive",
            "Lifecycle-neutralized coverage cannot create operational projections.",
            coverage_id=coverage.id,
        )
    coverage = locked_coverage
    desired_memberships = {
        membership_id
        for membership_id in (
            coverage.responsible_membership_id,
            coverage.backup_membership_id,
        )
        if membership_id
    }
    sync_rows = list(
        session.scalars(
            select(CalendarEventSync)
            .where(
                CalendarEventSync.company_id == coverage.company_id,
                CalendarEventSync.source_type
                == CalendarSyncSourceType.MATTER_DEADLINE.value,
                CalendarEventSync.source_id == coverage.matter_deadline_id,
            )
            .order_by(CalendarEventSync.calendar_connection_id, CalendarEventSync.id)
            .with_for_update(of=CalendarEventSync)
            .execution_options(populate_existing=True)
        ).all()
    )
    existing_connection_ids = {row.calendar_connection_id for row in sync_rows}
    role_connection_ids = set(
        session.scalars(
            select(UserCalendarConnection.id).where(
                UserCalendarConnection.company_id == coverage.company_id,
                UserCalendarConnection.membership_id.in_(sorted(desired_memberships)),
            )
        ).all()
    )
    connection_ids = sorted(existing_connection_ids | role_connection_ids)
    connections = (
        list(
            session.scalars(
                select(UserCalendarConnection)
                .where(UserCalendarConnection.id.in_(connection_ids))
                .order_by(UserCalendarConnection.id)
                .with_for_update(of=UserCalendarConnection)
                .execution_options(populate_existing=True)
            ).all()
        )
        if connection_ids
        else []
    )
    desired_connection_ids = {
        row.id
        for row in connections
        if row.membership_id in desired_memberships
        and row.status == CalendarConnectionStatus.CONNECTED
    }
    by_connection = {row.calendar_connection_id: row for row in sync_rows}
    created: list[str] = []
    revived: list[str] = []
    tombstoned: list[str] = []

    claim_states: dict[str, str] = {}
    for row in sync_rows:
        claim_state = calendar_sync_upsert_claim_state(row, now=at)
        if claim_state == "expired":
            materialize_expired_calendar_sync_upsert_claim(row, now=at)
            session.add(row)
            claim_state = "manual_reconciliation"
        claim_states[row.id] = claim_state

    for connection_id in sorted(desired_connection_ids):
        row = by_connection.get(connection_id)
        if row is None:
            row = CalendarEventSync(
                company_id=coverage.company_id,
                calendar_connection_id=connection_id,
                source_type=CalendarSyncSourceType.MATTER_DEADLINE.value,
                source_id=coverage.matter_deadline_id,
                sync_status=CalendarEventSyncStatus.PENDING,
            )
            session.add(row)
            session.flush()
            by_connection[connection_id] = row
            sync_rows.append(row)
            created.append(row.id)
            continue
        if claim_states.get(row.id) in {"live", "manual_reconciliation"}:
            # Live provider work keeps its exact durable claim; a typed
            # unknown-outcome row is operator-only. Neither state may be
            # revived by a responsibility cutover.
            continue
        if row.neutralized_by_ip_lifecycle_event_id is not None:
            raise _conflict(
                "ip_coverage_projection_lifecycle_tombstone",
                "A lifecycle-neutralized calendar projection cannot be revived.",
                calendar_event_sync_id=row.id,
            )
        if row.sync_status in {
            CalendarEventSyncStatus.DELETED,
            CalendarEventSyncStatus.DELETE_PENDING,
            CalendarEventSyncStatus.FAILED,
            CalendarEventSyncStatus.RETRY_SCHEDULED,
            CalendarEventSyncStatus.DEAD_LETTER,
        }:
            if row.sync_status == CalendarEventSyncStatus.DELETED:
                row.provider_event_id = None
            row.sync_status = CalendarEventSyncStatus.PENDING
            row.attempts = 0
            row.next_attempt_at = None
            row.last_error = None
            row.dead_letter_reason = None
            row.durable_last_attempt_at = None
            row.drift_status = "unchecked"
            row.drift_checked_at = None
            row.drift_detail = None
            revived.append(row.id)
            session.add(row)

    for row in sync_rows:
        if row.calendar_connection_id in desired_connection_ids:
            continue
        if row.neutralized_by_ip_lifecycle_event_id is not None:
            continue
        if not _tombstone_calendar_sync_row(
            row,
            changed_at=at,
            reason="coverage_assignment_changed",
        ):
            continue
        tombstoned.append(row.id)
        session.add(row)

    all_desired_synced = all(
        by_connection[connection_id].sync_status == CalendarEventSyncStatus.SYNCED
        for connection_id in desired_connection_ids
    )
    all_undesired_deleted = all(
        row.sync_status == CalendarEventSyncStatus.DELETED
        for row in sync_rows
        if row.calendar_connection_id not in desired_connection_ids
    )
    coverage.calendar_projection_status = (
        "projected" if all_desired_synced and all_undesired_deleted else "pending"
    )
    session.add(coverage)
    session.flush()
    return CalendarProjectionCutoverResult(
        desired_connection_ids=tuple(sorted(desired_connection_ids)),
        created_sync_ids=tuple(created),
        revived_sync_ids=tuple(revived),
        tombstoned_sync_ids=tuple(tombstoned),
    )


def _reminder_template_key(intent: NotificationDeliveryIntent) -> str:
    values = (
        str(intent.channel),
        intent.event_type,
        intent.source_type,
        intent.notification_rule_id or "",
        intent.scheduled_for.isoformat() if intent.scheduled_for else "",
        "1" if intent.critical else "0",
        intent.confidentiality_mode,
        intent.title or "",
        intent.body or "",
        intent.recipient_membership_id or "",
    )
    return sha256("\x1f".join(values).encode("utf-8")).hexdigest()


def cutover_ip_deadline_notification_intents(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    ip_deadline: IpDeadline,
    previous_primary_membership_id: str,
    resulting_primary_membership: CompanyMembership,
    escalation_membership: CompanyMembership | None,
    generation: str,
) -> NotificationProjectionCutoverResult:
    """Cancel queued/retry rows and create generation-scoped IP replacements.

    Sent/delivered/blocked/cancelled/dead-letter rows remain immutable history.
    Unchanged backup/supervisor/docketing recipients retain their existing
    rows and policy; only old-primary rows are superseded.
    Replacements target ``ip_docket_id`` so dispatch always reauthorizes IP
    access (and linked-Matter access) instead of relying on Matter access alone.
    """

    generation_digest = sha256(generation.encode("utf-8")).hexdigest()[:16]
    source_prefix = f"ipcov:{ip_deadline.id}:{generation_digest}:"
    pending = list(
        session.scalars(
            select(NotificationDeliveryIntent)
            .where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.schedule_source_type == "ip_deadline",
                NotificationDeliveryIntent.schedule_source_id == ip_deadline.id,
                NotificationDeliveryIntent.status.in_(
                    (
                        NotificationDeliveryStatus.QUEUED,
                        NotificationDeliveryStatus.RETRY_SCHEDULED,
                    )
                ),
                NotificationDeliveryIntent.recipient_membership_id.is_not(None),
                ~NotificationDeliveryIntent.source_id.startswith(source_prefix),
                NotificationDeliveryIntent.recipient_membership_id
                == previous_primary_membership_id,
            )
            .order_by(NotificationDeliveryIntent.id)
            .with_for_update(of=NotificationDeliveryIntent)
            .execution_options(populate_existing=True)
        ).all()
    )
    grouped: dict[str, list[NotificationDeliveryIntent]] = {}
    for intent in pending:
        grouped.setdefault(_reminder_template_key(intent), []).append(intent)
    templates = [
        _ReminderTemplate(
            key=key,
            channel=rows[0].channel,
            event_type=rows[0].event_type,
            source_type=rows[0].source_type,
            notification_rule_id=rows[0].notification_rule_id,
            title=rows[0].title,
            body=rows[0].body,
            scheduled_for=rows[0].scheduled_for,
            critical=rows[0].critical,
            confidentiality_mode=rows[0].confidentiality_mode,
            recipient_membership_id=str(rows[0].recipient_membership_id),
            original_intent_ids=tuple(row.id for row in rows),
        )
        for key, rows in sorted(grouped.items())
    ]
    if pending:
        cancel_pending_notification_intents(
            session,
            company_id=context.company.id,
            schedule_source_type="ip_deadline",
            schedule_source_id=ip_deadline.id,
            exclude_source_id_prefix=source_prefix,
            cancellation_reason="coverage_assignment_changed",
            intent_ids=(row.id for row in pending),
        )

    replacements: list[NotificationDeliveryIntent] = []
    replacement_by_template: dict[str, list[NotificationDeliveryIntent]] = {}
    for template in templates:
        recipient = resulting_primary_membership
        source_id = f"{source_prefix}{recipient.id[:12]}:{template.key[:16]}"
        replacement = enqueue_notification_delivery_intent(
            session,
            context=context,
            recipient_membership=recipient,
            channel=template.channel,
            event_type=template.event_type,
            source_type=template.source_type,
            source_id=source_id,
            ip_docket=docket,
            notification_rule_id=template.notification_rule_id,
            title=template.title,
            body=template.body,
            scheduled_for=template.scheduled_for,
            critical=template.critical,
            escalation_membership=escalation_membership,
            confidentiality_mode=template.confidentiality_mode,
            schedule_source_type="ip_deadline",
            schedule_source_id=ip_deadline.id,
        )
        if replacement is None:
            raise _conflict(
                "ip_coverage_projection_notification_recipient_denied",
                "A resulting coverage owner is not authorized for deadline reminders.",
                recipient_membership_id=recipient.id,
            )
        replacements.append(replacement)
        replacement_by_template.setdefault(template.key, []).append(replacement)

    pending_by_id = {row.id: row for row in pending}
    for template in templates:
        candidates = replacement_by_template.get(template.key, [])
        if not candidates:
            continue
        replacement_id = sorted(candidates, key=lambda row: row.id)[0].id
        for old_id in template.original_intent_ids:
            pending_by_id[old_id].superseded_by_intent_id = replacement_id
            session.add(pending_by_id[old_id])
    session.flush()
    return NotificationProjectionCutoverResult(
        cancelled_intent_ids=tuple(row.id for row in pending),
        replacement_intent_ids=tuple(row.id for row in replacements),
    )


def cutover_ip_coverage_projection(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    coverage: IpDeadlineCoverage,
    previous_responsible_membership_id: str,
    previous_backup_membership_id: str | None,
    reason: str,
    replacement_source: str,
    responsible_accepted_at: datetime | None,
    notification_escalation_membership_id: str | None = None,
    reminder_generation: str | None = None,
    changed_at: datetime | None = None,
) -> IpCoverageProjectionCutoverResult:
    """Cut over every database projection of one locked coverage decision.

    The caller owns the transaction.  It must have locked all old/new/actor
    memberships and the Matter/docket/deadline/coverage chain in the documented
    order, and must already have written the resulting responsible/backup ids
    to ``coverage``.  No commit or external provider call occurs here.
    """

    if docket.company_id != context.company.id or coverage.company_id != context.company.id:
        raise _conflict(
            "ip_coverage_projection_tenant_mismatch",
            "Coverage projection targets must belong to the current company.",
        )
    if not replacement_source or len(replacement_source) > 120:
        raise ValueError("replacement_source must contain 1 to 120 characters")
    # Callers mutate the locked decision row first and CaseOps sessions have
    # autoflush disabled. Flush only to this transaction before refreshing the
    # source chain; the helper never commits.
    session.flush()
    at = changed_at or _now()
    ip_deadline, deadline, locked_coverage = _lock_projection_deadline_and_coverage(
        session,
        company_id=context.company.id,
        docket=docket,
        coverage=coverage,
    )
    if locked_coverage.backup_membership_id != previous_backup_membership_id:
        raise _conflict(
            "ip_coverage_projection_backup_change_unsupported",
            "Backup-role changes require an explicit responsibility decision and are refused.",
            coverage_id=locked_coverage.id,
        )
    resulting_ids = {
        membership_id
        for membership_id in (
            locked_coverage.responsible_membership_id,
            locked_coverage.backup_membership_id,
        )
        if membership_id
    }
    membership_ids_to_load = set(resulting_ids)
    if notification_escalation_membership_id is not None:
        membership_ids_to_load.add(notification_escalation_membership_id)
    memberships = _load_resulting_memberships(
        session,
        company_id=context.company.id,
        membership_ids=membership_ids_to_load,
    )
    expired_ids, replacement_ids, _assignment_rows = _cutover_responsibility_assignments(
        session,
        context=context,
        deadline=deadline,
        coverage=locked_coverage,
        ip_deadline=ip_deadline,
        previous_responsible_membership_id=previous_responsible_membership_id,
        previous_backup_membership_id=previous_backup_membership_id,
        memberships=memberships,
        reason=reason,
        replacement_source=replacement_source,
        responsible_accepted_at=responsible_accepted_at,
        changed_at=at,
    )
    calendar = reconcile_ip_coverage_calendar_projections(
        session,
        coverage=locked_coverage,
        changed_at=at,
    )

    notifications = NotificationProjectionCutoverResult((), ())
    roles_changed = (
        previous_responsible_membership_id
        != locked_coverage.responsible_membership_id
        or previous_backup_membership_id != locked_coverage.backup_membership_id
    )
    if ip_deadline is not None and roles_changed:
        notifications = cutover_ip_deadline_notification_intents(
            session,
            context=context,
            docket=docket,
            ip_deadline=ip_deadline,
            previous_primary_membership_id=previous_responsible_membership_id,
            resulting_primary_membership=memberships[
                locked_coverage.responsible_membership_id
            ],
            escalation_membership=(
                memberships.get(notification_escalation_membership_id)
                if notification_escalation_membership_id
                else None
            ),
            generation=(
                reminder_generation
                or f"coverage:{locked_coverage.id}:v{locked_coverage.reassignment_version}"
            ),
        )
    session.flush()
    return IpCoverageProjectionCutoverResult(
        matter_deadline_id=deadline.id,
        ip_deadline_id=ip_deadline.id if ip_deadline is not None else None,
        expired_assignment_ids=tuple(expired_ids),
        replacement_assignment_ids=tuple(replacement_ids),
        calendar=calendar,
        notifications=notifications,
    )


__all__ = [
    "CalendarProjectionCutoverResult",
    "CalendarProjectionTombstoneResult",
    "IpCoverageProjectionCutoverResult",
    "IpCoverageTerminalProjectionResult",
    "NotificationProjectionCutoverResult",
    "cutover_ip_coverage_projection",
    "cutover_ip_deadline_notification_intents",
    "reconcile_ip_coverage_calendar_projections",
    "terminalize_coverage_only_deadline_projection",
    "tombstone_matter_deadline_calendar_projections",
    "tombstone_membership_calendar_projections",
]
