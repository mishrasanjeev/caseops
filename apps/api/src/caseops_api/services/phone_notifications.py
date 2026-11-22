"""Opt-in SMS and WhatsApp delivery for reminders and alerts.

Every phone send must pass, in order and again at dispatch time:

1. the global kill switch and full provider configuration
   (:func:`phone_providers.phone_channel_readiness`);
2. the workspace admin's enablement of that channel (tenant preferences);
3. a verified number for the recipient membership in this workspace;
4. a timestamped, un-withdrawn consent for that channel;
5. the automated-test/no-paid fence, a verified per-message cost and the
   tenant's provider monthly budget.

Message bodies are never composed here. Providers receive an approved
template id plus at most four short variables (Matter code, hearing date,
time and court), so privileged Matter content cannot leave the workspace.
"""

from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from caseops_api.core.settings import get_settings
from caseops_api.db.models import (
    AuditActorType,
    AuditResult,
    BillingSubscription,
    Company,
    CompanyMembership,
    MatterHearing,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
    NotificationDeliveryStatus,
    NotificationPhoneContact,
    ProviderCostCategory,
    TenantNotificationPreference,
)
from caseops_api.schemas.phone_channels import (
    E164_PATTERN,
    PHONE_CONSENT_TEXT_VERSION,
    PhoneChannelAdminRecord,
    PhoneChannelAdminResponse,
    PhoneChannelConsentRecord,
    PhoneConsentRequest,
    PhoneContactStatusResponse,
    PhoneSendResult,
    PhoneTemplateMessage,
    PhoneVerificationConfirmRequest,
    PhoneVerificationStartRequest,
)
from caseops_api.services.audit import record_audit, record_from_context
from caseops_api.services.durable_workflows import redact_identifier
from caseops_api.services.paid_provider_safety import (
    assert_paid_provider_call_allowed,
    paid_provider_block_reason,
)
from caseops_api.services.phone_providers import (
    PHONE_CHANNELS,
    PROVIDER_KEY_BY_CHANNEL,
    phone_channel_readiness,
    phone_transport_is_injected,
    send_phone_template,
    template_reference,
)
from caseops_api.services.provider_costs import verified_actual_cost_minor
from caseops_api.services.session_context import SessionContext

VERIFICATION_CODE_TTL = timedelta(minutes=10)
VERIFICATION_RESEND_COOLDOWN = timedelta(seconds=60)
VERIFICATION_MAX_ATTEMPTS = 5
# DLT registers each template variable with a 30-character ceiling.
TEMPLATE_VARIABLE_MAX_LENGTH = 30
_COST_CATEGORY = {"sms": ProviderCostCategory.SMS, "whatsapp": ProviderCostCategory.WHATSAPP}
_STOP_WORDS = frozenset({"stop", "stop all", "unsubscribe", "opt out", "optout", "cancel"})


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def normalize_phone_number(raw: str) -> str:
    """Return E.164 (``+<digits>``); a bare 10-digit Indian mobile gets +91."""

    cleaned = re.sub(r"[\s().-]", "", str(raw or ""))
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if re.fullmatch(r"[6-9][0-9]{9}", cleaned):
        cleaned = "+91" + cleaned
    if not re.fullmatch(E164_PATTERN, cleaned):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "phone_number_invalid",
                "message": "Enter a mobile number in international format, for example "
                "+91 98123 45678.",
            },
        )
    return cleaned


def mask_phone_number(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:3]} ••••• {phone[-4:]}"


def phone_fingerprint(phone: str | None) -> str | None:
    return redact_identifier(phone)


def _consent_fields(channel: str) -> tuple[str, str]:
    return f"{channel}_consent_at", f"{channel}_opted_out_at"


def consent_active(contact: NotificationPhoneContact | None, channel: str) -> bool:
    if contact is None or contact.verified_at is None:
        return False
    consent_field, opt_out_field = _consent_fields(channel)
    return getattr(contact, consent_field) is not None and getattr(contact, opt_out_field) is None


def tenant_phone_channel_enabled(session: Session, *, company_id: str, channel: str) -> bool:
    channels = session.scalar(
        select(TenantNotificationPreference.channels_json).where(
            TenantNotificationPreference.company_id == company_id
        )
    )
    return isinstance(channels, dict) and channels.get(channel) is True


def _contact(
    session: Session, *, company_id: str, membership_id: str, lock: bool = False
) -> NotificationPhoneContact | None:
    query = select(NotificationPhoneContact).where(
        NotificationPhoneContact.company_id == company_id,
        NotificationPhoneContact.membership_id == membership_id,
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return session.scalar(query)


@dataclass(frozen=True, slots=True)
class PhoneAdmission:
    allowed: bool
    reason: str | None
    phone_number: str | None


def phone_admission(
    session: Session,
    *,
    company_id: str,
    membership_id: str | None,
    channel: str,
) -> PhoneAdmission:
    """The single consent/configuration gate used at enqueue and at dispatch."""

    readiness = phone_channel_readiness(channel)
    if not readiness.ready:
        return PhoneAdmission(False, readiness.reason, None)
    if not tenant_phone_channel_enabled(session, company_id=company_id, channel=channel):
        return PhoneAdmission(False, "workspace_channel_disabled", None)
    if membership_id is None:
        return PhoneAdmission(False, "phone_requires_workspace_member", None)
    contact = _contact(session, company_id=company_id, membership_id=membership_id)
    if contact is None:
        return PhoneAdmission(False, "phone_not_registered", None)
    if contact.verified_at is None:
        return PhoneAdmission(False, "phone_not_verified", None)
    consent_field, opt_out_field = _consent_fields(channel)
    if getattr(contact, opt_out_field) is not None:
        return PhoneAdmission(False, "phone_opted_out", None)
    if getattr(contact, consent_field) is None:
        return PhoneAdmission(False, "phone_consent_missing", None)
    if channel == "sms" and not contact.phone_number.startswith("+91"):
        return PhoneAdmission(False, "sms_requires_indian_number", None)
    return PhoneAdmission(True, None, contact.phone_number)


# ---------------------------------------------------------------- status reads


def _channel_record(
    session: Session,
    *,
    company_id: str,
    membership_id: str,
    contact: NotificationPhoneContact | None,
    channel: str,
) -> PhoneChannelConsentRecord:
    consent_field, opt_out_field = _consent_fields(channel)
    admission = phone_admission(
        session, company_id=company_id, membership_id=membership_id, channel=channel
    )
    return PhoneChannelConsentRecord(
        channel=channel,  # type: ignore[arg-type]
        opted_in=consent_active(contact, channel),
        consent_at=getattr(contact, consent_field) if contact else None,
        opted_out_at=getattr(contact, opt_out_field) if contact else None,
        opt_out_source=contact.opt_out_source if contact else None,
        tenant_enabled=tenant_phone_channel_enabled(
            session, company_id=company_id, channel=channel
        ),
        provider_ready=phone_channel_readiness(channel).ready,
        deliverable=admission.allowed,
        blocked_reason=admission.reason,
    )


def phone_contact_status(
    session: Session, *, context: SessionContext
) -> PhoneContactStatusResponse:
    company_id, membership_id = context.company.id, context.membership.id
    contact = _contact(session, company_id=company_id, membership_id=membership_id)
    expires_at = _as_utc(contact.verification_expires_at) if contact else None
    pending = bool(
        contact is not None
        and contact.verification_code_hash
        and expires_at is not None
        and expires_at > _now()
    )
    return PhoneContactStatusResponse(
        phone_masked=mask_phone_number(contact.phone_number if contact else None),
        verified=bool(contact and contact.verified_at),
        verified_at=contact.verified_at if contact else None,
        verification_pending=pending,
        verification_channel=(
            contact.verification_channel if pending else None  # type: ignore[arg-type]
        ),
        verification_expires_at=expires_at if pending else None,
        channels={
            channel: _channel_record(
                session,
                company_id=company_id,
                membership_id=membership_id,
                contact=contact,
                channel=channel,
            )
            for channel in PHONE_CHANNELS
        },
    )


def phone_channel_admin_status(
    session: Session, *, context: SessionContext
) -> PhoneChannelAdminResponse:
    records: dict[str, PhoneChannelAdminRecord] = {}
    for channel in PHONE_CHANNELS:
        readiness = phone_channel_readiness(channel)
        consent_field, opt_out_field = _consent_fields(channel)
        opted_in = int(
            session.scalar(
                select(func.count(NotificationPhoneContact.id)).where(
                    NotificationPhoneContact.company_id == context.company.id,
                    NotificationPhoneContact.verified_at.is_not(None),
                    getattr(NotificationPhoneContact, consent_field).is_not(None),
                    getattr(NotificationPhoneContact, opt_out_field).is_(None),
                )
            )
            or 0
        )
        records[channel] = PhoneChannelAdminRecord(
            channel=channel,  # type: ignore[arg-type]
            provider=PROVIDER_KEY_BY_CHANNEL[channel],  # type: ignore[arg-type]
            tenant_enabled=tenant_phone_channel_enabled(
                session, company_id=context.company.id, channel=channel
            ),
            provider_ready=readiness.ready,
            kill_switch_active=readiness.kill_switch_active,
            transport=readiness.transport,  # type: ignore[arg-type]
            missing_configuration=list(readiness.missing),
            not_ready_reason=readiness.reason,
            opted_in_members=opted_in,
        )
    return PhoneChannelAdminResponse(channels=records)  # type: ignore[arg-type]


# ------------------------------------------------------- spend and usage


def _problem(http_status: int, code: str, message: str, **extra: object) -> HTTPException:
    return HTTPException(
        status_code=http_status, detail={"code": code, "message": message, **extra}
    )


def _verified_unit_cost(session: Session, channel: str) -> int | None:
    cost = verified_actual_cost_minor(
        session, category=_COST_CATEGORY[channel], provider=PROVIDER_KEY_BY_CHANNEL[channel]
    )
    return cost if cost is not None and cost > 0 else None


def _record_phone_usage(
    session: Session,
    *,
    company_id: str,
    membership_id: str | None,
    channel: str,
    cost_minor: int,
    source_type: str,
    source_id: str,
    matter_id: str | None = None,
) -> None:
    from caseops_api.services.saas_billing import record_usage

    subscription_id = session.scalar(
        select(BillingSubscription.id)
        .where(BillingSubscription.company_id == company_id)
        .order_by(BillingSubscription.created_at.desc())
        .limit(1)
    )
    record_usage(
        session,
        company_id=company_id,
        subscription_id=subscription_id,
        usage_type=f"{channel}_message",
        feature_key="phone_notifications",
        provider_key=PROVIDER_KEY_BY_CHANNEL[channel],
        quantity=1,
        unit="message",
        actor_membership_id=membership_id,
        matter_id=matter_id,
        estimated_cost_minor=cost_minor,
        purpose="reminder_delivery",
        display_label="SMS reminder" if channel == "sms" else "WhatsApp reminder",
        source_type=source_type,
        source_id=source_id[:120],
        metadata={"provider": PROVIDER_KEY_BY_CHANNEL[channel], "channel": channel},
    )


# ------------------------------------------------------- verification flow


def _code_hash(contact: NotificationPhoneContact, code: str) -> str:
    secret = get_settings().auth_secret.encode("utf-8")
    message = f"{contact.company_id}|{contact.membership_id}|{contact.phone_number}|{code}"
    return hmac.new(secret, message.encode("utf-8"), sha256).hexdigest()


def _audit_user(
    session: Session,
    context: SessionContext,
    *,
    action: str,
    contact: NotificationPhoneContact,
    result: str = AuditResult.SUCCESS,
    **metadata: object,
) -> None:
    record_from_context(
        session,
        context,
        action=action,
        target_type="notification_phone_contact",
        target_id=contact.id,
        result=result,
        metadata={"phone_ref": phone_fingerprint(contact.phone_number), **metadata},
    )


def start_phone_verification(
    session: Session,
    *,
    context: SessionContext,
    payload: PhoneVerificationStartRequest,
) -> PhoneContactStatusResponse:
    from caseops_api.services.provider_spend import (
        dispatch_provider_spend,
        release_provider_spend_in_session,
        reserve_provider_spend_in_session,
        settle_provider_spend,
    )

    channel = payload.channel
    phone = normalize_phone_number(payload.phone_number)
    readiness = phone_channel_readiness(channel)
    if not readiness.ready:
        raise _problem(
            status.HTTP_409_CONFLICT,
            "phone_channel_unavailable",
            "This delivery channel is not available yet; no message was sent.",
            reason=readiness.reason,
        )
    if not tenant_phone_channel_enabled(session, company_id=context.company.id, channel=channel):
        raise _problem(
            status.HTTP_409_CONFLICT,
            "workspace_channel_disabled",
            "A workspace admin has not enabled this channel; no message was sent.",
        )
    if channel == "sms" and not phone.startswith("+91"):
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "sms_requires_indian_number",
            "Text messages are sent only to Indian (+91) mobile numbers.",
        )
    if readiness.live:
        assert_paid_provider_call_allowed(
            context=context,
            provider=readiness.provider_key,
            base_url=_provider_base_url(channel),
            transport_is_mocked=phone_transport_is_injected(),
        )

    contact = _contact(
        session, company_id=context.company.id, membership_id=context.membership.id, lock=True
    )
    now = _now()
    if contact is None:
        contact = NotificationPhoneContact(
            company_id=context.company.id,
            membership_id=context.membership.id,
            phone_number=phone,
            verification_attempts=0,
        )
        session.add(contact)
        session.flush()
    elif contact.phone_number != phone:
        # A new number is a new destination: it needs its own verification and
        # fresh consent before any reminder may go to it.
        contact.phone_number = phone
        contact.verified_at = None
        contact.sms_consent_at = None
        contact.whatsapp_consent_at = None
        contact.sms_opted_out_at = None
        contact.whatsapp_opted_out_at = None
        contact.opt_out_source = None
    sent_at = _as_utc(contact.verification_sent_at)
    if sent_at is not None and now - sent_at < VERIFICATION_RESEND_COOLDOWN:
        raise _problem(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "verification_resend_cooldown",
            "Wait a minute before requesting another code.",
        )

    reservation_id: str | None = None
    cost_minor: int | None = None
    if readiness.live:
        cost_minor = _verified_unit_cost(session, channel)
        if cost_minor is None:
            raise _problem(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "provider_cost_policy",
                "The message cost has no verified price; no message was sent.",
            )
        # Same transaction as the code issue: one writer, committed together
        # before provider I/O, and a refused budget rolls the code back too.
        try:
            reservation_id = reserve_provider_spend_in_session(
                session,
                company_id=context.company.id,
                actor_membership_id=context.membership.id,
                provider_key=readiness.provider_key,
                operation_key=f"phone_verification_{channel}",
                amount_minor=cost_minor,
            )
        except HTTPException:
            session.rollback()
            raise
        # A lost response is not a refund: hold the budget through worker loss.
        dispatch_provider_spend(
            session, reservation_id=reservation_id, company_id=context.company.id
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    contact.verification_code_hash = _code_hash(contact, code)
    contact.verification_channel = channel
    contact.verification_expires_at = now + VERIFICATION_CODE_TTL
    contact.verification_attempts = 0
    contact.verification_sent_at = now
    session.add(contact)
    # No database transaction stays open across provider I/O.
    session.commit()

    message = PhoneTemplateMessage(
        channel=channel,
        to=phone,
        template="otp",
        variables=(code,),
        idempotency_key=sha256(f"{contact.id}|{now.isoformat()}".encode()).hexdigest(),
    )
    try:
        result = send_phone_template(message)
    except Exception as exc:  # noqa: BLE001 - provider/network boundary
        result = PhoneSendResult(
            outcome="outcome_unknown",
            provider=readiness.provider_key,  # type: ignore[arg-type]
            error_code="adapter_exception",
            detail=type(exc).__name__,
        )
    contact = _contact(
        session, company_id=context.company.id, membership_id=context.membership.id, lock=True
    )
    if contact is None:
        raise _problem(status.HTTP_409_CONFLICT, "phone_removed", "The number was removed.")
    reference = template_reference(channel, "otp")
    if result.outcome == "accepted":
        if reservation_id is not None and cost_minor is not None:
            _record_phone_usage(
                session,
                company_id=context.company.id,
                membership_id=context.membership.id,
                channel=channel,
                cost_minor=cost_minor,
                source_type="notification_phone_verification",
                source_id=contact.id,
            )
            settle_provider_spend(session, reservation_id=reservation_id)
        _audit_user(
            session,
            context,
            action="notification_phone.verification_sent",
            contact=contact,
            channel=channel,
            provider=result.provider,
            provider_template_id=reference["provider_template_id"],
            dlt_template_id=reference.get("dlt_template_id"),
        )
        session.commit()
        return phone_contact_status(session, context=context)
    if result.outcome == "outcome_unknown":
        # The code may still arrive. Keep it valid and keep the budget hold.
        _audit_user(
            session,
            context,
            action="notification_phone.verification_outcome_unknown",
            contact=contact,
            result=AuditResult.FAILED,
            channel=channel,
            provider=result.provider,
            error_code=result.error_code,
        )
        session.commit()
        return phone_contact_status(session, context=context)
    contact.verification_code_hash = None
    contact.verification_expires_at = None
    contact.verification_sent_at = None
    session.add(contact)
    release_provider_spend_in_session(
        session, reservation_id=reservation_id, confirmed_no_charge=True
    )
    _audit_user(
        session,
        context,
        action="notification_phone.verification_failed",
        contact=contact,
        result=AuditResult.FAILED,
        channel=channel,
        provider=result.provider,
        error_code=result.error_code,
    )
    session.commit()
    raise _problem(
        status.HTTP_502_BAD_GATEWAY,
        "phone_verification_send_failed",
        "The verification code could not be sent. Try again shortly.",
        retryable=result.outcome == "retryable_rejection",
    )


def confirm_phone_verification(
    session: Session,
    *,
    context: SessionContext,
    payload: PhoneVerificationConfirmRequest,
) -> PhoneContactStatusResponse:
    contact = _contact(
        session, company_id=context.company.id, membership_id=context.membership.id, lock=True
    )
    expires_at = _as_utc(contact.verification_expires_at) if contact else None
    if (
        contact is None
        or not contact.verification_code_hash
        or expires_at is None
        or expires_at <= _now()
    ):
        raise _problem(
            status.HTTP_409_CONFLICT,
            "verification_expired",
            "This code has expired. Request a new code.",
        )
    if contact.verification_attempts >= VERIFICATION_MAX_ATTEMPTS:
        raise _problem(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "verification_locked",
            "Too many incorrect codes. Request a new code.",
        )
    if not hmac.compare_digest(contact.verification_code_hash, _code_hash(contact, payload.code)):
        contact.verification_attempts += 1
        session.add(contact)
        _audit_user(
            session,
            context,
            action="notification_phone.verification_rejected",
            contact=contact,
            result=AuditResult.DENIED,
            attempts=contact.verification_attempts,
        )
        session.commit()
        raise _problem(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "verification_code_invalid",
            "That code is not correct.",
        )
    contact.verified_at = _now()
    contact.verification_code_hash = None
    contact.verification_expires_at = None
    contact.verification_attempts = 0
    session.add(contact)
    _audit_user(
        session,
        context,
        action="notification_phone.verified",
        contact=contact,
        channel=contact.verification_channel,
    )
    session.commit()
    return phone_contact_status(session, context=context)


def set_phone_channel_consent(
    session: Session,
    *,
    context: SessionContext,
    payload: PhoneConsentRequest,
    source: str = "user",
) -> PhoneContactStatusResponse:
    contact = _contact(
        session, company_id=context.company.id, membership_id=context.membership.id, lock=True
    )
    consent_field, opt_out_field = _consent_fields(payload.channel)
    if payload.opted_in:
        if contact is None or contact.verified_at is None:
            raise _problem(
                status.HTTP_409_CONFLICT,
                "phone_not_verified",
                "Verify your mobile number before turning this channel on.",
            )
        if payload.consent_text_version != PHONE_CONSENT_TEXT_VERSION:
            raise _problem(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "consent_text_version_required",
                "Confirm the current consent wording to turn this channel on.",
                consent_text_version=PHONE_CONSENT_TEXT_VERSION,
            )
        setattr(contact, consent_field, _now())
        setattr(contact, opt_out_field, None)
        contact.consent_text_version = PHONE_CONSENT_TEXT_VERSION
        contact.opt_out_source = None
        action = "notification_phone.consent_granted"
    else:
        if contact is None:
            return phone_contact_status(session, context=context)
        setattr(contact, opt_out_field, _now())
        contact.opt_out_source = source
        action = "notification_phone.consent_withdrawn"
    session.add(contact)
    _audit_user(
        session,
        context,
        action=action,
        contact=contact,
        channel=payload.channel,
        consent_text_version=contact.consent_text_version,
        source=source,
    )
    session.commit()
    return phone_contact_status(session, context=context)


def remove_phone_contact(
    session: Session, *, context: SessionContext
) -> PhoneContactStatusResponse:
    contact = _contact(
        session, company_id=context.company.id, membership_id=context.membership.id, lock=True
    )
    if contact is not None:
        # Consent history survives in the audit trail (without the number).
        _audit_user(session, context, action="notification_phone.removed", contact=contact)
        session.delete(contact)
        session.commit()
    return phone_contact_status(session, context=context)


# --------------------------------------------------------------- dispatch


def _provider_base_url(channel: str) -> str:
    settings = get_settings()
    return settings.msg91_api_base_url if channel == "sms" else settings.whatsapp_api_base_url


def _short(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split()) or fallback
    if len(text) > TEMPLATE_VARIABLE_MAX_LENGTH:
        text = text[: TEMPLATE_VARIABLE_MAX_LENGTH - 1].rstrip() + "…"
    return text


def template_for_intent(
    session: Session, *, intent: NotificationDeliveryIntent
) -> tuple[str, tuple[str, ...]]:
    """Choose the approved template and its minimal variables for an intent."""

    matter = intent.matter
    reference = matter.matter_code if matter is not None else (
        "IP matter" if intent.ip_docket_id else "CaseOps"
    )
    if intent.source_type == "hearing_reminder" and intent.schedule_source_type == "matter_hearing":
        hearing = session.scalar(
            select(MatterHearing).where(
                MatterHearing.id == intent.schedule_source_id,
                MatterHearing.company_id == intent.company_id,
            )
        )
        if hearing is not None:
            if hearing.time_status == "exact" and hearing.hearing_time is not None:
                when = hearing.hearing_time.strftime("%H:%M")
            else:
                when = hearing.session_label or "time not fixed"
            return "hearing_reminder", (
                _short(reference, "CaseOps"),
                hearing.hearing_on.strftime("%d %b %Y"),
                _short(when, "time not fixed"),
                _short(hearing.forum_name, "court"),
            )
    return "alert", (_short(reference, "CaseOps"),)


def _system_audit(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    action: str,
    result: str,
    **metadata: object,
) -> None:
    record_audit(
        session,
        company_id=intent.company_id,
        actor_type=AuditActorType.SYSTEM,
        actor_label="notification-delivery",
        action=action,
        target_type="notification_delivery_intent",
        target_id=intent.id,
        matter_id=intent.matter_id,
        result=result,
        metadata={
            "channel": str(intent.channel),
            "recipient_membership_ref": redact_identifier(intent.recipient_membership_id),
            "source_type": intent.source_type,
            "source_ref": redact_identifier(intent.source_id),
            **metadata,
        },
    )


def _block(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    reason: str,
    context: SessionContext | None,
):
    from caseops_api.services.notification_delivery import (
        _delivery_result,
        _ensure_in_app_fallback,
        _record_delivery_event,
    )

    intent.status = NotificationDeliveryStatus.BLOCKED
    intent.dead_letter_reason = reason
    intent.last_error_redacted = "Phone delivery is not permitted for this recipient."
    intent.failed_at = _now()
    intent.next_attempt_at = None
    session.add(intent)
    _record_delivery_event(
        session,
        intent=intent,
        event_type="delivery_blocked",
        status_value=str(intent.status),
        error=reason,
        provider=PROVIDER_KEY_BY_CHANNEL[str(intent.channel)],
    )
    _system_audit(
        session,
        intent=intent,
        action="notification_delivery.phone.blocked",
        result=AuditResult.DENIED,
        reason=reason,
    )
    session.flush()
    _ensure_in_app_fallback(session, intent=intent, context=context)
    return _delivery_result(intent)


def dispatch_phone_intent(
    session: Session,
    *,
    intent: NotificationDeliveryIntent,
    company_id: str,
    context: SessionContext | None,
):
    """Claim, send and finalize one SMS/WhatsApp intent.

    The caller holds the tenant, membership, parent and intent row locks and
    has already applied the shared recipient/lifecycle/channel fences.
    """

    from caseops_api.services.notification_delivery import (
        NOTIFICATION_DISPATCH_CLAIM_PREFIX,
        _delivery_result,
        _ensure_in_app_fallback,
        _record_delivery_event,
        record_notification_delivery_failure,
    )
    from caseops_api.services.provider_spend import (
        dispatch_provider_spend,
        release_provider_spend_in_session,
        reserve_provider_spend_in_session,
        settle_provider_spend,
    )

    channel = str(intent.channel)
    provider_key = PROVIDER_KEY_BY_CHANNEL[channel]
    admission = phone_admission(
        session,
        company_id=company_id,
        membership_id=intent.recipient_membership_id,
        channel=channel,
    )
    if not admission.allowed or admission.phone_number is None:
        return _block(session, intent=intent, reason=str(admission.reason), context=context)
    readiness = phone_channel_readiness(channel)
    reservation_id: str | None = None
    cost_minor: int | None = None
    if readiness.live:
        company = session.get(Company, company_id)
        recipient = (
            session.get(CompanyMembership, intent.recipient_membership_id)
            if intent.recipient_membership_id
            else None
        )
        if company is not None and recipient is not None and recipient.user is not None:
            fence_context = SessionContext(
                company=company, membership=recipient, user=recipient.user
            )
            blocked = paid_provider_block_reason(
                context=fence_context,
                provider=provider_key,
                base_url=_provider_base_url(channel),
                transport_is_mocked=phone_transport_is_injected(),
                scheduled_tenant_filter=True,
            )
            if blocked is not None:
                return _block(
                    session, intent=intent, reason=f"paid_provider_{blocked}", context=context
                )
        cost_minor = _verified_unit_cost(session, channel)
        if cost_minor is None:
            return _block(
                session, intent=intent, reason="provider_cost_unverified", context=context
            )
        try:
            reservation_id = reserve_provider_spend_in_session(
                session,
                company_id=company_id,
                actor_membership_id=intent.recipient_membership_id,
                provider_key=provider_key,
                operation_key=f"phone_{channel}_{intent.id}",
                amount_minor=cost_minor,
            )
        except HTTPException as exc:
            if exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
                return _block(
                    session, intent=intent, reason="provider_budget_exhausted", context=context
                )
            raise
        # Hold the budget through worker loss: a lost response is not a refund.
        dispatch_provider_spend(session, reservation_id=reservation_id, company_id=company_id)

    template, variables = template_for_intent(session, intent=intent)
    reference = template_reference(channel, template)
    claim_marker = f"{NOTIFICATION_DISPATCH_CLAIM_PREFIX}{secrets.token_hex(16)}"
    intent.attempts += 1
    attempt = intent.attempts
    intent.status = NotificationDeliveryStatus.SENT
    intent.provider_event_id = claim_marker
    intent.dispatch_owner = "provider_claim"
    intent.next_attempt_at = _now() + timedelta(minutes=5)
    intent.last_error_redacted = None
    session.add(intent)
    _record_delivery_event(
        session,
        intent=intent,
        event_type="delivery_claimed",
        status_value=str(intent.status),
        provider=provider_key,
        metadata={
            "attempt": attempt,
            "template": template,
            "provider_template_id": reference.get("provider_template_id"),
            "dlt_template_id": reference.get("dlt_template_id"),
            "transport": readiness.transport,
        },
    )
    intent_id = intent.id
    message = PhoneTemplateMessage(
        channel=channel,  # type: ignore[arg-type]
        to=admission.phone_number,
        template=template,  # type: ignore[arg-type]
        variables=variables,
        idempotency_key=sha256(f"{intent.idempotency_key}|{attempt}".encode()).hexdigest(),
    )
    # The claim commit is the disclosure winner point; no SQL transaction
    # remains open over provider I/O.
    session.commit()
    try:
        result = send_phone_template(message)
    except Exception as exc:  # noqa: BLE001 - provider/network boundary
        result = PhoneSendResult(
            outcome="outcome_unknown",
            provider=provider_key,  # type: ignore[arg-type]
            error_code="adapter_exception",
            detail=type(exc).__name__,
        )

    intent = session.scalar(
        select(NotificationDeliveryIntent)
        .where(
            NotificationDeliveryIntent.id == intent_id,
            NotificationDeliveryIntent.company_id == company_id,
        )
        .with_for_update(of=NotificationDeliveryIntent)
        .execution_options(populate_existing=True)
    )
    if intent is None:
        session.rollback()
        raise ValueError("Notification delivery intent not found.")
    attempt_metadata = {
        "attempt": attempt,
        "outcome": result.outcome,
        "http_status": result.http_status,
        "error_code": result.error_code,
        "template": template,
        "provider_template_id": reference.get("provider_template_id"),
        "dlt_template_id": reference.get("dlt_template_id"),
        "transport_provider": result.provider,
    }
    if intent.status != NotificationDeliveryStatus.SENT or intent.provider_event_id != claim_marker:
        _record_delivery_event(
            session,
            intent=intent,
            event_type="provider_callback_discarded",
            status_value=str(intent.status),
            provider=provider_key,
            provider_event_id=result.provider_message_id,
            applied_to_state=False,
            metadata=attempt_metadata,
        )
        session.commit()
        return _delivery_result(intent)
    _system_audit(
        session,
        intent=intent,
        action="notification_delivery.phone.attempted",
        result=AuditResult.SUCCESS if result.outcome == "accepted" else AuditResult.FAILED,
        provider=provider_key,
        phone_ref=phone_fingerprint(admission.phone_number),
        **attempt_metadata,
    )
    if result.outcome == "accepted":
        intent.provider_event_id = result.provider_message_id
        intent.dispatch_owner = "durable_intent"
        intent.next_attempt_at = None
        intent.updated_at = _now()
        _record_delivery_event(
            session,
            intent=intent,
            event_type="provider_accepted",
            status_value=str(intent.status),
            provider=provider_key,
            provider_event_id=(
                f"{result.provider_message_id}:accepted" if result.provider_message_id else None
            ),
            metadata=attempt_metadata,
        )
        if reservation_id is not None and cost_minor is not None:
            _record_phone_usage(
                session,
                company_id=company_id,
                membership_id=intent.recipient_membership_id,
                channel=channel,
                cost_minor=cost_minor,
                source_type="notification_delivery_intent",
                source_id=intent.id,
                matter_id=intent.matter_id,
            )
            settle_provider_spend(session, reservation_id=reservation_id)
        session.add(intent)
        session.commit()
        return _delivery_result(intent)
    intent.provider_event_id = None
    intent.dispatch_owner = "durable_intent"
    intent.next_attempt_at = None
    _record_delivery_event(
        session,
        intent=intent,
        event_type="provider_attempt_failed",
        status_value=result.outcome,
        provider=provider_key,
        error=result.detail or result.error_code,
        metadata=attempt_metadata,
    )
    if result.outcome == "outcome_unknown":
        # The provider may have accepted it. Never resend automatically; the
        # budget hold stays in place because the charge may be real.
        intent.status = NotificationDeliveryStatus.DEAD_LETTER
        intent.dead_letter_reason = "dispatch_provider_outcome_unknown"
        intent.last_error_redacted = "Notification provider outcome is unknown."
        intent.failed_at = _now()
        intent.updated_at = _now()
        session.add(intent)
        _ensure_in_app_fallback(session, intent=intent, context=context)
        session.commit()
        return _delivery_result(intent)
    release_provider_spend_in_session(
        session, reservation_id=reservation_id, confirmed_no_charge=True
    )
    intent.attempts -= 1
    outcome = record_notification_delivery_failure(
        session,
        intent=intent,
        raw_error=f"{provider_key} {result.error_code}",
        retryable=result.outcome == "retryable_rejection",
    )
    if outcome.dead_lettered:
        _ensure_in_app_fallback(session, intent=intent, context=context)
    session.commit()
    return outcome


# ---------------------------------------------------------- WhatsApp webhook


def _whatsapp_status_map() -> dict[str, str]:
    return {
        "delivered": NotificationDeliveryStatus.DELIVERED,
        "read": NotificationDeliveryStatus.DELIVERED,
        "failed": NotificationDeliveryStatus.BOUNCED,
    }


def apply_whatsapp_webhook(session: Session, *, payload: dict) -> dict[str, int]:
    """Apply STOP-style replies and delivery statuses from a verified webhook.

    A STOP reply to the shared CaseOps sender withdraws WhatsApp consent for
    that number in every workspace: the person asked this sender to stop.
    Each workspace's own audit trail records only its own withdrawal.
    """

    from caseops_api.services.notification_delivery import _record_delivery_event

    counts = {"opt_outs": 0, "statuses": 0}
    entries = payload.get("entry") if isinstance(payload, dict) else None
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes") if isinstance(entry, dict) else None
        for change in changes if isinstance(changes, list) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                text = ""
                if isinstance(message.get("text"), dict):
                    text = str(message["text"].get("body") or "")
                elif isinstance(message.get("button"), dict):
                    text = str(message["button"].get("text") or "")
                if " ".join(text.lower().split()) not in _STOP_WORDS:
                    continue
                sender = "+" + re.sub(r"\D", "", str(message.get("from") or ""))
                if not re.fullmatch(E164_PATTERN, sender):
                    continue
                contacts = session.scalars(
                    select(NotificationPhoneContact)
                    .where(
                        NotificationPhoneContact.phone_number == sender,
                        NotificationPhoneContact.whatsapp_opted_out_at.is_(None),
                    )
                    .with_for_update()
                ).all()
                for contact in contacts:
                    contact.whatsapp_opted_out_at = _now()
                    contact.opt_out_source = "whatsapp_stop_reply"
                    session.add(contact)
                    record_audit(
                        session,
                        company_id=contact.company_id,
                        actor_type=AuditActorType.SYSTEM,
                        actor_label="whatsapp-webhook",
                        action="notification_phone.consent_withdrawn",
                        target_type="notification_phone_contact",
                        target_id=contact.id,
                        metadata={
                            "channel": "whatsapp",
                            "source": "whatsapp_stop_reply",
                            "phone_ref": phone_fingerprint(contact.phone_number),
                        },
                    )
                    counts["opt_outs"] += 1
            for status_row in value.get("statuses") or []:
                if not isinstance(status_row, dict):
                    continue
                message_id = str(status_row.get("id") or "")[:200]
                state = str(status_row.get("status") or "")
                mapped = _whatsapp_status_map().get(state)
                if not message_id or mapped is None:
                    continue
                intent = session.scalar(
                    select(NotificationDeliveryIntent)
                    .where(
                        NotificationDeliveryIntent.provider_event_id == message_id,
                        NotificationDeliveryIntent.channel == "whatsapp",
                    )
                    .with_for_update()
                )
                if intent is None:
                    continue
                event_key = sha256(f"{message_id}|{state}".encode()).hexdigest()
                duplicate = session.scalar(
                    select(NotificationDeliveryEvent.id).where(
                        NotificationDeliveryEvent.company_id == intent.company_id,
                        NotificationDeliveryEvent.provider == "meta-whatsapp",
                        NotificationDeliveryEvent.idempotency_key == event_key,
                    )
                )
                if duplicate is not None:
                    continue
                applies = intent.status == NotificationDeliveryStatus.SENT
                if applies:
                    intent.status = mapped
                    if mapped == NotificationDeliveryStatus.DELIVERED:
                        intent.delivered_at = _now()
                    else:
                        intent.failed_at = _now()
                        intent.dead_letter_reason = "whatsapp_delivery_failed"
                    session.add(intent)
                errors = status_row.get("errors")
                error_code = (
                    errors[0].get("code")
                    if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                    else None
                )
                _record_delivery_event(
                    session,
                    intent=intent,
                    event_type=f"provider_status_{state}",
                    status_value=str(intent.status),
                    provider="meta-whatsapp",
                    idempotency_key=event_key,
                    applied_to_state=applies,
                    metadata={"error_code": error_code},
                )
                counts["statuses"] += 1
    session.flush()
    return counts


__all__ = [
    "PhoneAdmission",
    "apply_whatsapp_webhook",
    "confirm_phone_verification",
    "consent_active",
    "dispatch_phone_intent",
    "mask_phone_number",
    "normalize_phone_number",
    "phone_admission",
    "phone_channel_admin_status",
    "phone_contact_status",
    "remove_phone_contact",
    "set_phone_channel_consent",
    "start_phone_verification",
    "template_for_intent",
    "tenant_phone_channel_enabled",
]
