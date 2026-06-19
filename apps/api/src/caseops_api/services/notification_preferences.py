from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    NotificationDigestFrequency,
    TenantNotificationPreference,
    UserNotificationPreference,
)
from caseops_api.schemas.notification_preferences import (
    DEFAULT_EVENT_CATEGORIES,
    NotificationChannelPreference,
    NotificationPreferenceRecord,
    NotificationPreferenceResponse,
    NotificationPreferenceUpdateRequest,
    NotificationQuietHours,
)
from caseops_api.services.audit import record_from_context
from caseops_api.services.session_context import SessionContext

_CHANNELS = ("in_app", "email", "sms", "whatsapp")


def _provider_configured() -> dict[str, bool]:
    settings = get_settings()
    return {
        "in_app": True,
        "email": bool(settings.sendgrid_api_key and settings.sendgrid_sender_email),
        "sms": bool(
            settings.twilio_enabled
            and settings.twilio_account_sid
            and settings.twilio_auth_token
            and settings.twilio_from_number
        ),
        "whatsapp": bool(
            settings.whatsapp_enabled
            and settings.whatsapp_access_token
            and settings.whatsapp_phone_number_id
            and settings.whatsapp_template_name
        ),
    }


def _default_channels() -> dict[str, bool]:
    return {"in_app": True, "email": False, "sms": False, "whatsapp": False}


def _default_categories() -> dict[str, bool]:
    return {category: True for category in DEFAULT_EVENT_CATEGORIES}


def _quiet_hours(value: dict | None) -> NotificationQuietHours:
    if not isinstance(value, dict):
        return NotificationQuietHours()
    return NotificationQuietHours(**value)


def _channel_preferences(raw: dict | None) -> dict[str, NotificationChannelPreference]:
    configured = _provider_configured()
    values = {**_default_channels(), **(raw or {})}
    result: dict[str, NotificationChannelPreference] = {}
    for channel in _CHANNELS:
        external = channel != "in_app"
        result[channel] = NotificationChannelPreference(
            enabled=bool(values.get(channel, False)),
            provider_configured=configured[channel],
            external_delivery_enabled=False if external else True,
        )
    return result


def _tenant_row(session: Session, *, context: SessionContext) -> TenantNotificationPreference:
    row = session.scalar(
        select(TenantNotificationPreference).where(
            TenantNotificationPreference.company_id == context.company.id
        )
    )
    if row is None:
        row = TenantNotificationPreference(
            company_id=context.company.id,
            channels_json=_default_channels(),
            event_categories_json=_default_categories(),
            digest_frequency=NotificationDigestFrequency.IMMEDIATE,
            quiet_hours_json=NotificationQuietHours().model_dump(),
            escalation_rules_json=[],
            external_delivery_policy="disabled_until_configured",
        )
        session.add(row)
        session.flush()
    return row


def _user_row(session: Session, *, context: SessionContext) -> UserNotificationPreference:
    row = session.scalar(
        select(UserNotificationPreference).where(
            UserNotificationPreference.company_id == context.company.id,
            UserNotificationPreference.membership_id == context.membership.id,
        )
    )
    if row is None:
        row = UserNotificationPreference(
            company_id=context.company.id,
            membership_id=context.membership.id,
            channels_json=_default_channels(),
            event_categories_json=_default_categories(),
            digest_frequency=NotificationDigestFrequency.IMMEDIATE,
            quiet_hours_json=NotificationQuietHours().model_dump(),
            escalation_rules_json=[],
            opt_out_categories_json=[],
        )
        session.add(row)
        session.flush()
    return row


def _tenant_record(row: TenantNotificationPreference) -> NotificationPreferenceRecord:
    return NotificationPreferenceRecord(
        id=row.id,
        company_id=row.company_id,
        membership_id=None,
        scope="tenant",
        channels=_channel_preferences(row.channels_json),
        event_categories={**_default_categories(), **(row.event_categories_json or {})},
        digest_frequency=row.digest_frequency,  # type: ignore[arg-type]
        quiet_hours=_quiet_hours(row.quiet_hours_json),
        escalation_rules=list(row.escalation_rules_json or []),
        opt_out_categories=[],
        external_delivery_policy=row.external_delivery_policy,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _user_record(row: UserNotificationPreference) -> NotificationPreferenceRecord:
    return NotificationPreferenceRecord(
        id=row.id,
        company_id=row.company_id,
        membership_id=row.membership_id,
        scope="user",
        channels=_channel_preferences(row.channels_json),
        event_categories={**_default_categories(), **(row.event_categories_json or {})},
        digest_frequency=row.digest_frequency,  # type: ignore[arg-type]
        quiet_hours=_quiet_hours(row.quiet_hours_json),
        escalation_rules=list(row.escalation_rules_json or []),
        opt_out_categories=list(row.opt_out_categories_json or []),
        external_delivery_policy="disabled_until_configured",
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def notification_preferences(
    session: Session,
    *,
    context: SessionContext,
) -> NotificationPreferenceResponse:
    tenant = _tenant_row(session, context=context)
    user = _user_row(session, context=context)
    return NotificationPreferenceResponse(
        tenant=_tenant_record(tenant),
        user=_user_record(user),
        external_delivery_enabled=False,
        provider_configured=_provider_configured(),  # type: ignore[arg-type]
    )


def update_tenant_notification_preferences(
    session: Session,
    *,
    context: SessionContext,
    payload: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceResponse:
    row = _tenant_row(session, context=context)
    _apply_update(row, payload, tenant=True)
    session.add(row)
    record_from_context(
        session,
        context,
        action="notification_preferences.tenant_updated",
        target_type="tenant_notification_preference",
        target_id=row.id,
        metadata={"external_delivery_enabled": False},
    )
    session.commit()
    return notification_preferences(session, context=context)


def update_user_notification_preferences(
    session: Session,
    *,
    context: SessionContext,
    payload: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceResponse:
    row = _user_row(session, context=context)
    _apply_update(row, payload, tenant=False)
    session.add(row)
    record_from_context(
        session,
        context,
        action="notification_preferences.user_updated",
        target_type="user_notification_preference",
        target_id=row.id,
        metadata={"external_delivery_enabled": False},
    )
    session.commit()
    return notification_preferences(session, context=context)


def _apply_update(
    row: TenantNotificationPreference | UserNotificationPreference,
    payload: NotificationPreferenceUpdateRequest,
    *,
    tenant: bool,
) -> None:
    if payload.channels is not None:
        row.channels_json = {**(row.channels_json or _default_channels()), **payload.channels}
    if payload.event_categories is not None:
        row.event_categories_json = {
            **(row.event_categories_json or _default_categories()),
            **payload.event_categories,
        }
    if payload.digest_frequency is not None:
        row.digest_frequency = payload.digest_frequency
    if payload.quiet_hours is not None:
        row.quiet_hours_json = payload.quiet_hours.model_dump()
    if payload.escalation_rules is not None:
        row.escalation_rules_json = payload.escalation_rules
    if not tenant and payload.opt_out_categories is not None:
        row.opt_out_categories_json = payload.opt_out_categories
