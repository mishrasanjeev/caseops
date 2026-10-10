from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from caseops_api.db.models import (
    CompanyMembership,
    Matter,
    MembershipRole,
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    NotificationRule,
    NotificationRuleScopeType,
    User,
)
from caseops_api.schemas.calendar import (
    NotificationRuleCreateRequest,
    NotificationRuleListResponse,
    NotificationRuleRecord,
    NotificationRuleUpdateRequest,
)
from caseops_api.services.assignment_memberships import lock_company_memberships_for_assignment
from caseops_api.services.audit import record_from_context
from caseops_api.services.compliance_participants import captured_order_notification_recipients
from caseops_api.services.matter_access import assert_access
from caseops_api.services.matter_operational_guard import require_operational_matter
from caseops_api.services.matter_write_fence import lock_matter_private_authority
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)
from caseops_api.services.session_context import SessionContext

_CHANNELS = {"in_app", "email", "sms", "whatsapp"}


def _lock_rule_authority(session: Session, context: SessionContext) -> None:
    from caseops_api.services.identity import get_session_context

    # Policy writers share the capture admission, including new-rule phantoms.
    lock_matter_private_authority(session, company_id=context.company.id)
    members = lock_company_memberships_for_assignment(
        session, company_id=context.company.id, membership_ids=[context.membership.id],
    )
    fresh = get_session_context(
        session, context.membership.id, token_issued_at=context.token_issued_at,
    )
    actor = members.get(context.membership.id)
    if actor is None or actor.role not in (MembershipRole.OWNER, MembershipRole.ADMIN):
        raise HTTPException(403, detail="Managing notification rules requires an admin or owner.")
    context.company, context.membership, context.user = fresh.company, actor, actor.user


def _channels(value: Iterable[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in value or ["in_app"]:
        channel = str(raw).strip()
        if channel not in _CHANNELS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported notification channel: {channel}",
            )
        if channel not in seen:
            cleaned.append(channel)
            seen.add(channel)
    if not cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Notification rules require at least one channel.",
        )
    return cleaned


def _record(rule: NotificationRule) -> NotificationRuleRecord:
    return NotificationRuleRecord(
        id=rule.id,
        company_id=rule.company_id,
        scope_type=rule.scope_type,  # type: ignore[arg-type]
        scope_id=rule.scope_id,
        event_type=rule.event_type,  # type: ignore[arg-type]
        channels=_channels(rule.channels_json),
        offset_minutes=rule.offset_minutes,
        enabled=rule.enabled,
        created_by_membership_id=rule.created_by_membership_id,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _scope_snapshot(rule: NotificationRule) -> dict[str, object | None]:
    return {
        "scope_type": rule.scope_type,
        "scope_id": rule.scope_id,
        "event_type": rule.event_type,
        "channels": list(rule.channels_json or []),
        "offset_minutes": rule.offset_minutes,
        "enabled": rule.enabled,
    }


def _validate_scope(
    session: Session,
    *,
    context: SessionContext,
    scope_type: str,
    scope_id: str | None,
) -> None:
    if scope_type == NotificationRuleScopeType.COMPANY:
        if scope_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Company scoped notification rules must not set scope_id.",
            )
        return
    if scope_type == NotificationRuleScopeType.MATTER:
        if not scope_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Matter scoped notification rules require scope_id.",
            )
        matter = session.scalar(
            select(Matter).where(
                Matter.id == scope_id,
                Matter.company_id == context.company.id,
            )
        )
        if matter is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Matter not found.",
            )
        assert_access(session, context=context, matter=matter)
        return
    if scope_type == NotificationRuleScopeType.USER:
        if not scope_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User scoped notification rules require scope_id.",
            )
        membership = session.scalar(
            select(CompanyMembership)
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.id == scope_id,
                CompanyMembership.company_id == context.company.id,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Active user membership not found.",
            )
        return
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported notification rule scope.",
    )


def _lock_operational_matter_scopes(
    session: Session,
    *,
    context: SessionContext,
    scope_ids: Iterable[str | None],
    operation: str,
) -> None:
    """Authorize and lock all affected Matter parents before rule writes."""

    for scope_id in sorted({scope_id for scope_id in scope_ids if scope_id}):
        matter = session.scalar(
            select(Matter).where(
                Matter.id == scope_id,
                Matter.company_id == context.company.id,
            )
        )
        if matter is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Matter not found.",
            )
        assert_access(session, context=context, matter=matter)
        require_operational_matter(
            session,
            matter=matter,
            operation=operation,
        )


def list_notification_rules(
    session: Session,
    *,
    context: SessionContext,
) -> NotificationRuleListResponse:
    rows = list(
        session.scalars(
            select(NotificationRule)
            .where(NotificationRule.company_id == context.company.id)
            .order_by(NotificationRule.created_at.desc())
        )
    )
    return NotificationRuleListResponse(rules=[_record(row) for row in rows])


def create_notification_rule(
    session: Session,
    *,
    context: SessionContext,
    payload: NotificationRuleCreateRequest,
) -> NotificationRuleRecord:
    _lock_rule_authority(session, context)
    _validate_scope(
        session,
        context=context,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
    )
    if payload.scope_type == NotificationRuleScopeType.MATTER:
        _lock_operational_matter_scopes(
            session,
            context=context,
            scope_ids=[payload.scope_id],
            operation="create a notification rule for this matter",
        )
    rule = NotificationRule(
        company_id=context.company.id,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        event_type=payload.event_type,
        channels_json=_channels(payload.channels),
        offset_minutes=payload.offset_minutes,
        enabled=payload.enabled,
        created_by_membership_id=context.membership.id,
    )
    session.add(rule)
    session.flush()
    record_from_context(
        session,
        context,
        action="notification_rule.created",
        target_type="notification_rule",
        target_id=rule.id,
        metadata=_scope_snapshot(rule),
    )
    session.commit()
    return _record(rule)


def update_notification_rule(
    session: Session,
    *,
    context: SessionContext,
    rule_id: str,
    payload: NotificationRuleUpdateRequest,
) -> NotificationRuleRecord:
    _lock_rule_authority(session, context)
    rule = session.scalar(
        select(NotificationRule).where(
            NotificationRule.id == rule_id,
            NotificationRule.company_id == context.company.id,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification rule not found.",
        )
    before = _scope_snapshot(rule)
    fields_set = payload.model_fields_set
    merged = {
        "scope_type": payload.scope_type or rule.scope_type,
        "scope_id": payload.scope_id if "scope_id" in fields_set else rule.scope_id,
        "event_type": payload.event_type or rule.event_type,
        "channels": _channels(payload.channels or rule.channels_json),
        "offset_minutes": (
            rule.offset_minutes
            if "offset_minutes" not in fields_set
            else payload.offset_minutes
        ),
        "enabled": (
            rule.enabled
            if "enabled" not in fields_set
            else bool(payload.enabled)
        ),
    }
    normalized = NotificationRuleCreateRequest(**merged)
    _validate_scope(
        session,
        context=context,
        scope_type=normalized.scope_type,
        scope_id=normalized.scope_id,
    )
    matter_scope_ids = []
    if rule.scope_type == NotificationRuleScopeType.MATTER:
        matter_scope_ids.append(rule.scope_id)
    if normalized.scope_type == NotificationRuleScopeType.MATTER:
        matter_scope_ids.append(normalized.scope_id)
    if matter_scope_ids:
        _lock_operational_matter_scopes(
            session,
            context=context,
            scope_ids=matter_scope_ids,
            operation="update a notification rule for this matter",
        )
    rule.scope_type = normalized.scope_type
    rule.scope_id = normalized.scope_id
    rule.event_type = normalized.event_type
    rule.channels_json = _channels(normalized.channels)
    rule.offset_minutes = normalized.offset_minutes
    rule.enabled = normalized.enabled
    session.add(rule)
    record_from_context(
        session,
        context,
        action="notification_rule.updated",
        target_type="notification_rule",
        target_id=rule.id,
        metadata={"before": before, "after": _scope_snapshot(rule)},
    )
    session.commit()
    return _record(rule)


def delete_notification_rule(
    session: Session,
    *,
    context: SessionContext,
    rule_id: str,
) -> None:
    _lock_rule_authority(session, context)
    rule = session.scalar(
        select(NotificationRule).where(
            NotificationRule.id == rule_id,
            NotificationRule.company_id == context.company.id,
        )
    )
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification rule not found.",
        )
    before = _scope_snapshot(rule)
    record_from_context(
        session,
        context,
        action="notification_rule.deleted",
        target_type="notification_rule",
        target_id=rule.id,
        metadata={"before": before},
    )
    session.execute(
        delete(NotificationRule).where(
            NotificationRule.id == rule.id,
            NotificationRule.company_id == context.company.id,
        )
    )
    session.commit()


def create_new_order_uploaded_notifications(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    attachment_id: str,
    linked_court_order_id: str,
) -> int:
    """Create durable notification delivery intents for LW-S10.

    In-app intents are processed transactionally. External channels are owned
    exclusively by the durable intent queue: the worker either dispatches
    through the approved provider or creates one in-app fallback. The legacy
    direct-send path is never called here.
    """

    selections = captured_order_notification_recipients(
        session, matter=matter, actor_membership_id=context.membership.id,
    )
    created = 0
    seen: set[tuple[str, str, str]] = set()
    for rule, recipients in selections:
        channels = _channels(rule.channels)
        for membership in recipients:
            for channel in channels:
                key = (membership.id, rule.event_type, channel)
                if key in seen:
                    continue
                seen.add(key)
                intent = enqueue_notification_delivery_intent(
                    session,
                    context=context,
                    recipient_membership=membership,
                    channel=channel,
                    event_type=rule.event_type,
                    source_type="matter_attachment",
                    source_id=attachment_id,
                    matter=matter,
                    notification_rule_id=rule.id,
                    title="New order uploaded",
                    body=(
                        f"{matter.matter_code}: a linked court order document was uploaded."
                    ),
                    linked_court_order_id=linked_court_order_id,
                )
                if intent is None or channel != NotificationDeliveryChannel.IN_APP:
                    continue
                before_status = intent.status
                before_attempts = intent.attempts
                result = process_notification_delivery_intent(
                    session,
                    intent_id=intent.id,
                    context=context,
                )
                if (
                    result.delivered
                    and before_status != NotificationDeliveryStatus.DELIVERED
                    and before_attempts == 0
                ):
                    created += 1
    return created


__all__ = [
    "create_new_order_uploaded_notifications",
    "create_notification_rule",
    "delete_notification_rule",
    "list_notification_rules",
    "update_notification_rule",
]
