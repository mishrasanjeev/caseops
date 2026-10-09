"""Bounded compliance provenance and live-participant persistence admission."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    MembershipRole,
    NotificationRule,
    NotificationRuleEventType,
    NotificationRuleScopeType,
    TeamMembership,
    User,
)
from caseops_api.services.assignment_memberships import (
    lock_company_memberships_for_assignment,
    require_locked_membership_capability,
)
from caseops_api.services.matter_access import assert_access, can_access
from caseops_api.services.matter_write_fence import lock_matter_private_authority
from caseops_api.services.session_context import SessionContext

_MAX_PARTICIPANTS = 500


class ComplianceParticipantFenceError(HTTPException):
    """A persistence fence rejection must escape best-effort extraction handlers."""


def _select_notification_context(
    session: Session,
    *,
    company_id: str,
    actor_membership_id: str | None,
) -> SessionContext | None:
    stmt = (
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.company), joinedload(CompanyMembership.user))
        .join(Company, Company.id == CompanyMembership.company_id)
        .join(User, User.id == CompanyMembership.user_id)
        .where(
            CompanyMembership.company_id == company_id,
            CompanyMembership.is_active.is_(True),
            User.is_active.is_(True),
            Company.is_active.is_(True),
        )
        .execution_options(populate_existing=True)
    )
    if actor_membership_id:
        actor = session.scalar(stmt.where(CompanyMembership.id == actor_membership_id))
        if actor is not None:
            return SessionContext(company=actor.company, user=actor.user, membership=actor)
    fallback = session.scalar(
        stmt.where(CompanyMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]))
        .order_by(CompanyMembership.created_at.asc(), CompanyMembership.id.asc())
        .limit(1)
    )
    if fallback is None:
        fallback = session.scalar(
            stmt.order_by(CompanyMembership.created_at.asc(), CompanyMembership.id.asc()).limit(1)
        )
    if fallback is None:
        return None
    return SessionContext(company=fallback.company, user=fallback.user, membership=fallback)


def _select_recipient_memberships(
    session: Session,
    *,
    matter: Matter,
    include_admins: bool = False,
) -> list[CompanyMembership]:
    ids: list[str] = []
    if matter.assignee_membership_id:
        ids.append(matter.assignee_membership_id)
    if matter.team_id:
        ids.extend(
            session.scalars(
                select(TeamMembership.membership_id)
                .where(TeamMembership.team_id == matter.team_id)
                .limit(_MAX_PARTICIPANTS + 1)
            )
        )
    if include_admins:
        ids.extend(
            session.scalars(
                select(CompanyMembership.id)
                .where(
                    CompanyMembership.company_id == matter.company_id,
                    CompanyMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
                )
                .limit(_MAX_PARTICIPANTS + 1)
            )
        )
    if not ids:
        ids.extend(
            session.scalars(
                select(CompanyMembership.id)
                .where(
                    CompanyMembership.company_id == matter.company_id,
                    CompanyMembership.role.in_([MembershipRole.OWNER, MembershipRole.ADMIN]),
                )
                .limit(_MAX_PARTICIPANTS + 1)
            )
        )
    unique_ids = list(dict.fromkeys(ids))
    _check_participant_bound(unique_ids)
    if not unique_ids:
        return []
    return list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user))
            .where(
                CompanyMembership.id.in_(unique_ids),
                CompanyMembership.company_id == matter.company_id,
                CompanyMembership.is_active.is_(True),
            )
            .execution_options(populate_existing=True)
        )
    )


def _check_participant_bound(ids: list[str] | set[str]) -> None:
    if len(ids) > _MAX_PARTICIPANTS:
        raise ComplianceParticipantFenceError(409, detail={"code": "compliance_participant_limit"})


@dataclass(frozen=True)
class CapturedOrderNotificationRule:
    id: str
    event_type: str
    scope_type: str
    scope_id: str | None
    channels: tuple[str, ...]
    recipient_ids: tuple[str, ...]


def _select_order_notifications(
    session: Session,
    *,
    matter: Matter,
) -> tuple[CapturedOrderNotificationRule, ...]:
    rules = list(
        session.scalars(
            select(NotificationRule)
            .where(
                NotificationRule.company_id == matter.company_id,
                NotificationRule.enabled.is_(True),
                NotificationRule.event_type == NotificationRuleEventType.NEW_ORDER_UPLOADED,
                (NotificationRule.scope_type != NotificationRuleScopeType.MATTER)
                | (NotificationRule.scope_id == matter.id),
            )
            .limit(_MAX_PARTICIPANTS + 1)
            .execution_options(populate_existing=True)
        )
    )
    _check_participant_bound([rule.id for rule in rules])
    if not rules:
        return ()
    statement = (
        select(CompanyMembership)
        .options(joinedload(CompanyMembership.user))
        .join(
            User,
            User.id == CompanyMembership.user_id,
        )
        .where(
            CompanyMembership.company_id == matter.company_id,
            CompanyMembership.is_active.is_(True),
            User.is_active.is_(True),
        )
    )
    if all(rule.scope_type == NotificationRuleScopeType.USER for rule in rules):
        statement = statement.where(CompanyMembership.id.in_([rule.scope_id for rule in rules]))
    candidates = list(
        session.scalars(
            statement.order_by(CompanyMembership.id)
            .limit(_MAX_PARTICIPANTS + 1)
            .execution_options(populate_existing=True)
        )
    )
    _check_participant_bound([member.id for member in candidates])
    pairs = sum(
        sum(
            rule.scope_type != NotificationRuleScopeType.USER or rule.scope_id == member.id
            for member in candidates
        )
        for rule in rules
    )
    if pairs > _MAX_PARTICIPANTS:
        raise ComplianceParticipantFenceError(409, detail={"code": "compliance_participant_limit"})
    company = session.get(Company, matter.company_id)
    eligible = {
        member.id
        for member in candidates
        if can_access(
            session,
            context=SessionContext(company=company, user=member.user, membership=member),
            matter=matter,
        )
    }
    return tuple(
        CapturedOrderNotificationRule(
            rule.id,
            rule.event_type,
            rule.scope_type,
            rule.scope_id,
            tuple(rule.channels_json or ["in_app"]),
            tuple(
                member.id
                for member in candidates
                if member.id in eligible
                and (
                    rule.scope_type != NotificationRuleScopeType.USER or rule.scope_id == member.id
                )
            ),
        )
        for rule in rules
    )


@dataclass(frozen=True)
class _ParticipantSelection:
    assignee_id: str | None
    team_id: str | None
    lifecycle_version: int
    audit_id: str | None
    review_ids: tuple[str, ...]
    failure_ids: tuple[str, ...]
    order_notifications: tuple[CapturedOrderNotificationRule, ...]


@dataclass
class _ParticipantFence:
    transaction: object
    selection: _ParticipantSelection
    memberships: dict[str, CompanyMembership]
    context: SessionContext | None
    include_order_notifications: bool


def _select_participants(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    actor_membership_id: str | None,
    include_order_notifications: bool = False,
) -> tuple[_ParticipantSelection, SessionContext | None]:
    # Scalar discovery must not reuse a cached parent or flush caller-owned writes.
    row = session.execute(
        select(
            Matter.assignee_membership_id,
            Matter.team_id,
            Matter.lifecycle_version,
        ).where(Matter.id == matter_id, Matter.company_id == company_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(404, detail="Matter not found.")
    parent = Matter(
        id=matter_id, company_id=company_id, assignee_membership_id=row[0], team_id=row[1]
    )
    context = _select_notification_context(
        session,
        company_id=company_id,
        actor_membership_id=actor_membership_id,
    )
    return _ParticipantSelection(
        row[0],
        row[1],
        row[2],
        context.membership.id if context else None,
        tuple(
            sorted(member.id for member in _select_recipient_memberships(session, matter=parent))
        ),
        tuple(
            sorted(
                member.id
                for member in _select_recipient_memberships(
                    session,
                    matter=parent,
                    include_admins=True,
                )
            )
        ),
        _select_order_notifications(session, matter=parent) if include_order_notifications else (),
    ), context


def _validate_live_context(
    session: Session,
    *,
    context: SessionContext,
    actor_membership_id: str | None,
    required_capability: str | None,
    memberships: dict[str, CompanyMembership],
) -> None:
    from caseops_api.services.identity import get_session_context

    if context.membership.id != actor_membership_id or required_capability is None:
        raise RuntimeError("Live compliance authority requires the request actor and capability.")
    actor = require_locked_membership_capability(
        session,
        memberships[context.membership.id],
        required_capability,
    )
    fresh = get_session_context(session, actor.id, token_issued_at=context.token_issued_at)
    context.company, context.membership, context.user = fresh.company, actor, actor.user


def lock_compliance_participants(
    session: Session,
    *,
    company_id: str,
    matter_id: str,
    actor_membership_id: str | None,
    context: SessionContext | None = None,
    required_capability: str | None = None,
    expected_lifecycle_version: int | None = None,
    include_order_notifications: bool = False,
) -> None:
    """Enter before source/parent locks; never expand a captured set behind them.

    Creator provenance (including null and inactive historical IDs) is distinct
    from live request authority and the existing notification-context election.
    Every commit invalidates this fence. Locks retain the assignment helper's
    existing strength and its Membership-then-User ordering.
    """
    key = (company_id, matter_id, actor_membership_id)
    fences = session.info.setdefault("compliance_participants", {})
    previous = fences.get(key)
    if previous is not None and previous.transaction is session.get_transaction():
        if include_order_notifications and not previous.include_order_notifications:
            raise RuntimeError(
                "Order notification participants must be captured before parent locks."
            )
        parent = session.get(Matter, matter_id)
        _participant_fence(session, matter=parent, actor_membership_id=actor_membership_id)
        if expected_lifecycle_version is not None and (
            previous.selection.lifecycle_version != expected_lifecycle_version
        ):
            raise ComplianceParticipantFenceError(
                409, detail={"code": "compliance_participants_changed"}
            )
        if context is not None:
            _validate_live_context(
                session,
                context=context,
                actor_membership_id=actor_membership_id,
                required_capability=required_capability,
                memberships=previous.memberships,
            )
            assert_access(session, context=context, matter=parent, commit_denial=False)
        return
    with session.no_autoflush:
        lock_matter_private_authority(session, company_id=company_id)
        company = session.get(Company, company_id)
        if company is None or not company.is_active:
            raise HTTPException(403, detail="The current workspace is no longer active.")
        selection, elected = _select_participants(
            session,
            company_id=company_id,
            matter_id=matter_id,
            actor_membership_id=actor_membership_id,
            include_order_notifications=include_order_notifications,
        )
        ids = set(selection.review_ids) | set(selection.failure_ids)
        ids.update(
            member_id for rule in selection.order_notifications for member_id in rule.recipient_ids
        )
        ids.update(
            value
            for value in (actor_membership_id, selection.audit_id, selection.assignee_id)
            if value
        )
        _check_participant_bound(ids)
        memberships = lock_company_memberships_for_assignment(
            session,
            company_id=company_id,
            membership_ids=ids,
        )
        if set(memberships) != ids:
            raise ComplianceParticipantFenceError(
                409,
                detail={"code": "compliance_participants_changed"},
            )
        if context is not None:
            _validate_live_context(
                session,
                context=context,
                actor_membership_id=actor_membership_id,
                required_capability=required_capability,
                memberships=memberships,
            )
        parent = session.scalar(
            select(Matter)
            .where(
                Matter.id == matter_id,
                Matter.company_id == company_id,
            )
            .with_for_update(of=Matter)
            .execution_options(populate_existing=True)
        )
        if context is not None:
            assert_access(session, context=context, matter=parent, commit_denial=False)
        current, elected = _select_participants(
            session,
            company_id=company_id,
            matter_id=matter_id,
            actor_membership_id=actor_membership_id,
            include_order_notifications=include_order_notifications,
        )
        if current != selection or (
            expected_lifecycle_version is not None
            and current.lifecycle_version != expected_lifecycle_version
        ):
            raise ComplianceParticipantFenceError(
                409,
                detail={"code": "compliance_participants_changed"},
            )
        fences[key] = _ParticipantFence(
            session.get_transaction(),
            current,
            memberships,
            elected,
            include_order_notifications,
        )


def _participant_fence(
    session: Session,
    *,
    matter: Matter,
    actor_membership_id: str | None,
) -> _ParticipantFence:
    fence = session.info.get("compliance_participants", {}).get(
        (matter.company_id, matter.id, actor_membership_id),
    )
    if fence is None or fence.transaction is not session.get_transaction():
        raise RuntimeError("Compliance participant fence must precede parent locks and writes.")
    with session.no_autoflush:
        current, _ = _select_participants(
            session,
            company_id=matter.company_id,
            matter_id=matter.id,
            actor_membership_id=actor_membership_id,
            include_order_notifications=fence.include_order_notifications,
        )
    if current != fence.selection:
        raise ComplianceParticipantFenceError(
            409, detail={"code": "compliance_participants_changed"}
        )
    return fence


def captured_order_notification_recipients(
    session: Session,
    *,
    matter: Matter,
    actor_membership_id: str,
) -> list[tuple[CapturedOrderNotificationRule, list[CompanyMembership]]]:
    fence = _participant_fence(session, matter=matter, actor_membership_id=actor_membership_id)
    if not fence.include_order_notifications:
        raise RuntimeError("Order notification participants were not captured before parent locks.")
    return [
        (rule, [fence.memberships[member_id] for member_id in rule.recipient_ids])
        for rule in fence.selection.order_notifications
    ]


def _notification_context(
    session: Session,
    *,
    matter: Matter,
    actor_membership_id: str | None,
) -> SessionContext | None:
    return _participant_fence(
        session, matter=matter, actor_membership_id=actor_membership_id
    ).context


def _recipient_memberships(
    session: Session,
    *,
    matter: Matter,
    actor_membership_id: str | None,
    include_admins: bool = False,
) -> list[CompanyMembership]:
    fence = _participant_fence(session, matter=matter, actor_membership_id=actor_membership_id)
    ids = fence.selection.failure_ids if include_admins else fence.selection.review_ids
    return [fence.memberships[member_id] for member_id in ids]
