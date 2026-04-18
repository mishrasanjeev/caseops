"""Matter-level access control (PRD §13.4, §5.6).

The tenant boundary is already enforced by `company_id` on every
matter query — this module adds the two finer layers on top:

- **Grants** (`MatterAccessGrant`) open a restricted matter to a
  specific membership.
- **Walls** (`EthicalWall`) block a specific membership regardless of
  grants, so a firm can conflict-wall an associate off a sensitive
  matter without revoking their broader access.

Decision rule for a given (membership, matter):

    owner of the company  →   ALLOW  (bypasses walls; owners cannot be
                                       locked out of their own firm)
    assignee of the matter →  ALLOW  (ditto — the responsible lawyer
                                       cannot be walled from the matter
                                       they're accountable for)
    wall matches           →  DENY   (audited)
    matter not restricted  →  ALLOW  (current default behaviour)
    grant exists           →  ALLOW
    otherwise              →  DENY   (audited)

The `denied` path records an `audit.access_denied` row every time so
the compliance view shows who tried.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from caseops_api.db.models import (
    Company,
    EthicalWall,
    Matter,
    MatterAccessGrant,
    MembershipRole,
    TeamMembership,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext


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
    checked by the caller (every matter lookup does this via
    `_get_matter_model`). This helper only layers on the grant/wall
    rules.
    """
    membership_id = context.membership.id

    # Owners always win so they can't lose access to their own firm.
    if _is_owner(context):
        return True
    # The matter's assignee is never walled from their own matter.
    if matter.assignee_membership_id == membership_id:
        return True

    # Walls are checked before grants.
    wall_exists = session.scalar(
        select(exists().where(
            EthicalWall.matter_id == matter.id,
            EthicalWall.excluded_membership_id == membership_id,
        ))
    )
    if wall_exists:
        return False

    if not matter.restricted_access:
        return True

    grant_exists = session.scalar(
        select(exists().where(
            MatterAccessGrant.matter_id == matter.id,
            MatterAccessGrant.membership_id == membership_id,
        ))
    )
    return bool(grant_exists)


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
        metadata={"reason": "ethical_wall_or_missing_grant"},
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

    if _is_owner(context):
        return and_(True)

    wall = (
        select(EthicalWall.id)
        .where(
            EthicalWall.matter_id == Matter.id,
            EthicalWall.excluded_membership_id == membership_id,
        )
    )
    grant = (
        select(MatterAccessGrant.id)
        .where(
            MatterAccessGrant.matter_id == Matter.id,
            MatterAccessGrant.membership_id == membership_id,
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
    "attach_visible_matters_filter",
    "can_access",
    "list_access_panel",
    "remove_access_grant",
    "remove_ethical_wall",
    "set_restricted_access",
    "visible_matters_filter",
]
