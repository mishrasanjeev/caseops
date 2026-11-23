from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    NotificationDigestFrequency,
    NotificationPhoneContact,
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
from caseops_api.schemas.phone_channels import PhoneConsentRequest
from caseops_api.services.audit import record_from_context
from caseops_api.services.phone_notifications import (
    consent_active,
    phone_admission,
    set_phone_channel_consent,
)
from caseops_api.services.phone_providers import phone_channel_readiness
from caseops_api.services.session_context import SessionContext

_CHANNELS = ("in_app", "email", "sms", "whatsapp")
_PHONE_CHANNELS = ("sms", "whatsapp")


def _provider_configured() -> dict[str, bool]:
    settings = get_settings()
    return {
        "in_app": True,
        "email": bool(settings.sendgrid_api_key and settings.sendgrid_sender_email),
        "sms": phone_channel_readiness("sms").ready,
        "whatsapp": phone_channel_readiness("whatsapp").ready,
    }


def _default_channels() -> dict[str, bool]:
    return {"in_app": True, "email": False, "sms": False, "whatsapp": False}


def _default_categories() -> dict[str, bool]:
    return {category: True for category in DEFAULT_EVENT_CATEGORIES}


def _quiet_hours(value: dict | None) -> NotificationQuietHours:
    if not isinstance(value, dict):
        return NotificationQuietHours()
    return NotificationQuietHours(**value)


def _channel_preferences(
    raw: dict | None,
    *,
    phone_enabled: dict[str, bool] | None = None,
    phone_deliverable: dict[str, bool] | None = None,
) -> dict[str, NotificationChannelPreference]:
    """Render channel state. SMS/WhatsApp ``enabled`` is the tenant switch for
    the tenant record and the recipient's recorded consent for the user record;
    ``external_delivery_enabled`` is true only when a send would be admitted."""

    configured = _provider_configured()
    values = {**_default_channels(), **(raw or {})}
    result: dict[str, NotificationChannelPreference] = {}
    for channel in _CHANNELS:
        if channel in _PHONE_CHANNELS:
            enabled = (
                phone_enabled[channel]
                if phone_enabled is not None
                else values.get(channel) is True
            )
            external = bool(
                phone_deliverable[channel]
                if phone_deliverable is not None
                else configured[channel] and enabled
            )
        else:
            enabled = bool(values.get(channel, False))
            external = channel == "in_app"
        result[channel] = NotificationChannelPreference(
            enabled=enabled,
            provider_configured=configured[channel],
            external_delivery_enabled=external,
        )
    return result


def _tenant_phone_channels(row: TenantNotificationPreference) -> dict[str, bool]:
    return {channel: (row.channels_json or {}).get(channel) is True for channel in _PHONE_CHANNELS}


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


def _user_record(
    session: Session, row: UserNotificationPreference
) -> NotificationPreferenceRecord:
    contact = session.scalar(
        select(NotificationPhoneContact).where(
            NotificationPhoneContact.company_id == row.company_id,
            NotificationPhoneContact.membership_id == row.membership_id,
        )
    )
    phone_enabled = {channel: consent_active(contact, channel) for channel in _PHONE_CHANNELS}
    phone_deliverable = {
        channel: phone_admission(
            session,
            company_id=row.company_id,
            membership_id=row.membership_id,
            channel=channel,
        ).allowed
        for channel in _PHONE_CHANNELS
    }
    return NotificationPreferenceRecord(
        id=row.id,
        company_id=row.company_id,
        membership_id=row.membership_id,
        scope="user",
        channels=_channel_preferences(
            row.channels_json,
            phone_enabled=phone_enabled,
            phone_deliverable=phone_deliverable,
        ),
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
        user=_user_record(session, user),
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
    before = _tenant_phone_channels(row)
    _apply_update(row, payload, tenant=True)
    session.add(row)
    after = _tenant_phone_channels(row)
    record_from_context(
        session,
        context,
        action="notification_preferences.tenant_updated",
        target_type="tenant_notification_preference",
        target_id=row.id,
        metadata={
            "external_delivery_enabled": False,
            "phone_channels_enabled": after,
            "phone_channels_changed": sorted(c for c in _PHONE_CHANNELS if before[c] != after[c]),
        },
    )
    session.commit()
    return notification_preferences(session, context=context)


def update_user_notification_preferences(
    session: Session,
    *,
    context: SessionContext,
    payload: NotificationPreferenceUpdateRequest,
) -> NotificationPreferenceResponse:
    phone_changes = {
        channel: value
        for channel, value in (payload.channels or {}).items()
        if channel in _PHONE_CHANNELS
    }
    if any(phone_changes.values()):
        # Turning a phone channel on is consent; it needs a verified number and
        # the consent wording, which only the phone opt-in flow captures.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "phone_consent_requires_verification",
                "message": "Turn on SMS or WhatsApp from the mobile number section, "
                "after verifying your number.",
            },
        )
    if payload.channels is not None:
        payload = payload.model_copy(
            update={
                "channels": {
                    channel: value
                    for channel, value in payload.channels.items()
                    if channel not in _PHONE_CHANNELS
                }
            }
        )
    for channel in phone_changes:
        # Turning a phone channel off is an opt-out and is always honoured.
        set_phone_channel_consent(
            session,
            context=context,
            payload=PhoneConsentRequest(channel=channel, opted_in=False),
        )
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
