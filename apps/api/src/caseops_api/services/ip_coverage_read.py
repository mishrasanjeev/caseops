"""Read-only operational coverage inventory shared with employee offboarding."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    IpDeadlineCoverage,
    IpDocketRecord,
    Matter,
    MatterDeadline,
    MatterDeadlineStatus,
)
from caseops_api.services.session_context import SessionContext

# Lifecycle-neutralized rows remain history, never live work after reopening.
_TERMINAL_COVERAGE_STATUSES = ("inactive_lifecycle", "completed")
_TERMINAL_DOCKET_STATUSES = ("archived", "abandoned", "transferred", "retired", "closed")


def operational_coverages_for_member(
    session: Session,
    *,
    context: SessionContext,
    membership_id: str,
    include_auxiliary_roles: bool = False,
    now: datetime | None = None,
) -> list[IpDeadlineCoverage]:
    at = now or datetime.now(UTC)

    # A preview is an actionable surface too. Filter the parent and deadline
    # lifecycle in SQL so a legacy non-terminal coverage row under a disposed
    # parent cannot appear transferable.
    membership_predicate = or_(
        IpDeadlineCoverage.responsible_membership_id == membership_id,
        IpDeadlineCoverage.backup_membership_id == membership_id,
    )
    if include_auxiliary_roles:
        membership_predicate = or_(
            membership_predicate,
            and_(
                IpDeadlineCoverage.pending_replacement_membership_id == membership_id,
                IpDeadlineCoverage.replacement_decision == "pending",
            ),
            and_(
                IpDeadlineCoverage.emergency_escalation_membership_id == membership_id,
                or_(
                    and_(
                        IpDeadlineCoverage.pending_replacement_membership_id.is_not(None),
                        IpDeadlineCoverage.replacement_decision == "pending",
                        IpDeadlineCoverage.pending_replacement_membership_id
                        == IpDeadlineCoverage.responsible_membership_id,
                    ),
                    and_(
                        IpDeadlineCoverage.coverage_status == "emergency",
                        IpDeadlineCoverage.emergency_until.is_not(None),
                        IpDeadlineCoverage.emergency_until > at,
                    ),
                ),
            ),
        )
    return list(
        session.scalars(
            select(IpDeadlineCoverage)
            .join(
                IpDocketRecord,
                and_(
                    IpDocketRecord.id == IpDeadlineCoverage.docket_id,
                    IpDocketRecord.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .join(
                MatterDeadline,
                and_(
                    MatterDeadline.id == IpDeadlineCoverage.matter_deadline_id,
                    MatterDeadline.company_id == IpDeadlineCoverage.company_id,
                ),
            )
            .outerjoin(
                Matter,
                and_(
                    Matter.id == IpDocketRecord.matter_id,
                    Matter.company_id == IpDocketRecord.company_id,
                ),
            )
            .where(
                IpDeadlineCoverage.company_id == context.company.id,
                membership_predicate,
                IpDeadlineCoverage.coverage_status.notin_(_TERMINAL_COVERAGE_STATUSES),
                IpDocketRecord.is_active.is_(True),
                IpDocketRecord.archived_by_matter_disposal.is_(False),
                IpDocketRecord.status.notin_(_TERMINAL_DOCKET_STATUSES),
                MatterDeadline.status.in_((MatterDeadlineStatus.OPEN, MatterDeadlineStatus.MISSED)),
                MatterDeadline.neutralized_at.is_(None),
                MatterDeadline.cancelled_by_matter_disposal.is_(False),
                or_(
                    IpDocketRecord.matter_id.is_(None),
                    and_(
                        Matter.id.is_not(None),
                        Matter.is_active.is_(True),
                        Matter.status.notin_(("disposed", "closed")),
                    ),
                ),
                or_(
                    and_(
                        MatterDeadline.ip_docket_id == IpDocketRecord.id,
                        MatterDeadline.matter_id.is_(None),
                    ),
                    and_(
                        IpDocketRecord.matter_id.is_not(None),
                        MatterDeadline.matter_id == IpDocketRecord.matter_id,
                        MatterDeadline.ip_docket_id.is_(None),
                    ),
                ),
            )
            .order_by(IpDeadlineCoverage.id)
        ).all()
    )
