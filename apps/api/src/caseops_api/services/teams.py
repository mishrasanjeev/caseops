"""Teams / departments service (Sprint 8c BG-026)."""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Team,
    TeamKind,
    TeamMembership,
    User,
)
from caseops_api.schemas.teams import (
    TeamCreateRequest,
    TeamListResponse,
    TeamMembershipRecord,
    TeamRecord,
    TeamUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext

logger = logging.getLogger(__name__)


def _load_team(
    session: Session, *, context: SessionContext, team_id: str
) -> Team:
    team = session.scalar(
        select(Team)
        .where(Team.id == team_id)
        .where(Team.company_id == context.company.id)
    )
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
        )
    return team


def _membership_records(
    session: Session, team_id: str
) -> list[TeamMembershipRecord]:
    rows = session.execute(
        select(
            TeamMembership.id,
            TeamMembership.team_id,
            TeamMembership.membership_id,
            TeamMembership.is_lead,
            TeamMembership.created_at,
            User.full_name,
            User.email,
        )
        .join(
            CompanyMembership,
            CompanyMembership.id == TeamMembership.membership_id,
        )
        .join(User, User.id == CompanyMembership.user_id)
        .where(TeamMembership.team_id == team_id)
        .order_by(
            TeamMembership.is_lead.desc(),
            User.full_name.asc(),
        )
    ).all()
    return [
        TeamMembershipRecord(
            id=row.id,
            team_id=row.team_id,
            membership_id=row.membership_id,
            member_name=row.full_name,
            member_email=row.email,
            is_lead=row.is_lead,
            created_at=row.created_at,
        )
        for row in rows
    ]


def _team_record(session: Session, team: Team) -> TeamRecord:
    members = _membership_records(session, team.id)
    return TeamRecord(
        id=team.id,
        company_id=team.company_id,
        name=team.name,
        slug=team.slug,
        description=team.description,
        kind=team.kind,  # type: ignore[arg-type]
        is_active=team.is_active,
        member_count=len(members),
        members=members,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


def list_teams(
    session: Session, *, context: SessionContext
) -> TeamListResponse:
    rows = list(
        session.scalars(
            select(Team)
            .where(Team.company_id == context.company.id)
            .order_by(Team.is_active.desc(), Team.name.asc())
        )
    )
    scoping = session.scalar(
        select(Company.team_scoping_enabled).where(
            Company.id == context.company.id
        )
    )
    return TeamListResponse(
        teams=[_team_record(session, t) for t in rows],
        team_scoping_enabled=bool(scoping),
    )


def create_team(
    session: Session,
    *,
    context: SessionContext,
    payload: TeamCreateRequest,
) -> TeamRecord:
    existing = session.scalar(
        select(Team.id)
        .where(Team.company_id == context.company.id)
        .where(Team.slug == payload.slug)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A team with slug {payload.slug!r} already exists.",
        )
    team = Team(
        company_id=context.company.id,
        name=payload.name.strip(),
        slug=payload.slug,
        description=(payload.description or "").strip() or None,
        kind=TeamKind(payload.kind),
    )
    session.add(team)
    session.flush()
    record_from_context(
        session,
        context,
        action="team.created",
        target_type="team",
        target_id=team.id,
        metadata={"name": team.name, "slug": team.slug, "kind": team.kind},
    )
    session.flush()
    return _team_record(session, team)


def update_team(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
    payload: TeamUpdateRequest,
) -> TeamRecord:
    team = _load_team(session, context=context, team_id=team_id)
    changes: dict[str, object] = {}
    if payload.name is not None:
        team.name = payload.name.strip()
        changes["name"] = team.name
    if payload.description is not None:
        team.description = payload.description.strip() or None
        changes["description_updated"] = True
    if payload.kind is not None:
        team.kind = TeamKind(payload.kind)
        changes["kind"] = team.kind
    if payload.is_active is not None:
        team.is_active = payload.is_active
        changes["is_active"] = team.is_active
    if changes:
        session.flush()
        record_from_context(
            session,
            context,
            action="team.updated",
            target_type="team",
            target_id=team.id,
            metadata=changes,
        )
        session.flush()
    return _team_record(session, team)


def delete_team(
    session: Session, *, context: SessionContext, team_id: str
) -> None:
    team = _load_team(session, context=context, team_id=team_id)
    session.delete(team)
    session.flush()
    record_from_context(
        session,
        context,
        action="team.deleted",
        target_type="team",
        target_id=team_id,
    )
    session.flush()


def add_team_member(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
    membership_id: str,
    is_lead: bool = False,
) -> TeamRecord:
    team = _load_team(session, context=context, team_id=team_id)

    # Validate the target membership belongs to the company.
    belongs = session.scalar(
        select(CompanyMembership.id)
        .where(CompanyMembership.id == membership_id)
        .where(CompanyMembership.company_id == context.company.id)
    )
    if belongs is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Membership does not belong to this company.",
        )

    exists_row = session.scalar(
        select(TeamMembership.id)
        .where(TeamMembership.team_id == team.id)
        .where(TeamMembership.membership_id == membership_id)
    )
    if exists_row:
        # Allow is_lead toggling on re-add without raising.
        row = session.get(TeamMembership, exists_row)
        if row is not None and row.is_lead != is_lead:
            row.is_lead = is_lead
            session.flush()
        return _team_record(session, team)

    row = TeamMembership(
        team_id=team.id,
        membership_id=membership_id,
        is_lead=is_lead,
    )
    session.add(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="team_membership.added",
        target_type="team_membership",
        target_id=row.id,
        metadata={"team_id": team.id, "membership_id": membership_id, "is_lead": is_lead},
    )
    session.flush()
    return _team_record(session, team)


def remove_team_member(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
    membership_id: str,
) -> TeamRecord:
    team = _load_team(session, context=context, team_id=team_id)
    row = session.scalar(
        select(TeamMembership)
        .where(TeamMembership.team_id == team.id)
        .where(TeamMembership.membership_id == membership_id)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member is not on this team.",
        )
    session.delete(row)
    session.flush()
    record_from_context(
        session,
        context,
        action="team_membership.removed",
        target_type="team_membership",
        target_id=row.id,
        metadata={"team_id": team.id, "membership_id": membership_id},
    )
    session.flush()
    return _team_record(session, team)


def set_team_scoping(
    session: Session, *, context: SessionContext, enabled: bool
) -> bool:
    company = session.get(Company, context.company.id)
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )
    if company.team_scoping_enabled == enabled:
        return enabled
    company.team_scoping_enabled = enabled
    session.flush()
    record_from_context(
        session,
        context,
        action="team_scoping.toggled",
        target_type="company",
        target_id=company.id,
        metadata={"enabled": enabled},
    )
    session.flush()
    return enabled


__all__ = [
    "add_team_member",
    "create_team",
    "delete_team",
    "list_teams",
    "remove_team_member",
    "set_team_scoping",
    "update_team",
]
