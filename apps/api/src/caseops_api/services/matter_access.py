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

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.sql import Select

from caseops_api.db.models import (
    AuditEvent,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDocketRecord,
    IpDocumentLink,
    Matter,
    MatterAccessGrant,
    MatterAccessLevel,
    MembershipRole,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    Team,
    TeamMembership,
)
from caseops_api.schemas.ip_access import (
    IpAccessAffectedMembership,
    IpAccessApplyRequest,
    IpAccessChangeRequest,
    IpAccessChangeResponse,
    IpAccessGrantRecord,
    IpAccessPanelResponse,
    IpAccessPreviewResponse,
    IpEthicalWallRecord,
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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _active_at(row: MatterAccessGrant | EthicalWall, now: datetime) -> bool:
    effective_from = _as_utc(row.effective_from)
    expires_at = _as_utc(row.expires_at)
    revoked_at = _as_utc(row.revoked_at)
    return bool(
        revoked_at is None
        and (effective_from is None or effective_from <= now)
        and (expires_at is None or expires_at > now)
    )


def _load_ip_docket_for_access_management(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    lock: bool = False,
) -> IpDocketRecord:
    statement = select(IpDocketRecord).where(
        IpDocketRecord.id == docket_id,
        IpDocketRecord.company_id == context.company.id,
    )
    if lock:
        statement = statement.with_for_update(of=IpDocketRecord)
    docket = session.scalar(statement)
    if docket is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="IP docket record not found.",
        )
    return docket


def _ip_access_rows(
    session: Session,
    *,
    docket: IpDocketRecord,
) -> tuple[list[MatterAccessGrant], list[EthicalWall]]:
    grants = list(
        session.scalars(
            select(MatterAccessGrant)
            .where(MatterAccessGrant.ip_docket_id == docket.id)
            .order_by(MatterAccessGrant.created_at, MatterAccessGrant.id)
        ).all()
    )
    walls = list(
        session.scalars(
            select(EthicalWall)
            .where(EthicalWall.ip_docket_id == docket.id)
            .order_by(EthicalWall.created_at, EthicalWall.id)
        ).all()
    )
    return grants, walls


def _active_company_memberships(
    session: Session,
    *,
    company_id: str,
) -> list[CompanyMembership]:
    return list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
            )
            .order_by(CompanyMembership.created_at, CompanyMembership.id)
        ).all()
    )


def _active_team_membership_map(
    session: Session,
    *,
    company_id: str,
) -> tuple[dict[str, set[str]], dict[str, str]]:
    rows = session.execute(
        select(TeamMembership.team_id, TeamMembership.membership_id, Team.name)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.company_id == company_id, Team.is_active.is_(True))
    ).all()
    membership_teams: dict[str, set[str]] = {}
    team_labels: dict[str, str] = {}
    for team_id, membership_id, team_name in rows:
        membership_teams.setdefault(str(membership_id), set()).add(str(team_id))
        team_labels[str(team_id)] = str(team_name)
    return membership_teams, team_labels


def _membership_label(membership: CompanyMembership) -> str:
    user = membership.user
    return str(user.full_name or user.email or membership.id)


def _subject_matches(
    *,
    membership_id: str,
    team_ids: set[str],
    subject_membership_id: str | None,
    subject_team_id: str | None,
) -> bool:
    return bool(
        (subject_membership_id is not None and subject_membership_id == membership_id)
        or (subject_team_id is not None and subject_team_id in team_ids)
    )


def _policy_visible_from_rows(
    *,
    membership_id: str,
    team_ids: set[str],
    restricted: bool,
    grants: list[MatterAccessGrant],
    walls: list[EthicalWall],
    now: datetime,
    ignored_grant_id: str | None = None,
    ignored_wall_id: str | None = None,
    added_grant_subject: tuple[str, str, datetime | None, datetime | None] | None = None,
    added_wall_subject: tuple[str, str, datetime | None, datetime | None] | None = None,
) -> bool:
    for wall in walls:
        if wall.id == ignored_wall_id or not _active_at(wall, now):
            continue
        if _subject_matches(
            membership_id=membership_id,
            team_ids=team_ids,
            subject_membership_id=wall.excluded_membership_id,
            subject_team_id=wall.excluded_team_id,
        ):
            return False
    if added_wall_subject is not None:
        subject_type, subject_id, effective_from, expires_at = added_wall_subject
        effective = _as_utc(effective_from)
        expires = _as_utc(expires_at)
        active = (effective is None or effective <= now) and (
            expires is None or expires > now
        )
        matches = (
            subject_type == "membership" and subject_id == membership_id
        ) or (subject_type == "team" and subject_id in team_ids)
        if active and matches:
            return False
    if not restricted:
        return True
    for grant in grants:
        if grant.id == ignored_grant_id or not _active_at(grant, now):
            continue
        if _subject_matches(
            membership_id=membership_id,
            team_ids=team_ids,
            subject_membership_id=grant.membership_id,
            subject_team_id=grant.team_id,
        ):
            return True
    if added_grant_subject is not None:
        subject_type, subject_id, effective_from, expires_at = added_grant_subject
        effective = _as_utc(effective_from)
        expires = _as_utc(expires_at)
        active = (effective is None or effective <= now) and (
            expires is None or expires > now
        )
        matches = (
            subject_type == "membership" and subject_id == membership_id
        ) or (subject_type == "team" and subject_id in team_ids)
        if active and matches:
            return True
    return False


def _validate_ip_access_change(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    payload: IpAccessChangeRequest,
    grants: list[MatterAccessGrant],
    walls: list[EthicalWall],
) -> tuple[MatterAccessGrant | None, EthicalWall | None]:
    if docket.access_policy_version != payload.expected_access_policy_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "IP access policy changed after this view was loaded. "
                "Refresh the access preview and try again."
            ),
        )
    grant: MatterAccessGrant | None = None
    wall: EthicalWall | None = None
    if payload.action in {"grant", "add_wall"}:
        if payload.subject_type == "membership":
            subject = session.scalar(
                select(CompanyMembership).where(
                    CompanyMembership.id == payload.subject_id,
                    CompanyMembership.company_id == context.company.id,
                    CompanyMembership.is_active.is_(True),
                )
            )
        else:
            subject = session.scalar(
                select(Team).where(
                    Team.id == payload.subject_id,
                    Team.company_id == context.company.id,
                    Team.is_active.is_(True),
                )
            )
        if subject is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Access subject does not belong to this company or is inactive.",
            )
    if payload.action == "grant":
        duplicate = next(
            (
                row
                for row in grants
                if row.revoked_at is None
                and (
                    payload.subject_type == "membership"
                    and row.membership_id == payload.subject_id
                    or payload.subject_type == "team"
                    and row.team_id == payload.subject_id
                )
            ),
            None,
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active grant already exists for this subject.",
            )
    elif payload.action == "add_wall":
        duplicate = next(
            (
                row
                for row in walls
                if row.revoked_at is None
                and (
                    payload.subject_type == "membership"
                    and row.excluded_membership_id == payload.subject_id
                    or payload.subject_type == "team"
                    and row.excluded_team_id == payload.subject_id
                )
            ),
            None,
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An active ethical wall already exists for this subject.",
            )
    elif payload.action == "revoke_grant":
        grant = next(
            (
                row
                for row in grants
                if row.id == payload.grant_id and row.revoked_at is None
            ),
            None,
        )
        if grant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active IP access grant not found.",
            )
    elif payload.action == "revoke_wall":
        wall = next(
            (
                row
                for row in walls
                if row.id == payload.wall_id and row.revoked_at is None
            ),
            None,
        )
        if wall is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active IP ethical wall not found.",
            )
    return grant, wall


def _preview_token(
    *,
    company_id: str,
    docket_id: str,
    payload: IpAccessChangeRequest,
) -> str:
    canonical = json.dumps(
        {
            "company_id": company_id,
            "docket_id": docket_id,
            "change": payload.model_dump(mode="json", exclude={"preview_token"}),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ip_access_preview_for_docket(
    session: Session,
    *,
    context: SessionContext,
    docket: IpDocketRecord,
    payload: IpAccessChangeRequest,
) -> IpAccessPreviewResponse:
    grants, walls = _ip_access_rows(session, docket=docket)
    revoked_grant, revoked_wall = _validate_ip_access_change(
        session,
        context=context,
        docket=docket,
        payload=payload,
        grants=grants,
        walls=walls,
    )
    memberships = _active_company_memberships(
        session, company_id=context.company.id
    )
    membership_teams, _ = _active_team_membership_map(
        session, company_id=context.company.id
    )
    now = datetime.now(UTC)
    linked_matter = (
        session.get(Matter, docket.matter_id) if docket.matter_id is not None else None
    )
    affected: list[IpAccessAffectedMembership] = []
    subject_membership_id = payload.subject_id if payload.subject_type == "membership" else None
    subject_team_id = payload.subject_id if payload.subject_type == "team" else None
    if revoked_grant is not None:
        subject_membership_id = revoked_grant.membership_id
        subject_team_id = revoked_grant.team_id
    if revoked_wall is not None:
        subject_membership_id = revoked_wall.excluded_membership_id
        subject_team_id = revoked_wall.excluded_team_id
    for membership in memberships:
        team_ids = membership_teams.get(membership.id, set())
        before_visible = _policy_visible_from_rows(
            membership_id=membership.id,
            team_ids=team_ids,
            restricted=docket.restricted,
            grants=grants,
            walls=walls,
            now=now,
        )
        after_visible = _policy_visible_from_rows(
            membership_id=membership.id,
            team_ids=team_ids,
            restricted=(
                bool(payload.restricted)
                if payload.action == "set_restricted"
                else docket.restricted
            ),
            grants=grants,
            walls=walls,
            now=now,
            ignored_grant_id=(
                revoked_grant.id if payload.action == "revoke_grant" and revoked_grant else None
            ),
            ignored_wall_id=(
                revoked_wall.id if payload.action == "revoke_wall" and revoked_wall else None
            ),
            added_grant_subject=(
                (
                    str(payload.subject_type),
                    str(payload.subject_id),
                    payload.effective_from,
                    payload.expires_at,
                )
                if payload.action == "grant"
                else None
            ),
            added_wall_subject=(
                (
                    str(payload.subject_type),
                    str(payload.subject_id),
                    payload.effective_from,
                    payload.expires_at,
                )
                if payload.action == "add_wall"
                else None
            ),
        )
        linked_visible: bool | None = None
        if linked_matter is not None:
            linked_context = SessionContext(
                company=context.company,
                user=membership.user,
                membership=membership,
            )
            linked_visible = can_access(
                session,
                context=linked_context,
                matter=linked_matter,
            )
        in_subject = payload.action == "set_restricted" or _subject_matches(
            membership_id=membership.id,
            team_ids=team_ids,
            subject_membership_id=subject_membership_id,
            subject_team_id=subject_team_id,
        )
        if in_subject or before_visible != after_visible:
            affected.append(
                IpAccessAffectedMembership(
                    membership_id=membership.id,
                    label=_membership_label(membership),
                    before_visible=before_visible,
                    after_visible=after_visible,
                    linked_matter_visible=linked_visible,
                )
            )
    actor_effect = next(
        (row for row in affected if row.membership_id == context.membership.id),
        None,
    )
    if actor_effect is not None and actor_effect.before_visible and not actor_effect.after_visible:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You cannot remove your own last effective access. "
                "A different authorized owner or access administrator must perform this change."
            ),
        )
    gains = sum(not row.before_visible and row.after_visible for row in affected)
    losses = sum(row.before_visible and not row.after_visible for row in affected)
    linked_mismatch = any(
        row.linked_matter_visible is not None
        and row.linked_matter_visible != row.after_visible
        for row in affected
    )
    queued_delivery_count = int(
        session.scalar(
            select(func.count(NotificationDeliveryIntent.id)).where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.ip_docket_id == docket.id,
                NotificationDeliveryIntent.status.in_(
                    [
                        NotificationDeliveryStatus.QUEUED,
                        NotificationDeliveryStatus.RETRY_SCHEDULED,
                    ]
                ),
            )
        )
        or 0
    )
    document_count = int(
        session.scalar(
            select(func.count(func.distinct(IpDocumentLink.document_id))).where(
                IpDocumentLink.company_id == context.company.id,
                IpDocumentLink.docket_id == docket.id,
            )
        )
        or 0
    )
    warnings = [
        "Linked Matter and IP access remain independent; this change never copies permissions."
    ] if linked_mismatch else []
    if losses:
        warnings.append(
            "Revoked users lose direct, list, document, source, audit, export, "
            "and queued-delivery visibility."
        )
    if payload.action == "set_restricted" and payload.restricted is False:
        warnings.append(
            "Default visibility will include every active internal membership "
            "not blocked by an ethical wall."
        )
    return IpAccessPreviewResponse(
        docket_id=docket.id,
        access_policy_version=docket.access_policy_version,
        action=payload.action,
        preview_token=_preview_token(
            company_id=context.company.id,
            docket_id=docket.id,
            payload=payload,
        ),
        affected_memberships=affected,
        visibility_gain_count=gains,
        visibility_loss_count=losses,
        queued_delivery_recheck_count=queued_delivery_count,
        document_count=document_count,
        linked_matter_id=docket.matter_id,
        linked_matter_mismatch=linked_mismatch,
        warnings=warnings,
    )


def preview_ip_access_change(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpAccessChangeRequest,
) -> IpAccessPreviewResponse:
    docket = _load_ip_docket_for_access_management(
        session,
        context=context,
        docket_id=docket_id,
    )
    return _ip_access_preview_for_docket(
        session,
        context=context,
        docket=docket,
        payload=payload,
    )


def _subject_labels(
    session: Session,
    *,
    company_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    memberships = _active_company_memberships(session, company_id=company_id)
    membership_labels = {
        membership.id: _membership_label(membership) for membership in memberships
    }
    team_labels = {
        str(team_id): str(name)
        for team_id, name in session.execute(
            select(Team.id, Team.name).where(Team.company_id == company_id)
        ).all()
    }
    return membership_labels, team_labels


def get_ip_access_panel(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
) -> IpAccessPanelResponse:
    docket = _load_ip_docket_for_access_management(
        session,
        context=context,
        docket_id=docket_id,
    )
    grants, walls = _ip_access_rows(session, docket=docket)
    membership_labels, team_labels = _subject_labels(
        session, company_id=context.company.id
    )
    memberships = _active_company_memberships(
        session, company_id=context.company.id
    )
    membership_teams, _ = _active_team_membership_map(
        session, company_id=context.company.id
    )
    now = datetime.now(UTC)
    active_count = sum(
        _policy_visible_from_rows(
            membership_id=membership.id,
            team_ids=membership_teams.get(membership.id, set()),
            restricted=docket.restricted,
            grants=grants,
            walls=walls,
            now=now,
        )
        for membership in memberships
    )
    queued_count = int(
        session.scalar(
            select(func.count(NotificationDeliveryIntent.id)).where(
                NotificationDeliveryIntent.company_id == context.company.id,
                NotificationDeliveryIntent.ip_docket_id == docket.id,
                NotificationDeliveryIntent.status.in_(
                    [
                        NotificationDeliveryStatus.QUEUED,
                        NotificationDeliveryStatus.RETRY_SCHEDULED,
                    ]
                ),
            )
        )
        or 0
    )
    grant_records = [
        IpAccessGrantRecord(
            id=row.id,
            subject_type="membership" if row.membership_id else "team",
            subject_id=str(row.membership_id or row.team_id),
            subject_label=(
                membership_labels.get(str(row.membership_id), "Former membership")
                if row.membership_id
                else team_labels.get(str(row.team_id), "Former team")
            ),
            access_level="member",
            reason=row.reason,
            effective_from=row.effective_from,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            granted_by_membership_id=row.granted_by_membership_id,
            revoked_by_membership_id=row.revoked_by_membership_id,
            record_version=row.record_version,
            created_at=row.created_at,
        )
        for row in grants
    ]
    wall_records = [
        IpEthicalWallRecord(
            id=row.id,
            subject_type="membership" if row.excluded_membership_id else "team",
            subject_id=str(row.excluded_membership_id or row.excluded_team_id),
            subject_label=(
                membership_labels.get(str(row.excluded_membership_id), "Former membership")
                if row.excluded_membership_id
                else team_labels.get(str(row.excluded_team_id), "Former team")
            ),
            reason=row.reason,
            effective_from=row.effective_from,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            created_by_membership_id=row.created_by_membership_id,
            revoked_by_membership_id=row.revoked_by_membership_id,
            record_version=row.record_version,
            created_at=row.created_at,
        )
        for row in walls
    ]
    return IpAccessPanelResponse(
        docket_id=docket.id,
        docket_title=docket.title,
        restricted=docket.restricted,
        access_policy_version=docket.access_policy_version,
        linked_matter_id=docket.matter_id,
        grants=grant_records,
        walls=wall_records,
        active_internal_membership_count=active_count,
        queued_delivery_count=queued_count,
    )


def apply_ip_access_change(
    session: Session,
    *,
    context: SessionContext,
    docket_id: str,
    payload: IpAccessApplyRequest,
) -> IpAccessChangeResponse:
    docket = _load_ip_docket_for_access_management(
        session,
        context=context,
        docket_id=docket_id,
        lock=True,
    )
    preview = _ip_access_preview_for_docket(
        session,
        context=context,
        docket=docket,
        payload=payload,
    )
    if preview.preview_token != payload.preview_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Access preview does not match this command. Preview the change again.",
        )
    grants, walls = _ip_access_rows(session, docket=docket)
    revoked_grant, revoked_wall = _validate_ip_access_change(
        session,
        context=context,
        docket=docket,
        payload=payload,
        grants=grants,
        walls=walls,
    )
    now = datetime.now(UTC)
    if payload.action == "set_restricted":
        docket.restricted = bool(payload.restricted)
    elif payload.action == "grant":
        session.add(
            MatterAccessGrant(
                company_id=context.company.id,
                ip_docket_id=docket.id,
                membership_id=(
                    payload.subject_id if payload.subject_type == "membership" else None
                ),
                team_id=payload.subject_id if payload.subject_type == "team" else None,
                access_level=MatterAccessLevel.MEMBER,
                reason=payload.reason.strip(),
                granted_by_membership_id=context.membership.id,
                effective_from=payload.effective_from or now,
                expires_at=payload.expires_at,
            )
        )
    elif payload.action == "revoke_grant":
        assert revoked_grant is not None
        revoked_grant.revoked_at = now
        revoked_grant.revoked_by_membership_id = context.membership.id
        revoked_grant.record_version += 1
        session.add(revoked_grant)
    elif payload.action == "add_wall":
        session.add(
            EthicalWall(
                company_id=context.company.id,
                ip_docket_id=docket.id,
                excluded_membership_id=(
                    payload.subject_id if payload.subject_type == "membership" else None
                ),
                excluded_team_id=(
                    payload.subject_id if payload.subject_type == "team" else None
                ),
                reason=payload.reason.strip(),
                created_by_membership_id=context.membership.id,
                effective_from=payload.effective_from or now,
                expires_at=payload.expires_at,
            )
        )
    elif payload.action == "revoke_wall":
        assert revoked_wall is not None
        revoked_wall.revoked_at = now
        revoked_wall.revoked_by_membership_id = context.membership.id
        revoked_wall.record_version += 1
        session.add(revoked_wall)
    previous_version = docket.access_policy_version
    docket.access_policy_version += 1
    session.add(docket)
    session.flush()
    operation_id = str(uuid4())
    record_from_context(
        session,
        context,
        action=f"ip.access.{payload.action}",
        target_type="ip_docket_record",
        target_id=docket.id,
        matter_id=docket.matter_id,
        ip_docket_id=docket.id,
        metadata={
            "reason": payload.reason.strip(),
            "subject_type": payload.subject_type,
            "subject_id": payload.subject_id,
            "grant_id": payload.grant_id,
            "wall_id": payload.wall_id,
            "restricted": payload.restricted,
            "access_policy_version_before": previous_version,
            "access_policy_version_after": docket.access_policy_version,
            "preview_token": payload.preview_token,
            "invalidation_operation_id": operation_id,
            "visibility_gain_count": preview.visibility_gain_count,
            "visibility_loss_count": preview.visibility_loss_count,
            "queued_delivery_recheck_count": preview.queued_delivery_recheck_count,
            "invalidation_contract": [
                "access_policy_generation",
                "result_hydration",
                "queued_delivery_reauthorization",
            ],
            "linked_matter_permissions_copied": False,
        },
    )
    session.commit()
    return IpAccessChangeResponse(
        action=payload.action,
        invalidation_operation_id=operation_id,
        visibility_gain_count=preview.visibility_gain_count,
        visibility_loss_count=preview.visibility_loss_count,
        queued_delivery_recheck_count=preview.queued_delivery_recheck_count,
        panel=get_ip_access_panel(
            session,
            context=context,
            docket_id=docket.id,
        ),
    )


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
        forbidden_parallel_owners=[
            "parallel_ip_grant_store",
            "parallel_ip_wall_store",
        ],
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
    "apply_ip_access_change",
    "assert_access",
    "assert_ip_docket_access",
    "attach_visible_ip_dockets_filter",
    "attach_visible_matters_filter",
    "can_access",
    "can_access_ip_docket",
    "list_access_panel",
    "get_ip_access_panel",
    "preview_ip_access_change",
    "remove_access_grant",
    "remove_ethical_wall",
    "reconcile_record_access",
    "record_access_foundation_contract",
    "seed_restricted_ip_creator_access",
    "set_restricted_access",
    "visible_matters_filter",
    "visible_ip_dockets_filter",
]
