"""HTTP adapters for SMS (MSG91 Flow API, DLT) and WhatsApp (Meta Cloud API).

Each adapter makes exactly one HTTP attempt and classifies the result. Retries
are owned by the durable notification intent, never by this module, so a
reminder cannot be sent twice by a hidden transport retry:

- ``accepted``            the provider returned a message id;
- ``retryable_rejection`` the provider definitely did not take the message
                          (connection never established, HTTP 429, or a
                          documented throughput code);
- ``permanent_rejection`` the provider refused it and would refuse it again;
- ``outcome_unknown``     the request may have reached the provider (read
                          timeout, dropped connection, 5xx); the caller must
                          not resend it automatically.

Neither provider exposes a client idempotency key on these endpoints, so the
caller's claim fence plus the no-resend rule for ``outcome_unknown`` is what
prevents a duplicate send.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import httpx

from caseops_api.core.redaction import redact_provider_error
from caseops_api.core.settings import get_settings, is_non_local_env
from caseops_api.schemas.phone_channels import (
    PhoneChannelLiteral,
    PhoneSendResult,
    PhoneTemplateMessage,
)

logger = logging.getLogger(__name__)

PHONE_CHANNELS: tuple[PhoneChannelLiteral, ...] = ("sms", "whatsapp")
PROVIDER_KEY_BY_CHANNEL: dict[str, str] = {"sms": "msg91", "whatsapp": "meta-whatsapp"}
# Meta Cloud API throughput and pair-rate codes: the message was not accepted.
_META_RETRYABLE_CODES = frozenset({4, 80007, 130429, 131056})
_META_AUTH_CODES = frozenset({0, 190})

# Test seam: an injected transport replaces real network I/O. Production code
# never sets it; ``phone_transport_is_injected`` lets the paid-provider fence
# distinguish an in-process fake from a leaked live configuration.
_injected_transport: httpx.BaseTransport | None = None


@contextmanager
def use_phone_transport(transport: httpx.BaseTransport) -> Iterator[None]:
    global _injected_transport
    previous = _injected_transport
    _injected_transport = transport
    try:
        yield
    finally:
        _injected_transport = previous


def phone_transport_is_injected() -> bool:
    return _injected_transport is not None


@dataclass(frozen=True, slots=True)
class PhoneChannelReadiness:
    channel: str
    provider_key: str
    ready: bool
    transport: str
    kill_switch_active: bool
    missing: tuple[str, ...]
    reason: str | None

    @property
    def live(self) -> bool:
        return self.transport == "live"


def _missing_configuration(channel: str) -> list[str]:
    settings = get_settings()
    if channel == "sms":
        required = {
            "CASEOPS_MSG91_AUTH_KEY": settings.msg91_auth_key,
            "CASEOPS_MSG91_SENDER_ID": settings.msg91_sender_id,
            "CASEOPS_MSG91_HEARING_TEMPLATE_ID": settings.msg91_hearing_template_id,
            "CASEOPS_MSG91_HEARING_DLT_TEMPLATE_ID": settings.msg91_hearing_dlt_template_id,
            "CASEOPS_MSG91_ALERT_TEMPLATE_ID": settings.msg91_alert_template_id,
            "CASEOPS_MSG91_ALERT_DLT_TEMPLATE_ID": settings.msg91_alert_dlt_template_id,
            "CASEOPS_MSG91_OTP_TEMPLATE_ID": settings.msg91_otp_template_id,
            "CASEOPS_MSG91_OTP_DLT_TEMPLATE_ID": settings.msg91_otp_dlt_template_id,
        }
    else:
        required = {
            "CASEOPS_WHATSAPP_ACCESS_TOKEN": settings.whatsapp_access_token,
            "CASEOPS_WHATSAPP_PHONE_NUMBER_ID": settings.whatsapp_phone_number_id,
            "CASEOPS_WHATSAPP_HEARING_TEMPLATE_NAME": settings.whatsapp_hearing_template_name,
            "CASEOPS_WHATSAPP_ALERT_TEMPLATE_NAME": settings.whatsapp_alert_template_name,
            "CASEOPS_WHATSAPP_OTP_TEMPLATE_NAME": settings.whatsapp_otp_template_name,
            "CASEOPS_WHATSAPP_APP_SECRET": settings.whatsapp_app_secret,
        }
    return [name for name, value in required.items() if not str(value or "").strip()]


def phone_channel_readiness(channel: str) -> PhoneChannelReadiness:
    """Return whether the platform may send on ``channel`` at all.

    Fails closed: the kill switch wins over everything, a disabled provider is
    not ready, every credential/template value must be present, and mock
    transport (no network) is honoured only in local environments so a
    misconfigured deployment can never report a fake send as delivered.
    """

    if channel not in PHONE_CHANNELS:
        raise ValueError(f"Unsupported phone channel: {channel}")
    settings = get_settings()
    transport = settings.phone_notification_transport
    enabled = settings.msg91_enabled if channel == "sms" else settings.whatsapp_enabled
    missing = tuple(_missing_configuration(channel))
    reason: str | None = None
    if settings.phone_notifications_kill_switch:
        reason = "kill_switch_active"
    elif not enabled:
        reason = "provider_disabled"
    elif missing:
        reason = "provider_incomplete"
    elif transport == "mock" and is_non_local_env(settings.env):
        reason = "mock_transport_outside_local"
    return PhoneChannelReadiness(
        channel=channel,
        provider_key=PROVIDER_KEY_BY_CHANNEL[channel],
        ready=reason is None,
        transport=transport,
        kill_switch_active=settings.phone_notifications_kill_switch,
        missing=missing,
        reason=reason,
    )


def template_reference(channel: str, template: str) -> dict[str, str | None]:
    """Configured provider template identity, recorded with every attempt."""

    settings = get_settings()
    if channel == "sms":
        template_id, dlt_id = {
            "hearing_reminder": (
                settings.msg91_hearing_template_id,
                settings.msg91_hearing_dlt_template_id,
            ),
            "alert": (settings.msg91_alert_template_id, settings.msg91_alert_dlt_template_id),
            "otp": (settings.msg91_otp_template_id, settings.msg91_otp_dlt_template_id),
        }[template]
        return {
            "provider_template_id": template_id,
            "dlt_template_id": dlt_id,
            "sender_id": settings.msg91_sender_id,
        }
    name = {
        "hearing_reminder": settings.whatsapp_hearing_template_name,
        "alert": settings.whatsapp_alert_template_name,
        "otp": settings.whatsapp_otp_template_name,
    }[template]
    return {"provider_template_id": name, "language": settings.whatsapp_template_language}


def msg91_request(message: PhoneTemplateMessage) -> tuple[str, dict[str, str], dict]:
    settings = get_settings()
    reference = template_reference("sms", message.template)
    recipient: dict[str, str] = {"mobiles": message.to.removeprefix("+")}
    # The MSG91 template registered against the DLT template must name its
    # variables VAR1..VARn in this order.
    for index, value in enumerate(message.variables, start=1):
        recipient[f"VAR{index}"] = value
    url = f"{settings.msg91_api_base_url.rstrip('/')}/api/v5/flow"
    headers = {
        "authkey": str(settings.msg91_auth_key or ""),
        "accept": "application/json",
        "content-type": "application/json",
    }
    body = {
        "template_id": reference["provider_template_id"],
        "short_url": "0",
        "realTimeResponse": "1",
        "recipients": [recipient],
    }
    return url, headers, body


def whatsapp_request(message: PhoneTemplateMessage) -> tuple[str, dict[str, str], dict]:
    settings = get_settings()
    reference = template_reference("whatsapp", message.template)
    parameters = [{"type": "text", "text": value} for value in message.variables]
    components: list[dict] = [{"type": "body", "parameters": parameters}]
    if message.template == "otp":
        # Copy-code authentication templates repeat the code on the URL button.
        components.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": "0",
                "parameters": [{"type": "text", "text": message.variables[0]}],
            }
        )
    url = (
        f"{settings.whatsapp_api_base_url.rstrip('/')}/{settings.whatsapp_api_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )
    headers = {
        "Authorization": f"Bearer {settings.whatsapp_access_token or ''}",
        "Content-Type": "application/json",
    }
    body = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": message.to,
        "type": "template",
        "template": {
            "name": reference["provider_template_id"],
            "language": {"code": settings.whatsapp_template_language},
            "components": components,
        },
    }
    return url, headers, body


def _json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _detail(value: object) -> str:
    return redact_provider_error(value)[:240]


def classify_msg91_response(response: httpx.Response) -> PhoneSendResult:
    payload = _json(response)
    status_code = response.status_code
    if status_code == 200 and payload.get("type") == "success" and payload.get("message"):
        return PhoneSendResult(
            outcome="accepted",
            provider="msg91",
            provider_message_id=str(payload["message"])[:255],
            http_status=status_code,
        )
    if status_code == 429:
        outcome, code = "retryable_rejection", "provider_rate_limited"
    elif status_code in {401, 403}:
        outcome, code = "permanent_rejection", "provider_authentication"
    elif status_code >= 500:
        outcome, code = "outcome_unknown", "provider_server_error"
    else:
        outcome, code = "permanent_rejection", "provider_rejected"
    return PhoneSendResult(
        outcome=outcome,
        provider="msg91",
        http_status=status_code,
        error_code=code,
        detail=_detail(payload.get("message") or f"msg91 {status_code}"),
    )


def classify_whatsapp_response(response: httpx.Response) -> PhoneSendResult:
    payload = _json(response)
    status_code = response.status_code
    messages = payload.get("messages")
    if (
        status_code == 200
        and isinstance(messages, list)
        and messages
        and isinstance(messages[0], dict)
        and messages[0].get("id")
    ):
        return PhoneSendResult(
            outcome="accepted",
            provider="meta-whatsapp",
            provider_message_id=str(messages[0]["id"])[:255],
            http_status=status_code,
        )
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    raw_code = error.get("code")
    code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
    if status_code == 429 or code in _META_RETRYABLE_CODES:
        outcome = "retryable_rejection"
    elif code in _META_AUTH_CODES or status_code in {401, 403}:
        outcome = "permanent_rejection"
    elif status_code >= 500:
        outcome = "outcome_unknown"
    else:
        outcome = "permanent_rejection"
    return PhoneSendResult(
        outcome=outcome,
        provider="meta-whatsapp",
        http_status=status_code,
        error_code=f"meta_{code}" if code is not None else f"http_{status_code}",
        detail=_detail(error.get("message") or f"whatsapp {status_code}"),
    )


def send_phone_template(message: PhoneTemplateMessage) -> PhoneSendResult:
    """Send one template message; one HTTP attempt, never retried here."""

    settings = get_settings()
    readiness = phone_channel_readiness(message.channel)
    if not readiness.ready:
        raise ValueError(f"Phone channel is not ready: {readiness.reason}")
    if settings.phone_notification_transport == "mock" and _injected_transport is None:
        if message.template == "otp" and not is_non_local_env(settings.env):
            # Local development only: there is no handset, so surface the code
            # in the local log. Mock transport is refused outside local envs.
            logger.warning(
                "Local mock %s verification code: %s", message.channel, message.variables[0]
            )
        return PhoneSendResult(
            outcome="accepted",
            provider="mock",
            provider_message_id=f"mock-{message.idempotency_key[:24]}",
        )
    build = msg91_request if message.channel == "sms" else whatsapp_request
    classify = classify_msg91_response if message.channel == "sms" else classify_whatsapp_response
    provider = "msg91" if message.channel == "sms" else "meta-whatsapp"
    url, headers, body = build(message)
    with httpx.Client(
        transport=_injected_transport,
        timeout=settings.phone_provider_timeout_seconds,
        follow_redirects=False,
    ) as client:
        try:
            response = client.post(url, headers=headers, json=body)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # The connection was never established, so nothing was sent.
            return PhoneSendResult(
                outcome="retryable_rejection",
                provider=provider,
                error_code="connect_failed",
                detail=_detail(type(exc).__name__),
            )
        except httpx.HTTPError as exc:
            return PhoneSendResult(
                outcome="outcome_unknown",
                provider=provider,
                error_code="transport_outcome_unknown",
                detail=_detail(type(exc).__name__),
            )
    if response.is_redirect:
        return PhoneSendResult(
            outcome="permanent_rejection",
            provider=provider,
            http_status=response.status_code,
            error_code="provider_contract_changed",
            detail="Provider redirected outside the pinned API contract.",
        )
    return classify(response)


__all__ = [
    "PHONE_CHANNELS",
    "PROVIDER_KEY_BY_CHANNEL",
    "PhoneChannelReadiness",
    "classify_msg91_response",
    "classify_whatsapp_response",
    "msg91_request",
    "phone_channel_readiness",
    "phone_transport_is_injected",
    "send_phone_template",
    "template_reference",
    "use_phone_transport",
    "whatsapp_request",
]
