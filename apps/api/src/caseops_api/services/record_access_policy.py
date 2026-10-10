"""Read-only Matter and IP visibility predicates, shared by writers and retrieval."""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import islice
from typing import Any

from sqlalchemy import and_, exists, or_, select, tuple_
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    Matter,
    MatterAccessGrant,
    MembershipRole,
    Team,
    TeamMembership,
)
from caseops_api.services.session_context import SessionContext


def _is_owner(context: SessionContext) -> bool:
    return context.membership.role == MembershipRole.OWNER



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



def _grant_subject_filter(membership_id: Any) -> Any:
    active_team_ids = (
        select(TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            TeamMembership.membership_id == membership_id,
            Team.is_active.is_(True),
        )
        .correlate_except(TeamMembership, Team)
    )
    return or_(
        MatterAccessGrant.membership_id == membership_id,
        MatterAccessGrant.team_id.in_(active_team_ids),
    )



def _wall_subject_filter(membership_id: Any) -> Any:
    active_team_ids = (
        select(TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            TeamMembership.membership_id == membership_id,
            Team.is_active.is_(True),
        )
        .correlate_except(TeamMembership, Team)
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
    if _is_owner(context):
        return and_(True)

    return _matter_visibility_predicate(
        membership_id=context.membership.id,
        owner=False,
        team_scoping=_team_scoping_clause(context.company.id),
        now=datetime.now(UTC),
    )


def _team_scoping_clause(company_id: Any) -> Any:
    return exists(
        select(Company.id).where(
            Company.id == company_id,
            Company.team_scoping_enabled.is_(True),
        ).correlate_except(Company)
    )


def _matter_visibility_predicate(
    *, membership_id: Any, owner: Any, team_scoping: Any, now: datetime,
) -> Any:
    # Scalar callers and bounded recipient batches compose the same live policy.
    wall = (
        select(EthicalWall.id)
        .where(
            EthicalWall.matter_id == Matter.id,
            _wall_subject_filter(membership_id),
            _active_wall_window(now),
        )
        .correlate_except(EthicalWall)
    )
    grant = (
        select(MatterAccessGrant.id)
        .where(
            MatterAccessGrant.matter_id == Matter.id,
            _grant_subject_filter(membership_id),
            _active_grant_window(now),
        )
        .correlate_except(MatterAccessGrant)
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

    team_membership = (
        select(TeamMembership.id).where(
            TeamMembership.team_id == Matter.team_id,
            TeamMembership.membership_id == membership_id,
        )
        .correlate_except(TeamMembership)
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
    non_owner = and_(base, or_(~team_scoping, team_gate))
    return non_owner if owner is False else or_(owner, non_owner)


def visible_matter_membership_ids(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    membership_ids: Iterable[str],
) -> set[str]:
    """Read current visibility for at most 500 already-admitted recipients.

    This does not replace current employee, capability or lifecycle admission.
    No mutable policy or decision is cached between calls or transactions.
    """
    ids = list(islice(membership_ids, 501))
    if len(ids) > 500:
        raise ValueError("Matter visibility batches are limited to 500 participants.")
    if not ids:
        return set()
    predicate = _matter_visibility_predicate(
        membership_id=CompanyMembership.id,
        owner=CompanyMembership.role == MembershipRole.OWNER,
        team_scoping=_team_scoping_clause(company_id),
        now=datetime.now(UTC),
    )
    return set(session.scalars(
        select(CompanyMembership.id)
        .join(Matter, Matter.company_id == CompanyMembership.company_id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.id.in_(sorted(set(ids))),
            Matter.id == matter_id,
            predicate,
        )
    ))



def _active_ip_subject_match(
    record: type[MatterAccessGrant] | type[EthicalWall],
    subject_column: Any,
    subject_id: Any,
    now: datetime,
    *correlated: Any,
) -> Any:
    # Seek one unique unrevoked pair, then reject a nonmatching successor.
    # An equality filter can choose a stale global/member index instead.
    candidate = (
        select(
            record.id,
            record.ip_docket_id.label("target_id"),
            subject_column.label("subject_id"),
            record.effective_from,
            record.expires_at,
        )
        .where(
            record.revoked_at.is_(None),
            record.ip_docket_id.is_not(None),
            subject_column.is_not(None),
            tuple_(record.ip_docket_id, subject_column)
            >= tuple_(IpDocketRecord.id, subject_id),
        )
        .order_by(record.ip_docket_id, subject_column)
        .correlate(IpDocketRecord, *correlated)
        .limit(1)
        .subquery()
    )
    return (
        select(candidate.c.id)
        .where(
            candidate.c.target_id == IpDocketRecord.id,
            candidate.c.subject_id == subject_id,
            or_(candidate.c.effective_from.is_(None), candidate.c.effective_from <= now),
            or_(candidate.c.expires_at.is_(None), candidate.c.expires_at > now),
        )
        .correlate(IpDocketRecord, *correlated)
        .scalar_subquery()
    )



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

    del session
    membership_id = context.membership.id
    now = datetime.now(UTC)
    active_teams = (
        select(TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(
            TeamMembership.membership_id == membership_id,
            Team.is_active.is_(True),
        )
        .subquery()
    )
    member_wall = _active_ip_subject_match(
        EthicalWall, EthicalWall.excluded_membership_id, membership_id, now
    )
    team_wall = _active_ip_subject_match(
        EthicalWall, EthicalWall.excluded_team_id, active_teams.c.team_id, now, active_teams
    )
    member_grant = _active_ip_subject_match(
        MatterAccessGrant, MatterAccessGrant.membership_id, membership_id, now
    )
    team_grant = _active_ip_subject_match(
        MatterAccessGrant, MatterAccessGrant.team_id, active_teams.c.team_id, now, active_teams
    )
    return and_(
        member_wall.is_(None),
        ~exists(select(active_teams.c.team_id).where(team_wall.is_not(None))),
        or_(
            IpDocketRecord.restricted.is_(False),
            member_grant.is_not(None),
            exists(select(active_teams.c.team_id).where(team_grant.is_not(None))),
        ),
    )
