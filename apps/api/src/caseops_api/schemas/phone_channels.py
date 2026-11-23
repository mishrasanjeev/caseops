"""Typed contracts for SMS (MSG91) and WhatsApp (Meta Cloud API) delivery."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PhoneChannelLiteral = Literal["sms", "whatsapp"]
PhoneTemplateLiteral = Literal["hearing_reminder", "alert", "otp"]
PhoneSendOutcomeLiteral = Literal[
    # The provider accepted the message (not the same as handset delivery).
    "accepted",
    # The provider definitely did not accept it; a later retry cannot duplicate.
    "retryable_rejection",
    # The provider refused it; retrying the same request would be refused too.
    "permanent_rejection",
    # The request may have reached the provider; never resend automatically.
    "outcome_unknown",
]
E164_PATTERN = r"^\+[1-9][0-9]{7,14}$"
# The consent wording shown beside the opt-in control. Bump the version when
# the wording changes so each recorded consent names the text it accepted.
PHONE_CONSENT_TEXT_VERSION = "2026-11-22"


class PhoneTemplateMessage(BaseModel):
    """One template send. Variables are positional and deliberately short."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: PhoneChannelLiteral
    to: str = Field(pattern=E164_PATTERN)
    template: PhoneTemplateLiteral
    variables: tuple[str, ...] = Field(max_length=4)
    idempotency_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class PhoneSendResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: PhoneSendOutcomeLiteral
    provider: Literal["msg91", "meta-whatsapp", "mock"]
    provider_message_id: str | None = Field(default=None, max_length=255)
    http_status: int | None = None
    error_code: str | None = Field(default=None, max_length=64)
    detail: str | None = Field(default=None, max_length=240)


class PhoneChannelConsentRecord(BaseModel):
    channel: PhoneChannelLiteral
    opted_in: bool
    consent_at: datetime | None = None
    opted_out_at: datetime | None = None
    opt_out_source: str | None = None
    tenant_enabled: bool
    provider_ready: bool
    deliverable: bool
    blocked_reason: str | None = None


class PhoneContactStatusResponse(BaseModel):
    phone_masked: str | None = None
    verified: bool = False
    verified_at: datetime | None = None
    verification_pending: bool = False
    verification_channel: PhoneChannelLiteral | None = None
    verification_expires_at: datetime | None = None
    consent_text_version: str = PHONE_CONSENT_TEXT_VERSION
    channels: dict[PhoneChannelLiteral, PhoneChannelConsentRecord]


class PhoneVerificationStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone_number: str = Field(min_length=8, max_length=24)
    channel: PhoneChannelLiteral = "sms"


class PhoneVerificationConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")


class PhoneConsentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: PhoneChannelLiteral
    opted_in: bool
    consent_text_version: Literal["2026-11-22"] | None = None


class PhoneChannelAdminRecord(BaseModel):
    channel: PhoneChannelLiteral
    provider: Literal["msg91", "meta-whatsapp"]
    tenant_enabled: bool
    provider_ready: bool
    kill_switch_active: bool
    transport: Literal["mock", "live"]
    missing_configuration: list[str] = Field(default_factory=list)
    not_ready_reason: str | None = None
    opted_in_members: int = 0


class PhoneChannelAdminResponse(BaseModel):
    channels: dict[PhoneChannelLiteral, PhoneChannelAdminRecord]

