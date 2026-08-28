from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    IpMatterLink,
    Matter,
    MatterAccessGrant,
    MembershipRole,
    Team,
    TeamMembership,
    User,
)
from caseops_api.schemas.ip_matter_links import (
    IpDocketMatterLinkListResponse,
    IpMatterLifecycleRecord,
    IpMatterLinkCreateRequest,
    IpMatterLinkRecord,
    IpMatterLinkRetireRequest,
    IpMatterLinkRetireResponse,
    MatterIpLinkListResponse,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.ip_operations import _lock_ip_writer_context
from caseops_api.services.matter_access import (
    assert_access,
    assert_ip_docket_access,
    visible_ip_dockets_filter,
    visible_matters_filter,
)
from caseops_api.services.matter_operational_guard import assert_operational_matter
from caseops_api.services.session_context import SessionContext


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message},
    )


def _access_mismatch_warnings(
    session: Session,
    *,
    context: SessionContext,
    pairs: list[tuple[IpDocketRecord, Matter]],
) -> dict[tuple[str, str], bool]:
    if not pairs:
        return {}

    membership_rows = list(
        session.execute(
            select(CompanyMembership.id, CompanyMembership.role)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
            .order_by(CompanyMembership.id)
        )
    )
    membership_ids = {str(row.id) for row in membership_rows}
    owner_ids = {
        str(row.id)
        for row in membership_rows
        if row.role == MembershipRole.OWNER
    }
    team_members: dict[str, set[str]] = defaultdict(set)
    active_team_members: dict[str, set[str]] = defaultdict(set)
    if membership_ids:
        for membership_id, team_id in session.execute(
            select(TeamMembership.membership_id, TeamMembership.team_id).where(
                TeamMembership.membership_id.in_(membership_ids)
            )
        ):
            team_members[str(team_id)].add(str(membership_id))
        for membership_id, team_id in session.execute(
            select(TeamMembership.membership_id, TeamMembership.team_id)
            .join(Team, Team.id == TeamMembership.team_id)
            .where(
                TeamMembership.membership_id.in_(membership_ids),
                Team.company_id == context.company.id,
                Team.is_active.is_(True),
            )
        ):
            active_team_members[str(team_id)].add(str(membership_id))

    docket_ids = {docket.id for docket, _matter in pairs}
    matter_ids = {matter.id for _docket, matter in pairs}
    now = datetime.now(UTC)
    grants = list(
        session.scalars(
            select(MatterAccessGrant).where(
                MatterAccessGrant.company_id == context.company.id,
                MatterAccessGrant.revoked_at.is_(None),
                or_(
                    MatterAccessGrant.effective_from.is_(None),
                    MatterAccessGrant.effective_from <= now,
                ),
                or_(
                    MatterAccessGrant.expires_at.is_(None),
                    MatterAccessGrant.expires_at > now,
                ),
                or_(
                    MatterAccessGrant.matter_id.in_(matter_ids),
                    MatterAccessGrant.ip_docket_id.in_(docket_ids),
                ),
            )
        )
    )
    walls = list(
        session.scalars(
            select(EthicalWall).where(
                EthicalWall.company_id == context.company.id,
                EthicalWall.revoked_at.is_(None),
                or_(
                    EthicalWall.effective_from.is_(None),
                    EthicalWall.effective_from <= now,
                ),
                or_(
                    EthicalWall.expires_at.is_(None),
                    EthicalWall.expires_at > now,
                ),
                or_(
                    EthicalWall.matter_id.in_(matter_ids),
                    EthicalWall.ip_docket_id.in_(docket_ids),
                ),
            )
        )
    )

    def subjects(direct_id: str | None, team_id: str | None) -> set[str]:
        if direct_id is not None:
            return {direct_id} & membership_ids
        if team_id is not None:
            return active_team_members.get(team_id, set())
        return set()

    matter_grants: dict[str, set[str]] = defaultdict(set)
    docket_grants: dict[str, set[str]] = defaultdict(set)
    for grant in grants:
        target = matter_grants if grant.matter_id is not None else docket_grants
        target_id = grant.matter_id or grant.ip_docket_id
        if target_id is not None:
            target[target_id].update(subjects(grant.membership_id, grant.team_id))

    matter_walls: dict[str, set[str]] = defaultdict(set)
    docket_walls: dict[str, set[str]] = defaultdict(set)
    for wall in walls:
        target = matter_walls if wall.matter_id is not None else docket_walls
        target_id = wall.matter_id or wall.ip_docket_id
        if target_id is not None:
            target[target_id].update(
                subjects(wall.excluded_membership_id, wall.excluded_team_id)
            )

    non_owner_ids = membership_ids - owner_ids
    warnings: dict[tuple[str, str], bool] = {}
    for docket, matter in pairs:
        matter_granted = matter_grants[matter.id]
        if matter.restricted_access:
            matter_visible = matter_granted & non_owner_ids
            if matter.assignee_membership_id in non_owner_ids:
                matter_visible.add(matter.assignee_membership_id)
        else:
            matter_visible = set(non_owner_ids)
        matter_visible.difference_update(matter_walls[matter.id])
        if context.company.team_scoping_enabled and matter.team_id is not None:
            team_gate = set(team_members.get(matter.team_id, set()))
            team_gate.update(matter_granted)
            if matter.assignee_membership_id in non_owner_ids:
                team_gate.add(matter.assignee_membership_id)
            matter_visible.intersection_update(team_gate)
        matter_visible.update(owner_ids)

        docket_visible = (
            set(membership_ids)
            if not docket.restricted
            else set(docket_grants[docket.id])
        )
        docket_visible.difference_update(docket_walls[docket.id])
        warnings[(docket.id, matter.id)] = matter_visible != docket_visible
    return warnings


def _record(
    session: Session,
    *,
    context: SessionContext,
    link: IpMatterLink,
    docket: IpDocketRecord,
    matter: Matter,
    access_mismatch_warning: bool | None = None,
) -> IpMatterLinkRecord:
    if access_mismatch_warning is None:
        access_mismatch_warning = _access_mismatch_warnings(
            session,
            context=context,
            pairs=[(docket, matter)],
        )[(docket.id, matter.id)]
    return IpMatterLinkRecord(
        id=link.id,
        company_id=link.company_id,
        docket_id=link.docket_id,
        matter_id=link.matter_id,
        relation_role=link.relation_role,
        effective_from=link.effective_from,
        retired_at=link.retired_at,
        source=link.source,
        source_reference=link.source_reference,
        reason=link.reason,
        retirement_reason=link.retirement_reason,
        created_by_membership_id=link.created_by_membership_id,
        retired_by_membership_id=link.retired_by_membership_id,
        access_mismatch_warning=access_mismatch_warning,
        lifecycle=IpMatterLifecycleRecord(
            matter_id=matter.id,
            matter_code=matter.matter_code,
            matter_title=matter.title,
            matter_status=str(getattr(matter.status, "value", matter.status)),
            matter_is_active=matter.is_active,
            docket_id=docket.id,
            docket_title=docket.title,
            docket_status=docket.status,
            docket_is_active=docket.is_active,
        ),
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def _visible_records(
    session: Session,
    *,
    context: SessionContext,
    rows: list[IpMatterLink],
) -> list[IpMatterLinkRecord]:
    if not rows:
        return []
    docket_ids = {link.docket_id for link in rows}
    matter_ids = {link.matter_id for link in rows}
    dockets = {
        docket.id: docket
        for docket in session.scalars(
            select(IpDocketRecord).where(
                IpDocketRecord.id.in_(docket_ids),
                IpDocketRecord.company_id == context.company.id,
                visible_ip_dockets_filter(session, context=context),
            )
        )
    }
    matters = {
        matter.id: matter
        for matter in session.scalars(
            select(Matter).where(
                Matter.id.in_(matter_ids),
                Matter.company_id == context.company.id,
                visible_matters_filter(session, context=context),
            )
        )
    }
    visible_pairs = [
        (dockets[link.docket_id], matters[link.matter_id])
        for link in rows
        if link.docket_id in dockets and link.matter_id in matters
    ]
    mismatch_warnings = _access_mismatch_warnings(
        session,
        context=context,
        pairs=visible_pairs,
    )
    records: list[IpMatterLinkRecord] = []
    for link in rows:
        docket = dockets.get(link.docket_id)
        matter = matters.get(link.matter_id)
        if docket is None or matter is None:
            continue
        records.append(
            _record(
                session,
                context=context,
                link=link,
                docket=docket,
                matter=matter,
                access_mismatch_warning=mismatch_warnings[(docket.id, matter.id)],
            )
        )
    return records


def list_docket_matter_links(
    session: Session, *, context: SessionContext, docket_id: str
) -> IpDocketMatterLinkListResponse:
    docket = session.scalar(
        select(IpDocketRecord).where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
    )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    rows = list(
        session.scalars(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.docket_id == docket.id,
            )
            .order_by(
                IpMatterLink.retired_at.is_not(None),
                IpMatterLink.effective_from.desc(),
                IpMatterLink.id,
            )
        )
    )
    records = _visible_records(session, context=context, rows=rows)
    return IpDocketMatterLinkListResponse(
        docket_id=docket.id,
        links=records,
        count=len(records),
        active_count=sum(row.retired_at is None for row in records),
    )


def list_matter_ip_links(
    session: Session, *, context: SessionContext, matter_id: str
) -> MatterIpLinkListResponse:
    matter = session.scalar(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.company_id == context.company.id,
        )
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    rows = list(
        session.scalars(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.matter_id == matter.id,
            )
            .order_by(
                IpMatterLink.retired_at.is_not(None),
                IpMatterLink.effective_from.desc(),
                IpMatterLink.id,
            )
        )
    )
    records = _visible_records(session, context=context, rows=rows)
    return MatterIpLinkListResponse(
        matter_id=matter.id,
        links=records,
        count=len(records),
        active_count=sum(row.retired_at is None for row in records),
    )


def create_matter_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpMatterLinkCreateRequest,
    commit: bool = True,
) -> IpMatterLinkRecord:
    context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:write"
    )
    matter = session.scalar(
        select(Matter)
        .where(
            Matter.id == payload.matter_id,
            Matter.company_id == context.company.id,
        )
        .with_for_update(of=Matter)
        .execution_options(populate_existing=True)
    )
    if matter is None:
        raise HTTPException(status_code=404, detail="Matter not found.")
    assert_access(session, context=context, matter=matter)
    docket = session.scalar(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpDocketRecord)
        .execution_options(populate_existing=True)
    )
    if docket is None:
        raise HTTPException(status_code=404, detail="IP docket record not found.")
    assert_ip_docket_access(session, context=context, docket=docket)
    if _aware(docket.updated_at) != _aware(payload.expected_docket_updated_at):
        raise _conflict("ip_docket_version_conflict", "The IP record changed; reload and retry.")
    if payload.relation_role == "operational":
        assert_operational_matter(session, matter=matter, lock_for_write=False)
        active_operational = session.scalar(
            select(IpMatterLink)
            .where(
                IpMatterLink.company_id == context.company.id,
                IpMatterLink.docket_id == docket.id,
                IpMatterLink.relation_role == "operational",
                IpMatterLink.retired_at.is_(None),
            )
            .limit(1)
        )
        if active_operational is not None or docket.matter_id not in (None, matter.id):
            raise _conflict(
                "ip_operational_matter_exists",
                "Retire the current operational Matter link before assigning another.",
            )
    now = datetime.now(UTC)
    effective_from = payload.effective_from or now
    if _aware(effective_from) > now:
        raise HTTPException(status_code=422, detail="effective_from cannot be in the future.")
    link = IpMatterLink(
        company_id=context.company.id,
        docket_id=docket.id,
        matter_id=matter.id,
        relation_role=payload.relation_role,
        effective_from=effective_from,
        source="manual",
        source_reference=payload.source_reference,
        reason=payload.reason.strip(),
        created_by_membership_id=context.membership.id,
    )
    session.add(link)
    if payload.relation_role == "operational":
        docket.matter_id = matter.id
    docket.updated_at = now
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise _conflict(
            "ip_matter_link_duplicate",
            "That active Matter link already exists.",
        ) from exc
    record_from_context(
        session,
        context,
        action="ip_matter_link.created",
        target_type="ip_matter_link",
        target_id=link.id,
        matter_id=matter.id,
        ip_docket_id=docket.id,
        metadata={"relation_role": link.relation_role, "effective_from": link.effective_from},
    )
    if commit:
        session.commit()
        session.refresh(link)
    return _record(session, context=context, link=link, docket=docket, matter=matter)


def retire_matter_link(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    link_id: str,
    payload: IpMatterLinkRetireRequest,
) -> IpMatterLinkRetireResponse:
    context = _lock_ip_writer_context(
        session, context=context, required_capability="ip:write"
    )
    discovered = session.scalar(
        select(IpMatterLink).where(
            IpMatterLink.id == link_id,
            IpMatterLink.docket_id == docket_id,
            IpMatterLink.company_id == context.company.id,
        )
    )
    if discovered is None:
        raise HTTPException(status_code=404, detail="IP Matter link not found.")
    matter = session.scalar(
        select(Matter)
        .where(
            Matter.id == discovered.matter_id,
            Matter.company_id == context.company.id,
        )
        .with_for_update(of=Matter)
    )
    docket = session.scalar(
        select(IpDocketRecord)
        .where(
            IpDocketRecord.id == docket_id,
            IpDocketRecord.company_id == context.company.id,
        )
        .with_for_update(of=IpDocketRecord)
        .execution_options(populate_existing=True)
    )
    link = session.scalar(
        select(IpMatterLink)
        .where(
            IpMatterLink.id == link_id,
            IpMatterLink.company_id == context.company.id,
        )
        .with_for_update(of=IpMatterLink)
        .execution_options(populate_existing=True)
    )
    if matter is None or docket is None or link is None:
        raise HTTPException(status_code=404, detail="IP Matter link not found.")
    assert_access(session, context=context, matter=matter)
    assert_ip_docket_access(session, context=context, docket=docket)
    if link.retired_at is not None:
        raise _conflict("ip_matter_link_retired", "That Matter link is already retired.")
    if _aware(link.updated_at) != _aware(payload.expected_link_updated_at):
        raise _conflict(
            "ip_matter_link_version_conflict",
            "The Matter link changed; reload and retry.",
        )
    if _aware(docket.updated_at) != _aware(payload.expected_docket_updated_at):
        raise _conflict("ip_docket_version_conflict", "The IP record changed; reload and retry.")
    now = datetime.now(UTC)
    retired_at = payload.retired_at or now
    if _aware(retired_at) < _aware(link.effective_from) or _aware(retired_at) > now:
        raise HTTPException(
            status_code=422,
            detail="retired_at must be between effective_from and the current time.",
        )
    link.retired_at = retired_at
    link.retired_by_membership_id = context.membership.id
    link.retirement_reason = payload.reason.strip()
    link.updated_at = now
    pointer_cleared = link.relation_role == "operational" and docket.matter_id == matter.id
    if pointer_cleared:
        docket.matter_id = None
    docket.updated_at = now
    record_from_context(
        session,
        context,
        action="ip_matter_link.retired",
        target_type="ip_matter_link",
        target_id=link.id,
        matter_id=matter.id,
        ip_docket_id=docket.id,
        metadata={"relation_role": link.relation_role, "retired_at": retired_at},
    )
    session.commit()
    session.refresh(link)
    return IpMatterLinkRetireResponse(
        link=_record(session, context=context, link=link, docket=docket, matter=matter),
        operational_pointer_cleared=pointer_cleared,
    )
