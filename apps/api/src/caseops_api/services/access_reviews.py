"""Review evidence orchestrator. All grant mutations delegate to matter_access."""

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import exists, select, tuple_
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    AccessReviewCampaign,
    AccessReviewDecision,
    Company,
    CompanyMembership,
    EthicalWall,
    IpDeadline,
    IpDeadlineCoverage,
    IpDocketRecord,
    IpRelatedRightObligation,
    IpResponsibilityAssignment,
    Matter,
    MatterAccessGrant,
    MatterDeadline,
    MatterHearing,
    MatterTask,
    MembershipRole,
    NotificationDeliveryIntent,
    Team,
    TeamMembership,
)
from caseops_api.schemas.access_reviews import (
    CampaignCreate,
    CampaignPage,
    CampaignRecord,
    DecisionRecord,
    GrantSnapshot,
    ReviewDecision,
    ScopeSnapshot,
    TargetPage,
    TargetType,
)
from caseops_api.schemas.ip_access import IpAccessApplyRequest, IpAccessChangeRequest
from caseops_api.services import matter_access
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.capabilities import membership_has_capability
from caseops_api.services.matter_operational_guard import matter_is_operational
from caseops_api.services.security import require_step_up_always
from caseops_api.services.session_context import SessionContext


def _fail(detail: str, status: int = 409):
    raise HTTPException(status_code=status, detail=detail)


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _actor(session: Session, context: SessionContext, *, write=False):
    company_query = select(Company).where(Company.id == context.company.id)
    company = session.scalar(
        (company_query.with_for_update() if write else company_query).execution_options(
            populate_existing=True
        )
    )
    if company is None or not company.is_active:
        _fail("An active workspace is required.", 403)
    if write:
        # The owner may also fence operational assignees. Lock the bounded tenant
        # membership set first so campaigns cannot invert that ordering.
        ids = list(
            session.scalars(
                select(CompanyMembership.id)
                .where(CompanyMembership.company_id == company.id)
                .limit(201)
            )
        )
        if len(ids) > 200:
            _fail("This workspace exceeds the 200-membership review limit.")
        members = lock_company_memberships_for_assignment(
            session, company_id=company.id, membership_ids=ids
        )
        actor = members.get(context.membership.id)
        if actor is not None:
            require_locked_membership_capability(session, actor, "matter_access:manage")
    else:
        actor = session.scalar(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.id == context.membership.id,
                CompanyMembership.company_id == company.id,
            )
            .execution_options(populate_existing=True)
        )
        members = {}
    if (
        actor is None
        or actor.user_id != context.user.id
        or not actor.is_active
        or not actor.user.is_active
        or actor.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
        or not membership_has_capability(session, actor, "matter_access:manage")
    ):
        _fail("Active access administration is required.", 403)
    context = SessionContext(company=company, membership=actor, user=actor.user)
    if write:
        require_step_up_always(session, context=context, purpose="record_access_change")
    return context, members


def _model(kind: TargetType):
    return Matter if kind == "matter" else IpDocketRecord


def _visible(session, context, kind):
    return (
        matter_access.visible_matters_filter
        if kind == "matter"
        else matter_access.visible_ip_dockets_filter
    )(session, context=context)


def _target(session, context, kind, target_id, *, write=False):
    model = _model(kind)
    query = select(model).where(
        model.id == target_id,
        model.company_id == context.company.id,
        _visible(session, context, kind),
    )
    # Acquire the linked parent before the docket, as the canonical owner does.
    if write and kind == "ip_docket":
        parent = session.scalar(
            select(Matter)
            .join(IpDocketRecord, IpDocketRecord.matter_id == Matter.id)
            .where(
                IpDocketRecord.id == target_id,
                IpDocketRecord.company_id == context.company.id,
                Matter.company_id == context.company.id,
            )
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
        if parent is not None and not matter_is_operational(parent):
            _fail("A terminal linked Matter cannot change access reviews.")
    row = session.scalar(
        (query.with_for_update(of=model) if write else query).execution_options(
            populate_existing=True
        )
    )
    if row is None:
        _fail("Review target not found.", 404)
    if write and (
        (kind == "matter" and not matter_is_operational(row))
        or (
            kind == "ip_docket"
            and (
                not row.is_active
                or row.archived_by_matter_disposal
                or row.status in {"archived", "abandoned", "transferred", "retired", "closed"}
            )
        )
    ):
        _fail("A terminal record cannot start or finalize an access review.")
    return row


def list_targets(session, *, context, kind: TargetType, query="", after_id=None):
    context, _ = _actor(session, context)
    model = _model(kind)
    statement = select(model.id, model.title).where(
        model.company_id == context.company.id, _visible(session, context, kind)
    )
    if kind == "matter":
        statement = statement.where(
            Matter.is_active.is_(True), Matter.status.in_(("intake", "active", "on_hold"))
        )
    else:
        statement = statement.where(
            IpDocketRecord.is_active.is_(True),
            IpDocketRecord.archived_by_matter_disposal.is_(False),
            IpDocketRecord.status.notin_(
                ("archived", "abandoned", "transferred", "retired", "closed")
            ),
            (
                IpDocketRecord.matter_id.is_(None)
                | exists(
                    select(Matter.id).where(
                        Matter.id == IpDocketRecord.matter_id,
                        Matter.company_id == context.company.id,
                        Matter.is_active.is_(True),
                        Matter.status.in_(("intake", "active", "on_hold")),
                    )
                )
            ),
        )
    if query:
        statement = statement.where(model.title.icontains(query, autoescape=True))
    if after_id:
        statement = statement.where(model.id > after_id)
    rows = session.execute(statement.order_by(model.id).limit(26)).all()
    return TargetPage(
        targets=[{"id": row.id, "title": row.title} for row in rows[:25]],
        next_after_id=rows[24].id if len(rows) > 25 else None,
    )


def _snapshot(session, context, kind, target):
    column = MatterAccessGrant.matter_id if kind == "matter" else MatterAccessGrant.ip_docket_id
    now = datetime.now(UTC)
    grants = list(
        session.scalars(
            select(MatterAccessGrant)
            .where(
                MatterAccessGrant.company_id == context.company.id,
                column == target.id,
                MatterAccessGrant.revoked_at.is_(None),
            )
            .order_by(MatterAccessGrant.id)
            .limit(21)
        )
    )
    if len(grants) > 20:
        _fail("This record exceeds the 20-grant campaign limit.")
    member_ids = {g.membership_id for g in grants if g.membership_id}
    team_ids = {g.team_id for g in grants if g.team_id}
    members = {
        m.id: m
        for m in session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id.in_(member_ids),
            )
        )
    }
    teams = {
        t.id: t
        for t in session.scalars(
            select(Team).where(Team.company_id == context.company.id, Team.id.in_(team_ids))
        )
    }
    team_links = session.execute(
        select(TeamMembership.team_id, TeamMembership.membership_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.company_id == context.company.id, Team.id.in_(team_ids))
        .order_by(TeamMembership.team_id, TeamMembership.membership_id)
        .limit(401)
    ).all()
    if len(team_links) > 400:
        _fail("This record exceeds the 400 team-membership review limit.")
    scope = ScopeSnapshot(
        target_type=kind,
        target_id=target.id,
        target_title=target.title,
        access_policy_version=target.access_policy_version,
        grants=[
            GrantSnapshot(
                id=g.id,
                record_version=g.record_version,
                subject_type="membership" if g.membership_id else "team",
                subject_id=g.membership_id or g.team_id,
                subject_label=(
                    members[g.membership_id].user.full_name
                    if g.membership_id in members
                    else teams[g.team_id].name
                    if g.team_id in teams
                    else "Unavailable subject"
                ),
                effective_from=g.effective_from,
                expires_at=g.expires_at,
                reason=g.reason,
            )
            for g in grants
        ],
    )
    return {
        "scope": scope.model_dump(mode="json"),
        "fence": {
            "active": [matter_access._active_at(g, now) for g in grants],
            "team_links": [list(link) for link in team_links],
            "team_active": {key: team.is_active for key, team in teams.items()},
            "members_active": {
                key: bool(m.is_active and m.user.is_active) for key, m in members.items()
            },
            "team_scoping": context.company.team_scoping_enabled,
        },
    }


def scope_snapshot(session, *, context, kind, target_id):
    context, _ = _actor(session, context)
    return ScopeSnapshot.model_validate(
        _snapshot(session, context, kind, _target(session, context, kind, target_id))["scope"]
    )


def _decisions(session, context, ids):
    rows = list(
        session.scalars(
            select(AccessReviewDecision)
            .where(
                AccessReviewDecision.company_id == context.company.id,
                AccessReviewDecision.campaign_id.in_(ids),
            )
            .order_by(AccessReviewDecision.created_at, AccessReviewDecision.id)
            .limit(len(ids) * 20 + 1)
        )
    )
    if len(rows) > len(ids) * 20:
        _fail("Retained campaign decisions exceed the evidence bound.")
    return rows


def _record(row, decisions):
    return CampaignRecord(
        id=row.id,
        title=row.title,
        reason=row.reason,
        trigger=row.trigger,
        status=row.status,
        version=row.version,
        creator_user_id=row.creator_user_id,
        created_at=row.created_at,
        finalized_at=row.finalized_at,
        snapshot=ScopeSnapshot.model_validate(row.snapshot_json["scope"]),
        decisions=[
            DecisionRecord.model_validate(d, from_attributes=True)
            for d in decisions
            if d.campaign_id == row.id
        ],
    )


def _campaign_query(session, context):
    return select(AccessReviewCampaign).where(
        AccessReviewCampaign.company_id == context.company.id,
        (
            exists(
                select(Matter.id).where(
                    Matter.id == AccessReviewCampaign.matter_id,
                    Matter.company_id == context.company.id,
                    _visible(session, context, "matter"),
                )
            )
            | exists(
                select(IpDocketRecord.id).where(
                    IpDocketRecord.id == AccessReviewCampaign.ip_docket_id,
                    IpDocketRecord.company_id == context.company.id,
                    _visible(session, context, "ip_docket"),
                )
            )
        ),
    )


def _load(session, context, campaign_id, *, write=False):
    query = _campaign_query(session, context).where(AccessReviewCampaign.id == campaign_id)
    row = session.scalar(
        (query.with_for_update(of=AccessReviewCampaign) if write else query).execution_options(
            populate_existing=True
        )
    )
    if row is None:
        _fail("Access review not found.", 404)
    return row


def get_campaign(session, *, context, campaign_id):
    context, _ = _actor(session, context)
    return _record(
        _load(session, context, campaign_id), _decisions(session, context, [campaign_id])
    )


def list_campaigns(session, *, context, before_id=None):
    context, _ = _actor(session, context)
    query = _campaign_query(session, context)
    if before_id:
        anchor = _load(session, context, before_id)
        query = query.where(
            tuple_(AccessReviewCampaign.created_at, AccessReviewCampaign.id)
            < (anchor.created_at, anchor.id)
        )
    rows = list(
        session.scalars(
            query.order_by(
                AccessReviewCampaign.created_at.desc(), AccessReviewCampaign.id.desc()
            ).limit(26)
        )
    )
    decisions = _decisions(session, context, [row.id for row in rows[:25]])
    return CampaignPage(
        campaigns=[_record(row, decisions) for row in rows[:25]],
        next_before_id=rows[24].id if len(rows) > 25 else None,
    )


def create_campaign(session, *, context, payload: CampaignCreate):
    context, _members = _actor(session, context, write=True)
    target = _target(session, context, payload.target_type, payload.target_id, write=True)
    if target.access_policy_version != payload.expected_access_policy_version:
        _fail("Access changed. Reload the scope before starting a campaign.")
    snapshot = _snapshot(session, context, payload.target_type, target)
    if not snapshot["scope"]["grants"]:
        _fail("This record has no standing grants to review.")
    row = AccessReviewCampaign(
        company_id=context.company.id,
        matter_id=target.id if payload.target_type == "matter" else None,
        ip_docket_id=target.id if payload.target_type == "ip_docket" else None,
        title=payload.title,
        reason=payload.reason,
        trigger=payload.trigger,
        creator_user_id=context.user.id,
        snapshot_json=snapshot,
        snapshot_hash=_digest(snapshot),
    )
    session.add(row)
    session.flush()
    _audit(session, context, row, "created", {"snapshot_hash": row.snapshot_hash})
    session.commit()
    return _record(row, [])


def _audit(session, context, row, action, metadata):
    record_from_context(
        session,
        context,
        action=f"access.review.{action}",
        target_type="access_review_campaign",
        target_id=row.id,
        matter_id=row.matter_id,
        ip_docket_id=row.ip_docket_id,
        metadata={"campaign_version": row.version, **metadata},
    )


def _current(session, context, row, expected_version):
    if row.status != "open" or row.version != expected_version:
        _fail("This campaign changed or is finalized. Reload before continuing.")
    scope = row.snapshot_json["scope"]
    target = _target(session, context, scope["target_type"], scope["target_id"], write=True)
    if (
        _digest(row.snapshot_json) != row.snapshot_hash
        or _digest(_snapshot(session, context, scope["target_type"], target)) != row.snapshot_hash
    ):
        _fail("The grant snapshot is stale. Start a new campaign against current access.")
    return target


def _owner_budget(session, context, row):
    """Charge retained rows before entering the owner's expanded role/ACL reads."""

    def bound(statement, maximum, label):
        if len(session.execute(statement.limit(maximum + 1)).all()) > maximum:
            _fail(f"This review exceeds the {maximum}-row {label} execution limit.")

    bound(select(Team.id).where(Team.company_id == context.company.id), 100, "team")
    bound(
        select(TeamMembership.id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.company_id == context.company.id),
        400,
        "team membership",
    )
    docket_ids = (
        [row.ip_docket_id]
        if row.ip_docket_id
        else list(
            session.scalars(
                select(IpDocketRecord.id)
                .where(
                    IpDocketRecord.company_id == context.company.id,
                    IpDocketRecord.matter_id == row.matter_id,
                )
                .limit(21)
            )
        )
    )
    if len(docket_ids) > 20:
        _fail("This review exceeds the 20-linked-docket execution limit.")
    matter_id = row.matter_id
    if row.ip_docket_id:
        matter_id = session.scalar(
            select(IpDocketRecord.matter_id).where(
                IpDocketRecord.id == row.ip_docket_id,
                IpDocketRecord.company_id == context.company.id,
            )
        )
    for model in (
        MatterAccessGrant,
        EthicalWall,
        MatterDeadline,
        MatterHearing,
        MatterTask,
        NotificationDeliveryIntent,
    ):
        scope = model.ip_docket_id.in_(docket_ids)
        if matter_id is not None:
            scope = scope | (model.matter_id == matter_id)
        bound(
            select(model.id).where(model.company_id == context.company.id, scope),
            256,
            model.__tablename__,
        )
    for model in (
        IpDeadline,
        IpDeadlineCoverage,
        IpRelatedRightObligation,
        IpResponsibilityAssignment,
    ):
        bound(
            select(model.id).where(
                model.company_id == context.company.id, model.docket_id.in_(docket_ids)
            ),
            256,
            model.__tablename__,
        )


def _independent(session, context, row, grant, reviewer):
    if reviewer.user_id == row.creator_user_id:
        _fail("The campaign preparer cannot review its grants.")
    if grant["subject_type"] == "membership":
        subject_user = session.scalar(
            select(CompanyMembership.user_id).where(
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.id == grant["subject_id"],
            )
        )
        conflict = subject_user == reviewer.user_id
    else:
        conflict = (
            session.scalar(
                select(TeamMembership.id)
                .join(CompanyMembership, CompanyMembership.id == TeamMembership.membership_id)
                .where(
                    TeamMembership.team_id == grant["subject_id"],
                    CompanyMembership.company_id == context.company.id,
                    CompanyMembership.user_id == reviewer.user_id,
                )
                .limit(1)
            )
            is not None
        )
    if conflict:
        _fail("A reviewer cannot certify their own membership or team grant.")


def decide(session, *, context, campaign_id, payload: ReviewDecision):
    context, _members = _actor(session, context, write=True)
    row = _load(session, context, campaign_id, write=True)
    _current(session, context, row, payload.expected_version)
    grant = next(
        (g for g in row.snapshot_json["scope"]["grants"] if g["id"] == payload.grant_id), None
    )
    if grant is None:
        _fail("Grant not found in this campaign.", 404)
    _independent(session, context, row, grant, context.membership)
    decisions = _decisions(session, context, [row.id])
    if any(d.grant_id == payload.grant_id for d in decisions):
        _fail("This grant already has an immutable review decision.")
    decision = AccessReviewDecision(
        company_id=context.company.id,
        campaign_id=row.id,
        grant_id=payload.grant_id,
        decision=payload.decision,
        reason=payload.reason,
        reviewer_user_id=context.user.id,
        reviewer_membership_id=context.membership.id,
    )
    session.add(decision)
    row.version += 1
    session.flush()
    _audit(
        session,
        context,
        row,
        "decided",
        {"grant_id": payload.grant_id, "decision": payload.decision, "reason": payload.reason},
    )
    session.commit()
    return _record(row, [*decisions, decision])


def finalize(session, *, context, campaign_id, expected_version):
    context, members = _actor(session, context, write=True)
    row = _load(session, context, campaign_id, write=True)
    target = _current(session, context, row, expected_version)
    _owner_budget(session, context, row)
    decisions = _decisions(session, context, [row.id])
    grants = row.snapshot_json["scope"]["grants"]
    if {d.grant_id for d in decisions} != {g["id"] for g in grants}:
        _fail("Every snapshotted grant needs an independent decision.")
    for decision in decisions:
        reviewer = members.get(decision.reviewer_membership_id)
        if (
            reviewer is None
            or reviewer.user_id != decision.reviewer_user_id
            or reviewer.role not in (MembershipRole.OWNER, MembershipRole.ADMIN)
        ):
            _fail("A reviewer is no longer authorized. Start a new campaign.")
        require_locked_membership_capability(session, reviewer, "matter_access:manage")
        if reviewer.user_id == context.user.id:
            _fail("The reviewer cannot execute campaign finalization.")
        _independent(
            session, context, row, next(g for g in grants if g["id"] == decision.grant_id), reviewer
        )
    operations = []
    for decision in decisions:
        if decision.decision != "revoke":
            continue
        if row.ip_docket_id:
            command = IpAccessChangeRequest(
                action="revoke_grant",
                grant_id=decision.grant_id,
                reason=decision.reason,
                expected_access_policy_version=target.access_policy_version,
            )
            preview = matter_access.preview_ip_access_change(
                session, context=context, docket_id=target.id, payload=command
            )
            response = matter_access.apply_ip_access_change(
                session,
                context=context,
                docket_id=target.id,
                payload=IpAccessApplyRequest(
                    **command.model_dump(), preview_token=preview.preview_token
                ),
                commit=False,
            )
            operations.append(response.invalidation_operation_id)
        else:
            matter_access.remove_access_grant(
                session,
                context=context,
                matter_id=target.id,
                grant_id=decision.grant_id,
                commit=False,
            )
    row.status = "finalized"
    row.finalized_at = datetime.now(UTC)
    row.version += 1
    session.flush()
    _audit(
        session,
        context,
        row,
        "finalized",
        {
            "snapshot_hash": row.snapshot_hash,
            "revoked_grant_ids": [d.grant_id for d in decisions if d.decision == "revoke"],
            "invalidation_operation_ids": operations,
            "final_access_policy_version": target.access_policy_version,
        },
    )
    session.commit()
    return _record(row, decisions)
