from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from caseops_api.db.models import (
    Company,
    CompanyMembership,
    Matter,
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    NotificationRule,
    NotificationRuleEventType,
    NotificationRuleScopeType,
    User,
)
from caseops_api.schemas.calendar import (
    NotificationRuleCreateRequest,
    NotificationRuleListResponse,
    NotificationRuleRecord,
    NotificationRuleUpdateRequest,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.identity import SessionContext
from caseops_api.services.matter_access import assert_access, can_access
from caseops_api.services.notification_delivery import (
    enqueue_notification_delivery_intent,
    process_notification_delivery_intent,
)

_CHANNELS = {"in_app", "email", "sms", "whatsapp"}


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
    _validate_scope(
        session,
        context=context,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
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


def _active_memberships(session: Session, company_id: str) -> list[CompanyMembership]:
    return list(
        session.scalars(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user), joinedload(CompanyMembership.company))
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.company_id == company_id,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
    )


def _recipient_context(
    *,
    company: Company,
    membership: CompanyMembership,
) -> SessionContext:
    return SessionContext(company=company, user=membership.user, membership=membership)


def _eligible_recipients(
    session: Session,
    *,
    actor_context: SessionContext,
    rule: NotificationRule,
    matter: Matter,
) -> list[CompanyMembership]:
    if rule.scope_type == NotificationRuleScopeType.USER:
        membership = session.scalar(
            select(CompanyMembership)
            .options(joinedload(CompanyMembership.user), joinedload(CompanyMembership.company))
            .join(User, User.id == CompanyMembership.user_id)
            .where(
                CompanyMembership.id == rule.scope_id,
                CompanyMembership.company_id == actor_context.company.id,
                CompanyMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        candidates = [membership] if membership is not None else []
    else:
        candidates = _active_memberships(session, actor_context.company.id)

    recipients: list[CompanyMembership] = []
    for membership in candidates:
        assert membership is not None
        # Owners may see all matters via the access helper; other roles remain
        # bound by restricted access, team scoping, grants, and ethical walls.
        recipient_context = _recipient_context(
            company=actor_context.company,
            membership=membership,
        )
        if can_access(session, context=recipient_context, matter=matter):
            recipients.append(membership)
    return recipients


def create_new_order_uploaded_notifications(
    session: Session,
    *,
    context: SessionContext,
    matter: Matter,
    attachment_id: str,
    linked_court_order_id: str,
) -> int:
    """Create durable notification delivery intents for LW-S10.

    In-app intents are processed transactionally into existing
    ``InAppNotification`` rows. External email/SMS/WhatsApp channels are
    fail-closed into durable blocked intents until provider policy,
    credentials, and runbooks are approved separately.
    """

    rules = list(
        session.scalars(
            select(NotificationRule).where(
                NotificationRule.company_id == context.company.id,
                NotificationRule.enabled.is_(True),
                NotificationRule.event_type == NotificationRuleEventType.NEW_ORDER_UPLOADED,
            )
        )
    )
    created = 0
    seen: set[tuple[str, str, str]] = set()
    for rule in rules:
        if rule.scope_type == NotificationRuleScopeType.MATTER and rule.scope_id != matter.id:
            continue
        channels = _channels(rule.channels_json)
        recipients = _eligible_recipients(
            session,
            actor_context=context,
            rule=rule,
            matter=matter,
        )
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
                    title=(
                        "New order uploaded"
                        if channel == NotificationDeliveryChannel.IN_APP
                        else None
                    ),
                    body=(
                        f"{matter.matter_code}: a linked court order document was uploaded."
                        if channel == NotificationDeliveryChannel.IN_APP
                        else None
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
