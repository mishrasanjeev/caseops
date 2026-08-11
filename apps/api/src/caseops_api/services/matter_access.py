"""Matter-level access control.

Tenant ownership is enforced by ``company_id`` at the matter lookup
edge. This module adds the finer visibility rules used by both list and
direct matter endpoints:

- ethical walls hide a matter from a specific membership;
- restricted matters require assignee status or an explicit grant;
- team-scoped tenants require firm-wide matters, team membership,
  assignee status, or an explicit grant;
- company owners bypass these gates so they cannot lock themselves out.

The denied path records an ``audit.access_denied`` event before raising
a 404, matching the tenant-isolation pattern.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    MatterAccessLevel,
    MembershipRole,
    Team,
    TeamMembership,
)
from caseops_api.schemas.ip_access import (
    RecordAccessFoundationContract,
    RecordAccessReconciliationReport,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext


def _is_owner(context: SessionContext) -> bool:
    return context.membership.role == MembershipRole.OWNER


def can_access(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
) -> bool:
    """Return True if the signed-in membership may act on this matter.

    Assumes `matter.company_id == context.company.id` has already been
    checked by the caller. Direct matter reads/writes intentionally reuse
    the same SQL visibility predicate as list endpoints so team scoping,
    restricted access, grants, and ethical walls cannot drift by route.
    """
    visible = session.scalar(
        select(Matter.id)
        .where(
            Matter.id == matter.id,
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )
        .limit(1)
    )
    return visible is not None


def assert_access(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
) -> None:
    """Enforce access and audit denials. Called from every matter
    service right after the company_id check."""
    if can_access(session, context=context, matter=matter):
        return
    # Commit the denial audit BEFORE raising. Without the commit the
    # request-scoped session tears down without flushing the row, and
    # the compliance trail silently loses the denial.
    record_from_context(
        session,
        context,
        action="access_denied",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        result="denied",
        metadata={"reason": "matter_visibility_denied"},
        commit=True,
    )
    # Pretend the matter does not exist rather than leaking that it does
    # but the user is walled — matches the tenant-isolation 404 pattern.
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Matter not found.",
    )


def _team_scoping_enabled(session: Session, company_id: str) -> bool:
    flag = session.scalar(
        select(Company.team_scoping_enabled).where(Company.id == company_id)
    )
    return bool(flag)


def _active_grant_window(now: datetime) -> Any:
    return and_(
        MatterAccessGrant.revoked_at.is_(None),
        or_(
            MatterAccessGrant.effective_from.is_(None),
            MatterAccessGrant.effective_from <= now,
        ),
        or_(
            MatterAccessGrant.expires_at.is_(None),
            MatterAccessGrant.expires_at > now,
        ),
    )


def _active_wall_window(now: datetime) -> Any:
    return and_(
        EthicalWall.revoked_at.is_(None),
        or_(EthicalWall.effective_from.is_(None), EthicalWall.effective_from <= now),
        or_(EthicalWall.expires_at.is_(None), EthicalWall.expires_at > now),
    )


def _grant_subject_filter(membership_id: str) -> Any:
    active_team_ids = (
        select(TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            TeamMembership.membership_id == membership_id,
            Team.is_active.is_(True),
        )
    )
    return or_(
        MatterAccessGrant.membership_id == membership_id,
        MatterAccessGrant.team_id.in_(active_team_ids),
    )


def _wall_subject_filter(membership_id: str) -> Any:
    active_team_ids = (
        select(TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            TeamMembership.membership_id == membership_id,
            Team.is_active.is_(True),
        )
    )
    return or_(
        EthicalWall.excluded_membership_id == membership_id,
        EthicalWall.excluded_team_id.in_(active_team_ids),
    )


def visible_matters_filter(
    session: Session,
    *,
    context: SessionContext,
) -> Any:
    """Return a SQLAlchemy `where(...)` clause that restricts a matter
    query to the matters this membership is allowed to see.

    Composes cleanly:

        stmt = select(Matter).where(
            Matter.company_id == context.company.id,
            visible_matters_filter(session, context=context),
        )

    Sprint 8c: when the tenant has ``team_scoping_enabled = True``,
    non-owners additionally need to see the matter via its team
    (matter.team_id IS NULL -> firm-wide -> still visible; otherwise
    the member must belong to that team).
    """
    membership_id = context.membership.id
    now = datetime.now(UTC)

    if _is_owner(context):
        return and_(True)

    wall = (
        select(EthicalWall.id)
        .where(
            EthicalWall.matter_id == Matter.id,
            _wall_subject_filter(membership_id),
            _active_wall_window(now),
        )
    )
    grant = (
        select(MatterAccessGrant.id)
        .where(
            MatterAccessGrant.matter_id == Matter.id,
            _grant_subject_filter(membership_id),
            _active_grant_window(now),
        )
    )
    base = and_(
        # Not walled.
        ~exists(wall),
        # Either unrestricted, OR the membership is the matter's
        # assignee, OR an explicit grant exists.
        or_(
            Matter.restricted_access.is_(False),
            Matter.assignee_membership_id == membership_id,
            exists(grant),
        ),
    )

    if not _team_scoping_enabled(session, context.company.id):
        return base

    team_membership = (
        select(TeamMembership.id).where(
            TeamMembership.team_id == Matter.team_id,
            TeamMembership.membership_id == membership_id,
        )
    )
    team_gate = or_(
        # Firm-wide matters (no team) stay visible even when scoping
        # is on — this keeps historical data accessible.
        Matter.team_id.is_(None),
        # Or the membership belongs to the matter's team.
        exists(team_membership),
        # Explicit grants bypass team scoping (the point of a grant
        # is cross-team loan-in).
        exists(grant),
        # Assignees always see their own matter.
        Matter.assignee_membership_id == membership_id,
    )
    return and_(base, team_gate)


def visible_ip_dockets_filter(
    session: Session,
    *,
    context: SessionContext,
) -> Any:
    """Return the single fail-closed internal policy for IP docket queries.

    Linked Matter access is intentionally not inherited. An IP wall always
    wins, and a restricted IP record requires an effective membership or team
    grant. Company owners follow the same rule as every other membership.
    """

    del session  # kept for parity with the Matter filter and future policy inputs
    membership_id = context.membership.id
    now = datetime.now(UTC)
    wall = select(EthicalWall.id).where(
        EthicalWall.ip_docket_id == IpDocketRecord.id,
        _wall_subject_filter(membership_id),
        _active_wall_window(now),
    )
    grant = select(MatterAccessGrant.id).where(
        MatterAccessGrant.ip_docket_id == IpDocketRecord.id,
        _grant_subject_filter(membership_id),
        _active_grant_window(now),
    )
    return and_(
        ~exists(wall),
        or_(IpDocketRecord.restricted.is_(False), exists(grant)),
    )


def can_access_ip_docket(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
) -> bool:
    visible = session.scalar(
        select(IpDocketRecord.id)
        .where(
            IpDocketRecord.id == docket.id,
            IpDocketRecord.company_id == context.company.id,
            visible_ip_dockets_filter(session, context=context),
        )
        .limit(1)
    )
    return visible is not None


def assert_ip_docket_access(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
) -> None:
    if can_access_ip_docket(session, context=context, docket=docket):
        return
    record_from_context(
        session,
        context,
        action="access_denied",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        result="denied",
        metadata={"reason": "ip_docket_visibility_denied"},
        commit=True,
    )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="IP docket record not found.",
    )


def seed_restricted_ip_creator_access(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
) -> MatterAccessGrant | None:
    """Create the initial explicit grant for a newly restricted IP record."""

    if not docket.restricted:
        return None
    grant = MatterAccessGrant(
        company_id=context.company.id,
        ip_docket_id=docket.id,
        membership_id=context.membership.id,
        access_level=MatterAccessLevel.MEMBER,
        reason="Initial restricted-record creator access.",
        granted_by_membership_id=context.membership.id,
    )
    session.add(grant)
    docket.access_policy_version += 1
    session.add(docket)
    session.flush()
    return grant


def attach_visible_ip_dockets_filter(
    session: Session,
    context: SessionContext,
    stmt: Select,
) -> Select:
    return stmt.where(visible_ip_dockets_filter(session, context=context))


def record_access_foundation_contract() -> RecordAccessFoundationContract:
    return RecordAccessFoundationContract(
        supported_targets=["matter", "ip_docket"],
        supported_subjects=["membership", "team"],
        owner_bypass={"matter": True, "ip_docket": False},
        forbidden_parallel_owners=["ip_access_grants", "ip_ethical_walls"],
        excluded_persistence=[
            "portal_grants",
            "access_review_campaigns",
            "emergency_access_sessions",
        ],
    )


def reconcile_record_access(
    session: Session,
    *,
    context: SessionContext,
) -> RecordAccessReconciliationReport:
    """Release-blocking tenant reconciliation for the generalized owner."""

    company_id = context.company.id
    company_matter_ids = select(Matter.id).where(Matter.company_id == company_id)
    legacy_tail_count = 0
    invalid_target_count = 0
    invalid_subject_count = 0
    target_company_mismatch_count = 0
    subject_company_mismatch_count = 0
    for model, membership_column, team_column in (
        (MatterAccessGrant, MatterAccessGrant.membership_id, MatterAccessGrant.team_id),
        (
            EthicalWall,
            EthicalWall.excluded_membership_id,
            EthicalWall.excluded_team_id,
        ),
    ):
        scope = or_(
            model.company_id == company_id,
            and_(model.company_id.is_(None), model.matter_id.in_(company_matter_ids)),
        )
        legacy_tail_count += int(
            session.scalar(
                select(func.count(model.id)).where(scope, model.company_id.is_(None))
            )
            or 0
        )
        invalid_target_count += int(
            session.scalar(
                select(func.count(model.id)).where(
                    scope,
                    or_(
                        and_(model.matter_id.is_(None), model.ip_docket_id.is_(None)),
                        and_(model.matter_id.is_not(None), model.ip_docket_id.is_not(None)),
                    ),
                )
            )
            or 0
        )
        invalid_subject_count += int(
            session.scalar(
                select(func.count(model.id)).where(
                    scope,
                    or_(
                        and_(membership_column.is_(None), team_column.is_(None)),
                        and_(
                            membership_column.is_not(None),
                            team_column.is_not(None),
                        ),
                    ),
                )
            )
            or 0
        )
        target_company_mismatch_count += int(
            session.scalar(
                select(func.count(model.id))
                .outerjoin(Matter, Matter.id == model.matter_id)
                .outerjoin(IpDocketRecord, IpDocketRecord.id == model.ip_docket_id)
                .where(
                    scope,
                    or_(
                        and_(
                            model.matter_id.is_not(None),
                            or_(
                                Matter.id.is_(None),
                                Matter.company_id != model.company_id,
                            ),
                        ),
                        and_(
                            model.ip_docket_id.is_not(None),
                            or_(
                                IpDocketRecord.id.is_(None),
                                IpDocketRecord.company_id != model.company_id,
                            ),
                        ),
                    ),
                )
            )
            or 0
        )
        subject_company_mismatch_count += int(
            session.scalar(
                select(func.count(model.id))
                .outerjoin(
                    CompanyMembership,
                    CompanyMembership.id == membership_column,
                )
                .outerjoin(Team, Team.id == team_column)
                .where(
                    scope,
                    or_(
                        and_(
                            membership_column.is_not(None),
                            or_(
                                CompanyMembership.id.is_(None),
                                CompanyMembership.company_id != model.company_id,
                            ),
                        ),
                        and_(
                            team_column.is_not(None),
                            or_(
                                Team.id.is_(None),
                                Team.company_id != model.company_id,
                            ),
                        ),
                    ),
                )
            )
            or 0
        )
    uncorrelated_ip_audit_count = int(
        session.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.company_id == company_id,
                AuditEvent.target_type == "ip_docket_record",
                AuditEvent.ip_docket_id.is_(None),
            )
        )
        or 0
    )
    counts = (
        legacy_tail_count,
        invalid_target_count,
        invalid_subject_count,
        target_company_mismatch_count,
        subject_company_mismatch_count,
        uncorrelated_ip_audit_count,
    )
    return RecordAccessReconciliationReport(
        generated_at=datetime.now(UTC),
        company_id=company_id,
        legacy_tail_count=legacy_tail_count,
        invalid_target_count=invalid_target_count,
        invalid_subject_count=invalid_subject_count,
        target_company_mismatch_count=target_company_mismatch_count,
        subject_company_mismatch_count=subject_company_mismatch_count,
        uncorrelated_ip_audit_count=uncorrelated_ip_audit_count,
        healthy=not any(counts),
    )


def attach_visible_matters_filter(
    session: Session, context: SessionContext, stmt: Select
) -> Select:
    """Convenience wrapper so call sites don't import `where` logic."""
    return stmt.where(visible_matters_filter(session, context=context))


# ---------------------------------------------------------------------------
# CRUD helpers for grants / walls / restricted flag.
#
# All three require the caller to be owner/admin; that gate lives in the
# route. These functions assume the caller is authorised.
# ---------------------------------------------------------------------------


def _require_admin(context: SessionContext) -> None:
    role = context.membership.role
    if role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Managing matter access requires admin or owner role.",
        )


def _load_matter_or_404(
    session: Session, company_id: str, matter_id: str
) -> Matter:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id, Matter.company_id == company_id
        )
    )
    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found."
        )
    return matter


def _membership_in_company(
    session: Session, *, company_id: str, membership_id: str
) -> bool:
    from caseops_api.db.models import CompanyMembership

    row = session.scalar(
        select(CompanyMembership).where(
            CompanyMembership.id == membership_id,
            CompanyMembership.company_id == company_id,
        )
    )
    return row is not None


def list_access_panel(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
) -> tuple[Matter, list[MatterAccessGrant], list[EthicalWall]]:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    grants = list(
        session.scalars(
            select(MatterAccessGrant)
            .where(MatterAccessGrant.matter_id == matter.id)
            .order_by(MatterAccessGrant.created_at.asc())
        )
    )
    walls = list(
        session.scalars(
            select(EthicalWall)
            .where(EthicalWall.matter_id == matter.id)
            .order_by(EthicalWall.created_at.asc())
        )
    )
    return matter, grants, walls


def set_restricted_access(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    restricted: bool,
) -> Matter:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    if matter.restricted_access == restricted:
        return matter
    matter.restricted_access = restricted
    session.add(matter)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.restricted_access_changed",
        target_type="matter",
        target_id=matter.id,
        matter_id=matter.id,
        metadata={"restricted": restricted},
    )
    session.commit()
    session.refresh(matter)
    return matter


def add_access_grant(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    membership_id: str,
    access_level: str = "member",
    reason: str | None = None,
) -> MatterAccessGrant:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    if not _membership_in_company(
        session, company_id=context.company.id, membership_id=membership_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Membership does not belong to this company.",
        )
    existing = session.scalar(
        select(MatterAccessGrant).where(
            MatterAccessGrant.matter_id == matter.id,
            MatterAccessGrant.membership_id == membership_id,
        )
    )
    if existing is not None:
        return existing
    grant = MatterAccessGrant(
        company_id=context.company.id,
        matter_id=matter.id,
        membership_id=membership_id,
        access_level=access_level,
        reason=reason,
        granted_by_membership_id=context.membership.id,
    )
    session.add(grant)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.access_grant_added",
        target_type="matter_access_grant",
        target_id=grant.id,
        matter_id=matter.id,
        metadata={
            "membership_id": membership_id,
            "access_level": access_level,
            "has_reason": bool(reason),
        },
    )
    session.commit()
    session.refresh(grant)
    return grant


def remove_access_grant(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    grant_id: str,
) -> None:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    grant = session.scalar(
        select(MatterAccessGrant).where(
            MatterAccessGrant.id == grant_id,
            MatterAccessGrant.matter_id == matter.id,
        )
    )
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Grant not found."
        )
    session.delete(grant)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.access_grant_removed",
        target_type="matter_access_grant",
        target_id=grant_id,
        matter_id=matter.id,
        metadata={"membership_id": grant.membership_id},
    )
    session.commit()


def add_ethical_wall(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    excluded_membership_id: str,
    reason: str | None = None,
) -> EthicalWall:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    if not _membership_in_company(
        session, company_id=context.company.id, membership_id=excluded_membership_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Excluded membership does not belong to this company.",
        )
    existing = session.scalar(
        select(EthicalWall).where(
            EthicalWall.matter_id == matter.id,
            EthicalWall.excluded_membership_id == excluded_membership_id,
        )
    )
    if existing is not None:
        return existing
    wall = EthicalWall(
        company_id=context.company.id,
        matter_id=matter.id,
        excluded_membership_id=excluded_membership_id,
        reason=reason,
        created_by_membership_id=context.membership.id,
    )
    session.add(wall)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.ethical_wall_added",
        target_type="ethical_wall",
        target_id=wall.id,
        matter_id=matter.id,
        metadata={
            "excluded_membership_id": excluded_membership_id,
            "has_reason": bool(reason),
        },
    )
    session.commit()
    session.refresh(wall)
    return wall


def remove_ethical_wall(
    session: Session,
    *,
    context: SessionContext,
    matter_id: str,
    wall_id: str,
) -> None:
    _require_admin(context)
    matter = _load_matter_or_404(session, context.company.id, matter_id)
    wall = session.scalar(
        select(EthicalWall).where(
            EthicalWall.id == wall_id,
            EthicalWall.matter_id == matter.id,
        )
    )
    if wall is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Wall not found."
        )
    excluded = wall.excluded_membership_id
    session.delete(wall)
    session.flush()
    record_from_context(
        session,
        context,
        action="matter.ethical_wall_removed",
        target_type="ethical_wall",
        target_id=wall_id,
        matter_id=matter.id,
        metadata={"excluded_membership_id": excluded},
    )
    session.commit()


__all__ = [
    "add_access_grant",
    "add_ethical_wall",
    "assert_access",
    "assert_ip_docket_access",
    "attach_visible_ip_dockets_filter",
    "attach_visible_matters_filter",
    "can_access",
    "can_access_ip_docket",
    "list_access_panel",
    "remove_access_grant",
    "remove_ethical_wall",
    "reconcile_record_access",
    "record_access_foundation_contract",
    "seed_restricted_ip_creator_access",
    "set_restricted_access",
    "visible_matters_filter",
    "visible_ip_dockets_filter",
]
