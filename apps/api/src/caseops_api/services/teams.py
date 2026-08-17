"""Teams / departments service (Sprint 8c BG-026)."""
from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    IpDocketRecord,
    Matter,
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
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.matter_access import (
    _operational_ip_docket_role_membership_ids,
    can_stably_access_ip_docket,
)
from caseops_api.services.session_context import SessionContext

_TERMINAL_IP_DOCKET_STATUSES = frozenset(
    {"archived", "abandoned", "transferred", "retired", "closed"}
)


class _IpRoleFenceEntry(NamedTuple):
    matter_id: str | None
    role_membership_ids: tuple[str, ...]


class _TeamMembershipSnapshot(NamedTuple):
    row_id: str
    membership_id: str


class _TeamMutationSnapshot(NamedTuple):
    name: str
    description: str | None
    kind: str
    is_active: bool
    updated_at: datetime


def _team_mutation_snapshot(team: Team) -> _TeamMutationSnapshot:
    return _TeamMutationSnapshot(
        name=team.name,
        description=team.description,
        kind=str(team.kind),
        is_active=bool(team.is_active),
        updated_at=team.updated_at,
    )


def _assert_active_locked_actor(
    session: Session,
    memberships: dict[str, CompanyMembership],
    *,
    context: SessionContext,
) -> CompanyMembership:
    actor = memberships.get(context.membership.id)
    if (
        actor is None
        or not actor.is_active
        or actor.user is None
        or not actor.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An active company membership is required for team changes.",
        )
    require_locked_membership_capability(session, actor, "teams:manage")
    # Downstream access checks and audit creation must use the authoritative
    # instances that were refreshed while the Membership/User locks are held.
    context.membership = actor
    context.user = actor.user
    return actor


def _load_team(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
    for_update: bool = False,
) -> Team:
    statement = (
        select(Team)
        .where(Team.id == team_id)
        .where(Team.company_id == context.company.id)
    )
    if for_update:
        statement = statement.with_for_update(of=Team).execution_options(
            populate_existing=True
        )
    team = session.scalar(statement)
    if team is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Team not found."
        )
    return team


def _team_membership_snapshot(
    session: Session,
    *,
    team_id: str,
    for_update: bool = False,
) -> tuple[_TeamMembershipSnapshot, ...]:
    statement = (
        select(TeamMembership.id, TeamMembership.membership_id)
        .where(TeamMembership.team_id == team_id)
        .order_by(TeamMembership.membership_id, TeamMembership.id)
    )
    if for_update:
        statement = statement.with_for_update(of=TeamMembership)
    return tuple(
        _TeamMembershipSnapshot(row_id=row.id, membership_id=row.membership_id)
        for row in session.execute(statement)
    )


def _operational_ip_role_fence_snapshot(
    session: Session,
    *,
    company_id: str,
    membership_scope: set[str] | None,
    include_empty: bool = False,
    linked_only: bool = False,
) -> dict[str, _IpRoleFenceEntry]:
    statement = select(IpDocketRecord).where(
        IpDocketRecord.company_id == company_id,
        IpDocketRecord.is_active.is_(True),
        IpDocketRecord.archived_by_matter_disposal.is_(False),
        IpDocketRecord.status.notin_(_TERMINAL_IP_DOCKET_STATUSES),
    )
    if linked_only:
        statement = statement.where(IpDocketRecord.matter_id.is_not(None))
    dockets = list(session.scalars(statement.order_by(IpDocketRecord.id)))
    snapshot: dict[str, _IpRoleFenceEntry] = {}
    for docket in dockets:
        role_ids = _operational_ip_docket_role_membership_ids(
            session,
            docket=docket,
        )
        if membership_scope is not None:
            role_ids &= membership_scope
        if not role_ids and not include_empty:
            continue
        snapshot[docket.id] = _IpRoleFenceEntry(
            matter_id=docket.matter_id,
            role_membership_ids=tuple(sorted(role_ids)),
        )
    return snapshot


def _lock_ip_role_fence_parents(
    session: Session,
    *,
    company_id: str,
    expected: dict[str, _IpRoleFenceEntry],
    membership_scope: set[str] | None,
    include_empty: bool = False,
    linked_only: bool = False,
) -> tuple[list[Matter], list[IpDocketRecord]]:
    matter_ids = sorted(
        {
            entry.matter_id
            for entry in expected.values()
            if entry.matter_id is not None
        }
    )
    matters = (
        list(
            session.scalars(
                select(Matter)
                .where(Matter.company_id == company_id, Matter.id.in_(matter_ids))
                .order_by(Matter.id)
                .with_for_update(of=Matter)
                .execution_options(populate_existing=True)
            )
        )
        if matter_ids
        else []
    )
    if {matter.id for matter in matters} != set(matter_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A linked Matter changed while team access was being updated.",
        )

    docket_ids = sorted(expected)
    dockets = (
        list(
            session.scalars(
                select(IpDocketRecord)
                .where(
                    IpDocketRecord.company_id == company_id,
                    IpDocketRecord.id.in_(docket_ids),
                )
                .order_by(IpDocketRecord.id)
                .with_for_update(of=IpDocketRecord)
                .execution_options(populate_existing=True)
            )
        )
        if docket_ids
        else []
    )
    if {docket.id for docket in dockets} != set(docket_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An IP record changed while team access was being updated.",
        )
    current = _operational_ip_role_fence_snapshot(
        session,
        company_id=company_id,
        membership_scope=membership_scope,
        include_empty=include_empty,
        linked_only=linked_only,
    )
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_team_access_responsibility_changed",
                "message": "Operational IP responsibility changed; retry the team update.",
            },
        )
    return matters, dockets


def _assert_ip_role_access_survives_team_change(
    session: Session,
    *,
    context: SessionContext,
    expected: dict[str, _IpRoleFenceEntry],
    dockets: list[IpDocketRecord],
    memberships: dict[str, CompanyMembership],
) -> None:
    by_id = {docket.id: docket for docket in dockets}
    blocked: dict[str, list[str]] = {}
    for docket_id, entry in sorted(expected.items()):
        docket = by_id[docket_id]
        for membership_id in entry.role_membership_ids:
            membership = memberships.get(membership_id)
            if (
                membership is None
                or not membership.is_active
                or membership.user is None
                or not membership.user.is_active
            ):
                blocked.setdefault(membership_id, []).append(docket_id)
                continue
            member_context = SessionContext(
                company=context.company,
                membership=membership,
                user=membership.user,
            )
            if not can_stably_access_ip_docket(
                session,
                context=member_context,
                docket=docket,
            ):
                blocked.setdefault(membership_id, []).append(docket_id)
    if blocked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ip_team_access_responsibility_handoff_required",
                "message": (
                    "Reassign every live linked-IP responsibility before this "
                    "team access change."
                ),
                "blocked_membership_ids": sorted(blocked),
                "blocked_ip_docket_ids": sorted(
                    {docket_id for docket_ids in blocked.values() for docket_id in docket_ids}
                ),
            },
        )


def _assert_fence_unchanged_before_parent_locks(
    session: Session,
    *,
    company_id: str,
    expected: dict[str, _IpRoleFenceEntry],
    membership_scope: set[str] | None,
    include_empty: bool = False,
    linked_only: bool = False,
) -> None:
    if _operational_ip_role_fence_snapshot(
        session,
        company_id=company_id,
        membership_scope=membership_scope,
        include_empty=include_empty,
        linked_only=linked_only,
    ) == expected:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "ip_team_access_responsibility_changed",
            "message": "Operational IP responsibility changed; retry the team update.",
        },
    )


def _lock_whole_team_access_fence(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
) -> tuple[
    Team,
    dict[str, CompanyMembership],
    dict[str, _IpRoleFenceEntry],
    list[Matter],
    list[IpDocketRecord],
]:
    advisory_team = _load_team(session, context=context, team_id=team_id)
    team_snapshot = _team_mutation_snapshot(advisory_team)
    team_memberships = _team_membership_snapshot(session, team_id=team_id)
    membership_scope = {row.membership_id for row in team_memberships}
    expected = _operational_ip_role_fence_snapshot(
        session,
        company_id=context.company.id,
        membership_scope=membership_scope,
    )
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={*membership_scope, context.membership.id},
    )
    _assert_active_locked_actor(session, memberships, context=context)
    team = _load_team(
        session,
        context=context,
        team_id=team_id,
        for_update=True,
    )
    if _team_mutation_snapshot(team) != team_snapshot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team changed; retry the team update.",
        )
    if _team_membership_snapshot(
        session,
        team_id=team.id,
        for_update=True,
    ) != team_memberships:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team membership changed; retry the team update.",
        )
    _assert_fence_unchanged_before_parent_locks(
        session,
        company_id=context.company.id,
        expected=expected,
        membership_scope=membership_scope,
    )
    matters, dockets = _lock_ip_role_fence_parents(
        session,
        company_id=context.company.id,
        expected=expected,
        membership_scope=membership_scope,
    )
    return team, memberships, expected, matters, dockets


def _lock_single_team_member_access_fence(
    session: Session,
    *,
    context: SessionContext,
    team_id: str,
    membership_id: str,
) -> tuple[
    Team,
    TeamMembership,
    dict[str, CompanyMembership],
    dict[str, _IpRoleFenceEntry],
    list[Matter],
    list[IpDocketRecord],
]:
    advisory_team = _load_team(session, context=context, team_id=team_id)
    team_snapshot = _team_mutation_snapshot(advisory_team)
    advisory_row = session.execute(
        select(TeamMembership.id, TeamMembership.membership_id).where(
            TeamMembership.team_id == advisory_team.id,
            TeamMembership.membership_id == membership_id,
        )
    ).one_or_none()
    if advisory_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member is not on this team.",
        )
    membership_scope = {membership_id}
    expected = _operational_ip_role_fence_snapshot(
        session,
        company_id=context.company.id,
        membership_scope=membership_scope,
    )
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={membership_id, context.membership.id},
    )
    _assert_active_locked_actor(session, memberships, context=context)
    team = _load_team(
        session,
        context=context,
        team_id=team_id,
        for_update=True,
    )
    if _team_mutation_snapshot(team) != team_snapshot:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team changed; retry the team update.",
        )
    row = session.scalar(
        select(TeamMembership)
        .where(
            TeamMembership.id == advisory_row.id,
            TeamMembership.team_id == team.id,
            TeamMembership.membership_id == membership_id,
        )
        .with_for_update(of=TeamMembership)
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team membership changed; retry the team update.",
        )
    _assert_fence_unchanged_before_parent_locks(
        session,
        company_id=context.company.id,
        expected=expected,
        membership_scope=membership_scope,
    )
    matters, dockets = _lock_ip_role_fence_parents(
        session,
        company_id=context.company.id,
        expected=expected,
        membership_scope=membership_scope,
    )
    return team, row, memberships, expected, matters, dockets


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
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id},
    )
    _assert_active_locked_actor(session, memberships, context=context)
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
    advisory_team = _load_team(session, context=context, team_id=team_id)
    team_snapshot = _team_mutation_snapshot(advisory_team)
    deactivating = payload.is_active is False and advisory_team.is_active
    if deactivating:
        team, memberships, role_fence, _matters, dockets = (
            _lock_whole_team_access_fence(
                session,
                context=context,
                team_id=team_id,
            )
        )
    else:
        memberships = lock_company_memberships_for_assignment(
            session,
            company_id=context.company.id,
            membership_ids={context.membership.id},
        )
        _assert_active_locked_actor(session, memberships, context=context)
        team = _load_team(
            session,
            context=context,
            team_id=team_id,
            for_update=True,
        )
        if _team_mutation_snapshot(team) != team_snapshot:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Team changed; retry the team update.",
            )
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
        if deactivating:
            _assert_ip_role_access_survives_team_change(
                session,
                context=context,
                expected=role_fence,
                dockets=dockets,
                memberships=memberships,
            )
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
    team, memberships, role_fence, matters, dockets = _lock_whole_team_access_fence(
        session,
        context=context,
        team_id=team_id,
    )
    session.delete(team)
    session.flush()
    for matter in matters:
        session.expire(matter, ["team_id"])
    _assert_ip_role_access_survives_team_change(
        session,
        context=context,
        expected=role_fence,
        dockets=dockets,
        memberships=memberships,
    )
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
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={context.membership.id, membership_id},
    )
    _assert_active_locked_actor(session, memberships, context=context)
    membership = memberships.get(membership_id)
    if (
        membership is None
        or not membership.is_active
        or membership.user is None
        or not membership.user.is_active
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Membership does not belong to this company or is inactive.",
        )
    team = _load_team(
        session,
        context=context,
        team_id=team_id,
        for_update=True,
    )

    row = session.scalar(
        select(TeamMembership)
        .where(TeamMembership.team_id == team.id)
        .where(TeamMembership.membership_id == membership_id)
        .with_for_update(of=TeamMembership)
        .execution_options(populate_existing=True)
    )
    if row is not None:
        # Allow is_lead toggling on re-add without raising.
        if row.is_lead != is_lead:
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
    team, row, memberships, role_fence, _matters, dockets = (
        _lock_single_team_member_access_fence(
            session,
            context=context,
            team_id=team_id,
            membership_id=membership_id,
        )
    )
    session.delete(row)
    session.flush()
    _assert_ip_role_access_survives_team_change(
        session,
        context=context,
        expected=role_fence,
        dockets=dockets,
        memberships=memberships,
    )
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
    discovered_enabled = session.scalar(
        select(Company.team_scoping_enabled).where(Company.id == context.company.id)
    )
    if discovered_enabled is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )
    if bool(discovered_enabled) == enabled:
        memberships = lock_company_memberships_for_assignment(
            session,
            company_id=context.company.id,
            membership_ids={context.membership.id},
        )
        _assert_active_locked_actor(session, memberships, context=context)
        return enabled
    role_fence: dict[str, _IpRoleFenceEntry] = {}
    memberships: dict[str, CompanyMembership] = {}
    dockets: list[IpDocketRecord] = []
    if enabled:
        role_fence = _operational_ip_role_fence_snapshot(
            session,
            company_id=context.company.id,
            membership_scope=None,
            include_empty=True,
            linked_only=True,
        )
        role_membership_ids = {
            membership_id
            for entry in role_fence.values()
            for membership_id in entry.role_membership_ids
        }
    memberships = lock_company_memberships_for_assignment(
        session,
        company_id=context.company.id,
        membership_ids={*role_membership_ids, context.membership.id}
        if enabled
        else {context.membership.id},
    )
    _assert_active_locked_actor(session, memberships, context=context)
    company = session.scalar(
        select(Company)
        .where(Company.id == context.company.id)
        .with_for_update(of=Company)
        .execution_options(populate_existing=True)
    )
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )
    if bool(company.team_scoping_enabled) != bool(discovered_enabled):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Team scoping changed; retry the update.",
        )
    if enabled:
        _assert_fence_unchanged_before_parent_locks(
            session,
            company_id=context.company.id,
            expected=role_fence,
            membership_scope=None,
            include_empty=True,
            linked_only=True,
        )
        _matters, dockets = _lock_ip_role_fence_parents(
            session,
            company_id=context.company.id,
            expected=role_fence,
            membership_scope=None,
            include_empty=True,
            linked_only=True,
        )
    company.team_scoping_enabled = enabled
    session.flush()
    if enabled:
        _assert_ip_role_access_survives_team_change(
            session,
            context=context,
            expected=role_fence,
            dockets=dockets,
            memberships=memberships,
        )
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
